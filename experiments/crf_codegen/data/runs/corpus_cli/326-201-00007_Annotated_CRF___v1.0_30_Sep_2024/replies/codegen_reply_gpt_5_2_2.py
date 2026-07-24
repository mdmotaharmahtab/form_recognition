```python
import re
import unicodedata
from statistics import median

_WS_RE = re.compile(r"\s+")
_UNDERSCORE_RE = re.compile(r"_")
_MACHINEISH_RE = re.compile(r"^\s*\[[^\]]+\]\s*(?:SAS:)?", re.I)


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def _has_alpha(s: str) -> bool:
    for ch in s or "":
        if ch.isalpha():
            return True
        if unicodedata.category(ch).startswith("L"):
            return True
    return False


def _is_footer(ln) -> bool:
    return ln.y0 >= 720


def _infer_body_size(lines) -> float:
    sizes = [
        ln.size
        for ln in lines
        if 130 <= ln.y0 <= 710 and not _is_footer(ln) and not ln.non_black and (ln.text or "").strip()
    ]
    return float(median(sizes)) if sizes else 10.0


def _infer_label_x(lines, body_size: float) -> float:
    xs = []
    for ln in lines:
        if ln.y0 < 120 or _is_footer(ln):
            continue
        if ln.non_black:
            continue
        if not (body_size - 2.5 <= ln.size <= body_size + 3.5):
            continue
        if not ln.bold:
            continue
        if ln.x0 < 90:
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _MACHINEISH_RE.match(t):
            continue
        xs.append(ln.x0)
    return float(median(xs)) if xs else 170.0


def _is_date_placeholder_row(ln, body_size: float) -> bool:
    if ln.x0 > 90:
        return False
    if ln.non_black:
        return False
    if not (body_size - 2.5 <= ln.size <= body_size + 3.5):
        return False
    t = (ln.text or "").strip()
    if not t:
        return False
    if "-" not in t:
        return False
    if t.count("_") < 6:
        return False
    if len(t) < 8:
        return False
    return True


def _is_value_placeholder(ln, body_size: float) -> bool:
    # Generic input line made of underscores (not the left-column date placeholder)
    if ln.x0 <= 90:
        return False
    if ln.non_black:
        return False
    if not (body_size - 2.5 <= ln.size <= body_size + 4.0):
        return False
    t = (ln.text or "").strip()
    if not t:
        return False
    if t.count("_") < 6:
        return False
    if _has_alpha(t):
        return False
    # Allow punctuation/spaces around underscores; avoid tiny artifacts
    non_us = [ch for ch in t if ch != "_" and not ch.isspace()]
    if len(non_us) > max(4, len(t) // 6):
        return False
    return True


def _find_top_field_y(lines, body_size: float):
    ys = []
    for ln in lines:
        if ln.y0 < 120 or _is_footer(ln):
            continue
        if _is_date_placeholder_row(ln, body_size) or _is_value_placeholder(ln, body_size):
            ys.append(ln.y0)
    return min(ys) if ys else None


def _pick_form_title(lines, body_size: float, band_y_max: float):
    # Prefer a bold/larger title above the first fields on *this* page.
    # Fallbacks are allowed, but only if they look title-ish by style/geometry.
    cands = []
    for ln in lines:
        if _is_footer(ln):
            continue
        if ln.y0 > band_y_max:
            continue
        if ln.x0 < 40:
            continue
        if ln.non_black:
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _UNDERSCORE_RE.search(t):
            continue
        if _MACHINEISH_RE.match(t):
            continue
        if not _has_alpha(t):
            continue

        # Title-ish: either larger-than-body, or bold near the very top band.
        size_up = ln.size - body_size
        titleish = (size_up >= 0.9) or (ln.bold and ln.y0 <= 140 and size_up >= -0.2)
        if not titleish:
            continue
        cands.append(ln)

    if not cands:
        return None

    # Anchor on the strongest single line, then collect adjacent lines (multi-line title).
    def line_score(ln):
        t = _norm(ln.text)
        size_up = ln.size - body_size
        return (ln.size * 120.0) + (24.0 if ln.bold else 0.0) + (min(len(t), 160) / 2.0) + (size_up * 40.0) - (ln.y0 / 40.0)

    anchor = max(cands, key=line_score)
    a_size = anchor.size
    a_y = anchor.y0

    block = []
    for ln in cands:
        if abs(ln.size - a_size) > 1.4:
            continue
        if ln.y0 < a_y - 2.0:
            continue
        if ln.y0 > a_y + 30.0:
            continue
        # Keep roughly the same horizontal band; titles often start near label column
        if ln.x0 > 540:
            continue
        block.append(ln)

    block.sort(key=lambda l: (l.y0, l.x0))
    text = _norm(" ".join(_norm(l.text) for l in block if _norm(l.text)))

    # Confidence gate: keep titles that are substantial and style-strong.
    if len(text) < 10:
        return None
    # Require that at least one line is clearly above body or bold.
    if not any((l.size - body_size) >= 0.9 or l.bold for l in block):
        return None
    return text


def _find_aligned_label(lines, y, label_x, body_size: float):
    best = None
    best_dx = None
    for ln in lines:
        if abs(ln.y0 - y) > 3.2:
            continue
        if ln.non_black:
            continue
        if not (body_size - 2.5 <= ln.size <= body_size + 3.5):
            continue
        if ln.x0 < 110:
            continue
        if abs(ln.x0 - label_x) > 155:
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _UNDERSCORE_RE.search(t):
            continue
        if _MACHINEISH_RE.match(t):
            continue
        if not _has_alpha(t):
            continue

        dx = abs(ln.x0 - label_x) + (0.0 if ln.bold else 55.0)
        if best is None or dx < best_dx:
            best = ln
            best_dx = dx
    return best


def _find_label_left_of_placeholder(lines, ph_ln, label_x, body_size: float):
    best = None
    best_score = None
    y = ph_ln.y0
    x_limit = ph_ln.x0 - 6.0

    for ln in lines:
        if abs(ln.y0 - y) > 4.5:
            continue
        if ln.non_black:
            continue
        if not (body_size - 2.5 <= ln.size <= body_size + 3.5):
            continue
        if ln.x0 < 80:
            continue
        if ln.x0 >= x_limit:
            continue
        # Prefer the main label column, but allow slightly left/right drift.
        if abs(ln.x0 - label_x) > 190:
            continue

        t = _norm(ln.text)
        if not t:
            continue
        if _UNDERSCORE_RE.search(t):
            continue
        if _MACHINEISH_RE.match(t):
            continue
        if not _has_alpha(t):
            continue

        # Score: closeness to label column and proximity to placeholder start.
        score = abs(ln.x0 - label_x) + max(0.0, (x_limit - ln.x0) / 40.0) + (0.0 if ln.bold else 20.0)
        if best is None or score < best_score:
            best = ln
            best_score = score

    return best


def _collect_wrapped(lines, start_ln, body_size: float):
    x0 = start_ln.x0
    y0 = start_ln.y0
    want_bold = start_ln.bold
    parts = [_norm(start_ln.text)]
    prev_y = y0
    max_span = 44.0
    gap = 16.5

    cands = []
    for ln in lines:
        if ln is start_ln:
            continue
        if ln.y0 <= y0:
            continue
        if ln.y0 > y0 + max_span:
            continue
        if ln.non_black:
            continue
        if not (body_size - 2.5 <= ln.size <= body_size + 3.5):
            continue
        if abs(ln.x0 - x0) > 16.5:
            continue
        if want_bold and not ln.bold:
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _MACHINEISH_RE.match(t):
            continue
        if _UNDERSCORE_RE.search(t):
            continue
        if not _has_alpha(t):
            continue
        cands.append(ln)

    cands.sort(key=lambda l: (l.y0, l.x0))
    for ln in cands:
        if ln.y0 - prev_y > gap:
            break
        parts.append(_norm(ln.text))
        prev_y = ln.y0

    return _norm(" ".join(p for p in parts if p))


def extract(pages):
    out = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        body_size = _infer_body_size(lines)
        label_x = _infer_label_x(lines, body_size)

        # Update carried form name using a per-page title found above the first fields.
        top_field_y = _find_top_field_y(lines, body_size)
        band_y_max = 170.0
        if top_field_y is not None:
            band_y_max = max(140.0, min(260.0, top_field_y - 6.0))

        fm = _pick_form_title(lines, body_size, band_y_max)
        if fm:
            current_form = fm

        # Extract fields triggered by left-column date placeholders (original strategy).
        seen = set()
        for ln in lines:
            if _is_footer(ln) or ln.y0 < 120:
                continue
            if not _is_date_placeholder_row(ln, body_size):
                continue

            yk = int(round(ln.y0))
            if ("date_row", yk) in seen:
                continue
            seen.add(("date_row", yk))

            start = _find_aligned_label(lines, ln.y0, label_x, body_size)
            if not start:
                continue

            field = _collect_wrapped(lines, start, body_size)
            if not field or not _has_alpha(field):
                continue

            out.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

        # Additional extraction: labels aligned to generic underscore input lines (e.g., "Other (Specify)").
        for ln in lines:
            if _is_footer(ln) or ln.y0 < 120:
                continue
            if not _is_value_placeholder(ln, body_size):
                continue

            start = _find_label_left_of_placeholder(lines, ln, label_x, body_size)
            if not start:
                continue

            key = ("val_row", int(round(start.y0)), int(round(start.x0)))
            if key in seen:
                continue
            seen.add(key)

            field = _collect_wrapped(lines, start, body_size)
            if not field or not _has_alpha(field):
                continue

            out.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

    return out
```
