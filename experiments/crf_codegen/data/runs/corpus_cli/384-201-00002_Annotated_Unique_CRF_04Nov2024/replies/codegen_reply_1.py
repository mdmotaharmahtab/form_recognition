# Observed layout: every content page has a bold header ("Form: <name>") and a footer
# near y~692. Two page kinds: (a) question pages - field labels in a left column
# (x0<=120), answer options at x~370-510, and a small integer marker at the right edge
# (x~520-535) aligned ~2pt below the label's first line; (b) technical spec tables
# ("Field Name / Data Type / ... / Field OID") holding machine codes only - skipped.
# Strategy: track form from headers; anchor each right-edge marker to its left-column
# line, then absorb following left lines (~12pt wraps) to rebuild multi-line labels.

import re

_HEADER_Y = 140.0     # header band ends above this
_FOOTER_Y = 685.0     # footer band starts below this
_LEFT_X_MAX = 120.0   # field labels live left of this
_MARK_X_MIN = 515.0   # right-edge field markers
_MARK_X_MAX = 545.0
_WRAP_GAP = 15.0      # max y-gap between wrapped label lines (~12pt leading)
_ANCHOR_TOL = 6.0     # marker sits ~2pt below label top

_MARK_RE = re.compile(r'^\d{1,3}$')
_FORM_RE = re.compile(r'^Form:\s*(.+)$')
_TABLE_HDR_RE = re.compile(r'^Field\s+Name\b')


def _clean(s):
    return re.sub(r'\s+', ' ', s).strip()


def _is_table_page(lines):
    # Spec-table pages repeat a column header row ("Field Name Data Type" ... "Field OID").
    for ln in lines:
        t = ln.text.strip()
        if t == 'Field OID' or _TABLE_HDR_RE.match(t):
            return True
    return False


def extract(pages):
    out = []
    cur_form = ""
    for idx, lines in pages:
        # 1) Update current form from the bold page header.
        for ln in lines:
            if ln.y0 < _HEADER_Y:
                m = _FORM_RE.match(ln.text.strip())
                if m:
                    cur_form = _clean(m.group(1))
                    break

        # 2) Skip machine-code specification tables entirely.
        if _is_table_page(lines):
            continue

        content = [ln for ln in lines if _HEADER_Y <= ln.y0 < _FOOTER_Y]
        if not content:
            continue

        # 3) Field markers: small bare integers hugging the right page edge.
        markers = [ln for ln in content
                   if _MARK_X_MIN <= ln.x0 <= _MARK_X_MAX
                   and _MARK_RE.match(ln.text.strip())]
        if not markers:
            continue

        # 4) Left-column label lines, top to bottom.
        left = [ln for ln in content if ln.x0 <= _LEFT_X_MAX]
        left.sort(key=lambda l: (l.y0, l.x0))
        if not left:
            continue

        # 5) Anchor each marker to the nearest left line (label top ~2pt above marker).
        marker_anchor = {}  # index into left -> True
        for mk in sorted(markers, key=lambda l: l.y0):
            best_i, best_d = -1, None
            for i, ln in enumerate(left):
                if i in marker_anchor:
                    continue
                d = abs((ln.y0 + 2.0) - mk.y0)
                if best_d is None or d < best_d:
                    best_d, best_i = d, i
            if best_i >= 0 and best_d is not None and best_d <= _ANCHOR_TOL:
                marker_anchor[best_i] = True

        # 6) Grow each anchored line downward through unanchored wrap lines.
        for i in sorted(marker_anchor):
            parts = [left[i].text]
            prev = left[i]
            j = i + 1
            while j < len(left) and j not in marker_anchor:
                if left[j].y0 - prev.y0 > _WRAP_GAP:
                    break
                parts.append(left[j].text)
                prev = left[j]
                j += 1
            name = _clean(' '.join(parts))
            # Keep only human-readable labels (must contain letters, not bare numbers).
            if len(name) < 2 or not re.search(r'[A-Za-z]', name):
                continue
            out.append({"form_name": cur_form,
                        "field_name": name,
                        "page": idx + 1})
    return out
