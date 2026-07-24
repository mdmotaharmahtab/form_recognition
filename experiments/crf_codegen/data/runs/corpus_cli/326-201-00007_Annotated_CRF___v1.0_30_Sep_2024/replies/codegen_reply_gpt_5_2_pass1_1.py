```python
# Observed layout: "Annotated CRF" pages with a fixed header block, then repeated activity blocks.
# Each activity block prints a bold black activity/form title at x≈168 (often containing "#<n>"),
# followed by one bold black question/label that may wrap across multiple bold lines, then blue "Staff Initials"/"Answer(s)".
# Strategy: detect these pages by header markers; carry forward the last seen activity/form title across page breaks;
# for each activity, capture the next bold-black label paragraph (excluding options/codes) up to the next blue boundary.

import re
import unicodedata


def extract(pages):
    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKC", s or "")
        s = s.replace("\u00a0", " ")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def is_machine_code_text(t: str) -> bool:
        # e.g. "[DSSTDAT] SAS:[Name=..., Length=..., DataType=...]"
        if not t:
            return True
        if t.startswith("[") and ("SAS:" in t or re.search(r"^\[[A-Z0-9_]+\]\s*", t)):
            return True
        return False

    def is_page_furniture_text(t: str) -> bool:
        if not t:
            return True
        tt = t.lower()
        if "page " in tt and " of " in tt:
            return True
        if tt.startswith("date created:"):
            return True
        return False

    def is_target_layout(lines) -> bool:
        # Look for the distinctive header combination.
        has_annotated = False
        has_schedule = False
        has_timepoint_row = False
        for ln in lines[:60]:
            t = norm(ln.text)
            if not t:
                continue
            if t.lower() == "annotated crf" and ln.bold and ln.non_black and ln.size >= 16:
                has_annotated = True
            if "schedule category" in t.lower() and ln.bold and not ln.non_black and 9 <= ln.size <= 13:
                has_schedule = True
            if t.lower() == "timepoint" and ln.bold and ln.non_black and 8 <= ln.size <= 12:
                has_timepoint_row = True
        return has_annotated and has_schedule and has_timepoint_row

    def get_body_start_y(lines) -> float:
        # After the blue "Timepoint" row; default if not found.
        for ln in lines[:80]:
            t = norm(ln.text)
            if t.lower() == "timepoint" and ln.bold and ln.non_black:
                return ln.y0 + 5.0
        return 120.0

    def get_schedule_name(lines) -> str:
        # Value printed on same row as "Schedule Category & Name:" (often at x≈168).
        # Fall back to the first non-bold black line near that region.
        schedule_label_y = None
        for ln in lines[:80]:
            t = norm(ln.text)
            if t.lower().startswith("schedule category") and ln.bold and not ln.non_black:
                schedule_label_y = ln.y0
                break
        if schedule_label_y is None:
            return ""
        best = None
        best_dx = 1e9
        for ln in lines[:120]:
            t = norm(ln.text)
            if not t or is_page_furniture_text(t):
                continue
            if abs(ln.y0 - schedule_label_y) <= 2.5 and 120 <= ln.x0 <= 260 and not ln.bold and not ln.non_black:
                dx = abs(ln.x0 - 168.0)
                if dx < best_dx:
                    best_dx = dx
                    best = t
        return best or ""

    def is_blue_boundary(ln, t: str) -> bool:
        if not ln.bold or not ln.non_black or not (8 <= ln.size <= 12):
            return False
        tl = t.lower()
        return tl.startswith("staff initials") or tl.startswith("answer") or tl.startswith("comment")

    def looks_like_activity_title(t: str) -> bool:
        # Titles usually contain "#<n>" marker; keep language-agnostic by keying on "#digits".
        return bool(re.search(r"#\s*\d+\b", t))

    def is_activity_title_line(ln, t: str, body_start_y: float) -> bool:
        if ln.y0 < body_start_y:
            return False
        if not (ln.bold and (not ln.non_black) and (9 <= ln.size <= 11)):
            return False
        if not (140 <= ln.x0 <= 260):
            return False
        if is_machine_code_text(t) or is_page_furniture_text(t):
            return False
        return looks_like_activity_title(t)

    def is_question_start_line(ln, t: str, body_start_y: float) -> bool:
        if ln.y0 < body_start_y:
            return False
        if not (ln.bold and (not ln.non_black) and (9 <= ln.size <= 11)):
            return False
        if not (140 <= ln.x0 <= 260):
            return False
        if not t or is_machine_code_text(t) or is_page_furniture_text(t):
            return False
        # Avoid starting a label on pure parenthetical instruction lines.
        if t.startswith("(") and t.endswith(")"):
            return False
        if t.startswith("("):
            return False
        # Exclude header row words if present in body by chance.
        if t.lower() in ("timepoint", "activity", "line #", "line#", "line"):
            return False
        return True

    def is_question_continuation_line(ln, t: str, body_start_y: float, anchor_x: float, prev_y: float) -> bool:
        if ln.y0 < body_start_y:
            return False
        if not (ln.bold and (not ln.non_black) and (9 <= ln.size <= 11)):
            return False
        if not t or is_machine_code_text(t) or is_page_furniture_text(t):
            return False
        if abs(ln.x0 - anchor_x) > 18.0:
            return False
        # Continuations are typically close in y; allow slightly larger gaps.
        if (ln.y0 - prev_y) > 28.0:
            return False
        return True

    def finalize_label(label_lines) -> str:
        txt = norm(" ".join(label_lines))
        # Remove obvious trailing double spaces already handled; keep punctuation as printed.
        return txt

    out = []
    current_form = ""
    current_schedule = ""
    expecting_question = False

    for page_index, lines in pages:
        if not lines:
            continue
        if not is_target_layout(lines):
            continue

        body_start_y = get_body_start_y(lines)
        sched = get_schedule_name(lines)
        if sched:
            current_schedule = sched

        page_seen = set()

        collecting = False
        label_lines = []
        anchor_x = 0.0
        prev_y = -1e9

        i = 0
        while i < len(lines):
            ln = lines[i]
            t = norm(ln.text)

            # Skip obvious furniture early.
            if not t or is_page_furniture_text(t):
                i += 1
                continue

            # Detect and set new activity/form title.
            if is_activity_title_line(ln, t, body_start_y):
                # If we were collecting, finalize before switching.
                if collecting and label_lines:
                    field_name = finalize_label(label_lines)
                    form_name = current_form or current_schedule or ""
                    if field_name and form_name:
                        key = (form_name, field_name)
                        if key not in page_seen:
                            out.append({"form_name": form_name, "field_name": field_name, "page": page_index + 1})
                            page_seen.add(key)
                    collecting = False
                    label_lines = []

                current_form = t
                expecting_question = True
                collecting = False
                label_lines = []
                i += 1
                continue

            # Blue boundaries end a question/label capture.
            if collecting and is_blue_boundary(ln, t):
                field_name = finalize_label(label_lines)
                form_name = current_form or current_schedule or ""
                if field_name and form_name:
                    key = (form_name, field_name)
                    if key not in page_seen:
                        out.append({"form_name": form_name, "field_name": field_name, "page": page_index + 1})
                        page_seen.add(key)
                collecting = False
                label_lines = []
                i += 1
                continue

            # Start capturing the next question after an activity title (may be on next page).
            if (not collecting) and expecting_question and is_question_start_line(ln, t, body_start_y):
                # Do not treat an activity title as a question.
                if not looks_like_activity_title(t):
                    collecting = True
                    expecting_question = False
                    label_lines = [t]
                    anchor_x = ln.x0
                    prev_y = ln.y0
                i += 1
                continue

            # Continue capturing wrapped label/paragraph lines.
            if collecting:
                if is_machine_code_text(t):
                    i += 1
                    continue
                if is_activity_title_line(ln, t, body_start_y):
                    # handled above, but keep safe.
                    i += 1
                    continue
                if is_question_continuation_line(ln, t, body_start_y, anchor_x, prev_y):
                    label_lines.append(t)
                    prev_y = ln.y0
                i += 1
                continue

            i += 1

        # End of page: finalize if we were collecting (rare, but safe).
        if collecting and label_lines:
            field_name = finalize_label(label_lines)
            form_name = current_form or current_schedule or ""
            if field_name and form_name:
                key = (form_name, field_name)
                if key not in page_seen:
                    out.append({"form_name": form_name, "field_name": field_name, "page": page_index + 1})
                    page_seen.add(key)

    return out
```
