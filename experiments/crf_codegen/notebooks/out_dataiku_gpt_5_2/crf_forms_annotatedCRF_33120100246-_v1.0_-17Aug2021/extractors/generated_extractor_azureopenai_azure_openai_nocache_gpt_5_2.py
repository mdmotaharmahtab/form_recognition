import re

RE_CODE = re.compile(r'^\[[A-Z0-9_]+\]$')
RE_TYPE = re.compile(r'^\[TYPE\s*:\s*', re.I)
RE_VIS = re.compile(r'^\[VISIBILITY\s*:', re.I)
RE_READONLY = re.compile(r'^\[Read-only field\]$', re.I)
RE_BRACKET_ANY = re.compile(r'^\[.*\]$')
RE_TOC_ITEM = re.compile(r'^\s*\d+(\.\d+)+\.\s+.+')
RE_PAGE_FURN = re.compile(r'^(Pack Version|Annotated CRF|CHANGE HISTORY|SCHEDULE OF ASSESSMENT|PAGES)\b', re.I)
RE_ROW = re.compile(r'^\s*Row\s+\d+\s*$', re.I)

def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '').strip())

def _is_probably_option(line):
    # Options are often grey (#454545) and 9.2pt, short tokens like Yes/No/NA.
    t = _norm(line.text)
    if not t:
        return True
    if len(t) <= 4 and re.fullmatch(r'[A-Za-z]{1,4}', t):
        return True
    if re.fullmatch(r'(Yes|No|N/?A|NA|Unknown|Not Done|Positive|Negative|Scan)', t, re.I):
        return True
    # very short single-word tokens at right side are likely options
    if len(t) <= 12 and ' ' not in t and getattr(line, "x0", 0) > 350 and getattr(line, "size", 0) >= 8.5:
        return True
    return False

def _is_machine_or_annotation(line):
    t = _norm(line.text)
    if not t:
        return True
    if RE_TYPE.match(t) or RE_VIS.match(t) or RE_READONLY.match(t):
        return True
    if RE_CODE.match(t):
        return True
    # other bracketed annotations are not labels
    if RE_BRACKET_ANY.match(t):
        return True
    return False

def _is_header_candidate(line):
    t = _norm(line.text)
    if not t:
        return False
    if RE_PAGE_FURN.match(t):
        return False
    # Form titles are typically blue and larger (e.g., 14.4) near top.
    if getattr(line, "non_black", False) and getattr(line, "size", 0) >= 12.0 and getattr(line, "y0", 9999) < 120:
        return True
    return False

def _extract_form_title(lines):
    # Choose the most prominent colored header near top.
    cands = [ln for ln in lines if _is_header_candidate(ln)]
    if not cands:
        return None
    # Prefer largest font, then highest on page.
    cands.sort(key=lambda l: (-getattr(l, "size", 0), getattr(l, "y0", 0), getattr(l, "x0", 0)))
    title = _norm(cands[0].text)
    # Avoid TOC items like "3.1. Visit Date" (blue but smaller ~13.1 and many per page)
    if RE_TOC_ITEM.match(title) and getattr(cands[0], "size", 0) <= 13.5:
        return None
    return title

def _build_reading_order(lines):
    # Mostly single column; still, sort by y then x with row clustering.
    if not lines:
        return []
    lines = sorted(lines, key=lambda l: (getattr(l, "y0", 0), getattr(l, "x0", 0)))
    tol = 2.0
    rows = []
    cur = [lines[0]]
    yref = getattr(lines[0], "y0", 0)
    for ln in lines[1:]:
        y = getattr(ln, "y0", 0)
        if abs(y - yref) <= tol:
            cur.append(ln)
        else:
            cur.sort(key=lambda l: getattr(l, "x0", 0))
            rows.extend(cur)
            cur = [ln]
            yref = y
    cur.sort(key=lambda l: getattr(l, "x0", 0))
    rows.extend(cur)
    return rows

def _collect_label_before_type(ordered, idx_type):
    """
    Given ordered lines and index of a [TYPE:] line, find the field label text
    immediately preceding the code/[TYPE] block.
    """
    labels = []
    y_type = getattr(ordered[idx_type], "y0", 0)
    max_dy = 90.0
    i = idx_type - 1
    while i >= 0:
        ln = ordered[i]
        t = _norm(ln.text)
        if not t:
            i -= 1
            continue
        if (y_type - getattr(ln, "y0", 0)) > max_dy:
            break
        if _is_header_candidate(ln):
            break
        if _is_machine_or_annotation(ln):
            i -= 1
            continue
        if RE_ROW.match(t):
            i -= 1
            continue
        if _is_probably_option(ln):
            i -= 1
            continue

        # likely label line: black, small font, left-ish
        if getattr(ln, "x0", 0) <= 120 or getattr(ln, "size", 0) <= 9.0:
            labels.append((getattr(ln, "y0", 0), getattr(ln, "x0", 0), t))
            i -= 1
            continue

        i -= 1

    if not labels:
        return None

    labels.sort(key=lambda z: (z[0], z[1]))
    bottom_y = max(y for y, _, _ in labels)
    kept = [(y, x, t) for (y, x, t) in labels if bottom_y - y <= 28.0]
    kept.sort(key=lambda z: (z[0], z[1]))
    text = _norm(' '.join(t for _, _, t in kept))
    if not text or len(text) < 2:
        return None
    if len(text) > 220:
        return None
    return text

def _collect_label_left_of_type(ordered, idx_type):
    """
    NEW: Handle table-like layouts where the field label is in a left column and
    the [CODE]/[TYPE:] block is in a right column on the same row band.
    Example: C-SSRS Page 2 where labels like "Most severe ideation" are at x~45
    and [TYPE:] is at x~353.
    """
    type_ln = ordered[idx_type]
    y_type = getattr(type_ln, "y0", 0)
    x_type = getattr(type_ln, "x0", 0)

    # Search a horizontal band around the TYPE line for left-column label candidates.
    band = 26.0
    cands = []
    for ln in ordered:
        t = _norm(ln.text)
        if not t:
            continue
        y = getattr(ln, "y0", 0)
        x = getattr(ln, "x0", 0)
        if abs(y - y_type) > band:
            continue
        if x >= x_type - 40:  # must be meaningfully left of the type block
            continue
        if _is_header_candidate(ln):
            continue
        if _is_machine_or_annotation(ln):
            continue
        if RE_ROW.match(t):
            continue
        if _is_probably_option(ln):
            continue
        # Avoid grabbing long instructional paragraph lines in the left column.
        if len(t) > 160:
            continue
        # Prefer bold-ish short labels; we don't have bold flag reliably, so use size/position.
        cands.append((abs(y - y_type), -x, y, x, t))

    if not cands:
        return None

    # Choose closest in y; if tie, prefer further-left (smaller x).
    cands.sort()
    best = cands[0]
    label = best[-1]

    # If the chosen label is a generic section header, try to extend with the next line below
    # only when it looks like a question (ends with ?), but keep it conservative.
    return _norm(label)

def extract(pages):
    out = []
    seen = set()  # (form_name_norm, field_name_norm)
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        title = _extract_form_title(lines)
        if title:
            current_form = title

        ordered = _build_reading_order(lines)

        for i, ln in enumerate(ordered):
            t = _norm(ln.text)
            if not t:
                continue
            if not RE_TYPE.match(t):
                continue

            # Primary strategy (existing): label immediately above the code/[TYPE] block.
            label = _collect_label_before_type(ordered, i)

            # NEW fallback: table/two-column layouts where label is left of [TYPE:].
            if not label:
                label = _collect_label_left_of_type(ordered, i)

            if not label:
                continue

            if RE_TOC_ITEM.match(label):
                continue
            if RE_PAGE_FURN.match(label):
                continue

            form_name = _norm(current_form)
            field_name = _norm(label)

            if re.fullmatch(r'[\d\W]+', field_name):
                continue
            if re.fullmatch(r'\d{1,2}[A-Za-z]{3}\d{4}', field_name):
                continue

            key = (form_name.lower(), field_name.lower())
            if key in seen:
                continue
            seen.add(key)

            out.append({
                "form_name": form_name,
                "field_name": field_name,
                "page": page_idx0 + 1
            })

    return out
