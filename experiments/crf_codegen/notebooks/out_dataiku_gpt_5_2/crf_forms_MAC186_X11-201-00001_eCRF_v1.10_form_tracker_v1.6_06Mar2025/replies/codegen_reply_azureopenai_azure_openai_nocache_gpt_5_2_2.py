import re
from collections import defaultdict

RE_BRACKET_CODE = re.compile(r"\[\s*\d+\s*\]")
RE_PURE_BRACKET = re.compile(r"^\[\s*\d+\s*\]$")
RE_MACHINE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
RE_NUM_ONLY = re.compile(r"^\d+([.,]\d+)?$")

def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def _strip_bracket_codes(s: str) -> str:
    s = RE_BRACKET_CODE.sub("", s)
    return _norm_space(s)

def _is_probably_option_text(s: str) -> bool:
    s = _norm_space(s)
    if not s:
        return True
    if RE_PURE_BRACKET.match(s):
        return True
    if RE_NUM_ONLY.match(s):
        return True
    if len(s) <= 3:
        return True
    if re.fullmatch(r"[-–—•]+", s):
        return True
    return False

def _is_header_or_footer(line) -> bool:
    t = line.text.strip()
    if not t:
        return True
    # top file identifier line
    if line.y0 < 45 and len(t) > 20 and ("eCRF" in t or "form" in t.lower() or "_" in t):
        return True
    return False

def _cluster_rows(lines, y_tol=2.5):
    rows = []
    cur = []
    cur_y = None
    for ln in sorted(lines, key=lambda l: (l.y0, l.x0)):
        y = ln.y0
        if cur_y is None or abs(y - cur_y) <= y_tol:
            cur.append(ln)
            cur_y = y if cur_y is None else (cur_y + y) / 2.0
        else:
            rows.append(cur)
            cur = [ln]
            cur_y = y
    if cur:
        rows.append(cur)
    return rows

def _row_text_sorted(row, rtl=False):
    return sorted(row, key=lambda l: (-l.x0 if rtl else l.x0, l.y0))

def _detect_form_name(lines):
    # Prefer large title around y~70-110, size ~15+
    candidates = []
    for ln in lines:
        if _is_header_or_footer(ln):
            continue
        t = _norm_space(ln.text)
        if not t:
            continue
        if ln.size >= 15 and 55 <= ln.y0 <= 120:
            candidates.append((ln.y0, -ln.size, ln.x0, t))
    if candidates:
        candidates.sort()
        return candidates[0][3]

    # Fallback: small bold header at y~48
    small = []
    for ln in lines:
        t = _norm_space(ln.text)
        if not t:
            continue
        if ln.bold and 6.5 <= ln.size <= 9.5 and 40 <= ln.y0 <= 60 and ln.x0 <= 80:
            if t.lower().startswith("variable details"):
                continue
            small.append((ln.y0, ln.x0, t))
    if small:
        small.sort()
        return small[0][2]

    # Cover page: "Visit:" + next line
    visit = None
    for ln in lines:
        if ln.size >= 18 and "visit" in ln.text.lower():
            visit = ln
            break
    if visit:
        below = [ln for ln in lines if ln.size >= 18 and ln.y0 > visit.y0 + 5]
        if below:
            below.sort(key=lambda l: l.y0)
            return _norm_space(visit.text) + " " + _norm_space(below[0].text)

    return ""

def _is_variable_details_page(lines):
    for ln in lines:
        if ln.bold and 6.5 <= ln.size <= 8.5 and 45 <= ln.y0 <= 62:
            if ln.text.strip().lower().startswith("variable details"):
                return True
    return False

def _extract_fields_variable_details(lines):
    # Table: columns at approx x=80 (Name), x=235 (Export Name), etc.
    # Extract "Name" column entries for each row that begins with [n] at x~41.
    rows = _cluster_rows([ln for ln in lines if not _is_header_or_footer(ln)], y_tol=2.2)
    fields = []
    for row in rows:
        idx_cell = None
        for ln in row:
            if 30 <= ln.x0 <= 60 and RE_PURE_BRACKET.match(ln.text.strip()):
                idx_cell = ln
                break
        if not idx_cell:
            continue

        name_cells = [ln for ln in row if 70 <= ln.x0 <= 220]
        if not name_cells:
            continue

        name_cells_sorted = sorted(name_cells, key=lambda l: l.x0)
        name_text = _norm_space(" ".join([c.text for c in name_cells_sorted]))
        if not name_text:
            continue
        if name_text.lower() == "name":
            continue
        if RE_MACHINE_CODE.match(name_text):
            continue

        fields.append(name_text)
    return fields

def _extract_fields_crf_page(lines):
    # Extract bold label lines (size ~6-11) excluding bracket-only and excluding option lists.
    content = [ln for ln in lines if not _is_header_or_footer(ln)]
    rows = _cluster_rows(content, y_tol=2.8)

    fields = []
    for row in rows:
        row_sorted = _row_text_sorted(row, rtl=False)

        bold_parts = []
        for ln in row_sorted:
            t = ln.text.strip()
            if not t:
                continue
            if RE_PURE_BRACKET.match(t):
                continue
            if RE_MACHINE_CODE.match(t) and ln.size <= 11:
                continue
            if ln.bold and 5.5 <= ln.size <= 11.5:
                bold_parts.append((ln.x0, t))

        if not bold_parts:
            continue

        joined = _norm_space(" ".join([p[1] for p in bold_parts]))
        if not joined:
            continue

        cleaned = _strip_bracket_codes(joined)
        if not cleaned:
            continue

        low = cleaned.lower()
        if low in ("variable details", "name", "export name", "type", "max length", "categories"):
            continue

        # Skip obvious section headers (large bold, centered-ish, no bracket codes)
        if len(RE_BRACKET_CODE.findall(joined)) == 0 and any(ln.size >= 10.2 for ln in row_sorted if ln.bold):
            # If it's short and looks like a banner header, ignore
            if len(cleaned.split()) <= 6 and cleaned.isupper():
                continue

        # Skip table header rows listing multiple columns
        bracket_count = len(RE_BRACKET_CODE.findall(joined))
        if bracket_count >= 3 and len(cleaned.split()) <= 12:
            continue

        # NEW: avoid capturing "Yes [n]" / "No" option tokens as fields
        # If the cleaned text is exactly/starts with common option words and contains a bracket code, treat as option.
        if re.match(r"^(yes|no|unknown|not done|none)\b", low) and bracket_count >= 1:
            continue

        min_x = min([p[0] for p in bold_parts]) if bold_parts else 0
        if _is_probably_option_text(cleaned) and min_x >= 180:
            continue

        # Split on bracket codes to recover multiple labels in one row
        tmp = re.sub(r"\s*\[\s*\d+\s*\]\s*", " | ", joined)
        parts = [_strip_bracket_codes(p) for p in tmp.split("|")]
        parts = [_norm_space(p) for p in parts if _norm_space(p)]

        plausible = []
        for p in parts:
            if not p:
                continue
            pl = p.lower()
            if RE_NUM_ONLY.match(p):
                continue
            if len(p) <= 2:
                continue
            if pl in ("yes", "no"):
                continue
            # also exclude "Yes" variants that slipped through splitting
            if re.fullmatch(r"(yes|no|unknown|not done|none)", pl):
                continue
            plausible.append(p)

        if len(plausible) >= 2:
            fields.extend(plausible)
        else:
            fields.append(cleaned)

    seen = set()
    out = []
    for f in fields:
        f = _norm_space(f)
        if not f:
            continue
        key = f.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out

def extract(pages):
    results = []
    seen_global = set()  # (form_name_lower, field_name_lower)
    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1
        if not lines:
            continue

        form = _detect_form_name(lines)
        if form:
            current_form = form

        if _is_variable_details_page(lines):
            fields = _extract_fields_variable_details(lines)
            form_name = current_form or form or "Variable details"
        else:
            fields = _extract_fields_crf_page(lines)
            form_name = current_form or form

        for field in fields:
            field = _norm_space(field)
            if not field:
                continue
            if RE_PURE_BRACKET.match(field):
                continue
            if RE_NUM_ONLY.match(field):
                continue
            if RE_MACHINE_CODE.match(field):
                continue
            if len(field) < 3:
                continue

            key = ((form_name or "").lower(), field.lower())
            if key in seen_global:
                continue
            seen_global.add(key)
            results.append({"form_name": form_name or "", "field_name": field, "page": page_num})

    return results