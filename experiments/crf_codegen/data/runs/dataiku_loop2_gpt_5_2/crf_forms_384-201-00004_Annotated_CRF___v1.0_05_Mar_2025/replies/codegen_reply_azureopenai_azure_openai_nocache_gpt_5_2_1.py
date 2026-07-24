```python
# Observed layouts: (1) cover/approval pages with bold left labels and values on right;
# (2) schedule/listing pages with "Form:" metadata on right; (3) main annotated CRF pages
# with a colored form title bar at top and repeated field blocks where the human label is
# a black ~7.5pt line at left (x~46) and machine annotations (codes, [SAS Field Name:], etc.)
# appear nearby; (4) code list pages (Coded/Decode tables) that contain no data-entry fields.
# Strategy: track current form_name from top title bar or "Form:" metadata; extract field_name
# from left-column black label lines while skipping options, codes, and annotation furniture.

import re
from collections import defaultdict

def extract(pages):
    # ---------- helpers ----------
    def norm(s):
        s = re.sub(r"\s+", " ", (s or "").strip())
        return s

    def is_page_footer(line):
        t = line.text.strip()
        if not t:
            return True
        if re.search(r"\bAnnotated\s+CRF\b", t, re.I):
            return True
        if re.search(r"\bhttps?://", t, re.I):
            return True
        if re.search(r"\b\d+\s+of\s+\d+\b", t):
            return True
        if re.search(r"\bP\s*a\s*g\s*e\b", t, re.I):
            return True
        return False

    def is_machine_code_line(line):
        t = line.text.strip()
        if not t:
            return True
        # bracketed technical tags
        if t.startswith("[") and t.endswith("]"):
            return True
        if t.startswith("Odm OID") or "Odm OID" in t:
            return True
        if re.match(r"^(Format|Data Type|Origin|Aliases|Description|Mandatory\?|Disallow|Default Item Value|Conditional Item|Visible If Value|Conditionally Visible|Role Restriction|Domain|Repeating)\b", t):
            return True
        # short all-caps variable-like codes (e.g., PEDTC, INC001)
        if line.bold and line.size <= 6.2 and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", t):
            return True
        # protocol number header
        if re.fullmatch(r"\d{3}-\d{3}-\d{5}", t):
            return True
        return False

    def is_option_line(line):
        t = line.text.strip()
        if not t:
            return True
        # radio/checkbox options often start with "O " (letter O) in this PDF text
        if re.match(r"^[Oo]\s+\S", t):
            return True
        # underscore entry widgets / date templates
        if re.search(r"\[_\|?_\]", t) or re.search(r"_{5,}", t):
            return True
        # coded/decode tables: numeric/short code in first column
        if re.fullmatch(r"(NA|N/A|MET|NOTMET|UNS|\d+)", t):
            return True
        return False

    def is_cover_label(line):
        # cover page: bold ~16pt labels at x~78
        return line.bold and 14.5 <= line.size <= 17.5 and 60 <= line.x0 <= 120

    def is_cover_value(line):
        return (not line.bold) and 10.5 <= line.size <= 13.0 and line.x0 >= 180

    def looks_like_form_title(line):
        # main CRF pages: title in white text around y~35, size ~12
        if line.y0 > 80:
            return False
        if line.size >= 11.0 and line.non_black:
            # often white on colored bar
            return True
        return False

    def is_code_list_page(lines):
        # detect "Coded" and "Decode" headers
        has_coded = any(norm(ln.text).lower() == "coded" for ln in lines if ln.y0 < 120)
        has_decode = any(norm(ln.text).lower() == "decode" for ln in lines if ln.y0 < 120)
        return has_coded and has_decode

    def get_form_from_metadata(lines):
        # schedule/listing pages: right column contains "Form: <name>"
        # return last seen on page (most relevant)
        form = None
        for ln in lines:
            t = ln.text.strip()
            if ln.x0 >= 380 and re.match(r"^Form:\s*", t):
                form = norm(re.sub(r"^Form:\s*", "", t))
        return form

    def get_form_from_titlebar(lines):
        # main CRF pages: top title bar line (white text)
        candidates = [ln for ln in lines if looks_like_form_title(ln)]
        if not candidates:
            return None
        # choose leftmost among top candidates (title usually at x~42)
        candidates.sort(key=lambda l: (l.y0, l.x0))
        title = norm(candidates[0].text)
        # avoid generic "Origin: CRF" etc.
        if re.match(r"^(Origin|Aliases)\b", title):
            # try next
            for ln in candidates[1:]:
                title2 = norm(ln.text)
                if title2 and not re.match(r"^(Origin|Aliases)\b", title2):
                    return title2
            return None
        return title or None

    def extract_fields_from_main_page(lines, current_form, page1based):
        out = []
        # Candidate label lines: black, ~7-8pt, left column x~46, not bracketed, not options
        # Also allow slightly larger (10.5) colored section headers but those are not fields.
        # We'll only take black ~7-8pt lines as field labels.
        label_lines = []
        for ln in lines:
            if is_page_footer(ln):
                continue
            if ln.y0 < 80 and looks_like_form_title(ln):
                continue
            if ln.x0 <= 30:
                continue
            if ln.x0 > 220:
                continue
            if ln.non_black:
                continue
            if not (6.8 <= ln.size <= 8.2):
                continue
            if is_machine_code_line(ln):
                continue
            if is_option_line(ln):
                continue
            t = norm(ln.text)
            if not t:
                continue
            # exclude pure numbering/bullets without text
            if re.fullmatch(r"[\d\.\)\(]+", t):
                continue
            # exclude lines that are just code tags without brackets (rare)
            if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", t):
                continue
            label_lines.append(ln)

        # Merge multi-line labels: consecutive label lines close in y and similar x
        label_lines.sort(key=lambda l: (l.y0, l.x0))
        merged = []
        for ln in label_lines:
            t = norm(ln.text)
            if not merged:
                merged.append([ln, t])
                continue
            prev_ln, prev_txt = merged[-1]
            # if next line is directly below and aligned, treat as continuation
            if abs(ln.x0 - prev_ln.x0) <= 8 and 0 < (ln.y0 - prev_ln.y0) <= 12:
                merged[-1][0] = ln  # update last line ref to newest for y tracking
                merged[-1][1] = norm(prev_txt + " " + t)
            else:
                merged.append([ln, t])

        for ln, t in merged:
            # final sanity: avoid very short generic words that are likely column headers
            if len(t) < 3:
                continue
            out.append({"form_name": current_form or "", "field_name": t, "page": page1based})
        return out

    def extract_fields_from_cover(lines, page1based):
        # cover page: bold labels at left are fields
        out = []
        # group by y proximity: label line then value line(s) to right; we only need label
        for ln in lines:
            if is_page_footer(ln):
                continue
            if is_cover_label(ln):
                t = norm(ln.text)
                if t and not re.search(r"\bSponsor Name:\b", t):
                    out.append({"form_name": "aCRF Approval Form", "field_name": t, "page": page1based})
        return out

    # ---------- main loop ----------
    results = []
    seen = set()  # (form_name, field_name)
    current_form = ""

    for page_index, lines in pages:
        page1based = page_index + 1
        if not lines:
            continue

        # Update form context
        title_form = get_form_from_titlebar(lines)
        meta_form = get_form_from_metadata(lines)
        if title_form:
            current_form = title_form
        elif meta_form:
            current_form = meta_form

        # Skip code list pages (no data-entry fields)
        if is_code_list_page(lines):
            continue

        # Cover/approval pages: detect by presence of big title "aCRF Approval Form"
        has_big_title = any(ln.bold and ln.size >= 18 and "CRF" in ln.text for ln in lines)
        if has_big_title:
            page_fields = extract_fields_from_cover(lines, page1based)
        else:
            page_fields = extract_fields_from_main_page(lines, current_form, page1based)

        for rec in page_fields:
            key = (rec["form_name"], rec["field_name"])
            if key in seen:
                continue
            # avoid empty/garbage field names
            fn = rec["field_name"]
            if not fn or re.fullmatch(r"[\W_]+", fn):
                continue
            # avoid machine-ish leftovers
            if re.match(r"^\[?SAS Field Name\b", fn) or re.match(r"^\[?[A-Z0-9_]{3,}\]?$", fn):
                continue
            seen.add(key)
            results.append(rec)

    return results
```