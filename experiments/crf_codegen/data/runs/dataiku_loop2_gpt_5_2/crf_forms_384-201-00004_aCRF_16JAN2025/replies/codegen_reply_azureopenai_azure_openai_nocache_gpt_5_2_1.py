```python
# Observed layouts: (1) cover/table pages without data-entry fields; (2) main annotated CRF pages
# where each field is a left-side question/label (7.5pt black) paired with a bracketed item code
# line like "[XXXX]" and right-side technical annotations (5.6pt) including bold variable names.
# Strategy: detect form/section name from the top banner (12pt white) or teal section headers
# (10.5pt colored). Extract field labels by finding bracketed item-code lines at left and taking
# the nearest preceding non-bracket label line; ignore code lists/options and right-side metadata.

import re
from collections import defaultdict

BRACKET_CODE_RE = re.compile(r'^\[[A-Za-z0-9][A-Za-z0-9_]*\]$')
SAS_FIELD_RE = re.compile(r'^\[SAS Field Name:\s*([A-Za-z0-9_]+)\s*\]$')
PURE_CODE_RE = re.compile(r'^[A-Z]{2,}[A-Z0-9_]*$')
PAGE_FURN_RE = re.compile(r'^\s*(Annotated CRF|\d+\s+of\s+\d+|https?://\S+)\s*$',
                          re.IGNORECASE)

def _norm_space(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()

def _is_noise_line(t: str) -> bool:
    if not t:
        return True
    if PAGE_FURN_RE.match(t):
        return True
    # study id like 384-201-00004
    if re.fullmatch(r'\d{2,4}-\d{2,4}-\d{3,6}', t):
        return True
    return False

def _is_option_line(line) -> bool:
    # Radio/checkbox options often start with "O " at x around 240-260
    t = line.text.strip()
    if t.startswith('O '):
        return True
    # Code list / aliases / origin etc are not labels
    if re.match(r'^(Code List:|Aliases:|Odm OID|Origin:|Format:|Data Type:|Description:|Mandatory\?:|Disallow Future Date:|Conditionally Visible|Conditional Item:|Visible If Value:|Default Item Value:|Role Restriction:)', t):
        return True
    return False

def _is_form_header_line(line) -> bool:
    # Top banner: 12pt, non-black (white on dark bar), near top-left
    if line.size >= 11.5 and line.non_black and line.x0 < 120 and line.y0 < 60:
        return True
    # Teal section header: 10.5pt, non-black, near left, not too low
    if 10.0 <= line.size <= 11.2 and line.non_black and line.x0 < 120 and line.y0 < 200:
        return True
    return False

def _extract_form_name_from_page(lines):
    # Prefer top banner (12pt white), else first teal header (10.5 colored)
    candidates = []
    for ln in lines:
        t = _norm_space(ln.text)
        if _is_noise_line(t):
            continue
        if _is_form_header_line(ln):
            candidates.append((ln.y0, -ln.size, ln.x0, t))
    if not candidates:
        return None
    candidates.sort()
    # Sometimes there are multiple headers; take the earliest/topmost
    return candidates[0][3]

def _cluster_left_lines(lines, x_cut=220.0):
    # Left side contains labels and bracket codes; right side contains metadata.
    left = []
    for ln in lines:
        if ln.x0 < x_cut:
            left.append(ln)
    return left

def _build_prev_label_index(left_lines):
    # For each line index, store nearest preceding "label-like" line index.
    prev = [-1] * len(left_lines)
    last = -1
    for i, ln in enumerate(left_lines):
        t = _norm_space(ln.text)
        if _is_noise_line(t):
            prev[i] = last
            continue
        # Exclude bracket codes and SAS field name lines and obvious options
        if BRACKET_CODE_RE.match(t) or SAS_FIELD_RE.match(t):
            prev[i] = last
            continue
        if _is_option_line(ln):
            prev[i] = last
            continue
        # Exclude pure machine codes
        if PURE_CODE_RE.fullmatch(t) and len(t) <= 20:
            prev[i] = last
            continue
        # Label-like: typical 7-9pt black, left aligned
        if 6.8 <= ln.size <= 9.5 and (not ln.non_black) and ln.x0 < 120:
            last = i
        prev[i] = last
    return prev

def extract(pages):
    out = []
    seen = set()  # (form_name, field_name)
    current_form = ""

    for page_idx0, lines in pages:
        # Update form name if present on this page
        fn = _extract_form_name_from_page(lines)
        if fn:
            current_form = fn

        # Work only with left column for field extraction
        left = _cluster_left_lines(lines, x_cut=220.0)
        if not left:
            continue

        prev_label = _build_prev_label_index(left)

        # Find bracketed item-code lines and map to nearest preceding label
        for i, ln in enumerate(left):
            t = _norm_space(ln.text)
            if not BRACKET_CODE_RE.match(t):
                continue
            # Exclude bracketed SAS field name lines (different pattern)
            if SAS_FIELD_RE.match(t):
                continue
            # Find label above
            j = prev_label[i]
            if j < 0:
                continue
            label = _norm_space(left[j].text)
            if not label or _is_noise_line(label):
                continue
            # Avoid capturing the bracket code itself as label
            if BRACKET_CODE_RE.match(label) or SAS_FIELD_RE.match(label):
                continue
            # Avoid labels that are just punctuation or too short
            if len(label) < 2:
                continue
            # Avoid labels that look like page furniture or pure codes
            if PURE_CODE_RE.fullmatch(label) and len(label) <= 20:
                continue

            form_name = current_form or ""
            key = (form_name, label)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})

    return out
```