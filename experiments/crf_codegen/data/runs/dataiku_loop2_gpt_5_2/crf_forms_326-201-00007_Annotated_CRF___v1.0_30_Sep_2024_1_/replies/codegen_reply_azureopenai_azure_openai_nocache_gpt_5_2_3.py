```python
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

    def safe_text(ln) -> str:
        return norm_space(getattr(ln, "text", "") or "")

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
        low = tt.lower()
        if low == "annotated crf":
            return True
        if low in ("timepoint", "activity", "line #", "line#", "line"):
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
        parts = [ln for ln in row if ln.x0 >= x0 and ln.x0 <= x1 and getattr(ln, "text", None) and ln.text.strip()]
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
            if re.search(r"\b(if|record|specify|describe|date|time|units|must|ensure|checked|check)\b", tt, flags=re.I):
                return False
            # If it contains parentheses, often a field label with guidance; keep it.
            if "(" in tt and ")" in tt:
                return False
            return True
        return False

    def is_vitals_component_label(t: str) -> bool:
        tt = norm_space(t).lower()
        return tt in {
            "qtc", "qtcf",
            "systolic", "diastolic",
            "heart rate", "respiratory rate",
            "oral temperature - degrees celsius",
            "oral temperature - degrees c",
            "oral temperature",
        }

    def canon_vitals(t: str) -> str:
        low = norm_space(t).lower()
        if low == "qtcf":
            return "QTcF"
        if low == "qtc":
            return "QTc"
        if low == "heart rate":
            return "Heart Rate"
        if low == "respiratory rate":
            return "Respiratory Rate"
        if low == "systolic":
            return "Systolic"
        if low == "diastolic":
            return "Diastolic"
        if low.startswith("oral temperature"):
            return "Oral Temperature - Degrees Celsius"
        return norm_space(t)

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

    def merge_wrapped_lines(lines, y_gap=14.5, x_tol=6.0):
        """
        Merge consecutive lines that are likely wrapped text:
        close in y and aligned in x.
        Input lines should already be filtered to a region and sorted by (y0,x0).
        Returns list of tuples: (base_line, merged_text)
        """
        lines = sorted(lines, key=lambda l: (l.y0, l.x0))
        merged = []
        i = 0
        while i < len(lines):
            base = lines[i]
            text = safe_text(base)
            x0 = base.x0
            y0 = base.y0
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if (nxt.y0 - y0) <= y_gap and abs(nxt.x0 - x0) <= x_tol:
                    text = norm_space(text + " " + safe_text(nxt))
                    y0 = nxt.y0
                    j += 1
                else:
                    break
            merged.append((base, text))
            i = j
        return merged

    def is_probable_field_text(t: str) -> bool:
        """
        A slightly more permissive field detector than looks_like_field_label(),
        used for non-bold extraction in the activity column.
        """
        tt = norm_space(t)
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
        if is_answer_label(tt):
            return False
        # avoid pure punctuation / very short tokens
        if len(re.sub(r"[\W_]+", "", tt)) < 2:
            return False
        if re.fullmatch(r"[\d\W]+", tt):
            return False
        # exclude obvious section headers
        if is_section_header_like(tt):
            return False
        # exclude "X: 1. ..." style block titles
        if re.search(r":\s*\d+\.\s", tt):
            return False
        return True

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
    BLUE_X_MAX = 175.0  # slightly widened to avoid missing on some pages

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
        for ln in lines:
            t = safe_text(ln)
            if not t:
                continue
            if is_staff_or_comment_label(t):
                add_record(out, seen, current_form, t, page_num)

        # 2) Extract vitals component labels even if not bold (page 247 issue).
        #    Restrict to activity-ish region to avoid picking up unrelated occurrences.
        for ln in lines:
            t = safe_text(ln)
            if not t:
                continue
            if ln.x0 < ACT_X_MIN or ln.x0 > 600:
                continue
            if is_vitals_component_label(t):
                add_record(out, seen, current_form, canon_vitals(t), page_num)

        # 3) Existing bold-label extraction in activity column
        candidates = []
        for ln in lines:
            t = getattr(ln, "text", "") or ""
            if not t.strip():
                continue
            if ln.x0 < ACT_X_MIN or ln.x0 > ACT_X_MAX:
                continue
            if not getattr(ln, "bold", False):
                continue
            if is_header_or_furniture(t):
                continue
            if is_machine_code_line(t):
                continue
            candidates.append(ln)

        merged = merge_wrapped_lines(candidates, y_gap=14.5, x_tol=6.0)

        field_texts = []
        for base, txt in merged:
            t = norm_space(txt)
            if not t:
                continue

            if is_answer_label(t):
                continue

            if is_staff_or_comment_label(t):
                field_texts.append((base, t))
                continue

            if not looks_like_field_label(t):
                continue

            if re.search(r":\s*\d+\.\s", t):
                continue

            if is_section_header_like(t):
                continue

            t2 = clean_activity_prefix(t)
            if not looks_like_field_label(t2):
                continue
            if is_section_header_like(t2):
                continue

            field_texts.append((base, t2))

        seen_text = set()
        for base, ft in field_texts:
            if ft in seen_text:
                continue
            seen_text.add(ft)
            add_record(out, seen, current_form, ft, page_num)

        # 4) Additional pass (EXTENSION): non-bold field labels in activity column.
        #    Fixes pages where questions/labels are not bold (e.g., page 3, 122, 247).
        #    We keep this conservative to avoid pulling section headers.
        nonbold_candidates = []
        for ln in lines:
            t = safe_text(ln)
            if not t:
                continue
            if ln.x0 < ACT_X_MIN or ln.x0 > ACT_X_MAX:
                continue
            if getattr(ln, "bold", False):
                continue
            if is_header_or_furniture(t):
                continue
            if is_machine_code_line(t):
                continue
            # Avoid picking up the schedule header value itself if it falls in range
            if re.search(r"Schedule Category\s*&\s*Name:", t, flags=re.I):
                continue
            nonbold_candidates.append(ln)

        merged_nb = merge_wrapped_lines(nonbold_candidates, y_gap=14.5, x_tol=8.0)

        for base, txt in merged_nb:
            t = clean_activity_prefix(norm_space(txt))
            if not is_probable_field_text(t):
                continue

            # Explicitly exclude known non-field headers that were leaking:
            # - "Admission Restrictions: ICF Version/Date"
            # - "Vital Signs (Supine for at least 3 minutes)"
            low = t.lower()
            if low.startswith("admission restrictions:"):
                continue
            if low.startswith("vital signs (") and low.endswith(")"):
                continue

            add_record(out, seen, current_form, t, page_num)

        # 5) Additional pass (EXTENSION): left-column labels that are true fields but not bold.
        #    Staff/Comment already handled; this targets items like "Vital Signs" (as a field)
        #    and other left-side prompts that are data-entry fields.
        left_candidates = []
        for ln in lines:
            t = safe_text(ln)
            if not t:
                continue
            if ln.x0 < BLUE_X_MIN or ln.x0 > BLUE_X_MAX:
                continue
            if is_staff_or_comment_label(t) or is_answer_label(t):
                continue
            if is_header_or_furniture(t):
                continue
            if is_machine_code_line(t):
                continue
            if is_option_line(t) or is_fill_line(t):
                continue
            # Exclude schedule furniture labels
            if re.fullmatch(r"(Study,\s*Site:|Group,\s*Visit:|Slot:|Schedule Category\s*&\s*Name:)", t, flags=re.I):
                continue
            left_candidates.append(ln)

        merged_left = merge_wrapped_lines(left_candidates, y_gap=14.5, x_tol=10.0)
        for base, txt in merged_left:
            t = clean_activity_prefix(norm_space(txt))
            if not is_probable_field_text(t):
                continue

            # Avoid section headers in left column too
            if is_section_header_like(t):
                continue

            # Keep "Vital Signs" as a field (page 247 missing), but exclude the parenthetical header variant
            low = t.lower()
            if low.startswith("vital signs (") and low.endswith(")"):
                continue

            add_record(out, seen, current_form, t, page_num)

    return out
```