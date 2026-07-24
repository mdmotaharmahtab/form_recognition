```python
import re
from statistics import median

def extract(pages):
    def norm(s):
        s = re.sub(r"\s+", " ", s or "").strip()
        return s

    # -----------------------------
    # Stronger furniture/code filters
    # -----------------------------
    FOOTER_STUDY_RE = re.compile(r"^\s*\d{2}\.\d{3}\s+[A-Z]{2,}\s*\(\s*\d+\s*\)\s*$")
    PAGE_X_OF_Y_RE = re.compile(r"\b\d+\s+of\s+\d+\b", re.I)

    def is_page_footer(line):
        t = line.text.strip()
        # bottom band only
        if line.y0 < 660:
            return False
        if PAGE_X_OF_Y_RE.search(t):
            return True
        if FOOTER_STUDY_RE.match(t):
            return True
        # generic "(432)" alone at bottom
        if re.fullmatch(r"\(\s*\d+\s*\)", t):
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
        for ln in lines:
            if ln.y0 > 140:
                break
            t = ln.text.strip()
            if ln.bold and t.startswith("Form:"):
                return norm(t.split("Form:", 1)[1])
        return None

    def is_codebook_page(lines):
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
        # code + datatype marker like "VISREASND $200"
        if re.fullmatch(r"[A-Z0-9_]{3,}\s+\$\d+", s):
            return True
        # dollar datatype markers like $25, $200
        if re.fullmatch(r"\$\d+", s):
            return True
        # date/time format fragments
        if re.fullmatch(r"(dd|mm|MMM|yyyy|HH|HR|24\s*HR|24HR|AM|PM|GMT|UTC)[A-Za-z\s:()/-]*", s, flags=re.I):
            return True
        return False

    # Phrases that are commonly not data-entry fields (section headers / instructions / units)
    NON_FIELD_EXACT = {
        "Units",
        "Check all that apply",
        "If No, please provide reason",  # instruction, not a field label itself
    }
    NON_FIELD_PREFIX_RE = re.compile(r"^(If\s+No\b|If\s+Yes\b|If\s+applicable\b|Please\s+specify\b)\b", re.I)
    ROMAN_SECTION_RE = re.compile(r"^\s*[IVXLCDM]+\.\s+[A-Z0-9][A-Z0-9 ,;:'()/\-]+$", re.I)

    def is_non_field_text(txt):
        t = norm(txt)
        if not t:
            return True
        # footer-like study identifier anywhere (some pages leak it into body extraction)
        if FOOTER_STUDY_RE.match(t):
            return True
        # "Folder OID (auto-populated)" is not a data-entry field
        if re.search(r"\bOID\b", t) and re.search(r"\bauto-?populated\b", t, re.I):
            return True
        # explicit non-field exact matches
        if t in NON_FIELD_EXACT:
            return True
        # instruction-like prefixes
        if NON_FIELD_PREFIX_RE.match(t):
            return True
        # roman numeral section headers like "VIII. SUICIDE"
        if ROMAN_SECTION_RE.match(t) and t.upper() == t:
            return True
        # "Category" alone
        if re.fullmatch(r"Category", t, re.I):
            return True
        # fixed unit annotation
        if re.match(r"^Fixed\s+Unit\s*:", t, re.I):
            return True
        return False

    def is_answer_option_line(line, left_x_threshold):
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
        left_min = left_x - 15
        left_max = 365

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
            # drop obvious furniture even if it appears mid-page
            if FOOTER_STUDY_RE.match(t):
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
            if ln.y0 - last_y > 18:
                blocks.append(cur)
                cur = [ln]
            else:
                cur.append(ln)
            last_y = ln.y0
        if cur:
            blocks.append(cur)

        out = []
        for blk in blocks:
            blk_sorted = sorted(blk, key=lambda l: (l.y0, l.x0))
            txt = norm(" ".join([b.text.strip() for b in blk_sorted]))
            if not txt:
                continue

            # exclude table headers if any leak in
            if re.search(r"\bField\s+Name\b", txt, flags=re.I) and re.search(r"\bData\s+Type\b", txt, flags=re.I):
                continue

            # stronger non-field filtering
            if looks_like_oid_or_code(txt):
                continue
            if is_non_field_text(txt):
                continue

            # also exclude very short fragments
            if len(txt) < 2:
                continue

            out.append({"form_name": form_name or "", "field_name": txt, "page": page1based})
        return out

    def extract_fields_codebook_page(lines, form_name, page1based):
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
            # focus on left column where human field labels appear
            if not (80 <= ln.x0 <= 240):
                continue
            if looks_like_oid_or_code(t):
                continue
            if is_non_field_text(t):
                continue
            if len(t) <= 2:
                continue
            candidates.append(ln)

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
            if is_non_field_text(txt):
                continue
            out.append({"form_name": form_name or "", "field_name": txt, "page": page1based})
        return out

    results = []
    seen = set()

    current_form = ""
    for page_idx0, lines in pages:
        page1 = page_idx0 + 1

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
            # final guardrails against known failures
            if is_non_field_text(r.get("field_name", "")):
                continue
            if looks_like_oid_or_code(r.get("field_name", "")):
                continue

            key = (r["form_name"], r["field_name"], r["page"])
            if key in seen:
                continue
            seen.add(key)
            results.append(r)

    return results
```