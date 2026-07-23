# Observed layouts: (1) cover/signature pages with narrative text only; (2) CRF pages with
# a bold header "Form: <name>" near top-left and then left-column question/label lines,
# with right-column answer options/values and a far-right numeric field index; (3) codebook
# pages with a table header "Field Name Data Type ..." and rows containing machine OIDs.
# Strategy: track current form_name from the "Form:" header; for each page, if it's a
# codebook/table page, extract human field labels from the left "Field Name" column while
# filtering out OIDs/codes; otherwise extract question/label blocks from the left column,
# joining wrapped lines and excluding answer options and page furniture.

import re
from statistics import median

def extract(pages):
    def norm(s):
        s = re.sub(r"\s+", " ", s or "").strip()
        return s

    def is_page_footer(line):
        t = line.text.strip()
        if line.y0 < 660:
            return False
        # "X of Y" and study footer like "01.025 GMK (432)"
        if re.search(r"\b\d+\s+of\s+\d+\b", t, flags=re.I):
            return True
        if re.search(r"\(\s*\d+\s*\)\s*$", t) and re.search(r"\d+\.\d+|\d+\.\d+|\d+\.\d+", t) is None:
            # generic "(432)" style
            return True
        return False

    def is_header_line(line):
        t = line.text.strip()
        if line.y0 > 140:
            return False
        if line.bold and (t.startswith("Form:") or "Generated On:" in t):
            return True
        if line.bold and re.search(r":\s*Unique\s*CRF\b", t):
            return True
        return False

    def get_form_name(lines):
        # Find bold "Form:" line
        for ln in lines:
            if ln.y0 > 140:
                break
            t = ln.text.strip()
            if ln.bold and t.startswith("Form:"):
                return norm(t.split("Form:", 1)[1])
        return None

    def is_codebook_page(lines):
        # Detect table header "Field Name Data Type" etc.
        header_hits = 0
        for ln in lines:
            if ln.y0 > 220:
                break
            t = ln.text.strip()
            if re.search(r"\bField\s+Name\b", t, flags=re.I):
                header_hits += 1
            if re.search(r"\bData\s+Type\b", t, flags=re.I):
                header_hits += 1
            if re.search(r"\bField\s+OID\b", t, flags=re.I):
                header_hits += 1
        return header_hits >= 2

    def looks_like_oid_or_code(s):
        s = norm(s)
        if not s:
            return True
        # pure number or short index
        if re.fullmatch(r"\d{1,4}", s):
            return True
        # typical OID/code patterns: uppercase/underscore/digits, maybe trailing underscore
        if re.fullmatch(r"[A-Z0-9_]{3,}", s):
            return True
        # dollar datatype markers like $25, $200
        if re.fullmatch(r"\$\d+", s):
            return True
        # date format fragments
        if re.fullmatch(r"(dd|mm|MMM|yyyy|HH|HR|24\s*HR|24HR|AM|PM|GMT|UTC)[A-Za-z\s:()/-]*", s, flags=re.I):
            return True
        return False

    def is_answer_option_line(line, left_x_threshold):
        # Answer options typically appear in right column (x >= ~400) and are short like Yes/No or "1=Absent"
        t = norm(line.text)
        if not t:
            return True
        if line.x0 < left_x_threshold:
            return False
        if re.match(r"^\d+\s*=\s*\S", t):
            return True
        if re.match(r"^[YN]\s*=\s*\w+", t, flags=re.I):
            return True
        if len(t) <= 12 and re.fullmatch(r"[A-Za-z]+", t):
            return True
        return False

    def compute_left_x(lines):
        # Determine dominant left margin for labels/questions (exclude headers/footers)
        xs = []
        for ln in lines:
            if is_header_line(ln) or is_page_footer(ln):
                continue
            t = ln.text.strip()
            if not t:
                continue
            # ignore far-right numeric field indices
            if ln.x0 > 500 and re.fullmatch(r"\d{1,4}", t):
                continue
            # ignore right-column options/values
            if ln.x0 > 360:
                continue
            xs.append(ln.x0)
        if not xs:
            return 90.0
        return median(xs)

    def extract_fields_normal_page(lines, form_name, page1based):
        left_x = compute_left_x(lines)
        # left column region: from left_x-10 to ~360
        left_min = left_x - 15
        left_max = 365

        # collect candidate lines in body
        body = []
        for ln in lines:
            if is_header_line(ln) or is_page_footer(ln):
                continue
            if ln.y0 < 140:
                continue
            t = ln.text.strip()
            if not t:
                continue
            # skip far-right numeric field index
            if ln.x0 > 500 and re.fullmatch(r"\d{1,4}", t):
                continue
            # skip right-column answer options/values
            if is_answer_option_line(ln, left_x_threshold=390):
                continue
            # keep only left-ish content
            if ln.x0 < left_min or ln.x0 > left_max:
                continue
            body.append(ln)

        # group into blocks by vertical proximity; join wrapped lines
        blocks = []
        cur = []
        last_y = None
        for ln in body:
            if last_y is None:
                cur = [ln]
                last_y = ln.y0
                continue
            # new block if large vertical gap
            if ln.y0 - last_y > 18:
                blocks.append(cur)
                cur = [ln]
            else:
                # if same block but line is far to the right compared to left margin, it might be a value; drop it
                cur.append(ln)
            last_y = ln.y0
        if cur:
            blocks.append(cur)

        out = []
        for blk in blocks:
            # sort by y then x to join in reading order
            blk_sorted = sorted(blk, key=lambda l: (l.y0, l.x0))
            txt = norm(" ".join([b.text.strip() for b in blk_sorted]))
            if not txt:
                continue
            # filter out obvious non-fields / narrative paragraphs (cover pages handled separately)
            if len(txt) < 2:
                continue
            # exclude table headers if any leak in
            if re.search(r"\bField\s+Name\b", txt, flags=re.I) and re.search(r"\bData\s+Type\b", txt, flags=re.I):
                continue
            # exclude pure category/value lines that look like codes
            if looks_like_oid_or_code(txt):
                continue
            # exclude fixed unit annotations
            if re.match(r"^Fixed\s+Unit\s*:", txt, flags=re.I):
                continue
            # exclude standalone "Category" label (usually paired with right value)
            if re.fullmatch(r"Category", txt, flags=re.I):
                continue
            out.append({"form_name": form_name or "", "field_name": txt, "page": page1based})
        return out

    def extract_fields_codebook_page(lines, form_name, page1based):
        # Extract from left "Field Name" column: x around 110 in samples; ignore row numbers at ~95 and OIDs.
        # We'll take lines with x in [80, 210] and not header/footer, and not pure codes.
        candidates = []
        for ln in lines:
            if is_header_line(ln) or is_page_footer(ln):
                continue
            if ln.y0 < 140:
                continue
            t = ln.text.strip()
            if not t:
                continue
            # skip table header lines
            if re.search(r"\bField\s+Name\b", t, flags=re.I) or re.search(r"\bData\s+Type\b", t, flags=re.I):
                continue
            if re.search(r"\bField\s+OID\b", t, flags=re.I):
                continue
            # skip row numbers
            if ln.x0 < 105 and re.fullmatch(r"\d{1,4}", t):
                continue
            # focus on left column where human field labels appear (often mixed case, may include spaces/hyphens)
            if not (80 <= ln.x0 <= 240):
                continue
            # remove datatype fragments that are not labels (e.g., "$25", "dd MMM")
            if looks_like_oid_or_code(t):
                continue
            # also skip very short fragments that are likely wrapped codes
            if len(t) <= 2:
                continue
            candidates.append(ln)

        # Join wrapped labels if they appear on consecutive lines with similar x
        candidates = sorted(candidates, key=lambda l: (l.y0, l.x0))
        blocks = []
        cur = []
        last = None
        for ln in candidates:
            if last is None:
                cur = [ln]
                last = ln
                continue
            same_col = abs(ln.x0 - last.x0) <= 25
            close_y = (ln.y0 - last.y0) <= 16
            if same_col and close_y:
                cur.append(ln)
            else:
                blocks.append(cur)
                cur = [ln]
            last = ln
        if cur:
            blocks.append(cur)

        out = []
        for blk in blocks:
            txt = norm(" ".join([b.text.strip() for b in blk]))
            if not txt:
                continue
            if looks_like_oid_or_code(txt):
                continue
            out.append({"form_name": form_name or "", "field_name": txt, "page": page1based})
        return out

    results = []
    seen = set()

    current_form = ""
    for page_idx0, lines in pages:
        page1 = page_idx0 + 1

        # Update form name if present
        fn = get_form_name(lines)
        if fn:
            current_form = fn

        # Skip cover/signature narrative pages without "Form:"
        if not current_form and not fn:
            continue

        if is_codebook_page(lines):
            recs = extract_fields_codebook_page(lines, current_form, page1)
        else:
            recs = extract_fields_normal_page(lines, current_form, page1)

        for r in recs:
            key = (r["form_name"], r["field_name"], r["page"])
            if key in seen:
                continue
            seen.add(key)
            results.append(r)

    return results
