```python
import re
from typing import List, Dict, Tuple, Optional


def extract(pages):
    out: List[Dict[str, object]] = []
    seen = set()

    def norm_space(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip())

    def strip_trailing_colon(s: str) -> str:
        s = norm_space(s)
        return re.sub(r"\s*[:：]\s*$", "", s)

    def y_close(a: float, b: float, tol: float = 1.6) -> bool:
        return abs(a - b) <= tol

    def looks_like_schedule_value(txt: str) -> str:
        t = norm_space(txt)
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

    def line_is_right_linenum(ln) -> bool:
        t = norm_space(ln.text)
        if ln.x0 < 440:
            return False
        if not t:
            return False
        return re.match(r"^\d+(\.\d+)?(\s*\(.*\))?$", t) is not None

    def row_has_activity_signature(lines, y: float) -> bool:
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
        best_val = None
        best_y = None
        for ln in lines:
            t = norm_space(ln.text)
            if ln.bold and (not ln.non_black) and 10.0 <= ln.size <= 12.5 and ln.x0 <= 120 and ln.y0 <= 140:
                if re.search(r"Schedule\s+Category", t, flags=re.IGNORECASE) and re.search(
                    r"\bName\b", t, flags=re.IGNORECASE
                ):
                    y = ln.y0
                    for ln2 in lines:
                        if y_close(ln2.y0, y) and ln2.x0 >= 135 and (not ln2.bold) and (not ln2.non_black):
                            v = looks_like_schedule_value(ln2.text)
                            if v:
                                if best_y is None or y < best_y:
                                    best_y = y
                                    best_val = v
        if best_val:
            return best_val

        cands = []
        for ln in lines:
            if (
                80 <= ln.y0 <= 120
                and 140 <= ln.x0 <= 260
                and (not ln.bold)
                and (not ln.non_black)
                and 10.0 <= ln.size <= 12.5
            ):
                v = looks_like_schedule_value(ln.text)
                if v:
                    cands.append((ln.y0, v))
        if cands:
            cands.sort()
            return cands[0][1]
        return None

    def find_activity_rows(lines) -> List[Tuple[float, str]]:
        rows = []
        for ln in lines:
            if not (ln.bold and (not ln.non_black) and 9.0 <= ln.size <= 11.5 and 140 <= ln.x0 <= 420):
                continue
            y = ln.y0
            if row_has_activity_signature(lines, y):
                txt = norm_space(ln.text)
                if txt:
                    rows.append((y, txt))
        rows.sort()
        dedup = []
        for y, txt in rows:
            if dedup and abs(y - dedup[-1][0]) <= 1.6 and txt == dedup[-1][1]:
                continue
            dedup.append((y, txt))
        return dedup

    def is_blue_label_colon(ln) -> bool:
        t = norm_space(ln.text)
        if not t:
            return False
        if not (ln.bold and ln.non_black and 8.8 <= ln.size <= 12.6):
            return False
        if ln.y0 < 110:
            return False
        if not re.search(r"[:：]\s*$", t):
            return False
        return True

    def is_answers_marker(ln) -> bool:
        if not is_blue_label_colon(ln):
            return False
        if not (110 <= ln.x0 <= 340):
            return False
        t = strip_trailing_colon(ln.text)
        if re.search(r"\bAnswered\b", t, flags=re.IGNORECASE):
            return False
        return re.search(r"\bAnswer", t, flags=re.IGNORECASE) is not None

    def is_comment_marker(ln) -> bool:
        if not is_blue_label_colon(ln):
            return False
        if not (0 <= ln.x0 <= 340):
            return False
        t = strip_trailing_colon(ln.text)
        return re.fullmatch(r"Comments?", t, flags=re.IGNORECASE) is not None

    def is_staff_marker(ln) -> bool:
        if not is_blue_label_colon(ln):
            return False
        if not (0 <= ln.x0 <= 340):
            return False
        t = strip_trailing_colon(ln.text)
        return re.fullmatch(r"Staff\s*Initials", t, flags=re.IGNORECASE) is not None

    def page_matches_family(lines) -> bool:
        if any(is_title_annotated_crf(ln) for ln in lines):
            return True

        has_schedule = False
        for ln in lines:
            t = norm_space(ln.text)
            if ln.bold and (not ln.non_black) and 10.0 <= ln.size <= 12.5 and ln.x0 <= 140 and ln.y0 <= 170:
                if re.search(r"Schedule\s+Category", t, flags=re.IGNORECASE) and re.search(r"\bName\b", t, flags=re.IGNORECASE):
                    has_schedule = True
                    break

        has_right_ln = any(line_is_right_linenum(ln) for ln in lines)
        has_answers = any(is_answers_marker(ln) for ln in lines)

        return (has_schedule and has_right_ln) or (has_answers and has_right_ln)

    forbidden_question_texts = {
        "group, visit",
        "group",
        "visit",
        "timepoint",
        "activity",
        "line #",
        "line#",
        "line",
    }

    def is_candidate_question_line(lines, ln) -> bool:
        if not (ln.bold and (not ln.non_black) and 9.0 <= ln.size <= 11.8 and 120 <= ln.x0 <= 440):
            return False
        t = norm_space(ln.text)
        if not t:
            return False
        if row_has_activity_signature(lines, ln.y0):
            return False
        if t.startswith("(") and t.endswith(")") and len(t) >= 3:
            return False
        if re.match(r"^[\u25CB\u25EF\u25E6O0]\s+\S", t):
            return False

        tl = strip_trailing_colon(t).lower()
        if tl in forbidden_question_texts:
            return False
        if re.fullmatch(r"Group\s*,\s*Visit", strip_trailing_colon(t), flags=re.IGNORECASE):
            return False
        if re.search(r"\b(Staff\s*Initials|Comments?|Answer\(s\)?|Answer)\b", t, flags=re.IGNORECASE):
            return False
        if len(strip_trailing_colon(t)) < 8:
            return False
        return True

    def collect_wrapped_label(lines, anchor_ln) -> str:
        anchor_y = anchor_ln.y0
        anchor_x = anchor_ln.x0
        cands = []
        for ln in lines:
            if not is_candidate_question_line(lines, ln):
                continue
            if ln.y0 > anchor_y + 0.5:
                continue
            if ln.y0 < anchor_y - 55.0:
                continue
            if abs(ln.x0 - anchor_x) > 34.0:
                continue
            cands.append(ln)
        cands.sort(key=lambda z: (z.y0, z.x0))

        idx = None
        for i, ln in enumerate(cands):
            if y_close(ln.y0, anchor_y, tol=0.8) and abs(ln.x0 - anchor_x) <= 1.0:
                idx = i
                break
        if idx is None:
            if not cands:
                return norm_space(anchor_ln.text)
            idx = max(range(len(cands)), key=lambda i: cands[i].y0)

        group = [cands[idx]]
        prev = cands[idx]
        for j in range(idx - 1, -1, -1):
            ln = cands[j]
            gap = prev.y0 - ln.y0
            if gap <= 0:
                continue
            if gap > 13.0:
                break
            if abs(ln.x0 - anchor_x) > 34.0:
                break
            group.append(ln)
            prev = ln

        group.sort(key=lambda z: (z.y0, z.x0))
        txt = norm_space(" ".join(norm_space(g.text) for g in group if norm_space(g.text)))
        return txt

    def pick_best_question_anchor(lines, y_marker: float, y_lower_bound: Optional[float]) -> Optional[object]:
        cands = []
        min_y = y_marker - 320.0
        if y_lower_bound is not None:
            min_y = max(min_y, y_lower_bound + 4.0)

        for ln in lines:
            if ln.y0 >= y_marker - 6.0:
                continue
            if ln.y0 < min_y:
                continue
            if not is_candidate_question_line(lines, ln):
                continue
            t = strip_trailing_colon(norm_space(ln.text))
            tl = t.lower()

            dy = y_marker - ln.y0
            score = 0.0

            score += max(0.0, 220.0 - dy)  # prefer close
            score += min(len(t), 90) * 1.2  # prefer substantive labels
            if "?" in t:
                score += 30.0
            if "(" in t or ")" in t:
                score += 14.0
            if re.search(r"\b(what|which|when|where|why|how)\b", t, flags=re.IGNORECASE):
                score += 10.0

            if tl in forbidden_question_texts or re.fullmatch(r"group\s*,\s*visit", t, flags=re.IGNORECASE):
                score -= 300.0
            if "," in t and len(t) <= 14:
                score -= 80.0

            cands.append((score, ln))

        if not cands:
            return None
        cands.sort(key=lambda x: x[0], reverse=True)
        best_score, best_ln = cands[0]
        if best_score < 60.0:
            return None
        return best_ln

    current_schedule = ""
    current_activity = ""

    for page_idx0, lines in pages:
        if not lines:
            continue
        if not page_matches_family(lines):
            continue

        schedule = find_schedule_name(lines)
        if schedule and schedule != current_schedule:
            current_schedule = schedule
            current_activity = ""

        activity_rows = find_activity_rows(lines)
        if activity_rows:
            current_activity = activity_rows[-1][1]

        def nearest_activity_before(y: float) -> Optional[Tuple[float, str]]:
            best = None
            best_dy = None
            for ay, atxt in activity_rows:
                if ay <= y + 0.5:
                    dy = y - ay
                    if best_dy is None or dy < best_dy:
                        best_dy = dy
                        best = (ay, atxt)
            return best

        def page_form_context_for_y(y: float) -> str:
            local = nearest_activity_before(y)
            if local:
                return norm_space(local[1])
            if current_activity:
                return norm_space(current_activity)
            return norm_space(current_schedule or "")

        answers_markers = [ln for ln in lines if is_answers_marker(ln)]
        answers_markers.sort(key=lambda z: (z.y0, z.x0))

        for am in answers_markers:
            form_name = page_form_context_for_y(am.y0)
            local_act = nearest_activity_before(am.y0)
            y_lower = local_act[0] if local_act else None

            anchor = pick_best_question_anchor(lines, am.y0, y_lower)
            if anchor is None:
                continue

            field_name = strip_trailing_colon(collect_wrapped_label(lines, anchor))
            if not field_name:
                continue

            kq = (page_idx0, form_name, field_name, int(round(am.y0)))
            if kq not in seen:
                seen.add(kq)
                out.append({"form_name": form_name, "field_name": field_name, "page": page_idx0 + 1})

            # Comment is a data-entry field in this family; Staff Initials is not.
            comment_cands = []
            for ln in lines:
                if not is_comment_marker(ln):
                    continue
                if y_lower is not None and ln.y0 < y_lower + 2.0:
                    continue
                if not (am.y0 - 10.0 <= ln.y0 <= am.y0 + 150.0):
                    continue
                dy = abs(ln.y0 - (am.y0 + 30.0))  # typically below Answer(s)
                dx = abs(ln.x0 - am.x0)
                comment_cands.append((dy + 0.15 * dx, ln))

            if comment_cands:
                comment_cands.sort(key=lambda x: x[0])
                ck = (page_idx0, form_name, "Comment", int(round(comment_cands[0][1].y0)))
                if ck not in seen:
                    seen.add(ck)
                    out.append({"form_name": form_name, "field_name": "Comment", "page": page_idx0 + 1})

            # If the page has Staff Initials labels, ignore them explicitly (no emission).
            # (kept only to avoid future accidental reuse)
            _ = any(is_staff_marker(ln) for ln in lines)

    return out
```
