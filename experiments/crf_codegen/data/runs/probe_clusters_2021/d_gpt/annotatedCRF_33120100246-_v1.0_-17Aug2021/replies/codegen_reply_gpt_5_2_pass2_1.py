```python
# Observed annotated CRF layout: human labels in black, form titles in larger blue text near top-left,
# and per-field machine markers printed in red bracketed codes like "[ABC123]" followed by "[TYPE: ...]".
# Strategy: detect/track form titles from prominent top-of-page lines, then extract each field by
# locating red field-code markers and recovering the nearby human label block by geometry + wrap-join.
# Avoid options/legend rows by position/style (right-side short colored items) and skip technical "[TYPE:...]".

import re
from typing import List, Dict, Tuple, Optional

_RE_FIELD_CODE = re.compile(r"^\[[A-Za-z0-9]+\]$")
_RE_TYPELIKE = re.compile(r"^\[(TYPE|VISIBILITY|FORMAT|DEFAULT|NOTE|DERIVATION)\b[:\]]", re.I)
_RE_ROW = re.compile(r"^\s*Row\s+\d+\s*$", re.I)
_RE_NUMBERED = re.compile(r"^\s*[\\/]*\s*\d+\s*[\.\)]")  # e.g. "\1.\" or "1." or "1)"
_RE_MOSTLY_PUNCT = re.compile(r"^[\W_]+$")

def _clean_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def _is_code_line(t: str) -> bool:
    t = t.strip()
    if not t.startswith("[") or not t.endswith("]"):
        return False
    if _RE_TYPELIKE.match(t):
        return True
    return bool(_RE_FIELD_CODE.match(t))

def _is_field_code_line(t: str) -> bool:
    t = t.strip()
    if not _RE_FIELD_CODE.match(t):
        return False
    if _RE_TYPELIKE.match(t):
        return False
    # exclude bracketed blobs that are not field ids (very rare here, but be safe)
    inner = t[1:-1]
    if ":" in inner:
        return False
    return True

def _looks_like_short_option(line, page_right: float) -> bool:
    # Options (Yes/No/Met/Not Met/etc.) are often short, colored/grey, in right-side columns.
    # Don't key on words; key on (short + right-side + colored).
    t = _clean_text(line.text)
    if not t:
        return False
    if line.x0 < page_right * 0.55:
        return False
    if not line.non_black:
        return False
    if len(t) > 18:
        return False
    # avoid excluding true labels that happen to be short but left-aligned
    if line.size >= 12.0:
        return False
    # very short tokens in right column are almost always options
    return True

def _is_row_header(line) -> bool:
    return bool(line.bold and _RE_ROW.match(_clean_text(line.text)))

def _is_label_candidate(line, page_right: float) -> bool:
    t = _clean_text(line.text)
    if not t:
        return False
    if _is_code_line(t):
        return False
    if _RE_ROW.match(t):
        return False
    if _RE_MOSTLY_PUNCT.match(t):
        return False
    if _looks_like_short_option(line, page_right):
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

def _page_right(lines) -> float:
    mr = 0.0
    for ln in lines:
        if ln.x1 > mr:
            mr = ln.x1
    return mr if mr > 0 else 600.0

def _find_form_title(lines, page_right: float) -> Optional[str]:
    # Prefer prominent top-left title lines: larger font, often colored, y near top.
    # Avoid picking right-column options by requiring left alignment.
    candidates = []
    for ln in lines:
        t = _clean_text(ln.text)
        if not t:
            continue
        if _is_code_line(t):
            continue
        if ln.y0 > 140:
            continue
        if ln.x0 > page_right * 0.45:
            continue
        # titles tend to be larger than body (7-9) and table text (9)
        if ln.size < 11.5:
            continue
        # colored titles are most reliable, but allow bold black if large
        if not ln.non_black and not ln.bold:
            continue
        if _RE_ROW.match(t):
            continue
        candidates.append((ln.size, -ln.y0, -ln.bold, -ln.non_black, ln.x0, t))
    if not candidates:
        return None
    # choose largest, then highest on page
    candidates.sort(reverse=True)
    title = candidates[0][-1]
    return title if title else None

def _build_row_spans(lines, page_right: float) -> List[Tuple[int, int]]:
    # returns list of (row_header_idx, next_row_header_idx_exclusive), sorted by idx
    row_idxs = [i for i, ln in enumerate(lines) if _is_row_header(ln)]
    spans = []
    for k, i in enumerate(row_idxs):
        j = row_idxs[k + 1] if k + 1 < len(row_idxs) else len(lines)
        spans.append((i, j))
    return spans

def _row_span_for_index(row_spans: List[Tuple[int, int]], idx: int) -> Optional[Tuple[int, int]]:
    # row_spans are in increasing order, non-overlapping
    lo, hi = 0, len(row_spans) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        a, b = row_spans[mid]
        if a <= idx < b:
            return (a, b)
        if idx < a:
            hi = mid - 1
        else:
            lo = mid + 1
    # if not inside any span, still allow using the last row span above as a soft boundary
    for a, b in reversed(row_spans):
        if a < idx:
            best = (a, b)
            break
    return best

def _labelish_score(line) -> int:
    t = _clean_text(line.text)
    if not t:
        return 0
    s = 0
    if line.bold:
        s += 3
    if t.endswith("?"):
        s += 3
    if t.endswith(":"):
        s += 2
    if _RE_NUMBERED.match(t):
        s += 2
    if len(t) <= 80:
        s += 1
    return s

def _extract_label(lines, code_idx: int, page_right: float, row_spans: List[Tuple[int, int]]) -> Optional[str]:
    code = lines[code_idx]
    code_y = code.y0
    code_x = code.x0
    left_col_max = page_right * 0.45

    # limit search context: prefer within the same "Row N" band when present
    span = _row_span_for_index(row_spans, code_idx)
    span_start, span_end = (span if span else (0, len(lines)))

    # candidate set for anchoring
    max_back = 140.0
    best_anchor = None
    best_score = -1
    best_dist = 1e9

    for j in range(code_idx - 1, span_start - 1, -1):
        ln = lines[j]
        if code_y - ln.y0 > max_back:
            break
        if not _is_label_candidate(ln, page_right):
            continue
        # geometry gating
        if code_x < left_col_max:
            if abs(ln.x0 - code_x) > 85:
                continue
        else:
            if ln.x0 > left_col_max:
                continue

        sc = _labelish_score(ln)
        dist = code_y - ln.y0
        # choose by (score desc, distance asc)
        if sc > best_score or (sc == best_score and dist < best_dist):
            best_score = sc
            best_dist = dist
            best_anchor = j

    # fallback: nearest above in appropriate column even if not labelish
    if best_anchor is None:
        for j in range(code_idx - 1, span_start - 1, -1):
            ln = lines[j]
            if code_y - ln.y0 > max_back:
                break
            if not _is_label_candidate(ln, page_right):
                continue
            if code_x < left_col_max:
                if abs(ln.x0 - code_x) > 85:
                    continue
            else:
                if ln.x0 > left_col_max:
                    continue
            best_anchor = j
            break

    if best_anchor is None:
        return None

    base_x = lines[best_anchor].x0
    base_size = lines[best_anchor].size

    def x_ok(x: float) -> bool:
        return abs(x - base_x) <= 40.0

    def size_ok(sz: float) -> bool:
        return abs(sz - base_size) <= 2.0

    # extend upward (tight wrap)
    start = best_anchor
    prev_y = lines[start].y0
    for j in range(best_anchor - 1, span_start - 1, -1):
        ln = lines[j]
        if _is_row_header(ln):
            break
        if not _is_label_candidate(ln, page_right):
            continue
        if code_x < left_col_max:
            if not x_ok(ln.x0):
                break
        else:
            if ln.x0 > left_col_max or not x_ok(ln.x0):
                break
        # wrap continuity
        gap = prev_y - ln.y0
        if gap > 15.5:
            break
        if not size_ok(ln.size):
            break
        start = j
        prev_y = ln.y0

    # extend downward until just before code (skip interleaved right-column codes/options)
    parts = []
    prev_included_y = None
    for j in range(start, min(code_idx, span_end)):
        ln = lines[j]
        if _is_row_header(ln):
            break
        if not _is_label_candidate(ln, page_right):
            continue
        # must stay in the label column (left side for right-code pages; same x band for left-code pages)
        if code_x < left_col_max:
            if not x_ok(ln.x0):
                continue
        else:
            if ln.x0 > left_col_max:
                continue
            if not x_ok(ln.x0) and not (abs(ln.x0 - base_x) <= 40.0):
                continue
        if not size_ok(ln.size):
            continue
        if prev_included_y is not None:
            gap = ln.y0 - prev_included_y
            if gap > 15.5:
                # stop at first big break after we started collecting (prevents swallowing long definitions)
                break
        parts.append(ln.text)
        prev_included_y = ln.y0

    label = _join_wrap(parts)
    if not label:
        return None
    return label

def extract(pages):
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
            t = _clean_text(ln.text)
            if not _is_field_code_line(t):
                continue

            label = _extract_label(lines, i, pr, row_spans)
            if not label:
                continue

            form_name = current_form.strip()
            field_name = label.strip()

            key = (page_idx0 + 1, form_name, field_name)
            if key in seen:
                continue
            seen.add(key)

            out.append(
                {
                    "form_name": form_name,
                    "field_name": field_name,
                    "page": page_idx0 + 1,
                }
            )

    return out
```
