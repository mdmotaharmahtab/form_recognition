```python
# Observed layout: an "Annotated CRF" where form titles are blue (~16–17pt) near top-left,
# field machine annotations are red bracket codes (e.g., [VISDAT], [RPF3]) near the label area,
# and some forms are grid/table pages whose data-entry fields are the black column headers near y~124.
# Strategy: carry forward the latest top-left blue title as form_name; extract field labels by
# (1) anchoring on left-margin red bracket codes and grabbing the best nearby black label lines,
# (2) extracting multi-column table header labels near the top band; avoid bracketed tech lines and options.

import re
from typing import List, Dict, Tuple, Optional


_CODE_TOKEN_RE = re.compile(r"^\[[A-Za-z0-9][A-Za-z0-9_]{1,40}\]$")
_BRACKET_ANY_RE = re.compile(r"^\[.*\]$")


def extract(pages):
    out: List[Dict[str, object]] = []
    seen = set()

    current_form: str = ""

    for page_index0, lines in pages:
        if not lines:
            continue

        width = max((ln.x1 for ln in lines), default=0.0) or 1.0
        height = max((ln.y1 for ln in lines), default=0.0) or 1.0

        # Exclude obvious footers (page number furniture near bottom center).
        footer_ys = height - 70.0

        def is_footer_line(ln) -> bool:
            if ln.y0 < footer_ys:
                return False
            if ln.size > 13.0:
                return False
            # Structural: bottom-ish, mostly numeric-ish, short.
            t = ln.text.strip()
            if not t:
                return True
            if len(t) > 40:
                return False
            digitish = sum(ch.isdigit() for ch in t)
            return digitish >= 1 and ln.x0 > width * 0.25

        # Detect and set/update form title from prominent top-left blue line(s).
        title = _detect_form_title(lines, width)

        # Identify page templates that are not data-entry forms (index/schedule/change history).
        # If unsure, we do NOT skip; these signatures are intentionally specific.
        if _is_index_like_page(lines, width) or _is_schedule_table_page(lines, width) or _is_change_history_page(lines, width):
            # Still allow title update if it exists, but do not extract fields.
            if title:
                current_form = title
            continue

        if title:
            current_form = title

        # Extract table header fields (multi-column top band).
        fields: List[str] = []
        header_fields = _extract_table_header_fields(lines, width, height)
        fields.extend(header_fields)

        # Extract fields via code anchors (left-margin red bracket codes).
        code_fields = _extract_fields_via_left_codes(lines, width, height)
        fields.extend(code_fields)

        # If no codes and no headers, do a very conservative fallback for "question + option list" pages.
        if not fields:
            fields.extend(_extract_question_with_optionlist_fallback(lines, width, height))

        # Emit, with de-dup on the same page.
        page1 = page_index0 + 1
        for f in _dedup_preserve_order(_clean_field_names(fields)):
            if not f:
                continue
            form_name = (current_form or "").strip()
            key = (form_name, f, page1)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": f, "page": page1})

    return out


def _detect_form_title(lines, width: float) -> str:
    # Prefer a non-black (blue) title near top-left, medium-large (~14–20pt).
    cands = []
    for ln in lines:
        t = ln.text.strip()
        if not t or _is_bracket_line(t):
            continue
        if ln.y0 > 220.0:
            continue
        if ln.x0 > min(220.0, width * 0.35):
            continue
        if not ln.non_black:
            continue
        if ln.size < 13.5 or ln.size > 20.5:
            continue
        # Avoid very short numeric-only titles.
        if _is_mostly_numeric(t):
            continue
        cands.append(ln)

    if not cands:
        return ""

    # Pick the earliest (topmost), break ties by larger size.
    cands.sort(key=lambda l: (l.y0, -l.size, l.x0))
    return cands[0].text.strip()


def _is_index_like_page(lines, width: float) -> bool:
    # Index/TOC pages in samples: many blue (~15pt) lines aligned around x~159 listing items, few/no red codes.
    blue_list = 0
    red_code_like = 0
    for ln in lines:
        t = ln.text.strip()
        if not t:
            continue
        if _CODE_TOKEN_RE.match(t):
            red_code_like += 1
        if ln.non_black and 13.0 <= ln.size <= 17.5:
            if width * 0.12 <= ln.x0 <= width * 0.32:
                # Often prefixed with numbering like "3.21." but keep structural (digit+dot) as weak hint.
                if re.match(r"^\s*\d+\.\d+|\s*\d+\s*$", t):
                    blue_list += 1
                else:
                    blue_list += 1

    return blue_list >= 10 and red_code_like <= 1


def _is_schedule_table_page(lines, width: float) -> bool:
    # Schedule pages: multiple repeated header blocks of small bold column headings at top, no red codes.
    red_brackets = sum(1 for ln in lines if _is_bracket_line(ln.text))
    if red_brackets >= 2:
        return False

    top = [ln for ln in lines if ln.y0 < 180.0 and ln.size <= 10.5 and ln.bold and ln.text.strip() and not _is_bracket_line(ln.text)]
    if len(top) < 6:
        return False

    # Columns spread across x positions.
    xs = sorted(ln.x0 for ln in top)
    spread = (xs[-1] - xs[0]) if xs else 0.0
    if spread < width * 0.45:
        return False

    # Often has multiple blue link-like labels in-body; treat as additional weak signal.
    blue_small = sum(1 for ln in lines if ln.non_black and ln.size <= 10.5 and ln.x0 > width * 0.3 and ln.y0 < 760.0 and not _is_bracket_line(ln.text))
    return blue_small >= 2


def _is_change_history_page(lines, width: float) -> bool:
    # Change History page: has a blue title near top-left and a dense black 9pt table with a bold header row band.
    title = _detect_form_title(lines, width)
    if not title:
        return False

    red_brackets = sum(1 for ln in lines if _is_bracket_line(ln.text))
    if red_brackets >= 2:
        return False

    # Look for >=4 bold small lines around the same y (table header band).
    header_band = [ln for ln in lines if 180.0 <= ln.y0 <= 230.0 and ln.bold and ln.size <= 10.5 and ln.text.strip() and not _is_bracket_line(ln.text)]
    if len(header_band) < 4:
        return False

    xs = sorted(ln.x0 for ln in header_band)
    spread = xs[-1] - xs[0]
    if spread < width * 0.45:
        return False

    # Many small table rows.
    small_lines = sum(1 for ln in lines if ln.size <= 10.0 and not _is_bracket_line(ln.text) and ln.text.strip())
    return small_lines >= 30


def _extract_table_header_fields(lines, width: float, height: float) -> List[str]:
    # Detect multi-column header band near the top (around y ~ 110–165).
    band = []
    for ln in lines:
        if ln.y0 < 90.0 or ln.y0 > 170.0:
            continue
        t = ln.text.strip()
        if not t or _is_bracket_line(t):
            continue
        # Exclude footer-ish (rare in this band anyway).
        if ln.y0 > height - 70.0:
            continue
        # Typical header font size around 10–11, but allow drift.
        if not (8.8 <= ln.size <= 13.0):
            continue
        # Column headers are printed in black in samples.
        if ln.non_black:
            continue
        # Exclude single bullet glyphs.
        if len(t) == 1 and _is_bullet_char(t):
            continue
        # Exclude pure numbers (like page/visit nums).
        if _is_mostly_numeric(t):
            continue
        band.append(ln)

    if not band:
        return []

    # Cluster by x (columns). Use a tolerant bucket width.
    band.sort(key=lambda l: (l.x0, l.y0))
    col_clusters: List[List[object]] = []
    for ln in band:
        placed = False
        for col in col_clusters:
            if abs(col[0].x0 - ln.x0) <= 18.0:
                col.append(ln)
                placed = True
                break
        if not placed:
            col_clusters.append([ln])

    # Require a multi-column structure (avoid accidentally treating prose as headers).
    # At least 3 columns, or 2 columns with one far right.
    col_xs = sorted(c[0].x0 for c in col_clusters)
    if len(col_clusters) < 2:
        return []
    if len(col_clusters) == 2:
        if not (col_xs[1] - col_xs[0] > width * 0.45 and col_xs[1] > width * 0.55):
            return []

    if len(col_clusters) >= 3:
        # Ensure columns are meaningfully separated.
        if (col_xs[-1] - col_xs[0]) < width * 0.45:
            return []

    # For each column, join wrapped header lines (e.g., second-line "- date").
    fields = []
    for col in col_clusters:
        col.sort(key=lambda l: l.y0)
        # Keep only lines within a compact vertical span; drop strays.
        y0_min = col[0].y0
        kept = [ln for ln in col if ln.y0 - y0_min <= 45.0]
        txt = " ".join(ln.text.strip() for ln in kept if ln.text.strip())
        txt = _normalize_spaces(txt)
        if txt:
            fields.append(txt)

    return fields


def _extract_fields_via_left_codes(lines, width: float, height: float) -> List[str]:
    # Find left-margin variable code tokens (e.g., [VISDAT]) and attach best nearby black label text.
    codes = []
    for ln in lines:
        t = ln.text.strip()
        if not t:
            continue
        if not ln.non_black:
            continue
        # Codes are bracket tokens; prefer strict alnum/underscore tokens.
        if not _CODE_TOKEN_RE.match(t):
            continue
        # Anchor on left area; codes in far-right columns typically annotate cells/options.
        if ln.x0 > min(250.0, width * 0.35):
            continue
        # Exclude near-bottom.
        if ln.y0 > height - 90.0:
            continue
        codes.append(ln)

    if not codes:
        return []

    # Preindex potential label lines (black, not bracket, not footer).
    black_lines = [ln for ln in lines if (not ln.non_black) and ln.text.strip() and (not _is_bracket_line(ln.text)) and ln.y0 < height - 70.0]
    black_lines.sort(key=lambda l: (l.y0, l.x0))

    results: List[str] = []

    for code_ln in codes:
        label = _best_label_near_code(code_ln, black_lines, lines, width)
        if label:
            results.append(label)

    return results


def _best_label_near_code(code_ln, black_lines, all_lines, width: float) -> str:
    # Search window: allow label to be moderately above the code; slightly below in some layouts.
    y0 = code_ln.y0
    x0 = code_ln.x0

    window = []
    for ln in black_lines:
        if ln.y0 < y0 - 160.0:
            continue
        if ln.y0 > y0 + 60.0:
            break
        # Must be reasonably near the code's left area.
        if abs(ln.x0 - x0) > 120.0:
            continue
        t = ln.text.strip()
        if not t:
            continue
        # Avoid single bullets and tiny artifacts.
        if len(t) == 1 and _is_bullet_char(t):
            continue
        window.append(ln)

    if not window:
        return ""

    def score(ln) -> float:
        t = ln.text.strip()
        dy = ln.y0 - y0
        dx = abs(ln.x0 - x0)

        s = 0.0
        # Prefer slightly-above labels.
        if dy <= 0:
            s += 10.0 - (abs(dy) * 0.10)
        else:
            s += 5.0 - (dy * 0.15)

        # Prefer closer x alignment.
        s += max(0.0, 6.0 - (dx * 0.06))

        # Prefer label-like text.
        if ln.bold:
            s += 6.0
        if t.endswith("?"):
            s += 6.0
        if t.endswith(":"):
            s += 2.5
        if 3 <= len(t) <= 80:
            s += 3.0
        if len(t) > 120:
            s -= 6.0
        if "(" in t and len(t) > 80:
            s -= 4.0
        if _looks_like_row_label(t) and ln.bold:
            s -= 4.0

        # Penalize lines that look like option items (bullet on same row).
        if _has_bullet_neighbor(ln, all_lines):
            s -= 10.0

        return s

    best = max(window, key=score)
    if score(best) < 2.0:
        return ""

    # Expand to wrapped lines aligned to the best line.
    merged = _merge_wrapped_label(best, window, all_lines)
    merged = _normalize_spaces(merged)

    # Final guard: avoid returning bracket-like or empty.
    if not merged or _is_bracket_line(merged):
        return ""
    return merged


def _merge_wrapped_label(seed, window, all_lines) -> str:
    # Merge lines around seed with similar x and size, in close vertical proximity.
    x_ref = seed.x0
    size_ref = seed.size

    # Include seed, then extend up/down.
    candidates = [ln for ln in window if abs(ln.x0 - x_ref) <= 14.0 and abs(ln.size - size_ref) <= 2.2 and not _has_bullet_neighbor(ln, all_lines)]
    candidates.sort(key=lambda l: l.y0)

    # Keep a contiguous run containing seed.
    seed_idx = None
    for i, ln in enumerate(candidates):
        if ln is seed:
            seed_idx = i
            break
    if seed_idx is None:
        return seed.text.strip()

    run = [candidates[seed_idx]]

    # Upward
    i = seed_idx - 1
    while i >= 0:
        prev = candidates[i]
        cur = run[0]
        if cur.y0 - prev.y0 > 22.0:
            break
        run.insert(0, prev)
        i -= 1

    # Downward
    i = seed_idx + 1
    while i < len(candidates):
        nxt = candidates[i]
        cur = run[-1]
        if nxt.y0 - cur.y0 > 22.0:
            break
        run.append(nxt)
        i += 1

    # Join with spaces.
    txt = " ".join(ln.text.strip() for ln in run if ln.text.strip())
    return txt


def _extract_question_with_optionlist_fallback(lines, width: float, height: float) -> List[str]:
    # Very conservative: detect right-side vertical list of short ALLCAPS/digits tokens (options),
    # then take the best left-side question sentence near the top.
    option_like = []
    for ln in lines:
        t = ln.text.strip()
        if not t:
            continue
        if ln.y0 < 90.0 or ln.y0 > height - 90.0:
            continue
        if ln.x0 < width * 0.55:
            continue
        if ln.size < 8.5 or ln.size > 13.5:
            continue
        if _is_bracket_line(t):
            continue
        if re.match(r"^[A-Z]{2,10}\d{0,3}$", t):
            option_like.append(ln)

    if len(option_like) < 6:
        return []

    # Find left-side question-like text near top.
    left = []
    for ln in lines:
        t = ln.text.strip()
        if not t or _is_bracket_line(t):
            continue
        if ln.non_black:
            continue
        if ln.x0 > width * 0.45:
            continue
        if ln.y0 > 220.0:
            continue
        if len(t) < 10 or len(t) > 220:
            continue
        left.append(ln)

    if not left:
        return []

    # Pick the topmost long-ish line.
    left.sort(key=lambda l: (l.y0, l.x0))
    return [_normalize_spaces(left[0].text.strip())]


def _clean_field_names(fields: List[str]) -> List[str]:
    cleaned = []
    for f in fields:
        t = _normalize_spaces((f or "").strip())
        if not t:
            continue
        # Drop purely numeric / punctuation-ish artifacts.
        if _is_mostly_numeric(t):
            continue
        if len(t) == 1 and _is_bullet_char(t):
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
    return re.sub(r"\s+", " ", s).strip()


def _is_bracket_line(t: str) -> bool:
    t = (t or "").strip()
    return bool(_BRACKET_ANY_RE.match(t))


def _is_mostly_numeric(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return True
    alnum = sum(ch.isalnum() for ch in t)
    digits = sum(ch.isdigit() for ch in t)
    if alnum == 0:
        return True
    return digits >= max(1, int(0.8 * alnum))


def _is_bullet_char(ch: str) -> bool:
    return ch in {"•", "·", "‣", "▪", "●", "○", "–", "-", "•"}


def _has_bullet_neighbor(label_ln, all_lines) -> bool:
    # Same-row bullet immediately to the left indicates an option list item.
    y = label_ln.y0
    for ln in all_lines:
        if abs(ln.y0 - y) <= 4.0:
            t = ln.text.strip()
            if len(t) == 1 and _is_bullet_char(t):
                if 0.0 < (label_ln.x0 - ln.x0) < 30.0:
                    return True
    return False


def _looks_like_row_label(t: str) -> bool:
    # Heuristic to avoid "Row 1" style table row headers.
    t = (t or "").strip()
    if len(t) > 10:
        return False
    return bool(re.match(r"^[A-Za-z]{1,5}\s*\d{1,3}$", t))
```
