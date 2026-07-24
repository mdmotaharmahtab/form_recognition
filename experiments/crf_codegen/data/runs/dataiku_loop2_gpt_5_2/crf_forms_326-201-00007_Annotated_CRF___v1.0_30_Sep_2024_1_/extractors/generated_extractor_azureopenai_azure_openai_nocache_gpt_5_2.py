import re
from collections import defaultdict

def extract(pages):
    """
    Input: pages = iterable of (page_idx0, lines)
      where each line has at least: text, x0, y0, y1, bold (bool), color (optional)
    Output: list of dicts: {"form_name": str, "field_name": str, "page": int}
    """

    # ----------------------------
    # Helpers
    # ----------------------------
    def norm_space(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip()

    def is_machine_code_line(t: str) -> bool:
        # e.g. "[QSORRES] SAS:[Name=..., Length=..., DataType=...]"
        return bool(re.match(r"^\s*\[[A-Z0-9_]+\]\s+SAS:\[", t))

    def is_option_line(t: str) -> bool:
        # radio/checkbox options like "O Yes", "O 0 - ...", etc.
        return bool(re.match(r"^\s*[Oo]\s+\S", t))

    def is_fill_line(t: str) -> bool:
        tt = t.strip()
        if not tt:
            return True
        if re.fullmatch(r"[_\s]+", tt):
            return True
        if re.search(r"_{3,}", tt):
            return True
        # date/time placeholders
        if re.fullmatch(r"(dd\s*-\s*MMM\s*-\s*yyyy|HH:mm|mm:ss|yyyy\s*-\s*mm\s*-\s*dd)", tt, flags=re.I):
            return True
        return False

    def is_header_or_furniture(t: str) -> bool:
        tt = t.strip()
        if not tt:
            return True
        if tt.lower() == "annotated crf":
            return True
        if tt.lower() in ("timepoint", "activity", "line #", "line#", "line"):
            return True
        # study/site/group/slot labels
        if re.fullmatch(r"(Study,\s*Site:|Group,\s*Visit:|Slot:|Schedule Category\s*&\s*Name:)", tt, flags=re.I):
            return True
        # timepoint content like "Day 0 (0), -00:00.00"
        if re.match(r"^\s*Day\s+\d+", tt, flags=re.I):
            return True
        # line number values like "198.0 (hidden)" or "1.0"
        if re.fullmatch(r"\d+(\.\d+)?(\s*\(hidden\))?", tt, flags=re.I):
            return True
        return False

    def clean_activity_prefix(t: str) -> str:
        # Remove trailing instance markers like "#1", "#3" at end
        t = re.sub(r"\s+#\s*\d+\s*$", "", t).strip()
        # Remove trailing "(hidden)" if present
        t = re.sub(r"\s*\(hidden\)\s*$", "", t).strip()
        return t

    def looks_like_field_label(t: str) -> bool:
        tt = t.strip()
        if not tt:
            return False
        if is_header_or_furniture(tt):
            return False
        if is_machine_code_line(tt):
            return False
        if is_option_line(tt):
            return False
        if is_fill_line(tt):
            return False
        # avoid pure punctuation / very short tokens
        if len(re.sub(r"[\W_]+", "", tt)) < 2:
            return False
        # avoid lines that are mostly numeric
        if re.fullmatch(r"[\d\W]+", tt):
            return False
        return True

    def cluster_lines_by_y(lines, y_tol=2.0):
        # returns list of rows; each row is list of lines with similar y0
        rows = []
        cur = []
        cur_y = None
        for ln in sorted(lines, key=lambda l: (l.y0, l.x0)):
            if cur_y is None or abs(ln.y0 - cur_y) <= y_tol:
                cur.append(ln)
                if cur_y is None:
                    cur_y = ln.y0
                else:
                    cur_y = (cur_y * (len(cur) - 1) + ln.y0) / len(cur)
            else:
                rows.append(cur)
                cur = [ln]
                cur_y = ln.y0
        if cur:
            rows.append(cur)
        return rows

    def row_text_in_xrange(row, x0, x1):
        parts = [ln for ln in row if ln.x0 >= x0 and ln.x0 <= x1 and ln.text and ln.text.strip()]
        parts.sort(key=lambda l: l.x0)
        return norm_space(" ".join(p.text for p in parts))

    def is_staff_or_comment_label(t: str) -> bool:
        # These MUST be extracted as fields per audit.
        tt = norm_space(t)
        return bool(re.fullmatch(r"(Staff Initials:|Comment:)", tt, flags=re.I))

    def is_answer_label(t: str) -> bool:
        # Still not a field
        tt = norm_space(t)
        return bool(re.fullmatch(r"Answer\(s\):", tt, flags=re.I))

    def is_section_header_like(t: str) -> bool:
        """
        Exclude non-data-entry "section headers" like:
          "Admission Restrictions: Photo ID"
          "Vital Signs: Vital Signs Supine Full Set"
          "Prompts: PD Prompt"
        But do NOT exclude true fields that contain ':' (e.g., "Signed ICF Version / Date ...")
        Heuristic: header-like if it is short, has a single colon early, and no question mark,
        and doesn't look like an instruction with parentheses, and isn't Staff/Comment.
        """
        tt = norm_space(t)
        if not tt or is_staff_or_comment_label(tt):
            return False
        if "?" in tt:
            return False
        if is_answer_label(tt):
            return True
        # If it matches "X: Y" and is relatively short, treat as header.
        if re.match(r"^[^:]{2,40}:\s+.{2,80}$", tt):
            # If it ends with a period, more likely a sentence/field; keep it.
            if tt.endswith("."):
                return False
            # If it contains typical instruction markers, keep it as field.
            if re.search(r"\b(if|record|specify|describe|date|time|units)\b", tt, flags=re.I):
                return False
            # If it contains parentheses, often a field label with guidance; keep it.
            if "(" in tt and ")" in tt:
                return False
            # Otherwise likely a section header.
            return True
        return False

    def is_vitals_component_label(t: str) -> bool:
        tt = norm_space(t).lower()
        return tt in {
            "qtc", "qtcf",
            "systolic", "diastolic",
            "heart rate", "respiratory rate",
            "oral temperature - degrees celsius",
            "oral temperature - degrees c",  # tolerate truncation
            "oral temperature",
        }

    def add_record(out, seen, form_name, field_name, page_num):
        fn = norm_space(form_name)
        fld = norm_space(field_name)
        if not fld:
            return
        key = (fn, fld, page_num)
        if key in seen:
            return
        seen.add(key)
        out.append({"form_name": fn, "field_name": fld, "page": page_num})

    # ----------------------------
    # Main extraction
    # ----------------------------
    out = []
    seen = set()
    current_form = ""

    # constants from observed geometry
    ACT_X_MIN = 150.0  # activity column starts around 167.7
    ACT_X_MAX = 470.0
    SCHED_LABEL_X_MAX = 120.0  # "Schedule Category & Name:" at x~30
    SCHED_VALUE_X_MIN = 140.0  # value at x~167.7

    # Blue label column (Staff Initials / Answer(s) / Comment) tends to be left of activity
    BLUE_X_MIN = 0.0
    BLUE_X_MAX = 155.0

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1

        # Update form_name from "Schedule Category & Name:" row if present
        rows = cluster_lines_by_y(lines, y_tol=2.0)
        for row in rows:
            left = row_text_in_xrange(row, 0, SCHED_LABEL_X_MAX)
            if re.search(r"Schedule Category\s*&\s*Name:", left, flags=re.I):
                val = row_text_in_xrange(row, SCHED_VALUE_X_MIN, 600)
                val = norm_space(val)
                if val:
                    current_form = val
                break

        # 1) Always extract Staff Initials: and Comment: wherever they appear
        #    (audit requires these; previously excluded as furniture).
        for ln in lines:
            t = norm_space(ln.text)
            if not t:
                continue
            if is_staff_or_comment_label(t):
                add_record(out, seen, current_form, t, page_num)

        # 2) Extract vitals component labels even if not bold (page 247 issue).
        #    Restrict to activity-ish region to avoid picking up unrelated occurrences.
        for ln in lines:
            t = norm_space(ln.text)
            if not t:
                continue
            if ln.x0 < ACT_X_MIN or ln.x0 > 600:
                continue
            if is_vitals_component_label(t):
                # Normalize capitalization to match audit expectations
                # (keep original if it already matches; else title-case special cases)
                canon = t
                low = t.lower()
                if low == "qtcf":
                    canon = "QTcF"
                elif low == "qtc":
                    canon = "QTc"
                elif low == "heart rate":
                    canon = "Heart Rate"
                elif low == "respiratory rate":
                    canon = "Respiratory Rate"
                elif low == "systolic":
                    canon = "Systolic"
                elif low == "diastolic":
                    canon = "Diastolic"
                elif low.startswith("oral temperature"):
                    canon = "Oral Temperature - Degrees Celsius"
                add_record(out, seen, current_form, canon, page_num)

        # 3) Existing bold-label extraction in activity column, extended with:
        #    - do NOT exclude Staff/Comment (already handled, but safe)
        #    - exclude section headers like "Admission Restrictions: Photo ID"
        #    - keep coverage for question labels etc.
        candidates = []
        for ln in lines:
            t = ln.text.strip() if ln.text else ""
            if not t:
                continue
            if ln.x0 < ACT_X_MIN or ln.x0 > ACT_X_MAX:
                continue
            if not getattr(ln, "bold", False):
                continue
            if is_header_or_furniture(t):
                continue
            if is_machine_code_line(t):
                continue
            # keep; filtering later
            candidates.append(ln)

        # Merge wrapped bold lines: consecutive candidates close in y and similar x0
        candidates.sort(key=lambda l: (l.y0, l.x0))
        merged = []
        i = 0
        while i < len(candidates):
            base = candidates[i]
            text = base.text.strip()
            x0 = base.x0
            y0 = base.y0
            j = i + 1
            while j < len(candidates):
                nxt = candidates[j]
                # wrap if close vertically and aligned
                if (nxt.y0 - y0) <= 14.5 and abs(nxt.x0 - x0) <= 5.0:
                    text = norm_space(text + " " + nxt.text.strip())
                    y0 = nxt.y0
                    j += 1
                else:
                    break
            merged.append((base, text))
            i = j

        field_texts = []
        for base, txt in merged:
            t = norm_space(txt)
            if not t:
                continue

            # Explicitly ignore Answer(s): (not a field)
            if is_answer_label(t):
                continue

            # Keep Staff/Comment if they appear bold in activity column (rare)
            if is_staff_or_comment_label(t):
                field_texts.append((base, t))
                continue

            if not looks_like_field_label(t):
                continue

            # Exclude obvious block titles with section prefix and item number
            if re.search(r":\s*\d+\.\s", t):
                continue

            # Exclude section headers like "Admission Restrictions: Photo ID"
            if is_section_header_like(t):
                continue

            t2 = clean_activity_prefix(t)
            if not looks_like_field_label(t2):
                continue
            if is_section_header_like(t2):
                continue

            field_texts.append((base, t2))

        # De-duplicate within page by text
        seen_text = set()
        for base, ft in field_texts:
            if ft in seen_text:
                continue
            seen_text.add(ft)
            add_record(out, seen, current_form, ft, page_num)

        # 4) Additional pass: sometimes "Comment:" appears only in left/blue column and not bold.
        #    Already handled globally above, but ensure we catch split tokens like "Comment" ":".
        #    We'll scan rows in left column and reconstruct.
        for row in rows:
            left_txt = row_text_in_xrange(row, BLUE_X_MIN, BLUE_X_MAX)
            if not left_txt:
                continue
            # Normalize common split patterns
            left_txt_n = norm_space(left_txt.replace("Comment :", "Comment:").replace("Staff Initials :", "Staff Initials:"))
            if is_staff_or_comment_label(left_txt_n):
                add_record(out, seen, current_form, left_txt_n, page_num)

    return out
