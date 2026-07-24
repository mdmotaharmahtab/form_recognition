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
        if ln.non_black and t.startswith("[") and not t.endswith("]"):
            parts = [t]
            x0 = ln.x0
            y0 = ln.y0
            j = i + 1
            while j < n:
                ln2 = lines[j]
                t2 = (ln2.text or "").strip()
                if not ln2.non_black:
                    break
                if abs(ln2.x0 - x0) > 6:
                    break
                if (ln2.y0 - y0) > 30:
                    break
                parts.append(t2)
                y0 = ln2.y0
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
                nl.x0, nl.y0, nl.x1, nl.y1 = ln.x0, ln.y0, ln.x1, ln.y1
                nl.size, nl.bold, nl.non_black = ln.size, ln.bold, ln.non_black
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
    if inner_u.startswith("TYPE:") or "[TYPE:" in ("[" + inner_u):
        return True
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
    # Some templates print VISIBILITY/READ-ONLY near non-editable display cells.
    mx = float(mk.x0)
    my = float(mk.y0)
    for ln in lines:
        if not getattr(ln, "non_black", False):
            continue
        t = (ln.text or "").strip()
        if not (t.startswith("[") and t.endswith("]")):
            continue
        if not _is_readonly_or_visibility_bracket(t):
            continue
        if abs(float(ln.y0) - my) <= y_slack and abs(float(ln.x0) - mx) <= x_slack:
            return True
        # tolerate a wrapped readonly marker slightly below
        if 0.0 <= (float(ln.y0) - my) <= (y_slack + 12.0) and abs(float(ln.x0) - mx) <= (x_slack + 25.0):
            return True
    return False


def _pick_form_title(lines, has_fields: bool, current_form: str) -> Optional[str]:
    # Prefer a prominent top-band title (often colored + larger).
    top = [ln for ln in lines if ln.y0 <= 175 and not _is_bracketish(ln.text)]
    if not top:
        return None

    max_size_top = max((ln.size for ln in top), default=0.0)
    if max_size_top < 10.6:
        return None

    cands = []
    for ln in top:
        txt = (ln.text or "").strip()
        if len(txt) < 2:
            continue
        if ln.size < (max_size_top - 1.2):
            continue
        if ln.x0 > 560:
            continue
        if ln.non_black or ln.bold or ln.size >= (max_size_top - 0.2):
            cands.append(ln)

    if not cands:
        return None

    if not has_fields and current_form:
        return None

    cands.sort(key=lambda l: (l.y0, (0 if l.x0 <= 320 else 1), l.x0))
    title = _norm_text(cands[0].text)

    if title.endswith("?") and current_form:
        return None
    return title


def _nearest_row_context(black_lines, y0: float, max_dy: float = 95.0) -> Optional[str]:
    best = None
    best_dy = 1e9
    for ln in black_lines:
        if not ln.bold:
            continue
        if ln.x0 > 170:
            continue
        t = (ln.text or "").strip()
        if not _is_row_only(t):
            continue
        dy = y0 - ln.y0
        if 0 < dy <= max_dy and dy < best_dy:
            best = _norm_text(t)
            best_dy = dy
    return best


def _wrap_label_block_lines(base, black_sorted, y_stop: float, base_x: float) -> List[Any]:
    # Build a wrapped label block around the base line by proximity/indent.
    block = [base]

    idx = None
    for k in range(len(black_sorted) - 1, -1, -1):
        ln = black_sorted[k]
        if ln is base:
            idx = k
            break
        if abs(ln.y0 - base.y0) < 0.2 and abs(ln.x0 - base.x0) < 0.2 and (ln.text or "") == (base.text or ""):
            idx = k
            break
    if idx is None:
        idx = 0

    last = base
    k = idx - 1
    while k >= 0:
        ln = black_sorted[k]
        if ln.y0 >= y_stop:
            k -= 1
            continue
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            k -= 1
            continue
        if (last.y0 - ln.y0) > 14.5:
            break
        if abs(ln.x0 - base_x) > 30:
            break
        block.insert(0, ln)
        last = ln
        k -= 1

    last = base
    k = idx + 1
    while k < len(black_sorted):
        ln = black_sorted[k]
        if ln.y0 >= y_stop:
            break
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t):
            k += 1
            continue
        if _is_row_only(t):
            break
        if (ln.y0 - last.y0) > 14.5:
            break
        if abs(ln.x0 - base_x) > 30:
            break
        block.append(ln)
        last = ln
        k += 1

    return block


def _block_text(block_lines: List[Any]) -> str:
    return _norm_text(" ".join((ln.text or "").strip() for ln in block_lines))


def _extract_label_same_row_left(marker, black_lines, left: float, span: float) -> Optional[str]:
    # Prefer the label on the same row to the left of the marker (common in tables).
    y = float(marker.y0)
    x = float(marker.x0)
    x_left_limit = left + 0.12 * span

    same = []
    for ln in black_lines:
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        if ln.x0 >= x - 10:
            continue
        # slightly wider slack: some PDFs baseline-shift rows in tables
        if abs(float(ln.y0) - y) > 8.0:
            continue
        if ln.x0 < x_left_limit and (x - ln.x0) > 420:
            continue
        same.append(ln)

    if not same:
        return None

    same.sort(key=lambda l: (abs(x - float(getattr(l, "x1", l.x0))), abs(y - float(l.y0)), abs(x - float(l.x0))))
    base = same[0]

    black_sorted = sorted(black_lines, key=lambda l: (l.y0, l.x0))
    block = _wrap_label_block_lines(base, black_sorted, y_stop=y + 9.0, base_x=base.x0)

    # Structural guard: avoid choosing far-left section headers that don't reach the value column.
    if x >= (left + 0.55 * span):
        rightmost = max(float(getattr(ln, "x1", ln.x0)) for ln in block)
        if rightmost < (x - 110.0) and float(base.x0) <= (left + 0.22 * span):
            return None

    return _block_text(block) or None


def _extract_label_same_line_right(marker, black_lines) -> Optional[str]:
    # For left-margin technical markers, the human label is often on the same line to the right.
    y = float(marker.y0)
    x = float(marker.x0)

    cands = []
    for ln in black_lines:
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        if float(ln.x0) <= x + 8:
            continue
        if abs(float(ln.y0) - y) > 7.0:
            continue
        cands.append(ln)

    if not cands:
        return None

    def score(ln):
        dx = float(ln.x0) - x
        return dx + (8.0 if ln.x0 > 520 else 0.0)

    base = min(cands, key=score)
    black_sorted = sorted(black_lines, key=lambda l: (l.y0, l.x0))
    block = _wrap_label_block_lines(base, black_sorted, y_stop=y + 14.0, base_x=base.x0)
    return _block_text(block) or None


def _extract_label_for_left_margin_code(code_line, black_lines, left: float, span: float) -> Optional[str]:
    # Layout: code printed at far-left margin, label immediately above (often the question line).
    y = float(code_line.y0)
    x = float(code_line.x0)

    cands = []
    for ln in black_lines:
        if float(ln.y0) >= y:
            continue
        dy = y - float(ln.y0)
        if dy > 80:
            continue
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        # Prefer same indent as code area.
        if abs(float(ln.x0) - x) > 16 and float(ln.x0) > (left + 0.30 * span):
            continue
        cands.append(ln)

    if not cands:
        return None

    def score(ln):
        dy = y - float(ln.y0)
        dx = abs(float(ln.x0) - x)
        pen = 0.0
        if ln.bold:
            pen -= 6.0
        return dy + 0.25 * dx + pen

    base = min(cands, key=score)
    black_sorted = sorted([ln for ln in black_lines if float(ln.y0) < y], key=lambda l: (l.y0, l.x0))
    block = _wrap_label_block_lines(base, black_sorted, y_stop=y, base_x=base.x0)
    return _block_text(block) or None


def _extract_label_for_code(code_line, black_lines, left: float, span: float) -> Optional[str]:
    y = float(code_line.y0)
    x = float(code_line.x0)

    cands = []
    for ln in black_lines:
        if float(ln.y0) >= y:
            continue
        dy = y - float(ln.y0)
        if dy > 170:
            continue
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t):
            continue
        if float(ln.x0) > 420 and abs(float(ln.x0) - x) > 90:
            continue
        cands.append(ln)

    if not cands:
        return None

    def score(ln):
        dy = y - float(ln.y0)
        dx = abs(float(ln.x0) - x)
        pen = 0.0

        # Avoid selecting far-left section headers when the code lives in a far-right value column.
        if x >= (left + 0.55 * span):
            lx0 = float(ln.x0)
            lx1 = float(getattr(ln, "x1", ln.x0))
            if lx0 <= (left + 0.20 * span) and lx1 < (x - 80.0):
                pen += 140.0

        if x < 140:
            if float(ln.x0) > 260:
                pen += 250.0
        else:
            if float(ln.x0) < 200 and dx > 120:
                pen += 55.0

        if _is_row_only((ln.text or "").strip()):
            pen += 150.0
        if ln.bold and dy <= 75:
            pen -= 18.0

        return dy + 0.33 * dx + pen

    base = min(cands, key=score)
    black_sorted = sorted([ln for ln in black_lines if float(ln.y0) < y], key=lambda l: (l.y0, l.x0))
    block = _wrap_label_block_lines(base, black_sorted, y_stop=y, base_x=base.x0)

    # Structural guard: ensure the chosen block "reaches" toward the code column for right-column codes.
    if x >= (left + 0.55 * span):
        rightmost = max(float(getattr(ln, "x1", ln.x0)) for ln in block)
        if rightmost < (x - 110.0) and float(base.x0) <= (left + 0.22 * span):
            return None

    return _block_text(block) or None


def _extract_label_near_type_marker(type_line, black_lines, left: float, span: float) -> Optional[str]:
    label = _extract_label_same_line_right(type_line, black_lines)
    if label:
        return label

    label = _extract_label_for_code(type_line, black_lines, left=left, span=span)
    if label:
        return label

    y = float(type_line.y0)
    x = float(type_line.x0)

    cands = []
    for ln in black_lines:
        if float(ln.y0) <= y:
            continue
        dy = float(ln.y0) - y
        if dy > 185:
            continue
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        if float(ln.x0) > 420 and abs(float(ln.x0) - x) > 90:
            continue
        if float(ln.x0) >= 260:
            tu = _norm_text(t).lower()
            if tu in _OPTION_WORDS and dy <= 100:
                continue
        cands.append(ln)

    if not cands:
        return None

    def score(ln):
        dy = float(ln.y0) - y
        dx = abs(float(ln.x0) - x)
        pen = 0.0
        if ln.bold:
            pen -= 10.0
        if float(ln.x0) >= 260:
            pen += 18.0
        return dy + 0.30 * dx + pen

    base = min(cands, key=score)
    black_sorted = sorted([ln for ln in black_lines if float(ln.y0) < (y + 220)], key=lambda l: (l.y0, l.x0))
    block = _wrap_label_block_lines(base, black_sorted, y_stop=y + 220, base_x=base.x0)
    return _block_text(block) or None


def _detect_row_headers(black_lines):
    rows = []
    for ln in black_lines:
        if not ln.bold:
            continue
        if float(ln.x0) > 180:
            continue
        t = (ln.text or "").strip()
        if _is_row_only(t):
            rows.append(ln)
    rows.sort(key=lambda l: float(l.y0))
    return rows


def _extract_table_column_header(marker, black_lines, table_top_y: float, left: float, span: float) -> Optional[str]:
    # In "Row N" repeating tables, prefer a column header above the table body.
    my = float(marker.y0)
    mx0 = float(marker.x0)
    mx1 = float(getattr(marker, "x1", marker.x0))
    mx = 0.5 * (mx0 + mx1)

    # Header band: above the table top, but not too high (avoid page title).
    band_top = max(0.0, table_top_y - 200.0)
    band_bot = table_top_y - 4.0

    header_lines = []
    for ln in black_lines:
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        y0 = float(ln.y0)
        if not (band_top <= y0 < band_bot):
            continue
        if float(ln.x0) > 560:
            continue
        header_lines.append(ln)

    if not header_lines:
        return None

    black_sizes = [float(getattr(ln, "size", 0.0)) for ln in black_lines if (ln.text or "").strip() and not _is_bracketish(ln.text)]
    med_size = _median(black_sizes) if black_sizes else 0.0

    def xdist_to_span(ln):
        lx0 = float(ln.x0) - 8.0
        lx1 = float(getattr(ln, "x1", ln.x0)) + 8.0
        if lx0 <= mx <= lx1:
            return 0.0
        if mx < lx0:
            return lx0 - mx
        return mx - lx1

    def score(ln):
        dx = xdist_to_span(ln)
        dy = abs((table_top_y - 12.0) - float(ln.y0))
        pen = 0.0

        # Prefer header-like text (slightly larger / bold).
        if med_size > 0.0 and float(getattr(ln, "size", 0.0)) < (med_size - 0.7):
            pen += 18.0
        if ln.bold:
            pen -= 10.0

        # Discourage picking the far-left row-label area as "header" for mid/right columns.
        if float(ln.x0) < (left + 0.18 * span) and mx0 > (left + 0.30 * span):
            pen += 30.0

        return 0.70 * dx + 0.80 * dy + pen

    base = min(header_lines, key=score)

    black_sorted = sorted(black_lines, key=lambda l: (l.y0, l.x0))
    block = _wrap_label_block_lines(base, black_sorted, y_stop=band_bot + 1.0, base_x=base.x0)
    label = _block_text(block)

    # If the "header" appears to be a body-cell value (too low / within body), reject.
    if float(base.y0) >= (table_top_y - 2.0):
        return None

    return label or None


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        lines2 = _merge_bracket_fragments(lines)
        left, right, span = _page_metrics(lines2)

        black_lines = [ln for ln in lines2 if (not getattr(ln, "non_black", False)) and (ln.text or "").strip()]
        row_headers = _detect_row_headers(black_lines)
        first_row_y = float(row_headers[0].y0) if row_headers else None

        # Primary layout: bracket codes (not necessarily colored on all pages)
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

        # Keep codes that are plausibly in a "code" column if this page uses a right-column code layout.
        code_lines = []
        if code_candidates:
            if right_code_layout:
                x_thr = left + 0.33 * span
                for ln in code_candidates:
                    if float(ln.x0) >= x_thr:
                        code_lines.append(ln)
                if not code_lines:
                    code_lines = code_candidates[:]
            else:
                code_lines = code_candidates[:]

        # Fallback layout: pages that only expose technical TYPE brackets (no item code brackets)
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

        title = _pick_form_title(lines2, has_fields=has_fields, current_form=current_form)
        if title:
            current_form = title

        if not has_fields:
            continue

        # Readonly/visibility filtering is only reliable for right-column code layouts;
        # left-margin technical stacks frequently include VISIBILITY next to real fields.
        apply_readonly_filter = bool(code_lines) and right_code_layout

        field_markers = sorted(field_markers, key=lambda l: (float(l.y0), float(l.x0)))

        for mk in field_markers:
            if apply_readonly_filter:
                if float(getattr(mk, "x0", 0.0)) >= (left + 0.35 * span):
                    if _has_nearby_readonly_marker(mk, lines2, x_slack=120.0, y_slack=22.0):
                        continue

            label: Optional[str] = None

            if code_lines:
                mk_x0 = float(getattr(mk, "x0", 0.0))

                # Left-margin code layout (e.g., question text + red [CODE]/[TYPE]/[VISIBILITY] stack)
                if left_code_layout and mk_x0 <= (left + 0.24 * span):
                    label = _extract_label_for_left_margin_code(mk, black_lines, left=left, span=span)

                if not label:
                    # Row tables: use a header-above-table strategy, avoid body-cell values.
                    if row_headers and first_row_y is not None and float(mk.y0) >= (first_row_y - 6.0):
                        label = _extract_table_column_header(mk, black_lines, table_top_y=float(first_row_y), left=left, span=span)
                        if not label:
                            # As a safe fallback, allow generic extraction, but only if it doesn't pick from table body.
                            tmp = _extract_label_for_code(mk, black_lines, left=left, span=span)
                            if tmp:
                                # Reject if the chosen base likely lives inside the table body area (common filled-value trap).
                                # We approximate by requiring the label text to not be a short value-like token in the table region.
                                toks = [w for w in _norm_text(tmp).split(" ") if w]
                                if not (first_row_y is not None and float(mk.y0) >= first_row_y - 6.0 and len(toks) <= 2 and mk_x0 >= (left + 0.45 * span)):
                                    label = tmp
                    else:
                        label = _extract_label_same_row_left(mk, black_lines, left=left, span=span)
                        if not label:
                            label = _extract_label_for_code(mk, black_lines, left=left, span=span)
            else:
                label = _extract_label_near_type_marker(mk, black_lines, left=left, span=span)

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
            if row_headers and float(mk.y0) >= (float(row_headers[0].y0) - 6.0):
                row_ctx = _nearest_row_context(black_lines, float(mk.y0), max_dy=130.0)
            elif float(mk.y0) >= 260 and float(mk.x0) >= (left + 0.22 * span):
                row_ctx = _nearest_row_context(black_lines, float(mk.y0), max_dy=115.0)

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
