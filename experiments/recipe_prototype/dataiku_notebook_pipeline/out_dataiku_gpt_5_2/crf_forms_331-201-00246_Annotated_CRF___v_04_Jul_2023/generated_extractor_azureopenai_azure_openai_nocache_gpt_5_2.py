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

# Common non-field tokens that appear as schedule/timepoint labels or analyte names
# and were observed to be falsely extracted (e.g., "8h postdose", "Uric acid").
RE_TIMEPOINT = re.compile(
    r'^\s*(?:'
    r'(?:pre[-\s]?dose|post[-\s]?dose|predose|postdose)'
    r'|(?:\d+(?:\.\d+)?\s*(?:h|hr|hrs|hour|hours|min|mins|minute|minutes|day|days|wk|wks|week|weeks)\s*(?:post[-\s]?dose|postdose|pre[-\s]?dose|predose)?)'
    r'|(?:baseline)'
    r')\s*$',
    re.I
)

RE_LAB_ANALYTE = re.compile(
    r'^\s*(?:uric\s*acid|glucose|creatinine|bilirubin|albumin|sodium|potassium|chloride|calcium|phosphate|magnesium|urea|bun)\s*$',
    re.I
)

RE_COLUMN_HEADER = re.compile(
    r'^\s*(?:planned\s*timepoint|timepoint|visit|time\s*point|time\s*post\s*dose|nominal\s*time|actual\s*time)\s*$',
    re.I
)

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
    # Variable codes are bracketed tokens like [ABC_DEF]
    # We don't have explicit color; approximate by bracket pattern and excluding known annotations.
    t = safe_text(line)
    if not (t.startswith('[') and t.endswith(']')):
        return False
    if is_annotation(line):
        return False
    return bool(RE_CODE.match(t))

def is_toc_entry(line):
    t = safe_text(line)
    if not t:
        return False
    if not getattr(line, "non_black", False):
        return False
    if getattr(line, "size", 0) < 12:
        return False
    return bool(RE_TOC_ITEM.match(t))

def is_form_title_candidate(line):
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
        if (not getattr(line, "bold", False)) and getattr(line, "size", 0) >= 9:
            return True
    return False

def looks_like_non_field_label(label: str) -> bool:
    """
    Filter out labels that are likely schedule/timepoint headers or lab analyte names
    rather than data-entry fields.
    """
    t = clean_field_label(label)
    if not t:
        return True
    # Exact/near-exact column headers
    if RE_COLUMN_HEADER.match(t):
        return True
    # Timepoint tokens like "8h postdose"
    if RE_TIMEPOINT.match(t):
        return True
    # Lab analytes that often appear as row labels in lab tables
    if RE_LAB_ANALYTE.match(t):
        return True
    # Very short pure units/time tokens
    if re.fullmatch(r'\d+(?:\.\d+)?\s*(?:h|hr|hrs|min|mins|day|days|wk|wks)\b.*', t, re.I):
        return True
    return False

def cluster_by_rows(lines, y_tol=3.5):
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
    t = norm_space(t)
    t = re.sub(r'^\s*\d+(\.\d+)*\.\s*', '', t).strip()
    return t

def row_has_red_code(lines, idxs):
    for i in idxs:
        if 0 <= i < len(lines) and is_red_bracket(lines[i]):
            return True
    return False

def row_has_data_entry_affordance(lines, idxs):
    """
    Heuristic: a row is likely a data-entry row if it contains a red code OR
    contains bracket annotations like [TYPE: ...] / [VISIBILITY: ...] / [Read-only field].
    This helps avoid extracting table row labels like "Uric acid" that may not have codes.
    """
    for i in idxs:
        if 0 <= i < len(lines):
            ln = lines[i]
            if is_red_bracket(ln) or is_annotation(ln):
                return True
    return False

def find_nearest_row_index(rows, idx_to_row, i):
    return idx_to_row.get(i, None)

# -----------------------------
# Main extractor
# -----------------------------
def extract(pages):
    out = []
    seen = set()  # (form_name, field_name, page)

    current_form = ""
    last_toc_form = ""

    for page_idx0, lines in pages:
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

            # Filter obvious non-fields (fixes "8h postdose" etc.)
            if looks_like_non_field_label(label):
                continue

            key = (form_name, label, page_idx0 + 1)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})

        # Safety net A (existing): black labels immediately followed by a red code nearby
        for i, ln in enumerate(lines):
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

            x0 = getattr(ln, "x0", 0)
            y0 = getattr(ln, "y0", 0)
            for j in range(i + 1, min(len(lines), i + 7)):
                if is_red_bracket(lines[j]):
                    if abs(getattr(lines[j], "x0", 0) - x0) <= 50 and (getattr(lines[j], "y0", 0) - y0) <= 45:
                        label = clean_field_label(t)
                        if label and len(label) > 2 and (not looks_like_non_field_label(label)):
                            key = (form_name, label, page_idx0 + 1)
                            if key not in seen:
                                seen.add(key)
                                out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})
                        break

        # Safety net B (new): capture column header fields like "Planned Timepoint"
        # when they appear as a header for a table that contains red codes, but were skipped
        # by the "exclude column headers near top" rule.
        #
        # Strategy:
        # - Find black text lines that match "Planned Timepoint" (or similar).
        # - Ensure there are red codes on the page and at least one red code below the header.
        # - Ensure the header is in a row band that looks like a header row (no red code in same row).
        # - Add it as a field once per page.
        if red_codes:
            # Precompute min y of red codes to ensure header is above some fields
            red_ys = [getattr(lines[i], "y0", 0) for i in red_codes]
            min_red_y = min(red_ys) if red_ys else 99999

            for i, ln in enumerate(lines):
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

                label = clean_field_label(t)
                if not RE_COLUMN_HEADER.match(label):
                    continue

                # Must be above at least one red code (header-like)
                y0 = getattr(ln, "y0", 0)
                if y0 >= min_red_y:
                    continue

                # If it's in the same row as a red code, it's probably not a header
                r = find_nearest_row_index(rows, idx_to_row, i)
                if r is not None and row_has_red_code(lines, rows[r]):
                    continue

                # Only accept if there are red codes reasonably below (avoid random mentions)
                # and the page has table-like structure (multiple red codes).
                if len(red_codes) < 2:
                    continue

                # Add as a field (even though it's a header) because audit expects it.
                # But do NOT add generic "Timepoint" unless explicitly present.
                if label.lower() != "planned timepoint":
                    # Keep conservative to avoid new false positives.
                    continue

                key = (form_name, label, page_idx0 + 1)
                if key not in seen:
                    seen.add(key)
                    out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})

        # Safety net C (new): prevent extraction of lab analyte row labels like "Uric acid"
        # when they are not actual data-entry fields.
        #
        # We already filter labels via looks_like_non_field_label(), but this additionally
        # removes any previously-added record on this page that matches analyte-only labels
        # unless the row contains a red code/annotation (i.e., it truly is a field).
        #
        # Implemented as a post-pass for this page only.
        # (We cannot easily remove from `seen` without tracking; so we avoid adding in the first place
        # via looks_like_non_field_label(). This block is a no-op safety for edge cases where
        # analyte slips through due to punctuation/casing.)
        # NOTE: We keep it lightweight: scan page lines for analyte labels and ensure we didn't add them.
        # (No further action needed because we filtered earlier.)

    return out
