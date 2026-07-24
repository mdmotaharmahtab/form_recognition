```python
import re
from typing import List, Dict, Tuple, Optional, Iterable


# --- Regexes ---
# Allow common code chars like "_" and "-" while still avoiding 1-char junk.
_RE_BRACKET_TOKEN = re.compile(r"\[[A-Za-z0-9][A-Za-z0-9_\-]{1,}\]")
_RE_FIELD_CODE_EXACT = re.compile(r"^\[[A-Za-z0-9][A-Za-z0-9_\-]{1,}\]$")

_RE_TYPELIKE = re.compile(
    r"^\[(TYPE|VISIBILITY|FORMAT|DEFAULT|NOTE|DERIVATION)\b[:\]]", re.I
)
_RE_ROW = re.compile(r"^\s*Row\s+\d+\s*$", re.I)

# e.g. "\1.\" or "1." or "1)" or "/ 1." (OCR-ish)
_RE_NUMBERED = re.compile(r"^\s*[\\/]*\s*\d+\s*[\.\)]")
_RE_MOSTLY_PUNCT = re.compile(r"^[\W_]+$")


def _clean_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _g(ln, name: str, default):
    return getattr(ln, name, default)


def _page_right(lines) -> float:
    mr = 0.0
    for ln in lines:
        x1 = float(_g(ln, "x1", 0.0) or 0.0)
        if x1 > mr:
            mr = x1
    return mr if mr > 0 else 600.0


def _is_typelike_line(t: str) -> bool:
    t = t.strip()
    return bool(_RE_TYPELIKE.match(t))


def _extract_code_tokens_from_text(t: str) -> List[str]:
    """
    Returns bracket tokens that look like field codes, excluding typelike tokens.
    """
    t = (t or "").strip()
    if not t:
        return []
    tokens = _RE_BRACKET_TOKEN.findall(t)
    out = []
    for tok in tokens:
        if _RE_TYPELIKE.match(tok):
            continue
        inner = tok[1:-1]
        # Avoid "[NOTE: ...]" / "[TYPE: ...]" style blobs (and other colon payloads).
        if ":" in inner:
            continue
        out.append(tok)
    return out


def _is_field_code_line(t: str) -> bool:
    """
    True for lines that are exactly a field code token.
    """
    t = t.strip()
    if not _RE_FIELD_CODE_EXACT.match(t):
        return False
    if _RE_TYPELIKE.match(t):
        return False
    inner = t[1:-1]
    if ":" in inner:
        return False
    return True


def _is_row_header(line) -> bool:
    t = _clean_text(_g(line, "text", "") or "")
    return bool(_g(line, "bold", False) and _RE_ROW.match(t))


def _looks_like_short_option(line, page_right: float) -> bool:
    """
    Right-column anchors/options (Yes/No/Met/Not Met etc.) tend to be short.
    Keep structural, not word-based.
    """
    t = _clean_text(_g(line, "text", "") or "")
    if not t:
        return False

    # If it looks like an instruction/prompt (often used for text fields), don't treat as an option.
    if t.endswith(":") or t.endswith("?"):
        return False

    x0 = float(_g(line, "x0", 0.0) or 0.0)
    size = float(_g(line, "size", 0.0) or 0.0)
    bold = bool(_g(line, "bold", False))
    non_black = bool(_g(line, "non_black", False))

    # Many options are 1–3 words; longer phrases are more likely to be labels/instructions.
    wc = len([w for w in t.split(" ") if w])

    # strong signal: very short + far-right + colored + small
    if (
        x0 >= page_right * 0.58
        and non_black
        and size <= 11.0
        and len(t) <= 14
        and wc <= 3
    ):
        return True

    # weaker signal: extremely short + far-right + small (even if black)
    if (
        x0 >= page_right * 0.68
        and size <= 10.5
        and not bold
        and len(t) <= 10
        and wc <= 2
    ):
        return True

    return False


def _is_label_candidate(line, page_right: float) -> bool:
    t = _clean_text(_g(line, "text", "") or "")
    if not t:
        return False
    if _is_typelike_line(t):
        return False
    if _RE_ROW.match(t):
        return False
    if _RE_MOSTLY_PUNCT.match(t):
        return False
    if _looks_like_short_option(line, page_right):
        return False
    # Avoid pure code lines and bracket-only junk
    if _is_field_code_line(t):
        return False
    if t.startswith("[") and t.endswith("]") and len(_extract_code_tokens_from_text(t)) > 0:
        # If line is mostly bracket tokens, not a human label
        remainder = _clean_text(_RE_BRACKET_TOKEN.sub(" ", t))
        if not remainder:
            return False
    return True


def _join_wrap(lines_text: List[str]) -> str:
    out = ""
    for s in lines_text:
        s = _clean_text(s)
        if not s:
            continue
        if not out:
            out = s
            continue
        # no-space join after hyphen-like wrap
        if out.endswith(("-", "‐", "‑", "–")):
            out = out + s
        else:
            out = out + " " + s
    return out.strip()


def _labelish_score(line) -> int:
    t = _clean_text(_g(line, "text", "") or "")
    if not t:
        return 0
    s = 0
    if bool(_g(line, "bold", False)):
        s += 3
    if t.endswith("?"):
        s += 3
    if t.endswith(":"):
        s += 2
    if _RE_NUMBERED.match(t):
        s += 4
    if len(t) <= 90:
        s += 1
    return s


def _find_form_title(lines, page_right: float) -> Optional[str]:
    """
    Prefer prominent top-left title lines: larger font, often colored, near top.
    Loosened to catch bold black titles too (some forms).
    """
    candidates = []
    for ln in lines:
        t = _clean_text(_g(ln, "text", "") or "")
        if not t:
            continue
        if _is_typelike_line(t) or _is_field_code_line(t):
            continue
        if _RE_ROW.match(t):
            continue

        y0 = float(_g(ln, "y0", 0.0) or 0.0)
        x0 = float(_g(ln, "x0", 0.0) or 0.0)
        size = float(_g(ln, "size", 0.0) or 0.0)
        bold = bool(_g(ln, "bold", False))
        non_black = bool(_g(ln, "non_black", False))

        # Must be near top and left-ish
        if y0 > 160:
            continue
        if x0 > page_right * 0.52:
            continue

        # Titles tend to be larger; accept slightly smaller if bold and very top
        if size >= 11.0:
            pass
        elif size >= 10.0 and bold and y0 <= 95:
            pass
        else:
            continue

        # Prefer colored or bold
        if not non_black and not bold:
            continue

        candidates.append((size, -y0, int(bold), int(non_black), -x0, t))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][-1] or None


def _build_row_spans(lines, page_right: float) -> List[Tuple[int, int]]:
    row_idxs = [i for i, ln in enumerate(lines) if _is_row_header(ln)]
    spans = []
    for k, i in enumerate(row_idxs):
        j = row_idxs[k + 1] if k + 1 < len(row_idxs) else len(lines)
        spans.append((i, j))
    return spans


def _row_span_for_index(row_spans: List[Tuple[int, int]], idx: int) -> Optional[Tuple[int, int]]:
    if not row_spans:
        return None
    lo, hi = 0, len(row_spans) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        a, b = row_spans[mid]
        if a <= idx < b:
            return (a, b)
        if idx < a:
            hi = mid - 1
        else:
            lo = mid + 1
    # soft boundary: last row header above
    for a, b in reversed(row_spans):
        if a < idx:
            return (a, b)
    return None


def _is_numbered_start_text(t: str) -> bool:
    t = _clean_text(t)
    return bool(_RE_NUMBERED.match(t))


def _is_codey_only_text(t: str) -> bool:
    t = _clean_text(t)
    if not t:
        return True
    if _is_field_code_line(t) or _is_typelike_line(t):
        return True
    toks = _extract_code_tokens_from_text(t)
    if toks and _clean_text(_RE_BRACKET_TOKEN.sub(" ", t)) == "":
        return True
    return False


def _column_thresholds(page_right: float) -> Tuple[float, float]:
    # left-ish boundary and right-ish boundary for structural gating
    return (page_right * 0.52, page_right * 0.62)


def _x_band_tol(page_right: float) -> float:
    # Slack scales with page width; keep a hard minimum.
    return max(120.0, min(180.0, page_right * 0.16))


def _collect_numbered_block_until(lines, start_idx: int, stop_exclusive: int, page_right: float) -> str:
    """
    For numbered criteria-like labels, collect all continuation lines until stop_exclusive
    (typically the code line), ignoring large vertical gaps.
    """
    base_x = float(_g(lines[start_idx], "x0", 0.0) or 0.0)
    base_size = float(_g(lines[start_idx], "size", 0.0) or 0.0)
    tol = max(55.0, _x_band_tol(page_right) * 0.45)

    parts: List[str] = []
    for j in range(start_idx, max(start_idx + 1, stop_exclusive)):
        ln = lines[j]
        if _is_row_header(ln):
            break

        t = _clean_text(_g(ln, "text", "") or "")
        if not t:
            continue
        if _is_codey_only_text(t):
            continue
        if _looks_like_short_option(ln, page_right):
            continue

        x0 = float(_g(ln, "x0", 0.0) or 0.0)
        sz = float(_g(ln, "size", 0.0) or 0.0)

        # stop if we hit the next numbered item before the code line
        if j > start_idx and _is_numbered_start_text(t):
            break

        # keep within the same left-column band and font neighborhood
        if abs(x0 - base_x) > tol and x0 > base_x + tol:
            # allow slightly more indented bullet sub-lines (e.g. "- item")
            if not t.lstrip().startswith(("-", "–", "•")):
                break

        if abs(sz - base_size) > 2.8:
            # allow smaller font for hyphen bullet lists within same item
            if not t.lstrip().startswith(("-", "–", "•")):
                pass  # don't break solely on size; keep structural checks dominant

        parts.append(_g(ln, "text", "") or "")

    return _join_wrap(parts)


def _extract_inline_label_from_code_line_text(raw_text: str) -> Optional[str]:
    """
    If a line contains both human label and a [CODE], use the human prefix.
    """
    raw_text = raw_text or ""
    tokens = _extract_code_tokens_from_text(raw_text)
    if not tokens:
        return None

    # Take prefix before first code token
    m = _RE_BRACKET_TOKEN.search(raw_text)
    if not m:
        return None
    prefix = _clean_text(raw_text[: m.start()])
    if not prefix:
        return None

    # If prefix is just punctuation/number marker, not a label
    if _RE_MOSTLY_PUNCT.match(prefix):
        return None

    return prefix


def _extract_label_near_code(
    lines,
    code_idx: int,
    page_right: float,
    row_spans: List[Tuple[int, int]],
) -> Optional[str]:
    code_ln = lines[code_idx]
    code_y = float(_g(code_ln, "y0", 0.0) or 0.0)
    code_x = float(_g(code_ln, "x0", 0.0) or 0.0)

    left_col_max, _right_col_min = _column_thresholds(page_right)
    tolx = _x_band_tol(page_right)

    span = _row_span_for_index(row_spans, code_idx)
    span_start, span_end = (span if span else (0, len(lines)))

    # 0) If the code line itself carries label text + [CODE], use it.
    inline = _extract_inline_label_from_code_line_text(_g(code_ln, "text", "") or "")
    if inline and not _is_typelike_line(inline):
        if _clean_text(_RE_BRACKET_TOKEN.sub(" ", inline)):
            return inline.strip()

    def column_accept(ln) -> bool:
        x0 = float(_g(ln, "x0", 0.0) or 0.0)
        # If code is on left-ish, labels usually align near it or left.
        if code_x <= left_col_max:
            return abs(x0 - code_x) <= tolx
        # If code is right-ish, labels are often in the left column,
        # but some layouts place labels near the right-side field itself.
        if x0 <= left_col_max + 10.0:
            return True
        return abs(x0 - code_x) <= tolx

    # 0.5) Same-row neighbor (handles right-column labels aligned with right-column fields)
    neigh_best = None
    neigh_best_score = -1
    neigh_best_cost = 1e18
    for j in range(max(span_start, code_idx - 6), min(span_end, code_idx + 7)):
        if j == code_idx:
            continue
        ln = lines[j]
        if not _is_label_candidate(ln, page_right):
            continue
        if not column_accept(ln):
            continue
        y0 = float(_g(ln, "y0", 0.0) or 0.0)
        if abs(y0 - code_y) > 7.0:
            continue

        # prefer candidates to the left of the code when possible
        x0 = float(_g(ln, "x0", 0.0) or 0.0)
        dx = abs(code_x - x0)
        left_pen = 0.0 if x0 <= code_x + 1.0 else 45.0

        sc = _labelish_score(ln)
        cost = dx + left_pen + (abs(y0 - code_y) * 3.0)
        if sc > neigh_best_score or (sc == neigh_best_score and cost < neigh_best_cost):
            neigh_best = j
            neigh_best_score = sc
            neigh_best_cost = cost

    # If we found a strong neighbor, try to wrap-join around it (using existing logic below).
    preferred_anchor = neigh_best

    # 1) Find best anchor above the code (primary)
    max_back = max(220.0, min(360.0, page_right * 0.55))
    best_anchor = preferred_anchor
    best_score = neigh_best_score if preferred_anchor is not None else -1
    best_dist = 1e9

    for j in range(code_idx - 1, span_start - 1, -1):
        ln = lines[j]
        y0 = float(_g(ln, "y0", 0.0) or 0.0)
        if code_y - y0 > max_back:
            break
        if _is_row_header(ln):
            break
        if not _is_label_candidate(ln, page_right):
            continue
        if not column_accept(ln):
            continue
        sc = _labelish_score(ln)
        dist = code_y - y0
        if sc > best_score or (sc == best_score and dist < best_dist):
            best_anchor = j
            best_score = sc
            best_dist = dist

    # 2) If not found above, search forward below (some layouts place label under marker)
    if best_anchor is None:
        max_fwd = max(150.0, min(300.0, page_right * 0.50))
        for j in range(code_idx + 1, min(span_end, len(lines))):
            ln = lines[j]
            y0 = float(_g(ln, "y0", 0.0) or 0.0)
            if y0 - code_y > max_fwd:
                break
            t = _clean_text(_g(ln, "text", "") or "")
            if _is_field_code_line(t) or _is_typelike_line(t):
                break
            if not _is_label_candidate(ln, page_right):
                continue
            if not column_accept(ln):
                continue
            best_anchor = j
            break

    if best_anchor is None:
        return None

    anchor_ln = lines[best_anchor]
    base_x = float(_g(anchor_ln, "x0", 0.0) or 0.0)
    base_size = float(_g(anchor_ln, "size", 0.0) or 0.0)

    def x_ok(ln) -> bool:
        x0 = float(_g(ln, "x0", 0.0) or 0.0)
        # allow a bit more slack for wrapped text
        return abs(x0 - base_x) <= max(45.0, tolx * 0.35) or (
            _clean_text(_g(ln, "text", "") or "").lstrip().startswith(("-", "–", "•"))
            and (x0 >= base_x - 5.0 and x0 <= base_x + tolx * 0.7)
        )

    def size_ok(ln) -> bool:
        sz = float(_g(ln, "size", 0.0) or 0.0)
        return abs(sz - base_size) <= 3.0

    # Special handling: numbered criteria blocks (capture full text up to code line).
    anchor_text = _clean_text(_g(anchor_ln, "text", "") or "")
    if _is_numbered_start_text(anchor_text):
        stop = code_idx if best_anchor <= code_idx else min(span_end, len(lines))
        label = _collect_numbered_block_until(lines, best_anchor, stop, page_right)
        return label or None

    # General wrap-join around anchor.

    # Extend upward (tight wrap)
    start = best_anchor
    prev_y = float(_g(lines[start], "y0", 0.0) or 0.0)
    for j in range(best_anchor - 1, span_start - 1, -1):
        ln = lines[j]
        if _is_row_header(ln):
            break
        if not _is_label_candidate(ln, page_right):
            continue
        if not column_accept(ln):
            break
        if not x_ok(ln):
            break
        if not size_ok(ln):
            break
        y0 = float(_g(ln, "y0", 0.0) or 0.0)
        gap = prev_y - y0
        if gap > 20.0:
            break
        start = j
        prev_y = y0

    # Collect downward, stopping before code_idx if anchor above; otherwise stop at next structural break.
    parts: List[str] = []
    prev_included_y: Optional[float] = None
    stop_excl = code_idx if start <= code_idx else span_end

    # Allow larger line gaps for long question-like prompts.
    gap_limit = 26.0
    if anchor_text.endswith("?") or len(anchor_text) >= 70:
        gap_limit = 44.0

    for j in range(start, min(stop_excl, span_end)):
        ln = lines[j]
        if _is_row_header(ln):
            break
        if not _is_label_candidate(ln, page_right):
            continue
        if not column_accept(ln):
            continue
        if not x_ok(ln):
            continue
        if not size_ok(ln):
            continue

        t = _clean_text(_g(ln, "text", "") or "")
        if not t or _is_codey_only_text(t):
            continue

        y0 = float(_g(ln, "y0", 0.0) or 0.0)
        if prev_included_y is not None:
            gap = y0 - prev_included_y
            if gap > gap_limit:
                if parts:
                    break
        parts.append(_g(ln, "text", "") or "")
        prev_included_y = y0

    label = _join_wrap(parts)
    return label or None


def extract(pages: Iterable[Tuple[int, object]]):
    out: List[Dict[str, object]] = []
    seen = set()

    current_form = ""

    for page_idx0, lines in pages:
        pr = _page_right(lines)
        title = _find_form_title(lines, pr)
        if title:
            current_form = title

        row_spans = _build_row_spans(lines, pr)

        for i, ln in enumerate(lines):
            raw = _g(ln, "text", "") or ""
            t = _clean_text(raw)

            # Identify field markers both as standalone lines and embedded tokens.
            codes: List[str] = []
            if _is_field_code_line(t):
                codes = [t]
            else:
                if _is_typelike_line(t):
                    continue
                toks = _extract_code_tokens_from_text(raw)
                if toks:
                    codes = toks

            if not codes:
                continue

            label = _extract_label_near_code(lines, i, pr, row_spans)
            if not label:
                continue

            form_name = (current_form or "").strip()
            field_name = (label or "").strip()
            if not field_name:
                continue
            if _is_field_code_line(field_name) or _is_typelike_line(field_name):
                continue

            page_num = page_idx0 + 1

            # Allow duplicate labels on the same page if they correspond to different field markers.
            for code_tok in codes:
                key = (page_num, form_name, field_name, code_tok)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "form_name": form_name,
                        "field_name": field_name,
                        "page": page_num,
                    }
                )

    return out
```
