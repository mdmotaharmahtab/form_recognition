```python
# Observed layouts: (1) CRF pages with a bold small header at y~48 and a large title at y~74,
# followed by bold field labels (often with bracketed item numbers) and non-bold answer options.
# (2) "Variable details" dictionary pages: table with columns; field label is in the "Name" column.
# Strategy: detect form_name from large title (preferred) or small bold header; then extract fields
# from bold label lines while excluding machine codes ([n], export names) and excluding answer options.

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
    # Options are typically short, non-bold, and often numeric or simple words.
    s = _norm_space(s)
    if not s:
        return True
    if RE_PURE_BRACKET.match(s):
        return True
    if RE_NUM_ONLY.match(s):
        return True
    # very short tokens are often options (Yes/No/etc.) or row numbers
    if len(s) <= 3:
        return True
    # common checkbox/radio style tokens (language-agnostic-ish)
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
    # page furniture like "Visit:" cover page handled separately; otherwise ignore very large centered
    return False

def _cluster_rows(lines, y_tol=2.5):
    rows = []
    cur = []
    cur_y = None
    for ln in lines:
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
    # default LTR: sort by x0
    row_sorted = sorted(row, key=lambda l: (-l.x0 if rtl else l.x0, l.y0))
    return row_sorted

def _detect_form_name(lines):
    # Prefer large title around y~70-90, size ~17+
    candidates = []
    for ln in lines:
        if _is_header_or_footer(ln):
            continue
        t = _norm_space(ln.text)
        if not t:
            continue
        if ln.size >= 15 and 55 <= ln.y0 <= 110:
            # likely form title
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
            # avoid "Variable details"
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
        # find next large line below
        below = [ln for ln in lines if ln.size >= 18 and ln.y0 > visit.y0 + 5]
        if below:
            below.sort(key=lambda l: l.y0)
            return _norm_space(visit.text) + " " + _norm_space(below[0].text)

    return ""

def _is_variable_details_page(lines):
    for ln in lines:
        if ln.bold and 6.5 <= ln.size <= 8.0 and 45 <= ln.y0 <= 60:
            if ln.text.strip().lower().startswith("variable details"):
                return True
    return False

def _extract_fields_variable_details(lines):
    # Table: columns at approx x=80 (Name), x=235 (Export Name), etc.
    # Extract "Name" column entries for each row that begins with [n] at x~41.
    rows = _cluster_rows([ln for ln in lines if not _is_header_or_footer(ln)], y_tol=2.2)
    fields = []
    for row in rows:
        # find bracket index cell
        idx_cell = None
        for ln in row:
            if 30 <= ln.x0 <= 60 and RE_PURE_BRACKET.match(ln.text.strip()):
                idx_cell = ln
                break
        if not idx_cell:
            continue
        # find name cell near x~80-200
        name_cells = [ln for ln in row if 70 <= ln.x0 <= 220]
        if not name_cells:
            continue
        # ignore header row "Name"
        name_cells_sorted = sorted(name_cells, key=lambda l: l.x0)
        name_text = _norm_space(" ".join([c.text for c in name_cells_sorted]))
        if not name_text:
            continue
        if name_text.lower() == "name":
            continue
        # Exclude if it looks like machine code
        if RE_MACHINE_CODE.match(name_text):
            continue
        fields.append(name_text)
    return fields

def _extract_fields_crf_page(lines):
    # Extract bold label lines (size ~6-9) excluding bracket-only and excluding option lists.
    content = [ln for ln in lines if not _is_header_or_footer(ln)]
    rows = _cluster_rows(content, y_tol=2.6)

    fields = []
    for row in rows:
        # sort by x for LTR
        row_sorted = _row_text_sorted(row, rtl=False)

        # Build segments: bold label segments vs others
        bold_parts = []
        for ln in row_sorted:
            t = ln.text.strip()
            if not t:
                continue
            # ignore pure bracket codes
            if RE_PURE_BRACKET.match(t):
                continue
            # ignore machine codes in CRF pages (rare)
            if RE_MACHINE_CODE.match(t) and ln.size <= 9:
                continue
            if ln.bold and 5.5 <= ln.size <= 10.5:
                bold_parts.append((ln.x0, t))

        if not bold_parts:
            continue

        # Join bold parts in the row; then split into multiple fields if pattern "  [n] " repeats.
        joined = _norm_space(" ".join([p[1] for p in bold_parts]))
        if not joined:
            continue

        # Remove bracket codes and normalize
        cleaned = _strip_bracket_codes(joined)
        if not cleaned:
            continue

        # Exclude table column headers that are not fields (heuristic: many short tokens and/or ends with "Categories")
        low = cleaned.lower()
        if low in ("variable details", "name", "export name", "type", "max length", "categories"):
            continue

        # Exclude lines that are clearly just section/table headers like "Test  [5] Not Done [6] Interpretation [7] ..."
        # Heuristic: if after stripping codes it contains 3+ distinct short header-like chunks separated by two spaces in original,
        # or contains many bracket codes originally.
        bracket_count = len(RE_BRACKET_CODE.findall(joined))
        if bracket_count >= 3 and len(cleaned.split()) <= 12:
            # likely a table header row listing multiple columns
            continue

        # Exclude if it is likely an answer option line (usually non-bold, but sometimes bold for first option)
        # If the cleaned text is very short and appears at x>180 (options column), skip.
        min_x = min([p[0] for p in bold_parts]) if bold_parts else 0
        if _is_probably_option_text(cleaned) and min_x >= 180:
            continue

        # Sometimes a row contains multiple field labels separated by bracket codes; attempt to split by detecting "  " around codes.
        # We'll split on occurrences of bracket codes in the original joined string by inserting separators.
        tmp = joined
        tmp = re.sub(r"\s*\[\s*\d+\s*\]\s*", " | ", tmp)
        parts = [_strip_bracket_codes(p) for p in tmp.split("|")]
        parts = [_norm_space(p) for p in parts if _norm_space(p)]
        # If splitting yields multiple plausible labels, use them; else use cleaned.
        plausible = []
        for p in parts:
            if not p:
                continue
            if RE_NUM_ONLY.match(p):
                continue
            if len(p) <= 2:
                continue
            if p.lower() in ("yes", "no"):
                continue
            plausible.append(p)

        if len(plausible) >= 2:
            for p in plausible:
                # avoid duplicates within same row
                fields.append(p)
        else:
            fields.append(cleaned)

    # De-dup while preserving order
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
            # final filters: avoid bare codes/brackets/numbers
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
```