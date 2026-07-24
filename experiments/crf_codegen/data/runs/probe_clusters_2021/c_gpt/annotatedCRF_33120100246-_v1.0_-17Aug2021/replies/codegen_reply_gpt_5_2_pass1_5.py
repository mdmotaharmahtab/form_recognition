```python
import re
from typing import List, Tuple, Dict, Any, Optional


_WS_RE = re.compile(r"\s+")
_BRACKET_FULL_RE = re.compile(r"^\[(.*)\]$")
_CODE_RE = re.compile(r"^[A-Za-z0-9_]{2,}$")
_ROW_ONLY_RE = re.compile(r"^\s*Row\s*\d+\s*$", re.IGNORECASE)


_OPTION_WORDS = {
    "yes",
    "no",
    "unknown",
    "not done",
    "n/a",
    "na",
    "none",
    "other",
    "male",
    "female",
    "true",
    "false",
}


def _norm_text(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def _is_bracketish(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("[") and ("]" in t)


def _is_row_only(line_text: str) -> bool:
    return bool(_ROW_ONLY_RE.match(line_text or ""))


def _page_metrics(lines) -> Tuple[float, float, float]:
    xs0 = [float(getattr(ln, "x0", 0.0)) for ln in lines if getattr(ln, "text", None) is not None]
    xs1 = [float(getattr(ln, "x1", 0.0)) for ln in lines if getattr(ln, "text", None) is not None]
    if not xs0 or not xs1:
        return 0.0, 0.0, 1.0
    left = min(xs0)
    right = max(xs1)
    span = max(1.0, right - left)
    return left, right, span


def _median(vals: List[float]) -> float:
    if not vals:
        return 0.0
    v = sorted(vals)
    n = len(v)
    mid = n // 2
    if n % 2 == 1:
        return float(v[mid])
    return 0.5 * (float(v[mid - 1]) + float(v[mid]))


def _quantile(vals: List[float], q: float) -> float:
    if not vals:
        return 0.0
    v = sorted(vals)
    q = max(0.0, min(1.0, float(q)))
    idx = int(round(q * (len(v) - 1)))
    return float(v[idx])


def _merge_bracket_fragments(lines):
    """
    Merge colored bracket fragments split across lines at same x (e.g. "[SCANNE" + "R]").
    Also merges multi-line bracket payloads (e.g. long "[TYPE: ...]" that wraps) into one.
    """
    merged = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        t = (ln.text or "").strip()
        if getattr(ln, "non_black", False) and t.startswith("[") and not t.endswith("]"):
            parts = [t]
            x0 = float(getattr(ln, "x0", 0.0))
            y0 = float(getattr(ln, "y0", 0.0))
            j = i + 1
            while j < n:
                ln2 = lines[j]
                t2 = (ln2.text or "").strip()
                if not getattr(ln2, "non_black", False):
                    break
                if abs(float(getattr(ln2, "x0", 0.0)) - x0) > 6:
                    break
                if (float(getattr(ln2, "y0", 0.0)) - y0) > 30:
                    break
                parts.append(t2)
                y0 = float(getattr(ln2, "y0", 0.0))
                if t2.endswith("]"):
                    j += 1
                    break
                j += 1
            if len(parts) > 1:
                new_text = _norm_text(" ".join(parts)).replace("[ ", "[").replace(" ]", "]")

                class _L:
                    __slots__ = ("text", "x0", "y0", "x1", "y1", "size", "bold", "non_black")

                nl = _L()
                nl.text = new_text
                nl.x0, nl.y0, nl.x1, nl.y1 = ln.x0, ln.y0, getattr(ln, "x1", ln.x0), getattr(ln, "y1", ln.y0)
                nl.size, nl.bold, nl.non_black = getattr(ln, "size", 0.0), getattr(ln, "bold", False), getattr(ln, "non_black", False)
                merged.append(nl)
                i = j
                continue
        merged.append(ln)
        i += 1
    return merged


def _field_code_from_bracket_line(text: str) -> Optional[str]:
    t = (text or "").strip()
    m = _BRACKET_FULL_RE.match(t)
    if not m:
        return None
    inner = (m.group(1) or "").strip()
    inner_u = inner.upper()

    # Exclude technical annotations (structure landmarks only)
    if ":" in inner:
        return None
    if "TYPE" in inner_u or "VISIBILITY" in inner_u:
        return None
    if "READ-ONLY" in inner_u or "READ ONLY" in inner_u:
        return None

    if not _CODE_RE.match(inner):
        return None
    return inner


def _is_type_annotation_bracket(text: str) -> bool:
    t = (text or "").strip()
    m = _BRACKET_FULL_RE.match(t)
    if not m:
        return False
    inner = (m.group(1) or "").strip()
    inner_u = inner.upper()
    if "TYPE" not in inner_u:
        return False
    return inner_u.lstrip().startswith("TYPE:")


def _is_readonly_or_visibility_bracket(text: str) -> bool:
    t = (text or "").strip()
    m = _BRACKET_FULL_RE.match(t)
    if not m:
        return False
    inner_u = ((m.group(1) or "").strip()).upper()
    if "VISIBILITY" in inner_u:
        return True
    if "READ-ONLY" in inner_u or "READ ONLY" in inner_u:
        return True
    return False


def _has_nearby_readonly_marker(mk, lines, x_slack: float, y_slack: float) -> bool:
    mx = float(getattr(mk, "x0", 0.0))
    my = float(getattr(mk, "y0", 0.0))
    for ln in lines:
        if not getattr(ln, "non_black", False):
            continue
        t = (ln.text or "").strip()
        if not (t.startswith("[") and t.endswith("]")):
            continue
        if not _is_readonly_or_visibility_bracket(t):
            continue
        lx = float(getattr(ln, "x0", 0.0))
        ly = float(getattr(ln, "y0", 0.0))
        if abs(ly - my) <= y_slack and abs(lx - mx) <= x_slack:
            return True
        if 0.0 <= (ly - my) <= (y_slack + 12.0) and abs(lx - mx) <= (x_slack + 25.0):
            return True
    return False


def _wrap_label_block_lines(base, black_sorted, y_stop: float, base_x: float) -> List[Any]:
    block = [base]

    idx = None
    for k in range(len(black_sorted) - 1, -1, -1):
        ln = black_sorted[k]
        if ln is base:
            idx = k
            break
        if abs(float(getattr(ln, "y0", 0.0)) - float(getattr(base, "y0", 0.0))) < 0.2 and abs(float(getattr(ln, "x0", 0.0)) - float(getattr(base, "x0", 0.0))) < 0.2 and (ln.text or "") == (base.text or ""):
            idx = k
            break
    if idx is None:
        idx = 0

    last = base
    k = idx - 1
    while k >= 0:
        ln = black_sorted[k]
        if float(getattr(ln, "y0", 0.0)) >= y_stop:
            k -= 1
            continue
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            k -= 1
            continue
        if (float(getattr(last, "y0", 0.0)) - float(getattr(ln, "y0", 0.0))) > 14.5:
            break
        if abs(float(getattr(ln, "x0", 0.0)) - base_x) > 30:
            break
        block.insert(0, ln)
        last = ln
        k -= 1

    last = base
    k = idx + 1
    while k < len(black_sorted):
        ln = black_sorted[k]
        if float(getattr(ln, "y0", 0.0)) >= y_stop:
            break
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t):
            k += 1
            continue
        if _is_row_only(t):
            break
        if (float(getattr(ln, "y0", 0.0)) - float(getattr(last, "y0", 0.0))) > 14.5:
            break
        if abs(float(getattr(ln, "x0", 0.0)) - base_x) > 30:
            break
        block.append(ln)
        last = ln
        k += 1

    return block


def _block_text(block_lines: List[Any]) -> str:
    return _norm_text(" ".join((ln.text or "").strip() for ln in block_lines))


def _extract_label_same_row_left(marker, black_lines, left: float, span: float, med_size: float) -> Optional[str]:
    y = float(getattr(marker, "y0", 0.0))
    x = float(getattr(marker, "x0", 0.0))

    same = []
    for ln in black_lines:
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        if float(getattr(ln, "x0", 0.0)) >= x - 10:
            continue
        if abs(float(getattr(ln, "y0", 0.0)) - y) > 8.0:
            continue
        same.append(ln)

    if not same:
        return None

    same.sort(
        key=lambda l: (
            abs(x - float(getattr(l, "x1", getattr(l, "x0", 0.0)))),
            abs(y - float(getattr(l, "y0", 0.0))),
            abs(x - float(getattr(l, "x0", 0.0))),
        )
    )
    base = same[0]

    black_sorted = sorted(black_lines, key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))
    block = _wrap_label_block_lines(base, black_sorted, y_stop=y + 9.0, base_x=float(getattr(base, "x0", 0.0)))
    label = _block_text(block) or None
    if not label:
        return None

    # Guard: only reject far-left "section headers" when they look header-like (bold/oversized).
    if x >= (left + 0.55 * span):
        rightmost = max(float(getattr(ln, "x1", getattr(ln, "x0", 0.0))) for ln in block)
        base_x0 = float(getattr(base, "x0", 0.0))
        base_size = float(getattr(base, "size", 0.0))
        base_bold = bool(getattr(base, "bold", False))
        if rightmost < (x - 110.0) and base_x0 <= (left + 0.22 * span):
            if base_bold or (med_size > 0.0 and base_size >= (med_size + 1.3)):
                return None

    return label


def _extract_label_same_row_right(marker, black_lines) -> Optional[str]:
    y = float(getattr(marker, "y0", 0.0))
    x = float(getattr(marker, "x0", 0.0))

    cands = []
    for ln in black_lines:
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        if float(getattr(ln, "x0", 0.0)) <= x + 8:
            continue
        if abs(float(getattr(ln, "y0", 0.0)) - y) > 7.0:
            continue
        cands.append(ln)

    if not cands:
        return None

    def score(ln):
        dx = float(getattr(ln, "x0", 0.0)) - x
        return dx + (8.0 if float(getattr(ln, "x0", 0.0)) > 520 else 0.0)

    base = min(cands, key=score)
    black_sorted = sorted(black_lines, key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))
    block = _wrap_label_block_lines(base, black_sorted, y_stop=y + 14.0, base_x=float(getattr(base, "x0", 0.0)))
    return _block_text(block) or None


def _extract_label_for_left_margin_code(code_line, black_lines, left: float, span: float) -> Optional[str]:
    y = float(getattr(code_line, "y0", 0.0))
    x = float(getattr(code_line, "x0", 0.0))

    cands = []
    for ln in black_lines:
        if float(getattr(ln, "y0", 0.0)) >= y:
            continue
        dy = y - float(getattr(ln, "y0", 0.0))
        if dy > 80:
            continue
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        if abs(float(getattr(ln, "x0", 0.0)) - x) > 16 and float(getattr(ln, "x0", 0.0)) > (left + 0.30 * span):
            continue
        cands.append(ln)

    if not cands:
        return None

    def score(ln):
        dy = y - float(getattr(ln, "y0", 0.0))
        dx = abs(float(getattr(ln, "x0", 0.0)) - x)
        pen = -6.0 if bool(getattr(ln, "bold", False)) else 0.0
        return dy + 0.25 * dx + pen

    base = min(cands, key=score)
    black_sorted = sorted([ln for ln in black_lines if float(getattr(ln, "y0", 0.0)) < y], key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))
    block = _wrap_label_block_lines(base, black_sorted, y_stop=y, base_x=float(getattr(base, "x0", 0.0)))
    return _block_text(block) or None


def _extract_label_for_code(code_line, black_lines, left: float, span: float, med_size: float) -> Optional[str]:
    y = float(getattr(code_line, "y0", 0.0))
    x = float(getattr(code_line, "x0", 0.0))

    cands = []
    for ln in black_lines:
        if float(getattr(ln, "y0", 0.0)) >= y:
            continue
        dy = y - float(getattr(ln, "y0", 0.0))
        if dy > 170:
            continue
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t):
            continue
        if float(getattr(ln, "x0", 0.0)) > 420 and abs(float(getattr(ln, "x0", 0.0)) - x) > 90:
            continue
        if t.endswith(":"):
            continue
        cands.append(ln)

    if not cands:
        return None

    def score(ln):
        dy = y - float(getattr(ln, "y0", 0.0))
        dx = abs(float(getattr(ln, "x0", 0.0)) - x)
        pen = 0.0

        if x >= (left + 0.55 * span):
            lx0 = float(getattr(ln, "x0", 0.0))
            lx1 = float(getattr(ln, "x1", getattr(ln, "x0", 0.0)))
            if lx0 <= (left + 0.20 * span) and lx1 < (x - 80.0):
                if bool(getattr(ln, "bold", False)) or (med_size > 0.0 and float(getattr(ln, "size", 0.0)) >= (med_size + 1.3)):
                    pen += 140.0
                else:
                    pen += 60.0

        if x < 140:
            if float(getattr(ln, "x0", 0.0)) > 260:
                pen += 250.0
        else:
            if float(getattr(ln, "x0", 0.0)) < 200 and dx > 120:
                pen += 55.0

        if _is_row_only((ln.text or "").strip()):
            pen += 150.0
        if bool(getattr(ln, "bold", False)) and dy <= 75:
            pen -= 18.0

        return dy + 0.33 * dx + pen

    base = min(cands, key=score)
    black_sorted = sorted([ln for ln in black_lines if float(getattr(ln, "y0", 0.0)) < y], key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))
    block = _wrap_label_block_lines(base, black_sorted, y_stop=y, base_x=float(getattr(base, "x0", 0.0)))

    if x >= (left + 0.55 * span):
        rightmost = max(float(getattr(ln, "x1", getattr(ln, "x0", 0.0))) for ln in block)
        base_x0 = float(getattr(base, "x0", 0.0))
        base_size = float(getattr(base, "size", 0.0))
        base_bold = bool(getattr(base, "bold", False))
        if rightmost < (x - 110.0) and base_x0 <= (left + 0.22 * span):
            if base_bold or (med_size > 0.0 and base_size >= (med_size + 1.3)):
                return None

    return _block_text(block) or None


def _detect_row_headers(black_lines):
    rows = []
    for ln in black_lines:
        if not bool(getattr(ln, "bold", False)):
            continue
        if float(getattr(ln, "x0", 0.0)) > 180:
            continue
        t = (ln.text or "").strip()
        if _is_row_only(t):
            rows.append(ln)
    rows.sort(key=lambda l: float(getattr(l, "y0", 0.0)))
    return rows


def _nearest_row_context(black_lines, y0: float, max_dy: float = 95.0) -> Optional[str]:
    best = None
    best_dy = 1e9
    for ln in black_lines:
        if not bool(getattr(ln, "bold", False)):
            continue
        if float(getattr(ln, "x0", 0.0)) > 170:
            continue
        t = (ln.text or "").strip()
        if not _is_row_only(t):
            continue
        dy = y0 - float(getattr(ln, "y0", 0.0))
        if 0 < dy <= max_dy and dy < best_dy:
            best = _norm_text(t)
            best_dy = dy
    return best


def _extract_table_column_header(marker, black_lines, table_top_y: float, left: float, span: float, med_size: float) -> Optional[str]:
    my = float(getattr(marker, "y0", 0.0))
    mx0 = float(getattr(marker, "x0", 0.0))
    mx1 = float(getattr(marker, "x1", mx0))
    mx = 0.5 * (mx0 + mx1)

    band_top = max(0.0, table_top_y - 200.0)
    band_bot = table_top_y - 4.0

    header_lines = []
    for ln in black_lines:
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        y0 = float(getattr(ln, "y0", 0.0))
        if not (band_top <= y0 < band_bot):
            continue
        if float(getattr(ln, "x0", 0.0)) > 560:
            continue
        if t.endswith(":"):
            continue
        header_lines.append(ln)

    if not header_lines:
        return None

    def xdist_to_span(ln):
        lx0 = float(getattr(ln, "x0", 0.0)) - 8.0
        lx1 = float(getattr(ln, "x1", getattr(ln, "x0", 0.0))) + 8.0
        if lx0 <= mx <= lx1:
            return 0.0
        if mx < lx0:
            return lx0 - mx
        return mx - lx1

    def score(ln):
        dx = xdist_to_span(ln)
        dy = abs((table_top_y - 12.0) - float(getattr(ln, "y0", 0.0)))
        pen = 0.0

        if med_size > 0.0 and float(getattr(ln, "size", 0.0)) < (med_size - 0.7):
            pen += 18.0
        if bool(getattr(ln, "bold", False)):
            pen -= 10.0

        if float(getattr(ln, "x0", 0.0)) < (left + 0.18 * span) and mx0 > (left + 0.30 * span):
            pen += 30.0

        return 0.70 * dx + 0.80 * dy + pen

    base = min(header_lines, key=score)

    black_sorted = sorted(black_lines, key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))
    block = _wrap_label_block_lines(base, black_sorted, y_stop=band_bot + 1.0, base_x=float(getattr(base, "x0", 0.0)))
    label = _block_text(block)

    if float(getattr(base, "y0", 0.0)) >= (table_top_y - 2.0):
        return None

    return label or None


def _extract_label_near_type_marker(type_line, text_lines, left: float, span: float, med_size: float) -> Optional[str]:
    # Left-margin technical marker: prefer a label immediately to the right or just below.
    y = float(getattr(type_line, "y0", 0.0))
    x = float(getattr(type_line, "x0", 0.0))

    # Same-line right is common.
    label = _extract_label_same_row_right(type_line, [ln for ln in text_lines if not _is_bracketish((ln.text or "").strip())])
    if label:
        return label

    # Window around marker: favor near-right and near-below candidates.
    cands = []
    for ln in text_lines:
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        ly = float(getattr(ln, "y0", 0.0))
        lx0 = float(getattr(ln, "x0", 0.0))
        if ly < (y - 8.0) or ly > (y + 120.0):
            continue
        if lx0 <= x + 10.0:
            continue
        if lx0 > (left + 0.90 * span):
            continue
        if t.endswith(":"):
            continue
        cands.append(ln)

    if not cands:
        # Fallback: look above (some templates put label then type marker below it).
        above = []
        for ln in text_lines:
            t = (ln.text or "").strip()
            if not t or _is_bracketish(t) or _is_row_only(t):
                continue
            ly = float(getattr(ln, "y0", 0.0))
            if ly >= y:
                continue
            dy = y - ly
            if dy > 120.0:
                continue
            lx0 = float(getattr(ln, "x0", 0.0))
            if abs(lx0 - x) > 60.0 and lx0 > (left + 0.35 * span):
                continue
            if t.endswith(":"):
                continue
            above.append(ln)
        if not above:
            return None

        def score_a(ln):
            dy = y - float(getattr(ln, "y0", 0.0))
            dx = abs(float(getattr(ln, "x0", 0.0)) - x)
            pen = -10.0 if bool(getattr(ln, "bold", False)) else 0.0
            if med_size > 0.0 and float(getattr(ln, "size", 0.0)) >= (med_size + 1.0):
                pen -= 6.0
            return dy + 0.35 * dx + pen

        base = min(above, key=score_a)
        sorted_lines = sorted([ln for ln in text_lines if float(getattr(ln, "y0", 0.0)) < y], key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))
        block = _wrap_label_block_lines(base, sorted_lines, y_stop=y, base_x=float(getattr(base, "x0", 0.0)))
        return _block_text(block) or None

    def score(ln):
        ly = float(getattr(ln, "y0", 0.0))
        lx0 = float(getattr(ln, "x0", 0.0))
        dy = max(0.0, ly - y)
        dx = max(0.0, lx0 - x)
        pen = 0.0
        if bool(getattr(ln, "bold", False)):
            pen -= 10.0
        if med_size > 0.0 and float(getattr(ln, "size", 0.0)) >= (med_size + 1.0):
            pen -= 6.0
        # Discourage far-right values for left-margin markers.
        if lx0 >= (left + 0.70 * span):
            pen += 35.0
        return 0.90 * dy + 0.35 * dx + pen

    base = min(cands, key=score)
    sorted_lines = sorted([ln for ln in text_lines if float(getattr(ln, "y0", 0.0)) <= (y + 140.0)], key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))
    block = _wrap_label_block_lines(base, sorted_lines, y_stop=y + 140.0, base_x=float(getattr(base, "x0", 0.0)))
    return _block_text(block) or None


def _pick_form_title(lines, has_fields: bool, current_form: str, left: float, span: float, med_size: float, min_marker_y: float) -> Optional[str]:
    # Only attempt to update title on pages where we will try to extract fields.
    if not has_fields:
        return None

    top_band_y = min(175.0, max(90.0, min_marker_y - 18.0))
    top = [ln for ln in lines if float(getattr(ln, "y0", 0.0)) <= top_band_y and not _is_bracketish(ln.text)]
    if not top:
        return None

    # Filter out TOC-like list items: prefer "header-like" (non-black or bold/oversized) and not too far right.
    cands = []
    for ln in top:
        txt = (ln.text or "").strip()
        if len(txt) < 2:
            continue
        if txt.endswith(":"):
            continue
        if _is_row_only(txt):
            continue
        x0 = float(getattr(ln, "x0", 0.0))
        if x0 > (left + 0.70 * span):
            continue

        size = float(getattr(ln, "size", 0.0))
        bold = bool(getattr(ln, "bold", False))
        non_black = bool(getattr(ln, "non_black", False))

        headerish = non_black or bold or (med_size > 0.0 and size >= (med_size + 1.0))
        if not headerish:
            continue

        # Avoid "question-as-title" churn when we already have a form.
        if txt.endswith("?") and current_form:
            continue

        # Avoid adopting a single field label as title when it sits in the value area.
        if x0 >= (left + 0.34 * span) and float(getattr(ln, "y0", 0.0)) >= 60.0:
            continue

        cands.append(ln)

    if not cands:
        return None

    # Prefer the most prominent (size), then colored/bold, then upper/left.
    def score(ln):
        size = float(getattr(ln, "size", 0.0))
        non_black = 1 if bool(getattr(ln, "non_black", False)) else 0
        bold = 1 if bool(getattr(ln, "bold", False)) else 0
        y0 = float(getattr(ln, "y0", 0.0))
        x0 = float(getattr(ln, "x0", 0.0))
        # higher size better => negative
        return (-size, -(non_black + bold), y0, 0 if x0 <= (left + 0.40 * span) else 1, x0)

    cands.sort(key=score)
    base = cands[0]

    # Merge immediate next line if it's clearly a wrapped title line (same indent, close y, same style-ish).
    parts = [(_norm_text((base.text or "").strip()), base)]
    bx0 = float(getattr(base, "x0", 0.0))
    by0 = float(getattr(base, "y0", 0.0))
    bsz = float(getattr(base, "size", 0.0))
    bnb = bool(getattr(base, "non_black", False))
    bbd = bool(getattr(base, "bold", False))

    for ln in cands[1:]:
        ly0 = float(getattr(ln, "y0", 0.0))
        if ly0 <= by0:
            continue
        if (ly0 - by0) > 18.0:
            break
        lx0 = float(getattr(ln, "x0", 0.0))
        if abs(lx0 - bx0) > 26.0:
            continue
        if abs(float(getattr(ln, "size", 0.0)) - bsz) > 1.2:
            continue
        if bool(getattr(ln, "non_black", False)) != bnb and not (bnb or bool(getattr(ln, "non_black", False))):
            continue
        if bool(getattr(ln, "bold", False)) != bbd and not (bbd or bool(getattr(ln, "bold", False))):
            continue
        t = _norm_text((ln.text or "").strip())
        if not t or t.endswith(":"):
            continue
        parts.append((t, ln))
        break

    title = _norm_text(" ".join(p for p, _ in parts))
    if not title:
        return None
    return title


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        lines2 = _merge_bracket_fragments(lines)
        left, right, span = _page_metrics(lines2)

        black_lines = [ln for ln in lines2 if (not getattr(ln, "non_black", False)) and (ln.text or "").strip()]
        # For type-only layouts, labels can sometimes be colored; keep a broader pool for those cases.
        text_lines_any = [ln for ln in lines2 if (ln.text or "").strip() and not _is_bracketish((ln.text or "").strip())]

        black_sizes = [
            float(getattr(ln, "size", 0.0))
            for ln in black_lines
            if (ln.text or "").strip() and not _is_bracketish((ln.text or "").strip())
        ]
        med_size = _median(black_sizes) if black_sizes else 0.0

        row_headers = _detect_row_headers(black_lines)
        first_row_y = float(getattr(row_headers[0], "y0", 0.0)) if row_headers else None

        # Primary layout: bracket codes
        code_candidates = []
        for ln in lines2:
            t = (ln.text or "").strip()
            if not (t.startswith("[") and t.endswith("]")):
                continue
            code = _field_code_from_bracket_line(t)
            if not code:
                continue
            code_candidates.append(ln)

        code_xs = [float(getattr(ln, "x0", 0.0)) for ln in code_candidates]
        med_code_x = _median(code_xs) if code_xs else 0.0
        left_code_layout = bool(code_candidates) and (med_code_x <= (left + 0.30 * span))
        right_code_layout = bool(code_candidates) and (med_code_x >= (left + 0.48 * span))

        code_lines = []
        if code_candidates:
            if right_code_layout:
                x_thr = left + 0.33 * span
                for ln in code_candidates:
                    if float(getattr(ln, "x0", 0.0)) >= x_thr:
                        code_lines.append(ln)
                if not code_lines:
                    code_lines = code_candidates[:]
            else:
                code_lines = code_candidates[:]

        # Fallback layout: TYPE brackets (technical markers) when no item code brackets appear.
        type_lines = []
        if not code_lines:
            for ln in lines2:
                if not getattr(ln, "non_black", False):
                    continue
                t = (ln.text or "").strip()
                if not (t.startswith("[") and t.endswith("]")):
                    continue
                if _is_type_annotation_bracket(t):
                    type_lines.append(ln)

        field_markers = code_lines if code_lines else type_lines
        has_fields = bool(field_markers)
        if not has_fields:
            # Critical: do not update current_form on pages with no fields (prevents TOC/instructions from poisoning later pages).
            continue

        field_markers = sorted(field_markers, key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))
        min_marker_y = float(getattr(field_markers[0], "y0", 0.0)) if field_markers else 9999.0

        title = _pick_form_title(
            lines2,
            has_fields=has_fields,
            current_form=current_form,
            left=left,
            span=span,
            med_size=med_size,
            min_marker_y=min_marker_y,
        )
        if title:
            current_form = title

        # Readonly/visibility filtering:
        # - reliable when codes live in mid/right columns
        # - avoid applying to far-left technical stacks (left_code_layout)
        apply_readonly_filter = bool(code_lines) and (not left_code_layout)

        # Table structural discriminator: on Row N tables, drop obvious non-entry columns (left-most schedule/display columns)
        # without using literal word blocklists.
        table_body_markers = []
        if row_headers and first_row_y is not None:
            for mk in field_markers:
                if float(getattr(mk, "y0", 0.0)) >= (first_row_y - 6.0):
                    table_body_markers.append(mk)

        body_xs = [float(getattr(mk, "x0", 0.0)) for mk in table_body_markers] if table_body_markers else []
        # Estimate a boundary between "left display columns" and "entry columns" only when there are many distinct columns.
        body_xs_rounded = sorted({round(x / 6.0) * 6.0 for x in body_xs})
        entry_col_x_min = None
        if len(body_xs_rounded) >= 4:
            entry_col_x_min = _quantile(body_xs, 0.45)

        # Skip markers that live in the header band of a Row table (column labels etc.), not data-entry cells.
        def _marker_is_in_table_header(mk) -> bool:
            if not (row_headers and first_row_y is not None):
                return False
            y0 = float(getattr(mk, "y0", 0.0))
            return y0 < (first_row_y - 8.0)

        for mk in field_markers:
            if _marker_is_in_table_header(mk):
                continue

            if apply_readonly_filter:
                mk_x0 = float(getattr(mk, "x0", 0.0))
                # Only attempt filter away from far-left margin (avoid left technical stacks).
                if mk_x0 >= (left + 0.28 * span):
                    if _has_nearby_readonly_marker(mk, lines2, x_slack=120.0, y_slack=22.0):
                        continue

            label: Optional[str] = None
            label_source = ""

            if code_lines:
                mk_x0 = float(getattr(mk, "x0", 0.0))

                # Left-margin code layout
                if left_code_layout and mk_x0 <= (left + 0.24 * span):
                    label = _extract_label_for_left_margin_code(mk, black_lines, left=left, span=span)
                    label_source = "left_margin"

                if not label:
                    # Prefer same-row left label in tables (prevents grabbing nearby instruction bands above)
                    label = _extract_label_same_row_left(mk, black_lines, left=left, span=span, med_size=med_size)
                    if label:
                        label_source = "same_row_left"

                if not label and row_headers and first_row_y is not None and float(getattr(mk, "y0", 0.0)) >= (first_row_y - 6.0):
                    # Row tables: try column header above table
                    hdr = _extract_table_column_header(mk, black_lines, table_top_y=float(first_row_y), left=left, span=span, med_size=med_size)
                    if hdr:
                        # Structural drop: left-most columns in multi-column row tables are often non-entry schedule/display.
                        if entry_col_x_min is not None and float(getattr(mk, "x0", 0.0)) < float(entry_col_x_min):
                            continue
                        label = hdr
                        label_source = "table_header"

                if not label:
                    label = _extract_label_for_code(mk, black_lines, left=left, span=span, med_size=med_size)
                    if label:
                        label_source = "above"

                if not label:
                    # Rare: code marker at left of a label on same line
                    label = _extract_label_same_row_right(mk, black_lines)
                    if label:
                        label_source = "same_row_right"
            else:
                # TYPE-only fallback: allow labels from broader text pool (some templates color the question text)
                label = _extract_label_near_type_marker(mk, text_lines_any, left=left, span=span, med_size=med_size)
                label_source = "type_near"

            if not label:
                continue

            field_name = _norm_text(label)
            if not field_name:
                continue
            if _is_bracketish(field_name) or _is_row_only(field_name):
                continue

            # Avoid lifting pure answer tokens from right-side value columns.
            if field_name.strip().lower() in _OPTION_WORDS and float(getattr(mk, "x0", 0.0)) >= left + 0.45 * span:
                continue

            # Add row context for dense/repeatable tables so repeated rows don't collapse semantically.
            row_ctx = None
            if row_headers and first_row_y is not None and float(getattr(mk, "y0", 0.0)) >= (first_row_y - 6.0):
                row_ctx = _nearest_row_context(black_lines, float(getattr(mk, "y0", 0.0)), max_dy=130.0)
            elif float(getattr(mk, "y0", 0.0)) >= 260 and float(getattr(mk, "x0", 0.0)) >= (left + 0.22 * span):
                row_ctx = _nearest_row_context(black_lines, float(getattr(mk, "y0", 0.0)), max_dy=115.0)

            if row_ctx and row_ctx.lower() not in field_name.lower():
                field_name = _norm_text(f"{row_ctx} - {field_name}")

            out.append(
                {
                    "form_name": current_form or "",
                    "field_name": field_name,
                    "page": int(page_idx0) + 1,
                }
            )

    return out
```
