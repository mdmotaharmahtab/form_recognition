```python
import re
from bisect import bisect_left, bisect_right
from typing import List, Dict, Tuple


_CODE_TOKEN_RE = re.compile(r"^\[[A-Za-z0-9][A-Za-z0-9_]{1,40}\]$")
_BRACKET_ANY_RE = re.compile(r"^\[.*\]$")
_DATEISH_RE = re.compile(
    r"(?i)\b(\d{1,2}[-/][A-Za-z]{3}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b"
)
_TIMEISH_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_MOSTLY_PUNCT_RE = re.compile(r"^[\W_]+$")


def extract(pages):
    out: List[Dict[str, object]] = []
    seen = set()
    current_form: str = ""

    for page_index0, lines in pages:
        if not lines:
            continue

        width = max((getattr(ln, "x1", 0.0) for ln in lines), default=0.0) or 1.0
        height = max((getattr(ln, "y1", 0.0) for ln in lines), default=0.0) or 1.0
        page1 = page_index0 + 1

        footer_y = height - max(55.0, 0.085 * height)

        def is_footer_line(ln) -> bool:
            if ln.y0 < footer_y:
                return False
            if getattr(ln, "size", 0.0) > 13.0:
                return False
            t = (ln.text or "").strip()
            if not t:
                return True
            if len(t) > 55:
                return False
            digitish = sum(ch.isdigit() for ch in t)
            return (digitish >= 1) and (ln.x0 > width * 0.20)

        # Remove footer furniture from consideration everywhere
        core_lines = [ln for ln in lines if not is_footer_line(ln) and (ln.text or "").strip()]

        # Form title (persist across pages)
        title = _detect_form_title(core_lines, width)
        if title:
            current_form = title

        # Code anchors (anywhere, not just left margin)
        code_lines = _find_code_lines(core_lines, width, height)

        # Structural "navigation table" (schedule/index-like) pages: do not emit fields
        if _looks_like_navigation_table(core_lines, width, height, code_lines):
            continue

        # Structural "change history / revision log" pages: do not emit fields
        if _looks_like_revision_log_page(core_lines, width, height, code_lines):
            continue

        fields: List[str] = []

        # Table header fields: only when there's evidence the page is an annotated form/grid
        if _has_grid_evidence(core_lines, width, height, code_lines):
            fields.extend(_extract_table_header_fields(core_lines, width, height))

        # Code-anchored labels (primary)
        fields.extend(_extract_fields_via_codes(core_lines, width, height, code_lines))

        # Post-filter: remove heading-like fragments that often have codes but are not data-entry fields
        fields = _post_filter_heading_like(fields, core_lines, width, height)

        # Emit
        form_name = (current_form or "").strip()
        for f in _dedup_preserve_order(_clean_field_names(fields)):
            if not f:
                continue
            key = (form_name, f, page1)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": f, "page": page1})

    return out


def _detect_form_title(lines, width: float) -> str:
    # Prefer a non-black title near top-left, medium-large.
    cands = []
    for ln in lines:
        t = (ln.text or "").strip()
        if not t or _is_bracket_line(t):
            continue
        if ln.y0 > max(220.0, 0.30 * 800.0):  # tolerant; absolute cap still ok
            continue
        if ln.x0 > min(240.0, width * 0.38):
            continue
        if not getattr(ln, "non_black", False):
            continue
        sz = getattr(ln, "size", 0.0)
        if sz < 13.0 or sz > 21.5:
            continue
        if _is_mostly_numeric(t):
            continue
        if len(t) < 3:
            continue
        cands.append(ln)

    if not cands:
        return ""
    cands.sort(key=lambda l: (l.y0, -getattr(l, "size", 0.0), l.x0))
    return (cands[0].text or "").strip()


def _find_code_lines(lines, width: float, height: float):
    # Red bracket tokens; exclude extreme top/bottom to avoid stray annotations.
    top_cut = max(35.0, 0.04 * height)
    bot_cut = height - max(75.0, 0.10 * height)
    codes = []
    for ln in lines:
        t = (ln.text or "").strip()
        if not t:
            continue
        if not getattr(ln, "non_black", False):
            continue
        if not _CODE_TOKEN_RE.match(t):
            continue
        if ln.y0 < top_cut or ln.y0 > bot_cut:
            continue
        codes.append(ln)
    return codes


def _looks_like_navigation_table(lines, width: float, height: float, code_lines) -> bool:
    # Structural: small bold header row near top, many small blue row labels in a column, and no codes.
    if code_lines:
        return False

    header_band = [
        ln
        for ln in lines
        if (110.0 <= ln.y0 <= 155.0)
        and (8.0 <= getattr(ln, "size", 0.0) <= 10.5)
        and (not getattr(ln, "non_black", False))
        and getattr(ln, "bold", False)
        and (ln.text or "").strip()
        and not _is_bracket_line((ln.text or ""))
        and not _is_mostly_numeric((ln.text or ""))
    ]
    if len(header_band) < 5:
        return False

    xs = sorted(ln.x0 for ln in header_band)
    spread = xs[-1] - xs[0]
    if spread < width * 0.55:
        return False

    blue_rows = [
        ln
        for ln in lines
        if getattr(ln, "non_black", False)
        and (8.0 <= getattr(ln, "size", 0.0) <= 10.5)
        and (ln.y0 >= 155.0)
        and (ln.y0 <= height - max(120.0, 0.15 * height))
        and (ln.text or "").strip()
        and not _is_bracket_line((ln.text or ""))
    ]
    if len(blue_rows) < 10:
        return False

    # Blue rows tend to sit in a mid-right "label" column
    x_blue = [ln.x0 for ln in blue_rows]
    if not x_blue:
        return False
    if (max(x_blue) - min(x_blue)) < width * 0.20:
        # Narrow column of blue labels
        pass
    else:
        return False

    # Also see a numeric-ish column nearby (page numbers)
    numeric_col = [
        ln
        for ln in lines
        if (8.0 <= getattr(ln, "size", 0.0) <= 10.5)
        and (not getattr(ln, "non_black", False))
        and (ln.y0 >= 155.0)
        and (ln.y0 <= height - max(120.0, 0.15 * height))
        and _is_mostly_numeric((ln.text or "").strip())
        and (width * 0.20 <= ln.x0 <= width * 0.45)
    ]
    return len(numeric_col) >= 6


def _looks_like_revision_log_page(lines, width: float, height: float, code_lines) -> bool:
    # Structural: title-like colored line near top-left, dense small black table, date-like entries, no codes.
    if code_lines:
        return False

    title = _detect_form_title(lines, width)
    if not title:
        return False

    small_black = [
        ln
        for ln in lines
        if (not getattr(ln, "non_black", False))
        and (getattr(ln, "size", 0.0) <= 10.5)
        and (ln.text or "").strip()
        and not _is_bracket_line((ln.text or ""))
        and (ln.y0 >= 160.0)
        and (ln.y0 <= height - max(120.0, 0.15 * height))
    ]
    if len(small_black) < 35:
        return False

    # Find a header row band: several short-ish entries at nearly same y, spread across page
    band = [ln for ln in small_black if 170.0 <= ln.y0 <= 270.0 and len((ln.text or "").strip()) <= 30]
    if len(band) < 4:
        return False

    band.sort(key=lambda l: l.y0)
    # Cluster by y
    y_vals = [ln.y0 for ln in band]
    best_cluster = []
    for ln in band:
        cluster = [x for x in band if abs(x.y0 - ln.y0) <= 6.0]
        if len(cluster) > len(best_cluster):
            best_cluster = cluster

    if len(best_cluster) < 4:
        return False

    xs = sorted(ln.x0 for ln in best_cluster)
    if (xs[-1] - xs[0]) < width * 0.45:
        return False

    # Date-like values appear frequently in revision logs
    dateish = 0
    for ln in small_black:
        t = (ln.text or "").strip()
        if _DATEISH_RE.search(t) or _TIMEISH_RE.search(t):
            dateish += 1
    if dateish < 3:
        return False

    return True


def _has_grid_evidence(lines, width: float, height: float, code_lines) -> bool:
    # Prefer to extract table headers only when the page looks like an annotated form/grid.
    if len(code_lines) >= 1:
        return True

    # Secondary evidence: underscores/blanks or checkbox-like glyphs
    for ln in lines:
        t = (ln.text or "").strip()
        if not t or _is_bracket_line(t):
            continue
        if "____" in t or "___" in t:
            return True
        if _contains_checkbox_glyph(t):
            return True
    return False


def _extract_table_header_fields(lines, width: float, height: float) -> List[str]:
    # Multi-column header band near the top; join wrapped header lines only.
    band = []
    for ln in lines:
        if ln.y0 < 90.0 or ln.y0 > 175.0:
            continue
        t = (ln.text or "").strip()
        if not t or _is_bracket_line(t):
            continue
        if getattr(ln, "non_black", False):
            continue
        sz = getattr(ln, "size", 0.0)
        if not (8.5 <= sz <= 12.8):
            continue
        if len(t) == 1 and _is_bullet_char(t):
            continue
        if _is_mostly_numeric(t):
            continue
        # Avoid value-like entries in the header band
        if _looks_like_filled_value(t):
            continue
        band.append(ln)

    if len(band) < 2:
        return []

    band.sort(key=lambda l: (l.x0, l.y0))

    # Cluster into columns by x
    col_clusters = []
    for ln in band:
        placed = False
        for col in col_clusters:
            if abs(col[0].x0 - ln.x0) <= 18.0:
                col.append(ln)
                placed = True
                break
        if not placed:
            col_clusters.append([ln])

    col_xs = sorted(c[0].x0 for c in col_clusters)
    if len(col_clusters) < 2:
        return []
    if (col_xs[-1] - col_xs[0]) < width * 0.40:
        return []

    fields = []
    for col in col_clusters:
        col.sort(key=lambda l: l.y0)
        # Keep only compact run from the topmost line in this column
        y0_min = col[0].y0
        kept = [ln for ln in col if (ln.y0 - y0_min) <= 28.0 and not _looks_like_filled_value((ln.text or "").strip())]
        txt = " ".join((ln.text or "").strip() for ln in kept if (ln.text or "").strip())
        txt = _normalize_spaces(txt)
        if txt and not _looks_like_filled_value(txt) and not _is_mostly_numeric(txt):
            fields.append(txt)

    return fields


def _extract_fields_via_codes(lines, width: float, height: float, code_lines) -> List[str]:
    if not code_lines:
        return []

    # Candidate label lines: black, non-bracket, non-footer already removed
    black = [
        ln
        for ln in lines
        if (not getattr(ln, "non_black", False))
        and (ln.text or "").strip()
        and not _is_bracket_line((ln.text or ""))
        and not _is_mostly_numeric((ln.text or ""))
        and not _looks_like_filled_value((ln.text or "").strip())
    ]
    if not black:
        return []

    black.sort(key=lambda l: (l.y0, l.x0))
    black_y = [ln.y0 for ln in black]

    results: List[str] = []

    for code_ln in code_lines:
        y0 = code_ln.y0
        # Window around code
        y_min = y0 - 170.0
        y_max = y0 + 95.0
        i0 = bisect_left(black_y, y_min)
        i1 = bisect_right(black_y, y_max)

        window = []
        for ln in black[i0:i1]:
            if _acceptable_label_geometry(code_ln, ln, width):
                window.append(ln)

        if not window:
            continue

        best = max(window, key=lambda ln: _label_score_near_code(code_ln, ln))
        if _label_score_near_code(code_ln, best) < 1.5:
            continue

        merged = _merge_wrapped_label(best, window)
        merged = _normalize_spaces(merged)
        if not merged:
            continue
        if _is_bracket_line(merged) or _looks_like_filled_value(merged) or _is_mostly_numeric(merged):
            continue
        results.append(merged)

    return results


def _acceptable_label_geometry(code_ln, label_ln, width: float) -> bool:
    # Allow label to be near code horizontally, either to left or right.
    cx0, cx1 = code_ln.x0, getattr(code_ln, "x1", code_ln.x0)
    lx0, lx1 = label_ln.x0, getattr(label_ln, "x1", label_ln.x0)

    # Horizontal "near" based on overlap / distance between spans
    left_gap = cx0 - lx1
    right_gap = lx0 - cx1
    gap = min(abs(left_gap), abs(right_gap), abs(lx0 - cx0))
    if gap > max(260.0, 0.38 * width):
        return False

    # Prefer labels that are not far to the right of the code on wide pages
    if (label_ln.x0 - code_ln.x0) > max(340.0, 0.50 * width):
        return False

    return True


def _label_score_near_code(code_ln, ln) -> float:
    t = (ln.text or "").strip()
    dy = ln.y0 - code_ln.y0

    # distance between x starts is a weak signal; allow both sides
    dx = abs(ln.x0 - code_ln.x0)

    s = 0.0
    if dy <= 0:
        s += 10.0 - (abs(dy) * 0.10)
    else:
        s += 6.0 - (dy * 0.14)

    s += max(0.0, 6.0 - (dx * 0.02))

    if getattr(ln, "bold", False):
        s += 2.0
    if t.endswith("?"):
        s += 6.0
    if t.endswith(":"):
        s += 2.0

    # Prefer label-like lengths
    L = len(t)
    if 3 <= L <= 90:
        s += 3.0
    elif L > 150:
        s -= 6.0

    # Penalize obvious prose paragraph lines (very long, sentence-like)
    if L > 120 and (t.count(".") + t.count(";") + t.count(",")) >= 2:
        s -= 4.0

    # Penalize lines with strong value-like patterns (extra guard)
    if _looks_like_filled_value(t):
        s -= 10.0

    return s


def _merge_wrapped_label(seed, window) -> str:
    # Merge nearby lines aligned to seed.
    x_ref = seed.x0
    size_ref = getattr(seed, "size", 0.0)

    candidates = [
        ln
        for ln in window
        if abs(ln.x0 - x_ref) <= 16.0 and abs(getattr(ln, "size", 0.0) - size_ref) <= 2.5
    ]
    candidates.sort(key=lambda l: l.y0)

    seed_idx = None
    for i, ln in enumerate(candidates):
        if ln is seed:
            seed_idx = i
            break
    if seed_idx is None:
        return (seed.text or "").strip()

    run = [candidates[seed_idx]]

    # Up
    i = seed_idx - 1
    while i >= 0:
        prev = candidates[i]
        cur = run[0]
        if (cur.y0 - prev.y0) > 24.0:
            break
        # Avoid merging in unrelated header fragments that are value-like
        if _looks_like_filled_value((prev.text or "").strip()):
            break
        run.insert(0, prev)
        i -= 1

    # Down
    i = seed_idx + 1
    while i < len(candidates):
        nxt = candidates[i]
        cur = run[-1]
        if (nxt.y0 - cur.y0) > 24.0:
            break
        if _looks_like_filled_value((nxt.text or "").strip()):
            break
        run.append(nxt)
        i += 1

    return " ".join((ln.text or "").strip() for ln in run if (ln.text or "").strip())


def _post_filter_heading_like(fields: List[str], lines, width: float, height: float) -> List[str]:
    if not fields:
        return fields

    # Map text -> best matching line for style/position checks
    by_text = {}
    for ln in lines:
        t = _normalize_spaces((ln.text or "").strip())
        if not t:
            continue
        if t not in by_text:
            by_text[t] = ln
        else:
            # Keep the larger/more prominent one
            if getattr(ln, "size", 0.0) > getattr(by_text[t], "size", 0.0):
                by_text[t] = ln

    # If there are question-like fields, treat short bold headers above them as non-fields.
    has_question = any(f.endswith("?") for f in fields)

    filtered = []
    for f in fields:
        ln = by_text.get(_normalize_spaces(f))
        if ln:
            sz = getattr(ln, "size", 0.0)
            bold = getattr(ln, "bold", False)
            t = f.strip()

            # Large instrument/section headers often appear as bold 12+ without punctuation.
            if bold and sz >= 12.0 and (not t.endswith("?")) and (not t.endswith(":")) and len(t) <= 40:
                continue

            # Subheadings near the top-left: short bold phrase without punctuation,
            # immediately preceding real questions on the same page.
            if has_question and bold and sz >= 10.5 and ln.y0 <= 320.0 and ln.x0 <= width * 0.45:
                if (not t.endswith("?")) and (not t.endswith(":")) and (len(t.split()) <= 5) and len(t) <= 45:
                    continue

        filtered.append(f)

    return filtered


def _looks_like_filled_value(t: str) -> bool:
    s = (t or "").strip()
    if not s:
        return False

    if _DATEISH_RE.search(s) or _TIMEISH_RE.search(s):
        return True

    # High digit ratio tends to be values (IDs, page counts, dates not caught)
    alnum = sum(ch.isalnum() for ch in s)
    digits = sum(ch.isdigit() for ch in s)
    if alnum >= 6 and digits / max(1, alnum) >= 0.55:
        return True

    # Looks like a person list / attribution line (often not a field label)
    if len(s) > 55 and (s.count(";") >= 2 or s.count(",") >= 4):
        return True

    return False


def _contains_checkbox_glyph(t: str) -> bool:
    # Common checkbox glyphs in extracted text
    glyphs = {"□", "☐", "▢", "▣", "■", "☑", "✓", "✔"}
    return any(ch in glyphs for ch in (t or ""))


def _clean_field_names(fields: List[str]) -> List[str]:
    cleaned = []
    for f in fields:
        t = _normalize_spaces((f or "").strip())
        if not t:
            continue
        if _is_bracket_line(t):
            continue
        if _MOSTLY_PUNCT_RE.match(t):
            continue
        if _is_mostly_numeric(t):
            continue
        if len(t) == 1 and _is_bullet_char(t):
            continue
        # strip trailing stray hyphens from wrapped headers
        t = re.sub(r"\s+-\s*$", "", t).strip()
        if not t:
            continue
        cleaned.append(t)
    return cleaned


def _dedup_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _is_bracket_line(t: str) -> bool:
    t = (t or "").strip()
    return bool(_BRACKET_ANY_RE.match(t))


def _is_mostly_numeric(t: str) -> bool:
    s = (t or "").strip()
    if not s:
        return True
    alnum = sum(ch.isalnum() for ch in s)
    digits = sum(ch.isdigit() for ch in s)
    if alnum == 0:
        return True
    return digits >= max(1, int(0.80 * alnum))


def _is_bullet_char(ch: str) -> bool:
    # Keep as "bullet-like"; do not include checkbox glyphs here.
    return ch in {"•", "·", "‣", "▪", "●", "○", "◯", "–", "-", "•"}
```
