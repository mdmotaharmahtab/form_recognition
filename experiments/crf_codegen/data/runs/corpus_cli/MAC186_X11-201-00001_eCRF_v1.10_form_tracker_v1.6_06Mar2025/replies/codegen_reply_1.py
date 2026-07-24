# Layout: Viedoc-style eCRF book with two repeating field-bearing layouts. (A) Form
# pages: bold breadcrumb form name ~y=48 under the doc-id header, large (size>=14)
# title, bold ~7.8pt field labels each tied to a printed [n] marker (standalone at the
# right, inline after table-column headers, or on a bold "Yes" option line). (B)
# "Variable details" pages: [n]|Name|Export Name|... table; Name column holds labels.
# Strategy: carry form name across pages; anchor labels to markers / Name column x.

import re

_MARK = re.compile(r'\[\s*\d{1,3}\s*\]')
_FULLMARK = re.compile(r'^\[\s*\d{1,3}\s*\]$')
_OPTION_WORDS = {"yes", "no", "unknown", "na", "n/a", "not applicable"}


def _norm(s):
    return re.sub(r'\s+', ' ', s).strip()


def _clean_label(s):
    return _norm(s).strip(':').strip()


def _has_letter(s):
    return re.search(r'[A-Za-z]', s) is not None


def _is_option(s):
    return _clean_label(s).lower() in _OPTION_WORDS


def _var_page_name_x(lines):
    # Returns x0 of the Name column if this is a "Variable details" page, else None.
    exp = None
    for l in lines:
        if l.bold and _norm(l.text).lower() == 'export name':
            exp = l
            break
    has_vd = any(_norm(l.text).lower() == 'variable details' for l in lines)
    if exp is None and not has_vd:
        return None
    if exp is not None:
        for l in lines:
            if (l.bold and _norm(l.text).lower() == 'name'
                    and abs(l.y0 - exp.y0) <= 3.0):
                return l.x0
    # Fallback: infer Name column as first cell right of a row marker.
    marks = sorted((l for l in lines if _FULLMARK.match(l.text.strip())),
                   key=lambda l: l.y0)
    for m in marks:
        row = [l for l in lines
               if l is not m and abs(l.y0 - m.y0) <= 2.0 and l.x0 > m.x1]
        if row:
            return min(row, key=lambda l: l.x0).x0
    return None


def _parse_var_page(lines, name_x):
    # Each [n] marker in the leftmost column starts one row; the field label is the
    # (possibly wrapped) text in the Name column between this marker and the next.
    marks = sorted((l for l in lines
                    if _FULLMARK.match(l.text.strip()) and l.x0 < name_x - 5.0),
                   key=lambda l: l.y0)
    names = []
    for i, m in enumerate(marks):
        y_lo = m.y0 - 3.0
        y_hi = marks[i + 1].y0 - 3.0 if i + 1 < len(marks) else float('inf')
        parts = sorted((l for l in lines
                        if abs(l.x0 - name_x) <= 3.0 and y_lo <= l.y0 < y_hi),
                       key=lambda l: (l.y0, l.x0))
        name = _clean_label(' '.join(p.text for p in parts))
        if name and _has_letter(name) and not _FULLMARK.match(name):
            names.append(name)
    return names


def _form_title(lines):
    big = sorted((l for l in lines
                  if l.size >= 14.0 and l.y0 < 150.0 and _has_letter(l.text)),
                 key=lambda l: (l.y0, l.x0))
    if not big:
        return None
    group = [big[0]]
    for b in big[1:]:
        if b.y0 - group[-1].y0 <= max(b.size, group[-1].size) * 1.6:
            group.append(b)
        else:
            break
    return _clean_label(' '.join(g.text for g in group))


def _breadcrumb(lines):
    for l in lines:
        if (l.bold and l.size < 10.0 and 40.0 < l.y0 < 64.0 and l.x0 < 60.0
                and _has_letter(l.text) and not _MARK.search(l.text)):
            t = _norm(l.text)
            if t.lower() != 'variable details':
                return t
    return None


def _left_label(mline, bolds):
    # Label for a marker with no usable inline text: nearest bold line on the same
    # row to the left, extended over vertically adjacent wrapped label lines.
    def ok(b):
        return (b is not mline and not _MARK.search(b.text)
                and not _is_option(b.text) and _has_letter(b.text)
                and b.x0 < mline.x0 - 1.0)

    cands = [b for b in bolds if ok(b) and abs(b.y0 - mline.y0) <= 6.5]
    if not cands:
        return None
    anchor = min(cands, key=lambda b: (abs(b.y0 - mline.y0), -b.x1))
    pool = sorted((b for b in bolds if ok(b)), key=lambda b: (b.y0, b.x0))
    ai = next(i for i, b in enumerate(pool) if b is anchor)
    lo = hi = ai
    while lo - 1 >= 0 and 0.0 < pool[lo].y0 - pool[lo - 1].y0 <= 9.5:
        lo -= 1
    while hi + 1 < len(pool) and 0.0 < pool[hi + 1].y0 - pool[hi].y0 <= 9.5:
        hi += 1
    return _clean_label(' '.join(b.text for b in pool[lo:hi + 1]))


def _parse_form_page(lines):
    # Every data-entry field on a visual form page carries a [n] marker. The label is
    # the inline text preceding the marker (table headers), or - when that text is
    # empty or a bare choice word like "Yes" - the bold label to the left of it.
    small = [l for l in lines if l.size < 10.0 and l.y0 > 60.0]
    bolds = [l for l in small if l.bold]
    labels = []
    for l in small:
        matches = list(_MARK.finditer(l.text))
        if not matches:
            continue
        prev_end = 0
        for m in matches:
            pre = _clean_label(l.text[prev_end:m.start()])
            prev_end = m.end()
            if pre and _has_letter(pre) and not _is_option(pre):
                labels.append(pre)
            else:
                lbl = _left_label(l, bolds)
                if lbl:
                    labels.append(lbl)
    return labels


def extract(pages):
    out = []
    cur_form = ""
    for idx, lines in sorted(pages, key=lambda p: p[0]):
        pno = idx + 1
        lines = [l for l in lines if l.text and l.text.strip()]
        if not lines:
            continue
        name_x = _var_page_name_x(lines)
        if name_x is not None:
            # Technical annotation table for the most recently announced form.
            for name in _parse_var_page(lines, name_x):
                out.append({"form_name": cur_form, "field_name": name, "page": pno})
            continue
        form = _breadcrumb(lines) or _form_title(lines)
        if form:
            cur_form = form
        for name in _parse_form_page(lines):
            out.append({"form_name": cur_form, "field_name": name, "page": pno})
    return out
