```python
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
    if _BRACKET_RE.match(tt):
        return False
    if _PAGE_FOOTER_RE.match(tt):
        return False
    if len(tt) <= 2:
        return False
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

    max_gap = max(18.0, body_size * 2.4)
    last_y = top_y0
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
        if abs(x0 - top_x0) > 160.0:
            continue
        if (y0 - last_y) > (max_gap * 1.45) and parts:
            break
        if _PAGE_FOOTER_RE.match(t):
            continue
        parts.append(t)
        last_y = y0

    title = _clean_label(" ".join(parts))
    if not title or len(title) <= 2:
        return None
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
    # Treat as read-only only if marker is near the ID's column.
    id_line = lines[idx]
    base_y = float(getattr(id_line, "y0", 0.0) or 0.0)
    ix0 = float(getattr(id_line, "x0", 0.0) or 0.0)
    ix1 = float(getattr(id_line, "x1", ix0) or ix0)
    ixc = 0.5 * (ix0 + ix1)

    def _x_close(lj) -> bool:
        x0 = float(getattr(lj, "x0", 0.0) or 0.0)
        x1 = float(getattr(lj, "x1", x0) or x0)
        xc = 0.5 * (x0 + x1)
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


def _y_bucket(y: float, step: float = 3.0) -> int:
    try:
        return int(float(y) / step)
    except Exception:
        return 0


def _is_skippable_text_line(line) -> bool:
    t = (getattr(line, "text", "") or "").strip()
    if not t:
        return True
    if _PAGE_FOOTER_RE.match(t):
        return True
    if _is_bracket_meta(line):
        return True
    if t in ("•", "\u2022"):
        return True
    return False


def _detect_table_header_buckets(lines, body_size: float, id_buckets: set) -> set:
    # Detect "table header rows" anywhere on the page (not just the top band).
    # These often get incorrectly chosen as row labels for the first data row.
    counts = {}
    y_example = {}
    for l in lines:
        if _is_skippable_text_line(l):
            continue
        if _is_field_id_line(l):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if not (90.0 <= y0 <= 720.0):
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        # Slightly above body often indicates headers, but allow colored too (many templates).
        if sz < body_size + 0.7:
            continue
        b = _y_bucket(y0, 3.0)
        counts[b] = counts.get(b, 0) + 1
        y_example.setdefault(b, y0)

    header_buckets = set()
    for b, c in counts.items():
        if c >= 2 and b not in id_buckets:
            header_buckets.add(b)

    return header_buckets


def _stitch_wrapped_lines(lines, seed, body_size: float, x_ref: float, header_buckets: set, y_min: float, y_max: float) -> str:
    # Stitch label lines around a seed line based on geometry (order-independent).
    if seed is None:
        return ""
    size_lo = body_size - 2.6
    size_hi = body_size + 2.6
    line_gap = max(18.0, body_size * 2.35)

    seed_y = float(getattr(seed, "y0", 0.0) or 0.0)
    seed_x0 = float(getattr(seed, "x0", 0.0) or 0.0)
    seed_sz = float(getattr(seed, "size", 0.0) or 0.0)

    # Collect candidate lines in a band around the seed.
    cands = []
    for l in lines:
        if _is_skippable_text_line(l):
            continue
        if _is_field_id_line(l):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 < y_min or y0 > y_max:
            continue
        if _y_bucket(y0, 3.0) in header_buckets:
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if abs(x0 - x_ref) > 80.0 and abs(x0 - seed_x0) > 90.0:
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        # Allow seed's own size even if it's slightly out of body range (some bold labels).
        if not (size_lo <= sz <= size_hi) and abs(sz - seed_sz) > 1.6:
            continue
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        cands.append(l)

    if not cands:
        t0 = (getattr(seed, "text", "") or "").strip()
        return _clean_label(t0)

    # Keep lines close in y to the seed and to each other.
    cands.sort(key=lambda z: (float(getattr(z, "y0", 0.0) or 0.0), float(getattr(z, "x0", 0.0) or 0.0)))
    # Find cluster around seed_y.
    cluster = []
    for l in cands:
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if abs(y0 - seed_y) <= (line_gap * 1.45):
            cluster.append(l)

    if not cluster:
        cluster = [seed]

    # Expand cluster upward and downward by small y gaps and consistent indentation.
    cluster.sort(key=lambda z: float(getattr(z, "y0", 0.0) or 0.0))
    # Greedy expansion: include nearby lines that look like wrapping.
    expanded = []
    for l in cluster:
        expanded.append(l)

    # Add additional wrap lines above and below.
    y_vals = [float(getattr(l, "y0", 0.0) or 0.0) for l in expanded]
    y_lo, y_hi = (min(y_vals), max(y_vals)) if y_vals else (seed_y, seed_y)

    for l in cands:
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 < y_lo - (line_gap * 1.25) or y0 > y_hi + (line_gap * 1.25):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if abs(x0 - x_ref) > 80.0 and abs(x0 - seed_x0) > 90.0:
            continue
        expanded.append(l)

    # Deduplicate objects (by identity) then keep a tight y-span.
    seen = set()
    uniq = []
    for l in expanded:
        if id(l) in seen:
            continue
        seen.add(id(l))
        uniq.append(l)

    uniq.sort(key=lambda z: (float(getattr(z, "y0", 0.0) or 0.0), float(getattr(z, "x0", 0.0) or 0.0)))

    # Keep contiguous lines where y-gaps are small.
    kept = []
    prev_y = None
    for l in uniq:
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if prev_y is None:
            kept.append(l)
            prev_y = y0
            continue
        if (y0 - prev_y) <= (line_gap * 1.35):
            kept.append(l)
            prev_y = y0

    parts = []
    for l in kept:
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        parts.append(t)

    return _clean_label(" ".join(parts))


def _find_same_row_left_label(lines, id_y: float, body_size: float, left_margin: float, header_buckets: set) -> Optional[str]:
    # Find a row label aligned with the ID's y (order-independent).
    y_band = max(12.0, body_size * 1.35)
    size_lo = body_size - 2.8
    size_hi = body_size + 2.8
    x_hi = max(left_margin + 260.0, left_margin + 220.0)

    best = None
    best_key = None

    for l in lines:
        if _is_skippable_text_line(l):
            continue
        if _is_field_id_line(l):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if abs(y0 - id_y) > y_band:
            continue
        if _y_bucket(y0, 3.0) in header_buckets:
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if x0 > x_hi:
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if not (size_lo <= sz <= size_hi):
            continue
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        cand = _clean_label(t)
        if not cand:
            continue
        if len(cand) <= 3 and _text_quality(cand) < 0.45:
            continue
        # Prefer leftmost and closest in y.
        key = (abs(y0 - id_y), x0, -len(cand))
        if best_key is None or key < best_key:
            best = l
            best_key = key

    if best is None:
        return None

    stitched = _stitch_wrapped_lines(
        lines=lines,
        seed=best,
        body_size=body_size,
        x_ref=float(getattr(best, "x0", 0.0) or 0.0),
        header_buckets=header_buckets,
        y_min=id_y - (y_band * 2.2),
        y_max=id_y + (y_band * 2.2),
    )

    if not stitched or len(stitched) <= 2:
        return None
    return stitched


def _find_left_column_label(lines, id_y: float, body_size: float, left_margin: float, headers_present: bool, header_buckets: set) -> Optional[str]:
    # Nearest plausible left-column label above (or on) the ID, order-independent.
    y_window = 420.0
    size_lo = body_size - 2.7
    size_hi = body_size + 2.8
    x_hi = left_margin + 140.0

    best = None
    best_key = None

    for l in lines:
        if getattr(l, "non_black", False):
            continue
        if _is_skippable_text_line(l):
            continue
        if _is_field_id_line(l):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 > id_y + 6.0:
            continue
        if y0 < id_y - y_window:
            continue
        if _y_bucket(y0, 3.0) in header_buckets:
            continue
        if headers_present and y0 <= 175.0 and float(getattr(l, "size", 0.0) or 0.0) >= body_size + 1.0:
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if x0 > x_hi:
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if not (size_lo <= sz <= size_hi):
            continue
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        cand = _clean_label(t)
        if not cand:
            continue
        if len(cand) <= 3 and _text_quality(cand) < 0.45:
            continue
        # Prefer closest above in y, then leftmost.
        key = (abs(id_y - y0), x0, -len(cand))
        if best_key is None or key < best_key:
            best = l
            best_key = key

    if best is None:
        return None

    stitched = _stitch_wrapped_lines(
        lines=lines,
        seed=best,
        body_size=body_size,
        x_ref=float(getattr(best, "x0", 0.0) or 0.0),
        header_buckets=header_buckets,
        y_min=float(getattr(best, "y0", 0.0) or 0.0) - (max(18.0, body_size * 2.2) * 2.2),
        y_max=id_y + 6.0,
    )
    if not stitched or len(stitched) <= 2:
        return None
    return stitched


def _find_below_leftish_label(lines, id_y: float, body_size: float, left_margin: float, headers_present: bool, header_buckets: set, id_x0: float) -> Optional[str]:
    # Some layouts place the human label below the field ID.
    y_window = 210.0
    size_lo = body_size - 2.8
    size_hi = body_size + 2.9

    x_anchor = id_x0 if id_x0 <= (left_margin + 120.0) else left_margin
    x_lo = max(0.0, x_anchor - 40.0)
    x_hi = x_anchor + 160.0

    best = None
    best_key = None

    for l in lines:
        if getattr(l, "non_black", False):
            continue
        if _is_skippable_text_line(l):
            continue
        if _is_field_id_line(l):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 <= id_y + 6.0:
            continue
        if y0 > id_y + y_window:
            continue
        if _y_bucket(y0, 3.0) in header_buckets:
            continue
        if headers_present and y0 <= 175.0 and float(getattr(l, "size", 0.0) or 0.0) >= body_size + 1.0:
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if not (x_lo <= x0 <= x_hi):
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if not (size_lo <= sz <= size_hi):
            continue
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        cand = _clean_label(t)
        if not cand:
            continue
        if len(cand) <= 3 and _text_quality(cand) < 0.45:
            continue
        key = (y0 - id_y, x0, -len(cand))
        if best_key is None or key < best_key:
            best = l
            best_key = key

    if best is None:
        return None

    stitched = _stitch_wrapped_lines(
        lines=lines,
        seed=best,
        body_size=body_size,
        x_ref=float(getattr(best, "x0", 0.0) or 0.0),
        header_buckets=header_buckets,
        y_min=id_y + 6.0,
        y_max=id_y + y_window,
    )
    if not stitched or len(stitched) <= 2:
        return None
    return stitched


def _find_row_context(lines, id_y: float, body_size: float, left_margin: float, header_buckets: set, id_x: float) -> Optional[str]:
    # Find a row-item label near the id's row band (often left-ish). Avoid table header rows.
    y_lo = id_y - 85.0
    y_hi = id_y + 26.0
    x_cut = max(260.0, left_margin + 230.0)

    best_line = None
    best_key = None

    for l in lines:
        if _is_skippable_text_line(l):
            continue
        if _is_field_id_line(l):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if not (y_lo <= y0 <= y_hi):
            continue
        if _y_bucket(y0, 3.0) in header_buckets:
            continue
        # Ignore very large "top title" artifacts.
        if float(getattr(l, "size", 0.0) or 0.0) >= body_size + 4.0 and y0 <= 230.0:
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        x1 = float(getattr(l, "x1", x0) or x0)
        xc = 0.5 * (x0 + x1)

        # Prefer left side; only accept far-right if aligned with the id column.
        if x0 > x_cut and abs(xc - id_x) > 80.0:
            continue

        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        cand = _clean_label(t)
        if not cand:
            continue
        if len(cand) <= 4 and _text_quality(cand) < 0.45:
            continue

        # Prefer closer to the id's y (same-row), then leftmost.
        key = (abs(y0 - id_y), x0, -len(cand))
        if best_key is None or key < best_key:
            best_line = l
            best_key = key

    if best_line is None:
        return None

    stitched = _stitch_wrapped_lines(
        lines=lines,
        seed=best_line,
        body_size=body_size,
        x_ref=float(getattr(best_line, "x0", 0.0) or 0.0),
        header_buckets=header_buckets,
        y_min=id_y - (max(18.0, body_size * 2.2) * 1.9),
        y_max=id_y + (max(18.0, body_size * 2.2) * 1.2),
    )
    if not stitched or len(stitched) <= 2:
        return None
    return stitched


def _field_name_for_id(
    lines,
    id_idx: int,
    id_indices_by_y,
    headers,
    body_size: float,
    left_margin: float,
    header_buckets: set,
    header_usage: Dict[str, int],
) -> Optional[str]:
    id_line = lines[id_idx]
    id_y = float(getattr(id_line, "y0", 0.0) or 0.0)
    id_x0 = float(getattr(id_line, "x0", 0.0) or 0.0)
    id_x1 = float(getattr(id_line, "x1", id_x0) or id_x0)
    id_xc = 0.5 * (id_x0 + id_x1)

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

    # Prefer row-aligned label first (fixes cases where list order puts the ID before its row label).
    same_row = _find_same_row_left_label(lines, id_y, body_size, left_margin, header_buckets)

    # Then left-column label (section/field label at left margin).
    left_label = _find_left_column_label(lines, id_y, body_size, left_margin, headers_present, header_buckets)

    # Then broader row context (near band).
    row_label = _find_row_context(lines, id_y, body_size, left_margin, header_buckets, id_xc)

    # Then below-label (some templates place the label below the ID).
    below_label = _find_below_leftish_label(lines, id_y, body_size, left_margin, headers_present, header_buckets, id_x0)

    base = same_row or left_label or row_label or below_label

    field = None
    if base:
        if headers_present and col_header and (multi_col or id_x0 >= 250.0):
            field = _clean_label(f"{base} - {col_header}")
        else:
            field = base
        # If multi-col and header exists but wasn't appended (e.g., narrow x), add it when it adds information.
        if field and col_header and multi_col and col_header not in field and id_x0 >= 230.0:
            field = _clean_label(f"{field} - {col_header}")
    else:
        # Avoid turning a repeated table column header into a "field" (false extractions like header cells).
        if col_header:
            use_count = int(header_usage.get(col_header, 0) or 0)
            if use_count <= 1:
                field = col_header
            else:
                field = None
        else:
            field = None

    if not field:
        return None

    q = _text_quality(field)
    if q < 0.12 and len(field) <= 8:
        return None
    if _PAGE_FOOTER_RE.match(field.strip()):
        return None

    # If the result is exactly a detected table header bucket label, drop it.
    # (Structural protection: don't emit header-row cells as fields.)
    # This is a last-resort guard; primary fix is selecting base labels correctly.
    if headers_present and col_header and field == col_header:
        if int(header_usage.get(col_header, 0) or 0) >= 2:
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
        id_buckets = set()
        for i, l in enumerate(lines):
            if _is_field_id_line(l):
                id_idxs.append(i)
                y0 = float(getattr(l, "y0", 0.0) or 0.0)
                id_buckets.add(_y_bucket(y0, 3.0))

        if not id_idxs:
            continue

        # Detect table header rows (avoid mislabeling as fields).
        header_row_buckets = _detect_table_header_buckets(lines, body_size, id_buckets)

        # Bucket ids by y to detect multi-column rows.
        id_indices_by_y = {}
        for idx in id_idxs:
            yb = int(float(getattr(lines[idx], "y0", 0.0) or 0.0) / 3.0)
            id_indices_by_y.setdefault(yb, []).append(idx)

        # Header usage counts (for suppressing "header-only" false fields when it repeats).
        header_usage: Dict[str, int] = {}
        if headers:
            for idx in id_idxs:
                l = lines[idx]
                x0 = float(getattr(l, "x0", 0.0) or 0.0)
                x1 = float(getattr(l, "x1", x0) or x0)
                xc = 0.5 * (x0 + x1)
                h = _header_for_x(headers, xc)
                if h:
                    header_usage[h] = header_usage.get(h, 0) + 1

        for idx in id_idxs:
            # Skip read-only fields (column-aware marker check).
            if _id_has_read_only_marker(lines, idx):
                continue

            field_name = _field_name_for_id(
                lines=lines,
                id_idx=idx,
                id_indices_by_y=id_indices_by_y,
                headers=headers,
                body_size=body_size,
                left_margin=left_margin,
                header_buckets=header_row_buckets,
                header_usage=header_usage,
            )
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
```
