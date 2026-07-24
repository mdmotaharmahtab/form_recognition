```python
# Observed layout: repeated “Annotated CRF” pages with a 3-column header (Timepoint / Activity / Line #)
# and many stacked field blocks. Each block has a bold black question/label near x~167 and a colored
# “Answer(s):” marker; machine annotations like “[XXXX] SAS:[...]” appear under answers.
# Strategy: detect this layout by header geometry; track current form_name from “Activity” rows; for each
# “Answer(s):” marker, collect the label lines above the nearby “Staff Initials:” marker and emit fields.

import re
from typing import List, Tuple, Dict, Any


_WS_RE = re.compile(r"\s+")
_MACHINE_RE = re.compile(r"^\s*\[[A-Za-z0-9_]+\]\s*")
_PAGE_FURN_RE = re.compile(r"^\s*(Page\s+\d+\s+of\s+\d+|Date\s+Created\s*:)", re.IGNORECASE)


def _norm(s: str) -> str:
    s = s.replace("\u00ad", "").replace("\u200b", "")
    s = _WS_RE.sub(" ", s).strip()
    return s


def _has_many_underscores(s: str) -> bool:
    # Treat answer-entry prompts/blank lines as non-labels.
    return s.count("_") >= 4


def _is_machine_annotation(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if "SAS:[" in s or "SAS:" in s:
        return True
    if _MACHINE_RE.match(s):
        return True
    return False


def _looks_like_furniture(line) -> bool:
    t = line.text.strip()
    if not t:
        return True
    if line.y0 > 730:
        return True
    if _PAGE_FURN_RE.match(t):
        return True
    return False


def _is_colored_headerish(line) -> bool:
    # Blue header/labels: non_black + bold + size ~10, used for column headers and markers.
    return bool(line.non_black and line.bold and 8.5 <= line.size <= 12.5)


def _is_layout_page(lines) -> bool:
    if not lines:
        return False

    # Large colored title near the top (size ~20).
    has_title = any((ln.non_black and ln.bold and ln.size >= 18 and ln.y0 < 70) for ln in lines)

    # Column header trio around y~110-130: colored bold at left/mid/right.
    left = mid = right = 0
    for ln in lines:
        if not _is_colored_headerish(ln):
            continue
        if not (90 <= ln.y0 <= 140):
            continue
        if ln.x0 < 80:
            left += 1
        elif 120 <= ln.x0 <= 240:
            mid += 1
        elif ln.x0 > 430:
            right += 1

    return has_title and (left + mid + right) >= 2 and (mid >= 1)


def _row_key(y: float, tol: float = 2.0) -> int:
    return int((y + tol / 2.0) // tol)


def _build_rows(lines):
    rows = {}
    for i, ln in enumerate(lines):
        k = _row_key(ln.y0)
        rows.setdefault(k, []).append((i, ln))
    # keep each row sorted by x
    for k in list(rows.keys()):
        rows[k].sort(key=lambda p: p[1].x0)
    return rows


def _is_line_number_token(s: str) -> bool:
    s = s.strip()
    # Examples: "1.0", "3.0 (hidden)", "5.1 (hidden)"
    return bool(re.match(r"^\d+(\.\d+)?(\s*\(.*\))?\s*$", s))


def _extract_schedule_context(lines) -> str:
    # Geometry-based fallback context: the schedule value line is usually at x~167, size~11, black, near y~90-105.
    best = ""
    best_y = 1e9
    for ln in lines:
        if ln.non_black:
            continue
        if not (9.5 <= ln.size <= 12.5):
            continue
        if not (140 <= ln.x0 <= 220):
            continue
        if not (80 <= ln.y0 <= 115):
            continue
        t = _norm(ln.text)
        if not t:
            continue
        # Prefer the earliest such line; it tends to be the schedule/category name value.
        if ln.y0 < best_y:
            best, best_y = t, ln.y0
    return best


def _mark_activity_rows(lines) -> Tuple[Dict[int, str], List[float]]:
    """
    Returns:
      - activity_mid_index_to_text
      - list of activity y0 positions (for quick lookup)
    """
    rows = _build_rows(lines)
    activity = {}
    activity_ys = []
    for _, row in rows.items():
        # Need: left timepoint-ish cell, mid bold black, right numeric line# token
        left_ln = None
        mid_ln = None
        right_ln = None

        for _, ln in row:
            if _looks_like_furniture(ln):
                continue
            if ln.x0 < 80 and not ln.non_black and 8.5 <= ln.size <= 12.5:
                # timepoint / day line (language-agnostic)
                left_ln = ln
            elif 140 <= ln.x0 <= 260 and ln.bold and not ln.non_black and 8.5 <= ln.size <= 12.5:
                # mid activity title
                mid_ln = ln
            elif ln.x0 > 430 and not ln.non_black and 8.5 <= ln.size <= 12.5:
                if _is_line_number_token(ln.text):
                    right_ln = ln

        if left_ln and mid_ln and right_ln:
            t = _norm(mid_ln.text)
            if t and not _is_machine_annotation(t) and not _has_many_underscores(t):
                # store by identity via index, but we only have line objects; map by row search later if needed
                # We'll match by (y0,x0,text) when excluding.
                activity[id(mid_ln)] = t
                activity_ys.append(mid_ln.y0)

    activity_ys.sort()
    return activity, activity_ys


def _find_last_activity_before(lines, activity_map, y: float) -> str:
    # Find nearest activity title row above y by scanning a limited window.
    best_y = -1e9
    best = ""
    for ln in lines:
        if ln.y0 >= y:
            continue
        if not (140 <= ln.x0 <= 260):
            continue
        if not (ln.bold and not ln.non_black and 8.5 <= ln.size <= 12.5):
            continue
        key = id(ln)
        if key in activity_map:
            if ln.y0 > best_y:
                best_y = ln.y0
                best = activity_map[key]
    return best


def _is_answer_marker(ln) -> bool:
    if not _is_colored_headerish(ln):
        return False
    if not (120 <= ln.x0 <= 240):
        return False
    t = ln.text.strip()
    # Typically ends with ":" (e.g., "Answer(s):"); language-independent enough.
    return t.endswith(":")


def _is_staff_marker(ln) -> bool:
    if not _is_colored_headerish(ln):
        return False
    if not (ln.x0 < 90):
        return False
    t = ln.text.strip()
    return t.endswith(":")


def _label_candidate(ln, activity_map) -> bool:
    if _looks_like_furniture(ln):
        return False
    if ln.non_black:
        return False
    if not (140 <= ln.x0 <= 280):
        return False
    if not (8.5 <= ln.size <= 12.5):
        return False
    t = _norm(ln.text)
    if not t:
        return False
    if _is_machine_annotation(t):
        return False
    if _has_many_underscores(t):
        return False
    # Exclude activity titles themselves.
    if id(ln) in activity_map:
        return False
    return True


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    current_schedule = ""
    current_form = ""

    for page_index0, lines in pages:
        if not _is_layout_page(lines):
            continue

        # Update schedule context if present.
        sched = _extract_schedule_context(lines)
        if sched:
            current_schedule = sched

        activity_map, _ = _mark_activity_rows(lines)

        # Also update current_form as we encounter activity rows in reading y-order.
        # We'll do this on the fly while scanning markers by using nearest activity above each field.
        # (Still, if a page has activity rows but no fields, keep the last one.)
        last_activity_on_page = _find_last_activity_before(lines, activity_map, y=1e9)
        if last_activity_on_page:
            # do not blindly override (fields might belong to earlier activity on page),
            # but keep it as a future fallback after processing.
            pass

        # Collect indices of answer markers.
        answer_idxs = [i for i, ln in enumerate(lines) if _is_answer_marker(ln) and ln.y0 > 130]

        # Precompute previous answer marker y for window bounding.
        prev_answer_y = -1e9
        for idx in answer_idxs:
            ans_ln = lines[idx]

            # Find a nearby staff marker just above (within ~45 pts).
            staff_ln = None
            for j in range(idx - 1, -1, -1):
                ln = lines[j]
                if ln.y0 < ans_ln.y0 - 60:
                    break
                if _is_staff_marker(ln) and 0 < (ans_ln.y0 - ln.y0) <= 45:
                    staff_ln = ln
                    break
            if staff_ln is None:
                prev_answer_y = ans_ln.y0
                continue

            # Determine form name: nearest activity row above staff marker, else carry from previous pages.
            form_here = _find_last_activity_before(lines, activity_map, y=staff_ln.y0 + 0.01)
            if form_here:
                current_form = form_here

            # Label window: between previous answer marker and staff marker, and not too far.
            y_min = max(prev_answer_y + 1.0, staff_ln.y0 - 230.0)
            y_max = staff_ln.y0 - 0.5

            cands = []
            for ln in lines:
                if not (y_min <= ln.y0 <= y_max):
                    continue
                if _label_candidate(ln, activity_map):
                    cands.append(ln)

            if not cands:
                prev_answer_y = ans_ln.y0
                continue

            # Join label lines in y/x order; avoid accidental duplicates.
            cands.sort(key=lambda l: (l.y0, l.x0))
            parts = []
            last_t = None
            for ln in cands:
                t = _norm(ln.text)
                if not t:
                    continue
                if t == last_t:
                    continue
                parts.append(t)
                last_t = t

            field = _norm(" ".join(parts))
            if not field:
                prev_answer_y = ans_ln.y0
                continue

            # Final guard: field_name should not be purely numeric / trivial.
            if re.fullmatch(r"[\d\.\-]+", field):
                prev_answer_y = ans_ln.y0
                continue

            form_name = current_form or current_schedule or ""
            out.append({"form_name": form_name, "field_name": field, "page": page_index0 + 1})

            prev_answer_y = ans_ln.y0

        # If we saw an activity on this page, update carry-forward for next page.
        if last_activity_on_page:
            current_form = last_activity_on_page

    return out
```
