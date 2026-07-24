```python
# Observed layouts: (1) standard CRF pages with a prominent form title near top and bold field labels,
# (2) "variable list" pages that enumerate fields in a table where each row starts with a bracketed index "[n]",
# (3) multi-column header tables where fields appear as a band of many bold headers (often wrapped).
# Strategy: carry forward the current form title; extract field labels from variable-table "Name" column rows,
# and from bold left-side labels + detected multi-column header bands; structurally skip answer-option lists.

import re
import statistics
from typing import List, Tuple, Dict, Any, Iterable, Optional


_RE_BRACKET_NUM = re.compile(r"\[\s*\d+\s*\]")
_RE_CODE_ONLY = re.compile(r"^\[\s*\d+\s*\]$")
_RE_MOSTLY_MACHINE = re.compile(r"^[A-Za-z0-9_./-]{18,}$")
_RE_SPACES = re.compile(r"\s+")
_RE_HAS_LETTER = re.compile(r"\w", re.UNICODE)


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()  # (page_idx, form_name, field_name)
    current_form = ""

    for page_idx, lines in pages:
        if not lines:
            continue

        # Basic page stats
        sizes = [float(getattr(ln, "size", 0.0) or 0.0) for ln in lines]
        max_size = max(sizes) if sizes else 0.0
        med_size = statistics.median(sizes) if sizes else 0.0
        y_tol = _row_y_tol(med_size)

        # Update current form title (prefer prominent title; fallback to leftmost header form-name line)
        title = _detect_prominent_title(lines, max_size=max_size)
        if title:
            current_form = title
        else:
            header_form = _detect_header_form_name(lines)
            if header_form:
                current_form = header_form

        # Dispatch
        rows = _cluster_rows(lines, y_tol=y_tol)
        if _is_variable_table(rows):
            fields = _extract_variable_table_fields(rows)
        else:
            header_fields = _extract_header_band_fields(rows, max_size=max_size, med_size=med_size)
            body_fields = _extract_body_label_fields(rows, max_size=max_size, med_size=med_size)
            fields = header_fields + body_fields

        # Emit
        for field in fields:
            field_name = _clean_field_text(field)
            if not field_name:
                continue
            key = (page_idx, current_form or "", field_name)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {"form_name": current_form or "", "field_name": field_name, "page": int(page_idx) + 1}
            )

    return out


# ----------------------------
# Row clustering / geometry
# ----------------------------

def _row_y_tol(med_size: float) -> float:
    # Tolerant grouping across small fonts; keep deterministic.
    if med_size <= 0:
        return 2.5
    return max(1.6, min(3.6, 0.36 * med_size))


def _cluster_rows(lines: List[Any], y_tol: float) -> List[List[Any]]:
    rows: List[List[Any]] = []
    cur: List[Any] = []
    cur_y: Optional[float] = None

    for ln in lines:
        y = float(getattr(ln, "y0", 0.0) or 0.0)
        if cur_y is None:
            cur = [ln]
            cur_y = y
            continue
        if abs(y - cur_y) <= y_tol:
            cur.append(ln)
        else:
            cur.sort(key=lambda z: float(getattr(z, "x0", 0.0) or 0.0))
            rows.append(cur)
            cur = [ln]
            cur_y = y

    if cur:
        cur.sort(key=lambda z: float(getattr(z, "x0", 0.0) or 0.0))
        rows.append(cur)
    return rows


# ----------------------------
# Text helpers / filters
# ----------------------------

def _norm(s: str) -> str:
    return _RE_SPACES.sub(" ", (s or "").strip())


def _strip_codes(s: str) -> str:
    s = _RE_BRACKET_NUM.sub("", s or "")
    return _norm(s)


def _has_letters(s: str) -> bool:
    s = s or ""
    # Use unicode word chars; robust across languages.
    return bool(_RE_HAS_LETTER.search(s))


def _is_code_only_text(s: str) -> bool:
    return bool(_RE_CODE_ONLY.match(_norm(s)))


def _is_machine_chrome_text(s: str) -> bool:
    s = _norm(s)
    if not s:
        return True
    # Very long, underscored/alnum-only tracker strings.
    if _RE_MOSTLY_MACHINE.match(s) and ("_" in s or s.count("-") >= 3 or s.count("/") >= 2):
        return True
    # Likely page furniture: extremely machine-like without spaces.
    if len(s) >= 28 and " " not in s and any(ch.isdigit() for ch in s) and any(ch.isalpha() for ch in s):
        return True
    return False


def _clean_field_text(s: str) -> str:
    s = _strip_codes(s)
    s = _norm(s)
    # Avoid empty / trivial.
    if not s:
        return ""
    if _is_machine_chrome_text(s):
        return ""
    # Reject pure numbers/punctuation.
    if not _has_letters(s):
        return ""
    return s


def _split_multi_coded_segments(s: str) -> Optional[List[str]]:
    """
    If a single visual line contains multiple coded segments like:
      'A  [1] B  [2] C  [3]'
    split into ['A [1]', 'B [2]', 'C [3]'].
    Return None if not multi-coded.
    """
    s0 = s or ""
    matches = list(_RE_BRACKET_NUM.finditer(s0))
    if len(matches) <= 1:
        return None
    segs: List[str] = []
    start = 0
    for m in matches:
        end = m.end()
        seg = _norm(s0[start:end])
        if seg:
            segs.append(seg)
        start = end
    tail = _norm(s0[start:])
    if tail and _has_letters(_strip_codes(tail)):
        segs.append(tail)
    return [seg for seg in segs if seg]


# ----------------------------
# Form name detection
# ----------------------------

def _detect_prominent_title(lines: List[Any], max_size: float) -> str:
    if max_size <= 0:
        return ""
    # Prominent title tends to be the largest font, around y~70-90.
    cand = []
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0) or 0.0)
        x = float(getattr(ln, "x0", 0.0) or 0.0)
        sz = float(getattr(ln, "size", 0.0) or 0.0)
        txt = _norm(getattr(ln, "text", "") or "")
        if y < 55 or y > 120:
            continue
        if sz < 0.86 * max_size:
            continue
        if not _has_letters(txt) or _is_machine_chrome_text(txt):
            continue
        # Prefer left-ish titles; still allow moderately centered.
        if x > 260 and len(txt) < 6:
            continue
        cand.append((sz, -y, -len(txt), txt))

    if not cand:
        return ""
    cand.sort(reverse=True)
    return cand[0][3]


def _detect_header_form_name(lines: List[Any]) -> str:
    # Many pages repeat a small bold form name at x close to the chrome's left margin (x~33).
    min_x = min(float(getattr(ln, "x0", 0.0) or 0.0) for ln in lines) if lines else 0.0
    cand = []
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0) or 0.0)
        x = float(getattr(ln, "x0", 0.0) or 0.0)
        sz = float(getattr(ln, "size", 0.0) or 0.0)
        bold = bool(getattr(ln, "bold", False))
        txt = _norm(getattr(ln, "text", "") or "")
        if not bold or not txt:
            continue
        if y < 40 or y > 62:
            continue
        if x > min_x + 10:  # must be very left-aligned (avoid table headers)
            continue
        if sz < 5.5 or sz > 11.0:
            continue
        if _is_machine_chrome_text(txt) or _is_code_only_text(txt):
            continue
        if not _has_letters(txt):
            continue
        cand.append((len(txt), -sz, txt))
    if not cand:
        return ""
    cand.sort(reverse=True)
    return cand[0][2]


# ----------------------------
# Variable-table ("[n]" rows) extraction
# ----------------------------

def _is_variable_table(rows: List[List[Any]]) -> bool:
    """
    Detect the table layout where each variable row starts with a code-only '[n]' cell,
    and the human field label is in the next cell on the same row.
    """
    bracket_rows = 0
    bracket_rows_with_name = 0
    for row in rows:
        # find any code-only cell early in the row
        bracket_cells = [ln for ln in row if _is_code_only_text(getattr(ln, "text", "") or "")]
        if not bracket_cells:
            continue
        # in variable tables, the bracket cell is usually the leftmost text cell
        leftmost = min(bracket_cells, key=lambda z: float(getattr(z, "x0", 0.0) or 0.0))
        bx = float(getattr(leftmost, "x0", 0.0) or 0.0)
        by = float(getattr(leftmost, "y0", 0.0) or 0.0)
        if by < 60:  # header band: ignore
            continue
        bracket_rows += 1

        # look for a plausible "Name" cell on same row
        name_cells = []
        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            txt = _norm(getattr(ln, "text", "") or "")
            if x <= bx + 18:
                continue
            if x > bx + 260:
                continue
            if not txt or _is_code_only_text(txt) or _RE_BRACKET_NUM.fullmatch(txt):
                continue
            if _is_machine_chrome_text(txt):
                continue
            if not _has_letters(txt):
                continue
            name_cells.append(ln)
        if name_cells:
            bracket_rows_with_name += 1

    return bracket_rows >= 3 and bracket_rows_with_name >= max(2, int(0.6 * bracket_rows))


def _extract_variable_table_fields(rows: List[List[Any]]) -> List[str]:
    fields: List[str] = []

    # Collect candidate row starts (code-only "[n]" on the row)
    starts = []
    for i, row in enumerate(rows):
        for ln in row:
            if _is_code_only_text(getattr(ln, "text", "") or ""):
                y = float(getattr(ln, "y0", 0.0) or 0.0)
                if y >= 60:
                    starts.append((i, ln))
                    break

    # For each start row, pick the "Name" cell and join wrapped lines in the same column until next start row.
    for idx, (row_i, bracket_ln) in enumerate(starts):
        row = rows[row_i]
        bx = float(getattr(bracket_ln, "x0", 0.0) or 0.0)

        # Choose the leftmost plausible name cell to the right
        name_ln = None
        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            txt = _norm(getattr(ln, "text", "") or "")
            if x <= bx + 18 or x > bx + 260:
                continue
            if not txt or _is_code_only_text(txt) or _is_machine_chrome_text(txt):
                continue
            if not _has_letters(txt):
                continue
            if name_ln is None or x < float(getattr(name_ln, "x0", 0.0) or 0.0):
                name_ln = ln

        if name_ln is None:
            continue

        name_x = float(getattr(name_ln, "x0", 0.0) or 0.0)
        end_row_i = starts[idx + 1][0] if idx + 1 < len(starts) else len(rows)

        parts = [_norm(getattr(name_ln, "text", "") or "")]
        # Wrapped continuation lines usually keep the same x0 in the Name column.
        for rj in range(row_i + 1, end_row_i):
            for ln in rows[rj]:
                x = float(getattr(ln, "x0", 0.0) or 0.0)
                if abs(x - name_x) > 10:
                    continue
                txt = _norm(getattr(ln, "text", "") or "")
                if not txt:
                    continue
                # Avoid pulling in other columns.
                if x > name_x + 40:
                    continue
                if _is_code_only_text(txt) or _is_machine_chrome_text(txt):
                    continue
                # In this layout, continuation should still be human label text.
                if not _has_letters(txt):
                    continue
                parts.append(txt)

        fields.append(_norm(" ".join(parts)))

    return fields


# ----------------------------
# Header-band (multi-column) extraction
# ----------------------------

def _extract_header_band_fields(rows: List[List[Any]], max_size: float, med_size: float) -> List[str]:
    """
    Extract fields from dense multi-column header bands (tables).
    Handles wrapped headers by binning on x0 and concatenating top-to-bottom.
    Also handles single visual lines containing multiple coded segments.
    """
    fields: List[str] = []
    if not rows:
        return fields

    # Identify candidate header rows: many bold items spanning wide x, not in top chrome.
    candidate_row_idxs = []
    for i, row in enumerate(rows):
        y = float(getattr(row[0], "y0", 0.0) or 0.0)
        if y < 45:
            continue
        bolds = [ln for ln in row if bool(getattr(ln, "bold", False))]
        if len(bolds) < 3:
            continue
        xs = [float(getattr(ln, "x0", 0.0) or 0.0) for ln in bolds]
        span = (max(xs) - min(xs)) if xs else 0.0
        if span < 240 and len(bolds) < 5:
            continue
        # Avoid grabbing big titles.
        if max_size > 0:
            if all(float(getattr(ln, "size", 0.0) or 0.0) >= 0.75 * max_size for ln in bolds):
                continue
        candidate_row_idxs.append(i)

    if not candidate_row_idxs:
        return fields

    # Expand each candidate into a header block including nearby wrap rows.
    used = set()
    for start_i in candidate_row_idxs:
        if start_i in used:
            continue
        # Build block: start row plus immediately following rows that contain mostly bold small text.
        block = []
        i = start_i
        last_y = float(getattr(rows[i][0], "y0", 0.0) or 0.0)
        while i < len(rows):
            row = rows[i]
            y = float(getattr(row[0], "y0", 0.0) or 0.0)
            if i != start_i and (y - last_y) > 14.0:
                break
            bolds = [ln for ln in row if bool(getattr(ln, "bold", False))]
            if not bolds:
                break
            # Stop if this row looks like regular body label rows (few bolds and narrow span).
            xs = [float(getattr(ln, "x0", 0.0) or 0.0) for ln in bolds]
            span = (max(xs) - min(xs)) if xs else 0.0
            if len(bolds) < 2 and span < 180:
                break
            # Prefer smaller fonts within the header block.
            if max_size > 0:
                if any(float(getattr(ln, "size", 0.0) or 0.0) > 0.72 * max_size for ln in bolds):
                    if i != start_i:
                        break
            block.extend(bolds)
            used.add(i)
            last_y = y
            i += 1

        if not block:
            continue

        # First, emit any multi-coded segments directly (don't let binning concatenate them).
        bin_lines = []
        for ln in block:
            txt = _norm(getattr(ln, "text", "") or "")
            if not txt:
                continue
            segs = _split_multi_coded_segments(txt)
            if segs:
                for seg in segs:
                    fields.append(seg)
            else:
                bin_lines.append(ln)

        # Bin remaining by x0 and concatenate top-to-bottom to reconstruct wrapped headers.
        bins: List[Dict[str, Any]] = []
        for ln in bin_lines:
            txt = _norm(getattr(ln, "text", "") or "")
            if not txt:
                continue
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            y = float(getattr(ln, "y0", 0.0) or 0.0)

            placed = False
            for b in bins:
                if abs(x - b["x"]) <= 10.0:
                    b["items"].append((y, x, txt))
                    # keep a stable representative x
                    b["x"] = (b["x"] * 0.8) + (x * 0.2)
                    placed = True
                    break
            if not placed:
                bins.append({"x": x, "items": [(y, x, txt)]})

        bins.sort(key=lambda b: b["x"])
        for b in bins:
            items = sorted(b["items"])
            parts = []
            for _, __, t in items:
                if _is_code_only_text(t):
                    continue
                parts.append(t)
            joined = _norm(" ".join(parts))
            if joined:
                fields.append(joined)

    return fields


# ----------------------------
# Body label extraction (standard CRF pages)
# ----------------------------

def _extract_body_label_fields(rows: List[List[Any]], max_size: float, med_size: float) -> List[str]:
    fields: List[str] = []
    if not rows:
        return fields

    # Gather bold candidates in body region to estimate left margin.
    cand = []
    for row in rows:
        for ln in row:
            y = float(getattr(ln, "y0", 0.0) or 0.0)
            if y < 85:
                continue
            if not bool(getattr(ln, "bold", False)):
                continue
            txt = _norm(getattr(ln, "text", "") or "")
            if not txt or _is_code_only_text(txt) or _is_machine_chrome_text(txt):
                continue
            if max_size > 0 and float(getattr(ln, "size", 0.0) or 0.0) >= 0.75 * max_size:
                continue
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            if x > 320:
                continue
            if not _has_letters(_strip_codes(txt)):
                continue
            cand.append(x)

    if not cand:
        return fields

    cand.sort()
    base_left = cand[max(0, int(0.1 * (len(cand) - 1)))]  # 10th percentile

    # Helper: detect option lists (answer choices) under a parent label.
    def is_option_like(row_i: int, ln: Any) -> bool:
        x = float(getattr(ln, "x0", 0.0) or 0.0)
        y = float(getattr(ln, "y0", 0.0) or 0.0)
        sz = float(getattr(ln, "size", 0.0) or 0.0)
        if not (base_left + 4.0 <= x <= base_left + 26.0):
            return False

        # Need a nearby parent label above at (near) base_left.
        parent_found = False
        for up in range(row_i - 1, max(-1, row_i - 10), -1):
            for up_ln in rows[up]:
                if not bool(getattr(up_ln, "bold", False)):
                    continue
                up_y = float(getattr(up_ln, "y0", 0.0) or 0.0)
                if y - up_y > 45.0:
                    break
                up_x = float(getattr(up_ln, "x0", 0.0) or 0.0)
                if up_x <= base_left + 4.0:
                    up_txt = _strip_codes(_norm(getattr(up_ln, "text", "") or ""))
                    if up_txt and _has_letters(up_txt):
                        parent_found = True
                        break
            if parent_found:
                break
        if not parent_found:
            return False

        # Confirm a vertical list at same indentation (multiple subsequent lines at similar x).
        sibs = 0
        for dn in range(row_i + 1, min(len(rows), row_i + 18)):
            for dn_ln in rows[dn]:
                dn_x = float(getattr(dn_ln, "x0", 0.0) or 0.0)
                dn_y = float(getattr(dn_ln, "y0", 0.0) or 0.0)
                if dn_y - y > 130.0:
                    break
                if abs(dn_x - x) <= 6.0:
                    dn_txt = _strip_codes(_norm(getattr(dn_ln, "text", "") or ""))
                    if dn_txt and not _is_code_only_text(dn_txt):
                        sibs += 1
            if sibs >= 2:
                return True
        return False

    # Extract bold left-side labels, joining wrapped lines with same x.
    for i, row in enumerate(rows):
        for ln in row:
            y = float(getattr(ln, "y0", 0.0) or 0.0)
            if y < 85:
                continue
            if not bool(getattr(ln, "bold", False)):
                continue

            x = float(getattr(ln, "x0", 0.0) or 0.0)
            sz = float(getattr(ln, "size", 0.0) or 0.0)
            txt0 = _norm(getattr(ln, "text", "") or "")
            if not txt0 or _is_code_only_text(txt0):
                continue
            if _is_machine_chrome_text(txt0):
                continue
            if max_size > 0 and sz >= 0.75 * max_size:
                continue
            if x > 320:
                continue

            # Avoid extracting option items (checkbox/radio choices).
            if is_option_like(i, ln):
                continue

            # Join wrapped continuation lines below with same x and similar style.
            parts = [txt0]
            last_y = y
            j = i + 1
            while j < len(rows):
                next_row = rows[j]
                # Find a single best continuation candidate in this next row.
                cont = None
                cont_x = None
                cont_y = float(getattr(next_row[0], "y0", 0.0) or 0.0)
                if cont_y - last_y > max(11.0, 2.2 * sz):
                    break
                for nn in next_row:
                    nx = float(getattr(nn, "x0", 0.0) or 0.0)
                    if abs(nx - x) > 8.0:
                        continue
                    n_txt = _norm(getattr(nn, "text", "") or "")
                    if not n_txt or _is_code_only_text(n_txt):
                        continue
                    if _is_machine_chrome_text(n_txt):
                        continue
                    # Don't absorb a bracket-only marker line.
                    if _RE_CODE_ONLY.match(_norm(getattr(nn, "text", "") or "")):
                        continue
                    # Avoid accidentally absorbing an option list at an indented x.
                    if (base_left + 4.0 <= nx <= base_left + 26.0) and is_option_like(j, nn):
                        continue
                    cont = n_txt
                    cont_x = nx
                    break
                if cont is None:
                    break
                parts.append(cont)
                last_y = cont_y
                x = float(cont_x or x)
                j += 1

            joined = _norm(" ".join(parts))
            fields.append(joined)

    return fields
```
