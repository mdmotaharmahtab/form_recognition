```python
import re
import unicodedata


def extract(pages):
    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKC", s or "")
        s = s.replace("\u00a0", " ")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def is_machine_code_text(t: str) -> bool:
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

    def is_instruction_text(t: str) -> bool:
        """
        Filters imperative/instruction-only sentences that appear in this layout
        but are not data-entry field labels.
        """
        if not t:
            return False
        tl = t.lower().strip()

        # Very specific known offender from audit.
        if "protocol deviation" in tl and "completed" in tl:
            return True

        # Common instruction preambles (kept narrow to avoid losing true labels).
        if tl.startswith("please "):
            if any(
                tl.startswith(p)
                for p in (
                    "please ensure",
                    "please complete",
                    "please confirm",
                    "please refer",
                    "please see",
                    "please indicate",
                    "please record",
                    "please provide",
                )
            ):
                return True

        return False

    def is_target_layout(lines) -> bool:
        has_annotated = False
        has_schedule = False
        has_timepoint_row = False
        for ln in lines[:60]:
            t = norm(ln.text)
            if not t:
                continue
            if t.lower() == "annotated crf" and ln.bold and ln.non_black and ln.size >= 16:
                has_annotated = True
            if "schedule category" in t.lower() and ln.bold and (not ln.non_black) and 9 <= ln.size <= 13:
                has_schedule = True
            if t.lower() == "timepoint" and ln.bold and ln.non_black and 8 <= ln.size <= 12:
                has_timepoint_row = True
        return has_annotated and has_schedule and has_timepoint_row

    def get_body_start_y(lines) -> float:
        for ln in lines[:80]:
            t = norm(ln.text)
            if t.lower() == "timepoint" and ln.bold and ln.non_black:
                return ln.y0 + 5.0
        return 120.0

    def get_schedule_name(lines) -> str:
        schedule_label_y = None
        for ln in lines[:80]:
            t = norm(ln.text)
            if t.lower().startswith("schedule category") and ln.bold and (not ln.non_black):
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
            if abs(ln.y0 - schedule_label_y) <= 2.5 and 120 <= ln.x0 <= 260 and (not ln.bold) and (not ln.non_black):
                dx = abs(ln.x0 - 168.0)
                if dx < best_dx:
                    best_dx = dx
                    best = t
        return best or ""

    def is_blue_heading_line(ln, t: str) -> bool:
        # Still treated as a boundary, but no longer emitted as a field
        # (it recurs on most pages and triggers furniture gates).
        if not (ln.bold and ln.non_black and (8 <= ln.size <= 12)):
            return False
        tl = t.lower()
        return tl.startswith("staff initials") or tl.startswith("answer") or tl.startswith("comment")

    def looks_like_activity_title(t: str) -> bool:
        if not re.search(r"#\s*\d+\b", t):
            return False
        if "?" in t:
            return False
        tl = t.lower().strip()
        for q in (
            "does ",
            "did ",
            "do ",
            "has ",
            "have ",
            "was ",
            "were ",
            "what ",
            "when ",
            "where ",
            "who ",
            "why ",
            "how ",
        ):
            if tl.startswith(q):
                return False
        return True

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

    def is_numbered_label_text(t: str) -> bool:
        tt = (t or "").strip()
        if not re.match(r"^\d{1,2}\.\s+\S", tt):
            return False
        if "?" in tt:
            return False
        if len(tt) > 220:
            return False
        return True

    def is_question_start_line(ln, t: str, body_start_y: float) -> bool:
        if ln.y0 < body_start_y:
            return False

        if not t or is_machine_code_text(t) or is_page_furniture_text(t):
            return False
        if is_instruction_text(t):
            return False
        if t.startswith("("):
            return False
        if t.lower() in ("timepoint", "activity", "line #", "line#", "line"):
            return False

        # Original strict signature (kept for existing coverage).
        if (ln.bold and (not ln.non_black) and (9 <= ln.size <= 11) and (140 <= ln.x0 <= 260)):
            return True

        # Extension: numbered labels in this family sometimes sit outside the strict x-range.
        if is_numbered_label_text(t) and (8 <= ln.size <= 12) and (60 <= ln.x0 <= 340):
            return True

        return False

    def is_question_continuation_line(ln, t: str, body_start_y: float, anchor_x: float, prev_y: float) -> bool:
        if ln.y0 < body_start_y:
            return False
        if not (ln.bold and (not ln.non_black) and (9 <= ln.size <= 11)):
            return False
        if not t or is_machine_code_text(t) or is_page_furniture_text(t):
            return False
        if is_instruction_text(t):
            return False
        if abs(ln.x0 - anchor_x) > 18.0:
            return False
        if (ln.y0 - prev_y) > 28.0:
            return False
        return True

    def sanitize_field_label(raw: str) -> str:
        """
        Removes trailing descriptive/instructional prose that is not part of the
        human field label (common in this layout family).
        """
        s = norm(raw)
        if not s:
            return ""

        # Common: numbered label + short unit window + description prose -> keep just the label.
        if re.match(r"^\d{1,2}\.\s+", s):
            m = re.match(
                r"^(\d{1,2}\.\s+[^()]{2,160}\([A-Za-z0-9 ,/\-]{1,20}\))\s+[A-Z].+$",
                s,
            )
            if m:
                return norm(m.group(1))

        # Strip trailing parenthetical instructions (keep short unit-like parentheses; never strip questions).
        while True:
            m = re.search(r"\s*\(([^()]*)\)\s*$", s)
            if not m:
                break
            inner = norm(m.group(1))
            if not inner or "?" in inner:
                break
            il = inner.lower()

            instructional = (
                len(inner) > 35
                or "must " in il
                or "must be" in il
                or "escalat" in il
                or "checked against" in il
                or il.startswith("version must")
                or il.startswith("please ")
            )
            if instructional:
                s = norm(s[: m.start()].rstrip(" -–;,:"))
                continue
            break

        # Strip trailing dash-delimited escalation/instruction text (non-question labels only).
        if "?" not in s:
            md = re.search(r"\s+[–-]\s*(escalat|refer|ensure|confirm|must)\b", s, flags=re.I)
            if md:
                s = norm(s[: md.start()].rstrip(" -–;,:"))

        # If a short label is followed by a long prose explanation, cut at the first clear prose start.
        if "?" not in s:
            mp = re.match(r"^(.{1,180}\))\s+(Subject|General)\b.*$", s)
            if mp and re.match(r"^\d{1,2}\.\s+", s):
                return norm(mp.group(1))

        return s

    def finalize_label(label_lines) -> str:
        return sanitize_field_label(" ".join(label_lines))

    def emit(out, page_seen, form_name: str, field_name: str, page_index: int):
        form_name = norm(form_name)
        field_name = sanitize_field_label(field_name)
        if not form_name or not field_name:
            return
        if is_machine_code_text(field_name) or is_page_furniture_text(field_name):
            return
        if is_instruction_text(field_name):
            return
        key = (form_name, field_name)
        if key in page_seen:
            return
        out.append({"form_name": form_name, "field_name": field_name, "page": page_index + 1})
        page_seen.add(key)

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

            if not t or is_page_furniture_text(t):
                i += 1
                continue

            # Blue headings: do NOT emit as fields (template-furniture gate),
            # but treat as boundaries so labels don't drift.
            if is_blue_heading_line(ln, t):
                if collecting and label_lines:
                    field_name = finalize_label(label_lines)
                    emit(out, page_seen, current_form or current_schedule or "", field_name, page_index)
                    collecting = False
                    label_lines = []
                i += 1
                continue

            # Detect and set new activity/form title.
            if is_activity_title_line(ln, t, body_start_y):
                if collecting and label_lines:
                    field_name = finalize_label(label_lines)
                    emit(out, page_seen, current_form or current_schedule or "", field_name, page_index)
                    collecting = False
                    label_lines = []

                current_form = t
                expecting_question = True
                collecting = False
                label_lines = []
                i += 1
                continue

            # Start capturing the next question after an activity title (may be on next page).
            if (not collecting) and expecting_question and is_question_start_line(ln, t, body_start_y):
                if not looks_like_activity_title(t):
                    collecting = True
                    expecting_question = False
                    label_lines = [t]
                    anchor_x = ln.x0
                    prev_y = ln.y0
                i += 1
                continue

            # Extension: allow extraction of numbered labels even if we didn't see an activity title.
            if (not collecting) and is_numbered_label_text(t) and is_question_start_line(ln, t, body_start_y):
                collecting = True
                expecting_question = False
                label_lines = [t]
                anchor_x = ln.x0
                prev_y = ln.y0
                i += 1
                continue

            # Continue capturing wrapped label lines.
            if collecting:
                if is_machine_code_text(t) or is_instruction_text(t):
                    i += 1
                    continue
                if is_activity_title_line(ln, t, body_start_y):
                    i += 1
                    continue
                if is_question_continuation_line(ln, t, body_start_y, anchor_x, prev_y):
                    label_lines.append(t)
                    prev_y = ln.y0
                i += 1
                continue

            i += 1

        # End of page: finalize any in-progress capture.
        if collecting and label_lines:
            field_name = finalize_label(label_lines)
            emit(out, page_seen, current_form or current_schedule or "", field_name, page_index)

    return out
```
