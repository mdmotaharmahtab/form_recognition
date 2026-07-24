```python
import re
from typing import List, Tuple, Dict, Any, Optional


_CODE_RE = re.compile(r"^\[[A-Za-z0-9][A-Za-z0-9_\-]*\]$")
_ROW_RE = re.compile(r"^\s*Row\s*\d+\s*$", re.IGNORECASE)
_SPACES_RE = re.compile(r"\s+")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _norm(s: str) -> str:
    s = (s or "").strip()
    s = _SPACES_RE.sub(" ", s)
    return s


def _has_letter(s: str) -> bool:
    for ch in s:
        if ch.isalpha():
            return True
    return False


def _word_count(s: str) -> int:
    s = _norm(s)
    if not s:
        return 0
    return len([p for p in s.split(" ") if p])


def _has_struct_punct(s: str) -> bool:
    for ch in s:
        if ch in "():;/,":
            return True
    return False


def _is_field_code_line(text: str) -> bool:
    return bool(_CODE_RE.match((text or "").strip()))


def _is_row_header(text: str) -> bool:
    return bool(_ROW_RE.match((text or "").strip()))


def _is_bracket_metadata_line(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("[") and t.endswith("]") and (":" in t)


def _page_y_span(lines: List[Any]) -> float:
    ys: List[float] = []
    for ln in lines:
        y = _safe_float(getattr(ln, "y0", None), None)  # type: ignore[arg-type]
        if y is None:
            continue
        ys.append(y)
    if not ys:
        return 800.0
    y_min, y_max = min(ys), max(ys)
    span = y_max - y_min
    return span if span > 1.0 else 800.0


def _join_wrapped(lines: List[Any]) -> str:
    parts: List[str] = []
    for ln in lines:
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        if _is_bracket_metadata_line(t):
            continue
        if parts and parts[-1].endswith("-"):
            parts[-1] = parts[-1][:-1] + t
        else:
            parts.append(t)
    return _norm(" ".join(parts))


def _is_human_labelish(t: str) -> bool:
    t = _norm(t)
    if not t:
        return False
    if _is_field_code_line(t) or _is_bracket_metadata_line(t) or _is_row_header(t):
        return False
    if t.startswith("[") and t.endswith("]") and not _has_letter(t):
        return False
    if not _has_letter(t) and "?" not in t:
        return False
    return True


def _is_headerish(ln: Any) -> bool:
    t = _norm(getattr(ln, "text", ""))
    if not _is_human_labelish(t):
        return False
    sz = _safe_float(getattr(ln, "size", 0.0), 0.0)
    bold = bool(getattr(ln, "bold", False))
    non_black = bool(getattr(ln, "non_black", False))
    wc = _word_count(t)
    # Header-ish if styled OR carries units/structure.
    if bold or non_black:
        return True
    if sz >= 9.0 and wc >= 2:
        return True
    if _has_struct_punct(t) and wc >= 2:
        return True
    return False


def _lines_in_y_band(lines: List[Any], y0: float, tol: float) -> List[Any]:
    band: List[Any] = []
    for ln in lines:
        y = _safe_float(getattr(ln, "y0", None), None)  # type: ignore[arg-type]
        if y is None:
            continue
        if abs(y - y0) <= tol:
            band.append(ln)
    return band


def _looks_like_option_row(seed: Any, lines: List[Any], span: float) -> bool:
    y0 = _safe_float(getattr(seed, "y0", None), None)  # type: ignore[arg-type]
    if y0 is None:
        return False

    tol = max(3.5, min(7.5, 0.010 * span))
    band = _lines_in_y_band(lines, y0, tol)

    seed_size = _safe_float(getattr(seed, "size", 0.0), 0.0)
    shortish = 0
    xs: List[float] = []
    for ln in band:
        t = _norm(getattr(ln, "text", ""))
        if not _is_human_labelish(t):
            continue
        size = _safe_float(getattr(ln, "size", 0.0), 0.0)
        if abs(size - seed_size) > 1.2:
            continue
        wc = _word_count(t)
        if wc <= 3 and len(t) <= 22 and not _has_struct_punct(t):
            shortish += 1
            xs.append(_safe_float(getattr(ln, "x0", 0.0), 0.0))

    if shortish < 3 or len(xs) < 3:
        return False
    if (max(xs) - min(xs)) < 180.0:
        return False
    return True


def _collect_wrap_block_limited(
    seed: Any,
    pool: List[Any],
    wrap_gap: float,
    x_slack: float,
    size_slack: float,
    direction: str,
    y_min: Optional[float] = None,
    y_max: Optional[float] = None,
) -> List[Any]:
    base_x = _safe_float(getattr(seed, "x0", 0.0), 0.0)
    base_y = _safe_float(getattr(seed, "y0", 0.0), 0.0)
    base_size = _safe_float(getattr(seed, "size", 0.0), 0.0)

    chosen = [seed]
    chosen_ids = {id(seed)}
    last_y = base_y

    if direction == "down":
        ordered = sorted(pool, key=lambda l: _safe_float(getattr(l, "y0", 0.0), 0.0))
        for ln in ordered:
            if id(ln) in chosen_ids:
                continue
            y = _safe_float(getattr(ln, "y0", 0.0), 0.0)
            x = _safe_float(getattr(ln, "x0", 0.0), 0.0)
            sz = _safe_float(getattr(ln, "size", 0.0), 0.0)

            if y < base_y:
                continue
            if y_max is not None and y > y_max:
                continue
            if y - last_y > wrap_gap:
                continue
            if abs(x - base_x) > x_slack:
                continue
            if abs(sz - base_size) > size_slack:
                continue

            chosen.append(ln)
            chosen_ids.add(id(ln))
            last_y = y
    else:
        ordered = sorted(pool, key=lambda l: _safe_float(getattr(l, "y0", 0.0), 0.0), reverse=True)
        for ln in ordered:
            if id(ln) in chosen_ids:
                continue
            y = _safe_float(getattr(ln, "y0", 0.0), 0.0)
            x = _safe_float(getattr(ln, "x0", 0.0), 0.0)
            sz = _safe_float(getattr(ln, "size", 0.0), 0.0)

            if y > base_y:
                continue
            if y_min is not None and y < y_min:
                continue
            if last_y - y > wrap_gap:
                continue
            if abs(x - base_x) > x_slack:
                continue
            if abs(sz - base_size) > size_slack:
                continue

            chosen.append(ln)
            chosen_ids.add(id(ln))
            last_y = y

    chosen.sort(key=lambda l: _safe_float(getattr(l, "y0", 0.0), 0.0))
    return chosen


def _score_block(
    text: str,
    seed: Any,
    kind: str,
    code_ln: Any,
    lines: List[Any],
    span: float,
    target_anchor: float,
    title: str,
    same_row_tol: float,
) -> float:
    t = _norm(text)
    if not t:
        return -1e9
    if _is_field_code_line(t) or _is_bracket_metadata_line(t):
        return -1e9
    if title and _norm(title) == t:
        return -50.0

    y_seed = _safe_float(getattr(seed, "y0", 0.0), 0.0)
    x_seed = _safe_float(getattr(seed, "x0", 0.0), 0.0)
    sz = _safe_float(getattr(seed, "size", 0.0), 0.0)

    y_code = _safe_float(getattr(code_ln, "y0", y_seed), y_seed)
    x_code = _safe_float(getattr(code_ln, "x0", x_seed), x_seed)

    bold = bool(getattr(seed, "bold", False))
    non_black = bool(getattr(seed, "non_black", False))

    wc = _word_count(t)
    base = 0.0

    # Content preference (label-ish).
    base += 0.08 * min(120.0, float(len(t)))
    base += 0.55 * min(7.0, float(wc))
    if _has_struct_punct(t):
        base += 0.8

    # Style hints.
    if bold:
        base += 1.6
    if non_black:
        base += 0.6
    if sz > 0:
        base += max(0.0, min(1.2, (sz - 7.0) / 5.0))

    dx = abs(x_code - x_seed)
    dy = abs(y_code - y_seed)

    # Distance penalties/bonuses.
    if kind == "same_row_left":
        base -= 0.020 * dy
        base -= 0.0025 * max(0.0, (x_code - x_seed))
        if dy <= (same_row_tol + 1.0):
            base += max(0.0, 2.2 - 0.010 * dx)
    elif kind == "same_row_right":
        base -= 0.020 * dy
        base -= 0.0025 * max(0.0, (x_seed - x_code))
        if dy <= (same_row_tol + 1.0):
            base += max(0.0, 1.6 - 0.010 * dx)
    elif kind == "below":
        base -= 0.012 * max(0.0, (y_seed - y_code))
        base -= 0.002 * abs(x_seed - target_anchor)
        base -= 0.004 * min(200.0, dx)
    else:  # above / header_above
        base -= 0.010 * max(0.0, (y_code - y_seed))
        base -= 0.002 * abs(x_seed - target_anchor)
        base -= 0.004 * min(200.0, dx)

    # Penalize option-row-ish seeds only when they look like *answer options*.
    if _looks_like_option_row(seed, lines, span):
        if not (bold or non_black or sz >= 9.0 or _has_struct_punct(t)):
            base -= 4.0

    # Penalize very short, option-like tokens, but don't crush tight same-row labels (e.g., "Signed by").
    if wc <= 2 and len(t) <= 14 and not bold and not non_black and not _has_struct_punct(t):
        if kind in ("above", "below", "header_above"):
            base -= 2.6
        else:
            base -= 0.6

    # Penalize pulling from very top zone unless strongly styled.
    top_zone = min(160.0, max(110.0, 0.18 * span))
    if y_seed <= top_zone and abs(y_code - y_seed) > 70.0 and not bold and not non_black:
        base -= 2.0

    return base


def _header_label_for_code(code_ln: Any, lines: List[Any], span: float) -> str:
    y_code = _safe_float(getattr(code_ln, "y0", None), None)  # type: ignore[arg-type]
    x_code = _safe_float(getattr(code_ln, "x0", None), None)  # type: ignore[arg-type]
    if y_code is None or x_code is None:
        return ""

    tol = max(3.5, min(7.5, 0.010 * span))
    wrap_gap = max(16.0, min(26.0, 0.028 * span))
    max_up = max(70.0, min(125.0, 0.16 * span))

    # Gather labelish lines above code within window.
    above = []
    for ln in lines:
        y = _safe_float(getattr(ln, "y0", None), None)  # type: ignore[arg-type]
        if y is None:
            continue
        if not (y_code - max_up <= y <= y_code - 6.0):
            continue
        t = _norm(getattr(ln, "text", ""))
        if not _is_human_labelish(t):
            continue
        above.append(ln)

    if not above:
        return ""

    # Group by y buckets.
    buckets: Dict[int, List[Any]] = {}
    for ln in above:
        y = _safe_float(getattr(ln, "y0", 0.0), 0.0)
        k = int(round(y / tol))
        buckets.setdefault(k, []).append(ln)

    best_bucket: Optional[List[Any]] = None
    best_key = None

    for _, band in buckets.items():
        headerish = [ln for ln in band if _is_headerish(ln)]
        if len(headerish) < 3:
            continue
        xs = [_safe_float(getattr(ln, "x0", 0.0), 0.0) for ln in headerish]
        if not xs or (max(xs) - min(xs)) < 160.0:
            continue
        y_band = sum(_safe_float(getattr(ln, "y0", 0.0), 0.0) for ln in headerish) / float(len(headerish))
        key = (y_code - y_band, -len(headerish), min(xs))
        if best_key is None or key < best_key:
            best_key = key
            best_bucket = headerish

    if not best_bucket:
        return ""

    # Pick the header cell whose x0 is closest to code x.
    def pick_key(ln: Any) -> Tuple[float, float]:
        x = _safe_float(getattr(ln, "x0", 0.0), 0.0)
        # Prefer header starting at/before code slightly, but don't require it.
        bias = 0.0 if x <= (x_code + 35.0) else 25.0
        return (abs(x - x_code) + bias, x)

    seed = min(best_bucket, key=pick_key)

    seed_x = _safe_float(getattr(seed, "x0", 0.0), 0.0)
    seed_y = _safe_float(getattr(seed, "y0", 0.0), 0.0)
    seed_sz = _safe_float(getattr(seed, "size", 0.0), 0.0)

    # Collect wrapped header lines downwards but stop before the code.
    pool = []
    for ln in lines:
        y = _safe_float(getattr(ln, "y0", None), None)  # type: ignore[arg-type]
        if y is None:
            continue
        if not (seed_y - 1.0 <= y <= y_code - 3.0):
            continue
        t = _norm(getattr(ln, "text", ""))
        if not _is_human_labelish(t):
            continue
        x = _safe_float(getattr(ln, "x0", 0.0), 0.0)
        sz = _safe_float(getattr(ln, "size", 0.0), 0.0)
        if abs(x - seed_x) <= 140.0 and abs(sz - seed_sz) <= 2.8:
            pool.append(ln)

    block = _collect_wrap_block_limited(
        seed=seed,
        pool=pool,
        wrap_gap=wrap_gap,
        x_slack=140.0,
        size_slack=2.8,
        direction="down",
        y_min=seed_y - 1.0,
        y_max=y_code - 3.0,
    )
    return _join_wrapped(block)


def _page_x_anchors(lines: List[Any]) -> Tuple[float, float]:
    xs: List[float] = []
    for ln in lines:
        t = getattr(ln, "text", "")
        if not t or not t.strip():
            continue
        t = t.strip()
        if _is_field_code_line(t):
            continue
        if _is_bracket_metadata_line(t):
            continue
        if t.startswith("[") and t.endswith("]") and not _has_letter(t):
            continue
        if not _has_letter(t):
            continue
        if _safe_float(getattr(ln, "size", 0.0), 0.0) < 6.5:
            continue
        xs.append(_safe_float(getattr(ln, "x0", 0.0), 0.0))

    if not xs:
        return 50.0, 350.0

    xs.sort()
    n = len(xs)
    left = xs[int(0.25 * (n - 1))]
    right = xs[int(0.75 * (n - 1))]
    if right - left < 60:
        right = left + 300.0
    return left, right


def _detect_title(lines: List[Any], code_lines: List[Any]) -> str:
    span = _page_y_span(lines)
    top_zone = min(175.0, max(110.0, 0.20 * span))

    min_code_y: Optional[float] = None
    if code_lines:
        min_code_y = min(_safe_float(getattr(c, "y0", 1e9), 1e9) for c in code_lines)

    # Estimate typical label font size for the page.
    label_sizes: List[float] = []
    for ln in lines:
        t = _norm(getattr(ln, "text", ""))
        if not _is_human_labelish(t):
            continue
        sz = _safe_float(getattr(ln, "size", 0.0), 0.0)
        if 6.0 <= sz <= 14.0:
            label_sizes.append(sz)
    label_sizes.sort()
    median_sz = label_sizes[len(label_sizes) // 2] if label_sizes else 8.0

    cands: List[Any] = []
    for ln in lines:
        t = _norm(getattr(ln, "text", ""))
        if not t or not _has_letter(t):
            continue
        if _is_field_code_line(t) or _is_bracket_metadata_line(t):
            continue
        y0 = _safe_float(getattr(ln, "y0", 1e9), 1e9)
        if y0 > top_zone:
            continue
        if min_code_y is not None and y0 >= (min_code_y - 14.0):
            continue  # avoid picking a top-of-table field label as a title

        wc = _word_count(t)
        if wc < 2 and len(t) < 10:
            continue

        sz = _safe_float(getattr(ln, "size", 0.0), 0.0)
        bold = bool(getattr(ln, "bold", False))
        non_black = bool(getattr(ln, "non_black", False))
        # Require some title signal: bigger than typical OR styled.
        if not (sz >= (median_sz + 1.0) or sz >= 10.4 or bold or non_black):
            continue

        cands.append(ln)

    if not cands:
        return ""

    # Prefer the visually-strong block among candidates; allow wrap over 1-2 lines.
    wrap_gap = max(16.0, min(26.0, 0.030 * span))
    best_text = ""
    best_score = -1e9

    for seed in cands:
        seed_y = _safe_float(getattr(seed, "y0", 0.0), 0.0)
        seed_x = _safe_float(getattr(seed, "x0", 0.0), 0.0)
        seed_sz = _safe_float(getattr(seed, "size", 0.0), 0.0)

        pool = []
        for ln in lines:
            y = _safe_float(getattr(ln, "y0", 0.0), 0.0)
            if y < seed_y - 1.0 or y > top_zone:
                continue
            if min_code_y is not None and y >= (min_code_y - 10.0):
                continue
            t = _norm(getattr(ln, "text", ""))
            if not _is_human_labelish(t):
                continue
            x = _safe_float(getattr(ln, "x0", 0.0), 0.0)
            sz = _safe_float(getattr(ln, "size", 0.0), 0.0)
            if abs(x - seed_x) <= 160.0 and abs(sz - seed_sz) <= 2.8:
                pool.append(ln)

        block = _collect_wrap_block_limited(
            seed=seed,
            pool=pool,
            wrap_gap=wrap_gap,
            x_slack=160.0,
            size_slack=2.8,
            direction="down",
            y_min=seed_y - 1.0,
            y_max=(min_code_y - 10.0) if min_code_y is not None else top_zone,
        )
        text = _join_wrapped(block)
        if not text:
            continue

        bold = bool(getattr(seed, "bold", False))
        non_black = bool(getattr(seed, "non_black", False))

        score = 0.0
        score += 3.0 * seed_sz
        score += 0.08 * min(200.0, float(len(text)))
        score += 0.8 * min(8.0, float(_word_count(text)))
        if bold:
            score += 3.0
        if non_black:
            score += 1.2
        # Slight preference for titles nearer the left margin.
        score -= 0.010 * max(0.0, seed_x - 70.0)
        # Prefer higher (smaller y).
        score -= 0.020 * seed_y

        if score > best_score:
            best_score = score
            best_text = text

    return best_text


def _detect_section_title_near_code(lines: List[Any], code_lines: List[Any]) -> str:
    if not code_lines:
        return ""
    span = _page_y_span(lines)
    min_code_y = min(_safe_float(getattr(c, "y0", 1e9), 1e9) for c in code_lines)
    x_code = _safe_float(getattr(min(code_lines, key=lambda c: _safe_float(getattr(c, "y0", 1e9), 1e9)), "x0", 0.0), 0.0)

    window_up = max(60.0, min(160.0, 0.22 * span))
    cands = []
    for ln in lines:
        t = _norm(getattr(ln, "text", ""))
        if not _is_human_labelish(t):
            continue
        y = _safe_float(getattr(ln, "y0", 1e9), 1e9)
        if not (min_code_y - window_up <= y <= min_code_y - 10.0):
            continue
        sz = _safe_float(getattr(ln, "size", 0.0), 0.0)
        bold = bool(getattr(ln, "bold", False))
        non_black = bool(getattr(ln, "non_black", False))
        if not (bold or non_black or sz >= 10.0):
            continue
        if _word_count(t) < 2 and len(t) < 10:
            continue
        cands.append(ln)

    if not cands:
        return ""

    # Prefer the strongest style, then closest to the first code, then left-ish.
    def k(ln: Any) -> Tuple[float, float, float]:
        t = _norm(getattr(ln, "text", ""))
        y = _safe_float(getattr(ln, "y0", 1e9), 1e9)
        x = _safe_float(getattr(ln, "x0", 0.0), 0.0)
        sz = _safe_float(getattr(ln, "size", 0.0), 0.0)
        bold = bool(getattr(ln, "bold", False))
        non_black = bool(getattr(ln, "non_black", False))
        strength = -(sz + (2.0 if bold else 0.0) + (1.0 if non_black else 0.0) + 0.02 * min(80.0, len(t)))
        return (strength, abs(min_code_y - y), abs(x - x_code))

    seed = min(cands, key=k)

    wrap_gap = max(16.0, min(26.0, 0.030 * span))
    seed_x = _safe_float(getattr(seed, "x0", 0.0), 0.0)
    seed_y = _safe_float(getattr(seed, "y0", 0.0), 0.0)
    seed_sz = _safe_float(getattr(seed, "size", 0.0), 0.0)

    pool = []
    for ln in lines:
        y = _safe_float(getattr(ln, "y0", 0.0), 0.0)
        if y < seed_y - 1.0 or y > (min_code_y - 10.0):
            continue
        t = _norm(getattr(ln, "text", ""))
        if not _is_human_labelish(t):
            continue
        x = _safe_float(getattr(ln, "x0", 0.0), 0.0)
        sz = _safe_float(getattr(ln, "size", 0.0), 0.0)
        if abs(x - seed_x) <= 170.0 and abs(sz - seed_sz) <= 2.8:
            pool.append(ln)

    block = _collect_wrap_block_limited(
        seed=seed,
        pool=pool,
        wrap_gap=wrap_gap,
        x_slack=170.0,
        size_slack=2.8,
        direction="down",
        y_min=seed_y - 1.0,
        y_max=min_code_y - 10.0,
    )
    return _join_wrapped(block)


def _label_for_code(code_ln: Any, lines: List[Any], left_anchor: float, right_anchor: float, title: str) -> str:
    y_code = _safe_float(getattr(code_ln, "y0", None), None)  # type: ignore[arg-type]
    x_code = _safe_float(getattr(code_ln, "x0", None), None)  # type: ignore[arg-type]
    if y_code is None or x_code is None:
        return ""

    span = _page_y_span(lines)

    # First: try table header mapping (captures column headers like Heart Rate (bpm), Time of Vitals Measurement).
    hdr = _header_label_for_code(code_ln, lines, span)
    if hdr:
        if not (_is_bracket_metadata_line(hdr) or _is_field_code_line(hdr) or _is_row_header(hdr)):
            if not (title and _norm(title) == _norm(hdr)):
                return hdr

    window_up = max(150.0, min(280.0, 0.32 * span))
    window_down = max(90.0, min(200.0, 0.24 * span))
    wrap_gap = max(18.0, min(28.0, 0.030 * span))
    same_row_tol = max(3.5, min(7.5, 0.010 * span))

    prev_top = y_code - window_up
    prev_bottom = y_code - 1.0
    next_top = y_code + 1.0
    next_bottom = y_code + window_down

    prev: List[Any] = []
    nxt: List[Any] = []
    for ln in lines:
        y = _safe_float(getattr(ln, "y0", None), None)  # type: ignore[arg-type]
        if y is None:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not _is_human_labelish(t):
            continue
        if prev_top <= y <= prev_bottom:
            prev.append(ln)
        elif next_top <= y <= next_bottom:
            nxt.append(ln)

    same_left: List[Any] = []
    same_right: List[Any] = []
    for ln in lines:
        y = _safe_float(getattr(ln, "y0", None), None)  # type: ignore[arg-type]
        x = _safe_float(getattr(ln, "x0", None), None)  # type: ignore[arg-type]
        if y is None or x is None:
            continue
        if abs(y - y_code) > same_row_tol:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not _is_human_labelish(t):
            continue
        if x <= (x_code - 16.0) and (x_code - x) <= 520.0:
            same_left.append(ln)
        elif x >= (x_code + 12.0) and (x - x_code) <= 560.0:
            same_right.append(ln)

    if not prev and not nxt and not same_left and not same_right:
        return ""

    target_anchor = left_anchor if abs(x_code - left_anchor) <= abs(x_code - right_anchor) else right_anchor

    def _filter_col(cands: List[Any], anchor: float, slack: float) -> List[Any]:
        out: List[Any] = []
        for ln in cands:
            x0 = _safe_float(getattr(ln, "x0", None), None)  # type: ignore[arg-type]
            if x0 is None:
                continue
            if abs(x0 - anchor) <= slack:
                out.append(ln)
        return out

    col_prev = _filter_col(prev, target_anchor, 240.0)
    col_next = _filter_col(nxt, target_anchor, 260.0)

    if not col_prev:
        fallback = _filter_col(prev, left_anchor, 290.0)
        col_prev = fallback or prev
    if not col_next:
        fallback = _filter_col(nxt, left_anchor, 310.0)
        col_next = fallback or nxt

    candidates: List[Tuple[str, Any]] = []
    for ln in col_prev:
        candidates.append(("above", ln))
    for ln in same_left:
        candidates.append(("same_row_left", ln))
    for ln in same_right:
        candidates.append(("same_row_right", ln))
    for ln in col_next:
        candidates.append(("below", ln))

    best_text = ""
    best_score = -1e9

    for kind, seed in candidates:
        bold = bool(getattr(seed, "bold", False))

        if kind == "same_row_left":
            pool = same_left + col_prev
            block = _collect_wrap_block_limited(
                seed=seed,
                pool=pool,
                wrap_gap=wrap_gap,
                x_slack=130.0 if bold else 105.0,
                size_slack=2.6,
                direction="up",
                y_min=prev_top,
                y_max=y_code - 1.0,
            )
        elif kind == "same_row_right":
            pool = same_right + col_next
            block = _collect_wrap_block_limited(
                seed=seed,
                pool=pool,
                wrap_gap=wrap_gap,
                x_slack=145.0 if bold else 120.0,
                size_slack=2.8,
                direction="down",
                y_min=y_code + 1.0,
                y_max=next_bottom,
            )
        elif kind == "below":
            pool = col_next
            block = _collect_wrap_block_limited(
                seed=seed,
                pool=pool,
                wrap_gap=wrap_gap,
                x_slack=140.0 if bold else 115.0,
                size_slack=2.8,
                direction="down",
                y_min=next_top,
                y_max=next_bottom,
            )
        else:  # above
            pool = col_prev
            block = _collect_wrap_block_limited(
                seed=seed,
                pool=pool,
                wrap_gap=wrap_gap,
                x_slack=130.0 if bold else 105.0,
                size_slack=2.6,
                direction="up",
                y_min=prev_top,
                y_max=prev_bottom,
            )

        text = _join_wrapped(block)
        if not text:
            continue
        if _is_bracket_metadata_line(text) or _is_field_code_line(text) or _is_row_header(text):
            continue

        score = _score_block(
            text=text,
            seed=seed,
            kind=kind,
            code_ln=code_ln,
            lines=lines,
            span=span,
            target_anchor=target_anchor,
            title=title,
            same_row_tol=same_row_tol,
        )
        if score > best_score:
            best_score = score
            best_text = text

    return best_text


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()

    current_form = ""
    for page_idx0, lines in pages:
        # Identify field code anchors first.
        code_lines: List[Any] = []
        for ln in lines:
            t = getattr(ln, "text", "")
            if not t:
                continue
            if _is_field_code_line(t.strip()):
                code_lines.append(ln)

        # Update form context only on pages that actually carry fields (codes).
        page_title = ""
        if code_lines:
            page_title = _detect_title(lines, code_lines)
            if not page_title:
                page_title = _detect_section_title_near_code(lines, code_lines)

            page_title = _norm(page_title)
            if page_title.endswith(":"):
                page_title = _norm(page_title[:-1])

            if page_title and _has_letter(page_title):
                current_form = page_title

        left_anchor, right_anchor = _page_x_anchors(lines)
        form_name = current_form or ""

        for code_ln in code_lines:
            code_text = _norm(getattr(code_ln, "text", ""))
            if not code_text or not _is_field_code_line(code_text):
                continue

            field = _label_for_code(code_ln, lines, left_anchor, right_anchor, title=form_name)
            field = _norm(field)
            if not field:
                continue
            if _is_bracket_metadata_line(field) or _is_field_code_line(field) or _is_row_header(field):
                continue
            if form_name and _norm(form_name) == field:
                continue

            # Allow repeated same-label fields; key uniqueness by code + approximate position.
            yk = int(round(_safe_float(getattr(code_ln, "y0", 0.0), 0.0) / 2.0))
            xk = int(round(_safe_float(getattr(code_ln, "x0", 0.0), 0.0) / 2.0))
            key = (page_idx0 + 1, code_text, yk, xk)
            if key in seen:
                continue
            seen.add(key)

            out.append({"form_name": form_name, "field_name": field, "page": page_idx0 + 1})

    return out
```
