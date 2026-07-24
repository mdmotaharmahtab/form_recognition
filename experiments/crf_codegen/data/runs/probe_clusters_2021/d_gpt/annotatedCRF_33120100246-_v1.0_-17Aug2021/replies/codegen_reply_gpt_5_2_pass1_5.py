```python
import re
import statistics
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional, Set


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


def _is_tech_bracket(text: str) -> bool:
    t = (text or "").strip()
    if not (t.startswith("[") and t.endswith("]")):
        return False
    if ":" in t:
        return True
    return bool(_TECH_BRACKET_RE.match(t))


def _is_code_token(text: str) -> bool:
    return bool(_CODE_TOKEN_RE.match((text or "").strip()))


def _merge_bracket_fragments(lines: List[L]) -> List[L]:
    """
    Merge consecutive fragments that form a single bracket token, regardless of color.
    Common failure mode: scanned PDFs splitting a token like "[ABC" + "123]" into two lines.
    """
    merged: List[L] = []
    i = 0
    n = len(lines)

    def ok_piece(t: str) -> bool:
        if not t:
            return False
        # Allow token pieces with no whitespace.
        return not bool(re.search(r"\s", t))

    while i < n:
        cur = lines[i]
        t0 = (cur.text or "").strip()
        if t0.startswith("[") and (not t0.endswith("]")) and ok_piece(t0) and len(t0) >= 2:
            j = i + 1
            txt = t0
            x0, y0, x1, y1 = cur.x0, cur.y0, cur.x1, cur.y1
            size = cur.size
            bold = cur.bold
            nb = cur.non_black
            # Keep a tight spatial merge to avoid glomming unrelated text.
            while j < n:
                nxt = lines[j]
                t1 = (nxt.text or "").strip()
                if not t1:
                    j += 1
                    continue
                if not ok_piece(t1):
                    break
                # Fragments should share similar left edge (OCR often repeats x0).
                if abs(nxt.x0 - x0) > 6.0:
                    break
                # Prevent large vertical jumps.
                if (nxt.y0 - y1) > 26.0:
                    break
                # Avoid merging a new bracket start into an existing token.
                if t1.startswith("[") and "[" in txt:
                    break
                txt += t1
                x1 = max(x1, nxt.x1)
                y1 = max(y1, nxt.y1)
                size = max(size, nxt.size)
                bold = bold or nxt.bold
                nb = nb or nxt.non_black
                if txt.endswith("]"):
                    break
                j += 1

            if txt.endswith("]"):
                txt2 = txt.strip()
                # Only accept if it looks like a single bracketed token.
                if (txt2.startswith("[") and txt2.endswith("]")) and (len(txt2) <= 80) and (not re.search(r"\s", txt2)):
                    merged.append(L(txt2, x0, y0, x1, y1, size, bold, nb))
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


def _count_nontech_codes(lines: List[L]) -> int:
    c = 0
    for ln in lines:
        t = (ln.text or "").strip()
        if not (t.startswith("[") and t.endswith("]")):
            continue
        if _is_tech_bracket(t):
            continue
        if _is_code_token(t):
            c += 1
    return c


def _is_definition_only_page(lines: List[L]) -> bool:
    nonempty = [ln for ln in lines if ln.text]
    if not nonempty:
        return True

    nontech_codes = _count_nontech_codes(nonempty)
    if nontech_codes > 0:
        return False

    tech = [
        ln
        for ln in nonempty
        if ln.text.startswith("[") and ln.text.endswith("]") and _is_tech_bracket(ln.text)
    ]
    nonbr = [ln for ln in nonempty if not (ln.text.startswith("[") and ln.text.endswith("]"))]

    if tech and (len(nonbr) <= 1):
        topish = all(ln.y1 <= 160.0 for ln in nonempty)
        short_other = True
        if nonbr:
            txt = " ".join(x.text for x in nonbr).strip()
            short_other = len(txt) <= 28
        if topish and short_other:
            return True

    if len(tech) >= max(2, int(0.70 * len(nonempty))) and len(nonbr) <= max(2, int(0.18 * len(nonempty))):
        return True

    return False


def _is_toc_like(lines: List[L]) -> bool:
    colored = [ln for ln in lines if ln.text and ln.non_black]
    if len(colored) < 10:
        return False

    secnumlike = [ln for ln in colored if _SECTION_NUM_RE.match(ln.text)]
    if len(secnumlike) < max(8, int(0.45 * len(colored))):
        return False

    nontech_codes = _count_nontech_codes(lines)
    if nontech_codes >= 2:
        return False

    xs = sorted([ln.x0 for ln in secnumlike])
    if xs:
        spread = xs[-1] - xs[0]
        if spread > 120.0:
            return False

    return True


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
    if _SECTION_NUM_RE.match(tt):
        return False
    return True


def _same_row(a: L, b: L) -> bool:
    if a.y1 < b.y0 or b.y1 < a.y0:
        return False
    ac = 0.5 * (a.y0 + a.y1)
    bc = 0.5 * (b.y0 + b.y1)
    return abs(ac - bc) <= 7.0


def _near_code_same_row_right(title_ln: L, code_lines: List[L]) -> bool:
    for c in code_lines:
        if not _same_row(title_ln, c):
            continue
        if c.x0 < title_ln.x1 - 2.0:
            continue
        dx = c.x0 - title_ln.x1
        if 0 <= dx <= 210.0:
            return True
    return False


def _title_candidate(
    lines: List[L],
    st: Dict[str, float],
    has_any_red: bool,
    code_min_y0: Optional[float],
    allow_update: bool,
    code_lines: List[L],
) -> str:
    if not allow_update:
        return ""

    width = st["width"]
    height = st["height"]
    large = st["large"]
    median = st["median"]
    small = st["small"]

    top_band_y = min(270.0, 0.36 * height)
    top = [ln for ln in lines if ln.text and ln.y0 <= top_band_y]
    if not top:
        return ""

    # If we have codes, titles are typically near the first fields but should not be per-option labels.
    code_guard_y = None
    if code_min_y0 is not None:
        code_guard_y = min(height, code_min_y0 + 26.0)

    cands: List[L] = []
    for ln in top:
        if not _looks_like_title_text(ln.text):
            continue

        # Avoid extreme-top chrome unless clearly prominent.
        if ln.y0 <= 22.0:
            if not (
                ln.size >= (large - 0.2)
                or (ln.non_black and ln.size >= median + 1.5)
                or (ln.bold and ln.size >= median + 1.2)
            ):
                continue

        # Titles should not be long instruction sentences.
        if ":" in (ln.text or "") and ln.size <= median + 0.4 and (not ln.bold) and (not ln.non_black):
            continue

        # If codes exist, strongly prefer titles that are not obviously an option label next to a code.
        if code_guard_y is not None:
            if ln.y0 > code_guard_y and ln.size < (large - 0.8) and (not ln.bold) and (not ln.non_black):
                continue
            if _near_code_same_row_right(ln, code_lines):
                # Option labels often sit directly left of a code token.
                words = [w for w in re.split(r"\s+", ln.text.strip()) if w]
                span = max(0.0, ln.x1 - ln.x0)
                if (len(words) <= 2) and (span < 0.28 * width) and (ln.size < (large - 0.5)):
                    continue
                # Also reject very short one-word labels unless extremely prominent/centered.
                if len(words) == 1 and len(words[0]) <= 4:
                    centered = abs((0.5 * (ln.x0 + ln.x1)) - 0.5 * width) <= 120.0
                    if not (centered and (ln.size >= (large - 0.2)) and span >= 0.18 * width):
                        continue

        span = max(0.0, ln.x1 - ln.x0)
        if span < max(120.0, 0.22 * width):
            if not (
                ln.size >= median + 2.0
                or (ln.non_black and ln.size >= median + 1.2)
                or (ln.bold and ln.size >= median + 1.5)
                or (ln.size >= (large - 0.5))
            ):
                continue

        prominent = (
            ln.size >= max(median + 1.0, small + 2.0)
            or ln.bold
            or ln.non_black
            or ln.size >= (large - 2.0)
        )
        if not prominent:
            continue

        # If there are no red annotations at all, be conservative about black text being a title.
        if not has_any_red and not ln.non_black and not ln.bold and ln.size < median + 1.7:
            continue

        # Structural guard: avoid updating form to tiny short tokens (common in option/header cells).
        words = [w for w in re.split(r"\s+", ln.text.strip()) if w]
        if len(words) == 1 and len(words[0]) <= 3 and ln.size < (large - 0.2):
            span = max(0.0, ln.x1 - ln.x0)
            centered = abs((0.5 * (ln.x0 + ln.x1)) - 0.5 * width) <= 110.0
            if not (centered and span >= 0.20 * width and (ln.bold or ln.non_black)):
                continue

        cands.append(ln)

    if not cands:
        return ""

    target_y = 90.0
    if code_min_y0 is not None:
        target_y = max(44.0, min(150.0, code_min_y0 - 36.0))

    def score(l: L) -> float:
        span = max(0.0, l.x1 - l.x0)
        y_term = -0.016 * abs(l.y0 - target_y)
        center = 0.5 * (l.x0 + l.x1)
        center_term = -0.0006 * abs(center - 0.5 * width)
        option_pen = 0.0
        if _near_code_same_row_right(l, code_lines):
            option_pen = 6.0
        return (
            4.2 * l.size
            + (2.2 if l.bold else 0.0)
            + (1.8 if l.non_black else 0.0)
            + 0.0023 * span
            + y_term
            + center_term
            - 0.014 * l.x0
            - option_pen
        )

    cands.sort(key=score, reverse=True)
    best = cands[0]

    # Join wrapped title lines directly below with similar styling.
    same = [best]
    for ln in cands[1:]:
        if abs(ln.size - best.size) > 1.1:
            continue
        if abs(ln.x0 - best.x0) > 44.0:
            continue
        if 0 < (ln.y0 - best.y0) <= 26.0:
            # Still reject if it's clearly a per-option label next to a code.
            if _near_code_same_row_right(ln, code_lines):
                words = [w for w in re.split(r"\s+", ln.text.strip()) if w]
                span = max(0.0, ln.x1 - ln.x0)
                if (len(words) <= 2) and (span < 0.28 * st["width"]):
                    continue
            same.append(ln)

    same.sort(key=lambda l: l.y0)
    title = " ".join(s.text for s in same).strip()
    title = re.sub(r"\s+", " ", title)

    # Final guard: avoid "titles" that look like a lone option header near codes.
    words = [w for w in re.split(r"\s+", title) if w]
    if len(words) == 1 and len(words[0]) <= 4:
        if _near_code_same_row_right(best, code_lines):
            return ""

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
    if ln.non_black and not (
        ln.bold
        or ("?" in t)
        or t.endswith(":")
        or len(t.split()) >= 4
        or ln.size >= st["median"] + 0.5
    ):
        return False
    return True


def _is_labelish_upward(ln: L, st: Dict[str, float]) -> bool:
    if not ln.text:
        return False
    t = ln.text.strip()
    if not t or t.startswith("["):
        return False
    if not any(ch.isalnum() for ch in t):
        return False
    if len(t) <= 1:
        return False
    if ln.y0 <= 20 and ln.size >= st["large"] - 0.4:
        return False
    if not ln.non_black:
        return _is_labelish_black(ln, st)

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
        if abs(b.x0 - a.x0) > 38.0:
            return False
        if abs(b.y0 - a.y0) > 19.0:
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


def _is_instruction_like(ln: L, st: Dict[str, float]) -> bool:
    t = (ln.text or "").strip()
    if not t or t.startswith("["):
        return False
    if "?" in t or t.endswith(":"):
        return False
    if ln.bold:
        return False
    if ln.non_black and ln.size >= st["median"] + 0.6:
        return False
    if ln.size > st["median"] + 0.45:
        return False

    words = [w for w in re.split(r"\s+", t) if w]
    if len(words) < 4:
        return False

    span = max(0.0, ln.x1 - ln.x0)
    wide = span >= 0.55 * st["width"] or (span >= 0.45 * st["width"] and ln.x0 <= 0.18 * st["width"])
    if not wide:
        return False

    return True


def _best_label_same_line_left(lines: List[L], code_idx: int, st: Dict[str, float]) -> Tuple[str, Optional[int]]:
    code = lines[code_idx]
    best_i = None
    best_score = None
    start = max(0, code_idx - 55)
    end = min(len(lines), code_idx + 30)
    for i in range(start, end):
        if i == code_idx:
            continue
        ln = lines[i]
        if not _is_labelish_relaxed(ln, st):
            continue
        if _is_instruction_like(ln, st):
            continue
        if not _same_row(ln, code):
            continue
        if ln.x1 > code.x0 + 2.0:
            continue
        dx = code.x0 - ln.x1
        if dx < 0:
            continue
        if dx > 560.0:
            continue
        score = dx + (8.0 if ln.non_black else 0.0) + (1.5 if not ln.bold else 0.0)
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    if best_i is None:
        return "", None
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0 + 1000.0, relaxed=True), best_i


def _best_label_above_same_column(lines: List[L], code_idx: int, st: Dict[str, float]) -> Tuple[str, Optional[int]]:
    code = lines[code_idx]
    width = st["width"]
    height = st["height"]
    cx = 0.5 * (code.x0 + code.x1)

    best_i = None
    best_s = None
    max_dy = max(74.0, 0.095 * height)

    for i in range(code_idx - 1, -1, -1):
        ln = lines[i]
        if not _is_labelish_relaxed(ln, st):
            continue
        if _is_instruction_like(ln, st):
            continue
        if ln.y1 > code.y0 + 0.5:
            continue
        dy = code.y0 - ln.y1
        if dy < 0 or dy > max_dy:
            if dy > max_dy:
                break
            continue

        span = max(0.0, ln.x1 - ln.x0)
        if span < 45.0:
            continue

        # Require horizontal affinity to the code column.
        overlaps = (ln.x0 - 10.0) <= cx <= (ln.x1 + 10.0)
        if not overlaps:
            # allow near-by with slack
            if min(abs(cx - ln.x0), abs(cx - ln.x1)) > 70.0:
                continue

        # Avoid tiny option headers (e.g. Yes/No/Not Done).
        t = ln.text.strip()
        words = [w for w in re.split(r"\s+", t) if w]
        if (len(words) <= 2) and ("?" not in t) and (not t.endswith(":")) and (span < 0.32 * width) and (ln.size <= st["median"] + 0.35) and (not ln.bold):
            continue

        xdist = 0.0 if overlaps else min(abs(cx - ln.x0), abs(cx - ln.x1))
        s = dy + 0.18 * xdist + 0.010 * ln.x0 + (5.0 if ln.non_black and not ln.bold else 0.0)
        if best_s is None or s < best_s:
            best_s = s
            best_i = i

        if dy < 10 and overlaps:
            break

    if best_i is None:
        return "", None
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0, relaxed=True), best_i


def _row_label_same_row(lines: List[L], code_idx: int, st: Dict[str, float]) -> Tuple[str, Optional[int]]:
    code = lines[code_idx]
    best_i = None
    best_score = None
    start = max(0, code_idx - 125)
    end = min(len(lines), code_idx + 90)
    for i in range(start, end):
        ln = lines[i]
        if not _is_labelish_relaxed(ln, st):
            continue
        if _is_instruction_like(ln, st):
            continue
        if not _same_row(ln, code):
            continue
        if ln.x1 > code.x0 - 8.0:
            continue
        dx = code.x0 - ln.x1
        if dx < 0 or dx > 700.0:
            continue
        score = 0.65 * dx + 0.45 * ln.x0 + (7.0 if ln.non_black else 0.0)
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    if best_i is None:
        return "", None
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0 + 1000.0, relaxed=True), best_i


def _has_peer_codes_same_column(lines: List[L], code_idx: int, st: Dict[str, float]) -> bool:
    code = lines[code_idx]
    width = st["width"]
    if width <= 0:
        return False
    if code.x0 > width * 0.76:
        return False
    count = 0
    for j in range(max(0, code_idx - 65), min(len(lines), code_idx + 66)):
        if j == code_idx:
            continue
        t = (lines[j].text or "").strip()
        if not (t.startswith("[") and t.endswith("]")):
            continue
        if _is_tech_bracket(t) or not _is_code_token(t):
            continue
        if abs(lines[j].x0 - code.x0) <= 18.0 and abs(lines[j].y0 - code.y0) <= 160.0:
            count += 1
            if count >= 2:
                return True
    return False


def _best_prompt_for_option(lines: List[L], code_idx: int, st: Dict[str, float]) -> str:
    code = lines[code_idx]
    width = st["width"]
    height = st["height"]
    median = st["median"]

    best_i = None
    best_s = None
    max_dy = max(180.0, 0.26 * height)

    for i in range(code_idx - 1, -1, -1):
        ln = lines[i]
        if not _is_labelish_relaxed(ln, st):
            continue
        if _is_instruction_like(ln, st):
            continue
        if ln.y0 >= code.y0:
            continue
        dy = code.y0 - ln.y0
        if dy <= 0 or dy > max_dy:
            if dy > max_dy:
                break
            continue

        overlaps_x = (ln.x0 - 10.0) <= code.x0 <= (ln.x1 + 10.0)
        span = max(0.0, ln.x1 - ln.x0)

        if not overlaps_x:
            if not (span >= 0.48 * width and ln.x0 <= width * 0.42):
                continue

        t = ln.text.strip()
        words = [w for w in re.split(r"\s+", t) if w]

        # Reject likely column/option headers (short, not punctuated).
        if overlaps_x and (len(words) <= 2) and ("?" not in t) and (not t.endswith(":")) and span < 0.34 * width and ln.size <= median + 0.35 and (not ln.bold):
            continue

        prompty = bool(("?" in t) or t.endswith(":") or len(words) >= 3 or ln.bold or (ln.size >= median + 0.45))
        if not prompty:
            continue

        xdist = 0.0
        if ln.x1 <= code.x0:
            xdist = code.x0 - ln.x1
        else:
            xdist = abs(code.x0 - ln.x0)

        s = dy + 0.14 * xdist + 0.012 * ln.x0 + (4.5 if ln.non_black and not ln.bold else 0.0)
        if best_s is None or s < best_s:
            best_s = s
            best_i = i

        if dy < 28 and overlaps_x:
            break

    if best_i is None:
        return ""
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0, relaxed=True)


def _is_option_like_label(
    label_text: str,
    label_ln: Optional[L],
    code_ln: L,
    st: Dict[str, float],
    peer_codes: bool,
) -> bool:
    t = re.sub(r"\s+", " ", (label_text or "").strip())
    if not t or label_ln is None:
        return False
    width = st["width"]
    if width <= 0:
        return False

    if code_ln.x0 > width * 0.68:
        return False

    words = [w for w in re.split(r"\s+", t) if w]
    if ("?" in t) or t.endswith(":") or len(words) >= 4:
        return False

    if label_ln.bold or label_ln.size >= st["median"] + 0.6:
        return False

    span = max(0.0, label_ln.x1 - label_ln.x0)
    if span >= 0.30 * width:
        return False

    aligned = abs(label_ln.x0 - code_ln.x0) <= 72.0
    if _TIMEPOINT_RE.search(t) and aligned:
        return True

    if peer_codes and len(words) <= 2 and aligned:
        return True

    return False


def _best_label_for_code(lines: List[L], code_idx: int, st: Dict[str, float]) -> Tuple[str, Optional[int]]:
    code = lines[code_idx]
    width = st["width"]
    height = st["height"]

    # 1) Same-line left label.
    left, li = _best_label_same_line_left(lines, code_idx, st)
    if left:
        return left, li

    # 2) Above label in same column (common for stacked header->field layouts).
    above, ai = _best_label_above_same_column(lines, code_idx, st)
    if above:
        return above, ai

    # 3) Upward search.
    best_i = None
    best_score = None
    max_dy = max(270.0, 0.42 * height)

    for i in range(code_idx - 1, -1, -1):
        ln = lines[i]
        if not _is_labelish_upward(ln, st):
            continue
        if ln.y0 >= code.y0:
            continue
        dy = code.y0 - ln.y0
        if dy <= 0:
            continue
        if dy > max_dy:
            break

        if _is_instruction_like(ln, st):
            if dy > 22:
                continue

        if code.x0 <= width * 0.42:
            xdist = abs(code.x0 - ln.x0)
        else:
            if ln.x1 <= code.x0:
                xdist = code.x0 - ln.x1
            else:
                xdist = abs(code.x0 - ln.x0)

        bold_bonus = -10.0 if ln.bold else 0.0
        small_bonus = -5.0 if ln.size <= st["small"] + 0.8 else 0.0

        t = ln.text.strip()
        wcnt = len([w for w in re.split(r"\s+", t) if w])
        long_pen = 10.0 if (wcnt >= 8 and ("?" not in t) and (not t.endswith(":")) and (not ln.bold)) else 0.0

        score = dy + 0.26 * xdist + bold_bonus + small_bonus + long_pen + (6.0 if ln.non_black and not ln.bold else 0.0)

        if dy > 175 and xdist > 120:
            score += 35.0

        if best_score is None or score < best_score:
            best_score = score
            best_i = i

        if dy < 28 and xdist < 35:
            break

    label = ""
    label_idx: Optional[int] = None
    if best_i is not None:
        label = _collect_wrapped(lines, best_i, st, stop_y=code.y0, relaxed=(lines[best_i].non_black))
        label_idx = best_i
    else:
        # 4) Tight nearby relaxed fallback.
        best_j = None
        best_s = None
        for j, ln in enumerate(lines):
            if not _is_labelish_relaxed(ln, st):
                continue
            if _is_instruction_like(ln, st):
                continue
            if ln.y0 >= code.y0 + 1.0:
                continue
            dy = code.y0 - ln.y0
            if dy <= 0 or dy > max(160.0, 0.24 * height):
                continue

            xdist = abs(code.x0 - ln.x0)
            if ln.x1 <= code.x0:
                xdist = min(xdist, code.x0 - ln.x1)
            s = dy + 0.21 * xdist + (8.0 if ln.non_black and not ln.bold else 0.0)
            if best_s is None or s < best_s:
                best_s = s
                best_j = j
        if best_j is not None:
            label = _collect_wrapped(lines, best_j, st, stop_y=code.y0, relaxed=True)
            label_idx = best_j

    label = re.sub(r"\s+", " ", (label or "").strip())
    if not label:
        return "", None

    # 5) If label looks like an option header/value, try to find the prompt above and use that instead.
    peer_codes = _has_peer_codes_same_column(lines, code_idx, st)
    label_ln = lines[label_idx] if (label_idx is not None and 0 <= label_idx < len(lines)) else None
    if _is_option_like_label(label, label_ln, code, st, peer_codes):
        prompt = _best_prompt_for_option(lines, code_idx, st)
        prompt = re.sub(r"\s+", " ", (prompt or "").strip())
        if prompt and prompt.lower() != label.lower():
            return prompt, None
        return "", None

    # 6) If we accidentally grabbed a short timepoint-like header/value, prefer row label on same row.
    if _TIMEPOINT_RE.search(label) and len(label.split()) <= 3:
        row, _ri = _row_label_same_row(lines, code_idx, st)
        row = re.sub(r"\s+", " ", (row or "").strip())
        if row and row.lower() != label.lower():
            return row, None

    # 7) If a far-left same-row label exists and is more descriptive, prefer it (table-ish layouts).
    row2, _ri2 = _row_label_same_row(lines, code_idx, st)
    row2 = re.sub(r"\s+", " ", (row2 or "").strip())
    if row2:
        w_label = len([w for w in label.split() if w])
        w_row2 = len([w for w in row2.split() if w])
        if w_row2 >= w_label + 2 or (("?" in row2 or row2.endswith(":")) and ("?" not in label and not label.endswith(":"))):
            return row2, None

    return label, label_idx


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
        if _is_instruction_like(ln, st):
            continue
        t = ln.text.strip()
        if not any(ch.isalnum() for ch in t):
            continue
        if not (ln.bold or ln.size >= median + 0.25 or (ln.non_black and ln.size >= small + 0.8) or ("?" in t) or t.endswith(":")):
            continue
        cands.append(ln)
    if not cands:
        return {}, first_row_y

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


def _matrix_profile(lines: List[L], code_idxs: List[int], st: Dict[str, float]) -> Dict[str, Any]:
    width = st["width"]
    height = st["height"]
    if not code_idxs:
        return {"active": False}

    mid_codes = [i for i in code_idxs if lines[i].x0 <= width * 0.78]
    if len(mid_codes) < 6:
        return {"active": False}

    xs = [lines[i].x0 for i in mid_codes]
    ys = [lines[i].y0 for i in mid_codes]
    if not xs or not ys:
        return {"active": False}

    top = min(ys)
    bottom = max(lines[i].y1 for i in mid_codes)
    vspan = bottom - top
    if vspan < max(96.0, 0.13 * height):
        return {"active": False}

    binw = 24.0
    cols: Dict[int, List[int]] = {}
    for i in mid_codes:
        b = int((lines[i].x0 + 0.01) // binw)
        cols.setdefault(b, []).append(i)
    col_bins = sorted(cols.keys())
    if len(col_bins) < 2:
        return {"active": False}

    min_col_x0 = min(lines[i].x0 for i in mid_codes)
    max_col_x1 = max(lines[i].x1 for i in mid_codes)

    # Header region immediately above the matrix.
    header_top = max(0.0, top - max(135.0, 0.17 * height))
    header_bot = top - 2.0

    header_lines = [
        (idx, ln)
        for idx, ln in enumerate(lines)
        if ln.text
        and (not ln.text.startswith("["))
        and header_top <= ln.y0 <= header_bot
        and any(ch.isalnum() for ch in ln.text)
    ]

    option_header_idxs: Set[int] = set()
    col_header_idxs: Set[int] = set()

    for idx, ln in header_lines:
        if not _is_labelish_relaxed(ln, st):
            continue
        if _is_instruction_like(ln, st):
            continue

        t = ln.text.strip()
        words = [w for w in re.split(r"\s+", t) if w]
        span = max(0.0, ln.x1 - ln.x0)

        # Aligned with a code column.
        aligned = False
        for b in col_bins:
            col_x = statistics.median([lines[i].x0 for i in cols[b]])
            if abs(ln.x0 - col_x) <= 60.0 or (ln.x0 <= col_x <= ln.x1):
                aligned = True
                break
        if not aligned:
            continue

        # Short, low-prominence tokens aligned to columns are usually option headers (Yes/No/Not Done, etc.).
        if len(words) <= 2 and (not ln.bold) and (ln.size <= st["median"] + 0.35) and span < 0.22 * width:
            option_header_idxs.add(idx)

        # Column headers tend to be somewhat more prominent and can be multi-word, but still not fields.
        if len(words) <= 5 and ("?" not in t) and (not t.endswith(":")):
            # Must overlap matrix horizontally.
            if ln.x1 >= (min_col_x0 - 8.0) and ln.x0 <= (max_col_x1 + 8.0):
                if (ln.bold or ln.non_black or ln.size >= st["median"] + 0.3) and span < 0.55 * width:
                    col_header_idxs.add(idx)

    # Find a group header spanning across option columns (prefer wide/centered across the matrix).
    group = ""
    group_region_top = max(0.0, top - max(240.0, 0.31 * height))
    group_region_bot = top - max(95.0, 0.12 * height)
    group_cands: List[L] = []
    matrix_span = max(0.0, max_col_x1 - min_col_x0)
    for ln in lines:
        if not ln.text or ln.text.startswith("["):
            continue
        if not (group_region_top <= ln.y0 <= group_region_bot):
            continue
        if not _is_labelish_relaxed(ln, st):
            continue
        if _is_instruction_like(ln, st):
            continue
        span = max(0.0, ln.x1 - ln.x0)
        if span < max(0.30 * width, 0.55 * matrix_span):
            continue
        # must overlap the matrix horizontally
        if ln.x1 < (min_col_x0 + 18.0):
            continue
        if ln.x0 > (max_col_x1 - 18.0):
            continue
        # center should sit within matrix band
        center = 0.5 * (ln.x0 + ln.x1)
        if center < (min_col_x0 - 30.0) or center > (max_col_x1 + 30.0):
            continue
        group_cands.append(ln)

    if group_cands:

        def gscore(l: L) -> float:
            span = max(0.0, l.x1 - l.x0)
            center = 0.5 * (l.x0 + l.x1)
            center_term = -0.0007 * abs(center - 0.5 * (min_col_x0 + max_col_x1))
            return (
                4.0 * l.size
                + (2.0 if l.bold else 0.0)
                + (1.5 if l.non_black else 0.0)
                + 0.0018 * span
                + center_term
                - 0.010 * abs((top - 110.0) - l.y0)
                - 0.010 * l.x0
            )

        group_cands.sort(key=gscore, reverse=True)
        group = re.sub(r"\s+", " ", group_cands[0].text.strip())

    return {
        "active": True,
        "top": top,
        "bottom": bottom,
        "min_col_x0": min_col_x0,
        "max_col_x1": max_col_x1,
        "option_header_idxs": option_header_idxs,
        "col_header_idxs": col_header_idxs,
        "group": group,
    }


def _row_label_left_of_matrix(lines: List[L], code_idx: int, st: Dict[str, float], min_col_x0: float) -> str:
    code = lines[code_idx]
    width = st["width"]
    best_i = None
    best_s = None
    for i, ln in enumerate(lines):
        if not _is_labelish_relaxed(ln, st):
            continue
        if ln.text.startswith("["):
            continue
        if _is_instruction_like(ln, st):
            continue
        if not _same_row(ln, code):
            continue
        # allow slight overlap into the first code column
        if ln.x1 > min_col_x0 + 8.0:
            continue

        span = max(0.0, ln.x1 - ln.x0)
        if span >= 0.60 * width:
            continue

        dx = (min_col_x0 - ln.x1)
        if dx < -10 or dx > 740.0:
            continue

        # Prefer closest left label, slightly prefer left-ish and black.
        s = 0.90 * max(0.0, dx) + 0.10 * ln.x0 + (6.0 if ln.non_black else 0.0) + (1.5 if not ln.bold else 0.0)
        if best_s is None or s < best_s:
            best_s = s
            best_i = i
    if best_i is None:
        return ""
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0 + 1000.0, relaxed=True)


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
        def_only = _is_definition_only_page(lines)

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

        code_idxs = code_idxs_red + [i for i in code_idxs_black if i not in set(code_idxs_red)]
        code_min_y0 = min((lines[i].y0 for i in code_idxs), default=None)
        code_lines = [lines[i] for i in code_idxs]

        title = _title_candidate(
            lines,
            st,
            has_any_red=has_any_red,
            code_min_y0=code_min_y0,
            allow_update=(not toc_like) and (not def_only),
            code_lines=code_lines,
        )
        if title:
            current_form = title

        if toc_like or def_only:
            continue

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

        matrix = _matrix_profile(lines, code_idxs, st)

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
                    field_name = (rowtxt + " " + header).strip() if rowtxt else header
                else:
                    continue

            elif matrix.get("active") and (matrix["top"] - 7.0) <= code_ln.y0 <= (matrix["bottom"] + 7.0) and (code_ln.x0 <= width * 0.80):
                rowlbl = _row_label_left_of_matrix(lines, ci, st, float(matrix["min_col_x0"]))
                rowlbl = re.sub(r"\s+", " ", (rowlbl or "").strip())
                if rowlbl and (not _ROW_GENERIC_RE.match(rowlbl)) and (not _SECTION_NUM_RE.match(rowlbl)):
                    field_name = rowlbl
                else:
                    # fall back to general label, but reject column/option headers
                    lbl, label_idx = _best_label_for_code(lines, ci, st)
                    if label_idx is not None and (
                        label_idx in set(matrix.get("option_header_idxs", set()))
                        or label_idx in set(matrix.get("col_header_idxs", set()))
                    ):
                        lbl = ""
                    field_name = lbl

                    # as a last resort, allow group only if it is a true spanning header (matrix_profile already enforces width)
                    if not field_name:
                        grp = re.sub(r"\s+", " ", (matrix.get("group") or "").strip())
                        field_name = grp if grp else ""

            else:
                field_name, label_idx = _best_label_for_code(lines, ci, st)
                if matrix.get("active") and label_idx is not None and (
                    label_idx in set(matrix.get("option_header_idxs", set()))
                    or label_idx in set(matrix.get("col_header_idxs", set()))
                ):
                    # Avoid option/column headers getting selected as labels.
                    # Try matrix row label if we're near a matrix region; otherwise drop.
                    if (matrix["top"] - 12.0) <= code_ln.y0 <= (matrix["bottom"] + 12.0) and (code_ln.x0 <= width * 0.82):
                        rowlbl2 = _row_label_left_of_matrix(lines, ci, st, float(matrix["min_col_x0"]))
                        rowlbl2 = re.sub(r"\s+", " ", (rowlbl2 or "").strip())
                        if rowlbl2 and (not _ROW_GENERIC_RE.match(rowlbl2)) and (not _SECTION_NUM_RE.match(rowlbl2)):
                            field_name = rowlbl2
                        else:
                            field_name = ""
                    else:
                        field_name = ""

            field_name = re.sub(r"\s+", " ", (field_name or "").strip())
            if not field_name:
                continue

            if _ROW_GENERIC_RE.match(field_name.strip()):
                continue

            if _SECTION_NUM_RE.match(field_name):
                continue

            # Avoid returning timepoint option values as fields when code isn't on far right.
            if _TIMEPOINT_RE.search(field_name) and len(field_name.split()) <= 3 and code_ln.x0 <= width * 0.68:
                continue

            # Avoid extracting instruction-like lines as fields when they get picked accidentally.
            # (Structural: full-width, low-prominence, not punctuated.)
            tmp_ln = L(field_name, 0.0, code_ln.y0, width, code_ln.y1, st["median"], False, False)
            if _is_instruction_like(tmp_ln, st):
                continue

            key = (page_idx0 + 1, form_name, field_name)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": field_name, "page": page_idx0 + 1})

    return out
```
