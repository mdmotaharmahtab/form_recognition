```python
import re
from collections import defaultdict

def extract(pages):
    """
    Input: pages = iterable of (page_idx0, lines)
      where each line has at least:
        .text (str), .x0 (float), .y0 (float), .size (float),
        .bold (bool), .non_black (bool)
    Output: list of dicts: {"form_name": str, "field_name": str, "page": int}
    """

    # ----------------------------
    # Utilities
    # ----------------------------
    def norm_space(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip()

    def clean_label(s: str) -> str:
        s = norm_space(s)
        s = re.sub(r"\s*:\s*$", "", s).strip()
        s = re.sub(r"^[\u2022\-\–\—]\s*", "", s).strip()
        return s

    def is_page_footer(line) -> bool:
        t = (line.text or "").strip()
        if not t:
            return True
        if line.y0 > 760 and (re.search(r"\bAnnotated CRF\b", t, re.I) or re.search(r"\bPage\b", t, re.I) or re.search(r"\bof\b", t, re.I)):
            return True
        if line.y0 > 760 and re.search(r"https?://", t, re.I):
            return True
        return False

    # Machine annotation / metadata lines that must NOT become field labels
    MACHINE_PATTERNS = [
        r"\bSAS Field Name\b",
        r"\bODM OID\b",
        r"\bOdm OID\b",
        r"\bOrigin:\b",
        r"\bData Type:\b",
        r"\bFormat:\b",
        r"\bAliases:\b",
        r"\bDescription:\b",
        r"\bMandatory\?\b",
        r"\bDisallow Future Date\b",
        r"\bCode List:\b",
        r"\bRole Restriction:\b",
        r"\bDefault Item Value:\b",
        r"\bConditional(ly)? Visible\b",
        r"\bConditional Item:\b",
        r"\bVisible If Value:\b",
        r"\bData Collector\b",
        r"\bData Collector:\b",
    ]
    MACHINE_RE = re.compile("|".join(MACHINE_PATTERNS), re.I)

    # Strong "not a field label" prefixes (even if they appear without colon due to PDF extraction)
    META_PREFIX_RE = re.compile(
        r"^(Role Restriction|Aliases|Origin|Data Type|Format|Description|Mandatory\?|Code List|Default Item Value|Conditional(ly)? Visible|Data Collector)\b\s*:?\s*",
        re.I,
    )

    def is_machine_annotation_text(t: str) -> bool:
        tt = (t or "").strip()
        if not tt:
            return True
        if re.fullmatch(r"\[[^\]]+\]", tt):
            return True
        if MACHINE_RE.search(tt):
            return True
        # variable code lines (right column) are not labels
        if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", tt):
            return True
        return False

    def looks_like_option_line(line) -> bool:
        t = (line.text or "").strip()
        if not t:
            return False
        # options are typically "O Yes" etc at x~249 size~7.5
        if line.x0 > 180 and re.match(r"^(O|\u25CB|\u25A1)\s+\S", t):
            return True
        return False

    def is_form_header_candidate(line) -> bool:
        t = (line.text or "").strip()
        if not t:
            return False
        if line.y0 > 80:
            return False
        if line.size < 10.5:
            return False
        if re.fullmatch(r"\d{3}-\d{3}-\d{5}", t):
            return False
        if re.search(r"\bOrigin:\b", t):
            return False
        if line.non_black:
            return True
        if getattr(line, "bold", False) and 150 < line.x0 < 450:
            return True
        return False

    def detect_form_name(lines, prev_form: str) -> str:
        header_lines = [ln for ln in lines if is_form_header_candidate(ln)]
        if header_lines:
            header_lines.sort(key=lambda l: (abs(l.y0 - 35), l.x0))
            name = norm_space(header_lines[0].text)
            if not re.fullmatch(r"(Coded|Decode)", name, re.I):
                return name

        big_titles = [
            ln for ln in lines
            if getattr(ln, "bold", False) and ln.size >= 18 and 80 < ln.y0 < 220 and len((ln.text or "").strip()) > 2
        ]
        if big_titles:
            big_titles.sort(key=lambda l: (l.y0, -l.size))
            return norm_space(big_titles[0].text)

        return prev_form or ""

    def page_is_code_list_table(lines) -> bool:
        coded = any(getattr(ln, "bold", False) and 55 < ln.y0 < 70 and re.fullmatch(r"Coded", (ln.text or "").strip(), re.I) for ln in lines)
        decode = any(getattr(ln, "bold", False) and 55 < ln.y0 < 70 and re.fullmatch(r"Decode", (ln.text or "").strip(), re.I) for ln in lines)
        return coded and decode

    def extract_cover_fields(lines):
        fields = []
        for ln in lines:
            if is_page_footer(ln):
                continue
            t = (ln.text or "").strip()
            if not t:
                continue
            if getattr(ln, "bold", False) and 14.5 <= ln.size <= 17.5 and ln.x0 < 120 and 180 < ln.y0 < 520:
                lab = clean_label(t)
                if lab and not META_PREFIX_RE.match(lab):
                    fields.append(lab)
        seen = set()
        out = []
        for f in fields:
            if f and f not in seen:
                seen.add(f)
                out.append(f)
        return out

    # ----------------------------
    # Annotated CRF extraction
    # ----------------------------
    def is_left_column_label_line(ln) -> bool:
        """Heuristic for human label lines in left column."""
        if ln.x0 > 170:
            return False
        if not (6.0 <= ln.size <= 10.2):
            return False
        t = (ln.text or "").strip()
        if not t:
            return False
        if is_machine_annotation_text(t):
            return False
        if looks_like_option_line(ln):
            return False
        if re.fullmatch(r"\d{3}-\d{3}-\d{5}", t):
            return False
        # reject metadata-like prefixes even if not caught by MACHINE_RE
        if META_PREFIX_RE.match(t):
            return False
        return True

    def is_left_bracket_code_line(ln) -> bool:
        t = (ln.text or "").strip()
        return ln.x0 < 170 and bool(re.fullmatch(r"\[[A-Z0-9_]+\]", t))

    def is_right_variable_code_line(ln) -> bool:
        t = (ln.text or "").strip()
        return getattr(ln, "bold", False) and ln.x0 > 410 and bool(re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", t))

    def is_section_header_line(ln) -> bool:
        t = (ln.text or "").strip()
        if not t:
            return False
        if ln.non_black and ln.size >= 10:
            return True
        return False

    def extract_label_before_anchor(usable, anchor_idx: int) -> str:
        """
        Collect contiguous left-column label lines immediately preceding an anchor
        (anchor = bracket code line or right variable code line).
        Stops at big vertical gaps, section headers, other anchors, or machine text.
        """
        anchor = usable[anchor_idx]
        label_parts = []
        last_y = anchor.y0

        for j in range(anchor_idx - 1, max(-1, anchor_idx - 35), -1):
            ln = usable[j]
            if is_page_footer(ln):
                continue

            # stop on big gap
            if last_y - ln.y0 > 60:
                break
            last_y = ln.y0

            # stop if we hit another anchor or a section header
            if is_left_bracket_code_line(ln):
                break
            if is_right_variable_code_line(ln):
                break
            if is_section_header_line(ln):
                break

            if not is_left_column_label_line(ln):
                continue

            t = (ln.text or "").strip()
            if not t:
                continue
            label_parts.append(t)

        if not label_parts:
            return ""

        label = clean_label(" ".join(reversed(label_parts)))

        if not label or is_machine_annotation_text(label):
            return ""
        if META_PREFIX_RE.match(label):
            return ""
        return label

    def merge_wrapped_questions(cands):
        """
        Fix cases like:
          "Were any other actions taken in response to this adverse"
          "event?"
        by merging adjacent fragments when the first doesn't end with punctuation.
        """
        out = []
        i = 0
        while i < len(cands):
            a = clean_label(cands[i])
            if not a:
                i += 1
                continue
            if i + 1 < len(cands):
                b = clean_label(cands[i + 1])
                if b and not META_PREFIX_RE.match(a) and not META_PREFIX_RE.match(b):
                    # merge if a looks like a wrapped line (no terminal punctuation) and b is short continuation
                    if (not re.search(r"[.?!:]$", a)) and (len(b) <= 18 or b.lower() in {"event?", "event.", "event", "time", "date"} or re.match(r"^[a-z].*[.?!]?$", b)):
                        merged = clean_label(a + " " + b)
                        out.append(merged)
                        i += 2
                        continue
            out.append(a)
            i += 1
        return out

    def extract_annotated_fields(lines):
        usable = [ln for ln in lines if not is_page_footer(ln)]

        bracket_idxs = [i for i, ln in enumerate(usable) if is_left_bracket_code_line(ln)]
        candidates = []

        # 1) Bracket-driven extraction (main path)
        for bi in bracket_idxs:
            label = extract_label_before_anchor(usable, bi)
            if label:
                candidates.append(label)

        # 2) Right-code-driven extraction (fallback for fields without bracket line)
        right_code_idxs = [i for i, ln in enumerate(usable) if is_right_variable_code_line(ln)]
        for ri in right_code_idxs:
            label = extract_label_before_anchor(usable, ri)
            if label:
                candidates.append(label)

        # 3) Additional fallback: question lines that are followed soon by options (radio/checkbox)
        for i, ln in enumerate(usable):
            if not is_left_column_label_line(ln):
                continue
            t = clean_label((ln.text or "").strip())
            if not t or is_machine_annotation_text(t) or META_PREFIX_RE.match(t):
                continue

            y0 = ln.y0
            has_options = False
            for j in range(i + 1, min(len(usable), i + 12)):
                ln2 = usable[j]
                if ln2.y0 - y0 > 85:
                    break
                if is_section_header_line(ln2):
                    break
                if is_left_bracket_code_line(ln2) or is_right_variable_code_line(ln2):
                    # anchor exists; bracket/right-code path should handle it
                    has_options = False
                    break
                if looks_like_option_line(ln2):
                    has_options = True
                    break

            if has_options:
                candidates.append(t)

        # Merge wrapped question fragments (improves page 21 truncation/wrapping issues)
        candidates = merge_wrapped_questions(candidates)

        # De-dup preserving order + hard filters
        seen = set()
        out = []
        for c in candidates:
            c = clean_label(c)
            if not c:
                continue
            if is_machine_annotation_text(c):
                continue
            if META_PREFIX_RE.match(c):
                continue
            # reject very short non-fields
            if len(c) <= 2:
                continue
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    # ----------------------------
    # Main loop
    # ----------------------------
    results = []
    seen_global = set()  # (form_name, field_name)
    current_form = ""

    for page_idx0, lines in pages:
        current_form = detect_form_name(lines, current_form)

        # Skip pure code list dictionary pages (no data-entry fields)
        if page_is_code_list_table(lines):
            continue

        has_brackets = any(is_left_bracket_code_line(ln) for ln in lines)
        big_title = any(getattr(ln, "bold", False) and ln.size >= 18 and 80 < ln.y0 < 220 for ln in lines)

        if big_title and not has_brackets:
            fields = extract_cover_fields(lines)
        else:
            fields = extract_annotated_fields(lines)

        for f in fields:
            key = (current_form or "", f)
            if key in seen_global:
                continue
            seen_global.add(key)
            results.append({"form_name": current_form or "", "field_name": f, "page": page_idx0 + 1})

    return results
```