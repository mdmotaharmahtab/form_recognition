```python
import re
from collections import defaultdict

# -----------------------------
# Regexes / helpers
# -----------------------------
RE_CODE = re.compile(r'^\[[A-Z0-9_]+\]$')
RE_TYPE = re.compile(r'^\[TYPE\s*:\s*.*\]$', re.I)
RE_VIS = re.compile(r'^\[VISIBILITY\s*:\s*.*\]$', re.I)
RE_READONLY = re.compile(r'^\[Read-only field\]$', re.I)
RE_ROW = re.compile(r'^\s*Row\s+\d+\s*$', re.I)
RE_PAGE = re.compile(r'^\s*Page\s+\d+\s+of\s+\d+\s*$', re.I)
RE_TOC_ITEM = re.compile(r'^\s*\d+(\.\d+)*\.\s+\S.*$')  # "3.21. Something"
RE_JUNK_BRACKET = re.compile(r'^\[(TYPE|VISIBILITY|READ-ONLY|READ ONLY|SCANNER)\b', re.I)

def norm_space(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '')).strip()

def safe_text(line) -> str:
    return norm_space(getattr(line, "text", "") or "")

def is_header_footer(line):
    t = safe_text(line)
    if not t:
        return False
    if RE_PAGE.match(t):
        return True
    if t in ("Pack Version",):
        return True
    # sometimes footer has just a number
    if t.isdigit() and len(t) <= 3:
        return True
    return False

def is_annotation(line):
    t = safe_text(line)
    return bool(RE_TYPE.match(t) or RE_VIS.match(t) or RE_READONLY.match(t) or RE_JUNK_BRACKET.match(t))

def is_red_bracket(line):
    # In the observed docs, variable codes are red bracketed tokens like [ABC_DEF]
    # We don't have explicit color; we approximate by bracket pattern and excluding known annotations.
    t = safe_text(line)
    if not (t.startswith('[') and t.endswith(']')):
        return False
    if is_annotation(line):
        return False
    return bool(RE_CODE.match(t))

def is_toc_entry(line):
    # TOC entries are blue-ish (non_black) and look like "3.21. Something"
    t = safe_text(line)
    if not t:
        return False
    if not getattr(line, "non_black", False):
        return False
    if getattr(line, "size", 0) < 12:
        return False
    return bool(RE_TOC_ITEM.match(t))

def is_form_title_candidate(line):
    # Large blue title near top
    t = safe_text(line)
    if not t:
        return False
    if not getattr(line, "non_black", False):
        return False
    if getattr(line, "size", 0) < 14:
        return False
    if getattr(line, "y0", 9999) > 240:
        return False
    if len(t) < 3:
        return False
    return True

def clean_field_label(label: str) -> str:
    label = norm_space(label)
    # Remove leading numbering like "\17.\ " or "17." or "3."
    label = re.sub(r'^[\\]?\s*\d+(\.\d+)*\s*[\.\)]\s*', '', label).strip()
    # Remove trailing colon
    label = re.sub(r'\s*:\s*$', '', label).strip()
    return label

def is_option_like(line):
    # Heuristic: short tokens that are likely radio options (Yes/No etc.)
    t = safe_text(line)
    if not t:
        return False
    if len(t) <= 12:
        # If it's not bold and reasonably sized, often options
        if (not getattr(line, "bold", False)) and getattr(line, "size", 0) >= 9:
            return True
    return False

def cluster_by_rows(lines, y_tol=3.5):
    """
    Group line indices into row bands by y0 proximity.
    IMPORTANT: robust to empty input and header/footer filtering.
    """
    rows = []
    current = []
    last_y = None
    for i, ln in enumerate(lines):
        if is_header_footer(ln):
            continue
        y = getattr(ln, "y0", None)
        if y is None:
            continue
        if last_y is None or abs(y - last_y) <= y_tol:
            current.append(i)
            last_y = y if last_y is None else (last_y + y) / 2.0
        else:
            if current:
                rows.append(current)
            current = [i]
            last_y = y
    if current:
        rows.append(current)
    return rows

def extract_label_from_block(lines, idxs):
    """
    Join black label lines in idxs, excluding row markers, headers, bracket tokens.
    idxs: list of indices (already chosen).
    """
    parts = []
    for i in idxs:
        if i < 0 or i >= len(lines):
            continue
        ln = lines[i]
        t = safe_text(ln)
        if not t:
            continue
        if is_header_footer(ln):
            continue
        if RE_ROW.match(t):
            continue
        if t.startswith('[') and t.endswith(']'):
            continue
        parts.append(t)
    return clean_field_label(" ".join(parts))

def page_looks_like_toc(lines):
    toc_entries = [ln for ln in lines if is_toc_entry(ln)]
    return len(toc_entries) >= 5

def parse_toc_entry_text(t):
    """
    Convert "3.21. Something" -> "Something"
    """
    t = norm_space(t)
    t = re.sub(r'^\s*\d+(\.\d+)*\.\s*', '', t).strip()
    return t

# -----------------------------
# Main extractor
# -----------------------------
def extract(pages):
    out = []
    seen = set()  # (form_name, field_name, page)

    current_form = ""
    last_toc_form = ""

    for page_idx0, lines in pages:
        # Defensive: ensure lines is a list
        if not lines:
            continue

        # Detect TOC pages early
        is_toc = page_looks_like_toc(lines)

        # Update last_toc_form on TOC pages (use last entry on page)
        if is_toc:
            toc_entries = [ln for ln in lines if is_toc_entry(ln)]
            toc_entries.sort(key=lambda l: (getattr(l, "y0", 0), getattr(l, "x0", 0)))
            if toc_entries:
                last_toc_form = parse_toc_entry_text(safe_text(toc_entries[-1]))
            # TOC pages have no fields
            continue

        # Update current_form from title if present (non-TOC pages)
        title_lines = [ln for ln in lines if is_form_title_candidate(ln)]
        if title_lines:
            title_lines.sort(key=lambda l: (-getattr(l, "size", 0), getattr(l, "y0", 0), getattr(l, "x0", 0)))
            cand = safe_text(title_lines[0])
            if cand:
                current_form = cand

        form_name = current_form or last_toc_form or ""

        # Find all variable codes
        red_codes = [i for i, ln in enumerate(lines) if is_red_bracket(ln)]
        if not red_codes:
            continue

        # Row clustering for same-row association
        rows = cluster_by_rows(lines, y_tol=3.5)
        idx_to_row = {}
        for r_i, idxs in enumerate(rows):
            for ii in idxs:
                idx_to_row[ii] = r_i

        # Helper to choose best label indices for a given code index
        def choose_label_indices(ci):
            if ci < 0 or ci >= len(lines):
                return []

            code_ln = lines[ci]
            code_y = getattr(code_ln, "y0", 0)
            code_x = getattr(code_ln, "x0", 0)
            code_row = idx_to_row.get(ci, None)

            # Search window
            start = max(0, ci - 30)

            # Tighten start to after last "Row N" marker
            for j in range(ci - 1, start - 1, -1):
                t = safe_text(lines[j])
                if RE_ROW.match(t):
                    start = j + 1
                    break

            # Candidate label lines
            label_idxs = []
            for j in range(start, ci):
                ln = lines[j]
                t = safe_text(ln)
                if not t:
                    continue
                if is_header_footer(ln):
                    continue
                if t.startswith('[') and t.endswith(']'):
                    continue
                if getattr(ln, "non_black", False):
                    continue
                if RE_ROW.match(t):
                    continue

                # Exclude likely column headers near top
                if getattr(ln, "y0", 9999) < 140 and getattr(ln, "size", 0) >= 10:
                    continue

                # Exclude option lists on far right
                if is_option_like(ln) and getattr(ln, "x0", 0) > 400:
                    continue

                # Prefer left of code, or same row and left-ish
                x0 = getattr(ln, "x0", 0)
                same_row = (code_row is not None and idx_to_row.get(j) == code_row)
                if x0 <= code_x - 10 or (same_row and x0 < code_x):
                    label_idxs.append(j)

            # Fallback: nearest preceding black non-bracket line
            if not label_idxs:
                for j in range(ci - 1, start - 1, -1):
                    ln = lines[j]
                    t = safe_text(ln)
                    if not t:
                        continue
                    if is_header_footer(ln):
                        continue
                    if getattr(ln, "non_black", False):
                        continue
                    if t.startswith('[') and t.endswith(']'):
                        continue
                    if RE_ROW.match(t):
                        continue
                    label_idxs = [j]
                    break

            if not label_idxs:
                return []

            # Keep only those within ~90 pts above code to avoid previous row bleed
            label_idxs = [j for j in label_idxs if getattr(lines[j], "y0", 0) >= code_y - 90]
            if not label_idxs:
                return []

            label_idxs.sort()

            # If multiple, choose the block closest to the code (by last line y)
            if len(label_idxs) > 1:
                blocks = []
                cur = [label_idxs[0]]
                for j in label_idxs[1:]:
                    if getattr(lines[j], "y0", 0) - getattr(lines[cur[-1]], "y0", 0) <= 18:
                        cur.append(j)
                    else:
                        blocks.append(cur)
                        cur = [j]
                blocks.append(cur)

                # Choose block whose last line is closest above code
                blocks.sort(key=lambda b: abs(code_y - getattr(lines[b[-1]], "y0", 0)))
                return blocks[0]

            return label_idxs

        # Primary extraction: for each code, associate label
        for ci in red_codes:
            chosen = choose_label_indices(ci)
            if not chosen:
                continue

            label = extract_label_from_block(lines, chosen)
            if not label or len(label) <= 2:
                continue

            key = (form_name, label, page_idx0 + 1)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})

        # Safety net: black labels immediately followed by a red code nearby
        for i, ln in enumerate(lines):
            if i < 0 or i >= len(lines):
                continue
            if is_header_footer(ln):
                continue
            if getattr(ln, "non_black", False):
                continue
            t = safe_text(ln)
            if not t:
                continue
            if t.startswith('[') and t.endswith(']'):
                continue
            if RE_ROW.match(t):
                continue

            # Look ahead a few lines for a red code at similar x and close y
            x0 = getattr(ln, "x0", 0)
            y0 = getattr(ln, "y0", 0)
            for j in range(i + 1, min(len(lines), i + 7)):
                if is_red_bracket(lines[j]):
                    if abs(getattr(lines[j], "x0", 0) - x0) <= 50 and (getattr(lines[j], "y0", 0) - y0) <= 45:
                        label = clean_field_label(t)
                        if label and len(label) > 2:
                            key = (form_name, label, page_idx0 + 1)
                            if key not in seen:
                                seen.add(key)
                                out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})
                        break

    return out
```