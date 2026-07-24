```python
# Observed layout: most data-entry fields have a black human label and a nearby red
# bracketed machine id (e.g. [XXXX]); pages also have a prominent top title (often
# larger colored text) that serves as the form/section name and can be carried forward.
# Strategy: detect form titles from top-band prominence; detect fields via red code tokens
# (excluding [TYPE:...]/[VISIBILITY:...]); attach each code to the best label above by
# geometry, with a table-mode fallback using column headers + printed Row labels.

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


_CODE_TOKEN_RE = re.compile(r"^\[[^\s\]:]{2,40}\]$")
_TECH_BRACKET_RE = re.compile(r"^\[[A-Z][A-Z_ ]*:")


def _to_L(lines) -> List[L]:
    out = []
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
            # absorb a short run of fragments until we see a closing bracket
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
                # Avoid swallowing unrelated bracketed tokens far apart
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
    t = text.strip()
    if not _CODE_TOKEN_RE.match(t):
        return False
    # exclude known template tech annotations which still match token-ish shapes
    # (kept structural: colon-based already excluded)
    return True


def _is_toc_like(lines: List[L]) -> bool:
    # TOC pages have many similarly styled colored entries and no red bracket annotations.
    colored = [ln for ln in lines if ln.text and ln.non_black]
    redish_brackets = [ln for ln in lines if ln.text.startswith("[") and ln.non_black]
    if redish_brackets:
        return False
    if len(colored) < 12:
        return False
    # many entries start with numbering patterns; allow language-agnostic digits/dots.
    numlike = 0
    for ln in colored:
        if re.match(r"^\s*\d+(\.\d+)*\.", ln.text):
            numlike += 1
    return numlike >= max(8, int(0.5 * len(colored)))


def _title_candidate(lines: List[L], st: Dict[str, float], has_any_red: bool) -> str:
    width = st["width"]
    large = st["large"]
    small = st["small"]
    # look in top band, left-ish
    top = [ln for ln in lines if ln.text and ln.y0 <= 130 and ln.x0 <= width * 0.70]
    if not top:
        return ""
    # promote prominent lines (bigger font and often colored)
    cands = []
    for ln in top:
        if ln.text.startswith("["):
            continue
        if ln.size < max(small + 2.5, large - 2.0):
            continue
        # if this page has no red annotations at all, be conservative (avoid setting title from cover/TOC)
        if not has_any_red and not ln.non_black:
            continue
        cands.append(ln)
    if not cands:
        # fallback: biggest colored line in top band
        c2 = [ln for ln in top if ln.non_black and ln.size >= max(small + 2.0, large - 3.0)]
        if not c2:
            return ""
        cands = c2

    # choose best: biggest size, then leftmost x, then highest y
    cands.sort(key=lambda l: (-l.size, l.x0, l.y0))
    best = cands[0]
    # join nearby lines that look like wrapped title (same style, close y, similar x range)
    same = [best]
    for ln in cands[1:]:
        if abs(ln.size - best.size) > 0.8:
            continue
        if abs(ln.x0 - best.x0) > 25:
            continue
        if 0 < (ln.y0 - best.y0) <= 18:
            same.append(ln)
    same.sort(key=lambda l: l.y0)
    title = " ".join([s.text for s in same]).strip()
    return re.sub(r"\s+", " ", title)


def _is_labelish(ln: L, st: Dict[str, float]) -> bool:
    if not ln.text:
        return False
    if ln.text.startswith("["):
        return False
    if ln.non_black:
        return False  # options/values often grey/colored in samples
    if ln.size >= st["large"] - 0.6 and ln.y0 <= 150:
        return False  # likely title/chrome
    t = ln.text.strip()
    # require at least some letter/number in any script
    has_alnum = any(ch.isalnum() for ch in t)
    if not has_alnum:
        return False
    # avoid trivial one-token noise
    if len(t) <= 1:
        return False
    return True


def _collect_wrapped(lines: List[L], anchor_idx: int, st: Dict[str, float], stop_y: float) -> str:
    anchor = lines[anchor_idx]
    # expand up/down within tight geometry; do not cross stop_y (the code y)
    idxs = [anchor_idx]

    def ok_neighbor(a: L, b: L) -> bool:
        if not _is_labelish(b, st):
            return False
        if b.y0 >= stop_y - 0.5:
            return False
        if abs(b.size - a.size) > 1.2:
            return False
        if abs(b.x0 - a.x0) > 30:
            return False
        # typical wrap spacing
        if abs(b.y0 - a.y0) > 16:
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

    # downward (rare, but safe if wrap continues)
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


def _best_label_for_code(lines: List[L], code_idx: int, st: Dict[str, float]) -> str:
    code = lines[code_idx]
    width = st["width"]

    best_i = None
    best_score = None
    for i in range(code_idx - 1, -1, -1):
        ln = lines[i]
        if not _is_labelish(ln, st):
            continue
        dy = code.y0 - ln.y0
        if dy <= 0:
            continue
        if dy > 900:  # allow far, but bounded
            break

        # x relationship depends on which side the code is on
        if code.x0 <= width * 0.42:
            xdist = abs(code.x0 - ln.x0)
        else:
            # prefer label on the left side
            if ln.x1 <= code.x0:
                xdist = code.x0 - ln.x1
            else:
                xdist = abs(code.x0 - ln.x0)

        bold_bonus = -10.0 if ln.bold else 0.0
        small_bonus = -5.0 if ln.size <= st["small"] + 0.8 else 0.0
        score = dy + 0.30 * xdist + bold_bonus + small_bonus

        # mild penalty if label is very far in y but not well aligned in x
        if dy > 200 and xdist > 120:
            score += 40

        if best_score is None or score < best_score:
            best_score = score
            best_i = i

        # early stop if we found a very close label in same column
        if dy < 28 and xdist < 35:
            break

    if best_i is None:
        return ""
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0)


def _build_table_headers(lines: List[L], st: Dict[str, float], row_labels: List[Tuple[float, float, str]]) -> Dict[int, str]:
    # Build column header text by x-binning lines above the first row band.
    if not row_labels:
        return {}
    first_row_y = min(y0 for (y0, y1, _) in row_labels)
    # candidate header region: below title band, above first row label
    cands = []
    for ln in lines:
        if not ln.text or ln.text.startswith("["):
            continue
        if ln.non_black:
            continue
        if ln.y0 <= 120 or ln.y0 >= first_row_y - 8:
            continue
        # headers are typically larger than label font
        if ln.size < st["small"] + 1.0:
            continue
        cands.append(ln)
    if not cands:
        return {}

    # bin by x0 into ~25pt buckets
    buckets: Dict[int, List[L]] = {}
    for ln in cands:
        b = int((ln.x0 + 0.01) // 25)
        buckets.setdefault(b, []).append(ln)

    headers: Dict[int, str] = {}
    for b, blns in buckets.items():
        blns.sort(key=lambda l: (l.y0, l.x0))
        txt = " ".join(l.text for l in blns).strip()
        txt = re.sub(r"\s+", " ", txt)
        if txt and any(ch.isalnum() for ch in txt):
            headers[b] = txt
    return headers


def _row_bands(lines: List[L], st: Dict[str, float]) -> List[Tuple[float, float, str]]:
    # Use "Row <n>" as a template landmark when present.
    rows = []
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
    bands = []
    for idx, r in enumerate(rows):
        y0 = r.y0 - 2.0
        y1 = (rows[idx + 1].y0 - 2.0) if idx + 1 < len(rows) else (st["height"] + 1.0)
        bands.append((y0, y1, re.sub(r"\s+", " ", r.text.strip())))
    return bands


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

        if _is_toc_like(lines):
            # do not let TOC affect carried form context
            continue

        # Detect any red bracket-like annotations (field ids and tech notes)
        has_any_red = any(ln.text.startswith("[") and ln.non_black for ln in lines)

        # Determine/update form title for this page
        title = _title_candidate(lines, st, has_any_red=has_any_red)
        if title:
            current_form = title

        # Identify code tokens (data-entry fields), excluding tech annotations
        code_idxs = []
        for i, ln in enumerate(lines):
            if not ln.text.startswith("["):
                continue
            if not ln.non_black:
                continue
            t = ln.text.strip()
            if not (t.startswith("[") and t.endswith("]")):
                continue
            if _is_tech_bracket(t):
                continue
            if not _is_code_token(t):
                continue
            code_idxs.append(i)

        if not code_idxs:
            continue

        # Table-mode detection: multiple row bands and multiple code x-buckets
        row_labels = _row_bands(lines, st)
        headers = _build_table_headers(lines, st, row_labels)
        distinct_code_bins = set(int((lines[i].x0 + 0.01) // 25) for i in code_idxs)
        table_mode = bool(row_labels) and len(headers) >= 3 and len(distinct_code_bins) >= 3

        def find_row_label(y: float) -> str:
            for y0, y1, txt in row_labels:
                if y0 <= y < y1:
                    return txt
            return ""

        for ci in code_idxs:
            code_ln = lines[ci]
            field_name = ""

            if table_mode:
                col_bin = int((code_ln.x0 + 0.01) // 25)
                header = headers.get(col_bin, "")
                rowtxt = find_row_label(code_ln.y0)
                if header:
                    field_name = (rowtxt + " " + header).strip() if rowtxt else header

            if not field_name:
                field_name = _best_label_for_code(lines, ci, st)

            if not field_name and table_mode:
                # last-resort: header-only
                col_bin = int((code_ln.x0 + 0.01) // 25)
                field_name = headers.get(col_bin, "")

            field_name = re.sub(r"\s+", " ", (field_name or "").strip())
            form_name = (current_form or "").strip()

            if not field_name:
                continue
            if not form_name:
                # still emit, but try not to flood empties if a title exists later
                form_name = ""

            key = (page_idx0 + 1, form_name, field_name)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": field_name, "page": page_idx0 + 1})

    return out
```
