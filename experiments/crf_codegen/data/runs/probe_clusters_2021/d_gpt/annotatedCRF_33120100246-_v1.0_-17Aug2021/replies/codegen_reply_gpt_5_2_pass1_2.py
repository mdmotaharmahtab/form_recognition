```python
import re
import statistics
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional


@dataclass(frozen=True)
class L:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    bold: bool
    non_black: bool


_CODE_TOKEN_RE = re.compile(r"^\[[^\s\]:]{2,40}\]$")  # bracketed, no colon, no spaces
_TECH_BRACKET_RE = re.compile(r"^\[[A-Z][A-Z_ ]*:")
_TIMEPOINT_RE = re.compile(
    r"(?i)\b(\d+(\.\d+)?\s*(h|hr|hrs|hour|hours))\b|\b(pre[- ]?dose|post[- ]?dose)\b"
)


def _to_L(lines) -> List[L]:
    out: List[L] = []
    for ln in lines:
        out.append(
            L(
                text=(ln.text or "").strip(),
                x0=float(ln.x0),
                y0=float(ln.y0),
                x1=float(ln.x1),
                y1=float(ln.y1),
                size=float(ln.size),
                bold=bool(ln.bold),
                non_black=bool(ln.non_black),
            )
        )
    return out


def _merge_bracket_fragments(lines: List[L]) -> List[L]:
    # Merge consecutive colored bracket fragments like "[SCANNE" + "R]" at same x.
    merged: List[L] = []
    i = 0
    n = len(lines)
    while i < n:
        cur = lines[i]
        if (
            cur.non_black
            and cur.text.startswith("[")
            and not cur.text.endswith("]")
            and len(cur.text) >= 2
        ):
            j = i + 1
            txt = cur.text
            x0, y0, x1, y1 = cur.x0, cur.y0, cur.x1, cur.y1
            size = cur.size
            bold = cur.bold
            nb = cur.non_black
            while j < n:
                nxt = lines[j]
                if not nxt.non_black:
                    break
                if abs(nxt.x0 - x0) > 4.0:
                    break
                if (nxt.y0 - y1) > 20.0:
                    break
                if not nxt.text:
                    j += 1
                    continue
                if nxt.text.startswith("[") and "[" in txt:
                    break
                txt += nxt.text
                x1 = max(x1, nxt.x1)
                y1 = max(y1, nxt.y1)
                size = max(size, nxt.size)
                bold = bold or nxt.bold
                nb = nb or nxt.non_black
                if txt.endswith("]"):
                    break
                j += 1
            if txt.endswith("]"):
                merged.append(L(txt.strip(), x0, y0, x1, y1, size, bold, nb))
                i = j + 1
                continue
        merged.append(cur)
        i += 1
    return merged


def _quantile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if q <= 0:
        return sorted_vals[0]
    if q >= 1:
        return sorted_vals[-1]
    idx = int(round((len(sorted_vals) - 1) * q))
    idx = max(0, min(len(sorted_vals) - 1, idx))
    return sorted_vals[idx]


def _page_stats(lines: List[L]) -> Dict[str, float]:
    xs1 = [ln.x1 for ln in lines]
    ys1 = [ln.y1 for ln in lines]
    width = max(xs1) if xs1 else 612.0
    height = max(ys1) if ys1 else 792.0

    sizes = sorted([ln.size for ln in lines if ln.text])
    if not sizes:
        return {"width": width, "height": height, "small": 0.0, "large": 0.0, "median": 0.0}

    median = statistics.median(sizes)
    small = _quantile(sizes, 0.30)
    large = _quantile(sizes, 0.92)
    return {"width": width, "height": height, "small": small, "large": large, "median": median}


def _is_tech_bracket(text: str) -> bool:
    t = text.strip()
    if not (t.startswith("[") and t.endswith("]")):
        return False
    if ":" in t:
        return True
    return bool(_TECH_BRACKET_RE.match(t))


def _is_code_token(text: str) -> bool:
    return bool(_CODE_TOKEN_RE.match((text or "").strip()))


def _is_toc_like(lines: List[L]) -> bool:
    # Structural TOC-like pages: many similarly styled non-black numbered entries, no bracket annotations.
    bracketish = [ln for ln in lines if ln.text.startswith("[") and ln.text.endswith("]")]
    if bracketish:
        return False
    colored = [ln for ln in lines if ln.text and ln.non_black]
    if len(colored) < 12:
        return False
    numlike = 0
    for ln in colored:
        if re.match(r"^\s*\d+(\.\d+)*\.", ln.text):
            numlike += 1
    return numlike >= max(8, int(0.5 * len(colored)))


def _looks_like_title_text(t: str) -> bool:
    tt = (t or "").strip()
    if not tt:
        return False
    if tt.startswith("["):
        return False
    if "?" in tt:
        return False
    # Titles are not typically single-token noise.
    if len(tt) <= 2:
        return False
    return True


def _title_candidate(
    lines: List[L],
    st: Dict[str, float],
    has_any_red: bool,
    code_min_y0: Optional[float],
    allow_update: bool,
) -> str:
    if not allow_update:
        return ""
    width = st["width"]
    height = st["height"]
    large = st["large"]
    median = st["median"]
    small = st["small"]

    top_band_y = min(160.0, 0.22 * height)
    top = [ln for ln in lines if ln.text and ln.y0 <= top_band_y and ln.x0 <= width * 0.75]
    if not top:
        return ""

    cands: List[L] = []
    for ln in top:
        if not _looks_like_title_text(ln.text):
            continue
        # If we have codes, title should be clearly above the first code on the page.
        if code_min_y0 is not None:
            if ln.y1 > code_min_y0 - 6.0:
                continue

        # Promote prominence, but don't require extreme size; some layouts use modest bold titles.
        prominent = (
            ln.size >= max(median + 1.0, small + 2.0)
            or ln.bold
            or ln.non_black
            or ln.size >= (large - 2.5)
        )
        if not prominent:
            continue

        # If there are no red annotations at all, be conservative about black text being a title.
        if not has_any_red and not ln.non_black and not ln.bold:
            continue

        cands.append(ln)

    if not cands:
        return ""

    def score(l: L) -> float:
        span = max(0.0, l.x1 - l.x0)
        # Higher score is better.
        return (
            4.0 * l.size
            + (2.0 if l.bold else 0.0)
            + (1.5 if l.non_black else 0.0)
            + 0.002 * span
            - 0.02 * l.x0
            - 0.01 * l.y0
        )

    cands.sort(key=score, reverse=True)
    best = cands[0]

    # Join wrapped title lines with very similar styling directly below.
    same = [best]
    for ln in cands[1:]:
        if abs(ln.size - best.size) > 1.0:
            continue
        if abs(ln.x0 - best.x0) > 30.0:
            continue
        if 0 < (ln.y0 - best.y0) <= 20.0:
            same.append(ln)

    same.sort(key=lambda l: l.y0)
    title = " ".join(s.text for s in same).strip()
    title = re.sub(r"\s+", " ", title)
    return title


def _is_labelish_black(ln: L, st: Dict[str, float]) -> bool:
    if not ln.text:
        return False
    t = ln.text.strip()
    if not t or t.startswith("["):
        return False
    if ln.non_black:
        return False
    # Avoid chrome/title-like lines in the very top band.
    if ln.size >= st["large"] - 0.6 and ln.y0 <= 150:
        return False
    if not any(ch.isalnum() for ch in t):
        return False
    if len(t) <= 1:
        return False
    return True


def _is_labelish_relaxed(ln: L, st: Dict[str, float]) -> bool:
    # Used only in tight proximity searches; allows colored labels that look like prompts/headers.
    if not ln.text:
        return False
    t = ln.text.strip()
    if not t or t.startswith("["):
        return False
    if not any(ch.isalnum() for ch in t):
        return False
    if len(t) <= 1:
        return False
    # Still avoid very top chrome-like lines.
    if ln.y0 <= 20 and ln.size >= st["large"] - 0.5:
        return False
    # Non-black needs extra signal to avoid picking answer options.
    if ln.non_black and not (ln.bold or ("?" in t) or t.endswith(":") or len(t.split()) >= 4):
        return False
    return True


def _collect_wrapped(
    lines: List[L],
    anchor_idx: int,
    st: Dict[str, float],
    stop_y: float,
    *,
    relaxed: bool = False,
) -> str:
    anchor = lines[anchor_idx]
    idxs = [anchor_idx]

    def is_ok(b: L) -> bool:
        return _is_labelish_relaxed(b, st) if relaxed else _is_labelish_black(b, st)

    def ok_neighbor(a: L, b: L) -> bool:
        if not is_ok(b):
            return False
        if b.y0 >= stop_y - 0.5:
            return False
        if abs(b.size - a.size) > 1.3:
            return False
        if abs(b.x0 - a.x0) > 34.0:
            return False
        if abs(b.y0 - a.y0) > 17.0:
            return False
        return True

    # upward
    cur = anchor
    i = anchor_idx - 1
    while i >= 0:
        b = lines[i]
        if not ok_neighbor(cur, b):
            break
        idxs.append(i)
        cur = b
        i -= 1

    # downward
    cur = anchor
    i = anchor_idx + 1
    while i < len(lines):
        b = lines[i]
        if not ok_neighbor(cur, b):
            break
        idxs.append(i)
        cur = b
        i += 1

    idxs = sorted(set(idxs))
    txt = " ".join(lines[i].text.strip() for i in idxs).strip()
    return re.sub(r"\s+", " ", txt)


def _same_row(a: L, b: L) -> bool:
    # Consider same-row if vertical overlap is meaningful or centers are close.
    if a.y1 < b.y0 or b.y1 < a.y0:
        return False
    ac = 0.5 * (a.y0 + a.y1)
    bc = 0.5 * (b.y0 + b.y1)
    return abs(ac - bc) <= 7.0


def _best_label_same_line_left(lines: List[L], code_idx: int, st: Dict[str, float]) -> str:
    code = lines[code_idx]
    best_i = None
    best_score = None
    # Search within a window around the code index; lines are typically reading-order.
    start = max(0, code_idx - 25)
    end = min(len(lines), code_idx + 15)
    for i in range(start, end):
        if i == code_idx:
            continue
        ln = lines[i]
        if not _is_labelish_relaxed(ln, st):
            continue
        if not _same_row(ln, code):
            continue
        if ln.x1 > code.x0 + 2.0:
            continue
        dx = code.x0 - ln.x1
        if dx < 0:
            continue
        if dx > 320.0:
            continue
        # Prefer closer left labels; mildly prefer black labels.
        score = dx + (10.0 if ln.non_black else 0.0) + (3.0 if not ln.bold else 0.0)
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    if best_i is None:
        return ""
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0 + 1000.0, relaxed=True)


def _row_label_same_row(lines: List[L], code_idx: int, st: Dict[str, float]) -> str:
    # For table-like pages: find the left-most meaningful row label on the same row.
    code = lines[code_idx]
    best_i = None
    best_score = None
    start = max(0, code_idx - 60)
    end = min(len(lines), code_idx + 40)
    for i in range(start, end):
        ln = lines[i]
        if not _is_labelish_relaxed(ln, st):
            continue
        if not _same_row(ln, code):
            continue
        if ln.x1 > code.x0 - 8.0:
            continue
        dx = code.x0 - ln.x1
        if dx < 0 or dx > 520.0:
            continue
        # Prefer farther-left row headers (smaller x0), but not extremely far.
        score = 0.7 * dx + 0.4 * ln.x0 + (8.0 if ln.non_black else 0.0)
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    if best_i is None:
        return ""
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0 + 1000.0, relaxed=True)


def _best_label_for_code(lines: List[L], code_idx: int, st: Dict[str, float]) -> str:
    code = lines[code_idx]
    width = st["width"]
    height = st["height"]

    # 1) Same-line left label (fixes layouts where label sits left of the bracket id).
    left = _best_label_same_line_left(lines, code_idx, st)
    if left:
        return left

    # 2) Upward search in reading order.
    best_i = None
    best_score = None

    max_dy = max(240.0, 0.38 * height)
    for i in range(code_idx - 1, -1, -1):
        ln = lines[i]
        if not _is_labelish_black(ln, st):
            continue
        dy = code.y0 - ln.y0
        if dy <= 0:
            continue
        if dy > max_dy:
            break

        if code.x0 <= width * 0.42:
            xdist = abs(code.x0 - ln.x0)
        else:
            if ln.x1 <= code.x0:
                xdist = code.x0 - ln.x1
            else:
                xdist = abs(code.x0 - ln.x0)

        bold_bonus = -10.0 if ln.bold else 0.0
        small_bonus = -5.0 if ln.size <= st["small"] + 0.8 else 0.0
        score = dy + 0.30 * xdist + bold_bonus + small_bonus

        if dy > 160 and xdist > 120:
            score += 35.0

        if best_score is None or score < best_score:
            best_score = score
            best_i = i

        if dy < 28 and xdist < 35:
            break

    if best_i is None:
        # 3) Tight nearby relaxed fallback (colored question prompts, etc.)
        # Look a bit above and left; keep it strict to avoid options/values.
        best_j = None
        best_s = None
        for j, ln in enumerate(lines):
            if not _is_labelish_relaxed(ln, st):
                continue
            if ln.y0 >= code.y0 + 1.0:
                continue
            dy = code.y0 - ln.y0
            if dy <= 0 or dy > max(120.0, 0.18 * height):
                continue
            # prefer same column/left proximity
            xdist = abs(code.x0 - ln.x0)
            if ln.x1 <= code.x0:
                xdist = min(xdist, code.x0 - ln.x1)
            score = dy + 0.25 * xdist + (8.0 if ln.non_black and not ln.bold else 0.0)
            if best_s is None or score < best_s:
                best_s = score
                best_j = j
        if best_j is None:
            return ""
        label = _collect_wrapped(lines, best_j, st, stop_y=code.y0, relaxed=True)
    else:
        label = _collect_wrapped(lines, best_i, st, stop_y=code.y0, relaxed=False)

    label = re.sub(r"\s+", " ", (label or "").strip())
    if not label:
        return ""

    # 4) If we accidentally grabbed a timepoint header as a label, try to combine with row label.
    if _TIMEPOINT_RE.search(label) and len(label.split()) <= 3:
        row = _row_label_same_row(lines, code_idx, st)
        row = re.sub(r"\s+", " ", (row or "").strip())
        if row and row.lower() != label.lower():
            return re.sub(r"\s+", " ", (row + " " + label).strip())

    return label


def _row_bands(lines: List[L], st: Dict[str, float]) -> List[Tuple[float, float, str, float]]:
    # Use "Row <n>" as a strong landmark when present.
    rows: List[L] = []
    for ln in lines:
        if not ln.text or ln.text.startswith("["):
            continue
        if ln.non_black:
            continue
        if not ln.bold:
            continue
        if re.search(r"(?i)\brow\b\s*\d+", ln.text):
            rows.append(ln)
    rows.sort(key=lambda l: l.y0)
    if not rows:
        return []
    bands: List[Tuple[float, float, str, float]] = []
    for idx, r in enumerate(rows):
        y0 = r.y0 - 2.0
        y1 = (rows[idx + 1].y0 - 2.0) if idx + 1 < len(rows) else (st["height"] + 1.0)
        bands.append((y0, y1, re.sub(r"\s+", " ", r.text.strip()), r.x0))
    return bands


def _build_table_headers(
    lines: List[L],
    st: Dict[str, float],
    row_bands: List[Tuple[float, float, str, float]],
) -> Dict[int, str]:
    if not row_bands:
        return {}
    first_row_y = min(y0 for (y0, _y1, _txt, _x0) in row_bands)
    height = st["height"]
    median = st["median"]
    small = st["small"]

    # Candidate header region: below top chrome, above first row band.
    top_cut = min(140.0, 0.20 * height)
    cands: List[L] = []
    for ln in lines:
        if not ln.text or ln.text.startswith("["):
            continue
        if ln.y0 <= top_cut or ln.y0 >= first_row_y - 6.0:
            continue
        t = ln.text.strip()
        if not any(ch.isalnum() for ch in t):
            continue
        # Allow colored headers; require some signal to avoid picking random body text.
        if not (ln.bold or ln.size >= median + 0.4 or (ln.non_black and ln.size >= small + 1.0)):
            continue
        cands.append(ln)
    if not cands:
        return {}

    # Bin by x0 into ~22pt buckets (slightly tighter than 25 to reduce bleed).
    buckets: Dict[int, List[L]] = {}
    for ln in cands:
        b = int((ln.x0 + 0.01) // 22)
        buckets.setdefault(b, []).append(ln)

    headers: Dict[int, str] = {}
    for b, blns in buckets.items():
        blns.sort(key=lambda l: (l.y0, l.x0))
        # Merge wrapped headers within the bucket by y proximity.
        merged: List[List[L]] = []
        for ln in blns:
            placed = False
            for grp in merged:
                last = grp[-1]
                if abs(ln.x0 - last.x0) <= 30.0 and 0 <= (ln.y0 - last.y0) <= 18.0:
                    grp.append(ln)
                    placed = True
                    break
            if not placed:
                merged.append([ln])
        # Use the top-most group as the column header.
        merged.sort(key=lambda g: min(x.y0 for x in g))
        grp0 = merged[0]
        txt = " ".join(x.text for x in grp0).strip()
        txt = re.sub(r"\s+", " ", txt)
        if txt and any(ch.isalnum() for ch in txt):
            headers[b] = txt
    return headers


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    current_form = ""

    for page_idx0, raw_lines in pages:
        lines = _to_L(raw_lines)
        if not lines:
            continue

        lines = _merge_bracket_fragments(lines)
        st = _page_stats(lines)

        toc_like = _is_toc_like(lines)

        # Detect bracket annotations.
        has_any_red = any(ln.text.startswith("[") and ln.non_black for ln in lines)

        # Identify code tokens (prefer colored/red; fallback to black if none).
        code_idxs_red: List[int] = []
        code_idxs_black: List[int] = []
        for i, ln in enumerate(lines):
            t = (ln.text or "").strip()
            if not (t.startswith("[") and t.endswith("]")):
                continue
            if _is_tech_bracket(t):
                continue
            if not _is_code_token(t):
                continue
            if ln.non_black:
                code_idxs_red.append(i)
            else:
                code_idxs_black.append(i)

        code_idxs = code_idxs_red if code_idxs_red else code_idxs_black
        code_min_y0 = min((lines[i].y0 for i in code_idxs), default=None)

        # Update form title context (but don't let TOC-like pages poison carryover).
        title = _title_candidate(
            lines,
            st,
            has_any_red=has_any_red,
            code_min_y0=code_min_y0,
            allow_update=(not toc_like),
        )
        if title:
            current_form = title

        if not code_idxs:
            continue

        # Table-mode: row bands + headers + multiple code columns.
        row_bands = _row_bands(lines, st)
        headers = _build_table_headers(lines, st, row_bands)
        distinct_code_bins = set(int((lines[i].x0 + 0.01) // 22) for i in code_idxs)

        table_mode = bool(row_bands) and len(headers) >= 3 and len(distinct_code_bins) >= 3

        # Identify likely non-data "identifier" columns in table mode (short header on far left).
        identifier_bins = set()
        if table_mode and headers:
            width = st["width"]
            bins_sorted = sorted(headers.items(), key=lambda kv: kv[0])
            leftmost_bin, leftmost_header = bins_sorted[0]
            words = [w for w in re.split(r"\s+", leftmost_header.strip()) if w]
            has_q = "?" in leftmost_header
            has_colon = ":" in leftmost_header
            # Estimate x position of bin via bin index.
            approx_x0 = leftmost_bin * 22.0
            longish_headers = 0
            for _b, h in headers.items():
                ww = [w for w in re.split(r"\s+", h.strip()) if w]
                if ("?" in h) or h.endswith(":") or len(ww) >= 3:
                    longish_headers += 1
            if approx_x0 <= width * 0.32 and len(words) <= 2 and (not has_q) and (not has_colon) and longish_headers >= 2:
                identifier_bins.add(leftmost_bin)

        def find_row_label(y: float) -> str:
            for y0, y1, txt, _x0 in row_bands:
                if y0 <= y < y1:
                    return txt
            return ""

        for ci in code_idxs:
            code_ln = lines[ci]
            field_name = ""

            if table_mode:
                col_bin = int((code_ln.x0 + 0.01) // 22)
                if col_bin in identifier_bins:
                    continue
                header = headers.get(col_bin, "")
                rowtxt = find_row_label(code_ln.y0)
                if header:
                    field_name = (rowtxt + " " + header).strip() if rowtxt else header

            if not field_name:
                field_name = _best_label_for_code(lines, ci, st)

            if not field_name and table_mode:
                col_bin = int((code_ln.x0 + 0.01) // 22)
                if col_bin not in identifier_bins:
                    field_name = headers.get(col_bin, "")

            field_name = re.sub(r"\s+", " ", (field_name or "").strip())
            if not field_name:
                continue

            form_name = (current_form or "").strip()

            key = (page_idx0 + 1, form_name, field_name)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": field_name, "page": page_idx0 + 1})

    return out
```
