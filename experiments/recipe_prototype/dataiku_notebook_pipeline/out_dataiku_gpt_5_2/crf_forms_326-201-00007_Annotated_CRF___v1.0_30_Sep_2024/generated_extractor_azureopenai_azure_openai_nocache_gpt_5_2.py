# Observed layout: each page has a repeated header ("Annotated CRF") and a line
# "Schedule Category & Name:" followed by the current form/section name/value.
# Data-entry fields are presented as repeated blocks where the field label is a
# bold black line in the Activity column (x≈168), followed by blue labels like
# "Answer(s):", "Comment:", "Barcode:", "Staff Initials:" etc.
# Strategy: track form_name from the Schedule Category & Name value; then, per page,
# extract each bold Activity-column label as a field, plus standard blue left-column
# fields (Comment/Barcode/Staff Initials) when they appear; ignore answer options
# and machine annotations (e.g., [CODE] SAS:...).

import re
from collections import defaultdict

def extract(pages):
    # --- helpers ---
    def norm(s):
        s = re.sub(r"\s+", " ", (s or "").strip())
        return s

    def is_machine_annotation(t):
        t = t.strip()
        if not t:
            return True
        # Typical machine code lines: "[XXXX] SAS:[Name=..., Length=..., DataType=...]"
        if t.startswith("[") and "]" in t and "SAS:" in t:
            return True
        # Line numbers / hidden markers
        if re.fullmatch(r"\d+(\.\d+)?(\s*\(hidden\))?", t, flags=re.I):
            return True
        return False

    def is_option_line(t):
        # Choice options are not fields; they often start with "O " (radio) or similar.
        t = t.strip()
        if re.match(r"^[Oo]\s+", t):
            return True
        # Sometimes options are just underscores or date/time masks; treat as non-fields.
        if re.fullmatch(r"[_\s\-:./()A-Za-z0-9]+", t) and "_" in t and len(t) <= 40:
            return True
        return False

    def looks_like_header_or_furniture(t):
        t = t.strip()
        if not t:
            return True
        if t.lower() == "annotated crf":
            return True
        if t.endswith(":") and t.lower() in ("study, site:", "group, visit:", "slot:", "schedule category & name:"):
            return True
        if t.lower() in ("timepoint", "activity", "line #"):
            return True
        return False

    def is_blue_label(line):
        # In samples, blue labels are non-black and bold.
        return bool(line.bold and line.non_black)

    def is_activity_bold_label(line):
        # Field label/question: bold black in Activity column.
        if not line.bold or line.non_black:
            return False
        if line.size < 9:
            return False
        # Activity column starts around x=167.7 in samples; allow tolerance.
        if line.x0 < 140:
            return False
        # Exclude obvious headers/furniture
        t = line.text.strip()
        if looks_like_header_or_furniture(t):
            return False
        # Exclude machine annotations and option lines
        if is_machine_annotation(t) or is_option_line(t):
            return False
        # Exclude pure date/time masks that appear in left column; but activity labels can be short.
        if re.fullmatch(r"(dd\s*-\s*MMM\s*-\s*yyyy|HH:mm)", t, flags=re.I):
            return False
        return True

    def is_left_column_field_label(line):
        # Standard left-column blue labels like "Comment:", "Barcode:", "Staff Initials:"
        if not is_blue_label(line):
            return False
        if line.x0 > 140:
            return False
        t = line.text.strip()
        if not t.endswith(":"):
            return False
        # Exclude header labels at top
        if t.lower() in ("study, site:", "group, visit:", "slot:", "schedule category & name:"):
            return False
        if t.lower() in ("timepoint", "activity", "line #"):
            return False
        return True

    def is_answer_header(line):
        # "Answer(s):" appears in blue in Activity column; not a field itself.
        if not is_blue_label(line):
            return False
        if line.x0 < 140:
            return False
        return line.text.strip().lower().startswith("answer")

    def join_multiline_activity_labels(lines, idx, x_tol=25, y_gap=14):
        """
        Some questions wrap across multiple bold lines in Activity column.
        Join consecutive bold black lines with similar x and small y gap,
        stopping at blue labels or non-bold lines.
        """
        base = lines[idx]
        parts = [base.text.strip()]
        last = base
        j = idx + 1
        while j < len(lines):
            ln = lines[j]
            if ln.y0 - last.y0 > y_gap:
                break
            if is_answer_header(ln) or is_left_column_field_label(ln) or is_blue_label(ln):
                break
            if not ln.bold or ln.non_black:
                break
            if abs(ln.x0 - base.x0) > x_tol:
                break
            t = ln.text.strip()
            if not t or is_machine_annotation(t) or is_option_line(t):
                break
            # Avoid joining section titles like "Safety: ... #1" with the actual question below:
            # those titles are bold too, but they are separated by timepoint lines; still, keep join conservative.
            parts.append(t)
            last = ln
            j += 1
        return norm(" ".join(parts)), j

    def parse_form_name_from_schedule(lines):
        # Find "Schedule Category & Name:" (bold) then take nearest value line to its right on same row band.
        sched = None
        for ln in lines:
            if ln.bold and not ln.non_black and ln.text.strip().lower().startswith("schedule category"):
                sched = ln
                break
        if not sched:
            return None
        y0 = sched.y0
        # Candidate value lines: non-bold black around same y, to the right.
        cands = []
        for ln in lines:
            if ln.y0 < y0 - 3 or ln.y0 > y0 + 6:
                continue
            if ln.x0 <= sched.x1 + 5:
                continue
            if ln.bold:
                continue
            if ln.non_black:
                continue
            t = ln.text.strip()
            if not t:
                continue
            cands.append(ln)
        if not cands:
            return None
        # Choose leftmost candidate to the right (closest)
        cands.sort(key=lambda l: l.x0)
        val = cands[0].text.strip()
        # Remove leading schedule code like "QSC302573," if present.
        val = re.sub(r"^[A-Z]{2,}\d+\s*,\s*", "", val).strip()
        return norm(val) if val else None

    # --- main extraction ---
    out = []
    seen = set()  # (form_name, field_name, page)
    current_form = ""

    for page_idx0, lines in pages:
        # Update form name if present on this page
        fn = parse_form_name_from_schedule(lines)
        if fn:
            current_form = fn

        # Extract fields
        i = 0
        while i < len(lines):
            ln = lines[i]
            t = ln.text.strip()

            # Left-column standard fields (Comment/Barcode/Staff Initials/etc.)
            if is_left_column_field_label(ln):
                field = norm(t.rstrip(":"))
                if field and not looks_like_header_or_furniture(t):
                    key = (current_form, field, page_idx0 + 1)
                    if key not in seen:
                        seen.add(key)
                        out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})
                i += 1
                continue

            # Activity-column bold question/label fields
            if is_activity_bold_label(ln):
                field, j = join_multiline_activity_labels(lines, i)
                # Filter out block titles that look like "Section: Something #1" (often not a data-entry field)
                # Heuristic: if it contains ":" and ends with "#<n>" it's likely a block title.
                if re.search(r"#\s*\d+\s*$", field) and ":" in field:
                    i = j
                    continue
                # Also exclude parenthetical-only instruction lines
                if re.fullmatch(r"\(.*\)", field):
                    i = j
                    continue
                key = (current_form, field, page_idx0 + 1)
                if field and key not in seen:
                    seen.add(key)
                    out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})
                i = j
                continue

            i += 1

    return out
