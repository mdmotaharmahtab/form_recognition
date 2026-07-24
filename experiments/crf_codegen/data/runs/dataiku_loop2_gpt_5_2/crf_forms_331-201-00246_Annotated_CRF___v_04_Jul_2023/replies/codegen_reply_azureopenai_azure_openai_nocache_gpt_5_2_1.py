```python
# Observed layouts: (1) TOC pages with blue section titles; (2) CRF pages with a
# large blue form title near top; (3) tabular CRFs where each row has a long label
# in black and a red bracketed variable code + red [TYPE: ...] annotation.
# Strategy: track current form_name from the large blue title (fallback to last
# seen TOC entry if needed). Extract field labels by pairing each red [CODE] with
# the nearest preceding black label line(s) in the same row/column; also extract
# standalone black labels that are immediately followed by red [CODE]/[TYPE].
import re
from collections import defaultdict

RE_CODE = re.compile(r'^\[[A-Z0-9_]+\]$')
RE_TYPE = re.compile(r'^\[TYPE\s*:\s*.*\]$', re.I)
RE_VIS = re.compile(r'^\[VISIBILITY\s*:\s*.*\]$', re.I)
RE_READONLY = re.compile(r'^\[Read-only field\]$', re.I)
RE_ROW = re.compile(r'^\s*Row\s+\d+\s*$', re.I)
RE_PAGE = re.compile(r'^\s*Page\s+\d+\s+of\s+\d+\s*$', re.I)
RE_TOC_ITEM = re.compile(r'^\s*\d+(\.\d+)*\.\s+\S.*$')  # "3.21. Something"
RE_JUNK_BRACKET = re.compile(r'^\[(TYPE|VISIBILITY|READ-ONLY|READ ONLY|SCANNER)\b', re.I)

def norm_space(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()

def is_red_bracket(line):
    t = line.text.strip()
    if not (t.startswith('[') and t.endswith(']')):
        return False
    if RE_TYPE.match(t) or RE_VIS.match(t) or RE_READONLY.match(t):
        return False
    if RE_JUNK_BRACKET.match(t):
        return False
    return bool(RE_CODE.match(t))

def is_annotation(line):
    t = line.text.strip()
    return bool(RE_TYPE.match(t) or RE_VIS.match(t) or RE_READONLY.match(t) or RE_JUNK_BRACKET.match(t))

def is_option_like(line):
    # Grey/black short options like Yes/No/Met/Not Met etc. Avoid treating as fields.
    t = norm_space(line.text)
    if len(t) <= 12 and (line.non_black or (not line.bold and line.size >= 10)):
        # common option tokens are short; but keep language-agnostic by length/position later
        return True
    return False

def is_header_footer(line):
    t = line.text.strip()
    if RE_PAGE.match(t):
        return True
    if t in ("Pack Version",) or t.isdigit():
        return True
    return False

def is_form_title_candidate(line):
    # Large blue title near top (y ~ 150-170), size ~16.5, non-black.
    if not line.non_black:
        return False
    if line.size < 14:
        return False
    if line.y0 > 220:
        return False
    t = norm_space(line.text)
    if not t:
        return False
    # Exclude TOC headings like CHANGE HISTORY etc. (still could be non-black)
    if len(t) < 3:
        return False
    return True

def is_toc_entry(line):
    if not line.non_black:
        return False
    if line.size < 12:
        return False
    t = norm_space(line.text)
    return bool(RE_TOC_ITEM.match(t))

def clean_field_label(label):
    label = norm_space(label)
    # Remove leading numbering like "\17.\ " or "17." or "3."
    label = re.sub(r'^[\\]?\s*\d+(\.\d+)*\s*[\.\)]\s*', '', label).strip()
    # Remove trailing colon if present
    label = re.sub(r'\s*:\s*$', '', label).strip()
    return label

def extract_label_from_block(lines, idx_start, idx_end):
    # Join black label lines in a block, excluding Row markers and obvious headers.
    parts = []
    for i in range(idx_start, idx_end):
        t = norm_space(lines[i].text)
        if not t:
            continue
        if is_header_footer(lines[i]):
            continue
        if RE_ROW.match(t):
            continue
        if t.startswith('[') and t.endswith(']'):
            continue
        parts.append(t)
    label = clean_field_label(" ".join(parts))
    return label

def cluster_by_rows(lines, y_tol=3.0):
    # Group indices by approximate y0 (row bands)
    rows = []
    current = []
    last_y = None
    for i, ln in enumerate(lines):
        if is_header_footer(ln):
            continue
        y = ln.y0
        if last_y is None or abs(y - last_y) <= y_tol:
            current.append(i)
            last_y = y if last_y is None else (last_y + y) / 2.0
        else:
            rows.append(current)
            current = [i]
            last_y = y
    if current:
        rows.append(current)
    return rows

def extract(pages):
    out = []
    seen = set()  # (form_name, field_name, page)
    current_form = ""
    last_toc_form = ""

    for page_idx0, lines in pages:
        # Update form name from title if present
        title_lines = [ln for ln in lines if is_form_title_candidate(ln)]
        # Prefer the largest font non-black line near top
        if title_lines:
            title_lines.sort(key=lambda l: (-l.size, l.y0, l.x0))
            cand = norm_space(title_lines[0].text)
            # Avoid TOC headings by checking if page looks like TOC (many toc entries)
            toc_entries = [ln for ln in lines if is_toc_entry(ln)]
            if len(toc_entries) >= 5:
                # On TOC pages, update last_toc_form from entries but don't set current_form
                pass
            else:
                current_form = cand

        # Update last_toc_form if this is a TOC page
        toc_entries = [ln for ln in lines if is_toc_entry(ln)]
        if len(toc_entries) >= 5:
            # Keep the last entry on the page as context for subsequent pages
            toc_entries.sort(key=lambda l: (l.y0, l.x0))
            last_toc_form = norm_space(toc_entries[-1].text)
            # TOC pages have no fields
            continue

        form_name = current_form or last_toc_form or ""

        # Build quick access lists
        red_codes = [i for i, ln in enumerate(lines) if is_red_bracket(ln)]
        if not red_codes:
            continue

        # Precompute row clusters for label association
        rows = cluster_by_rows(lines, y_tol=3.5)
        idx_to_row = {}
        for r_i, idxs in enumerate(rows):
            for ii in idxs:
                idx_to_row[ii] = r_i

        # For each code, find label text to its left or above within same row block
        for ci in red_codes:
            code_ln = lines[ci]
            r = idx_to_row.get(ci, None)

            # Determine a vertical block: from previous "Row N" marker or previous code/type to this code
            # We'll search backwards for a plausible label start.
            start = max(0, ci - 25)
            # tighten start to after last Row marker
            for j in range(ci - 1, start - 1, -1):
                t = norm_space(lines[j].text)
                if RE_ROW.match(t):
                    start = j + 1
                    break

            # Candidate label lines: black, not bracketed, not options, mostly left of code
            label_idxs = []
            for j in range(start, ci):
                ln = lines[j]
                if ln.text.strip().startswith('['):
                    continue
                if is_header_footer(ln):
                    continue
                if ln.non_black:
                    continue
                t = norm_space(ln.text)
                if not t:
                    continue
                if RE_ROW.match(t):
                    continue
                # Exclude column headers like "Criteria", "Sample", etc. by position near top and larger size
                if ln.y0 < 140 and ln.size >= 10:
                    continue
                # Exclude obvious option lists on right side
                if is_option_like(ln) and ln.x0 > 400:
                    continue
                # Prefer lines left of the code, or same row but far left
                if ln.x0 <= code_ln.x0 - 10 or (r is not None and idx_to_row.get(j) == r and ln.x0 < code_ln.x0):
                    label_idxs.append(j)

            # If nothing found, try nearest preceding black line regardless of x (some layouts place code under label)
            if not label_idxs:
                for j in range(ci - 1, start - 1, -1):
                    ln = lines[j]
                    if ln.text.strip().startswith('['):
                        continue
                    if ln.non_black:
                        continue
                    t = norm_space(ln.text)
                    if not t or RE_ROW.match(t) or is_header_footer(ln):
                        continue
                    label_idxs = [j]
                    break

            if not label_idxs:
                continue

            # Merge contiguous label lines near each other in y (multi-line questions)
            # Take the last few label lines closest to the code, but include earlier ones if they are part of same paragraph.
            label_idxs.sort()
            # Keep only those within ~80 pts above code to avoid grabbing previous row text
            label_idxs = [j for j in label_idxs if lines[j].y0 >= code_ln.y0 - 90]

            # If still too many, keep the last block of consecutive-ish lines by y
            if len(label_idxs) > 1:
                # Build blocks by y gaps
                blocks = []
                cur = [label_idxs[0]]
                for j in label_idxs[1:]:
                    if lines[j].y0 - lines[cur[-1]].y0 <= 18:
                        cur.append(j)
                    else:
                        blocks.append(cur)
                        cur = [j]
                blocks.append(cur)
                # Choose block whose last line is closest above code
                blocks.sort(key=lambda b: abs(code_ln.y0 - lines[b[-1]].y0))
                chosen = blocks[0]
            else:
                chosen = label_idxs

            label = extract_label_from_block(lines, chosen[0], chosen[-1] + 1)
            if not label:
                continue
            # Avoid extracting pure headers like "If Yes, describe" when it's clearly a subfield? Actually it's a field label.
            # But avoid extracting generic column headers
            if len(label) <= 2:
                continue

            key = (form_name, label, page_idx0 + 1)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})

        # Also extract black labels that are immediately followed by a red code (some pages may omit code on same line)
        # This is a safety net; dedup by seen.
        for i, ln in enumerate(lines):
            if ln.non_black or ln.text.strip().startswith('[') or is_header_footer(ln):
                continue
            t = norm_space(ln.text)
            if not t or RE_ROW.match(t):
                continue
            # Look ahead a few lines for a red code at similar x (same field)
            for j in range(i + 1, min(len(lines), i + 6)):
                if is_red_bracket(lines[j]) and abs(lines[j].x0 - ln.x0) <= 40 and (lines[j].y0 - ln.y0) <= 40:
                    label = clean_field_label(t)
                    if label and len(label) > 2:
                        key = (form_name, label, page_idx0 + 1)
                        if key not in seen:
                            seen.add(key)
                            out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})
                    break

    return out
```