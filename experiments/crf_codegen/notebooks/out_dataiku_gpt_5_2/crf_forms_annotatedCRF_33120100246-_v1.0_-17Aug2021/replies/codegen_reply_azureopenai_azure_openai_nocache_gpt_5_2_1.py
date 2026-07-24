```python
# Observed layouts: (1) TOC pages with blue numbered section titles; (2) CRF pages
# where the form/section title is a large blue line near top; (3) fields are black
# labels (often 7.8pt) followed by red bracketed machine codes and red [TYPE: ...].
# Strategy: detect current form_name from the top blue title; extract field labels
# as the nearest preceding black label line(s) before each red [TYPE:] line, while
# skipping answer options and other non-field furniture; de-duplicate per form.

import re
from collections import defaultdict

RE_CODE = re.compile(r'^\[[A-Z0-9_]+\]$')
RE_TYPE = re.compile(r'^\[TYPE\s*:\s*', re.I)
RE_VIS = re.compile(r'^\[VISIBILITY\s*:', re.I)
RE_READONLY = re.compile(r'^\[Read-only field\]$', re.I)
RE_BRACKET_ANY = re.compile(r'^\[.*\]$')
RE_TOC_ITEM = re.compile(r'^\s*\d+(\.\d+)+\.\s+.+')
RE_PAGE_FURN = re.compile(r'^(Pack Version|Annotated CRF|CHANGE HISTORY|SCHEDULE OF ASSESSMENT|PAGES)\b', re.I)
RE_ROW = re.compile(r'^\s*Row\s+\d+\s*$', re.I)

def _norm(s: str) -> str:
    s = re.sub(r'\s+', ' ', (s or '').strip())
    return s

def _is_probably_option(line):
    # Options are often grey (#454545) and 9.2pt, short tokens like Yes/No/NA.
    t = _norm(line.text)
    if not t:
        return True
    if line.non_black and not RE_BRACKET_ANY.match(t):
        # colored non-bracket text is usually TOC or headers; options are grey too
        # but we don't want to treat them as labels anyway.
        pass
    if len(t) <= 4 and re.fullmatch(r'[A-Za-z]{1,4}', t):
        return True
    if re.fullmatch(r'(Yes|No|N/?A|NA|Unknown|Not Done|Positive|Negative|Scan)', t, re.I):
        return True
    # very short single-word tokens at right side are likely options
    if len(t) <= 12 and ' ' not in t and line.x0 > 350 and line.size >= 8.5:
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
    if line.non_black and line.size >= 12.0 and line.y0 < 120:
        return True
    return False

def _extract_form_title(lines):
    # Choose the most prominent colored header near top.
    cands = [ln for ln in lines if _is_header_candidate(ln)]
    if not cands:
        return None
    # Prefer largest font, then highest on page.
    cands.sort(key=lambda l: (-l.size, l.y0, l.x0))
    title = _norm(cands[0].text)
    # Avoid TOC items like "3.1. Visit Date" (blue but smaller ~13.1 and many per page)
    if RE_TOC_ITEM.match(title) and cands[0].size <= 13.5:
        return None
    return title

def _build_reading_order(lines):
    # Mostly single column; still, sort by y then x with row clustering.
    # Cluster by y within tolerance to order left-to-right within same row.
    if not lines:
        return []
    tol = 2.0
    rows = []
    cur = [lines[0]]
    yref = lines[0].y0
    for ln in lines[1:]:
        if abs(ln.y0 - yref) <= tol:
            cur.append(ln)
        else:
            cur.sort(key=lambda l: l.x0)
            rows.extend(cur)
            cur = [ln]
            yref = ln.y0
    cur.sort(key=lambda l: l.x0)
    rows.extend(cur)
    return rows

def _collect_label_before_type(ordered, idx_type):
    """
    Given ordered lines and index of a [TYPE:] line, find the field label text
    immediately preceding the code/[TYPE] block.
    """
    # Walk backwards skipping machine annotations and options; collect up to 3 label lines.
    labels = []
    y_type = ordered[idx_type].y0
    # stop if too far away vertically
    max_dy = 90.0
    i = idx_type - 1
    while i >= 0:
        ln = ordered[i]
        t = _norm(ln.text)
        if not t:
            i -= 1
            continue
        if (y_type - ln.y0) > max_dy:
            break
        # stop at form title/header
        if _is_header_candidate(ln):
            break
        # skip machine/annotation lines
        if _is_machine_or_annotation(ln):
            i -= 1
            continue
        # skip row markers and table column headers (often 9.2 black, centered)
        if RE_ROW.match(t):
            i -= 1
            continue
        if _is_probably_option(ln):
            i -= 1
            continue
        # likely label line: black, small font, left-ish
        # Accept also bold question lines.
        if ln.x0 <= 120 or ln.size <= 9.0:
            labels.append((ln.y0, ln.x0, t))
            # continue to capture wrapped label lines directly above
            i -= 1
            continue
        # if it's far right and not small, likely not label
        i -= 1

    if not labels:
        return None

    # labels collected bottom-up; keep those closest to type and merge in reading order.
    labels.sort(key=lambda z: (z[0], z[1]))
    # Heuristic: keep only last contiguous block near bottom (avoid grabbing earlier paragraph text)
    # Determine bottom-most y and keep lines within 25pt above it.
    bottom_y = max(y for y, _, _ in labels)
    kept = [(y, x, t) for (y, x, t) in labels if bottom_y - y <= 28.0]
    kept.sort(key=lambda z: (z[0], z[1]))
    text = _norm(' '.join(t for _, _, t in kept))
    # Filter out pure punctuation or too generic
    if not text or len(text) < 2:
        return None
    # Avoid capturing instructional paragraphs (long sentences) unless they look like a question/label.
    if len(text) > 220:
        return None
    return text

def extract(pages):
    out = []
    seen = set()  # (form_name_norm, field_name_norm)
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        # Update form name if a header title is present.
        title = _extract_form_title(lines)
        if title:
            current_form = title

        ordered = _build_reading_order(lines)

        # Identify [TYPE:] lines; each corresponds to a data-entry field.
        for i, ln in enumerate(ordered):
            t = _norm(ln.text)
            if not t:
                continue
            if not RE_TYPE.match(t):
                continue

            label = _collect_label_before_type(ordered, i)
            if not label:
                continue

            # Exclude TOC items and obvious furniture
            if RE_TOC_ITEM.match(label):
                continue
            if RE_PAGE_FURN.match(label):
                continue

            form_name = _norm(current_form)
            field_name = _norm(label)

            # Final sanity: field_name should not be just a number/date-like token
            if re.fullmatch(r'[\d\W]+', field_name):
                continue
            if re.fullmatch(r'\d{1,2}[A-Za-z]{3}\d{4}', field_name):  # e.g., 17Aug2021
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
```