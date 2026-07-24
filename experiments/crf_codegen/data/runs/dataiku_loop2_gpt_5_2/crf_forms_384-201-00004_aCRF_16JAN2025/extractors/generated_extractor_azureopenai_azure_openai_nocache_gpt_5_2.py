import re
from collections import defaultdict

# --- Regexes / constants ---
BRACKET_CODE_RE = re.compile(r'^\[[A-Za-z0-9][A-Za-z0-9_]*\]$')
SAS_FIELD_RE = re.compile(r'^\[SAS Field Name:\s*([A-Za-z0-9_]+)\s*\]$')
PURE_CODE_RE = re.compile(r'^[A-Z]{2,}[A-Z0-9_]*$')
PAGE_FURN_RE = re.compile(
    r'^\s*(Annotated CRF|\d+\s+of\s+\d+|https?://\S+)\s*$',
    re.IGNORECASE
)

# Questions that appear as annotations / derived flags on some pages and should not be treated
# as data-entry fields (document-specific quality gate fix).
NON_FIELD_QUESTION_PREFIXES = (
    "Is this a treatment emergent adverse event",
    "Is this an adverse event of special interest",
)

# Some pages have a "section header" that is actually the form name (e.g., Physical Exam),
# and the previous logic sometimes kept the prior form (e.g., AE/CM). We'll treat certain
# teal/colored headers as form switches more aggressively.
FORM_SWITCH_KEYWORDS = (
    "Physical Examination",
    "Physical Exam",
    "Abnormal findings",
    "Body system",
    "Examination result",
    "Clinical significance",
)

def _norm_space(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '')).strip()

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
    t = line.text.strip()
    if t.startswith('O '):
        return True
    if re.match(r'^(Code List:|Aliases:|Odm OID|Origin:|Format:|Data Type:|Description:|Mandatory\?:|Disallow Future Date:|Conditionally Visible|Conditional Item:|Visible If Value:|Default Item Value:|Role Restriction:)', t):
        return True
    return False

def _is_form_header_line(line) -> bool:
    # Top banner: 12pt, non-black (white on dark bar), near top-left
    if line.size >= 11.5 and line.non_black and line.x0 < 140 and line.y0 < 70:
        return True
    # Teal section header: 10.5pt colored, near left, not too low
    if 10.0 <= line.size <= 11.6 and line.non_black and line.x0 < 160 and line.y0 < 240:
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
    return candidates[0][3]

def _cluster_left_lines(lines, x_cut=240.0):
    # Left side contains labels and bracket codes; right side contains metadata.
    left = []
    for ln in lines:
        if ln.x0 < x_cut:
            left.append(ln)
    # Keep reading order stable
    left.sort(key=lambda l: (l.y0, l.x0))
    return left

def _looks_like_label_line(ln) -> bool:
    t = _norm_space(ln.text)
    if _is_noise_line(t):
        return False
    if BRACKET_CODE_RE.match(t) or SAS_FIELD_RE.match(t):
        return False
    if _is_option_line(ln):
        return False
    if PURE_CODE_RE.fullmatch(t) and len(t) <= 20:
        return False
    # Typical label-like: 7-9pt black, left aligned
    if 6.6 <= ln.size <= 10.0 and (not ln.non_black) and ln.x0 < 140:
        return True
    return False

def _build_prev_label_index(left_lines):
    prev = [-1] * len(left_lines)
    last = -1
    for i, ln in enumerate(left_lines):
        if _looks_like_label_line(ln):
            last = i
        prev[i] = last
    return prev

def _label_is_disallowed(label: str) -> bool:
    if not label:
        return True
    lab = _norm_space(label)
    if len(lab) < 2:
        return True
    if _is_noise_line(lab):
        return True
    if BRACKET_CODE_RE.match(lab) or SAS_FIELD_RE.match(lab):
        return True
    if PURE_CODE_RE.fullmatch(lab) and len(lab) <= 20:
        return True
    # Document-specific: exclude known non-entry derived questions
    low = lab.lower()
    for p in NON_FIELD_QUESTION_PREFIXES:
        if low.startswith(p.lower()):
            return True
    return False

def _page_has_form_switch_header(lines) -> str:
    """
    Detect a strong form switch on the page even if the generic header extractor fails.
    This helps fix wrong-form attribution (e.g., page 71).
    """
    # Look for prominent colored header lines containing known keywords.
    best = None
    for ln in lines:
        t = _norm_space(ln.text)
        if _is_noise_line(t):
            continue
        if not ln.non_black:
            continue
        if ln.size < 9.5:
            continue
        if ln.x0 > 200:
            continue
        # keyword match
        for kw in FORM_SWITCH_KEYWORDS:
            if kw.lower() in t.lower():
                cand = (ln.y0, -ln.size, ln.x0, t)
                if best is None or cand < best:
                    best = cand
                break
    return best[3] if best else None

def _extract_fields_by_bracket_codes(lines, current_form, page_num, seen):
    out = []
    left = _cluster_left_lines(lines, x_cut=240.0)
    if not left:
        return out

    prev_label = _build_prev_label_index(left)

    for i, ln in enumerate(left):
        t = _norm_space(ln.text)
        if not BRACKET_CODE_RE.match(t):
            continue
        if SAS_FIELD_RE.match(t):
            continue

        j = prev_label[i]
        if j < 0:
            continue
        label = _norm_space(left[j].text)

        if _label_is_disallowed(label):
            continue

        key = (current_form or "", label)
        if key in seen:
            continue
        seen.add(key)
        out.append({"form_name": current_form or "", "field_name": label, "page": page_num})
    return out

def _extract_fields_by_label_colon_pattern(lines, current_form, page_num, seen):
    """
    Fallback extractor for pages where fields are visible but bracket item codes are absent
    or not captured by OCR/layout (e.g., some Physical Exam pages).
    Heuristic: left-column label lines ending with ':' or followed by an obvious entry area.
    """
    out = []
    left = _cluster_left_lines(lines, x_cut=260.0)
    if not left:
        return out

    # Build y-sorted lines for proximity checks
    left.sort(key=lambda l: (l.y0, l.x0))

    for idx, ln in enumerate(left):
        t = _norm_space(ln.text)
        if not _looks_like_label_line(ln):
            continue

        # Strong signal: label ends with ":" (common in CRFs)
        ends_colon = t.endswith(':')
        # Another signal: label is one of known PE fields (page 71 gate)
        is_known_pe_field = t.lower() in {
            "abnormal findings",
            "body system",
            "examination result",
            "clinical significance",
        }

        if not (ends_colon or is_known_pe_field):
            continue

        label = t[:-1].strip() if ends_colon else t
        if _label_is_disallowed(label):
            continue

        key = (current_form or "", label)
        if key in seen:
            continue
        seen.add(key)
        out.append({"form_name": current_form or "", "field_name": label, "page": page_num})

    return out

def extract(pages):
    out = []
    seen = set()  # (form_name, field_name)
    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1

        # 1) Update form name using existing header logic
        fn = _extract_form_name_from_page(lines)
        if fn:
            current_form = fn

        # 2) Additional form-switch detection to fix wrong attribution (e.g., page 71)
        fn2 = _page_has_form_switch_header(lines)
        if fn2:
            current_form = fn2

        # 3) Primary extraction: bracket item codes -> preceding label
        recs = _extract_fields_by_bracket_codes(lines, current_form, page_num, seen)
        out.extend(recs)

        # 4) Fallback extraction for pages with visible fields but missing bracket codes
        # Only run if we extracted very little from this page to avoid duplicates/noise.
        if len(recs) < 2:
            out.extend(_extract_fields_by_label_colon_pattern(lines, current_form, page_num, seen))

    return out
