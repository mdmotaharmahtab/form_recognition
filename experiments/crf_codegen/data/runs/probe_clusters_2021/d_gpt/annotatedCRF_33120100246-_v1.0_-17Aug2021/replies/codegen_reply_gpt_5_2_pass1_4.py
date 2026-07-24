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
    # Pages that contain only technical annotations like "[TYPE: enumeration ...]"
    # should not affect form title persistence.
    nonempty = [ln for ln in lines if ln.text]
    if not nonempty:
        return True
    nontech_codes = _count_nontech_codes(nonempty)
    if nontech_codes > 0:
        return False

    tech = [ln for ln in nonempty if ln.text.startswith("[") and ln.text.endswith("]") and _is_tech_bracket(ln.text)]
    nonbr = [ln for ln in nonempty if not (ln.text.startswith("[") and ln.text.endswith("]"))]
    # If overwhelmingly tech brackets and very little other content (especially near top), treat as definition-only.
    if tech and (len(nonbr) <= 1):
        topish = all(ln.y1 <= 140.0 for ln in nonempty)
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
    # Structural TOC-like pages: many similarly styled colored section-number entries.
    colored = [ln for ln in lines if ln.text and ln.non_black]
    if len(colored) < 10:
        return False

    secnumlike = [ln for ln in colored if _SECTION_NUM_RE.match(ln.text)]
    if len(secnumlike) < max(8, int(0.45 * len(colored))):
        return False

    # If the page is a TOC/index, it should not contain actual field code tokens.
    nontech_codes = _count_nontech_codes(lines)
    if nontech_codes >= 2:
        return False

    # TOC entries are typically in one left column.
    xs = sorted([ln.x0 for ln in secnumlike])
    if xs:
        spread = xs[-1] - xs[0]
        if spread > 120.0:
            # allow a bit of spread, but not multi-column layouts
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

    # Slightly broader than before: titles sometimes sit below a modest header band.
    top_band_y = min(260.0, 0.34 * height)
    top = [ln for ln in lines if ln.text and ln.y0 <= top_band_y]
    if not top:
        return ""

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

        # If we have codes, title should be above the first code on the page.
        if code_min_y0 is not None and ln.y1 > code_min_y0 - 6.0:
            continue

        span = max(0.0, ln.x1 - ln.x0)
        if span < max(120.0, 0.22 * width):
            if not (
                ln.size >= median + 2.0
                or (ln.non_black and ln.size >= median + 1.2)
                or (ln.bold and ln.size >= median + 1.5)
            ):
                continue

        # Promote prominence.
        prominent = (
            ln.size >= max(median + 1.2, small + 2.2)
            or ln.bold
            or ln.non_black
            or ln.size >= (large - 2.2)
        )
        if not prominent:
            continue

        # If there are no red annotations at all, be conservative about black text being a title.
        if not has_any_red and not ln.non_black and not ln.bold and ln.size < median + 1.7:
            continue

        cands.append(ln)

    if not cands:
        return ""

    target_y = 90.0
    if code_min_y0 is not None:
        target_y = max(44.0, min(140.0, code_min_y0 - 40.0))

    def score(l: L) -> float:
        span = max(0.0, l.x1 - l.x0)
        y_term = -0.016 * abs(l.y0 - target_y)
        # favor centered-ish titles slightly
        center = 0.5 * (l.x0 + l.x1)
        center_term = -0.0006 * abs(center - 0.5 * width)
        return (
            4.2 * l.size
            + (2.2 if l.bold else 0.0)
            + (1.8 if l.non_black else 0.0)
            + 0.0023 * span
            + y_term
            + center_term
            - 0.014 * l.x0
        )

    cands.sort(key=score, reverse=True)
    best = cands[0]

    # Join wrapped title lines directly below with similar styling.
    same = [best]
    for ln in cands[1:]:
        if abs(ln.size - best.size) > 1.1:
            continue
        if abs(ln.x0 - best.x0) > 42.0:
            continue
        if 0 < (ln.y0 - best.y0) <= 24.0:
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


def _best_label_same_line_left(lines: List[L], code_idx: int, st: Dict[str, float]) -> Tuple[str, Optional[int]]:
    code = lines[code_idx]
    best_i = None
    best_score = None
    start = max(0, code_idx - 50)
    end = min(len(lines), code_idx + 25)
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
        if dx > 560.0:
            continue
        # Prefer closer, and prefer black/bold-ish prompts over colored tiny option labels.
        score = dx + (8.0 if ln.non_black else 0.0) + (1.5 if not ln.bold else 0.0)
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    if best_i is None:
        return "", None
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0 + 1000.0, relaxed=True), best_i


def _row_label_same_row(lines: List[L], code_idx: int, st: Dict[str, float]) -> Tuple[str, Optional[int]]:
    code = lines[code_idx]
    best_i = None
    best_score = None
    start = max(0, code_idx - 110)
    end = min(len(lines), code_idx + 80)
    for i in range(start, end):
        ln = lines[i]
        if not _is_labelish_relaxed(ln, st):
            continue
        if not _same_row(ln, code):
            continue
        if ln.x1 > code.x0 - 8.0:
            continue
        dx = code.x0 - ln.x1
        if dx < 0 or dx > 680.0:
            continue
        score = 0.65 * dx + 0.45 * ln.x0 + (7.0 if ln.non_black else 0.0)
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    if best_i is None:
        return "", None
    return _collect_wrapped(lines, best_i, st, stop_y=code.y0 + 1000.0, relaxed=True), best_i


def _has_peer_codes_same_column(lines: List[L], code_idx: int, st: Dict[str, float]) -> bool:
    # Detect radio/checkbox option lists: several codes aligned by x0.
    code = lines[code_idx]
    width = st["width"]
    if width <= 0:
        return False
    if code.x0 > width * 0.72:
        return False
    count = 0
    for j in range(max(0, code_idx - 45), min(len(lines), code_idx + 46)):
        if j == code_idx:
            continue
        t = lines[j].text.strip()
        if not (t.startswith("[") and t.endswith("]")):
            continue
        if _is_tech_bracket(t) or not _is_code_token(t):
            continue
        if abs(lines[j].x0 - code.x0) <= 18.0 and abs(lines[j].y0 - code.y0) <= 110.0:
            count += 1
            if count >= 2:
                return True
    return False


def _is_instruction_like(ln: L, st: Dict[str, float]) -> bool:
    # Structural filter: long, full-width, non-prompt sentences are often section instructions, not field labels.
    t = (ln.text or "").strip()
    if not t or t.startswith("["):
        return False
    if "?" in t or t.endswith(":"):
        return False
    words = [w for w in re.split(r"\s+", t) if w]
    if len(words) < 6:
        return False
    span = max(0.0, ln.x1 - ln.x0)
    if span < 0.62 * st["width"]:
        return False
    # Colored/bold long headers can still be real prompts; keep those.
    if ln.bold or (ln.non_black and ln.size >= st["median"] + 0.6):
        return False
    return True


def _best_prompt_for_option(lines: List[L], code_idx: int, st: Dict[str, float]) -> str:
    # Find a nearby prompt/header above a set of options; return prompt only.
    code = lines[code_idx]
    width = st["width"]
    height = st["height"]
    median = st["median"]

    best_i = None
    best_s = None
    max_dy = max(170.0, 0.25 * height)

    for i in range(code_idx - 1, -1, -1):
        ln = lines[i]
        if not _is_labelish_relaxed(ln, st):
            continue
        if ln.y0 >= code.y0:
            continue
        dy = code.y0 - ln.y0
        if dy <= 0 or dy > max_dy:
            break

        # Prefer prompts that overlap the option column, not a far-left identifier header.
        overlaps_x = (ln.x0 - 10.0) <= code.x0 <= (ln.x1 + 10.0)
        if not overlaps_x:
            # Allow if it's a wide spanning header.
            span = max(0.0, ln.x1 - ln.x0)
            if not (span >= 0.45 * width and ln.x0 <= width * 0.40):
                continue

        t = ln.text.strip()
        words = [w for w in re.split(r"\s+", t) if w]

        prompty = bool(("?" in t) or t.endswith(":") or len(words) >= 3 or ln.bold or (ln.size >= median + 0.35))
        if not prompty:
            continue

        if _is_instruction_like(ln, st) and dy > 60:
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

    # Don't treat far-right "label -> code" fields as options.
    if code_ln.x0 > width * 0.66:
        return False

    words = [w for w in re.split(r"\s+", t) if w]
    if ("?" in t) or t.endswith(":") or len(words) >= 4:
        return False

    # Prominent labels are prompts, not options.
    if label_ln.bold or label_ln.size >= st["median"] + 0.6:
        return False

    span = max(0.0, label_ln.x1 - label_ln.x0)
    if span >= 0.30 * width:
        return False

    aligned = abs(label_ln.x0 - code_ln.x0) <= 68.0
    if _TIMEPOINT_RE.search(t) and aligned:
        return True

    # Only use peer-code signal when label is short AND aligned to the option column.
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

    # 2) Upward search (black + prompty colored).
    best_i = None
    best_score = None
    max_dy = max(260.0, 0.40 * height)

    for i in range(code_idx - 1, -1, -1):
        ln = lines[i]
        if not _is_labelish_upward(ln, st):
            continue
        dy = code.y0 - ln.y0
        if dy <= 0:
            continue
        if dy > max_dy:
            break

        if _is_instruction_like(ln, st) and dy > 65:
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

        # Penalize very long upward candidates slightly unless they are prompt-like.
        t = ln.text.strip()
        wcnt = len([w for w in re.split(r"\s+", t) if w])
        long_pen = 10.0 if (wcnt >= 8 and ("?" not in t) and (not t.endswith(":")) and (not ln.bold)) else 0.0

        score = dy + 0.26 * xdist + bold_bonus + small_bonus + long_pen + (6.0 if ln.non_black and not ln.bold else 0.0)

        if dy > 170 and xdist > 120:
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
        # 3) Tight nearby relaxed fallback.
        best_j = None
        best_s = None
        for j, ln in enumerate(lines):
            if not _is_labelish_relaxed(ln, st):
                continue
            if ln.y0 >= code.y0 + 1.0:
                continue
            dy = code.y0 - ln.y0
            if dy <= 0 or dy > max(150.0, 0.22 * height):
                continue

            if _is_instruction_like(ln, st) and dy > 60:
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

    # 4) If label looks like an option header/value, try to find the prompt above and use that instead.
    peer_codes = _has_peer_codes_same_column(lines, code_idx, st)
    label_ln = lines[label_idx] if (label_idx is not None and 0 <= label_idx < len(lines)) else None
    if _is_option_like_label(label, label_ln, code, st, peer_codes):
        prompt = _best_prompt_for_option(lines, code_idx, st)
        prompt = re.sub(r"\s+", " ", (prompt or "").strip())
        if prompt and prompt.lower() != label.lower():
            return prompt, None
        return "", None

    # 5) If we accidentally grabbed a short timepoint-like header/value, prefer row label on same row.
    if _TIMEPOINT_RE.search(label) and len(label.split()) <= 3:
        row, _ri = _row_label_same_row(lines, code_idx, st)
        row = re.sub(r"\s+", " ", (row or "").strip())
        if row and row.lower() != label.lower():
            return row, None

    # 6) If a far-left same-row label exists and is more descriptive, prefer it (table-ish layouts).
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
    # Detect checkbox-matrix-like regions and provide row-label guidance.
    width = st["width"]
    height = st["height"]
    if not code_idxs:
        return {"active": False}

    # Focus on codes not in far-right label->value columns.
    mid_codes = [i for i in code_idxs if lines[i].x0 <= width * 0.74]
    if len(mid_codes) < 10:
        return {"active": False}

    xs = [lines[i].x0 for i in mid_codes]
    ys = [lines[i].y0 for i in mid_codes]
    if not xs or not ys:
        return {"active": False}

    top = min(ys)
    bottom = max(lines[i].y1 for i in mid_codes)
    vspan = bottom - top
    if vspan < max(120.0, 0.16 * height):
        return {"active": False}

    # Bin columns.
    binw = 24.0
    cols: Dict[int, List[int]] = {}
    for i in mid_codes:
        b = int((lines[i].x0 + 0.01) // binw)
        cols.setdefault(b, []).append(i)
    col_bins = sorted(cols.keys())
    if len(col_bins) < 3:
        return {"active": False}

    # Determine leftmost code column x0 for row-label search.
    min_col_x0 = min(lines[i].x0 for i in mid_codes)
    max_col_x1 = max(lines[i].x1 for i in mid_codes)

    # Identify likely option headers above the matrix (short, aligned to code columns).
    header_top = max(0.0, top - max(130.0, 0.16 * height))
    header_bot = top - 2.0
    header_lines = [
        (idx, ln)
        for idx, ln in enumerate(lines)
        if ln.text
        and (not ln.text.startswith("["))
        and header_top <= ln.y0 <= header_bot
        and any(ch.isalnum() for ch in ln.text)
    ]

    option_header_idxs = set()
    for idx, ln in header_lines:
        words = [w for w in re.split(r"\s+", ln.text.strip()) if w]
        if len(words) > 2:
            continue
        if ln.bold:
            continue
        if ln.size >= st["median"] + 0.35:
            continue
        span = max(0.0, ln.x1 - ln.x0)
        if span >= 0.22 * width:
            continue
        # aligned with any code column center
        aligned = False
        for b in col_bins:
            col_x = statistics.median([lines[i].x0 for i in cols[b]])
            if abs(ln.x0 - col_x) <= 60.0 or (ln.x0 <= col_x <= ln.x1):
                aligned = True
                break
        if aligned:
            option_header_idxs.add(idx)

    # Find a group header spanning across option columns (e.g., "Clinically Significant").
    group = ""
    group_region_top = max(0.0, top - max(230.0, 0.30 * height))
    group_region_bot = top - max(95.0, 0.12 * height)
    group_cands: List[L] = []
    for ln in lines:
        if not ln.text or ln.text.startswith("["):
            continue
        if not (group_region_top <= ln.y0 <= group_region_bot):
            continue
        if not _is_labelish_relaxed(ln, st):
            continue
        if _is_instruction_like(ln, st):
            continue
        # must overlap the matrix horizontally (avoid leftmost identifier header)
        if ln.x1 < (min_col_x0 + 22.0):
            continue
        if ln.x0 > (max_col_x1 - 20.0):
            continue
        group_cands.append(ln)

    if group_cands:
        def gscore(l: L) -> float:
            span = max(0.0, l.x1 - l.x0)
            return (
                4.0 * l.size
                + (2.0 if l.bold else 0.0)
                + (1.5 if l.non_black else 0.0)
                + 0.0018 * span
                - 0.010 * abs((top - 110.0) - l.y0)
                - 0.012 * l.x0
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
        "group": group,
    }


def _row_label_left_of_matrix(lines: List[L], code_idx: int, st: Dict[str, float], min_col_x0: float) -> str:
    code = lines[code_idx]
    best_i = None
    best_s = None
    for i, ln in enumerate(lines):
        if not _is_labelish_relaxed(ln, st):
            continue
        if ln.text.startswith("["):
            continue
        if not _same_row(ln, code):
            continue
        if ln.x1 > min_col_x0 - 6.0:
            continue
        # exclude very wide, instruction-like lines
        if _is_instruction_like(ln, st):
            continue
        dx = (min_col_x0 - ln.x1)
        if dx < 0 or dx > 720.0:
            continue
        # Prefer closest left label, slightly prefer left-ish and black.
        s = 0.90 * dx + 0.10 * ln.x0 + (6.0 if ln.non_black else 0.0) + (1.5 if not ln.bold else 0.0)
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

        # IMPORTANT: include both red and black codes (red first), to avoid missing fields on mixed-color pages.
        code_idxs = code_idxs_red + [i for i in code_idxs_black if i not in set(code_idxs_red)]
        code_min_y0 = min((lines[i].y0 for i in code_idxs), default=None)

        # Title update policy: never update on TOC-like or definition-only pages.
        title = _title_candidate(
            lines,
            st,
            has_any_red=has_any_red,
            code_min_y0=code_min_y0,
            allow_update=(not toc_like) and (not def_only),
        )
        if title:
            current_form = title

        # Never emit fields for TOC-like or definition-only pages.
        if toc_like or def_only:
            continue

        if not code_idxs:
            continue

        # Table-with-row-markers mode (existing behavior).
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

        # Checkbox-matrix mode (new): helps avoid extracting option headers/anchors and recovers row labels.
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

            elif matrix.get("active") and (matrix["top"] - 6.0) <= code_ln.y0 <= (matrix["bottom"] + 6.0) and (code_ln.x0 <= width * 0.76):
                # Prefer row label for matrix cells (e.g., HEENT/Thorax/Abdomen).
                rowlbl = _row_label_left_of_matrix(lines, ci, st, float(matrix["min_col_x0"]))
                rowlbl = re.sub(r"\s+", " ", (rowlbl or "").strip())
                if rowlbl and (not _ROW_GENERIC_RE.match(rowlbl)) and (not _SECTION_NUM_RE.match(rowlbl)):
                    field_name = rowlbl
                else:
                    # If row label isn't available, prefer group header over option headers.
                    grp = re.sub(r"\s+", " ", (matrix.get("group") or "").strip())
                    field_name = grp if grp else ""

                # If still empty, fall back to general label.
                if not field_name:
                    field_name, label_idx = _best_label_for_code(lines, ci, st)
                    if label_idx is not None and label_idx in set(matrix.get("option_header_idxs", set())):
                        grp = re.sub(r"\s+", " ", (matrix.get("group") or "").strip())
                        field_name = grp if grp else ""

            else:
                field_name, label_idx = _best_label_for_code(lines, ci, st)
                if matrix.get("active") and label_idx is not None and label_idx in set(matrix.get("option_header_idxs", set())):
                    # Avoid option headers like Yes/No/Not Done when they get selected as labels.
                    grp = re.sub(r"\s+", " ", (matrix.get("group") or "").strip())
                    field_name = grp if grp else ""

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
```
