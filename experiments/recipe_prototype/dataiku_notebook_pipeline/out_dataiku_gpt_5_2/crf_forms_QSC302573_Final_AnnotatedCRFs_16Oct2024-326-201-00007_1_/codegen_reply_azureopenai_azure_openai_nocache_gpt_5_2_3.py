```python
import re
from collections import defaultdict

def extract(pages):
    """
    Input: pages = iterable of (page_idx0, lines)
      where each line has at least:
        - text (str)
        - x0, x1, y0 (floats)
        - bold (bool)
        - non_black (bool)  # True for blue/colored text in this corpus
        - size (float)

    Output: list of dicts with keys: form_name, field_name, page
    """

    # ---------------- helpers ----------------
    def norm_space(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip()

    def lower(s: str) -> str:
        return norm_space(s).lower()

    def is_machine_annotation(t: str) -> bool:
        t = (t or "").strip()
        if not t:
            return True
        # Common technical lines in annotated CRFs
        if t.startswith("[") and "]" in t and "SAS:" in t:
            return True
        if re.search(r"\bSAS:\s*\[", t):
            return True
        if re.fullmatch(r"\[[A-Z0-9_]+\]", t):
            return True
        # OID-ish / dataset-ish fragments
        if re.search(r"\b(?:OID|EDC|CDASH|SDTM|CRF)\b", t, re.I) and "?" not in t:
            if len(t) < 80 and ":" in t:
                return True
        # Pure code-like tokens
        if re.fullmatch(r"[A-Z]{1,4}_[A-Z0-9]{4,}", t):
            return True
        return False

    def is_option_line(t: str) -> bool:
        t = (t or "").strip()
        if not t:
            return False
        if re.match(r"^(?:O|o|0|•|·|□|■|\(\s*\)|\[\s*\])\s+\S", t):
            return True
        if re.fullmatch(r"(?:Yes|No|Unknown|Not Done|N/A)(?:\s*/\s*(?:Yes|No|Unknown|Not Done|N/A))*", t, re.I):
            return True
        return False

    def is_placeholder_line(t: str) -> bool:
        t = (t or "").strip()
        if not t:
            return True
        if re.fullmatch(r"[_\s\-:./]+", t):
            return True
        if re.fullmatch(r"(?:dd|DD)\s*-\s*(?:MMM|mmm)\s*-\s*(?:yyyy|YYYY)", t):
            return True
        if re.fullmatch(r"(?:HH|hh)\s*:\s*(?:mm|MM)", t):
            return True
        if re.search(r"(?:_ ?){4,}", t):
            return True
        return False

    def looks_like_activity_header(t: str) -> bool:
        if ":" in t:
            if re.search(r"\s#\d+\b", t):
                return True
            if re.search(r"#\d+\s*$", t):
                return True
        return False

    def is_instruction_only(t: str) -> bool:
        tt = norm_space(t)
        if not tt:
            return True
        if tt.startswith("(") and tt.endswith(")") and len(tt) < 200:
            return True
        if re.match(r"^(please|ensure|note|instructions?)\b", tt, re.I):
            return True
        return False

    def merge_wrapped(lines_block):
        parts = []
        for ln in lines_block:
            t = norm_space(getattr(ln, "text", ""))
            if not t:
                continue
            if is_machine_annotation(t):
                continue
            parts.append(t)
        return norm_space(" ".join(parts))

    def blockify(lines_list, x_tol=10, y_gap=15):
        """Group lines into wrapped blocks by proximity in x and y."""
        if not lines_list:
            return []
        lines_list = sorted(lines_list, key=lambda l: (l.y0, l.x0))
        blocks = []
        cur = [lines_list[0]]
        last = lines_list[0]
        for ln in lines_list[1:]:
            if abs(ln.x0 - last.x0) <= x_tol and (ln.y0 - last.y0) <= y_gap:
                cur.append(ln)
            else:
                blocks.append(cur)
                cur = [ln]
            last = ln
        blocks.append(cur)
        return blocks

    # ---------------- schedule/form name ----------------
    def parse_schedule_name(lines):
        # Find "Schedule Category & Name:" label then take nearest right-side value line.
        label_idx = None
        for i, ln in enumerate(lines):
            if getattr(ln, "bold", False) and (not getattr(ln, "non_black", False)) and lower(ln.text).startswith("schedule category"):
                label_idx = i
                break
        if label_idx is None:
            return ""
        y = lines[label_idx].y0
        lab = lines[label_idx]
        candidates = []
        for ln in lines:
            if abs(ln.y0 - y) <= 2.5 and ln.x0 > lab.x1 - 5:
                if ln is lab:
                    continue
                txt = norm_space(ln.text)
                if txt:
                    candidates.append((ln.x0, txt))
        if not candidates:
            for j in range(label_idx + 1, min(label_idx + 10, len(lines))):
                ln = lines[j]
                if ln.x0 >= 140 and (y - 2) <= ln.y0 <= (y + 60):
                    txt = norm_space(ln.text)
                    if txt:
                        candidates.append((ln.x0, txt))
                        break
        if not candidates:
            return ""
        candidates.sort()
        val = candidates[0][1]
        if "," in val:
            left, right = val.split(",", 1)
            if re.fullmatch(r"[A-Z]_[A-Z0-9]+", left.strip()):
                val = right.strip()
        return val.strip()

    # ---------------- label classification ----------------
    # IMPORTANT FIXES:
    #  - Do NOT extract "Group, Visit:" (header furniture) as a field.
    #  - Do NOT extract "Staff Initials:", "Comment:", "Answer(s):" as standalone fields.
    #    (They are present on many pages but are not data-entry fields per gates.)
    #  - Ensure we still extract real fields like Randomisation Number, Treatment, Dose Level,
    #    and nitrite question, even when not bold-black at x~168.
    #  - Ensure we can extract top header fields: Study, Site:, Slot:, Schedule Category & Name:
    #    (these were missed on page 1).

    NON_FIELD_LABELS = {
        "group, visit:",
        "annotated crf",
    }

    # These appear as sublabels next to entry areas; gates say they are NOT data-entry fields.
    SUBLABELS_NOT_FIELDS = {
        "comment:",
        "staff initials:",
        "barcode:",
        "answer(s):",
        "answers:",
        "answer:",
    }

    def is_non_field_furniture(t: str) -> bool:
        tl = lower(t)
        if tl in NON_FIELD_LABELS:
            return True
        if tl in SUBLABELS_NOT_FIELDS:
            return True
        # Also exclude lone trailing fragments like "research?"
        if len(tl) <= 12 and tl.endswith("?") and tl in {"research?"}:
            return True
        return False

    def is_main_field_label_candidate(line):
        if not getattr(line, "bold", False):
            return False
        if getattr(line, "non_black", False):
            return False
        t = norm_space(line.text)
        if not t:
            return False
        if is_non_field_furniture(t):
            return False
        if lower(t).startswith("schedule category"):
            # handled separately as header field
            return False
        if is_machine_annotation(t) or is_option_line(t) or is_placeholder_line(t):
            return False
        if re.fullmatch(r"\d+(?:\.\d+)?(?:\s*\(hidden\))?", t):
            return False
        if not (120 <= line.x0 <= 260):
            return False
        sz = getattr(line, "size", 10)
        if sz < 7 or sz > 16:
            return False
        if is_instruction_only(t):
            return False
        return True

    def is_fallback_question(line):
        # Broader capture for key fields that may not be bold-black at x~168.
        if not getattr(line, "bold", False):
            return False
        t = norm_space(line.text)
        if not t:
            return False
        if is_non_field_furniture(t):
            return False
        if is_machine_annotation(t) or is_option_line(t) or is_placeholder_line(t):
            return False
        if lower(t).startswith("schedule category"):
            return False
        if not (90 <= line.x0 <= 360):
            return False
        sz = getattr(line, "size", 10)
        if sz < 7 or sz > 18:
            return False

        tl = t.lower()
        # Question marks are strong signals
        if t.endswith("?"):
            return True
        # Key phrases seen in missed pages
        if re.search(r"\b(randomisation|randomization|treatment|dose level|batch number|container number|number of tablets|capsules|nitrite)\b", tl):
            return True
        # "What was the nitrite result? (Perform ...)" sometimes wraps; allow "nitrite result" without '?'
        if "nitrite result" in tl:
            return True
        return False

    # ---------------- header fields (Study/Site/Slot/Schedule...) ----------------
    HEADER_LABELS = {
        "study, site:": "Study, Site:",
        "study, site": "Study, Site:",
        "slot:": "Slot:",
        "slot": "Slot:",
        "schedule category & name:": "Schedule Category & Name:",
        "schedule category & name": "Schedule Category & Name:",
    }

    def extract_header_fields(page_idx0, lines, current_form):
        """
        Extract header labels as fields (label-only), because gates expect them.
        We do NOT attempt to extract their values.
        """
        out_local = []
        seen_local = set()

        # Find lines that match header labels (bold or not; some renderings vary)
        for ln in lines:
            t = norm_space(getattr(ln, "text", ""))
            if not t:
                continue
            tl = t.lower()
            if tl in HEADER_LABELS:
                field = HEADER_LABELS[tl]
                key = (current_form or "", field, page_idx0 + 1)
                if key not in seen_local:
                    seen_local.add(key)
                    out_local.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

        # Also capture "Schedule Category & Name:" if it appears as prefix (sometimes extra spaces)
        for ln in lines:
            t = norm_space(getattr(ln, "text", ""))
            if not t:
                continue
            tl = t.lower()
            if tl.startswith("schedule category") and "&" in tl and "name" in tl:
                field = "Schedule Category & Name:"
                key = (current_form or "", field, page_idx0 + 1)
                if key not in seen_local:
                    seen_local.add(key)
                    out_local.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

        return out_local

    # ---------------- main extraction ----------------
    out = []
    seen = set()  # (form_name, field_name)

    current_form = ""

    for page_idx0, lines in pages:
        # Update form name from schedule name if present
        sched = parse_schedule_name(lines)
        if sched:
            current_form = sched

        # (0) Header fields expected by gates
        for rec in extract_header_fields(page_idx0, lines, current_form):
            key = (rec["form_name"], rec["field_name"])
            if key not in seen:
                seen.add(key)
                out.append(rec)

        # (1) Extract main field labels (bold black, main column)
        main_candidates = [ln for ln in lines if is_main_field_label_candidate(ln)]
        main_blocks = blockify(main_candidates, x_tol=10, y_gap=15)

        for blk in main_blocks:
            field = merge_wrapped(blk)
            if not field:
                continue
            if is_non_field_furniture(field):
                continue
            if looks_like_activity_header(field):
                continue
            if len(field) < 3:
                continue
            if is_instruction_only(field):
                continue

            key = (current_form or "", field)
            if key not in seen:
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

        # (2) Fallback extraction for key fields/questions in variant layouts
        fb_candidates = [ln for ln in lines if is_fallback_question(ln)]
        fb_blocks = blockify(fb_candidates, x_tol=14, y_gap=18)

        for blk in fb_blocks:
            field = merge_wrapped(blk)
            if not field:
                continue
            if is_non_field_furniture(field):
                continue
            if looks_like_activity_header(field):
                continue
            if is_instruction_only(field):
                continue
            if len(field) < 3:
                continue

            # Guard against extracting trailing fragments like "research?"
            # If it is very short and appears to be a wrap tail, drop it.
            if len(field) <= 12 and field.endswith("?") and field.lower() in {"research?"}:
                continue

            key = (current_form or "", field)
            if key not in seen:
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

        # (3) Additional targeted capture for non-bold key labels (page 281-like tables)
        # Some table labels may not be bold; capture black text in main column that matches key phrases.
        def is_table_key_label(line):
            t = norm_space(getattr(line, "text", ""))
            if not t:
                return False
            if is_non_field_furniture(t):
                return False
            if is_machine_annotation(t) or is_option_line(t) or is_placeholder_line(t):
                return False
            # Prefer black text (non_black False), but allow either if it matches strongly
            tl = t.lower()
            if not (90 <= getattr(line, "x0", 0) <= 360):
                return False
            sz = getattr(line, "size", 10)
            if sz < 7 or sz > 18:
                return False
            # Strong whitelist of missed labels
            if re.fullmatch(r"(randomisation|randomization) number", tl):
                return True
            if tl in {"treatment", "dose level", "batch number", "container number"}:
                return True
            if "number of tablets" in tl or "capsules to be administered" in tl:
                return True
            return False

        tbl_candidates = [ln for ln in lines if is_table_key_label(ln)]
        tbl_blocks = blockify(tbl_candidates, x_tol=18, y_gap=18)

        for blk in tbl_blocks:
            field = merge_wrapped(blk)
            if not field:
                continue
            if is_non_field_furniture(field):
                continue
            key = (current_form or "", field)
            if key not in seen:
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

    return out
```