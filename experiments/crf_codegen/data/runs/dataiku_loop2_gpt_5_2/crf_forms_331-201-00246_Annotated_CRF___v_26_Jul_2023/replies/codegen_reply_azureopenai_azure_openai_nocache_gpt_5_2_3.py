```python
import re
from collections import defaultdict

# -----------------------------
# Regex / heuristics (EXTENDED, not replaced)
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

# NEW: detect "Change History" / version tables and other doc-control tables
RE_DOC_CONTROL = re.compile(
    r'^(Change History|Document History|Revision History|Version History|Approval History)$',
    re.I
)

# NEW: detect "Met/Not Met" header-ish tokens
RE_MET_HEADER = re.compile(r'^(Met|Not Met|Met/Not Met)$', re.I)

# NEW: bracketed code token inside a longer string (rare OCR)
RE_CODE_INLINE = re.compile(r'\[([A-Z0-9_]+)\]')

def _norm_space(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '')).strip()

def _is_machine_annot_text(t: str) -> bool:
    t = (t or '').strip()
    return bool(RE_CODE.match(t) or RE_TYPE.match(t) or RE_VIS.match(t) or RE_READONLY.match(t))

def _is_footer_or_header_noise(line) -> bool:
    t = (line.text or '').strip()
    if not t:
        return True
    if RE_PAGE.match(t):
        return True
    if t in ("Pack Version",) or re.fullmatch(r'\d+(\.\d+)?', t):
        return True
    return False

def _reading_order(lines):
    return sorted(lines, key=lambda l: (round(getattr(l, "y0", 0.0), 1), getattr(l, "x0", 0.0)))

def _is_red_annot(line) -> bool:
    if not getattr(line, "non_black", False):
        return False
    t = (line.text or '').strip()
    return t.startswith('[') and t.endswith(']')

def _is_option_like(line) -> bool:
    t = (line.text or '').strip()
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
        if getattr(ln, "y0", 9999) > 240:
            continue
        if getattr(ln, "x0", 9999) > 320:
            continue
        if getattr(ln, "size", 0) >= 14 and getattr(ln, "non_black", False) and not _is_machine_annot_text(ln.text) and not _is_footer_or_header_noise(ln):
            txt = _norm_space(ln.text)
            if txt and not RE_TOC_ITEM.match(txt) and txt.upper() != txt:
                candidates.append((ln.size, -ln.y0, -int(bool(getattr(ln, "bold", False))), txt))
            else:
                if ln.size >= 16 and txt and not RE_TOC_ITEM.match(txt):
                    candidates.append((ln.size, -ln.y0, -int(bool(getattr(ln, "bold", False))), txt))
    if not candidates:
        for ln in lines:
            if getattr(ln, "y0", 9999) > 240:
                continue
            if getattr(ln, "size", 0) >= 16 and getattr(ln, "non_black", False) and not _is_machine_annot_text(ln.text) and not _is_footer_or_header_noise(ln):
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
        if getattr(ln, "non_black", False):
            continue
        t = (ln.text or '').strip()
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
    cx, cy = getattr(code_line, "x0", 0.0), getattr(code_line, "y0", 0.0)
    candidates = []
    for ln in black_lines:
        if getattr(ln, "y0", 0.0) >= cy:
            break
        dy = cy - getattr(ln, "y0", 0.0)
        if dy > max_dy:
            continue
        t = (ln.text or '').strip()
        if not t:
            continue
        if RE_ROW.match(t):
            continue
        if _is_option_like(ln):
            continue

        # Avoid capturing long numbered criteria statements as "labels" unless they are actual fields
        t_norm = _norm_space(t)

        # If it's a long numbered narrative, we still might want it (page 159 fix),
        # but only when it is clearly paired with a code nearby (handled elsewhere).
        # Here, keep the original suppression to avoid false positives.
        if RE_NUM_PREFIX.match(t_norm) and len(t_norm) > 80 and ':' not in t_norm and not t_norm.endswith('?'):
            continue

        if RE_JUNK_SINGLE.match(t_norm) or t_norm.lower() in {"met/not met"}:
            continue

        score = 0.0
        dx = abs(getattr(ln, "x0", 0.0) - cx)
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
    bx = getattr(best, "x0", 0.0)
    by = getattr(best, "y0", 0.0)
    for ln in reversed(black_lines):
        if getattr(ln, "y0", 0.0) >= by:
            continue
        if by - getattr(ln, "y0", 0.0) > 14.5:
            break
        if abs(getattr(ln, "x0", 0.0) - bx) <= 8 and not RE_ROW.match((ln.text or '').strip()) and not _is_option_like(ln):
            t_norm = _norm_space(ln.text)
            if RE_NUM_PREFIX.match(t_norm) and len(t_norm) > 80 and ':' not in t_norm and not t_norm.endswith('?'):
                break
            parts.insert(0, (ln.text or '').strip())
            by = getattr(ln, "y0", 0.0)
        else:
            break

    label = _strip_numbering(" ".join(parts))
    if not label:
        return None
    if _looks_like_heading_not_field(label):
        return None
    return label

# -----------------------------
# Table extraction (EXTENDED with doc-control suppression)
# -----------------------------
def _detect_table_headers(lines):
    hdrs = [
        ln for ln in lines
        if (not getattr(ln, "non_black", False))
        and 9.0 <= getattr(ln, "size", 0.0) <= 12.0
        and 105 <= getattr(ln, "y0", 0.0) <= 155
        and not _is_footer_or_header_noise(ln)
        and not _is_machine_annot_text(ln.text)
    ]
    if len(hdrs) < 2:
        return None
    hdrs = sorted(hdrs, key=lambda l: getattr(l, "x0", 0.0))
    headers = [(h.x0, _norm_space(h.text)) for h in hdrs if _norm_space(h.text)]
    return headers if len(headers) >= 2 else None

def _page_is_doc_control_table(form_name, page_lines):
    # If the form header itself indicates doc control, suppress table field extraction
    if form_name and RE_DOC_CONTROL.match(_norm_space(form_name)):
        return True
    # Or if prominent top text says "Change History"
    for ln in page_lines:
        if getattr(ln, "y0", 9999) > 220:
            continue
        t = _norm_space(ln.text)
        if RE_DOC_CONTROL.match(t):
            return True
    return False

def _extract_table_fields(page_lines, form_name, page_num):
    out = []
    if _page_is_doc_control_table(form_name, page_lines):
        return out

    headers = _detect_table_headers(page_lines)
    if not headers:
        return out

    stub_x, stub_name = headers[0]
    other_headers = headers[1:]

    stubs = []
    for ln in page_lines:
        if getattr(ln, "y0", 0.0) <= 140 or getattr(ln, "y0", 0.0) >= 770:
            continue
        if getattr(ln, "size", 0.0) < 8.0 or getattr(ln, "size", 0.0) > 12.5:
            continue
        t = _norm_space(ln.text)
        if not t or _is_machine_annot_text(t) or RE_ROW.match(t):
            continue
        if abs(getattr(ln, "x0", 0.0) - stub_x) <= 28:
            if _looks_like_heading_not_field(t) and len(t) <= 40:
                continue
            # Avoid treating version numbers / dates as stubs in doc-control-like tables
            if re.fullmatch(r'\d+(\.\d+){1,3}', t) or re.fullmatch(r'\d{1,2}-[A-Za-z]{3}-\d{4}', t):
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
# Inline label extraction (EXTENDED)
# -----------------------------
def _extract_inline_label_for_code(code_line, black_lines, max_dx=520, max_dy=7.5):
    """
    If a black label appears on the same row (or nearly same y) as the code,
    prefer that label. This catches patterns like:
        Protocol Version for Consent   [VSCONSV]
    """
    cy = getattr(code_line, "y0", 0.0)
    cx = getattr(code_line, "x0", 0.0)
    same_row = []
    for ln in black_lines:
        if abs(getattr(ln, "y0", 0.0) - cy) <= max_dy:
            t = _norm_space(ln.text)
            if not t or _is_machine_annot_text(t):
                continue
            if _is_option_like(ln):
                continue
            if getattr(ln, "x0", 0.0) < cx and (cx - getattr(ln, "x0", 0.0)) <= max_dx:
                if _looks_like_heading_not_field(t):
                    continue
                same_row.append((getattr(ln, "x0", 0.0), t))
    if not same_row:
        return None
    same_row.sort(key=lambda x: x[0])
    label = _norm_space(" ".join([t for _, t in same_row]))
    label = _strip_numbering(label)
    if not label or _looks_like_heading_not_field(label):
        return None
    return label

# -----------------------------
# NEW: Criteria checklist extraction (page 159 fix)
# -----------------------------
def _page_looks_like_criteria_checklist(lines_ro):
    """
    Detect pages that are eligibility criteria narrative with Met/Not Met columns.
    Unlike the previous version, we DO want to extract the numbered criteria
    as fields when they are paired with codes. We only use this to switch
    to a different label-finding strategy.
    """
    met_tokens = 0
    numbered = 0
    for ln in lines_ro:
        t = _norm_space(ln.text)
        if not t or _is_machine_annot_text(t) or _is_footer_or_header_noise(ln):
            continue
        if RE_MET_HEADER.match(t):
            met_tokens += 1
        if RE_NUM_PREFIX.match(t):
            numbered += 1
    return met_tokens >= 2 and numbered >= 3

def _collect_numbered_criteria_blocks(lines_ro):
    """
    Build blocks of numbered criteria text by concatenating subsequent lines
    until the next numbered item or a clear column header.
    Returns list of dicts: {y0, x0, text}
    """
    blocks = []
    cur = None

    def flush():
        nonlocal cur
        if cur:
            cur["text"] = _norm_space(cur["text"])
            blocks.append(cur)
            cur = None

    for ln in lines_ro:
        if _is_footer_or_header_noise(ln) or _is_machine_annot_text(ln.text):
            continue
        t = _norm_space(ln.text)
        if not t:
            continue
        if RE_MET_HEADER.match(t) or t.lower() in {"met/not met"}:
            continue

        if RE_NUM_PREFIX.match(t):
            flush()
            cur = {"y0": getattr(ln, "y0", 0.0), "x0": getattr(ln, "x0", 0.0), "text": t}
            continue

        # continuation line
        if cur is not None:
            # stop if looks like a new section heading
            if _looks_like_heading_not_field(t) and len(t) <= 40:
                flush()
                continue
            # stop if it's a short option token
            if len(t) <= 12 and RE_JUNK_SINGLE.match(t):
                continue
            cur["text"] += " " + t

    flush()
    # keep only reasonably long narrative criteria (avoid tiny numbered artifacts)
    out = []
    for b in blocks:
        txt = _strip_numbering(b["text"])
        if len(txt) >= 40:
            out.append({"y0": b["y0"], "x0": b["x0"], "text": txt})
    return out

def _match_code_to_nearest_criteria(code_line, criteria_blocks, max_dy=26.0):
    """
    On criteria pages, codes often sit on the same row as the numbered statement
    (or very close). Match by y proximity.
    """
    cy = getattr(code_line, "y0", 0.0)
    best = None
    best_dy = 1e9
    for b in criteria_blocks:
        dy = abs(cy - b["y0"])
        if dy <= max_dy and dy < best_dy:
            best = b
            best_dy = dy
    return best["text"] if best else None

# -----------------------------
# Core extraction
# -----------------------------
def extract(pages):
    """
    pages: list of page objects; each page has .page_num (1-based or 0-based),
           and iterable .lines where each line has:
             text, x0, y0, size, non_black, bold (optional)
    Returns list of dicts: {form_name, field_name, page}
    """
    records = []
    last_form = None

    for page in pages:
        page_num = getattr(page, "page_num", None)
        lines = list(getattr(page, "lines", []) or [])
        if not lines:
            continue

        lines_ro = _reading_order(lines)
        form_name = _find_form_header(lines_ro) or last_form or "Unknown Form"
        last_form = form_name

        # Table extraction (kept, but doc-control suppressed)
        records.extend(_extract_table_fields(lines_ro, form_name, page_num))

        # Prepare black lines for label matching
        black_lines = _collect_black_lines(lines_ro)

        # Collect code lines (non-black bracketed annotations)
        code_lines = []
        for ln in lines_ro:
            if _is_footer_or_header_noise(ln):
                continue
            t = (ln.text or '').strip()
            if not t:
                continue
            if _is_red_annot(ln) and RE_CODE.match(t):
                code_lines.append(ln)
            else:
                # fallback: inline code token inside a non-black annotation line
                if getattr(ln, "non_black", False) and RE_CODE_INLINE.search(t) and t.strip().startswith('[') and t.strip().endswith(']'):
                    # treat as code line if it contains a code-like token
                    code_lines.append(ln)

        # Criteria checklist mode (page 159)
        criteria_mode = _page_looks_like_criteria_checklist(lines_ro)
        criteria_blocks = _collect_numbered_criteria_blocks(lines_ro) if criteria_mode else []

        # Extract fields from codes
        seen = set()
        for cl in code_lines:
            # Prefer inline label on same row (page 33 fix)
            label = _extract_inline_label_for_code(cl, black_lines)

            # If not found, on criteria pages match to numbered narrative block (page 159 fix)
            if not label and criteria_mode and criteria_blocks:
                label = _match_code_to_nearest_criteria(cl, criteria_blocks)

            # Otherwise fallback to nearest preceding label (existing behavior)
            if not label:
                label = _nearest_preceding_label(cl, black_lines)

            if not label:
                continue

            # Final cleanup: avoid doc-control table values being treated as fields
            if RE_DOC_CONTROL.match(_norm_space(form_name)):
                continue
            if re.fullmatch(r'\d{1,2}-[A-Za-z]{3}-\d{4}', label) or re.fullmatch(r'\d+(\.\d+){1,3}', label):
                continue

            key = (form_name, label, page_num)
            if key in seen:
                continue
            seen.add(key)
            records.append({"form_name": form_name, "field_name": label, "page": page_num})

    return records
```