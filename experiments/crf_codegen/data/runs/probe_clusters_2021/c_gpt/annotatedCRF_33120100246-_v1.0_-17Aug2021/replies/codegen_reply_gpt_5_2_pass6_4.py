```python
import re
from typing import List, Tuple, Dict, Any


_CODE_RE = re.compile(r"^\[[A-Za-z0-9][A-Za-z0-9_\-]*\]$")
_ROW_RE = re.compile(r"^\s*Row\s*\d+\s*$", re.IGNORECASE)
_SPACES_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    s = s.strip()
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
    # Accept only machine-like bracket codes, not metadata like [TYPE: ...]
    return bool(_CODE_RE.match(text.strip()))


def _is_row_header(text: str) -> bool:
    return bool(_ROW_RE.match(text.strip()))


def _is_bracket_metadata_line(text: str) -> bool:
    t = text.strip()
    return t.startswith("[") and t.endswith("]") and (":" in t)


def _page_y_span(lines: List[Any]) -> float:
    ys = []
    for ln in lines:
        try:
            ys.append(float(ln.y0))
        except Exception:
            continue
    if not ys:
        return 800.0
    y_min, y_max = min(ys), max(ys)
    span = y_max - y_min
    return span if span > 1.0 else 800.0


def _join_wrapped(lines: List[Any]) -> str:
    parts = []
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


def _page_x_anchors(lines: List[Any]) -> Tuple[float, float]:
    xs = []
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
        if float(getattr(ln, "size", 0.0) or 0.0) < 6.5:
            continue
        try:
            xs.append(float(ln.x0))
        except Exception:
            continue

    if not xs:
        return 50.0, 350.0

    xs.sort()
    n = len(xs)
    left = xs[int(0.25 * (n - 1))]
    right = xs[int(0.75 * (n - 1))]
    if right - left < 60:
        right = left + 300.0
    return left, right


def _detect_title(lines: List[Any]) -> str:
    span = _page_y_span(lines)
    top_zone = min(160.0, max(110.0, 0.18 * span))

    cands = []
    for ln in lines:
        t = _norm(getattr(ln, "text", ""))
        if not t or not _has_letter(t):
            continue
        if _is_field_code_line(t) or _is_bracket_metadata_line(t):
            continue
        try:
            y0 = float(ln.y0)
        except Exception:
            continue
        if y0 > top_zone:
            continue

        size = float(getattr(ln, "size", 0.0) or 0.0)
        non_black = bool(getattr(ln, "non_black", False))
        bold = bool(getattr(ln, "bold", False))
        if size >= 11.0 or non_black or bold:
            cands.append(ln)

    if not cands:
        return ""

    max_size = max(float(getattr(l, "size", 0.0) or 0.0) for l in cands)

    best = None
    best_key = None
    for ln in cands:
        size = float(getattr(ln, "size", 0.0) or 0.0)
        if size < (max_size - 0.6):
            continue
        y0 = float(getattr(ln, "y0", 0.0) or 0.0)
        x0 = float(getattr(ln, "x0", 0.0) or 0.0)
        non_black = bool(getattr(ln, "non_black", False))
        bold = bool(getattr(ln, "bold", False))
        key = (y0, x0, -size, 0 if non_black else 1, 0 if bold else 1)
        if best is None or key < best_key:
            best = ln
            best_key = key

    if best is None:
        best = min(
            cands,
            key=lambda l: (
                -(float(getattr(l, "size", 0.0) or 0.0)),
                float(getattr(l, "y0", 0.0) or 0.0),
                float(getattr(l, "x0", 0.0) or 0.0),
                0 if bool(getattr(l, "non_black", False)) else 1,
                0 if bool(getattr(l, "bold", False)) else 1,
            ),
        )

    return _norm(getattr(best, "text", ""))


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


def _lines_in_y_band(lines: List[Any], y0: float, tol: float) -> List[Any]:
    band = []
    for ln in lines:
        try:
            y = float(ln.y0)
        except Exception:
            continue
        if abs(y - y0) <= tol:
            band.append(ln)
    return band


def _looks_like_option_row(seed: Any, lines: List[Any], span: float) -> bool:
    try:
        y0 = float(seed.y0)
    except Exception:
        return False

    tol = max(3.5, min(7.5, 0.010 * span))
    band = _lines_in_y_band(lines, y0, tol)

    seed_size = float(getattr(seed, "size", 0.0) or 0.0)
    shortish = []
    xs = []
    for ln in band:
        t = _norm(getattr(ln, "text", ""))
        if not _is_human_labelish(t):
            continue
        size = float(getattr(ln, "size", 0.0) or 0.0)
        if abs(size - seed_size) > 1.2:
            continue
        wc = _word_count(t)
        if wc <= 3 and len(t) <= 22 and not _has_struct_punct(t):
            shortish.append(ln)
            try:
                xs.append(float(ln.x0))
            except Exception:
                pass

    if len(shortish) < 3 or len(xs) < 3:
        return False
    if (max(xs) - min(xs)) < 180.0:
        return False
    return True


def _collect_wrap_block(
    seed: Any,
    pool: List[Any],
    wrap_gap: float,
    x_slack: float,
    size_slack: float,
    direction: str,
) -> List[Any]:
    try:
        base_x = float(getattr(seed, "x0", 0.0) or 0.0)
        base_y = float(getattr(seed, "y0", 0.0) or 0.0)
        base_size = float(getattr(seed, "size", 0.0) or 0.0)
    except Exception:
        return [seed]

    chosen = [seed]
    chosen_ids = {id(seed)}
    last_y = base_y

    if direction == "down":
        ordered = sorted(pool, key=lambda l: float(getattr(l, "y0", 0.0) or 0.0))
        for ln in ordered:
            if id(ln) in chosen_ids:
                continue
            try:
                y = float(getattr(ln, "y0", 0.0) or 0.0)
                x = float(getattr(ln, "x0", 0.0) or 0.0)
                sz = float(getattr(ln, "size", 0.0) or 0.0)
            except Exception:
                continue
            if y < base_y:
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
        # Walk upward (toward smaller y), grabbing wrap lines close in y/x/size.
        ordered = sorted(pool, key=lambda l: float(getattr(l, "y0", 0.0) or 0.0), reverse=True)
        for ln in ordered:
            if id(ln) in chosen_ids:
                continue
            try:
                y = float(getattr(ln, "y0", 0.0) or 0.0)
                x = float(getattr(ln, "x0", 0.0) or 0.0)
                sz = float(getattr(ln, "size", 0.0) or 0.0)
            except Exception:
                continue
            if y > base_y:
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

    chosen.sort(key=lambda l: float(getattr(l, "y0", 0.0) or 0.0))
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
) -> float:
    t = _norm(text)
    if not t:
        return -1e9
    if _is_field_code_line(t) or _is_bracket_metadata_line(t):
        return -1e9
    if title and _norm(title) == t:
        return -50.0

    try:
        y_seed = float(getattr(seed, "y0", 0.0) or 0.0)
        x_seed = float(getattr(seed, "x0", 0.0) or 0.0)
        sz = float(getattr(seed, "size", 0.0) or 0.0)
    except Exception:
        y_seed = 0.0
        x_seed = 0.0
        sz = 0.0

    try:
        y_code = float(getattr(code_ln, "y0", 0.0) or 0.0)
        x_code = float(getattr(code_ln, "x0", 0.0) or 0.0)
    except Exception:
        y_code = y_seed
        x_code = x_seed

    bold = bool(getattr(seed, "bold", False))
    non_black = bool(getattr(seed, "non_black", False))

    wc = _word_count(t)
    base = 0.0

    # Prefer label-ish text (some length/structure).
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

    # Distance penalties.
    if kind == "same_row_left":
        base -= 0.03 * abs(y_code - y_seed)
        base -= 0.004 * max(0.0, (x_code - x_seed))
    elif kind == "same_row_right":
        base -= 0.03 * abs(y_code - y_seed)
        base -= 0.004 * max(0.0, (x_seed - x_code))
    elif kind == "below":
        base -= 0.012 * max(0.0, (y_seed - y_code))
        base -= 0.002 * abs(x_seed - target_anchor)
    else:  # above
        base -= 0.010 * max(0.0, (y_code - y_seed))
        base -= 0.002 * abs(x_seed - target_anchor)

    # Penalize option-row-ish seeds unless strongly styled.
    if _looks_like_option_row(seed, lines, span) and not bold:
        base -= 4.0

    # Penalize very short, option-like tokens (generic, not literal).
    if wc <= 2 and len(t) <= 14 and not bold and not non_black and not _has_struct_punct(t):
        base -= 2.6

    # Penalize picking from the very top zone unless it's clearly a label block.
    top_zone = min(160.0, max(110.0, 0.18 * span))
    if y_seed <= top_zone and abs(y_code - y_seed) > 70.0 and not bold and not non_black:
        base -= 2.0

    return base


def _label_for_code(code_ln: Any, lines: List[Any], left_anchor: float, right_anchor: float, title: str) -> str:
    try:
        y_code = float(code_ln.y0)
        x_code = float(code_ln.x0)
    except Exception:
        return ""

    span = _page_y_span(lines)
    window_up = max(150.0, min(280.0, 0.32 * span))
    window_down = max(80.0, min(180.0, 0.22 * span))
    wrap_gap = max(18.0, min(28.0, 0.030 * span))
    same_row_tol = max(3.5, min(7.5, 0.010 * span))

    prev_top = y_code - window_up
    prev_bottom = y_code - 1.0
    next_top = y_code + 1.0
    next_bottom = y_code + window_down

    prev = []
    nxt = []
    for ln in lines:
        try:
            y = float(ln.y0)
        except Exception:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not _is_human_labelish(t):
            continue
        if prev_top <= y <= prev_bottom:
            prev.append(ln)
        elif next_top <= y <= next_bottom:
            nxt.append(ln)

    same_left = []
    same_right = []
    for ln in lines:
        try:
            y = float(ln.y0)
            x = float(ln.x0)
        except Exception:
            continue
        if abs(y - y_code) > same_row_tol:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not _is_human_labelish(t):
            continue
        if x <= (x_code - 16.0) and (x_code - x) <= 460.0:
            same_left.append(ln)
        elif x >= (x_code + 12.0) and (x - x_code) <= 520.0:
            same_right.append(ln)

    if not prev and not nxt and not same_left and not same_right:
        return ""

    # Choose which text column this field label likely belongs to.
    target_anchor = left_anchor if abs(x_code - left_anchor) <= abs(x_code - right_anchor) else right_anchor

    def _filter_col(cands: List[Any], anchor: float, slack: float) -> List[Any]:
        out = []
        for ln in cands:
            try:
                x0 = float(ln.x0)
            except Exception:
                continue
            if abs(x0 - anchor) <= slack:
                out.append(ln)
        return out

    col_prev = _filter_col(prev, target_anchor, 220.0)
    col_next = _filter_col(nxt, target_anchor, 240.0)

    if not col_prev:
        fallback = _filter_col(prev, left_anchor, 270.0)
        col_prev = fallback or prev
    if not col_next:
        fallback = _filter_col(nxt, left_anchor, 290.0)
        col_next = fallback or nxt

    candidates = []
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

    # Build blocks and score.
    for kind, seed in candidates:
        bold = bool(getattr(seed, "bold", False))

        if kind == "same_row_left":
            pool = same_left
            block = _collect_wrap_block(
                seed=seed,
                pool=pool,
                wrap_gap=wrap_gap,
                x_slack=120.0 if bold else 95.0,
                size_slack=2.4,
                direction="up",
            )
        elif kind == "same_row_right":
            # Allow labels that start to the right of the code and wrap down.
            pool = same_right + col_next
            block = _collect_wrap_block(
                seed=seed,
                pool=pool,
                wrap_gap=wrap_gap,
                x_slack=135.0 if bold else 110.0,
                size_slack=2.6,
                direction="down",
            )
        elif kind == "below":
            pool = col_next
            block = _collect_wrap_block(
                seed=seed,
                pool=pool,
                wrap_gap=wrap_gap,
                x_slack=130.0 if bold else 105.0,
                size_slack=2.6,
                direction="down",
            )
        else:  # above
            pool = col_prev
            block = _collect_wrap_block(
                seed=seed,
                pool=pool,
                wrap_gap=wrap_gap,
                x_slack=120.0 if bold else 95.0,
                size_slack=2.4,
                direction="up",
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
        code_lines = []
        for ln in lines:
            t = getattr(ln, "text", "")
            if not t:
                continue
            if _is_field_code_line(t.strip()):
                code_lines.append(ln)

        # Update form context only on pages that actually carry fields (codes),
        # to avoid TOC/schedule pages overwriting the running title.
        page_title = ""
        if code_lines:
            page_title = _detect_title(lines)
            if page_title:
                current_form = page_title

        left_anchor, right_anchor = _page_x_anchors(lines)
        form_name = current_form or ""

        for code_ln in code_lines:
            code_text = _norm(getattr(code_ln, "text", ""))
            if not code_text or not _is_field_code_line(code_text):
                continue

            field = _label_for_code(code_ln, lines, left_anchor, right_anchor, title=form_name)
            if not field:
                continue
            if _is_bracket_metadata_line(field) or _is_field_code_line(field) or _is_row_header(field):
                continue

            # Allow repeated same-label fields; key uniqueness by code + approximate position.
            try:
                yk = int(round(float(getattr(code_ln, "y0", 0.0) or 0.0) / 2.0))
                xk = int(round(float(getattr(code_ln, "x0", 0.0) or 0.0) / 2.0))
            except Exception:
                yk, xk = 0, 0
            key = (page_idx0 + 1, code_text, yk, xk)
            if key in seen:
                continue
            seen.add(key)

            out.append({"form_name": form_name, "field_name": field, "page": page_idx0 + 1})

    return out
```
