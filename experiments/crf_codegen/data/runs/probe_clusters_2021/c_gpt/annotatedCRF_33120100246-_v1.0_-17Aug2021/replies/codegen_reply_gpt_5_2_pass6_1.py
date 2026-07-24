```python
# Observed layouts: (a) TOC/schedule pages with blue link-like rows and no red annotations,
# (b) annotated eCRF pages where each data-entry field has a red bracketed code line like [ABC123],
#     followed by red [TYPE: ...] / [VISIBILITY: ...] metadata, and (c) multi-line wrapped labels.
# Strategy: use red bracketed code lines as reliable anchors for fields; attach the nearest label text
# above each code (preferring bold labels when present) and carry forward a prominent top title as form_name.

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
    # Accept only machine-like bracket codes, not metadata blocks like [TYPE: ...]
    # (those contain spaces/colon and won't match).
    return bool(_CODE_RE.match(text.strip()))


def _is_row_header(text: str) -> bool:
    return bool(_ROW_RE.match(text.strip()))


def _join_wrapped(lines: List[Any]) -> str:
    parts = []
    for ln in lines:
        t = _norm(ln.text)
        if not t:
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
        t = ln.text.strip()
        if not t:
            continue
        if _is_field_code_line(t):
            continue
        if t.startswith("[") and t.endswith("]") and not _has_letter(t):
            continue
        if not _has_letter(t):
            continue
        # Avoid tiny headers/footers by size
        if ln.size < 6.5:
            continue
        xs.append(float(ln.x0))
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
    cands = []
    for ln in lines:
        t = _norm(ln.text)
        if not t or not _has_letter(t):
            continue
        if _is_field_code_line(t):
            continue
        if ln.y0 > 125:
            continue
        # Title tends to be larger or colored; allow bold too.
        if ln.size >= 11.0 or ln.non_black or ln.bold:
            cands.append(ln)
    if not cands:
        return ""

    max_size = max(float(l.size) for l in cands)
    # Prefer the largest lines, then earliest, then left-ish.
    best = None
    best_key = None
    for ln in cands:
        # Strong preference to close-to-max size
        size_ok = float(ln.size) >= (max_size - 0.6)
        if not size_ok:
            continue
        # Avoid picking multi-row schedule link text (often many similar lines)
        # by preferring very top-most prominent header and left region.
        key = (float(ln.y0), float(ln.x0), -float(ln.size), 0 if ln.non_black else 1, 0 if ln.bold else 1)
        if best is None or key < best_key:
            best = ln
            best_key = key

    if best is None:
        # fallback: absolute best among candidates
        best = min(
            cands,
            key=lambda l: (-(float(l.size)), float(l.y0), float(l.x0), 0 if l.non_black else 1, 0 if l.bold else 1),
        )
    title = _norm(best.text)
    return title


def _label_for_code(code_ln: Any, lines: List[Any], left_anchor: float, right_anchor: float) -> str:
    y_code = float(code_ln.y0)

    # Collect nearby lines above the code.
    window_top = y_code - 160.0
    window_bottom = y_code - 1.0
    prev = []
    for ln in lines:
        y = float(ln.y0)
        if y < window_top or y > window_bottom:
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _is_field_code_line(t):
            continue
        # Exclude other bracket metadata blocks (usually non-human labels)
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
    # If there are bold lines close by, let them drive the column choice.
    mid_pref = float(code_ln.x0)
    target_anchor = left_anchor if abs(mid_pref - left_anchor) <= abs(mid_pref - right_anchor) else right_anchor

    # Filter to the nearest plausible column, but allow indents.
    col_prev = [ln for ln in prev if abs(float(ln.x0) - target_anchor) <= 210.0]
    if not col_prev:
        # If code is far left (codes printed in left margin), labels still likely in left column.
        col_prev = [ln for ln in prev if abs(float(ln.x0) - left_anchor) <= 260.0] or prev

    # Prefer bold label blocks when present reasonably near the code.
    bold_prev = [ln for ln in col_prev if ln.bold and (y_code - float(ln.y0)) <= 120.0]
    if bold_prev:
        bottom = max(bold_prev, key=lambda l: float(l.y0))
        base_x = float(bottom.x0)
        chosen = [bottom]
        last_y = float(bottom.y0)

        # Walk upward, collecting wrapped bold lines.
        for ln in sorted(bold_prev, key=lambda l: float(l.y0), reverse=True):
            if ln is bottom:
                continue
            y = float(ln.y0)
            if last_y - y > 22.0:
                continue
            if abs(float(ln.x0) - base_x) > 120.0:
                continue
            chosen.append(ln)
            last_y = y

        chosen = sorted(set(chosen), key=lambda l: float(l.y0))
        return _join_wrapped(chosen)

    # Otherwise: take the nearest human-readable line(s) above, joining wraps.
    bottom = max(col_prev, key=lambda l: float(l.y0))
    base_x = float(bottom.x0)
    base_size = float(bottom.size)

    chosen = [bottom]
    last_y = float(bottom.y0)

    # Collect preceding wrapped lines: similar x, similar size, small vertical gaps.
    for ln in sorted(col_prev, key=lambda l: float(l.y0), reverse=True):
        if ln is bottom:
            continue
        y = float(ln.y0)
        if last_y - y > 22.0:
            continue
        if abs(float(ln.x0) - base_x) > 90.0:
            continue
        if abs(float(ln.size) - base_size) > 2.2:
            continue
        chosen.append(ln)
        last_y = y

    chosen = sorted(set(chosen), key=lambda l: float(l.y0))
    return _join_wrapped(chosen)


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()

    current_form = ""
    for page_idx0, lines in pages:
        # Identify field code anchors first.
        code_lines = []
        for ln in lines:
            t = ln.text.strip()
            if _is_field_code_line(t):
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

            form_name = current_form or ""
            rec = (page_idx0 + 1, form_name, field)
            if rec in seen:
                continue
            seen.add(rec)
            out.append({"form_name": form_name, "field_name": field, "page": page_idx0 + 1})

    return out
```
