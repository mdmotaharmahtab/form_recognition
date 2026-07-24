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
_ROW_GENERIC_RE = re.compile(r"(?i)^\s*row\s*\d+\s*$")
_SECTION_NUM_RE = re.compile(r"^\s*\d+(\.\d+)*\.\s+\S")


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
    t = (text or "").strip()
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
    secnumlike = 0
    for ln in colored:
        if re.match(r"^\s*\d+(\.\d+)*\.", ln.text):
            numlike += 1
        if _SECTION_NUM_RE.match(ln.text):
            secnumlike += 1

    # Prefer strict section-number pattern; fallback to dotted list.
    if secnumlike >= max(10, int(0.55 * len(colored))):
        return True
    return numlike >= max(8, int(0.5 * len(colored)))


def _looks_like_title_text(t: str) -> bool:
    tt = (t or "").strip()
    if not tt:
        return False
    if tt.startswith("["):
        return False
    if "?" in tt:
        return False
    if len(tt) <= 2:
        return False
    # Avoid pure section numbering line as "title" (TOC pages already handled, but keep safe).
    if _SECTION_NUM_RE.match(tt):
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

    top_band_y = min(190.0, 0.25 * height)
    top = [ln for ln in lines if ln.text and ln.y0 <= top_band_y]
    if not top:
        return ""

    cands: List[L] = []
    for ln in top:
        if not _looks_like_title_text(ln.text):
            continue

        # Avoid ultra-top chrome unless extremely prominent.
        if ln.y0 <= 22.0:
            if not (ln.size >= (large - 0.3) or (ln.non_black and ln.size >= median + 2.0) or ln.bold):
                continue

        # If we have codes, title should be above the first code on the page.
        if code_min_y0 is not None and ln.y1 > code_min_y0 - 6.0:
            continue

        # Titles usually have some horizontal span.
        span = max(0.0, ln.x1 - ln.x0)
        if span < max(110.0, 0.22 * width):
            # Allow shorter spans only if the line is clearly a title by style.
            if not (ln.size >= median + 2.0 or (ln.non_black and ln.size >= median + 1.0) or (ln.bold and ln.size >= median + 1.2)):
                continue

        # Promote prominence, but don't require extreme size.
        prominent = (
            ln.size >= max(median + 1.0, small + 2.0)
            or ln.bold
            or ln.non_black
            or ln.size >= (large - 2.5)
        )
        if not prominent:
            continue

        # If there are no red annotations at all, be conservative about black text being a title.
        if not has_any_red and not ln.non_black and not ln.bold and ln.size < median + 1.5:
            continue

        # Avoid picking something that looks like a per-field label (too narrow, too left, too close to body).
        cands.append(ln)

    if not cands:
        return ""

    # Prefer titles somewhat below extreme top, and closer to the first code (common header+title layouts).
    target_y = 80.0
    if code_min_y0 is not None:
        target_y = max(38.0, min(110.0, code_min_y0 - 34.0))

    def score(l: L) -> float:
        span = max(0.0, l.x1 - l.x0)
        y_term = -0.018 * abs(l.y0 - target_y)
        # Higher is better.
        return (
            4.0 * l.size
            + (2.0 if l.bold else 0.0)
            + (1.6 if l.non_black else 0.0)
            + 0.0022 * span
            + y_term
            - 0.017 * l.x0
        )

    cands.sort(key=score, reverse=True)
    best = cands[0]

    # Join wrapped title lines directly below with similar styling.
    same = [best]
    for ln in cands[1:]:
        if abs(ln.size - best.size) > 1.0:
            continue
        if abs(ln.x0 - best.x0) > 34.0:
            continue
        if 0 < (ln.y0 - best.y0) <= 22.0:
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
    if ln.size >= st["large"] - 0.6 and ln.y0 <= 150:
        return False
    if not any(ch.isalnum() for ch in t):
        return False
    if len(t) <= 1:
        return False
    return True


def _is_labelish_relaxed(ln: L, st: Dict[str, float]) -> bool:
    if not ln.text:
        return False
    t = ln.text.strip()
    if not t or t.startswith("["):
        return False
    if not any(ch.isalnum() for ch in t):
        return False
    if len(t) <= 1:
        return False
    if ln.y0 <= 20 and ln.size >= st["large"] - 0.5:
        return False
    if ln.non_black and not (ln.bold or ("?" in t) or t.endswith(":") or len(t.split()) >= 4 or ln.size >= st["median"] + 0.5):
        return False
    return True


def _is_labelish_upward(ln: L, st: Dict[str, float]) -> bool:
    # For upward scans: allow colored prompts when they look like prompts/headers, not options.
    if not ln.text:
        return False
    t = ln.text.strip()
    if not t or t.startswith("["):
        return False
    if not any(ch.isalnum() for ch in t):
        return False
    if len(t) <= 1:
        return False

    # Avoid very top chrome-ish.
    if ln.y0 <= 20 and ln.size >= st["large"] - 0.4:
        return False

    if not ln.non_black:
        return _is_labelish_black(ln, st)

    # colored: require signal
    words = [w for w in re.split(r"\s+", t) if w]
    return bool(
        ln.bold
        or ("?" in t)
        or t.endswith(":")
        or len(words) >= 4
        or (ln.size >= st["median"] + 0.6)
    )


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
        if abs(b.x0 - a.x0) > 36.0:
            return False
        if abs(b.y0 - a.y0) > 18.0:
            return False
        return True

    cur = anchor
    i = anchor_idx - 1
    while i >= 0:
        b = lines[i]
        if not ok_neighbor(cur, b):
            break
        idxs.append(i)
        cur = b
        i -= 1

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
    if a.y1 < b.y0 or b.y1 < a.y0:
        return False
    ac = 0.5 * (a.y0 + a.y1)
    bc = 0.5 * (b.y0 + b.y1)
    return abs(ac - bc) <= 7.0


def _best_label_same_line_left(lines: List[L], code_idx: int, st: Dict[str, float]) -> str:
    code = lines[code_idx]
    best_i = None
    best_score = None
    start = max(0, code_idx - 40)
    end = min(len(lines), code_idx + 20)
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
        if dx > 520.0:
            continue
        score = dx + (9.0 if ln.non_black else 0.0) + (2.5 if not ln.bold else 0.0)
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    if best_i is None:
        return ""
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0 + 1000.0, relaxed=True)


def _row_label_same_row(lines: List[L], code_idx: int, st: Dict[str, float]) -> str:
    code = lines[code_idx]
    best_i = None
    best_score = None
    start = max(0, code_idx - 90)
    end = min(len(lines), code_idx + 60)
    for i in range(start, end):
        ln = lines[i]
        if not _is_labelish_relaxed(ln, st):
            continue
        if not _same_row(ln, code):
            continue
        if ln.x1 > code.x0 - 8.0:
            continue
        dx = code.x0 - ln.x1
        if dx < 0 or dx > 640.0:
            continue
        score = 0.65 * dx + 0.45 * ln.x0 + (7.0 if ln.non_black else 0.0)
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    if best_i is None:
        return ""
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0 + 1000.0, relaxed=True)


def _has_peer_codes_same_column(lines: List[L], code_idx: int, st: Dict[str, float]) -> bool:
    # Detect radio/checkbox option lists: several codes aligned by x0.
    code = lines[code_idx]
    width = st["width"]
    if width <= 0:
        return False
    # Option lists tend to have codes not on the far right margin.
    if code.x0 > width * 0.70:
        return False
    count = 0
    for j in range(max(0, code_idx - 35), min(len(lines), code_idx + 36)):
        if j == code_idx:
            continue
        t = lines[j].text.strip()
        if not (t.startswith("[") and t.endswith("]")):
            continue
        if _is_tech_bracket(t) or not _is_code_token(t):
            continue
        if abs(lines[j].x0 - code.x0) <= 18.0 and abs(lines[j].y0 - code.y0) <= 90.0:
            count += 1
            if count >= 2:
                return True
    return False


def _is_option_like_fieldname(field_name: str, code_ln: L, st: Dict[str, float], peer_codes: bool) -> bool:
    t = re.sub(r"\s+", " ", (field_name or "").strip())
    if not t:
        return False
    width = st["width"]
    if width <= 0:
        return False

    # Avoid misclassifying normal "label -> code on far right" fields like "Visit Date".
    if code_ln.x0 > width * 0.66:
        return False

    words = [w for w in re.split(r"\s+", t) if w]
    if len(words) > 3:
        return False
    if "?" in t or t.endswith(":"):
        return False

    # Strong signal: timepoint-like values.
    if _TIMEPOINT_RE.search(t):
        return True

    # Another signal: clustered codes aligned in a column (options).
    if peer_codes and len(words) <= 3:
        return True

    return False


def _best_prompt_for_option(lines: List[L], code_idx: int, st: Dict[str, float]) -> str:
    # Find a nearby prompt/header above a set of options; return prompt only.
    code = lines[code_idx]
    width = st["width"]
    height = st["height"]
    median = st["median"]

    best_i = None
    best_s = None
    max_dy = max(140.0, 0.22 * height)

    for i in range(code_idx - 1, -1, -1):
        ln = lines[i]
        if not _is_labelish_relaxed(ln, st):
            continue
        if ln.y0 >= code.y0:
            continue
        dy = code.y0 - ln.y0
        if dy <= 0 or dy > max_dy:
            break

        # Prompts tend to start in the left/middle region.
        if ln.x0 > width * 0.55:
            continue

        t = ln.text.strip()
        words = [w for w in re.split(r"\s+", t) if w]

        # Require some prompt signal, but allow short bold prompts too.
        prompty = bool(("?" in t) or t.endswith(":") or len(words) >= 3 or ln.bold or (ln.size >= median + 0.3))
        if not prompty:
            continue

        xdist = 0.0
        if ln.x1 <= code.x0:
            xdist = code.x0 - ln.x1
        else:
            xdist = abs(code.x0 - ln.x0)

        s = dy + 0.18 * xdist + 0.02 * ln.x0 + (6.0 if ln.non_black and not ln.bold else 0.0)
        if best_s is None or s < best_s:
            best_s = s
            best_i = i

        if dy < 24 and ln.x0 <= width * 0.35:
            # very close prompt; stop early
            break

    if best_i is None:
        return ""
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0, relaxed=True)


def _best_label_for_code(lines: List[L], code_idx: int, st: Dict[str, float]) -> str:
    code = lines[code_idx]
    width = st["width"]
    height = st["height"]

    # 1) Same-line left label.
    left = _best_label_same_line_left(lines, code_idx, st)
    if left:
        return left

    # 2) Upward search (black + prompty colored).
    best_i = None
    best_score = None
    max_dy = max(240.0, 0.38 * height)

    for i in range(code_idx - 1, -1, -1):
        ln = lines[i]
        if not _is_labelish_upward(ln, st):
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
        score = dy + 0.28 * xdist + bold_bonus + small_bonus + (6.0 if ln.non_black and not ln.bold else 0.0)

        if dy > 160 and xdist > 120:
            score += 35.0

        if best_score is None or score < best_score:
            best_score = score
            best_i = i

        if dy < 28 and xdist < 35:
            break

    label = ""
    if best_i is not None:
        label = _collect_wrapped(lines, best_i, st, stop_y=code.y0, relaxed=(lines[best_i].non_black))
    else:
        # 3) Tight nearby relaxed fallback.
        best_j = None
        best_s = None
        for j, ln in enumerate(lines):
            if not _is_labelish_relaxed(ln, st):
                continue
            if ln.y0 >= code.y0 + 1.0:
                continue
            dy = code.y0 - ln.y0
            if dy <= 0 or dy > max(135.0, 0.20 * height):
                continue
            xdist = abs(code.x0 - ln.x0)
            if ln.x1 <= code.x0:
                xdist = min(xdist, code.x0 - ln.x1)
            s = dy + 0.23 * xdist + (8.0 if ln.non_black and not ln.bold else 0.0)
            if best_s is None or s < best_s:
                best_s = s
                best_j = j
        if best_j is not None:
            label = _collect_wrapped(lines, best_j, st, stop_y=code.y0, relaxed=True)

    label = re.sub(r"\s+", " ", (label or "").strip())
    if not label:
        return ""

    # 4) If label looks like an option value, try to find the prompt above and use that instead.
    peer_codes = _has_peer_codes_same_column(lines, code_idx, st)
    if _is_option_like_fieldname(label, code, st, peer_codes):
        prompt = _best_prompt_for_option(lines, code_idx, st)
        prompt = re.sub(r"\s+", " ", (prompt or "").strip())
        if prompt and prompt.lower() != label.lower():
            return prompt
        return ""

    # 5) If we accidentally grabbed a short timepoint-like header/value, prefer row label on same row.
    if _TIMEPOINT_RE.search(label) and len(label.split()) <= 3:
        row = _row_label_same_row(lines, code_idx, st)
        row = re.sub(r"\s+", " ", (row or "").strip())
        if row and row.lower() != label.lower():
            return row

    # 6) If a far-left same-row label exists and is more descriptive, prefer it (table-ish layouts).
    row2 = _row_label_same_row(lines, code_idx, st)
    row2 = re.sub(r"\s+", " ", (row2 or "").strip())
    if row2:
        # Prefer the row label when it is clearly longer/more prompt-like.
        w_label = len([w for w in label.split() if w])
        w_row2 = len([w for w in row2.split() if w])
        if w_row2 >= w_label + 2 or (("?" in row2 or row2.endswith(":")) and ("?" not in label and not label.endswith(":"))):
            return row2

    return label


def _row_bands(lines: List[L], st: Dict[str, float]) -> List[Tuple[float, float, str, float]]:
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
) -> Tuple[Dict[int, str], float]:
    if not row_bands:
        return {}, 0.0
    first_row_y = min(y0 for (y0, _y1, _txt, _x0) in row_bands)
    height = st["height"]
    median = st["median"]
    small = st["small"]

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
        # Allow colored headers; allow non-bold if size suggests header-ish.
        if not (ln.bold or ln.size >= median + 0.25 or (ln.non_black and ln.size >= small + 0.8) or ("?" in t) or t.endswith(":")):
            continue
        cands.append(ln)
    if not cands:
        return {}, first_row_y

    # Bin by x0 into ~22pt buckets.
    buckets: Dict[int, List[L]] = {}
    for ln in cands:
        b = int((ln.x0 + 0.01) // 22)
        buckets.setdefault(b, []).append(ln)

    headers: Dict[int, str] = {}
    for b, blns in buckets.items():
        blns.sort(key=lambda l: (l.y0, l.x0))
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
        merged.sort(key=lambda g: min(x.y0 for x in g))
        grp0 = merged[0]
        txt = " ".join(x.text for x in grp0).strip()
        txt = re.sub(r"\s+", " ", txt)
        if txt and any(ch.isalnum() for ch in txt):
            headers[b] = txt
    return headers, first_row_y


def _normalize_rowtxt(rowtxt: str) -> str:
    t = re.sub(r"\s+", " ", (rowtxt or "").strip())
    if not t:
        return ""
    if _ROW_GENERIC_RE.match(t):
        return ""
    return t


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
        width = st["width"]

        toc_like = _is_toc_like(lines)

        has_any_red = any(ln.text.startswith("[") and ln.text.endswith("]") and ln.non_black for ln in lines)

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

        row_bands = _row_bands(lines, st)
        headers, first_row_y = _build_table_headers(lines, st, row_bands)
        distinct_code_bins = set(int((lines[i].x0 + 0.01) // 22) for i in code_idxs)

        table_mode = bool(row_bands) and len(headers) >= 3 and len(distinct_code_bins) >= 3

        identifier_bins = set()
        if table_mode and headers:
            bins_sorted = sorted(headers.items(), key=lambda kv: kv[0])
            leftmost_bin, leftmost_header = bins_sorted[0]
            words = [w for w in re.split(r"\s+", leftmost_header.strip()) if w]
            has_q = "?" in leftmost_header
            has_colon = leftmost_header.endswith(":") or (":" in leftmost_header)
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

        form_name = (current_form or "").strip()

        for ci in code_idxs:
            code_ln = lines[ci]
            field_name = ""

            in_table_region = table_mode and (code_ln.y0 >= (first_row_y - 4.0))

            if in_table_region:
                col_bin = int((code_ln.x0 + 0.01) // 22)
                if col_bin in identifier_bins:
                    continue
                header = headers.get(col_bin, "")
                if header:
                    rowtxt = _normalize_rowtxt(find_row_label(code_ln.y0))
                    # If rowtxt is meaningful (not generic "Row N"), keep it; otherwise, just the header.
                    field_name = (rowtxt + " " + header).strip() if rowtxt else header
                else:
                    # In table regions, avoid falling back to row labels/options that create false fields.
                    continue
            else:
                field_name = _best_label_for_code(lines, ci, st)

            field_name = re.sub(r"\s+", " ", (field_name or "").strip())
            if not field_name:
                continue

            # Drop generic row-only labels if any slipped through.
            if _ROW_GENERIC_RE.match(field_name.strip()):
                continue

            # Drop section-number TOC-like entries if ever selected as a "field".
            if _SECTION_NUM_RE.match(field_name):
                continue

            # Avoid returning timepoint option values as fields when code isn't on far right.
            if _TIMEPOINT_RE.search(field_name) and len(field_name.split()) <= 3 and code_ln.x0 <= width * 0.66:
                continue

            key = (page_idx0 + 1, form_name, field_name)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": field_name, "page": page_idx0 + 1})

    return out
