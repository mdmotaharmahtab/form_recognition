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
        geom = _page_geom(lines)

        has_code = _has_any_field_code(lines)
        has_desc = _has_any_descriptor(lines)

        # Table header mapping (for pages where bracketed codes appear inside table cells).
        header_cols = _detect_table_headers(lines, geom, y_band=(0.10, 0.22), min_cols=3, require_bold=True)

        # Never let TOC-like pages change the current form (but don't skip extraction on them).
        if (not has_code) and (not has_desc) and (not header_cols) and _looks_like_toc_page(lines, geom):
            # Keep current_form unchanged and proceed (generally no extractable fields anyway).
            pass
        else:
            form_title = _detect_form_title(lines, geom)
            if form_title:
                current_form = form_title
            # Descriptor-only pages: sometimes use a left header as the section/form title.
            if (not has_code) and has_desc:
                left = _detect_left_header_title(lines, geom)
                if left:
                    current_form = left

        page_seen = set()  # (form_name, field_name) de-dupe within page
        form_name = current_form or ""

        def emit(field_text: str) -> None:
            field_name = _clean_label(field_text)
            if not field_name or not _contains_letter(field_name):
                return
            if _looks_like_row_label(field_name):
                return
            if _looks_like_option_anchor(field_name):
                return
            if _looks_like_pure_value(field_name):
                return
            if _is_probable_page_header_text(field_name):
                return
            key = (form_name, field_name)
            if key in page_seen:
                return
            page_seen.add(key)
            out.append({"form_name": form_name, "field_name": field_name, "page": page_num})

        # 1) Extract from field-id codes (colored bracketed ids like [VISDAT], [RPF3], etc.)
        code_idxs = [i for i, ln in enumerate(lines) if _is_field_id_code_line(ln)]
        for ci in code_idxs:
            code_line = lines[ci]
            field_name = ""

            # Prefer column header mapping for table-like pages/cells
            if header_cols:
                y = getattr(code_line, "y0", 0.0)
                x = getattr(code_line, "x0", 0.0)
                if y > geom["y_min"] + 0.22 * geom["h"] and x > geom["x_min"] + 0.25 * geom["w"]:
                    hdr = _header_for_x(header_cols, x)
                    if hdr:
                        field_name = hdr

            if not field_name:
                field_name = _label_near_code(lines, ci, geom)

            field_name = _clean_label(field_name)
            if not field_name or not _contains_letter(field_name):
                continue
            if _looks_like_row_label(field_name):
                continue
            if _looks_like_option_anchor(field_name):
                continue
            if _looks_like_pure_value(field_name):
                continue
            if _looks_like_page_header_field(field_name, code_line, lines, geom):
                continue

            emit(field_name)

        # 1b) Descriptor-only pages: infer label near descriptor lines
        # (and be careful to join wrapped prompts so we don't emit a trailing single word like "suicide")
        if (not code_idxs) and has_desc:
            for di, dln in enumerate(lines):
                if not (_is_annotation_descriptor_line(dln) or _is_enum_value_descriptor_line(dln)):
                    continue

                lbl_idx = _nearest_black_label_above(lines, di, geom, max_dy=0.13 * geom["h"], max_dx=0.22 * geom["w"])
                if lbl_idx is None or _is_probable_page_header_line(lines[lbl_idx], geom):
                    lbl_idx = _nearest_black_label_below(lines, di, geom, max_dy=0.13 * geom["h"], max_dx=0.25 * geom["w"])
                if lbl_idx is None:
                    continue

                field_text = _expand_label_block(lines, lbl_idx, block_idx=di, geom=geom, stop_y=getattr(dln, "y0", 0.0))
                field_text = _clean_label(field_text)

                # Avoid emitting tiny trailing wrap fragments on long prompts.
                if _word_count(field_text) == 1 and len(field_text) <= 10 and ("?" not in field_text):
                    continue

                emit(field_text)

        # 2) Question-style prompts: join wrapped lines even if the first line lacks "?"
        for q in _extract_question_prompts(lines, geom):
            emit(q)

        # 3) "Instruction + many option tokens" pages: treat instruction as the field label (options are not fields)
        instr = _detect_instruction_field(lines, geom)
        if instr:
            emit(instr)

        # 4) Header-row-as-fields tables (e.g., contact log columns)
        # Only when it doesn't look like a page inventory / schedule index.
        header_fields = _detect_table_headers(lines, geom, y_band=(0.12, 0.42), min_cols=3, require_bold=True)
        if header_fields and (not _looks_like_page_inventory(lines, geom)):
            for col in header_fields:
                txt = col.get("text", "") if isinstance(col, dict) else ""
                if txt and _contains_letter(txt) and not _looks_like_pure_value(txt) and not _looks_like_option_anchor(txt):
                    emit(txt)

        # 5) Generic "Label:" fields (boost coverage on forms without codes)
        # Guarded so we don't harvest narrative definition/cover pages.
        is_data_entryish = bool(has_code or has_desc or header_fields or _count_short_label_candidates(lines, geom) >= 4 or _count_questionlike(lines, geom) >= 1)
        if is_data_entryish:
            for s in _extract_colon_labels(lines, geom):
                emit(s)

    return out


# ------------------------- geometry -------------------------

def _page_geom(lines) -> Dict[str, float]:
    xs = [getattr(ln, "x0", 0.0) for ln in lines]
    ys = [getattr(ln, "y0", 0.0) for ln in lines]
    x_min = min(xs) if xs else 0.0
    x_max = max(xs) if xs else 600.0
    y_min = min(ys) if ys else 0.0
    y_max = max(ys) if ys else 800.0
    w = max(1.0, x_max - x_min)
    h = max(1.0, y_max - y_min)
    return {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max, "w": w, "h": h}


# ------------------------- title detection -------------------------

def _detect_form_title(lines, geom) -> str:
    # Prefer a black bold "section" title (often the true form name on C-SSRS pages).
    sec = _detect_section_title(lines, geom)
    if sec:
        return sec

    # Prominent colored (non-black) top-left header seen across CRF forms.
    cands = []
    for ln in lines:
        t = ln.text or ""
        if not t or t.startswith("["):
            continue
        if "?" in t:
            continue
        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        if y > geom["y_min"] + 0.33 * geom["h"] or x > geom["x_min"] + 0.32 * geom["w"]:
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
        cands.sort(
            key=lambda l: (
                -getattr(l, "size", 0.0),
                getattr(l, "y0", 0.0),
                -int(bool(getattr(l, "bold", False))),
                getattr(l, "x0", 0.0),
            )
        )
        return _clean_title(cands[0].text)

    # Fallback: largest top-band bold text.
    top = [
        ln
        for ln in lines
        if (ln.text and not (ln.text or "").startswith("["))
        and ("?" not in (ln.text or ""))
        and getattr(ln, "y0", 0.0) < geom["y_min"] + 0.30 * geom["h"]
        and getattr(ln, "x0", 0.0) < geom["x_min"] + 0.48 * geom["w"]
    ]
    if not top:
        return ""
    max_size = max(getattr(ln, "size", 0.0) for ln in top)
    big = [ln for ln in top if getattr(ln, "size", 0.0) >= max_size - 0.5 and (getattr(ln, "bold", False) or max_size >= 16)]
    if big:
        big.sort(key=lambda l: (getattr(l, "y0", 0.0), getattr(l, "x0", 0.0)))
        t = _clean_title(big[0].text)
        if t and len(t) <= 90 and not _is_page_footer(t) and not _looks_like_option_anchor(t):
            return t
    return ""


def _detect_section_title(lines, geom) -> str:
    # Black bold header in the upper band (not the topmost program header).
    cands = []
    for ln in lines:
        t = _norm_space(ln.text or "")
        if not t or t.startswith("["):
            continue
        if "?" in t:
            continue
        if getattr(ln, "non_black", False):
            continue
        if not getattr(ln, "bold", False):
            continue
        y = getattr(ln, "y0", 0.0)
        x = getattr(ln, "x0", 0.0)
        sz = getattr(ln, "size", 0.0)

        y_lo = geom["y_min"] + 0.14 * geom["h"]
        y_hi = geom["y_min"] + 0.40 * geom["h"]
        if y < y_lo or y > y_hi:
            continue
        if x > geom["x_min"] + 0.44 * geom["w"]:
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
        if len(tt) > 95:
            continue
        cands.append(ln)

    if not cands:
        return ""
    cands.sort(key=lambda l: (-getattr(l, "size", 0.0), getattr(l, "y0", 0.0), getattr(l, "x0", 0.0)))
    return _clean_title(cands[0].text)


def _detect_left_header_title(lines, geom) -> str:
    # Black left header near the top, sometimes used as section title on descriptor-only pages.
    cands = []
    for ln in lines:
        t = ln.text or ""
        if not t or t.startswith("["):
            continue
        if "?" in t:
            continue
        if getattr(ln, "non_black", False):
            continue
        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        sz = getattr(ln, "size", 0.0)

        if x > geom["x_min"] + 0.44 * geom["w"]:
            continue
        y_lo = geom["y_min"] + 0.11 * geom["h"]
        y_hi = geom["y_min"] + 0.24 * geom["h"]
        if y < y_lo or y > y_hi:
            continue
        if sz < 9.0 or sz > 13.8:
            continue
        if _is_page_footer(t):
            continue
        tt = _clean_title(t)
        if not tt or not _contains_letter(tt):
            continue
        if len(tt) > 90:
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


def _nearest_black_label_above(lines, idx: int, geom, max_dy: float, max_dx: float) -> Optional[int]:
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


def _nearest_black_label_below(lines, idx: int, geom, max_dy: float, max_dx: float) -> Optional[int]:
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


def _label_near_code(lines, code_idx: int, geom) -> str:
    code = lines[code_idx]
    cy = getattr(code, "y0", 0.0)

    above = []
    below = []

    for j in range(code_idx - 1, -1, -1):
        ln = lines[j]
        if (cy - getattr(ln, "y0", 0.0)) > 0.18 * geom["h"]:
            break
        if _is_bad_label_line(ln):
            continue
        if getattr(ln, "non_black", False):
            continue
        if _contains_letter(ln.text or ""):
            above.append((cy - getattr(ln, "y0", 0.0), j))

    for j in range(code_idx + 1, len(lines)):
        ln = lines[j]
        if (getattr(ln, "y0", 0.0) - cy) > 0.34 * geom["h"]:
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
        if above[0][0] <= 0.14 * geom["h"]:
            pick_j = above[0][1]
    if pick_j is None and below:
        below.sort(key=lambda x: x[0])
        pick_j = below[0][1]
    if pick_j is None:
        return ""

    return _expand_label_block(lines, pick_j, block_idx=code_idx, geom=geom, stop_y=cy)


def _expand_label_block(lines, anchor_idx: int, block_idx: int, geom, stop_y: float) -> str:
    """
    Join wrapped black label/prompt lines around anchor_idx. More tolerant than the old join:
    - allows modest indentation shifts
    - can climb upward to capture the first line of a wrapped question
    """
    anchor = lines[anchor_idx]
    ax = getattr(anchor, "x0", 0.0)
    asz = getattr(anchor, "size", 0.0)

    def is_labelish(ln) -> bool:
        if _is_bad_label_line(ln):
            return False
        if getattr(ln, "non_black", False):
            return False
        if abs(getattr(ln, "size", 0.0) - asz) > 2.4:
            return False
        return True

    idxs = [anchor_idx]

    # Upward: allow same column or slightly more-left (common in wrapped sentences).
    prev = anchor
    for j in range(anchor_idx - 1, -1, -1):
        if j == block_idx:
            break
        ln = lines[j]
        if getattr(ln, "y0", 0.0) > stop_y + 1:
            continue
        dy = getattr(prev, "y0", 0.0) - getattr(ln, "y0", 0.0)
        if dy > 22:
            break
        if not is_labelish(ln):
            break
        x = getattr(ln, "x0", 0.0)
        if abs(x - ax) <= 60 or (x <= getattr(prev, "x0", 0.0) + 6):
            idxs.append(j)
            prev = ln
        else:
            break

    # Downward: allow same/similar column; stop before colored technical tokens.
    prev = anchor
    for j in range(anchor_idx + 1, len(lines)):
        if j == block_idx:
            break
        ln = lines[j]
        dy = getattr(ln, "y0", 0.0) - getattr(prev, "y0", 0.0)
        if dy > 22:
            break
        if (ln.text or "").startswith("[") and getattr(ln, "non_black", False):
            break
        if not is_labelish(ln):
            break
        x = getattr(ln, "x0", 0.0)
        if abs(x - ax) <= 60:
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


# ------------------------- table headers -------------------------

def _detect_table_headers(lines, geom, y_band=(0.10, 0.22), min_cols=3, require_bold=True):
    y_lo = geom["y_min"] + y_band[0] * geom["h"]
    y_hi = geom["y_min"] + y_band[1] * geom["h"]

    cands = []
    for ln in lines:
        t = ln.text or ""
        if not t or t.startswith("["):
            continue
        if getattr(ln, "non_black", False):
            continue
        y = getattr(ln, "y0", 0.0)
        x = getattr(ln, "x0", 0.0)
        sz = getattr(ln, "size", 0.0)
        if y < y_lo or y > y_hi:
            continue
        if sz < 8.5 or sz > 13.6:
            continue
        if require_bold and (not getattr(ln, "bold", False)):
            continue
        if _is_page_footer(t):
            continue
        if _looks_like_row_label(t) or _looks_like_option_anchor(t):
            continue
        if _looks_like_pure_value(t):
            continue
        if x < geom["x_min"] + 0.04 * geom["w"]:
            continue
        cands.append(ln)

    if len(cands) < min_cols:
        return []

    # Cluster by x into columns.
    cands.sort(key=lambda l: (getattr(l, "x0", 0.0), getattr(l, "y0", 0.0)))
    cols = []
    snap = max(34.0, 0.06 * geom["w"])
    for ln in cands:
        placed = False
        for col in cols:
            if abs(getattr(ln, "x0", 0.0) - col["x"]) <= snap:
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
        if txt and _contains_letter(txt) and not _looks_like_pure_value(txt) and not _looks_like_option_anchor(txt):
            cleaned.append({"x": col["x"], "text": txt})

    cleaned.sort(key=lambda c: c["x"])
    if len(cleaned) < min_cols:
        return []

    # Require a decent span so we don't mistake stacked labels for headers.
    if cleaned[-1]["x"] - cleaned[0]["x"] < max(220.0, 0.35 * geom["w"]):
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


# ------------------------- question prompts -------------------------

def _extract_question_prompts(lines, geom) -> List[str]:
    # Identify black prompt blocks in main content columns; join wrapped lines even if start line lacks '?'.
    cands = []
    left_max = geom["x_min"] + 0.56 * geom["w"]
    y_lo = geom["y_min"] + 0.18 * geom["h"]
    y_hi = geom["y_min"] + 0.92 * geom["h"]

    for i, ln in enumerate(lines):
        t0 = _norm_space(ln.text or "")
        if not t0 or t0.startswith("["):
            continue
        if getattr(ln, "non_black", False):
            continue
        if _is_page_footer(t0):
            continue
        if _looks_like_option_anchor(t0):
            continue
        if _is_probable_page_header_line(ln, geom):
            continue

        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        sz = getattr(ln, "size", 0.0)
        if y < y_lo or y > y_hi:
            continue
        if x > left_max:
            continue
        if sz < 8.0 or sz > 13.8:
            continue

        # Avoid starting on very short trailing fragments (common last-line wrap).
        if len(t0) <= 10 and ("?" not in t0):
            continue

        full = _join_wrapped_prompt_from_start(lines, i, geom)
        full = _norm_space(full)
        if "?" not in full:
            continue
        if 18 <= len(full) <= 320 and _contains_letter(full):
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


def _join_wrapped_prompt_from_start(lines, start_idx: int, geom) -> str:
    start = lines[start_idx]
    ax = getattr(start, "x0", 0.0)
    asz = getattr(start, "size", 0.0)

    parts = []
    prev_y = getattr(start, "y0", 0.0)

    for j in range(start_idx, min(len(lines), start_idx + 14)):
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
        if _is_probable_page_header_line(ln, geom):
            break

        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        sz = getattr(ln, "size", 0.0)

        # Column consistency with slack (allows light indentation).
        if abs(x - ax) > max(44.0, 0.08 * geom["w"]):
            break
        if abs(sz - asz) > 2.6:
            break
        if j != start_idx and (y - prev_y) > 26:
            break

        parts.append(t)
        prev_y = y
        if "?" in t and t.rstrip().endswith("?"):
            break

    return _norm_space(" ".join(parts))


# ------------------------- generic "Label:" fields -------------------------

def _extract_colon_labels(lines, geom) -> List[str]:
    y_lo = geom["y_min"] + 0.16 * geom["h"]
    y_hi = geom["y_min"] + 0.94 * geom["h"]
    left_max = geom["x_min"] + 0.62 * geom["w"]

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
        if _looks_like_pure_value(t):
            continue
        if _is_probable_page_header_line(ln, geom):
            continue

        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        sz = getattr(ln, "size", 0.0)
        if y < y_lo or y > y_hi:
            continue
        if x > left_max:
            continue
        if sz < 8.0 or sz > 13.8:
            continue

        if not (t.endswith(":") or t.endswith(":-")) and (":" not in t):
            continue
        if len(t) > 95:
            continue
        if not _contains_letter(t):
            continue

        full = _expand_label_block(lines, i, block_idx=-1, geom=geom, stop_y=y)
        full = _norm_space(full)
        if len(full) <= 4:
            continue
        cands.append(full.rstrip(":").strip())

    # De-dupe preserving order
    seen = set()
    out = []
    for s in cands:
        s = _clean_label(s)
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _count_short_label_candidates(lines, geom) -> int:
    y_lo = geom["y_min"] + 0.18 * geom["h"]
    y_hi = geom["y_min"] + 0.94 * geom["h"]
    left_max = geom["x_min"] + 0.62 * geom["w"]
    n = 0
    for ln in lines:
        t = _norm_space(ln.text or "")
        if not t or t.startswith("["):
            continue
        if getattr(ln, "non_black", False):
            continue
        if _is_page_footer(t) or _looks_like_option_anchor(t) or _looks_like_pure_value(t):
            continue
        if _is_probable_page_header_line(ln, geom):
            continue
        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        if y < y_lo or y > y_hi or x > left_max:
            continue
        if 4 <= len(t) <= 40 and _contains_letter(t):
            n += 1
    return n


def _count_questionlike(lines, geom) -> int:
    return len(_extract_question_prompts(lines, geom))


# ------------------------- special page patterns -------------------------

def _looks_like_toc_page(lines, geom) -> bool:
    blueish = [
        ln
        for ln in lines
        if getattr(ln, "non_black", False)
        and getattr(ln, "size", 0.0) >= 12.5
        and (ln.text and not (ln.text or "").startswith("["))
    ]
    if len(blueish) < 8:
        return False

    def looks_numbered(t: str) -> bool:
        t = t.strip()
        return bool(re.match(r"^\d+(\.\d+)*\.", t)) or bool(re.match(r"^\d+\s*$", t))

    numbered = sum(1 for ln in blueish if looks_numbered(ln.text or ""))
    ys = [getattr(ln, "y0", 0.0) for ln in blueish]
    if numbered >= max(3, len(blueish) // 3):
        return True
    if min(ys) > geom["y_min"] + 0.28 * geom["h"] and (max(ys) - min(ys)) > 0.32 * geom["h"] and len(blueish) >= 12:
        return True
    return False


def _looks_like_page_inventory(lines, geom) -> bool:
    """
    Structural detector for "visit/page listing" tables (like sample page 20/25):
    - many blue small items in a consistent mid column
    - many small black numeric-only items in a nearby column
    """
    blue = []
    nums = []
    for ln in lines:
        t = _norm_space(ln.text or "")
        if not t or t.startswith("["):
            continue
        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        sz = getattr(ln, "size", 0.0)
        if y < geom["y_min"] + 0.15 * geom["h"] or y > geom["y_min"] + 0.92 * geom["h"]:
            continue
        if 8.0 <= sz <= 10.5:
            if getattr(ln, "non_black", False) and (geom["x_min"] + 0.40 * geom["w"] <= x <= geom["x_min"] + 0.62 * geom["w"]):
                if len(t) >= 8:
                    blue.append(ln)
            if (not getattr(ln, "non_black", False)) and re.match(r"^\d{1,4}$", t) and (geom["x_min"] + 0.28 * geom["w"] <= x <= geom["x_min"] + 0.46 * geom["w"]):
                nums.append(ln)
    if len(blue) >= 10 and len(nums) >= 8:
        # Also expect a bold header row near the top with multiple columns.
        hdr = _detect_table_headers(lines, geom, y_band=(0.10, 0.20), min_cols=4, require_bold=True)
        if hdr:
            return True
    return False


def _detect_instruction_field(lines, geom) -> str:
    instr = None
    # Look for a long instruction sentence in the upper-left band.
    for ln in lines:
        if getattr(ln, "y0", 0.0) > geom["y_min"] + 0.24 * geom["h"]:
            break
        if getattr(ln, "x0", 0.0) < geom["x_min"] + 0.22 * geom["w"] and (8.0 <= getattr(ln, "size", 0.0) <= 11.0) and (not getattr(ln, "non_black", False)):
            t = _norm_space(ln.text or "")
            if len(t) >= 45 and _contains_letter(t) and t.endswith(".") and (not _looks_like_pure_value(t)):
                instr = t
                break
    if not instr:
        return ""

    # Confirm with many short tokens in the right column (typical option grids).
    right_tokens = 0
    for ln in lines:
        x = getattr(ln, "x0", 0.0)
        y = getattr(ln, "y0", 0.0)
        sz = getattr(ln, "size", 0.0)
        if x > geom["x_min"] + 0.55 * geom["w"] and (geom["y_min"] + 0.18 * geom["h"] <= y <= geom["y_min"] + 0.92 * geom["h"]) and (9.0 <= sz <= 13.2) and (not getattr(ln, "non_black", False)):
            tt = (ln.text or "").strip()
            if 2 <= len(tt) <= 10 and re.match(r"^[A-Z0-9]+$", tt):
                right_tokens += 1
    if right_tokens >= 10:
        return instr
    return ""


# ------------------------- structural filters -------------------------

def _looks_like_option_anchor(s: str) -> bool:
    s = _norm_space(s)
    if not s:
        return False
    if re.match(r"^\(?\s*\d{1,2}\s*\)?\s*[\)\.:-]\s*\S+", s):
        return True
    if re.match(r"^\(\s*\d{1,2}\s*\)\s*\S+", s):
        return True
    if re.match(r"^\(?\s*[A-H]\s*\)?\s*[\)\.:-]\s*\S+", s, flags=re.IGNORECASE):
        return True
    return False


def _looks_like_pure_value(s: str) -> bool:
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


def _is_probable_page_header_line(ln, geom) -> bool:
    t = _norm_space(ln.text or "")
    if not t or t.startswith("["):
        return False
    if "?" in t:
        return False
    if _is_page_footer(t):
        return False
    if getattr(ln, "non_black", False):
        return False
    y = getattr(ln, "y0", 0.0)
    x = getattr(ln, "x0", 0.0)
    sz = getattr(ln, "size", 0.0)
    if y <= geom["y_min"] + 0.32 * geom["h"] and x <= geom["x_min"] + 0.48 * geom["w"] and sz >= 11.5 and getattr(ln, "bold", False):
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


def _looks_like_page_header_field(field_text: str, code_ln, lines, geom) -> bool:
    s = _norm_space(field_text)
    if len(s) > 35:
        return False
    if "?" in s:
        return False
    y = getattr(code_ln, "y0", 0.0)
    if y > geom["y_min"] + 0.40 * geom["h"]:
        return False
    for ln in lines:
        if getattr(ln, "non_black", False):
            continue
        if not getattr(ln, "bold", False):
            continue
        if getattr(ln, "y0", 0.0) > geom["y_min"] + 0.34 * geom["h"]:
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


def _word_count(s: str) -> int:
    s = _norm_space(s)
    if not s:
        return 0
    return len([p for p in re.split(r"\s+", s) if p])
```
