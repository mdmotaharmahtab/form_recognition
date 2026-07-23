```python
# Observed layouts: (1) cover/approval pages with large bold title and left-column bold labels;
# (2) main annotated CRF pages with a white-on-dark form header at top and repeated item blocks:
#     right column shows bold variable code + metadata; left column shows human label and [CODE] lines;
# (3) code list dictionary pages with "Coded/Decode" tables (no data-entry fields).
# Strategy: detect form_name from top header (non-black/white text near y~35). Extract field labels
# from left-column black text lines (x~46, size~7.5) that precede a bracketed [CODE] line; also
# extract cover-page bold labels (size~16) as fields under the cover form title.

import re
from collections import defaultdict

def extract(pages):
    def norm_space(s):
        return re.sub(r"\s+", " ", s).strip()

    def is_page_footer(line):
        t = line.text.strip()
        if not t:
            return True
        if line.y0 > 760 and (re.search(r"\bAnnotated CRF\b", t, re.I) or re.search(r"\bPage\b", t, re.I) or re.search(r"\bof\b", t)):
            return True
        if line.y0 > 760 and re.search(r"https?://", t, re.I):
            return True
        return False

    def is_machine_annotation_text(t):
        tt = t.strip()
        if not tt:
            return True
        # bracketed machine codes / SAS field name / OID etc.
        if re.fullmatch(r"\[[^\]]+\]", tt):
            return True
        if re.search(r"\bSAS Field Name\b", tt, re.I):
            return True
        if re.search(r"\bOdm OID\b", tt, re.I):
            return True
        if re.search(r"\bOrigin:\b", tt):
            return True
        if re.search(r"\bData Type:\b", tt):
            return True
        if re.search(r"\bFormat:\b", tt):
            return True
        if re.search(r"\bAliases:\b", tt):
            return True
        if re.search(r"\bDescription:\b", tt):
            return True
        if re.search(r"\bMandatory\?\b", tt):
            return True
        if re.search(r"\bDisallow Future Date\b", tt):
            return True
        if re.search(r"\bCode List:\b", tt):
            return True
        if re.search(r"\bRole Restriction:\b", tt):
            return True
        if re.search(r"\bDefault Item Value:\b", tt):
            return True
        if re.search(r"\bConditional(ly)? Visible\b", tt):
            return True
        if re.search(r"\bConditional Item:\b", tt):
            return True
        if re.search(r"\bVisible If Value:\b", tt):
            return True
        # variable code lines (right column) are not labels
        if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", tt):
            return True
        return False

    def looks_like_option_line(line):
        # options are typically "O Yes" etc at x~249 size~7.5
        t = line.text.strip()
        if not t:
            return False
        if line.x0 > 200 and re.match(r"^O\s+\S", t):
            return True
        return False

    def is_form_header_candidate(line):
        # top header: often non-black (white) size ~12 at y~35 x~42
        t = line.text.strip()
        if not t:
            return False
        if line.y0 > 80:
            return False
        if line.size < 10.5:
            return False
        # exclude protocol number line at very top left
        if re.fullmatch(r"\d{3}-\d{3}-\d{5}", t):
            return False
        # exclude "Origin: CRF" etc
        if re.search(r"\bOrigin:\b", t):
            return False
        # header tends to be colored/non-black or white; but allow black if bold and centered-ish
        if line.non_black:
            return True
        if line.bold and 150 < line.x0 < 450:
            return True
        return False

    def detect_form_name(lines, prev_form):
        # Prefer top header candidate (cluster 2/3)
        header_lines = [ln for ln in lines if is_form_header_candidate(ln)]
        # choose leftmost among candidates near y~35-45
        if header_lines:
            header_lines.sort(key=lambda l: (abs(l.y0 - 35), l.x0))
            name = norm_space(header_lines[0].text)
            # avoid generic table headers
            if not re.fullmatch(r"(Coded|Decode)", name, re.I):
                return name

        # Cover page: large bold title around y~150
        big_titles = [ln for ln in lines if ln.bold and ln.size >= 18 and 80 < ln.y0 < 220 and len(ln.text.strip()) > 2]
        if big_titles:
            big_titles.sort(key=lambda l: (l.y0, -l.size))
            return norm_space(big_titles[0].text)

        return prev_form or ""

    def page_is_code_list_table(lines):
        # Detect dictionary pages: "Coded" and "Decode" headers at y~60
        coded = any(ln.bold and 55 < ln.y0 < 70 and re.fullmatch(r"Coded", ln.text.strip(), re.I) for ln in lines)
        decode = any(ln.bold and 55 < ln.y0 < 70 and re.fullmatch(r"Decode", ln.text.strip(), re.I) for ln in lines)
        return coded and decode

    def extract_cover_fields(lines):
        # Bold labels on left column size ~16; ignore page furniture
        fields = []
        for ln in lines:
            if is_page_footer(ln):
                continue
            t = ln.text.strip()
            if not t:
                continue
            if ln.bold and 14.5 <= ln.size <= 17.5 and ln.x0 < 120 and 180 < ln.y0 < 520:
                # exclude obvious non-field headings
                if re.search(r"\bSponsor Name\b|\bProtocol Number\b|\bProtocol Title\b|\baCRF Version\b|\bPrepared by\b|\bDate\b", t, re.I):
                    # still fields; keep as printed label
                    fields.append(norm_space(t))
                else:
                    fields.append(norm_space(t))
        # de-dup preserving order
        seen = set()
        out = []
        for f in fields:
            if f and f not in seen:
                seen.add(f)
                out.append(f)
        return out

    def extract_annotated_fields(lines):
        # Main extraction: label lines at x~46 size~7.5 that precede a bracketed [CODE] line.
        # We'll scan in y order; when we see a [CODE] line at x~46, take nearest preceding label
        # lines (x~46, size 7-8, black) since last field boundary.
        # Also handle section headers (blue 10.5) but those are not fields.
        candidates = []
        # filter out footer and right-column metadata
        usable = [ln for ln in lines if not is_page_footer(ln)]
        # index bracket lines
        bracket_idxs = []
        for i, ln in enumerate(usable):
            t = ln.text.strip()
            if ln.x0 < 120 and re.fullmatch(r"\[[A-Z0-9_]+\]", t):
                bracket_idxs.append(i)

        # helper to collect label text before bracket
        for bi in bracket_idxs:
            bline = usable[bi]
            # search backwards up to ~8 lines or until big gap
            label_parts = []
            last_y = bline.y0
            for j in range(bi - 1, max(-1, bi - 12), -1):
                ln = usable[j]
                if ln.y0 < 0:
                    continue
                if last_y - ln.y0 > 40:
                    break
                last_y = ln.y0
                if ln.x0 > 140:
                    continue
                if looks_like_option_line(ln):
                    continue
                t = ln.text.strip()
                if not t:
                    continue
                if is_machine_annotation_text(t):
                    continue
                # exclude protocol number at top
                if re.fullmatch(r"\d{3}-\d{3}-\d{5}", t):
                    continue
                # label lines are typically size ~7.5 black
                if 6.5 <= ln.size <= 9.0:
                    label_parts.append(t)
                # stop if we hit a blue section header (size ~10.5 non-black) or another bracket
                if ln.non_black and ln.size >= 10:
                    break
                if re.fullmatch(r"\[[A-Z0-9_]+\]", t):
                    break
            if label_parts:
                label = norm_space(" ".join(reversed(label_parts)))
                # remove trailing punctuation artifacts
                label = re.sub(r"\s*:\s*$", "", label).strip()
                if label and not is_machine_annotation_text(label):
                    candidates.append(label)

        # Also capture standalone labels that have no bracket line (rare): detect left label followed by right code
        # Pattern: right column bold code at x>430; left label at x~46 within ~20pt above.
        right_codes = [(i, ln) for i, ln in enumerate(usable) if ln.bold and ln.x0 > 420 and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", ln.text.strip())]
        for i, rln in right_codes:
            # find nearest left label line below/above within 30pt
            best = None
            best_dy = 1e9
            for j in range(max(0, i - 6), min(len(usable), i + 10)):
                ln = usable[j]
                if ln.x0 > 140:
                    continue
                if looks_like_option_line(ln):
                    continue
                t = ln.text.strip()
                if not t or is_machine_annotation_text(t):
                    continue
                if not (6.5 <= ln.size <= 9.0):
                    continue
                dy = abs(ln.y0 - rln.y0)
                if dy < best_dy and dy <= 35:
                    best = t
                    best_dy = dy
            if best:
                label = norm_space(best)
                if label and label not in candidates:
                    candidates.append(label)

        # de-dup preserving order
        seen = set()
        out = []
        for c in candidates:
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return out

    results = []
    seen_global = set()  # (form_name, field_name)
    current_form = ""

    for page_idx0, lines in pages:
        current_form = detect_form_name(lines, current_form)

        # Skip pure code list dictionary pages (no data-entry fields)
        if page_is_code_list_table(lines):
            continue

        # Determine which extractor to use
        # Cover pages have big title and bold left labels; annotated pages have many bracket codes.
        has_brackets = any(re.fullmatch(r"\[[A-Z0-9_]+\]", ln.text.strip()) for ln in lines if ln.x0 < 140)
        big_title = any(ln.bold and ln.size >= 18 and 80 < ln.y0 < 220 for ln in lines)

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