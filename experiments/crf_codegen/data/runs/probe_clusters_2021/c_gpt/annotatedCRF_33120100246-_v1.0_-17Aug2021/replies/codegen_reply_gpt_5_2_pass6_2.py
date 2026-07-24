```python
import re
from typing import List, Tuple, Dict, Any


_CODE_RE = re.compile(r"^\[[A-Za-z0-9][A-Za-z0-9_]*\]$")
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


def _is_field_code_line(text: str) -> bool:
    # Accept only machine-like bracket codes, not metadata like [TYPE: ...]
    return bool(_CODE_RE.match(text.strip()))


def _is_row_header(text: str) -> bool:
    return bool(_ROW_RE.match(text.strip()))


def _is_bracket_metadata_line(text: str) -> bool:
    # Structural filter: bracketed + colon lines are typically technical metadata,
    # not human labels (e.g., [TYPE: ...], [VISIBILITY: ...]).
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
    # Estimate left/right text columns using x0 distribution of human-readable lines.
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
        # Avoid tiny headers/footers by size
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
    # Prominent header near top-left: usually larger font and/or colored.
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
            x0 = float(ln.x0)
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


def _label_for_code(code_ln: Any, lines: List[Any], left_anchor: float, right_anchor: float) -> str:
    try:
        y_code = float(code_ln.y0)
    except Exception:
        return ""

    span = _page_y_span(lines)
    # Slacky, scale-aware vertical windows (keeps previous behavior on typical pages)
    window_up = max(130.0, min(200.0, 0.22 * span))
    wrap_gap = max(18.0, min(26.0, 0.028 * span))

    window_top = y_code - window_up
    window_bottom = y_code - 1.0

    prev = []
    for ln in lines:
        try:
            y = float(ln.y0)
        except Exception:
            continue
        if y < window_top or y > window_bottom:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        if _is_field_code_line(t):
            continue
        if _is_bracket_metadata_line(t):
            continue
        if t.startswith("[") and t.endswith("]") and not _has_letter(t):
            continue
        if not _has_letter(t) and "?" not in t:
            continue
        if _is_row_header(t):
            continue
        prev.append(ln)

    if not prev:
        return ""

    # Choose which text column this field label likely belongs to.
    try:
        mid_pref = float(code_ln.x0)
    except Exception:
        mid_pref = left_anchor
    target_anchor = left_anchor if abs(mid_pref - left_anchor) <= abs(mid_pref - right_anchor) else right_anchor

    # Filter to the nearest plausible column, but allow indents.
    col_prev = []
    for ln in prev:
        try:
            x0 = float(ln.x0)
        except Exception:
            continue
        if abs(x0 - target_anchor) <= 210.0:
            col_prev.append(ln)

    if not col_prev:
        # If code is far left (codes printed in left margin), labels still likely in left column.
        fallback = []
        for ln in prev:
            try:
                x0 = float(ln.x0)
            except Exception:
                continue
            if abs(x0 - left_anchor) <= 260.0:
                fallback.append(ln)
        col_prev = fallback or prev

    # Prefer bold label blocks when present reasonably near the code.
    bold_prev = []
    for ln in col_prev:
        if not bool(getattr(ln, "bold", False)):
            continue
        try:
            if (y_code - float(ln.y0)) <= min(140.0, 0.18 * span):
                bold_prev.append(ln)
        except Exception:
            continue

    if bold_prev:
        bottom = max(bold_prev, key=lambda l: float(getattr(l, "y0", 0.0) or 0.0))
        base_x = float(getattr(bottom, "x0", 0.0) or 0.0)

        chosen = [bottom]
        chosen_ids = {id(bottom)}
        last_y = float(getattr(bottom, "y0", 0.0) or 0.0)

        for ln in sorted(bold_prev, key=lambda l: float(getattr(l, "y0", 0.0) or 0.0), reverse=True):
            if id(ln) in chosen_ids:
                continue
            y = float(getattr(ln, "y0", 0.0) or 0.0)
            if last_y - y > wrap_gap:
                continue
            if abs(float(getattr(ln, "x0", 0.0) or 0.0) - base_x) > 120.0:
                continue
            chosen.append(ln)
            chosen_ids.add(id(ln))
            last_y = y

        chosen.sort(key=lambda l: float(getattr(l, "y0", 0.0) or 0.0))
        return _join_wrapped(chosen)

    # Otherwise: take the nearest human-readable line(s) above, joining wraps.
    bottom = max(col_prev, key=lambda l: float(getattr(l, "y0", 0.0) or 0.0))
    base_x = float(getattr(bottom, "x0", 0.0) or 0.0)
    base_size = float(getattr(bottom, "size", 0.0) or 0.0)

    chosen = [bottom]
    chosen_ids = {id(bottom)}
    last_y = float(getattr(bottom, "y0", 0.0) or 0.0)

    for ln in sorted(col_prev, key=lambda l: float(getattr(l, "y0", 0.0) or 0.0), reverse=True):
        if id(ln) in chosen_ids:
            continue
        y = float(getattr(ln, "y0", 0.0) or 0.0)
        if last_y - y > wrap_gap:
            continue
        if abs(float(getattr(ln, "x0", 0.0) or 0.0) - base_x) > 90.0:
            continue
        if abs(float(getattr(ln, "size", 0.0) or 0.0) - base_size) > 2.2:
            continue
        chosen.append(ln)
        chosen_ids.add(id(ln))
        last_y = y

    chosen.sort(key=lambda l: float(getattr(l, "y0", 0.0) or 0.0))
    return _join_wrapped(chosen)


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
        if code_lines:
            title = _detect_title(lines)
            if title:
                current_form = title

        left_anchor, right_anchor = _page_x_anchors(lines)

        for code_ln in code_lines:
            field = _label_for_code(code_ln, lines, left_anchor, right_anchor)
            if not field:
                continue
            if _is_bracket_metadata_line(field):
                continue
            if _is_field_code_line(field):
                continue

            form_name = current_form or ""
            rec = (page_idx0 + 1, form_name, field)
            if rec in seen:
                continue
            seen.add(rec)
            out.append({"form_name": form_name, "field_name": field, "page": page_idx0 + 1})

    return out
```
