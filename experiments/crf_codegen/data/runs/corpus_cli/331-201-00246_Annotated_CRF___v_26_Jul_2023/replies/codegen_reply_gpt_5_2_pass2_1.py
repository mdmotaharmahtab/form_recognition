```python
# Observed layouts: (1) annotated CRF pages where each entry field has nearby colored bracket annotations
# (e.g., [FIELDID], [TYPE: ...], [VISIBILITY: ...]); (2) table-style pages with column headers near top;
# (3) some non-data pages (TOC/schedule, cover/legal, change log). Strategy: carry forward a form title
# from prominent colored top-left headers; extract fields primarily by anchoring on bracketed field codes
# and mapping to the nearest human label (with wrap-joining), plus extracting table column headers.

import re
import unicodedata
from typing import List, Tuple, Dict, Optional


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1
        if not lines:
            continue

        form_title = _detect_form_title(lines)
        if form_title:
            current_form = form_title

        # Precompute table headers (used both standalone and as mapping targets for table cell field codes)
        header_cols = _detect_table_headers(lines)

        # "TOC/schedule" pages: blue numbered list, no field codes, no table headers => skip
        if not _has_any_field_code(lines) and not header_cols and _looks_like_toc_page(lines):
            continue

        page_seen = set()  # (form_name, field_name) dedupe within page

        # 1) Extract from field codes (colored bracketed ids like [VISDAT], [RPF3], [LBREQ8], etc.)
        code_idxs = [i for i, ln in enumerate(lines) if _is_field_id_code_line(ln)]
        for ci in code_idxs:
            code_line = lines[ci]
            field_name = ""

            # Prefer column header mapping for table-like pages/cells
            if header_cols and code_line.y0 > 165 and code_line.x0 > 150:
                hdr = _header_for_x(header_cols, code_line.x0)
                if hdr:
                    field_name = hdr

            if not field_name:
                field_name = _label_near_code(lines, ci)

            field_name = _clean_label(field_name)
            if not field_name or not _contains_letter(field_name):
                continue
            if _looks_like_row_label(field_name):
                continue

            form_name = current_form or ""
            key = (form_name, field_name)
            if key in page_seen:
                continue
            page_seen.add(key)
            out.append({"form_name": form_name, "field_name": field_name, "page": page_num})

        # 2) Table pages without codes in samples: extract column headers as fields
        if header_cols:
            for hdr in header_cols:
                field_name = _clean_label(hdr["text"])
                if not field_name or not _contains_letter(field_name):
                    continue
                if _looks_like_row_label(field_name):
                    continue
                form_name = current_form or ""
                key = (form_name, field_name)
                if key in page_seen:
                    continue
                page_seen.add(key)
                out.append({"form_name": form_name, "field_name": field_name, "page": page_num})

        # 3) "Instruction + many option tokens" pages: treat instruction as the field label (options are not fields)
        instr = _detect_instruction_field(lines)
        if instr:
            field_name = _clean_label(instr)
            if field_name and _contains_letter(field_name):
                form_name = current_form or ""
                key = (form_name, field_name)
                if key not in page_seen:
                    page_seen.add(key)
                    out.append({"form_name": form_name, "field_name": field_name, "page": page_num})

    return out


# ------------------------- title detection -------------------------

def _detect_form_title(lines) -> str:
    # Prefer prominent colored (non-black) top-left header around y~150 seen across CRF forms.
    cands = []
    for ln in lines:
        if ln.text and not ln.text.startswith("[") and ln.y0 < 220 and ln.x0 < 170:
            if ln.non_black and ln.size >= 13.5 and not _is_page_footer(ln.text):
                cands.append(ln)

    if cands:
        # prioritize larger size, then higher (smaller y), then bolder
        cands.sort(key=lambda l: (-l.size, l.y0, -int(bool(l.bold)), l.x0))
        return _clean_title(cands[0].text)

    # Fallback: if no colored title, use the largest top-band bold text (but avoid "Annotated CRF"/document cover feel).
    top = [ln for ln in lines if ln.y0 < 200 and ln.x0 < 250 and ln.text and not ln.text.startswith("[")]
    if not top:
        return ""
    max_size = max(ln.size for ln in top)
    big = [ln for ln in top if ln.size >= max_size - 0.5 and (ln.bold or max_size >= 16)]
    if big:
        big.sort(key=lambda l: (l.y0, l.x0))
        t = _clean_title(big[0].text)
        # guard: extremely generic cover lines can be huge; only accept if reasonable length
        if t and len(t) <= 80 and not _is_page_footer(t):
            return t
    return ""


def _clean_title(s: str) -> str:
    s = _norm_space(s)
    s = s.strip(" -\t")
    return s


# ------------------------- field-code anchoring -------------------------

_FIELD_ID_RE = re.compile(r"^\[[A-Za-z0-9_]+\]$")

def _has_any_field_code(lines) -> bool:
    return any(_is_field_id_code_line(ln) for ln in lines)


def _is_field_id_code_line(ln) -> bool:
    # Field IDs are bracketed and colored; exclude structural/type/visibility/read-only annotations.
    t = ln.text or ""
    if not ln.non_black:
        return False
    if not t.startswith("[") or not t.endswith("]"):
        return False
    if not _FIELD_ID_RE.match(t):
        return False
    up = t.upper()
    # These are not field IDs in this document style; they are descriptors.
    if up.startswith("[TYPE") or up.startswith("[VISIBILITY") or up.startswith("[READ-ONLY"):
        return False
    return True


def _is_annotation_descriptor_line(ln) -> bool:
    t = ln.text or ""
    if not ln.non_black:
        return False
    if not t.startswith("["):
        return False
    up = t.upper()
    return (
        up.startswith("[TYPE") or
        up.startswith("[VISIBILITY") or
        up.startswith("[READ-ONLY") or
        up.startswith("[RANGE") or
        up.startswith("[CALC") or
        up.startswith("[DERIVE")
    )


def _label_near_code(lines, code_idx: int) -> str:
    code = lines[code_idx]
    cy = code.y0

    # Search window
    above = []
    below = []

    # nearest above within ~85pt
    for j in range(code_idx - 1, -1, -1):
        ln = lines[j]
        if (cy - ln.y0) > 110:
            break
        if _is_bad_label_line(ln):
            continue
        if _contains_letter(ln.text or ""):
            above.append((cy - ln.y0, j))

    # nearest below within ~190pt
    for j in range(code_idx + 1, len(lines)):
        ln = lines[j]
        if (ln.y0 - cy) > 210:
            break
        if _is_bad_label_line(ln):
            continue
        if _contains_letter(ln.text or ""):
            below.append((ln.y0 - cy, j))

    # Prefer above if close, otherwise below
    pick_j = None
    if above:
        above.sort(key=lambda x: x[0])
        if above[0][0] <= 85:
            pick_j = above[0][1]
    if pick_j is None and below:
        below.sort(key=lambda x: x[0])
        pick_j = below[0][1]
    if pick_j is None:
        return ""

    return _join_wrapped_label(lines, pick_j, stop_y=cy, code_idx=code_idx)


def _join_wrapped_label(lines, anchor_idx: int, stop_y: float, code_idx: int) -> str:
    anchor = lines[anchor_idx]
    ax = anchor.x0
    asz = anchor.size

    # Define wrap criteria: same left margin, similar font size, small vertical gap, not annotations/codes.
    def is_wrap_line(ln) -> bool:
        if _is_bad_label_line(ln):
            return False
        if abs(ln.x0 - ax) > 30:
            return False
        if abs(ln.size - asz) > 2.0:
            return False
        return True

    idxs = [anchor_idx]

    # Extend upward
    prev = anchor
    for j in range(anchor_idx - 1, -1, -1):
        ln = lines[j]
        if (prev.y0 - ln.y0) > 20:
            break
        if j == code_idx:
            break
        if ln.y0 > stop_y + 1:
            continue
        if is_wrap_line(ln):
            idxs.append(j)
            prev = ln
        else:
            break

    # Extend downward
    prev = anchor
    for j in range(anchor_idx + 1, len(lines)):
        ln = lines[j]
        if (ln.y0 - prev.y0) > 20:
            break
        if j == code_idx:
            break
        if ln.text and ln.text.startswith("[") and ln.non_black:
            break
        if is_wrap_line(ln):
            idxs.append(j)
            prev = ln
        else:
            break

    idxs = sorted(set(idxs))
    parts = [lines[i].text for i in idxs if lines[i].text]
    return _norm_space(" ".join(parts))


def _is_bad_label_line(ln) -> bool:
    t = ln.text or ""
    if not t:
        return True
    if t.startswith("["):
        return True
    if _is_page_footer(t):
        return True
    if ln.non_black and not _contains_letter(t):
        return True
    if _looks_like_row_label(t):
        return True
    # Avoid obvious table filler/markers
    if t.strip() in {"•", "-", "–", "—"}:
        return True
    return False


# ------------------------- table headers -------------------------

def _detect_table_headers(lines):
    # Candidate header band around y ~ 110-165 with ~10.5pt black text.
    cands = []
    for ln in lines:
        if not ln.text or ln.text.startswith("["):
            continue
        if ln.non_black:
            continue
        if ln.y0 < 95 or ln.y0 > 170:
            continue
        if ln.size < 9.0 or ln.size > 12.8:
            continue
        if _is_page_footer(ln.text):
            continue
        # Exclude trivial/row labels that often appear around tables
        if _looks_like_row_label(ln.text):
            continue
        cands.append(ln)

    if len(cands) < 3:
        return []

    # Cluster by x into columns (tolerant)
    cands.sort(key=lambda l: (l.x0, l.y0))
    cols = []
    for ln in cands:
        placed = False
        for col in cols:
            if abs(ln.x0 - col["x"]) <= 45:
                col["items"].append(ln)
                # keep representative x near median-ish
                col["x"] = (col["x"] * 3 + ln.x0) / 4.0
                placed = True
                break
        if not placed:
            cols.append({"x": ln.x0, "items": [ln]})

    # Keep only columns that look like headers (not a single stray word)
    cleaned = []
    for col in cols:
        items = sorted(col["items"], key=lambda l: l.y0)
        txt = _norm_space(" ".join(i.text for i in items if i.text))
        txt = _clean_label(txt)
        if txt and _contains_letter(txt):
            cleaned.append({"x": col["x"], "text": txt})

    cleaned.sort(key=lambda c: c["x"])
    if len(cleaned) < 3:
        return []

    # Ensure it spans a meaningful width (multi-column table)
    if cleaned[-1]["x"] - cleaned[0]["x"] < 220:
        return []

    return cleaned


def _header_for_x(header_cols, x: float) -> str:
    best = None
    best_d = 10**9
    for col in header_cols:
        d = abs(col["x"] - x)
        if d < best_d:
            best_d = d
            best = col["text"]
    if best is None:
        return ""
    return best if best_d <= 95 else ""


# ------------------------- special page patterns -------------------------

def _looks_like_toc_page(lines) -> bool:
    # Many blue lines, mid-page, similar size (~15), often numbered at start; no codes.
    blueish = [ln for ln in lines if ln.non_black and ln.size >= 13 and (ln.text and not ln.text.startswith("["))]
    if len(blueish) < 8:
        return False
    # If most colored lines begin with digit/digit-dot patterns, it's likely an index/schedule listing.
    def looks_numbered(t: str) -> bool:
        t = t.strip()
        return bool(re.match(r"^\d+(\.\d+)*\.", t)) or bool(re.match(r"^\d+\s*$", t))

    numbered = sum(1 for ln in blueish if looks_numbered(ln.text or ""))
    # Alternatively, colored lines concentrated in a vertical list
    ys = [ln.y0 for ln in blueish]
    if numbered >= max(3, len(blueish) // 3):
        return True
    if min(ys) > 220 and (max(ys) - min(ys)) > 250 and len(blueish) >= 12:
        return True
    return False


def _detect_instruction_field(lines) -> str:
    # One long instruction sentence near top-left + many short tokens in right column.
    instr = None
    for ln in lines:
        if ln.y0 > 170:
            break
        if ln.x0 < 120 and (ln.size >= 8.0 and ln.size <= 10.5) and (not ln.non_black):
            t = _norm_space(ln.text or "")
            if len(t) >= 40 and _contains_letter(t) and t.endswith("."):
                instr = t
                break
    if not instr:
        return ""

    right_tokens = 0
    for ln in lines:
        if ln.x0 > 330 and ln.y0 >= 160 and ln.y0 <= 740 and (ln.size >= 9.0 and ln.size <= 12.5) and (not ln.non_black):
            t = (ln.text or "").strip()
            if 2 <= len(t) <= 10 and re.match(r"^[A-Z0-9]+$", t):
                right_tokens += 1
    if right_tokens >= 10:
        return instr
    return ""


# ------------------------- text utilities -------------------------

def _norm_space(s: str) -> str:
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_label(s: str) -> str:
    s = _norm_space(s)
    # remove leading bullet-only markers but keep meaningful punctuation inside
    s = re.sub(r"^[\u2022•\-\–\—\s]+", "", s).strip()
    s = s.strip()
    return s


def _contains_letter(s: str) -> bool:
    for ch in s:
        if unicodedata.category(ch).startswith("L"):
            return True
    return False


def _looks_like_row_label(s: str) -> bool:
    s = _norm_space(s)
    return bool(re.match(r"^Row\s*\d+\s*$", s, flags=re.IGNORECASE))


def _is_page_footer(text: str) -> bool:
    t = _norm_space(text)
    return bool(re.match(r"^Page\s+\d+\s+of\s+\d+\s*$", t, flags=re.IGNORECASE))
```
