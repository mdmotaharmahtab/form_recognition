# Layout: pages repeat a 3-column table (Timepoint x~30, Activity x~168, Line# x~488).
# Each field block opens with a header row: bold "<Form>: <Item> #n" text beside a
# numeric Line# cell; the bold field label sits at x~168 on rows anchored by entry
# placeholders ("_ _ - _ _ _ ...", "dd - MMM - yyyy") at x<160. Options/SAS codes at x~239.
# Strategy: carry the current form across pages from block header rows; emit each
# anchored bold label run; drop unanchored bold lines (help text), options, furniture.
import re

_ACT_LO, _ACT_HI = 160.0, 176.0   # activity/label column x0 window
_ANCH_X = 160.0                   # entry placeholders live left of this
_NUM_X = 450.0                    # Line# column starts right of this
_FOOT_Y = 735.0                   # footer zone
_ROW_TOL = 2.6                    # same-visual-row y tolerance
_WRAP_GAP = 14.5                  # max y-gap between wrapped label lines

_RE_LINENO = re.compile(r'^\d+(?:\.\d+)?\s*(?:\(hidden\))?$')
_RE_ANCHOR = re.compile(r'^(?:[_\s\-:.]+|dd\s*-\s*MMM\s*-\s*yyyy|HH\s*:\s*mm)$')
_RE_FOOT = re.compile(r'^(?:Page\s+\d+\s+of\s+\d+$|Date\s+Created\s*:)', re.IGNORECASE)
_RE_OCC = re.compile(r'\s*#\d+(?:\.\d+)?\s*$')
_RE_WS = re.compile(r'\s+')
_RE_ALPHA = re.compile(r'[A-Za-z]')


def _rows(lines):
    """Group lines into visual rows by y0 proximity; returns [[y, [lines...]], ...]."""
    rows = []
    for ln in sorted(lines, key=lambda l: (l.y0, l.x0)):
        if rows and abs(ln.y0 - rows[-1][0]) <= _ROW_TOL:
            rows[-1][1].append(ln)
        else:
            rows.append([ln.y0, [ln]])
    return rows


def extract(pages):
    out = []
    cur_form = None   # persists across pages: blocks straddle page breaks
    sched = None      # last seen schedule name, used only as form fallback

    for pidx, lines in pages:
        page_no = pidx + 1

        # Top of the data table = the colored bold "Activity" column header cell.
        body_top = 128.0
        for l in lines:
            if (l.bold and l.non_black and l.y0 < 260.0
                    and _ACT_LO <= l.x0 <= _ACT_HI
                    and l.text.strip() == 'Activity'):
                body_top = l.y0 + 2.0
                break

        # Schedule name from the page header area (form fallback only).
        for m in lines:
            if (m.bold and m.x0 < 60.0 and m.y0 < body_top
                    and m.text.strip().lower().startswith('schedule')):
                for l in lines:
                    if (not l.bold) and l.x0 > 150.0 and abs(l.y0 - m.y0) <= _ROW_TOL:
                        v = l.text.strip()
                        if ',' in v:
                            v = v.split(',', 1)[1].strip()
                        if v:
                            sched = v
                        break
                break

        body = []
        for l in lines:
            t = l.text.strip()
            if not t or l.y0 <= body_top or l.y0 >= _FOOT_Y or _RE_FOOT.match(t):
                continue
            body.append(l)

        parts = []
        last_y = None

        def flush():
            nonlocal parts, last_y
            if parts:
                name = _RE_WS.sub(' ', ' '.join(parts)).strip()
                if (len(name) >= 2 and _RE_ALPHA.search(name)
                        and not _RE_ANCHOR.match(name)):
                    out.append({'form_name': cur_form or sched or '',
                                'field_name': name,
                                'page': page_no})
            parts = []
            last_y = None

        for y, row in _rows(body):
            acts = [l for l in row
                    if _ACT_LO <= l.x0 <= _ACT_HI and l.bold and not l.non_black]
            has_num = any(l.x0 >= _NUM_X and _RE_LINENO.match(l.text.strip())
                          for l in row)
            if has_num:
                # Block header row: bold "<Form>: <Item> #n" | numeric line cell.
                flush()
                if acts:
                    t = ' '.join(a.text.strip()
                                 for a in sorted(acts, key=lambda a: a.x0))
                    form = (t.split(':', 1)[0] if ':' in t
                            else _RE_OCC.sub('', t)).strip()
                    if form:
                        cur_form = form
                continue
            if not acts:
                continue
            # Field label rows share y with an entry placeholder / format hint
            # in the left column; free-floating bold lines are help text.
            anchored = any(l.x0 < _ANCH_X and _RE_ANCHOR.match(l.text.strip())
                           for l in row)
            if not anchored:
                continue
            t = ' '.join(a.text.strip() for a in sorted(acts, key=lambda a: a.x0))
            if parts and last_y is not None and (y - last_y) <= _WRAP_GAP:
                parts.append(t)
                last_y = y
            else:
                flush()
                parts = [t]
                last_y = y

        flush()

    return out
