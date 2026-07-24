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
        # avoid picking page numbers / tiny headers
        if ln.size < (max_size_top - 1.2):
            continue
        # Titles are often left or centered; keep slack but avoid far-right legend columns.
        if ln.x0 > 560:
            continue
        # Prefer colored titles; allow black if very large/bold.
        if ln.non_black or ln.bold or ln.size >= (max_size_top - 0.2):
            cands.append(ln)

    if not cands:
        return None

    # Do not update title on pages without fields unless no title is known yet.
    if not has_fields and current_form:
        return None

    # Prefer the topmost prominent line; break ties by being more left-ish (but not strictly left).
    cands.sort(key=lambda l: (l.y0, (0 if l.x0 <= 320 else 1), l.x0))
    title = _norm_text(cands[0].text)

    # Guard: titles are not usually phrased as a question.
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


def _wrap_label_block(base, black_sorted, y_stop: float, base_x: float) -> str:
    # Build a wrapped label block around the base line by proximity/indent.
    # Collect nearby black lines (above and below) with similar indent.
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

    return _norm_text(" ".join((ln.text or "").strip() for ln in block))


def _extract_label_same_row_left(marker, black_lines, x_left_limit: float) -> Optional[str]:
    # Prefer the label on the same row to the left of the marker (common in tables).
    y = float(marker.y0)
    x = float(marker.x0)

    same = []
    for ln in black_lines:
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        if ln.x0 >= x - 10:
            continue
        if abs(float(ln.y0) - y) > 6.5:
            continue
        # avoid far-left headers when marker is far-right and there are better row labels
        if ln.x0 < x_left_limit and (x - ln.x0) > 420:
            continue
        same.append(ln)

    if not same:
        return None

    # Choose the closest left neighbor by horizontal gap, then by being slightly higher.
    same.sort(key=lambda l: (abs(x - float(l.x1)), abs(y - float(l.y0)), abs(x - float(l.x0))))
    base = same[0]

    black_sorted = sorted(black_lines, key=lambda l: (l.y0, l.x0))
    label = _wrap_label_block(base, black_sorted, y_stop=y + 9.0, base_x=base.x0)
    return label or None


def _extract_label_same_line_right(marker, black_lines) -> Optional[str]:
    # For left-margin technical markers (e.g. TYPE), the human label is often on the same line to the right.
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
        # prefer modest dx; labels usually start fairly near the marker
        return dx + (8.0 if ln.x0 > 520 else 0.0)

    base = min(cands, key=score)
    black_sorted = sorted(black_lines, key=lambda l: (l.y0, l.x0))
    label = _wrap_label_block(base, black_sorted, y_stop=y + 14.0, base_x=base.x0)
    return label or None


def _extract_label_for_code(code_line, black_lines) -> Optional[str]:
    y = float(code_line.y0)
    x = float(code_line.x0)

    # Candidate black lines above within a generous window.
    cands = []
    for ln in black_lines:
        if float(ln.y0) >= y:
            continue
        dy = y - float(ln.y0)
        if dy > 155:
            continue
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t):
            continue
        # De-emphasize right-side option/legend columns
        if float(ln.x0) > 420 and abs(float(ln.x0) - x) > 90:
            continue
        cands.append(ln)

    if not cands:
        return None

    def score(ln):
        dy = y - float(ln.y0)
        dx = abs(float(ln.x0) - x)
        pen = 0.0
        if x < 140:
            if float(ln.x0) > 260:
                pen += 250.0
        else:
            if float(ln.x0) < 200 and dx > 120:
                pen += 35.0
        if _is_row_only((ln.text or "").strip()):
            pen += 120.0
        if ln.bold and dy <= 70:
            pen -= 18.0
        return dy + 0.30 * dx + pen

    base = min(cands, key=score)
    black_sorted = sorted([ln for ln in black_lines if float(ln.y0) < y], key=lambda l: (l.y0, l.x0))
    label = _wrap_label_block(base, black_sorted, y_stop=y, base_x=base.x0)
    return label or None


def _extract_label_near_type_marker(type_line, black_lines) -> Optional[str]:
    # Same-line-right is common for TYPE markers.
    label = _extract_label_same_line_right(type_line, black_lines)
    if label:
        return label

    # Prefer the usual "label above" heuristic next.
    label = _extract_label_for_code(type_line, black_lines)
    if label:
        return label

    # Fallback: some pages place the human label below the TYPE line.
    y = float(type_line.y0)
    x = float(type_line.x0)

    cands = []
    for ln in black_lines:
        if float(ln.y0) <= y:
            continue
        dy = float(ln.y0) - y
        if dy > 165:
            continue
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        if float(ln.x0) > 420 and abs(float(ln.x0) - x) > 90:
            continue
        if float(ln.x0) >= 260:
            tu = _norm_text(t).lower()
            if tu in _OPTION_WORDS and dy <= 90:
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
    black_sorted = sorted([ln for ln in black_lines if float(ln.y0) < (y + 190)], key=lambda l: (l.y0, l.x0))
    label2 = _wrap_label_block(base, black_sorted, y_stop=y + 190, base_x=base.x0)
    return label2 or None


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


def _extract_table_column_header(marker, black_lines, row_header_ln) -> Optional[str]:
    # In "Row N" repeating tables, the field label is typically a column header above the row band.
    my = float(marker.y0)
    mx = float(marker.x0)
    ry = float(row_header_ln.y0)

    # Header band: above the row header, but not too high (to avoid page title).
    header_cands = []
    for ln in black_lines:
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t) or _is_row_only(t):
            continue
        y0 = float(ln.y0)
        if not (ry - 120.0 <= y0 < ry - 4.0):
            continue
        # column headers are often bold-ish; keep slack but prefer bold later
        # keep in the table area, not extreme far-right legends
        if float(ln.x0) > 560:
            continue
        header_cands.append(ln)

    if not header_cands:
        return None

    def score(ln):
        # Prefer x-aligned with marker column (header may start left of cell).
        dx = abs(float(ln.x0) - mx)
        dy = abs((ry - 10.0) - float(ln.y0))
        pen = 0.0
        if ln.bold:
            pen -= 10.0
        # discourage picking the left row-label area as a "header"
        if float(ln.x0) < 120 and mx > 220:
            pen += 35.0
        return 0.55 * dx + 0.75 * dy + pen

    base = min(header_cands, key=score)
    black_sorted = sorted(black_lines, key=lambda l: (l.y0, l.x0))
    label = _wrap_label_block(base, black_sorted, y_stop=ry - 1.0, base_x=base.x0)
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

        # Keep codes that are plausibly in a right-side "code" column.
        code_lines = []
        if code_candidates:
            x_thr = left + 0.40 * span
            # Some pages put codes mid-right; keep slack but avoid far-left technical markers.
            for ln in code_candidates:
                if float(ln.x0) >= x_thr:
                    code_lines.append(ln)
            # If that filtered everything (rare mid-page codes), fall back to all candidates.
            if not code_lines:
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

        # Sort markers top-to-bottom for stable behavior
        field_markers = sorted(field_markers, key=lambda l: (float(l.y0), float(l.x0)))

        for mk in field_markers:
            # Exclude non-editable display cells where VISIBILITY/READ-ONLY is printed nearby.
            if _has_nearby_readonly_marker(mk, lines2, x_slack=120.0, y_slack=22.0):
                continue

            label: Optional[str] = None

            if code_lines:
                # For row-tables (Row N present), prefer column-header extraction to avoid row labels and table furniture.
                if row_headers and first_row_y is not None and float(mk.y0) >= (first_row_y - 6.0):
                    # Pick nearest row header above marker
                    rh = None
                    best = 1e9
                    for rln in row_headers:
                        dy = float(mk.y0) - float(rln.y0)
                        if dy < -2.0:
                            continue
                        if dy <= 130.0 and dy < best:
                            best = dy
                            rh = rln
                    if rh is None:
                        rh = row_headers[0]
                    label = _extract_table_column_header(mk, black_lines, rh)

                    # If header couldn't be found, fall back to the original heuristic.
                    if not label:
                        label = _extract_label_for_code(mk, black_lines)
                else:
                    # Non-row-table pages: prefer same-row-left label first (avoids selecting section headers above).
                    label = _extract_label_same_row_left(mk, black_lines, x_left_limit=left + 0.12 * span)
                    if not label:
                        label = _extract_label_for_code(mk, black_lines)
            else:
                label = _extract_label_near_type_marker(mk, black_lines)

            if not label:
                continue

            field_name = _norm_text(label)
            if not field_name:
                continue
            if _is_bracketish(field_name) or _is_row_only(field_name):
                continue

            # Add row context for dense/repeatable tables so repeated rows don't collapse semantically.
            row_ctx = None
            if row_headers and float(mk.y0) >= (float(row_headers[0].y0) - 6.0):
                row_ctx = _nearest_row_context(black_lines, float(mk.y0), max_dy=120.0)
            elif float(mk.y0) >= (left + 0.0) and float(mk.y0) >= 260 and float(mk.x0) >= (left + 0.22 * span):
                row_ctx = _nearest_row_context(black_lines, float(mk.y0), max_dy=110.0)

            if row_ctx and row_ctx.lower() not in field_name.lower():
                field_name = _norm_text(f"{row_ctx} - {field_name}")

            # Final structural guard: avoid selecting isolated right-column option words.
            if field_name.strip().lower() in _OPTION_WORDS and float(getattr(mk, "x0", 0.0)) >= left + 0.55 * span:
                continue

            out.append(
                {
                    "form_name": current_form or "",
                    "field_name": field_name,
                    "page": int(page_idx0) + 1,
                }
            )

    return out
```
