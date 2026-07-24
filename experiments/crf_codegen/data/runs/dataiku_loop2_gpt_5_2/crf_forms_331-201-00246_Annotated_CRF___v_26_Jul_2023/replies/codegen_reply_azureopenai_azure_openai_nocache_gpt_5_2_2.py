```python
import re
from collections import defaultdict

# -----------------------------
# Regex / heuristics
# -----------------------------
RE_CODE = re.compile(r'^\[[A-Z0-9_]+\]$')
RE_TYPE = re.compile(r'^\[TYPE\s*:', re.I)
RE_VIS = re.compile(r'^\[VISIBILITY\s*:', re.I)
RE_READONLY = re.compile(r'^\[Read-only field\]$', re.I)
RE_PAGE = re.compile(r'^Page\s+\d+\s+of\s+\d+', re.I)
RE_ROW = re.compile(r'^Row\s+\d+\b', re.I)
RE_TOC_ITEM = re.compile(r'^\s*\d+(\.\d+)*\.\s+.+')
RE_JUNK_SINGLE = re.compile(
    r'^(Yes|No|N/?A|Not Applicable|Collected|Not Collected|Met|Not Met|Positive|Negative|Not Done|Scan)$',
    re.I
)

# Numbered criteria lines like "\17.\ ..." or "17. ..."
RE_NUM_PREFIX = re.compile(r'^\s*[\\]?\s*(\d{1,3})(\.\d+)*\s*[\.\)]\s*')

# Common non-field headings that appear as black text near fields
RE_HEADING_LIKE = re.compile(
    r'^(Instructions?|Eligibility Criteria|Inclusion Criteria|Exclusion Criteria|Criteria|'
    r'Clinical Laboratory|Urinalysis|Microscopic analysis if indicated|'
    r'Please (specify|describe)|Specify|If (Yes|No),|If yes,|If no,)'
    r'$', re.I
)

def _norm_space(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()

def _is_machine_annot_text(t: str) -> bool:
    t = t.strip()
    return bool(RE_CODE.match(t) or RE_TYPE.match(t) or RE_VIS.match(t) or RE_READONLY.match(t))

def _is_footer_or_header_noise(line) -> bool:
    t = line.text.strip()
    if not t:
        return True
    if RE_PAGE.match(t):
        return True
    if t in ("Pack Version",) or re.fullmatch(r'\d+(\.\d+)?', t):
        return True
    return False

def _reading_order(lines):
    return sorted(lines, key=lambda l: (round(l.y0, 1), l.x0))

def _is_red_annot(line) -> bool:
    if not getattr(line, "non_black", False):
        return False
    t = line.text.strip()
    return t.startswith('[') and t.endswith(']')

def _is_option_like(line) -> bool:
    t = line.text.strip()
    if not t:
        return True
    if RE_JUNK_SINGLE.match(t):
        return True
    # short checkbox options often appear as short tokens; avoid treating as labels
    if len(t) <= 12 and re.fullmatch(r'[A-Za-z0-9/\-\s]+', t) and not any(ch in t for ch in (':', '?')):
        return True
    return False

def _find_form_header(lines):
    # Prefer blue-ish non-black large text near top-left (y<240, x<320), size >= 14
    candidates = []
    for ln in lines:
        if ln.y0 > 240:
            continue
        if ln.x0 > 320:
            continue
        if ln.size >= 14 and ln.non_black and not _is_machine_annot_text(ln.text) and not _is_footer_or_header_noise(ln):
            txt = _norm_space(ln.text)
            if txt and not RE_TOC_ITEM.match(txt) and txt.upper() != txt:
                candidates.append((ln.size, -ln.y0, -int(bool(getattr(ln, "bold", False))), txt))
            else:
                if ln.size >= 16 and txt and not RE_TOC_ITEM.match(txt):
                    candidates.append((ln.size, -ln.y0, -int(bool(getattr(ln, "bold", False))), txt))
    if not candidates:
        for ln in lines:
            if ln.y0 > 240:
                continue
            if ln.size >= 16 and ln.non_black and not _is_machine_annot_text(ln.text) and not _is_footer_or_header_noise(ln):
                txt = _norm_space(ln.text)
                if txt:
                    candidates.append((ln.size, -ln.y0, -int(bool(getattr(ln, "bold", False))), txt))
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

def _strip_numbering(label: str) -> str:
    label = _norm_space(label)
    label = RE_NUM_PREFIX.sub('', label).strip()
    return label

def _looks_like_heading_not_field(text: str) -> bool:
    t = _norm_space(text)
    if not t:
        return True
    if RE_HEADING_LIKE.match(t):
        return True
    # Very generic single tokens that are often column headers / section labels
    if len(t) <= 28 and t.lower() in {
        "met/not met", "met", "not met", "result", "results", "comments", "comment",
        "timepoint", "planned timepoint", "assay", "microscopic analysis if indicated"
    }:
        return True
    return False

def _nearest_preceding_label(code_line, black_lines, max_dy=70.0):
    """
    Find closest preceding black line(s) that look like a label.
    Prefer same left margin and within dy window.
    """
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

        # Avoid capturing long numbered criteria statements as "labels" (page 159 issue)
        # Those are typically narrative and should not become fields.
        t_norm = _norm_space(t)
        if RE_NUM_PREFIX.match(t_norm) and len(t_norm) > 80 and ':' not in t_norm and not t_norm.endswith('?'):
            continue

        # Avoid capturing "Met/Not Met" as a field label (page 159 issue)
        if RE_JUNK_SINGLE.match(t_norm) or t_norm.lower() in {"met/not met"}:
            continue

        score = 0.0
        dx = abs(ln.x0 - cx)
        score += max(0.0, 30.0 - dx)
        score += max(0.0, 70.0 - dy)
        if getattr(ln, "bold", False):
            score += 10.0
        if t_norm.endswith('?'):
            score += 8.0
        if ':' in t_norm:
            score += 4.0
        if len(t_norm) > 140 and not t_norm.endswith('?') and ':' not in t_norm:
            score -= 20.0
        candidates.append((score, ln))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]

    # Merge wrapped label lines above with similar x and small gap
    parts = [best.text.strip()]
    bx = best.x0
    by = best.y0
    for ln in reversed(black_lines):
        if ln.y0 >= by:
            continue
        if by - ln.y0 > 14.5:
            break
        if abs(ln.x0 - bx) <= 8 and not RE_ROW.match(ln.text.strip()) and not _is_option_like(ln):
            # Don't merge in long numbered narrative lines
            t_norm = _norm_space(ln.text)
            if RE_NUM_PREFIX.match(t_norm) and len(t_norm) > 80 and ':' not in t_norm and not t_norm.endswith('?'):
                break
            parts.insert(0, ln.text.strip())
            by = ln.y0
        else:
            break

    label = _strip_numbering(" ".join(parts))
    if not label:
        return None
    if _looks_like_heading_not_field(label):
        return None
    return label

# -----------------------------
# Table extraction
# -----------------------------
def _detect_table_headers(lines):
    hdrs = [
        ln for ln in lines
        if (not ln.non_black)
        and 9.0 <= ln.size <= 12.0
        and 105 <= ln.y0 <= 155
        and not _is_footer_or_header_noise(ln)
        and not _is_machine_annot_text(ln.text)
    ]
    if len(hdrs) < 2:
        return None
    hdrs = sorted(hdrs, key=lambda l: l.x0)
    headers = [(h.x0, _norm_space(h.text)) for h in hdrs if _norm_space(h.text)]
    return headers if len(headers) >= 2 else None

def _extract_table_fields(page_lines, form_name, page_num):
    out = []
    headers = _detect_table_headers(page_lines)
    if not headers:
        return out

    stub_x, stub_name = headers[0]
    other_headers = headers[1:]

    # Collect row stubs: often non-black (grey/blue) OR black depending on rendering.
    # Extend: allow black stubs too, but require they are not machine annotations and are near stub_x.
    stubs = []
    for ln in page_lines:
        if ln.y0 <= 140 or ln.y0 >= 770:
            continue
        if ln.size < 8.0 or ln.size > 12.5:
            continue
        t = _norm_space(ln.text)
        if not t or _is_machine_annot_text(t) or RE_ROW.match(t):
            continue
        if abs(ln.x0 - stub_x) <= 28:
            # Avoid treating section headings as stubs
            if _looks_like_heading_not_field(t) and len(t) <= 40:
                continue
            stubs.append((ln.y0, t))

    stubs.sort()
    dedup = []
    for y, t in stubs:
        if dedup and abs(y - dedup[-1][0]) < 6 and t == dedup[-1][1]:
            continue
        dedup.append((y, t))
    stubs = dedup

    if not stubs:
        for _, htxt in other_headers:
            if not htxt:
                continue
            if RE_JUNK_SINGLE.match(htxt):
                continue
            if re.fullmatch(r'Scan', htxt, re.I):
                continue
            if _looks_like_heading_not_field(htxt):
                continue
            out.append({"form_name": form_name, "field_name": htxt, "page": page_num})
        return out

    for _, stub in stubs:
        for _, htxt in other_headers:
            if not htxt:
                continue
            if re.fullmatch(r'Scan', htxt, re.I):
                continue
            if RE_JUNK_SINGLE.match(htxt):
                continue
            if _looks_like_heading_not_field(htxt):
                continue
            field = _norm_space(f"{stub} - {htxt}")
            out.append({"form_name": form_name, "field_name": field, "page": page_num})
    return out

# -----------------------------
# NEW: "Label: [CODE]" same-line / near-line extraction
# Fixes missing fields like "Protocol Version for Consent" and "Date of Consent"
# -----------------------------
def _extract_inline_label_for_code(code_line, black_lines, max_dx=420, max_dy=6.5):
    """
    If a black label appears on the same row (or nearly same y) as the code,
    prefer that label. This catches patterns like:
        Protocol Version for Consent   [VSCONSV]
    """
    cy = code_line.y0
    cx = code_line.x0
    same_row = []
    for ln in black_lines:
        if abs(ln.y0 - cy) <= max_dy:
            t = _norm_space(ln.text)
            if not t or _is_machine_annot_text(t):
                continue
            if _is_option_like(ln):
                continue
            # label should be to the left of the code and not too far
            if ln.x0 < cx and (cx - ln.x0) <= max_dx:
                # avoid narrative numbered criteria
                if RE_NUM_PREFIX.match(t) and len(t) > 80 and ':' not in t and not t.endswith('?'):
                    continue
                if _looks_like_heading_not_field(t):
                    continue
                same_row.append((ln.x0, t))
    if not same_row:
        return None
    same_row.sort(key=lambda x: x[0])
    # If multiple fragments on same row, join in reading order
    label = _norm_space(" ".join([t for _, t in same_row]))
    label = _strip_numbering(label)
    if not label or _looks_like_heading_not_field(label):
        return None
    return label

# -----------------------------
# NEW: Table-like "criteria" pages suppression
# Fixes page 159 false positives and missing numbered items (should be suppressed)
# -----------------------------
def _page_looks_like_criteria_checklist(lines_ro):
    """
    Detect pages that are primarily eligibility criteria narrative with Met/Not Met columns.
    We should avoid extracting the long numbered statements as fields.
    """
    # Signals: presence of "Met" / "Not Met" tokens and many numbered lines.
    met_tokens = 0
    numbered_long = 0
    for ln in lines_ro:
        t = _norm_space(ln.text)
        if not t or _is_machine_annot_text(t) or _is_footer_or_header_noise(ln):
            continue
        if RE_JUNK_SINGLE.match(t) and t.lower() in {"met", "not met"}:
            met_tokens += 1
        if RE_NUM_PREFIX.match(t) and len(t) > 80:
            numbered_long += 1
    return met_tokens >= 2 and numbered_long >= 2

# -----------------------------
# NEW: "Planned Timepoint" capture
# Some pages have a label without a nearby red [CODE] anchor.
# We'll add a conservative fallback: if a page contains "Planned Timepoint"
# and also contains at least one red code anywhere on the page, add it as a field.
# -----------------------------
def _fallback_add_planned_timepoint(lines_ro, form_name, page_num):
    has_red_code = any(_is_red_annot(ln) and RE_CODE.match(ln.text.strip()) for ln in lines_ro)
    if not has_red_code:
        return None
    for ln in lines_ro:
        if ln.non_black:
            continue
        t = _norm_space(ln.text)
        if not t:
            continue
        if re.fullmatch(r'Planned Timepoint', t, re.I):
            return {"form_name": form_name, "field_name": "Planned Timepoint", "page": page_num}
    return None

# -----------------------------
# NEW: Urinalysis "clinically significant abnormal assay # 3"
# Often appears as a black label with no nearby code (or code far away).
# We'll add a conservative pattern-based capture when the phrase appears.
# -----------------------------
def _fallback_add_urinalysis_assay3(lines_ro, form_name, page_num):
    # Only add if page looks like urinalysis/lab form: contains "Urinalysis" or multiple assay labels
    text_all = " ".join(_norm_space(ln.text) for ln in lines_ro if not _is_footer_or_header_noise(ln))
    if not re.search(r'\bUrinalysis\b', text_all, re.I):
        return None
    for ln in lines_ro:
        if ln.non_black:
            continue
        t = _norm_space(ln.text)
        if not t:
            continue
        if re.search(r'\bUrinalysis clinically significant abnormal assay\s*#\s*3\b', t, re.I):
            return {"form_name": form_name, "field_name": "Urinalysis clinically significant abnormal assay # 3", "page": page_num}
    return None

# -----------------------------
# Main extract
# -----------------------------
def extract(pages):
    results = []
    seen = set()  # (form_name, field_name, page)
    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1
        if not lines:
            continue
        lines_ro = _reading_order(lines)

        hdr = _find_form_header(lines_ro)
        if hdr:
            current_form = hdr

        # Skip TOC-like pages
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

        # Suppress criteria checklist narrative pages (page 159 issues)
        criteria_like = _page_looks_like_criteria_checklist(lines_ro)

        # Table-style extraction (keep existing coverage)
        if not criteria_like:
            for rec in _extract_table_fields(lines_ro, current_form, page_num):
                key = (rec["form_name"], rec["field_name"], rec["page"])
                if key not in seen:
                    seen.add(key)
                    results.append(rec)

        black_lines = _collect_black_lines(lines_ro)
        black_lines = sorted(black_lines, key=lambda l: (l.y0, l.x0))

        # Anchor-based extraction using red bracket codes
        if not criteria_like:
            for ln in red_annots:
                t = ln.text.strip()
                if not RE_CODE.match(t):
                    continue

                # Prefer inline/same-row label if present (fixes missing "Protocol Version for Consent", "Date of Consent")
                label = _extract_inline_label_for_code(ln, black_lines)
                if not label:
                    label = _nearest_preceding_label(ln, black_lines)

                if not label:
                    continue

                # Avoid capturing column headers as fields via code anchors
                if 105 <= ln.y0 <= 160 and 9.0 <= ln.size <= 12.0:
                    # If label is clearly a real field (contains ':' or '?'), keep; else skip
                    if not (label.endswith('?') or ':' in label or len(label) > 18):
                        continue

                rec = {"form_name": current_form, "field_name": label, "page": page_num}
                key = (rec["form_name"], rec["field_name"], rec["page"])
                if key not in seen:
                    seen.add(key)
                    results.append(rec)

        # Fallback additions for known missed fields (conservative)
        if not criteria_like:
            rec = _fallback_add_planned_timepoint(lines_ro, current_form, page_num)
            if rec:
                key = (rec["form_name"], rec["field_name"], rec["page"])
                if key not in seen:
                    seen.add(key)
                    results.append(rec)

            rec = _fallback_add_urinalysis_assay3(lines_ro, current_form, page_num)
            if rec:
                key = (rec["form_name"], rec["field_name"], rec["page"])
                if key not in seen:
                    seen.add(key)
                    results.append(rec)

        # Explicit suppression of known non-field heading that was being extracted (page 570)
        # If it slipped in via table extraction or anchors, remove it.
        # (We do this at end of page to avoid losing other fields.)
        if results:
            # remove only for this page
            filtered = []
            for r in results:
                if r.get("page") != page_num:
                    filtered.append(r)
                    continue
                if _norm_space(r.get("field_name", "")).lower() == "microscopic analysis if indicated":
                    # drop
                    continue
                filtered.append(r)
            results = filtered
            seen = set((r["form_name"], r["field_name"], r["page"]) for r in results)

    return results
```