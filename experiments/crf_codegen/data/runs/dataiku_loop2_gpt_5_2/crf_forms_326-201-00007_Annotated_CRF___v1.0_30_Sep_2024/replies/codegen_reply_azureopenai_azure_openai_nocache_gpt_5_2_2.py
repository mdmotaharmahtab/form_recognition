```python
import re

def extract(pages):
    """
    Input: pages = iterable of (page_idx0, lines)
      where each line has at least:
        - text (str)
        - x0, x1, y0 (float)
        - bold (bool)
        - non_black (bool)
        - size (float)
    Output: list of dicts: {"form_name": str, "field_name": str, "page": int}
    """

    # ----------------------------
    # Helpers (mostly extending prior logic)
    # ----------------------------
    def norm(s):
        s = re.sub(r"\s+", " ", (s or "").strip())
        # normalize common unicode dashes
        s = s.replace("\u2013", "-").replace("\u2014", "-")
        return s

    def low(s):
        return (s or "").strip().lower()

    def looks_like_header_or_furniture(t):
        t0 = low(t)
        if not t0:
            return True
        if t0 == "annotated crf":
            return True
        if t0 in ("timepoint", "activity", "line #"):
            return True
        # NOTE: previously excluded Study/Site etc; now we WANT them as fields.
        if t0.startswith("schedule category & name:"):
            return True
        return False

    def is_machine_annotation(t):
        t = (t or "").strip()
        if not t:
            return True
        if t.startswith("[") and "]" in t and "SAS:" in t:
            return True
        if re.fullmatch(r"\d+(\.\d+)?(\s*\(hidden\))?", t, flags=re.I):
            return True
        return False

    def is_blue_label(line):
        return bool(getattr(line, "bold", False) and getattr(line, "non_black", False))

    def is_answer_header(line):
        if not is_blue_label(line):
            return False
        if getattr(line, "x0", 0) < 140:
            return False
        return low(line.text).startswith("answer")

    def is_left_column_field_label(line):
        # Standard left-column blue labels like "Comment:", "Barcode:", "Staff Initials:"
        if not is_blue_label(line):
            return False
        if getattr(line, "x0", 0) > 160:
            return False
        t = (line.text or "").strip()
        if not t.endswith(":"):
            return False
        # Exclude top header labels? We now INCLUDE Study/Site etc, so do not exclude them.
        if low(t) in ("timepoint", "activity", "line #"):
            return False
        if low(t).startswith("schedule category & name:"):
            return False
        return True

    def is_activity_bold_label(line):
        # Field label/question: bold black in Activity column.
        if not getattr(line, "bold", False) or getattr(line, "non_black", False):
            return False
        if getattr(line, "size", 0) < 9:
            return False
        if getattr(line, "x0", 0) < 140:
            return False
        t = (line.text or "").strip()
        if looks_like_header_or_furniture(t):
            return False
        if is_machine_annotation(t):
            return False
        # Do NOT exclude option-like lines too aggressively; prior heuristic caused misses.
        # Keep only a narrow exclusion for pure masks.
        if re.fullmatch(r"(dd\s*-\s*MMM\s*-\s*yyyy|HH:mm)", t, flags=re.I):
            return False
        return True

    def parse_form_name_from_schedule(lines):
        # Find "Schedule Category & Name:" then take nearest value line to its right on same row band.
        sched = None
        for ln in lines:
            if getattr(ln, "bold", False) and not getattr(ln, "non_black", False) and low(ln.text).startswith("schedule category"):
                sched = ln
                break
        if not sched:
            return None
        y0 = getattr(sched, "y0", 0)
        cands = []
        for ln in lines:
            if getattr(ln, "y0", 0) < y0 - 3 or getattr(ln, "y0", 0) > y0 + 6:
                continue
            if getattr(ln, "x0", 0) <= getattr(sched, "x1", 0) + 5:
                continue
            if getattr(ln, "bold", False):
                continue
            if getattr(ln, "non_black", False):
                continue
            t = (ln.text or "").strip()
            if not t:
                continue
            cands.append(ln)
        if not cands:
            return None
        cands.sort(key=lambda l: getattr(l, "x0", 0))
        val = (cands[0].text or "").strip()
        val = re.sub(r"^[A-Z]{2,}\d+\s*,\s*", "", val).strip()
        return norm(val) if val else None

    def join_multiline_activity_labels(lines, idx, x_tol=35, y_gap=16):
        """
        Join wrapped question text in Activity column.
        Fix: avoid emitting the continuation line as a separate field by joining more robustly.
        Stop when we hit blue labels (Answer(s):, Comment:, etc.) or a new bold label far away.
        """
        base = lines[idx]
        base_x = getattr(base, "x0", 0)
        parts = [norm(base.text)]
        last_y = getattr(base, "y0", 0)

        j = idx + 1
        while j < len(lines):
            ln = lines[j]
            t = norm(getattr(ln, "text", ""))
            if not t:
                j += 1
                continue

            # vertical gap too large => new block
            if getattr(ln, "y0", 0) - last_y > y_gap:
                break

            # stop at blue labels / answer header / left-column labels
            if is_blue_label(ln) or is_answer_header(ln) or is_left_column_field_label(ln):
                break

            # stop at machine annotations
            if is_machine_annotation(t):
                break

            # continuation lines are often NOT bold; allow them if they align with activity column
            # and are black (non_blue) and near same x.
            same_col = abs(getattr(ln, "x0", 0) - base_x) <= x_tol
            is_black = not getattr(ln, "non_black", False)

            # If it's a new bold black label but far x or clearly a new question, stop.
            if getattr(ln, "bold", False) and is_black and not same_col:
                break

            # Accept continuation if it's black and in same column band.
            if is_black and same_col:
                parts.append(t)
                last_y = getattr(ln, "y0", 0)
                j += 1
                continue

            # Otherwise stop (prevents swallowing unrelated text)
            break

        return norm(" ".join(parts)), j

    def is_instruction_like(field_text):
        """
        Filter out procedural instructions that are bold in Activity column but not data-entry fields.
        Target the observed false positives like:
          "Chemistry and Virology ... – Mix tube gently by inverting 5–6 times (5 mL SST)"
        """
        t = norm(field_text)
        tl = t.lower()

        # Strong instruction verbs/phrases
        instr_markers = [
            "mix tube", "invert", "gently", "times", "collect", "centrifuge", "store",
            "ship", "label the", "record on", "ensure", "do not", "must be", "within",
            "immediately", "prior to", "after dosing", "before dosing"
        ]
        if " - " in t or " – " in field_text:
            # if dash-separated and contains instruction markers, likely not a field
            if any(m in tl for m in instr_markers):
                return True

        # Pure section/procedure titles with specimen volumes often not fields
        if re.search(r"\(\s*\d+(\.\d+)?\s*mL\b", t, flags=re.I) and any(m in tl for m in instr_markers):
            return True

        return False

    def is_eligibility_criterion_like(field_text):
        """
        Exclusion/Inclusion criteria lines are often bold and look like statements, not fields.
        They were extracted incorrectly on page 39.
        """
        t = norm(field_text)
        tl = t.lower()
        if tl.startswith("exclusion ") or tl.startswith("inclusion "):
            # "Exclusion 24. ..." etc.
            if re.match(r"^(exclusion|inclusion)\s+\d+\s*[\.:]", tl):
                return True
        return False

    def is_block_title(field_text):
        # Prior heuristic: "Safety: ... #1" etc.
        t = norm(field_text)
        if re.search(r"#\s*\d+\s*$", t) and ":" in t:
            return True
        # Also common: "Affected Body System" appears as a header in some layouts; treat as non-field.
        if t.lower() in ("affected body system",):
            return True
        return False

    def add_record(out, seen, form_name, field_name, page_num):
        field_name = norm(field_name)
        form_name = norm(form_name)
        if not field_name:
            return
        key = (form_name, field_name, page_num)
        if key in seen:
            return
        seen.add(key)
        out.append({"form_name": form_name, "field_name": field_name, "page": page_num})

    # ----------------------------
    # Main extraction
    # ----------------------------
    out = []
    seen = set()
    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1

        # Update form name if present on this page
        fn = parse_form_name_from_schedule(lines)
        if fn:
            current_form = fn

        # 1) Always extract top header fields (Study, Site / Group, Visit / Slot) if present.
        # They appear as left-column labels with ":".
        for ln in lines:
            if not is_left_column_field_label(ln):
                continue
            label = norm((ln.text or "").rstrip(":"))
            # Include Study, Site / Group, Visit / Slot / Barcode / Staff Initials / Comment etc.
            add_record(out, seen, current_form, label, page_num)

        # 2) Extract Activity-column fields (questions/labels), joining wrapped lines.
        i = 0
        while i < len(lines):
            ln = lines[i]

            if is_activity_bold_label(ln):
                field, j = join_multiline_activity_labels(lines, i)

                # Filters for known non-fields
                if is_block_title(field):
                    i = j
                    continue
                if re.fullmatch(r"\(.*\)", field):
                    i = j
                    continue
                if is_instruction_like(field):
                    i = j
                    continue
                if is_eligibility_criterion_like(field):
                    i = j
                    continue

                add_record(out, seen, current_form, field, page_num)
                i = j
                continue

            i += 1

    return out
```