import re
import statistics
import unicodedata
from typing import List, Tuple, Dict, Any, Optional


# Field ID token inside brackets (allow lowercase + hyphen for robustness).
_ID_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_ID_LINE_RE = re.compile(r"^\[[A-Za-z0-9][A-Za-z0-9_-]*\]\s*[:;]?\s*$")
_BRACKET_RE = re.compile(r"^\[.*\]$")

_PAGE_FOOTER_RE = re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)


def _norm_space(s: str) -> str:
    return " ".join(s.split())


def _strip_leading_ordinals(s: str) -> str:
    # Removes leading "\25.\ " or "25. " style numbering (common in option/criterion rows).
    s = s.strip()
    s = re.sub(r"^\s*\\\s*\d+\s*[.)]\s*", "", s)
    s = re.sub(r"^\s*\d+\s*[.)]\s*", "", s)
    return s.strip()


def _clean_label(s: str) -> str:
    s = s.replace("\u00a0", " ")
    s = _norm_space(s).strip()
    s = s.strip("*").strip()
    s = re.sub(r"^[\u2022•·]\s*", "", s)
    s = _strip_leading_ordinals(s)
    return s


def _text_quality(s: str) -> float:
    s = s.strip()
    if not s:
        return 0.0
    letters = 0
    nonspace = 0
    for ch in s:
        if ch.isspace():
            continue
        nonspace += 1
        if unicodedata.category(ch).startswith("L"):
            letters += 1
    return 0.0 if nonspace == 0 else (letters / nonspace)


def _is_bracket_meta(line) -> bool:
    t = (getattr(line, "text", "") or "").strip()
    return bool(_BRACKET_RE.match(t))


def _is_field_id_text(t: str) -> bool:
    tt = (t or "").strip()
    if not tt:
        return False
    if not _ID_LINE_RE.match(tt):
        return False
    inner = tt.strip()
    if inner.endswith(":") or inner.endswith(";"):
        inner = inner[:-1].rstrip()
    if not (inner.startswith("[") and inner.endswith("]")):
        return False
    token = inner[1:-1].strip()
    if not _ID_TOKEN_RE.match(token):
        return False
    # Guard against bracket meta that might still slip through (shouldn't with token rule).
    low = token.lower()
    if low in ("type", "read-only", "readonly"):
        return False
    return True


def _is_field_id_line(line) -> bool:
    t = (getattr(line, "text", "") or "").strip()
    return _is_field_id_text(t)


def _median(vals: List[float], default: float) -> float:
    vals = [v for v in vals if v is not None]
    if not vals:
        return default
    try:
        return float(statistics.median(vals))
    except Exception:
        vals2 = sorted(vals)
        return float(vals2[len(vals2) // 2])


def _detect_body_size(lines) -> float:
    sizes = []
    for l in lines:
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if getattr(l, "non_black", False):
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if 6.0 <= sz <= 12.5:
            sizes.append(sz)
    return _median(sizes, 9.0)


def _detect_left_margin(lines, body_size: float) -> float:
    xs = []
    for l in lines:
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if getattr(l, "non_black", False):
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if sz > body_size + 1.2:
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if 40.0 <= x0 <= 140.0 and 90.0 <= y0 <= 740.0:
            xs.append(x0)
    return _median(xs, 64.0)


def _looks_like_title_text(t: str) -> bool:
    tt = (t or "").strip()
    if not tt:
        return False
    if _is_field_id_text(tt):
        return False
    if _is_bracket_meta(type("L", (), {"text": tt})()):  # cheap shim
        # still allow if it isn't meta, but here it is bracketed -> not title
        return False
    if _PAGE_FOOTER_RE.match(tt):
        return False
    # Avoid pure punctuation / tiny tokens.
    if len(tt) <= 2:
        return False
    # Titles usually have decent letter ratio.
    if len(tt) <= 8 and _text_quality(tt) < 0.2:
        return False
    return True


def _detect_form_title(lines, body_size: float) -> Optional[str]:
    # Prefer large text in top band; allow colored OR black titles.
    # Also supports multi-line titles by stitching nearby lines.
    cands = []
    for l in lines:
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 > 220.0:
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if sz < body_size + 3.0:
            continue
        if not _looks_like_title_text(t):
            continue
        cands.append(l)

    if not cands:
        return None

    # Prefer non-black (colored) if sizes comparable; otherwise, absolute largest wins.
    def _cand_key(z):
        sz = float(getattr(z, "size", 0.0) or 0.0)
        y0 = float(getattr(z, "y0", 0.0) or 0.0)
        x0 = float(getattr(z, "x0", 0.0) or 0.0)
        non_black = 1 if getattr(z, "non_black", False) else 0
        return (-sz, -non_black, y0, x0)

    cands.sort(key=_cand_key)
    top = cands[0]
    top_txt = (getattr(top, "text", "") or "").strip()
    top_x0 = float(getattr(top, "x0", 0.0) or 0.0)
    top_y0 = float(getattr(top, "y0", 0.0) or 0.0)
    top_sz = float(getattr(top, "size", 0.0) or 0.0)

    parts = [top_txt]

    # Stitch additional lines that look like continuation of the title.
    max_gap = max(18.0, body_size * 2.4)
    for l in cands[1:]:
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if abs(sz - top_sz) > 2.0:
            continue
        if y0 < top_y0:
            continue
        if (y0 - top_y0) > (max_gap * 2.2):
            continue
        if abs(x0 - top_x0) > 140.0:
            continue
        # must be close to prior stitched line
        last_y = float(getattr(cands[0], "y0", 0.0) or 0.0)
        if parts:
            # approximate last y using current top_y0 progression
            pass
        if (y0 - top_y0) > (max_gap * 1.6) and len(parts) >= 2:
            break
        if _PAGE_FOOTER_RE.match(t):
            continue
        parts.append(t)

    title = _clean_label(" ".join(parts))
    if not title or len(title) <= 2:
        return None
    # Titles shouldn't look like a single field label with trailing punctuation.
    title = title.strip(":-").strip()
    return title or None


def _build_header_blocks(lines, body_size: float):
    # Column headers: black text in a top band, slightly larger than body.
    header_lines = []
    for l in lines:
        if getattr(l, "non_black", False):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 > 175.0:
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if sz < body_size + 1.0:
            continue
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if _is_bracket_meta(l):
            continue
        if _PAGE_FOOTER_RE.match(t):
            continue
        header_lines.append(l)

    header_lines.sort(key=lambda z: (float(getattr(z, "x0", 0.0) or 0.0), float(getattr(z, "y0", 0.0) or 0.0)))

    blocks = []
    for l in header_lines:
        placed = False
        lx0, lx1 = float(getattr(l, "x0", 0.0) or 0.0), float(getattr(l, "x1", 0.0) or 0.0)
        for b in blocks:
            if abs(lx0 - b["x0_ref"]) <= 40.0 or not (lx1 < b["x0"] - 20.0 or lx0 > b["x1"] + 20.0):
                b["lines"].append(l)
                b["x0"] = min(b["x0"], lx0)
                b["x1"] = max(b["x1"], lx1)
                b["x0_ref"] = (b["x0_ref"] * 0.7) + (lx0 * 0.3)
                placed = True
                break
        if not placed:
            blocks.append({"x0": lx0, "x1": lx1, "x0_ref": lx0, "lines": [l]})

    out = []
    for b in blocks:
        b["lines"].sort(key=lambda z: (float(getattr(z, "y0", 0.0) or 0.0), float(getattr(z, "x0", 0.0) or 0.0)))
        txt = _clean_label(" ".join((getattr(ln, "text", "") or "").strip() for ln in b["lines"] if (getattr(ln, "text", "") or "").strip()))
        if not txt:
            continue
        out.append({"x0": b["x0"], "x1": b["x1"], "x_center": 0.5 * (b["x0"] + b["x1"]), "text": txt})
    out.sort(key=lambda z: z["x_center"])
    return out


def _header_for_x(headers, x: float) -> Optional[str]:
    if not headers:
        return None
    best = None
    best_d = 1e18
    for h in headers:
        d = abs(float(h["x_center"]) - x)
        if d < best_d:
            best_d = d
            best = h
    if best is None:
        return None
    if best_d <= 130.0:
        return best["text"]
    return None


def _id_has_read_only_marker(lines, idx: int) -> bool:
    # More precise than the old version:
    # - only treat as read-only if marker is near the ID's column (x proximity)
    # - look slightly forward (where template meta usually appears)
    id_line = lines[idx]
    base_y = float(getattr(id_line, "y0", 0.0) or 0.0)
    ix0 = float(getattr(id_line, "x0", 0.0) or 0.0)
    ix1 = float(getattr(id_line, "x1", ix0) or ix0)
    ixc = 0.5 * (ix0 + ix1)

    def _x_close(lj) -> bool:
        x0 = float(getattr(lj, "x0", 0.0) or 0.0)
        x1 = float(getattr(lj, "x1", x0) or x0)
        xc = 0.5 * (x0 + x1)
        # same column-ish: center close OR left edges close OR overlap
        if abs(xc - ixc) <= 55.0:
            return True
        if abs(x0 - ix0) <= 35.0:
            return True
        if not (x1 < ix0 - 18.0 or x0 > ix1 + 18.0):
            return True
        return False

    lo = max(0, idx - 2)
    hi = min(len(lines), idx + 14)
    for j in range(lo, hi):
        lj = lines[j]
        y = float(getattr(lj, "y0", 0.0) or 0.0)
        if y < base_y - 18.0:
            continue
        if y > base_y + 85.0:
            break
        t = (getattr(lj, "text", "") or "").strip()
        if not t:
            continue
        if "read-only" in t.lower() or "read only" in t.lower():
            if _x_close(lj):
                return True
    return False


def _find_left_label_block(lines, id_idx: int, id_y: float, body_size: float, left_margin: float, headers_present: bool) -> Optional[str]:
    # Nearest black left-column label above the id, with wrapping lines.
    y_window = 380.0
    size_lo = body_size - 1.8
    size_hi = body_size + 1.6
    x_hi = left_margin + 35.0

    best_j = None
    best_y = -1e18
    for j in range(id_idx - 1, -1, -1):
        lj = lines[j]
        y = float(getattr(lj, "y0", 0.0) or 0.0)
        if y < id_y - y_window:
            break
        if getattr(lj, "non_black", False):
            continue
        if headers_present and y <= 175.0 and float(getattr(lj, "size", 0.0) or 0.0) >= body_size + 1.0:
            continue
        if float(getattr(lj, "x0", 0.0) or 0.0) > x_hi:
            continue
        if not (size_lo <= float(getattr(lj, "size", 0.0) or 0.0) <= size_hi):
            continue
        t = (getattr(lj, "text", "") or "").strip()
        if not t:
            continue
        if _is_bracket_meta(lj):
            continue
        if t in ("•", "\u2022"):
            continue
        if _PAGE_FOOTER_RE.match(t):
            continue
        if y > best_y:
            best_y = y
            best_j = j

    if best_j is None:
        return None

    start = best_j
    line_gap = max(18.0, body_size * 2.2)
    while start - 1 >= 0:
        prev = lines[start - 1]
        if getattr(prev, "non_black", False):
            break
        if float(getattr(prev, "x0", 0.0) or 0.0) > x_hi:
            break
        if not (size_lo <= float(getattr(prev, "size", 0.0) or 0.0) <= size_hi):
            break
        if (float(getattr(lines[start], "y0", 0.0) or 0.0) - float(getattr(prev, "y0", 0.0) or 0.0)) > line_gap:
            break
        pt = (getattr(prev, "text", "") or "").strip()
        if not pt:
            break
        if _is_bracket_meta(prev):
            break
        if pt in ("•", "\u2022"):
            break
        if _PAGE_FOOTER_RE.match(pt):
            break
        start -= 1

    parts = []
    for k in range(start, best_j + 1):
        tk = (getattr(lines[k], "text", "") or "").strip()
        if not tk or tk in ("•", "\u2022"):
            continue
        if _PAGE_FOOTER_RE.match(tk):
            continue
        parts.append(tk)

    label = _clean_label(" ".join(parts))
    if not label or len(label) <= 2:
        return None
    return label


def _find_below_label_block(lines, id_idx: int, id_y: float, body_size: float, left_margin: float, headers_present: bool) -> Optional[str]:
    # Some layouts place the human label below the field ID block.
    # Find the nearest plausible black left-ish label below and stitch wrapped lines.
    y_window = 190.0
    size_lo = body_size - 1.8
    size_hi = body_size + 1.8

    id_line = lines[id_idx]
    ix0 = float(getattr(id_line, "x0", 0.0) or 0.0)
    # If the ID is left-ish, allow labels near the ID; otherwise, prefer the left margin.
    x_anchor = ix0 if ix0 <= (left_margin + 120.0) else left_margin
    x_lo = max(0.0, x_anchor - 30.0)
    x_hi = x_anchor + 120.0

    best_j = None
    best_dy = 1e18

    for j in range(id_idx + 1, min(len(lines), id_idx + 80)):
        lj = lines[j]
        y = float(getattr(lj, "y0", 0.0) or 0.0)
        if y <= id_y + 6.0:
            continue
        if y > id_y + y_window:
            break
        if getattr(lj, "non_black", False):
            continue
        if headers_present and y <= 175.0 and float(getattr(lj, "size", 0.0) or 0.0) >= body_size + 1.0:
            continue
        x0 = float(getattr(lj, "x0", 0.0) or 0.0)
        if not (x_lo <= x0 <= x_hi):
            continue
        sz = float(getattr(lj, "size", 0.0) or 0.0)
        if not (size_lo <= sz <= size_hi):
            continue
        t = (getattr(lj, "text", "") or "").strip()
        if not t:
            continue
        if _is_bracket_meta(lj):
            continue
        if _PAGE_FOOTER_RE.match(t):
            continue
        # Avoid picking a single short token unless it looks like real words.
        cand = _clean_label(t)
        if not cand:
            continue
        if len(cand) <= 3 and _text_quality(cand) < 0.45:
            continue

        dy = y - id_y
        if dy < best_dy:
            best_dy = dy
            best_j = j

    if best_j is None:
        return None

    # Stitch wrapped lines going downward.
    parts = []
    size_lo2 = body_size - 2.0
    size_hi2 = body_size + 2.2
    x0_ref = float(getattr(lines[best_j], "x0", 0.0) or 0.0)
    y_prev = float(getattr(lines[best_j], "y0", 0.0) or 0.0)
    line_gap = max(18.0, body_size * 2.35)

    for k in range(best_j, min(len(lines), best_j + 10)):
        lk = lines[k]
        if getattr(lk, "non_black", False):
            break
        yk = float(getattr(lk, "y0", 0.0) or 0.0)
        if yk < id_y + 6.0:
            continue
        if yk > id_y + y_window:
            break
        if (yk - y_prev) > (line_gap * 1.35) and parts:
            break
        xk = float(getattr(lk, "x0", 0.0) or 0.0)
        if abs(xk - x0_ref) > 70.0 and parts:
            break
        szk = float(getattr(lk, "size", 0.0) or 0.0)
        if not (size_lo2 <= szk <= size_hi2):
            break
        tk = (getattr(lk, "text", "") or "").strip()
        if not tk:
            break
        if _is_bracket_meta(lk):
            break
        if _PAGE_FOOTER_RE.match(tk):
            break
        parts.append(tk)
        y_prev = yk

    label = _clean_label(" ".join(parts))
    if not label or len(label) <= 2:
        return None
    return label


def _find_row_context(lines, id_idx: int, id_y: float, body_size: float, left_margin: float) -> Optional[str]:
    # Find a row-item label near the id's row band (often grey/black, left-ish).
    best = None
    best_key = None

    id_line = lines[id_idx]
    id_x = float(getattr(id_line, "x0", 0.0) or 0.0)

    for j in range(id_idx - 1, -1, -1):
        lj = lines[j]
        y = float(getattr(lj, "y0", 0.0) or 0.0)
        if y < id_y - 95.0:
            break
        t = (getattr(lj, "text", "") or "").strip()
        if not t:
            continue
        if _is_bracket_meta(lj):
            continue
        if t in ("•", "\u2022"):
            continue
        if _PAGE_FOOTER_RE.match(t):
            continue

        # Ignore big titles (top band).
        if float(getattr(lj, "size", 0.0) or 0.0) >= body_size + 4.0 and float(getattr(lj, "y0", 0.0) or 0.0) <= 230.0:
            continue

        # Must be on same row-ish band (typically above the id).
        if not (id_y - 75.0 <= y <= id_y + 10.0):
            continue

        x0 = float(getattr(lj, "x0", 0.0) or 0.0)
        x1 = float(getattr(lj, "x1", x0) or x0)
        xc = 0.5 * (x0 + x1)

        # Prefer row labels from the left side, especially for wide tables.
        # Still allow something above the id if it's directly aligned, but avoid far-right option/anchor text.
        if x0 > max(260.0, left_margin + 220.0):
            if abs(xc - id_x) > 80.0:
                continue

        dy = abs((id_y - 25.0) - y)
        key = (dy, x0)
        if best_key is None or key < best_key:
            cand = _clean_label(t)
            if cand:
                best = cand
                best_key = key

    if best and len(best) <= 4 and _text_quality(best) < 0.45:
        return None
    return best


def _field_name_for_id(lines, id_idx: int, id_indices_by_y, headers, body_size: float, left_margin: float) -> Optional[str]:
    id_line = lines[id_idx]
    id_y = float(getattr(id_line, "y0", 0.0) or 0.0)
    id_xc = 0.5 * (float(getattr(id_line, "x0", 0.0) or 0.0) + float(getattr(id_line, "x1", 0.0) or 0.0))

    headers_present = bool(headers)
    col_header = _header_for_x(headers, id_xc) if headers_present else None

    # Determine if this id shares a "row" with other ids (multi-column response).
    multi_col = False
    y_bucket = int(id_y / 3.0)
    sibs = id_indices_by_y.get(y_bucket, [])
    if len(sibs) >= 2:
        xs = [float(getattr(lines[k], "x0", 0.0) or 0.0) for k in sibs]
        if max(xs) - min(xs) > 80.0:
            multi_col = True

    left_label = _find_left_label_block(lines, id_idx, id_y, body_size, left_margin, headers_present)
    row_label = _find_row_context(lines, id_idx, id_y, body_size, left_margin)

    # New: some layouts put the label below the ID.
    below_label = None
    if not left_label and not row_label:
        below_label = _find_below_label_block(lines, id_idx, id_y, body_size, left_margin, headers_present)

    field = None
    if headers_present and id_y > 175.0:
        base = left_label or row_label or below_label
        if base and col_header and (multi_col or float(getattr(id_line, "x0", 0.0) or 0.0) >= 250.0):
            field = _clean_label(f"{base} - {col_header}")
        else:
            field = base or col_header
    else:
        field = left_label or row_label or below_label or col_header
        if field and col_header and multi_col and col_header not in field:
            field = _clean_label(f"{field} - {col_header}")

    if not field:
        return None

    # Final sanity: avoid labels that are essentially empty / non-letter noise.
    q = _text_quality(field)
    if q < 0.12 and len(field) <= 8:
        return None

    # Avoid accidentally returning the title-like "Page X of Y".
    if _PAGE_FOOTER_RE.match(field.strip()):
        return None

    return field


def extract(pages: List[Tuple[int, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        body_size = _detect_body_size(lines)
        left_margin = _detect_left_margin(lines, body_size)

        title = _detect_form_title(lines, body_size)
        if title:
            current_form = title

        headers = _build_header_blocks(lines, body_size)

        # Collect true field ID lines.
        id_idxs = []
        for i, l in enumerate(lines):
            if _is_field_id_line(l):
                id_idxs.append(i)

        if not id_idxs:
            continue

        # Bucket ids by y to detect multi-column rows.
        id_indices_by_y = {}
        for idx in id_idxs:
            yb = int(float(getattr(lines[idx], "y0", 0.0) or 0.0) / 3.0)
            id_indices_by_y.setdefault(yb, []).append(idx)

        for idx in id_idxs:
            # Skip read-only fields (more precise column-aware marker check).
            if _id_has_read_only_marker(lines, idx):
                continue

            field_name = _field_name_for_id(lines, idx, id_indices_by_y, headers, body_size, left_margin)
            if not field_name:
                continue

            out.append(
                {
                    "form_name": current_form or "",
                    "field_name": field_name,
                    "page": int(page_idx0) + 1,
                }
            )

    return out
