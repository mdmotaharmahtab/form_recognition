```python
# Observed layout: pages have a repeated header ("Annotated CRF") and a line
# "Schedule Category & Name:" followed by a value containing a human section name.
# Each data-entry field is printed as a bold black question/label line around x~168,
# followed by blue sublabels ("Answer(s):", "Comment:", "Barcode:", "Staff Initials:")
# and answer options/technical annotations (e.g., "[CODE] SAS:...") that must be ignored.
# Strategy: per page, derive form_name from the schedule name value; then scan for
# bold black label blocks at x~168, merge wrapped lines, and emit as field_name.

import re
from collections import defaultdict

def extract(pages):
    # --- helpers ---
    def norm_space(s):
        return re.sub(r"\s+", " ", s).strip()

    def is_machine_annotation(t):
        t = t.strip()
        if not t:
            return True
        # Common technical lines in annotated CRFs
        if t.startswith("[") and "]" in t and "SAS:" in t:
            return True
        if re.search(r"\bSAS:\s*\[", t):
            return True
        # Pure code-like tokens
        if re.fullmatch(r"\[[A-Z0-9_]+\]", t):
            return True
        return False

    def is_option_line(t):
        t = t.strip()
        # Radio/checkbox options often start with O / o / □ / ■ / ( ) etc.
        if re.match(r"^(?:O|o|0|•|·|□|■|\(\s*\)|\[\s*\])\s+\S", t):
            return True
        return False

    def is_placeholder_line(t):
        t = t.strip()
        if not t:
            return True
        # date/time placeholders and underscore fill lines
        if re.fullmatch(r"[_\s\-:./]+", t):
            return True
        if re.fullmatch(r"(?:dd|DD)\s*-\s*(?:MMM|mmm)\s*-\s*(?:yyyy|YYYY)", t):
            return True
        if re.fullmatch(r"(?:HH|hh)\s*:\s*(?:mm|MM)", t):
            return True
        # patterns like "_ _ - _ _ _ - _ _ _ _" or "SMP _ _ _ ..."
        if re.search(r"(?:_ ?){4,}", t):
            return True
        return False

    def is_blue_label(line):
        # In samples, blue labels are non_black True and bold, size ~10
        if not line.bold:
            return False
        if not line.non_black:
            return False
        t = line.text.strip()
        if not t:
            return False
        # Often ends with ":" but not always (e.g., "Answer(s):")
        return True

    def is_field_label_candidate(line):
        # Bold black text around x~167 is the question/label.
        if not line.bold:
            return False
        if line.non_black:
            return False
        t = line.text.strip()
        if not t:
            return False
        # Exclude obvious headers/furniture
        if t.lower() == "annotated crf":
            return False
        if t.endswith(":") and len(t) <= 40:
            # likely a blue-style label but printed black in some pages; exclude
            # (e.g., "Study, Site:" etc.)
            if re.search(r"\b(study|site|group|visit|slot|schedule|timepoint|activity|line)\b", t, re.I):
                return False
        # Exclude machine annotations/options/placeholders
        if is_machine_annotation(t) or is_option_line(t) or is_placeholder_line(t):
            return False
        # Exclude pure numbers / line numbers
        if re.fullmatch(r"\d+(?:\.\d+)?(?:\s*\(hidden\))?", t):
            return False
        # Geometry gate: main label column
        if not (140 <= line.x0 <= 220):
            return False
        # Avoid very small/large oddities
        if line.size < 8 or line.size > 14:
            return False
        return True

    def parse_schedule_name(lines):
        # Find "Schedule Category & Name:" label then take nearest right-side value line.
        label_idx = None
        for i, ln in enumerate(lines):
            if ln.bold and not ln.non_black and norm_space(ln.text).lower().startswith("schedule category"):
                label_idx = i
                break
        if label_idx is None:
            return ""
        y = lines[label_idx].y0
        candidates = []
        for ln in lines:
            if abs(ln.y0 - y) <= 2.5 and ln.x0 > lines[label_idx].x1 - 5:
                if ln is lines[label_idx]:
                    continue
                txt = norm_space(ln.text)
                if txt:
                    candidates.append((ln.x0, txt))
        if not candidates:
            # fallback: next line to the right-ish
            for j in range(label_idx + 1, min(label_idx + 6, len(lines))):
                ln = lines[j]
                if ln.x0 >= 140 and ln.y0 >= y - 1 and ln.y0 <= y + 30:
                    txt = norm_space(ln.text)
                    if txt:
                        candidates.append((ln.x0, txt))
                        break
        if not candidates:
            return ""
        candidates.sort()
        val = candidates[0][1]
        # Remove leading machine schedule code like "S_QSC302573," keep human name after comma if present
        if "," in val:
            left, right = val.split(",", 1)
            if re.fullmatch(r"[A-Z]_[A-Z0-9]+", left.strip()):
                val = right.strip()
        return val.strip()

    def merge_wrapped_labels(label_lines):
        # label_lines: list of Line objects in y order that belong to one label block
        parts = []
        for ln in label_lines:
            t = norm_space(ln.text)
            if not t:
                continue
            # avoid accidental inclusion of technical lines
            if is_machine_annotation(t) or is_option_line(t):
                continue
            parts.append(t)
        # Join with space, but avoid double spaces around hyphenation
        s = " ".join(parts)
        s = norm_space(s)
        return s

    # --- main extraction ---
    out = []
    seen = set()  # (form_name, field_name)
    current_form = ""

    for page_idx0, lines in pages:
        # Update form name from schedule name if present
        sched = parse_schedule_name(lines)
        if sched:
            current_form = sched

        # Identify label candidates and merge wrapped lines into blocks.
        # We treat consecutive bold-black label lines at x~168 with small vertical gaps as one field label.
        candidates = [ln for ln in lines if is_field_label_candidate(ln)]

        # Sort by y then x (already sorted), but ensure stable
        candidates.sort(key=lambda l: (l.y0, l.x0))

        blocks = []
        cur = []
        last_y = None
        for ln in candidates:
            if not cur:
                cur = [ln]
                last_y = ln.y0
                continue
            # same column and close vertically => wrap
            if abs(ln.x0 - cur[-1].x0) <= 8 and (ln.y0 - last_y) <= 14.5:
                cur.append(ln)
                last_y = ln.y0
            else:
                blocks.append(cur)
                cur = [ln]
                last_y = ln.y0
        if cur:
            blocks.append(cur)

        # Filter out blocks that are actually section/activity titles rather than questions?
        # In this CRF, activity titles are also bold black at x~168 but appear on the "Activity" row
        # and include a colon-separated prefix (e.g., "ECG: ... #2"). Those are not data-entry fields.
        # Heuristic: activity titles often contain " : " early and end with "#<n>" or have a line number nearby.
        # We'll exclude if it looks like an activity header (contains ":" and ends with "#digits" or has " #digits").
        def looks_like_activity_header(t):
            if ":" in t:
                if re.search(r"\s#\d+\b", t):
                    return True
                # also many activity headers have "Something: Something #n"
                if re.search(r"#\d+\s*$", t):
                    return True
            return False

        for blk in blocks:
            field = merge_wrapped_labels(blk)
            if not field:
                continue
            # Exclude activity headers
            if looks_like_activity_header(field):
                continue
            # Exclude parenthetical instruction-only lines (often follow a real label)
            if field.startswith("(") and field.endswith(")") and len(field) < 120:
                continue
            # Exclude very short generic words
            if len(field) < 3:
                continue

            form_name = current_form or ""
            key = (form_name, field)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": field, "page": page_idx0 + 1})

    return out
```