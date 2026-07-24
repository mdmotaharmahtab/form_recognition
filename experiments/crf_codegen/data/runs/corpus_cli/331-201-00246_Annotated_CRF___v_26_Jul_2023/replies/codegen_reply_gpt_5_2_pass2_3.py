```python
import re
import unicodedata
from typing import List, Tuple, Dict, Optional


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    current_form = ""

    for page_idx0, raw_lines in pages:
        page_num = page_idx0 + 1
        if not raw_lines:
            continue

        # Normalize reading order to make neighborhood heuristics stable.
        lines = sorted(raw_lines, key=lambda ln: (getattr(ln, "y0", 0.0), getattr(ln, "x0", 0.0)))

        has_code = _has_any_field_code(lines)
        has_desc = _has_any_descriptor(lines)
        header_cols = _detect_table_headers(lines)

        # Never let TOC-like pages change the current form.
        if (not has_code) and (not has_desc) and (not header_cols) and _looks_like_toc_page(lines):
            continue

        form_title = _detect_form_title(lines)
        if form_title:
            current_form = form_title

        # If this page has annotation descriptors but no field-id codes, it often uses
        # a left header as the section/form title.
        if (not has_code) and has_desc:
            left = _detect_left_header_title(lines)
            if left:
                current_form = left

        page_seen = set()  # (form_name, field_name) dedupe within page
        form_name = current_form or ""

        # 1) Extract from field codes (colored bracketed ids like [VISDAT], [RPF3], [LBREQ8], etc.)
        code_idxs = [i for i, ln in enumerate(lines) if _is_field_id_code_line(ln)]
        for ci in code_idxs:
            code_line = lines[ci]
            field_name = ""

            # Prefer column header mapping for table-like pages/cells
            if header_cols and getattr(code_line, "y0", 0.0) > 165 and getattr(code_line, "x0", 0.0) > 150:
                hdr = _header_for_x(header_cols, getattr(code_line, "x0", 0.0))
                if hdr:
                    field_name = hdr

            if not field_name:
                field_name = _label_near_code(lines, ci)

            field_name = _clean_label(field_name)
            if not field_name or not _contains_letter(field_name):
                continue
            if _looks_like_row_label(field_name):
                continue
            if _looks_like_option_anchor(field_name):
                continue
            if _looks_like_pure_value(field_name):
                continue
            if _looks_like_page_header_field(field_name, code_line, lines):
                continue

            key = (form_name, field_name)
            if key in page_seen:
                continue
            page_seen.add(key)
            out.append({"form_name": form_name, "field_name": field_name, "page": page_num})

        # 1b) Descriptor-only pages: infer label near descriptor lines (but never treat option lines as fields)
        if (not code_idxs) and has_desc:
            for di, dln in enumerate(lines):
                if not (_is_annotation_descriptor_line(dln) or _is_enum_value_descriptor_line(dln)):
                    continue

                lbl_idx = _nearest_black_label_above(lines, di, max_dy=90, max_dx=140)
                if lbl_idx is None or _is_probable_page_header_line(lines[lbl_idx]):
                    # If the nearest "label" is actually a page/section header, try below the descriptor.
                    lbl_idx = _nearest_black_label_below(lines, di, max_dy=90, max_dx=160)

                if lbl_idx is None:
                    continue

                field_name = _join_wrapped_black_label(lines, lbl_idx, stop_y=getattr(dln, "y0", 0.0), block_idx=di)
                field_name = _clean_label(field_name)

                if not field_name or not _contains_letter(field_name):
                    continue
                if _looks_like_row_label(field_name):
                    continue
                if _looks_like_option_anchor(field_name):
                    continue
                if _looks_like_pure_value(field_name):
                    continue
                if _is_probable_page_header_text(field_name):
                    continue

                key = (form_name, field_name)
                if key in page_seen:
                    continue
                page_seen.add(key)
                out.append({"form_name": form_name, "field_name": field_name, "page": page_num})

        # 2) Question-style labels (common in C-SSRS pages): extract prompts, not options/anchors.
        for q in _extract_question_like_fields(lines):
            field_name = _clean_label(q)
            if not field_name or not _contains_letter(field_name):
                continue
            if _looks_like_option_anchor(field_name):
                continue
            if _looks_like_pure_value(field_name):
                continue
            if _is_probable_page_header_text(field_name):
                continue

            key = (form_name, field_name)
            if key in page_seen:
                continue
            page_seen.add(key)
            out.append({"form_name": form_name, "field_name": field_name, "page": page_num})

        # 3) "Instruction + many option tokens" pages: treat instruction as the field label (options are not fields)
        instr = _detect_instruction_field(lines)
        if instr:
            field_name = _clean_label(instr)
            if field_name and _contains_letter(field_name) and not _looks_like_pure_value(field_name):
                key = (form_name, field_name)
                if key not in page_seen:
                    page_seen.add(key)
                    out.append({"form_name": form_name, "field_name": field_name, "page": page_num})

    return out


# ------------------------- title detection -------------------------

def _detect_form_title(lines) -> str:
    # First: prefer a black bold "section" title (often the true form name on C-SSRS pages).
    sec = _detect_section_title(lines)
    if sec:
        return sec

    # Next: prominent colored (non-black) top-left header around y~150 seen across CRF forms.
    cands = []
    for ln in lines:
        t = ln.text or ""
        if not t or t.startswith("["):
            continue
        if getattr(ln, "y0", 0.0) > 230 or getattr(ln, "x0", 0.0) > 190:
            continue
        if not getattr(ln, "non_black", False):
            continue
        if getattr(ln, "size", 0.0) < 13.0:
            continue
        if _is_page_footer(t):
            continue
        if _looks_like_option_anchor(t):
            continue
        cands.append(ln)

    if cands:
        cands.sort(key=lambda l: (-getattr(l, "size", 0.0), getattr(l, "y0", 0.0), -int(bool(getattr(l, "bold", False))), getattr(l, "x0", 0.0)))
        return _clean_title(cands[0].text)

    # Fallback: largest top-band bold text.
    top = [ln for ln in lines if (ln.text and not (ln.text or "").startswith("[")) and getattr(ln, "y0", 0.0) < 210 and getattr(ln, "x0", 0.0) < 280]
    if not top:
        return ""
    max_size = max(getattr(ln, "size", 0.0) for ln in top)
    big = [ln for ln in top if getattr(ln, "size", 0.0) >= max_size - 0.5 and (getattr(ln, "bold", False) or max_size >= 16)]
    if big:
        big.sort(key=lambda l: (getattr(l, "y0", 0.0), getattr(l, "x0", 0.0)))
        t = _clean_title(big[0].text)
        if t and len(t) <= 80 and not _is_page_footer(t) and not _looks_like_option_anchor(t):
            return t
    return ""


def _detect_section_title(lines) -> str:
    # Black bold header in the upper band (not the topmost program header).
    cands = []
    for ln in lines:
        t = _norm_space(ln.text or "")
        if not t or t.startswith("["):
            continue
        if getattr(ln, "non_black", False):
            continue
        if not getattr(ln, "bold", False):
            continue
        y = getattr(ln, "y0", 0.0)
        x = getattr(ln, "x0", 0.0)
        sz = getattr(ln, "size", 0.0)

        if y < 115 or y > 300:
            continue
        if x > 260:
            continue
        if sz < 11.5:
            continue
        if _is_page_footer(t):
            continue
        if _looks_like_option_anchor(t):
            continue
        tt = _clean_title(t)
        if not tt or not _contains_letter(tt):
            continue
        if len(tt) > 85:
            continue
        cands.append(ln)

    if not cands:
        return ""
    cands.sort(key=lambda l: (-getattr(l, "size", 0.0), getattr(l, "y0", 0.0), getattr(l, "x0", 0.0)))
    return _clean_title(cands[0].text)


def _detect_left_header_title(lines) -> str:
    # Black left header near the top, often used as section title on descriptor-only pages.
    cands = []
    for ln in lines:
        t = ln.text or ""
        if not t or t.startswith("["):
            continue
        if getattr(ln, "non_black", False):
            continue
        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        sz = getattr(ln, "size", 0.0)

        if x > 260:
            continue
        if y < 95 or y > 175:
            continue
        if sz < 9.0 or sz > 13.5:
            continue
        if _is_page_footer(t):
            continue
        tt = _clean_title(t)
        if not tt or not _contains_letter(tt):
            continue
        if len(tt) > 80:
            continue
        cands.append(ln)

    if not cands:
        return ""
    cands.sort(key=lambda l: (getattr(l, "x0", 0.0), getattr(l, "y0", 0.0), -getattr(l, "size", 0.0)))
    return _clean_title(cands[0].text)


def _clean_title(s: str) -> str:
    s = _norm_space(s)
    s = s.strip(" -\t")
    return s


# ------------------------- field-code anchoring -------------------------

_FIELD_ID_RE = re.compile(r"^\[[A-Za-z0-9_]+\]$")


def _has_any_field_code(lines) -> bool:
    return any(_is_field_id_code_line(ln) for ln in lines)


def _is_field_id_code_line(ln) -> bool:
    t = ln.text or ""
    if not getattr(ln, "non_black", False):
        return False
    if not t.startswith("[") or not t.endswith("]"):
        return False
    if not _FIELD_ID_RE.match(t):
        return False
    up = t.upper()
    if up.startswith("[TYPE") or up.startswith("[VISIBILITY") or up.startswith("[READ-ONLY"):
        return False
    return True


def _is_annotation_descriptor_line(ln) -> bool:
    t = ln.text or ""
    if not getattr(ln, "non_black", False):
        return False
    if not t.startswith("["):
        return False
    up = t.upper()
    return (
        up.startswith("[TYPE")
        or up.startswith("[VISIBILITY")
        or up.startswith("[READ-ONLY")
        or up.startswith("[RANGE")
        or up.startswith("[CALC")
        or up.startswith("[DERIVE")
    )


def _is_enum_value_descriptor_line(ln) -> bool:
    # Some pages render value lists as colored "(0) Does not apply" style lines.
    if not getattr(ln, "non_black", False):
        return False
    t = _norm_space(ln.text or "")
    if not t:
        return False
    return bool(re.match(r"^\(\s*\d+\s*\)\s*\S+", t))


def _has_any_descriptor(lines) -> bool:
    return any(_is_annotation_descriptor_line(ln) or _is_enum_value_descriptor_line(ln) for ln in lines)


def _nearest_black_label_above(lines, idx: int, max_dy: float, max_dx: float) -> Optional[int]:
    tgt = lines[idx]
    tx = getattr(tgt, "x0", 0.0)
    ty = getattr(tgt, "y0", 0.0)

    best_j = None
    best_score = 10**18

    for j in range(idx - 1, -1, -1):
        ln = lines[j]
        t = ln.text or ""
        if _is_bad_label_line(ln):
            continue
        if getattr(ln, "non_black", False):
            continue
        if _is_page_footer(t):
            continue
        if not _contains_letter(t):
            continue

        dy = ty - getattr(ln, "y0", 0.0)
        if dy < 0:
            continue
        if dy > max_dy:
            break

        dx = abs(getattr(ln, "x0", 0.0) - tx)
        if dx > max_dx:
            continue

        score = dy * 10.0 + dx
        if score < best_score:
            best_score = score
            best_j = j

    return best_j


def _nearest_black_label_below(lines, idx: int, max_dy: float, max_dx: float) -> Optional[int]:
    tgt = lines[idx]
    tx = getattr(tgt, "x0", 0.0)
    ty = getattr(tgt, "y0", 0.0)

    best_j = None
    best_score = 10**18

    for j in range(idx + 1, len(lines)):
        ln = lines[j]
        t = ln.text or ""
        if _is_bad_label_line(ln):
            continue
        if getattr(ln, "non_black", False):
            continue
        if _is_page_footer(t):
            continue
        if not _contains_letter(t):
            continue

        dy = getattr(ln, "y0", 0.0) - ty
        if dy < 0:
            continue
        if dy > max_dy:
            break

        dx = abs(getattr(ln, "x0", 0.0) - tx)
        if dx > max_dx:
            continue

        score = dy * 10.0 + dx
        if score < best_score:
            best_score = score
            best_j = j

    return best_j


def _label_near_code(lines, code_idx: int) -> str:
    code = lines[code_idx]
    cy = getattr(code, "y0", 0.0)

    above = []
    below = []

    for j in range(code_idx - 1, -1, -1):
        ln = lines[j]
        if (cy - getattr(ln, "y0", 0.0)) > 120:
            break
        if _is_bad_label_line(ln):
            continue
        if getattr(ln, "non_black", False):
            continue
        if _contains_letter(ln.text or ""):
            above.append((cy - getattr(ln, "y0", 0.0), j))

    for j in range(code_idx + 1, len(lines)):
        ln = lines[j]
        if (getattr(ln, "y0", 0.0) - cy) > 230:
            break
        if _is_bad_label_line(ln):
            continue
        if getattr(ln, "non_black", False):
            continue
        if _contains_letter(ln.text or ""):
            below.append((getattr(ln, "y0", 0.0) - cy, j))

    pick_j = None
    if above:
        above.sort(key=lambda x: x[0])
        if above[0][0] <= 95:
            pick_j = above[0][1]
    if pick_j is None and below:
        below.sort(key=lambda x: x[0])
        pick_j = below[0][1]
    if pick_j is None:
        return ""

    return _join_wrapped_black_label(lines, pick_j, stop_y=cy, block_idx=code_idx)


def _join_wrapped_black_label(lines, anchor_idx: int, stop_y: float, block_idx: int) -> str:
    anchor = lines[anchor_idx]
    ax = getattr(anchor, "x0", 0.0)
    asz = getattr(anchor, "size", 0.0)

    def is_wrap_line(ln) -> bool:
        if _is_bad_label_line(ln):
            return False
        if getattr(ln, "non_black", False):
            return False
        if abs(getattr(ln, "x0", 0.0) - ax) > 34:
            return False
        if abs(getattr(ln, "size", 0.0) - asz) > 2.0:
            return False
        return True

    idxs = [anchor_idx]

    prev = anchor
    for j in range(anchor_idx - 1, -1, -1):
        ln = lines[j]
        if (getattr(prev, "y0", 0.0) - getattr(ln, "y0", 0.0)) > 20:
            break
        if j == block_idx:
            break
        if getattr(ln, "y0", 0.0) > stop_y + 1:
            continue
        if is_wrap_line(ln):
            idxs.append(j)
            prev = ln
        else:
            break

    prev = anchor
    for j in range(anchor_idx + 1, len(lines)):
        ln = lines[j]
        if (getattr(ln, "y0", 0.0) - getattr(prev, "y0", 0.0)) > 20:
            break
        if j == block_idx:
            break
        if (ln.text or "").startswith("[") and getattr(ln, "non_black", False):
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
    if _looks_like_row_label(t):
        return True
    if _looks_like_option_anchor(t):
        return True
    if t.strip() in {"•", "-", "–", "—"}:
        return True
    return False


# ------------------------- table headers (used for mapping codes to columns; never emitted as fields) -------------------------

def _detect_table_headers(lines):
    cands = []
    for ln in lines:
        t = ln.text or ""
        if not t or t.startswith("["):
            continue
        if getattr(ln, "non_black", False):
            continue
        y = getattr(ln, "y0", 0.0)
        sz = getattr(ln, "size", 0.0)
        if y < 95 or y > 175:
            continue
        if sz < 9.0 or sz > 13.2:
            continue
        # Require bold-ish header style to avoid picking first-row values.
        if not getattr(ln, "bold", False):
            continue
        if _is_page_footer(t):
            continue
        if _looks_like_row_label(t) or _looks_like_option_anchor(t):
            continue
        if _looks_like_pure_value(t):
            continue
        cands.append(ln)

    if len(cands) < 3:
        return []

    cands.sort(key=lambda l: (getattr(l, "x0", 0.0), getattr(l, "y0", 0.0)))
    cols = []
    for ln in cands:
        placed = False
        for col in cols:
            if abs(getattr(ln, "x0", 0.0) - col["x"]) <= 45:
                col["items"].append(ln)
                col["x"] = (col["x"] * 3 + getattr(ln, "x0", 0.0)) / 4.0
                placed = True
                break
        if not placed:
            cols.append({"x": getattr(ln, "x0", 0.0), "items": [ln]})

    cleaned = []
    for col in cols:
        items = sorted(col["items"], key=lambda l: getattr(l, "y0", 0.0))
        txt = _norm_space(" ".join(i.text for i in items if i.text))
        txt = _clean_label(txt)
        if txt and _contains_letter(txt) and not _looks_like_pure_value(txt):
            cleaned.append({"x": col["x"], "text": txt})

    cleaned.sort(key=lambda c: c["x"])
    if len(cleaned) < 3:
        return []
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
    blueish = [ln for ln in lines if getattr(ln, "non_black", False) and getattr(ln, "size", 0.0) >= 13 and (ln.text and not (ln.text or "").startswith("["))]
    if len(blueish) < 8:
        return False

    def looks_numbered(t: str) -> bool:
        t = t.strip()
        return bool(re.match(r"^\d+(\.\d+)*\.", t)) or bool(re.match(r"^\d+\s*$", t))

    numbered = sum(1 for ln in blueish if looks_numbered(ln.text or ""))
    ys = [getattr(ln, "y0", 0.0) for ln in blueish]
    if numbered >= max(3, len(blueish) // 3):
        return True
    if min(ys) > 220 and (max(ys) - min(ys)) > 250 and len(blueish) >= 12:
        return True
    return False


def _detect_instruction_field(lines) -> str:
    instr = None
    for ln in lines:
        if getattr(ln, "y0", 0.0) > 180:
            break
        if getattr(ln, "x0", 0.0) < 130 and (8.0 <= getattr(ln, "size", 0.0) <= 10.8) and (not getattr(ln, "non_black", False)):
            t = _norm_space(ln.text or "")
            if len(t) >= 45 and _contains_letter(t) and t.endswith(".") and (not _looks_like_pure_value(t)):
                instr = t
                break
    if not instr:
        return ""

    right_tokens = 0
    for ln in lines:
        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        sz = getattr(ln, "size", 0.0)
        if x > 330 and 160 <= y <= 740 and (9.0 <= sz <= 12.8) and (not getattr(ln, "non_black", False)):
            t = (ln.text or "").strip()
            if 2 <= len(t) <= 10 and re.match(r"^[A-Z0-9]+$", t):
                right_tokens += 1
    if right_tokens >= 10:
        return instr
    return ""


def _extract_question_like_fields(lines) -> List[str]:
    # Find black question prompts and join wrapped lines in the same left column.
    cands = []
    for i, ln in enumerate(lines):
        t = _norm_space(ln.text or "")
        if not t or t.startswith("["):
            continue
        if getattr(ln, "non_black", False):
            continue
        if _is_page_footer(t):
            continue
        if _looks_like_option_anchor(t):
            continue
        if "?" not in t:
            continue

        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        sz = getattr(ln, "size", 0.0)

        # Prefer main content band; keep slack.
        if y < 170 or y > 760:
            continue
        if x > 260:
            continue
        if sz < 8.0 or sz > 13.5:
            continue

        if _is_probable_page_header_line(ln):
            continue

        full = _join_wrapped_prompt(lines, i)
        full = _norm_space(full)
        if 18 <= len(full) <= 260 and _contains_letter(full):
            cands.append(full)

    # De-dupe while preserving order
    seen = set()
    out = []
    for s in cands:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _join_wrapped_prompt(lines, start_idx: int) -> str:
    start = lines[start_idx]
    ax = getattr(start, "x0", 0.0)
    asz = getattr(start, "size", 0.0)

    parts = []
    prev_y = getattr(start, "y0", 0.0)

    for j in range(start_idx, min(len(lines), start_idx + 10)):
        ln = lines[j]
        t = _norm_space(ln.text or "")
        if not t or t.startswith("["):
            continue
        if getattr(ln, "non_black", False):
            continue
        if _is_page_footer(t):
            continue
        if _looks_like_option_anchor(t):
            break
        if _is_probable_page_header_line(ln):
            break

        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        sz = getattr(ln, "size", 0.0)

        if abs(x - ax) > 36:
            break
        if abs(sz - asz) > 2.2:
            break
        if j != start_idx and (y - prev_y) > 24:
            break

        parts.append(t)
        prev_y = y
        if "?" in t:
            # Stop once we have a question-ending line (still allows earlier wrapped lines).
            if t.rstrip().endswith("?"):
                break

    return _norm_space(" ".join(parts))


# ------------------------- structural filters -------------------------

def _looks_like_option_anchor(s: str) -> bool:
    s = _norm_space(s)
    if not s:
        return False
    # Numeric anchors like "(1) text", "1) text", "(0) text"
    if re.match(r"^\(?\s*\d{1,2}\s*\)?\s*[\)\.:-]\s*\S+", s):
        return True
    if re.match(r"^\(\s*\d{1,2}\s*\)\s*\S+", s):
        return True
    # Letter anchors like "A) text", "(B) text"
    if re.match(r"^\(?\s*[A-H]\s*\)?\s*[\)\.:-]\s*\S+", s, flags=re.IGNORECASE):
        return True
    return False


def _looks_like_pure_value(s: str) -> bool:
    # Heuristic: values like dates/versions/names often contain many digits and few letters.
    s = _norm_space(s)
    if not s:
        return False
    letters = sum(1 for ch in s if unicodedata.category(ch).startswith("L"))
    digits = sum(1 for ch in s if ch.isdigit())
    if digits >= 3 and letters <= 6 and len(s) <= 40:
        return True
    if re.match(r"^\d+(\.\d+){1,4}\s*$", s):
        return True
    if re.match(r"^\d{1,2}[-/][A-Za-z]{3,}[-/]\d{2,4}$", s):
        return True
    if re.match(r"^[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}$", s):
        return True
    return False


def _is_probable_page_header_line(ln) -> bool:
    t = _norm_space(ln.text or "")
    if not t or t.startswith("["):
        return False
    if _is_page_footer(t):
        return False
    if getattr(ln, "non_black", False):
        return False
    y = getattr(ln, "y0", 0.0)
    x = getattr(ln, "x0", 0.0)
    sz = getattr(ln, "size", 0.0)
    if y <= 210 and x <= 280 and sz >= 11.5 and getattr(ln, "bold", False):
        return True
    return False


def _is_probable_page_header_text(t: str) -> bool:
    t = _norm_space(t)
    if not t:
        return False
    if len(t) <= 4:
        return True
    if re.match(r"^Page\s+\d+\s+of\s+\d+\s*$", t, flags=re.IGNORECASE):
        return True
    return False


def _looks_like_page_header_field(field_text: str, code_ln, lines) -> bool:
    # If the inferred "field label" is actually a header (very top, bold-ish), drop it.
    # This is conservative: only triggers when the label text is short and header-like.
    s = _norm_space(field_text)
    if len(s) > 35:
        return False
    if "?" in s:
        return False
    y = getattr(code_ln, "y0", 0.0)
    if y > 260:
        return False
    # If there's any bold header line near top with same text, likely furniture.
    for ln in lines:
        if getattr(ln, "non_black", False):
            continue
        if not getattr(ln, "bold", False):
            continue
        if getattr(ln, "y0", 0.0) > 220:
            continue
        if _norm_space(ln.text or "") == s:
            return True
    return False


# ------------------------- text utilities -------------------------

def _norm_space(s: str) -> str:
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_label(s: str) -> str:
    s = _norm_space(s)
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
