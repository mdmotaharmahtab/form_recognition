```python
# Observed layout: "Annotated CRF" pages with a blue header row, a "Schedule Category & Name" value,
# and repeated vertical blocks containing an activity/form row (often with a right-side line number),
# followed by a bold black question label, and blue labels for Staff Initials / Answer(s) / Comment.
# Strategy: identify these pages by the large "Annotated CRF" title, track current schedule + activity
# as form context across pages, and for each Answer(s) marker extract the nearest preceding bold label
# (joining wrapped lines), plus the nearby blue left-margin labels (e.g., Staff Initials, Comment).

import re
from typing import List, Dict, Tuple, Optional


def extract(pages):
    out: List[Dict[str, object]] = []
    seen = set()

    def norm_space(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip())

    def strip_trailing_colon(s: str) -> str:
        s = norm_space(s)
        s = re.sub(r"\s*[:：]\s*$", "", s)
        return s

    def y_close(a: float, b: float, tol: float = 1.6) -> bool:
        return abs(a - b) <= tol

    def looks_like_schedule_value(txt: str) -> str:
        t = norm_space(txt)
        # Strip leading machine-ish code "AAAA12345," if present.
        m = re.match(r"^([A-Z]{2,}\d{3,})\s*,\s*(.+)$", t)
        if m:
            return norm_space(m.group(2))
        return t

    def is_title_annotated_crf(ln) -> bool:
        t = (ln.text or "").strip()
        if not t:
            return False
        return (
            ln.bold
            and ln.non_black
            and ln.size >= 17.5
            and ln.y0 <= 65
            and re.search(r"\bAnnotated\b", t, flags=re.IGNORECASE) is not None
            and re.search(r"\bCRF\b", t, flags=re.IGNORECASE) is not None
        )

    def page_matches_family(lines) -> bool:
        # Strong signal: large blue title "Annotated CRF"
        return any(is_title_annotated_crf(ln) for ln in lines)

    def line_is_right_linenum(ln) -> bool:
        t = norm_space(ln.text)
        if ln.x0 < 440:
            return False
        if not t:
            return False
        # E.g. "1.0", "3.0 (hidden)", "5.1 (hidden)"
        return re.match(r"^\d+(\.\d+)?(\s*\(.*\))?$", t) is not None

    def row_has_activity_signature(lines, y: float) -> bool:
        # Activity row: has a right-side line number and some left-side timepoint text at same y.
        has_right = False
        has_left = False
        for ln in lines:
            if not y_close(ln.y0, y):
                continue
            if line_is_right_linenum(ln):
                has_right = True
            if ln.x0 <= 90 and (not ln.bold) and (not ln.non_black) and 9.0 <= ln.size <= 11.5:
                if norm_space(ln.text):
                    has_left = True
        return has_right and has_left

    def find_schedule_name(lines) -> Optional[str]:
        # Look for "Schedule Category & Name:" label, then take the value on the same row at x~>140.
        best_val = None
        best_y = None
        for ln in lines:
            t = norm_space(ln.text)
            if ln.bold and (not ln.non_black) and 10.0 <= ln.size <= 12.5 and ln.x0 <= 120 and ln.y0 <= 140:
                if re.search(r"Schedule\s+Category", t, flags=re.IGNORECASE) and re.search(
                    r"\bName\b", t, flags=re.IGNORECASE
                ):
                    y = ln.y0
                    # find value line on same y, more to the right
                    for ln2 in lines:
                        if y_close(ln2.y0, y) and ln2.x0 >= 135 and (not ln2.bold) and (not ln2.non_black):
                            v = looks_like_schedule_value(ln2.text)
                            if v:
                                if best_y is None or y < best_y:
                                    best_y = y
                                    best_val = v
        if best_val:
            return best_val

        # Fallback: value-like line near top at x~167, size~11
        cands = []
        for ln in lines:
            if 80 <= ln.y0 <= 120 and 140 <= ln.x0 <= 260 and (not ln.bold) and (not ln.non_black) and 10.0 <= ln.size <= 12.5:
                v = looks_like_schedule_value(ln.text)
                if v:
                    cands.append((ln.y0, v))
        if cands:
            cands.sort()
            return cands[0][1]
        return None

    def find_activity_rows(lines) -> List[Tuple[float, str]]:
        rows = []
        # Candidate activity text: bold black at x~>140 on a row with a right line number.
        for ln in lines:
            if not (ln.bold and (not ln.non_black) and 9.0 <= ln.size <= 11.5 and 140 <= ln.x0 <= 420):
                continue
            y = ln.y0
            if row_has_activity_signature(lines, y):
                txt = norm_space(ln.text)
                if txt:
                    rows.append((y, txt))
        rows.sort()
        # De-dupe near-identical rows
        dedup = []
        for y, txt in rows:
            if dedup and abs(y - dedup[-1][0]) <= 1.6 and txt == dedup[-1][1]:
                continue
            dedup.append((y, txt))
        return dedup

    def is_answer_marker(ln) -> bool:
        # Blue label near x~167, ends with ":" and appears below header region.
        t = norm_space(ln.text)
        if not t:
            return False
        if not (ln.bold and ln.non_black and 9.0 <= ln.size <= 11.5):
            return False
        if not (125 <= ln.x0 <= 260 and ln.y0 >= 130):
            return False
        if not re.search(r"[:：]\s*$", t):
            return False
        # Exclude header-row items like "Activity" / "Timepoint" / "Line #"
        if ln.y0 <= 140 and re.fullmatch(r"(Timepoint|Activity|Line\s*#)", t, flags=re.IGNORECASE):
            return False
        return True

    def is_left_blue_label(ln) -> bool:
        t = norm_space(ln.text)
        if not t:
            return False
        if not (ln.bold and ln.non_black and 9.0 <= ln.size <= 11.5):
            return False
        if ln.x0 > 120:
            return False
        if not re.search(r"[:：]\s*$", t):
            return False
        # Avoid page furniture (rare on left, but cheap filter)
        if re.search(r"\bPage\b", t, flags=re.IGNORECASE):
            return False
        return True

    def is_candidate_question_line(lines, ln) -> bool:
        if not (ln.bold and (not ln.non_black) and 9.0 <= ln.size <= 11.5 and 140 <= ln.x0 <= 420):
            return False
        t = norm_space(ln.text)
        if not t:
            return False
        # Exclude the activity row itself
        if row_has_activity_signature(lines, ln.y0):
            return False
        # Exclude purely parenthetical notes (often instructions, not the field label)
        if t.startswith("(") and t.endswith(")") and len(t) >= 3:
            return False
        # Exclude obvious option lines ("O Yes", etc.) though those are not bold in samples
        if re.match(r"^[\u25CB\u25EF\u25E6O0]\s+\S", t):
            return False
        return True

    def collect_wrapped_label(lines, anchor_ln) -> str:
        # Collect the anchor line plus any immediately adjacent bold-black lines above it
        # with similar x, small vertical gap, and not activity/parenthetical.
        anchor_y = anchor_ln.y0
        anchor_x = anchor_ln.x0
        cands = []
        for ln in lines:
            if not is_candidate_question_line(lines, ln):
                continue
            if ln.y0 > anchor_y + 0.5:
                continue
            if ln.y0 < anchor_y - 40.0:
                continue
            if abs(ln.x0 - anchor_x) > 28.0:
                continue
            cands.append(ln)
        cands.sort(key=lambda z: (z.y0, z.x0))

        # Identify contiguous group ending at anchor by y gaps
        # Find anchor index (closest y match)
        idx = None
        for i, ln in enumerate(cands):
            if y_close(ln.y0, anchor_y, tol=0.8) and abs(ln.x0 - anchor_x) <= 1.0:
                idx = i
        if idx is None:
            # Fallback: choose lowest (max y) among candidates near anchor
            if not cands:
                return norm_space(anchor_ln.text)
            idx = max(range(len(cands)), key=lambda i: cands[i].y0)

        group = [cands[idx]]
        # walk upward
        prev = cands[idx]
        for j in range(idx - 1, -1, -1):
            ln = cands[j]
            gap = prev.y0 - ln.y0
            if gap <= 0:
                continue
            if gap > 13.0:
                break
            # keep same-ish x and line shape
            if abs(ln.x0 - anchor_x) > 28.0:
                break
            group.append(ln)
            prev = ln

        group.sort(key=lambda z: (z.y0, z.x0))
        txt = norm_space(" ".join(norm_space(g.text) for g in group if norm_space(g.text)))
        return txt

    current_schedule = ""
    current_activity = ""
    activity_rows_global: List[Tuple[int, float, str]] = []  # (page_idx, y, text)

    for page_idx0, lines in pages:
        if not lines:
            continue
        if not page_matches_family(lines):
            continue

        schedule = find_schedule_name(lines)
        if schedule and schedule != current_schedule:
            current_schedule = schedule
            # schedule changed: reset activity context (avoid leaking across sections)
            current_activity = ""

        activity_rows = find_activity_rows(lines)
        if activity_rows:
            # update current activity to the last one on the page (used as carryover)
            current_activity = activity_rows[-1][1]
            for y, txt in activity_rows:
                activity_rows_global.append((page_idx0, y, txt))

        # Build quick lookup for nearest activity row on this page
        def nearest_activity_before(y: float) -> Optional[str]:
            best = None
            best_dy = None
            for ay, atxt in activity_rows:
                if ay <= y + 0.5:
                    dy = y - ay
                    if best_dy is None or dy < best_dy:
                        best_dy = dy
                        best = atxt
            return best

        def page_form_context_for_y(y: float) -> str:
            local = nearest_activity_before(y)
            if local:
                return local
            if current_activity:
                return current_activity
            return current_schedule or ""

        # Process Answer(s) markers
        answer_markers = [ln for ln in lines if is_answer_marker(ln)]
        for am in answer_markers:
            form_name = norm_space(page_form_context_for_y(am.y0))

            # Find nearest preceding candidate question line within 120pt
            q_cands = []
            for ln in lines:
                if ln.y0 >= am.y0 - 8.0:
                    continue
                if ln.y0 < am.y0 - 120.0:
                    continue
                if not is_candidate_question_line(lines, ln):
                    continue
                q_cands.append(ln)
            if not q_cands:
                continue
            q_cands.sort(key=lambda z: (-(z.y0), z.x0))
            anchor = q_cands[0]
            field_name = strip_trailing_colon(collect_wrapped_label(lines, anchor))
            if not field_name:
                continue

            key = (page_idx0, form_name, field_name)
            if key not in seen:
                seen.add(key)
                out.append({"form_name": form_name, "field_name": field_name, "page": page_idx0 + 1})

            # Attach nearby left-margin blue labels as fields (e.g. Staff Initials, Comment)
            # Staff-like label: before Answer(s)
            staff_label = None
            staff_best_dy = None
            for ln in lines:
                if not is_left_blue_label(ln):
                    continue
                if not (am.y0 - 55.0 <= ln.y0 <= am.y0 - 4.0):
                    continue
                dy = am.y0 - ln.y0
                if staff_best_dy is None or dy < staff_best_dy:
                    staff_best_dy = dy
                    staff_label = ln

            if staff_label is not None:
                staff_name = strip_trailing_colon(staff_label.text)
                if staff_name:
                    key2 = (page_idx0, form_name, staff_name, int(round(staff_label.y0)))
                    if key2 not in seen:
                        seen.add(key2)
                        out.append({"form_name": form_name, "field_name": staff_name, "page": page_idx0 + 1})

            # Comment-like label: after Answer(s)
            comment_label = None
            comment_best_dy = None
            for ln in lines:
                if not is_left_blue_label(ln):
                    continue
                if not (am.y0 + 6.0 <= ln.y0 <= am.y0 + 95.0):
                    continue
                dy = ln.y0 - am.y0
                if comment_best_dy is None or dy < comment_best_dy:
                    comment_best_dy = dy
                    comment_label = ln

            if comment_label is not None:
                comment_name = strip_trailing_colon(comment_label.text)
                if comment_name:
                    key3 = (page_idx0, form_name, comment_name, int(round(comment_label.y0)))
                    if key3 not in seen:
                        seen.add(key3)
                        out.append({"form_name": form_name, "field_name": comment_name, "page": page_idx0 + 1})

    return out
```
