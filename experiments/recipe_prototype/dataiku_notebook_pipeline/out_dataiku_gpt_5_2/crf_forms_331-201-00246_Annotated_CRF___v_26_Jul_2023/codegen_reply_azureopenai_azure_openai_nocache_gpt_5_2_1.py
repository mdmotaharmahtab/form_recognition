```python
# Observed layouts: (1) TOC pages with blue numbered section titles; (2) CRF pages with a blue
# form header (size ~16.5) near top-left; (3) fields are labeled by nearby black text lines,
# while machine annotations are red bracket codes like [VSDAT] and [TYPE: ...].
# Strategy: track current form_name from the blue header; extract field labels by anchoring on
# red bracket codes and taking the closest preceding black label line(s) at same left margin;
# also handle table-style forms by using column headers + row stub text as field labels.

import re
from collections import defaultdict

RE_CODE = re.compile(r'^\[[A-Z0-9_]+\]$')
RE_TYPE = re.compile(r'^\[TYPE\s*:', re.I)
RE_VIS = re.compile(r'^\[VISIBILITY\s*:', re.I)
RE_READONLY = re.compile(r'^\[Read-only field\]$', re.I)
RE_PAGE = re.compile(r'^Page\s+\d+\s+of\s+\d+', re.I)
RE_ROW = re.compile(r'^Row\s+\d+\b', re.I)
RE_TOC_ITEM = re.compile(r'^\s*\d+(\.\d+)*\.\s+.+')
RE_JUNK_SINGLE = re.compile(r'^(Yes|No|N/?A|Not Applicable|Collected|Not Collected|Met|Not Met|Positive|Negative|Not Done|Scan)$', re.I)

def _norm_space(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()

def _is_red_annot(line) -> bool:
    if not line.non_black:
        return False
    t = line.text.strip()
    return t.startswith('[') and t.endswith(']')

def _is_machine_annot_text(t: str) -> bool:
    t = t.strip()
    return bool(RE_CODE.match(t) or RE_TYPE.match(t) or RE_VIS.match(t) or RE_READONLY.match(t))

def _is_footer_or_header_noise(line) -> bool:
    t = line.text.strip()
    if not t:
        return True
    if RE_PAGE.match(t):
        return True
    # cover page metadata
    if t in ("Pack Version",) or re.fullmatch(r'\d+(\.\d+)?', t):
        return True
    return False

def _is_option_like(line) -> bool:
    t = line.text.strip()
    if not t:
        return True
    if RE_JUNK_SINGLE.match(t):
        return True
    # short checkbox options often appear in grey; we don't have color, but size ~10.5 and short
    if len(t) <= 12 and re.fullmatch(r'[A-Za-z0-9/\-\s]+', t) and not any(ch in t for ch in (':', '?')):
        # still allow if it looks like a question (ends with ?)
        return True
    return False

def _reading_order(lines):
    # simple top-to-bottom; within same y band, left-to-right
    # lines already sorted by y then x, but we stabilize by y buckets
    return sorted(lines, key=lambda l: (round(l.y0, 1), l.x0))

def _find_form_header(lines):
    # Prefer blue-ish non-black large text near top-left (y<220, x<250), size >= 14
    candidates = []
    for ln in lines:
        if ln.y0 > 240:
            continue
        if ln.x0 > 320:
            continue
        if ln.size >= 14 and ln.non_black and not _is_machine_annot_text(ln.text) and not _is_footer_or_header_noise(ln):
            txt = _norm_space(ln.text)
            if txt and not RE_TOC_ITEM.match(txt) and txt.upper() != txt:  # avoid TOC headings like CHANGE HISTORY
                candidates.append((ln.size, -ln.y0, -ln.bold, txt))
            else:
                # still allow all-caps if it's clearly a form title (size big)
                if ln.size >= 16 and txt and not RE_TOC_ITEM.match(txt):
                    candidates.append((ln.size, -ln.y0, -ln.bold, txt))
    if not candidates:
        # fallback: any large non-black line near top
        for ln in lines:
            if ln.y0 > 240:
                continue
            if ln.size >= 16 and ln.non_black and not _is_machine_annot_text(ln.text) and not _is_footer_or_header_noise(ln):
                txt = _norm_space(ln.text)
                if txt:
                    candidates.append((ln.size, -ln.y0, -ln.bold, txt))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][3]

def _collect_black_lines(lines):
    bl = []
    for ln in lines:
        if _is_footer_or_header_noise(ln):
            continue
        if ln.non_black:
            continue
        t = ln.text.strip()
        if not t:
            continue
        if _is_machine_annot_text(t):
            continue
        bl.append(ln)
    return bl

def _nearest_preceding_label(code_line, black_lines, max_dy=55.0):
    # Find closest preceding black line(s) that look like a label.
    # Prefer same left margin (x within 25) and within dy window.
    cx, cy = code_line.x0, code_line.y0
    candidates = []
    for ln in black_lines:
        if ln.y0 >= cy:
            break
        dy = cy - ln.y0
        if dy > max_dy:
            continue
        t = ln.text.strip()
        if not t:
            continue
        if RE_ROW.match(t):
            continue
        if _is_option_like(ln):
            continue
        # avoid long instruction paragraphs: prefer lines ending with ? or containing ':' or short-ish
        score = 0.0
        dx = abs(ln.x0 - cx)
        score += max(0.0, 30.0 - dx)  # closer x is better
        score += max(0.0, 60.0 - dy)  # closer y is better
        if ln.bold:
            score += 10.0
        if t.endswith('?'):
            score += 8.0
        if ':' in t:
            score += 4.0
        # penalize very long narrative lines without punctuation
        if len(t) > 120 and not t.endswith('?') and ':' not in t:
            score -= 15.0
        candidates.append((score, ln))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]

    # Merge with immediately preceding lines if they are part of the same label (wrapped)
    parts = [best.text.strip()]
    # look upward for continuation lines with similar x and small gap
    bx = best.x0
    by = best.y0
    for ln in reversed(black_lines):
        if ln.y0 >= by:
            continue
        if by - ln.y0 > 14.5:
            break
        if abs(ln.x0 - bx) <= 8 and not RE_ROW.match(ln.text.strip()) and not _is_option_like(ln):
            # prepend if looks like continuation (no trailing period in previous)
            parts.insert(0, ln.text.strip())
            by = ln.y0
        else:
            break
    label = _norm_space(" ".join(parts))
    # strip leading numbering like "\12.\"
    label = re.sub(r'^[\\]?\s*\d+(\.\d+)*\s*[\.\)]\s*', '', label).strip()
    return label if label else None

def _detect_table_headers(lines):
    # Identify a header row: multiple black lines at y~124 with size ~10.5
    hdrs = [ln for ln in lines if (not ln.non_black) and 9.5 <= ln.size <= 11.5 and 110 <= ln.y0 <= 140 and not _is_footer_or_header_noise(ln)]
    if len(hdrs) < 2:
        return None
    # sort by x
    hdrs = sorted(hdrs, key=lambda l: l.x0)
    headers = [(h.x0, _norm_space(h.text)) for h in hdrs if _norm_space(h.text)]
    # filter out generic single words that are likely not headers? keep all; downstream uses.
    return headers if len(headers) >= 2 else None

def _extract_table_fields(page_lines, form_name, page_num):
    out = []
    headers = _detect_table_headers(page_lines)
    if not headers:
        return out

    # Determine leftmost "stub" column header (first header)
    stub_x, stub_name = headers[0]
    other_headers = headers[1:]

    # Collect grey-ish row stub values: non-black lines with size ~9 at x near stub_x and y below header
    # But we don't have grey flag; we have non_black True for colored (including grey). Use non_black and size ~9.
    stubs = []
    for ln in page_lines:
        if ln.y0 <= 140:
            continue
        if ln.y0 >= 760:
            continue
        if not ln.non_black:
            continue
        if ln.size < 8.5 or ln.size > 11.5:
            continue
        t = _norm_space(ln.text)
        if not t or _is_machine_annot_text(t) or RE_ROW.match(t):
            continue
        if abs(ln.x0 - stub_x) <= 25:
            stubs.append((ln.y0, t))
    # Deduplicate stubs by y proximity and text
    stubs.sort()
    dedup = []
    for y, t in stubs:
        if dedup and abs(y - dedup[-1][0]) < 6 and t == dedup[-1][1]:
            continue
        dedup.append((y, t))
    stubs = dedup

    # If no stubs, still treat headers as fields (single-row forms)
    if not stubs:
        for _, htxt in other_headers:
            if htxt and not RE_JUNK_SINGLE.match(htxt):
                out.append({"form_name": form_name, "field_name": htxt, "page": page_num})
        return out

    # For each stub row, create fields for each non-stub header (e.g., "Methadone - Result")
    for _, stub in stubs:
        # avoid creating fields from placeholder like "FBR Sample" if it's a section label; still a row value though.
        for _, htxt in other_headers:
            if not htxt:
                continue
            # Skip "Scan" header: it's usually a scanner action, not a data-entry field label
            if re.fullmatch(r'Scan', htxt, re.I):
                continue
            field = _norm_space(f"{stub} - {htxt}")
            out.append({"form_name": form_name, "field_name": field, "page": page_num})
    return out

def extract(pages):
    results = []
    seen = set()  # (form_name, field_name, page)
    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1
        if not lines:
            continue
        lines_ro = _reading_order(lines)

        # Update form name if a header is present
        hdr = _find_form_header(lines_ro)
        if hdr:
            current_form = hdr

        # Skip TOC-like pages: many blue numbered items, no red annotations
        red_annots = [ln for ln in lines_ro if _is_red_annot(ln)]
        toc_like = False
        if not red_annots:
            blue_items = 0
            for ln in lines_ro:
                if ln.non_black and 13 <= ln.size <= 16 and ln.x0 < 250:
                    if RE_TOC_ITEM.match(_norm_space(ln.text)):
                        blue_items += 1
            if blue_items >= 5:
                toc_like = True
        if toc_like:
            continue

        # Table-style extraction (adds many fields; safe because it keys on header row geometry)
        for rec in _extract_table_fields(lines_ro, current_form, page_num):
            key = (rec["form_name"], rec["field_name"], rec["page"])
            if key not in seen:
                seen.add(key)
                results.append(rec)

        # Anchor-based extraction using red bracket codes
        black_lines = _collect_black_lines(lines_ro)
        # black_lines are in reading order; ensure sorted by y then x
        black_lines = sorted(black_lines, key=lambda l: (l.y0, l.x0))

        for ln in red_annots:
            t = ln.text.strip()
            if not RE_CODE.match(t):
                continue
            # ignore codes in margins/top that are not fields? keep; label finder will filter.
            label = _nearest_preceding_label(ln, black_lines)
            if not label:
                continue
            # Exclude generic instruction headings
            if label.endswith(':') and len(label) <= 35 and not label.endswith('?:'):
                # keep "If not collected, reason:" etc. (ends with :)
                pass
            # Avoid capturing column headers as fields via code anchors (rare)
            if 110 <= ln.y0 <= 150 and 9.5 <= ln.size <= 11.5:
                continue
            # Avoid capturing "If Yes, describe" repeatedly as a field when it's a helper label:
            # but it is a real text field label in many CRFs; keep it.
            rec = {"form_name": current_form, "field_name": label, "page": page_num}
            key = (rec["form_name"], rec["field_name"], rec["page"])
            if key not in seen:
                seen.add(key)
                results.append(rec)

    return results
```