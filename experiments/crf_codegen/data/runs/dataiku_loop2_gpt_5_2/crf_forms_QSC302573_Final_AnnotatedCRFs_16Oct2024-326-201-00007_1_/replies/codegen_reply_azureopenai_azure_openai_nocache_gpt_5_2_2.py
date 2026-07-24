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
            # don't over-filter questions that mention these, but most are annotations
            if len(t) < 80 and ":" in t:
                return True
        return False

    def is_option_line(t: str) -> bool:
        t = (t or "").strip()
        if not t:
            return False
        # Radio/checkbox options often start with O / o / □ / ■ / ( ) etc.
        if re.match(r"^(?:O|o|0|•|·|□|■|\(\s*\)|\[\s*\])\s+\S", t):
            return True
        # "Yes / No" lines sometimes appear as options
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
        # Activity titles often contain ":" and "#<n>"
        if ":" in t:
            if re.search(r"\s#\d+\b", t):
                return True
            if re.search(r"#\d+\s*$", t):
                return True
        return False

    def is_instruction_only(t: str) -> bool:
        # Exclude long instruction parentheticals and "Please ensure..." type lines
        tt = norm_space(t)
        if not tt:
            return True
        if tt.startswith("(") and tt.endswith(")") and len(tt) < 200:
            return True
        if re.match(r"^(please|ensure|note|instructions?)\b", tt, re.I):
            return True
        return False

    def parse_schedule_name(lines):
        # Find "Schedule Category & Name:" label then take nearest right-side value line.
        label_idx = None
        for i, ln in enumerate(lines):
            if ln.bold and (not ln.non_black) and lower(ln.text).startswith("schedule category"):
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
            # fallback: next line to the right-ish
            for j in range(label_idx + 1, min(label_idx + 8, len(lines))):
                ln = lines[j]
                if ln.x0 >= 140 and (y - 2) <= ln.y0 <= (y + 40):
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

    def merge_wrapped(lines_block):
        parts = []
        for ln in lines_block:
            t = norm_space(ln.text)
            if not t:
                continue
            if is_machine_annotation(t):
                continue
            parts.append(t)
        return norm_space(" ".join(parts))

    # ---------------- field detection ----------------
    # We now extract TWO kinds of fields:
    #  (A) main question/field labels (bold black, x~168)
    #  (B) subfields like "Comment:" and "Staff Initials:" (often bold blue, x further right)
    #
    # Additionally, we must avoid extracting instruction-only labels like the ICF version note.

    SUBFIELD_WHITELIST = {
        "comment:",
        "staff initials:",
        "barcode:",
        "answer(s):",
        "answers:",
        "answer:",
    }

    def is_subfield_label(line):
        if not line.bold:
            return False
        t = norm_space(line.text)
        if not t:
            return False
        tl = t.lower()
        # In this corpus these are typically blue (non_black True), but sometimes may render black.
        if tl in SUBFIELD_WHITELIST:
            return True
        # Some pages may omit colon in rendering
        if tl.rstrip(":") + ":" in SUBFIELD_WHITELIST:
            return True
        return False

    def is_main_field_label_candidate(line):
        # Bold black text around x~168 is the question/label.
        if not line.bold:
            return False
        if line.non_black:
            return False
        t = norm_space(line.text)
        if not t:
            return False
        # Exclude obvious headers/furniture
        if t.lower() == "annotated crf":
            return False
        if lower(t).startswith("schedule category"):
            return False

        # Exclude machine annotations/options/placeholders
        if is_machine_annotation(t) or is_option_line(t) or is_placeholder_line(t):
            return False

        # Exclude pure numbers / line numbers
        if re.fullmatch(r"\d+(?:\.\d+)?(?:\s*\(hidden\))?", t):
            return False

        # Geometry gate: main label column (keep broad to not lose coverage)
        if not (120 <= line.x0 <= 260):
            return False

        # Avoid very small/large oddities
        if getattr(line, "size", 10) < 7 or getattr(line, "size", 10) > 16:
            return False

        # Exclude instruction-only lines (fix: ICF version note)
        if is_instruction_only(t):
            return False

        return True

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

    # ---------------- main extraction ----------------
    out = []
    seen = set()  # (form_name, field_name)
    current_form = ""

    for page_idx0, lines in pages:
        # Update form name from schedule name if present
        sched = parse_schedule_name(lines)
        if sched:
            current_form = sched

        # (1) Extract main field labels (existing behavior, but with instruction filter)
        main_candidates = [ln for ln in lines if is_main_field_label_candidate(ln)]
        main_blocks = blockify(main_candidates, x_tol=10, y_gap=15)

        for blk in main_blocks:
            field = merge_wrapped(blk)
            if not field:
                continue
            if looks_like_activity_header(field):
                continue
            if len(field) < 3:
                continue
            # Extra guard: exclude "Please ensure..." etc.
            if is_instruction_only(field):
                continue

            key = (current_form or "", field)
            if key not in seen:
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

        # (2) Extract subfields: Comment:, Staff Initials:, Barcode:, Answer(s):
        # These were previously excluded; now we include them as fields.
        sub_candidates = [ln for ln in lines if is_subfield_label(ln)]
        # Some renderings may wrap "Staff" and "Initials:"; allow wrap merge.
        sub_blocks = blockify(sub_candidates, x_tol=40, y_gap=18)

        for blk in sub_blocks:
            field = merge_wrapped(blk)
            if not field:
                continue
            # Normalize to canonical capitalization as seen on page
            # (keep original merged text, but ensure trailing colon if missing)
            if field.lower() in {k.rstrip(":") for k in SUBFIELD_WHITELIST} and not field.endswith(":"):
                field = field + ":"

            key = (current_form or "", field)
            if key not in seen:
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

        # (3) Layout variant handling: some pages have key fields not bold-black at x~168
        # (e.g., Randomisation Number, Treatment, Dose Level, nitrite result question).
        # Add a fallback: capture bold black OR bold blue question-like lines in the main column
        # that end with "?" or contain "result" / "number" / "dose level" etc., excluding sublabels.
        def is_fallback_question(line):
            if not line.bold:
                return False
            t = norm_space(line.text)
            if not t:
                return False
            tl = t.lower()
            if tl in SUBFIELD_WHITELIST or tl.rstrip(":") + ":" in SUBFIELD_WHITELIST:
                return False
            if is_machine_annotation(t) or is_option_line(t) or is_placeholder_line(t):
                return False
            if t.lower() == "annotated crf":
                return False
            if lower(t).startswith("schedule category"):
                return False
            # geometry: allow a bit wider; these fields often still align with main column
            if not (110 <= line.x0 <= 320):
                return False
            if getattr(line, "size", 10) < 7 or getattr(line, "size", 10) > 16:
                return False
            # must look like a field label
            if t.endswith("?"):
                return True
            if re.search(r"\b(result|number|treatment|dose level|randomisation|randomization|nitrite)\b", t, re.I):
                return True
            return False

        fb_candidates = [ln for ln in lines if is_fallback_question(ln)]
        fb_blocks = blockify(fb_candidates, x_tol=12, y_gap=16)

        for blk in fb_blocks:
            field = merge_wrapped(blk)
            if not field:
                continue
            if looks_like_activity_header(field):
                continue
            if is_instruction_only(field):
                continue
            if len(field) < 3:
                continue
            key = (current_form or "", field)
            if key not in seen:
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

    return out
```