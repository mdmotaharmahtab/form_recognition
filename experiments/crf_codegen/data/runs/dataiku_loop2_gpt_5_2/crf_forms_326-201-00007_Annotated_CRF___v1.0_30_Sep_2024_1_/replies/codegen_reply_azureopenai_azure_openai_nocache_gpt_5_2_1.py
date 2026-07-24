```python
# Observed layout: pages have a repeated header ("Annotated CRF") and a line
# "Schedule Category & Name:" followed by the schedule/form name value at x~168.
# Each data-entry block begins with a bold "Activity" line at x~168 (often with
# a prefix like "Section: ... #n"), followed by one or more bold question/label
# lines at the same x. Blue labels ("Staff Initials:", "Answer(s):", "Comment:")
# and answer options ("O ...") are not fields. Strategy: keep current form_name
# from the schedule name line; then extract bold label lines in the activity
# column, excluding headers, codes, options, and furniture.

import re
from collections import defaultdict

def extract(pages):
    # --- helpers ---
    def norm_space(s):
        return re.sub(r"\s+", " ", s).strip()

    def is_machine_code_line(t):
        # e.g. "[QSORRES] SAS:[Name=..., Length=..., DataType=...]"
        return bool(re.match(r"^\s*\[[A-Z0-9_]+\]\s+SAS:\[", t))

    def is_option_line(t):
        # radio/checkbox options like "O Yes", "O 0 - ...", etc.
        return bool(re.match(r"^\s*[Oo]\s+\S", t))

    def is_fill_line(t):
        # underscores / blanks / placeholder patterns
        if re.fullmatch(r"[_\s]+", t):
            return True
        if re.search(r"_{3,}", t):
            return True
        # date/time placeholders
        if re.fullmatch(r"(dd\s*-\s*MMM\s*-\s*yyyy|HH:mm|mm:ss|yyyy\s*-\s*mm\s*-\s*dd)", t, flags=re.I):
            return True
        return False

    def is_header_or_furniture(t):
        tt = t.strip()
        if not tt:
            return True
        # top title
        if tt.lower() == "annotated crf":
            return True
        # column headers
        if tt.lower() in ("timepoint", "activity", "line #", "line#", "line"):
            return True
        # left-side blue labels (not fields)
        if re.fullmatch(r"(Staff Initials:|Answer\(s\):|Comment:)", tt, flags=re.I):
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

    def clean_activity_prefix(t):
        # Remove trailing instance markers like "#1", "#3" at end
        t = re.sub(r"\s+#\s*\d+\s*$", "", t).strip()
        # Remove trailing "(hidden)" if present
        t = re.sub(r"\s*\(hidden\)\s*$", "", t).strip()
        return t

    def looks_like_field_label(t):
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
        for ln in lines:
            if cur_y is None or abs(ln.y0 - cur_y) <= y_tol:
                cur.append(ln)
                if cur_y is None:
                    cur_y = ln.y0
                else:
                    cur_y = (cur_y * (len(cur)-1) + ln.y0) / len(cur)
            else:
                rows.append(cur)
                cur = [ln]
                cur_y = ln.y0
        if cur:
            rows.append(cur)
        return rows

    def row_text_in_xrange(row, x0, x1):
        parts = [ln for ln in row if ln.x0 >= x0 and ln.x0 <= x1]
        parts.sort(key=lambda l: l.x0)
        return norm_space(" ".join(p.text for p in parts if p.text.strip()))

    # --- main extraction ---
    out = []
    seen = set()  # (form_name, field_name, page)
    current_form = ""

    # constants from observed geometry
    ACT_X_MIN = 150.0  # activity column starts around 167.7
    ACT_X_MAX = 470.0
    SCHED_LABEL_X_MAX = 120.0  # "Schedule Category & Name:" at x~30
    SCHED_VALUE_X_MIN = 140.0  # value at x~167.7

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

        # Extract bold label lines in activity column, excluding options/codes/etc.
        # Also merge multi-line bold labels that wrap (same x region, consecutive rows).
        # Build a list of candidate lines in reading order (by y then x).
        candidates = []
        for ln in lines:
            t = ln.text.strip()
            if not t:
                continue
            if ln.x0 < ACT_X_MIN or ln.x0 > ACT_X_MAX:
                continue
            if not ln.bold:
                continue
            if is_header_or_furniture(t):
                continue
            if is_machine_code_line(t):
                continue
            # activity header lines are also bold; keep them as potential fields too
            # but we'll later avoid duplicates by preferring the more specific question line.
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
            y1 = base.y1
            j = i + 1
            while j < len(candidates):
                nxt = candidates[j]
                # next line is a wrap if close vertically and aligned in activity column
                if (nxt.y0 - y0) <= 14.5 and abs(nxt.x0 - x0) <= 5.0:
                    # stop merging if next looks like a new block title with colon+number pattern?
                    # (still safe to merge; but avoid merging across big gaps)
                    text = norm_space(text + " " + nxt.text.strip())
                    y0 = nxt.y0
                    y1 = nxt.y1
                    j += 1
                else:
                    break
            merged.append((base, text))
            i = j

        # Filter merged texts to field labels:
        # - Exclude block titles that contain ":" and a trailing "#n" only if a more specific
        #   label follows soon; but since we only need field labels/questions, we keep the
        #   actual question lines (often without the section prefix).
        # We'll implement: if a merged bold line contains ":" and also a ". " number pattern
        # (e.g., "C-SSRS ...: 19. ..."), treat it as a block title, not a field.
        # Otherwise, treat as field label.
        field_texts = []
        for base, txt in merged:
            t = norm_space(txt)
            if not looks_like_field_label(t):
                continue
            # exclude obvious block titles with section prefix and item number
            if re.search(r":\s*\d+\.\s", t):
                continue
            # exclude titles that end with "#n" after cleaning (we'll clean anyway)
            t2 = clean_activity_prefix(t)
            if not looks_like_field_label(t2):
                continue
            field_texts.append((base, t2))

        # De-duplicate within page by text
        seen_text = set()
        for base, ft in field_texts:
            if ft in seen_text:
                continue
            seen_text.add(ft)
            rec = (current_form, ft, page_num)
            if rec in seen:
                continue
            seen.add(rec)
            out.append({"form_name": current_form, "field_name": ft, "page": page_num})

    return out
```