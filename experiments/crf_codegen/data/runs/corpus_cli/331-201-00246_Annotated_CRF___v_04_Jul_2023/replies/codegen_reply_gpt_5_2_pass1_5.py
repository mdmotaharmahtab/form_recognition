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

# Inline field-id tokens in arbitrary text (e.g., "Label [OID123]").
_INLINE_ID_TOKEN_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9_-]*)\]")

# Leading technical annotation blocks often injected into label lines.
_TECH_BRACKET_PREFIX_RE = re.compile(r"^\s*\[([^\]]{2,250})\]\s*")
_TRAILING_ID_TOKEN_RE = re.compile(r"\s*\[[A-Za-z0-9][A-Za-z0-9_-]*\]\s*$")

# Titles sometimes include a printed continuation suffix.
_TITLE_PAGE_SUFFIX_RE = re.compile(r"(\s*[-–—]\s*)?Page\s+\d+(\s*(of|/)\s*\d+)?\s*$", re.IGNORECASE)

# Short column headers that are meaningful qualifiers (e.g. "#1", "2").
_SHORT_QUAL_HDR_RE = re.compile(r"^\s*#?\s*\d+\s*$")


def _norm_space(s: str) -> str:
    return " ".join((s or "").split())


def _strip_leading_ordinals(s: str) -> str:
    # Removes leading "\25.\ " or "25. " style numbering (common in option/criterion rows).
    s = (s or "").strip()
    s = re.sub(r"^\s*\\\s*\d+\s*[.)]\s*", "", s)
    s = re.sub(r"^\s*\d+\s*[.)]\s*", "", s)
    return s.strip()


def _text_quality(s: str) -> float:
    s = (s or "").strip()
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


def _looks_like_technical_annotation_text(t: str) -> bool:
    tt = (t or "").strip()
    if not tt:
        return False
    if _PAGE_FOOTER_RE.match(tt):
        return False

    # Consider bracket-only lines as technical if they carry machine-ish markers.
    if _BRACKET_RE.match(tt):
        inner = tt[1:-1].strip().lower()
        if (
            (":" in inner)
            or ("values" in inner)
            or ("enumeration" in inner)
            or ("readonly" in inner)
            or ("read-only" in inner)
            or ("read only" in inner)
            or ("format" in inner)
            or ("type" in inner)
        ):
            return True

    low = tt.lower()
    # Non-bracket cases: still treat as technical if they clearly describe metadata.
    if ("type:" in low) or ("values:" in low) or ("enumeration" in low and "values" in low):
        return True
    if ("read-only" in low) or ("readonly" in low) or ("read only" in low):
        return True
    if "format:" in low:
        return True
    return False


def _strip_technical_bracket_prefixes(s: str) -> str:
    """
    Remove leading bracketed technical annotations like:
      "[TYPE: enumeration (...)] Consent Obtained?"
    but keep legitimate bracketed units like "[mmHg]" or "[kg]" (no ':'/values/type-like markers).
    Also drop standalone bracket-only technical lines.
    """
    s = (s or "")
    ss = s.strip()
    if _BRACKET_RE.match(ss) and _looks_like_technical_annotation_text(ss):
        return ""

    for _ in range(3):
        m = _TECH_BRACKET_PREFIX_RE.match(s)
        if not m:
            break
        inner = (m.group(1) or "").strip()
        inner_low = inner.lower()
        is_tech = (
            (":" in inner)
            or ("values" in inner_low)
            or ("enumeration" in inner_low)
            or ("type" in inner_low)
            or ("readonly" in inner_low)
            or ("read-only" in inner_low)
            or ("read only" in inner_low)
            or ("format" in inner_low)
        )
        if not is_tech:
            break
        s = s[m.end() :]
    return s


def _clean_label(s: str) -> str:
    s = (s or "").replace("\u00a0", " ")
    s = _strip_technical_bracket_prefixes(s)

    s = _norm_space(s).strip()
    s = s.strip("*").strip()
    s = re.sub(r"^[\u2022•·]\s*", "", s)
    s = _strip_leading_ordinals(s)

    # If a label line ends with an inline field-id token, drop it.
    s = _TRAILING_ID_TOKEN_RE.sub("", s).strip()

    # Trim trailing punctuation that is usually formatting.
    s = s.strip(":-").strip()

    # Drop remaining bracket-only technical residue.
    if _BRACKET_RE.match(s.strip()) and _looks_like_technical_annotation_text(s.strip()):
        return ""

    return s


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
    low = token.lower()
    if low in ("type", "read-only", "readonly"):
        return False
    return True


def _is_field_id_line(line) -> bool:
    t = (getattr(line, "text", "") or "").strip()
    return _is_field_id_text(t)


def _iter_inline_id_tokens(t: str):
    if not t:
        return
    for m in _INLINE_ID_TOKEN_RE.finditer(t):
        tok = (m.group(1) or "").strip()
        if not tok:
            continue
        if not _ID_TOKEN_RE.match(tok):
            continue
        low = tok.lower()
        if low in ("type", "read-only", "readonly"):
            continue
        yield tok


def _inline_id_label_hint(t: str) -> Optional[str]:
    """
    If a line contains an inline [TOKEN] and also human label text, return the cleaned label hint.
    Avoid treating bracket-only meta or type/values blocks as a label.
    """
    tt = (t or "").strip()
    if not tt:
        return None
    if _PAGE_FOOTER_RE.match(tt):
        return None
    if _is_field_id_text(tt):
        return None
    if _BRACKET_RE.match(tt):
        return None
    if _looks_like_technical_annotation_text(tt):
        return None

    toks = list(_iter_inline_id_tokens(tt))
    if not toks:
        return None

    def _strip_ids_once(s: str) -> str:
        return _INLINE_ID_TOKEN_RE.sub(
            lambda m: "" if _ID_TOKEN_RE.match((m.group(1) or "").strip()) else m.group(0),
            s,
        )

    stripped = _strip_ids_once(tt)
    cand = _clean_label(stripped)
    if not cand:
        return None
    if len(cand) <= 2:
        return None
    if _text_quality(cand) < 0.18 and len(cand) <= 10:
        return None
    return cand


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
        if _is_field_id_line(l):
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if sz > body_size + 1.2:
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if 40.0 <= x0 <= 160.0 and 90.0 <= y0 <= 740.0:
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
    if _looks_like_technical_annotation_text(tt):
        return False
    if _PAGE_FOOTER_RE.match(tt):
        return False
    if len(tt) <= 2:
        return False
    if len(tt) <= 8 and _text_quality(tt) < 0.2:
        return False
    return True


def _clean_form_title(t: str) -> str:
    tt = _clean_label(t or "")
    tt = _TITLE_PAGE_SUFFIX_RE.sub("", tt).strip()
    # Remove a lingering trailing dash/colon after suffix removal.
    tt = tt.rstrip("-–—:").strip()
    return tt


def _detect_form_title(lines, body_size: float, left_margin: float) -> Optional[str]:
    # Prefer larger/colored text in a top band; accept continuation headings with slightly smaller deltas.
    cands = []
    for l in lines:
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 > 260.0:
            continue

        sz = float(getattr(l, "size", 0.0) or 0.0)
        non_black = bool(getattr(l, "non_black", False))
        x0 = float(getattr(l, "x0", 0.0) or 0.0)

        # Most titles sit near the left margin; allow a bit of slack.
        if x0 > left_margin + 220.0:
            continue

        # Titles can be slightly smaller on continuation pages; colored headings often indicate titles.
        if non_black:
            if sz < body_size + 1.5:
                continue
        else:
            # Relax vs previous: some templates use modest bold headings.
            if sz < body_size + 2.0:
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
        # Prefer left/top, then larger size; colored slightly preferred.
        return (-non_black, y0, x0, -sz)

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
        if abs(sz - top_sz) > 3.2:
            continue
        if y0 < top_y0:
            continue
        if (y0 - top_y0) > (max_gap * 2.6):
            continue
        if abs(x0 - top_x0) > 210.0:
            continue
        if (y0 - last_y) > (max_gap * 1.55) and parts:
            break
        if _PAGE_FOOTER_RE.match(t):
            continue
        parts.append(t)
        last_y = y0

    title = _clean_form_title(" ".join(parts))
    if not title or len(title) <= 2:
        return None
    return title


def _build_header_blocks_from_lines(header_lines, body_size: float):
    """
    Build column header blocks from an arbitrary set of header-ish lines,
    grouping by x overlap / proximity, and concatenating wrapped header text.
    """
    header_lines = list(header_lines or [])
    header_lines.sort(
        key=lambda z: (float(getattr(z, "x0", 0.0) or 0.0), float(getattr(z, "y0", 0.0) or 0.0))
    )

    blocks = []
    for l in header_lines:
        placed = False
        lx0, lx1 = float(getattr(l, "x0", 0.0) or 0.0), float(getattr(l, "x1", 0.0) or 0.0)
        for b in blocks:
            # Same column if close starts or overlaps.
            if abs(lx0 - b["x0_ref"]) <= 42.0 or not (lx1 < b["x0"] - 22.0 or lx0 > b["x1"] + 22.0):
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
        raw = " ".join(
            (getattr(ln, "text", "") or "").strip()
            for ln in b["lines"]
            if (getattr(ln, "text", "") or "").strip()
        )
        if not raw:
            continue

        # If the raw block itself is clearly technical metadata, drop it.
        if _looks_like_technical_annotation_text(raw):
            continue

        txt = _clean_label(raw)
        if not txt:
            continue
        if _looks_like_technical_annotation_text(txt):
            continue
        if _BRACKET_RE.match(txt.strip()):
            continue

        # Filter out header blocks that are mostly non-letters and very short,
        # but keep numeric qualifiers like "#1"/"2" for later attachment to row labels.
        if len(txt) <= 2:
            if not _SHORT_QUAL_HDR_RE.match(txt):
                continue
        if len(txt) <= 6 and _text_quality(txt) < 0.2:
            if not _SHORT_QUAL_HDR_RE.match(txt):
                continue

        out.append({"x0": b["x0"], "x1": b["x1"], "x_center": 0.5 * (b["x0"] + b["x1"]), "text": txt})

    out.sort(key=lambda z: z["x_center"])
    return out


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
        if _looks_like_technical_annotation_text(t):
            continue
        if _PAGE_FOOTER_RE.match(t):
            continue
        if _is_field_id_line(l):
            continue
        header_lines.append(l)

    return _build_header_blocks_from_lines(header_lines, body_size)


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
        txt = (best.get("text") or "").strip()
        if not txt:
            return None
        if _looks_like_technical_annotation_text(txt):
            return None
        if _BRACKET_RE.match(txt):
            return None
        return txt
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
        low = t.lower()
        if "read-only" in low or "read only" in low or "readonly" in low:
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
        # Bracket-only lines are never labels.
        return True
    if _looks_like_technical_annotation_text(t):
        return True
    if t in ("•", "\u2022"):
        return True
    return False


def _looks_like_choice_anchor_header_text(t: str) -> bool:
    tt = _clean_label(t or "")
    if not tt:
        return False
    if _looks_like_technical_annotation_text(tt):
        return False
    if _SHORT_QUAL_HDR_RE.match(tt):
        return False
    # Short, mostly letters, no digits: commonly rating/choice anchors in grids.
    if len(tt) > 14:
        return False
    if any(ch.isdigit() for ch in tt):
        return False
    # Keep 1-2 token headers like "Normal", "Normal Abnormal", "Yes/No".
    toks = tt.split()
    if len(toks) > 2:
        return False
    if _text_quality(tt) < 0.25:
        return False
    return True


def _detect_table_header_buckets(lines, body_size: float, id_buckets: set, id_idxs: List[int], left_margin: float) -> set:
    """
    Detect table header rows anywhere on the page (not just the top band).

    Neighbor-aware to handle slight y misalignment across columns, and includes
    single-cell header buckets when they're structurally header-like.
    """
    buckets: Dict[int, List[Any]] = {}
    for l in lines:
        if _is_skippable_text_line(l):
            continue
        if _is_field_id_line(l):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if not (90.0 <= y0 <= 720.0):
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        non_black = bool(getattr(l, "non_black", False))
        if non_black:
            if sz < body_size + 0.2:
                continue
        else:
            if sz < body_size + 0.55:
                continue

        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if _looks_like_technical_annotation_text(t):
            continue

        b = _y_bucket(y0, 3.0)
        buckets.setdefault(b, []).append(l)

    header_buckets = set()

    # Overall id x spread: used to decide whether a page has multi-column structures.
    id_xcs = []
    for idx in id_idxs:
        l = lines[idx]
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        x1 = float(getattr(l, "x1", x0) or x0)
        id_xcs.append(0.5 * (x0 + x1))
    id_spread = (max(id_xcs) - min(id_xcs)) if id_xcs else 0.0

    # Direct: buckets with 2+ header-ish items.
    for b, ls in buckets.items():
        if b in id_buckets:
            continue
        if len(ls) >= 2:
            header_buckets.add(b)

    # Neighbor-aware: if b by itself has 1 item but neighbor buckets complete a multi-column row.
    for b in list(buckets.keys()):
        if b in id_buckets:
            continue
        group = []
        for bb in (b - 1, b, b + 1):
            if bb in buckets and bb not in id_buckets:
                group.extend(buckets[bb])
        if len(group) < 2:
            continue
        xcs = []
        for l in group:
            x0 = float(getattr(l, "x0", 0.0) or 0.0)
            x1 = float(getattr(l, "x1", x0) or x0)
            xcs.append(0.5 * (x0 + x1))
        if not xcs:
            continue
        if (max(xcs) - min(xcs)) < 180.0:
            continue
        for bb in (b - 1, b, b + 1):
            if bb in buckets and bb not in id_buckets:
                header_buckets.add(bb)

    # Single-cell headers: mark if they sit above a multi-column id region and look like anchors.
    if id_spread >= 220.0:
        # Precompute min id bucket above/below signals.
        id_buckets_list = sorted(list(id_buckets)) if id_buckets else []
        for b, ls in buckets.items():
            if b in id_buckets:
                continue
            if len(ls) != 1:
                continue
            l = ls[0]
            t = (getattr(l, "text", "") or "").strip()
            if not t:
                continue
            # Require that there are ids "below" this bucket (nearby).
            has_ids_below = False
            for ib in id_buckets_list:
                if (ib - b) >= 1 and (ib - b) <= 28:
                    has_ids_below = True
                    break
            if not has_ids_below:
                continue

            y0 = float(getattr(l, "y0", 0.0) or 0.0)
            if y0 <= 85.0 or y0 >= 740.0:
                continue

            x0 = float(getattr(l, "x0", 0.0) or 0.0)
            x1 = float(getattr(l, "x1", x0) or x0)
            xc = 0.5 * (x0 + x1)

            # Avoid treating left-margin question text as a "header row".
            # But allow left-side headers when they're clearly short anchors.
            if x0 <= left_margin + 40.0 and len(_clean_label(t)) > 18:
                continue

            if _looks_like_choice_anchor_header_text(t):
                header_buckets.add(b)

            # Also mark as header if it's a short non-numeric single token in a column region.
            ct = _clean_label(t)
            if ct and (len(ct) <= 12) and (not any(ch.isdigit() for ch in ct)) and (xc > left_margin + 80.0):
                header_buckets.add(b)

    return header_buckets


def _find_local_header_blocks(lines, id_y: float, body_size: float, id_buckets: set) -> List[Dict[str, Any]]:
    """
    Find a local table header row immediately above an ID (for mid-page grids),
    returning header blocks suitable for _header_for_x().
    """
    y_top = max(80.0, id_y - 175.0)
    y_bot = id_y - 8.0
    if y_bot <= y_top:
        return []

    cand_buckets: Dict[int, List[Any]] = {}
    for l in lines:
        if _is_skippable_text_line(l):
            continue
        if _is_field_id_line(l):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 < y_top or y0 > y_bot:
            continue
        b = _y_bucket(y0, 3.0)
        if b in id_buckets:
            continue

        sz = float(getattr(l, "size", 0.0) or 0.0)
        non_black = bool(getattr(l, "non_black", False))
        if non_black:
            if sz < body_size + 0.1:
                continue
        else:
            if sz < body_size + 0.35:
                continue

        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if _PAGE_FOOTER_RE.match(t):
            continue
        if _looks_like_technical_annotation_text(t):
            continue
        if _is_bracket_meta(l):
            continue

        cand_buckets.setdefault(b, []).append(l)

    if not cand_buckets:
        return []

    best_group = None
    best_score = None

    for b in list(cand_buckets.keys()):
        group = []
        for bb in (b - 1, b, b + 1):
            if bb in cand_buckets:
                group.extend(cand_buckets[bb])

        if len(group) < 2:
            continue

        xcs = []
        ys = []
        for l in group:
            x0 = float(getattr(l, "x0", 0.0) or 0.0)
            x1 = float(getattr(l, "x1", x0) or x0)
            xcs.append(0.5 * (x0 + x1))
            ys.append(float(getattr(l, "y0", 0.0) or 0.0))
        if not xcs or not ys:
            continue
        if (max(xcs) - min(xcs)) < 160.0:
            continue

        y_mean = sum(ys) / max(1, len(ys))
        dist = max(0.0, id_y - y_mean)
        score = (dist, -len(group))
        if best_score is None or score < best_score:
            best_score = score
            best_group = group

    if not best_group:
        return []

    return _build_header_blocks_from_lines(best_group, body_size)


def _line_is_header_like_for_id(line, id_y: float, body_size: float) -> bool:
    """
    Heuristic: identify short anchor/header cells (e.g., "Test", "Normal") so we
    don't treat them as field labels or stitch them into labels.
    """
    if line is None:
        return False
    t0 = (getattr(line, "text", "") or "").strip()
    if not t0:
        return False
    if _is_field_id_line(line):
        return False
    if _PAGE_FOOTER_RE.match(t0) or _looks_like_technical_annotation_text(t0) or _BRACKET_RE.match(t0):
        return True

    y0 = float(getattr(line, "y0", 0.0) or 0.0)
    if y0 >= id_y - 2.0:
        return False  # same row/below: not a column header
    sz = float(getattr(line, "size", 0.0) or 0.0)

    tt = _clean_label(t0)
    if not tt:
        return True

    # "Header-ish" typography + short content, no digits.
    if sz >= body_size + 0.7 and len(tt) <= 14 and not any(ch.isdigit() for ch in tt):
        # Slightly stronger when it's 1-2 tokens.
        if len(tt.split()) <= 2:
            return True
    return False


def _stitch_wrapped_lines(
    lines,
    seed,
    body_size: float,
    x_ref: float,
    header_buckets: set,
    y_min: float,
    y_max: float,
    id_y: Optional[float] = None,
) -> str:
    # Stitch label lines around a seed line based on geometry (order-independent).
    if seed is None:
        return ""
    size_lo = body_size - 2.6
    size_hi = body_size + 2.6
    line_gap = max(18.0, body_size * 2.35)

    seed_y = float(getattr(seed, "y0", 0.0) or 0.0)
    seed_x0 = float(getattr(seed, "x0", 0.0) or 0.0)
    seed_sz = float(getattr(seed, "size", 0.0) or 0.0)

    iy = float(id_y) if (id_y is not None) else seed_y

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

        # Avoid stitching column headers (often immediately above the first data row).
        if _line_is_header_like_for_id(l, id_y=iy, body_size=body_size):
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if abs(x0 - x_ref) > 85.0 and abs(x0 - seed_x0) > 95.0:
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if not (size_lo <= sz <= size_hi) and abs(sz - seed_sz) > 1.6:
            continue
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if _looks_like_technical_annotation_text(t):
            continue
        cands.append(l)

    if not cands:
        t0 = (getattr(seed, "text", "") or "").strip()
        return _clean_label(t0)

    cands.sort(key=lambda z: (float(getattr(z, "y0", 0.0) or 0.0), float(getattr(z, "x0", 0.0) or 0.0)))

    cluster = []
    for l in cands:
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if abs(y0 - seed_y) <= (line_gap * 1.25):
            cluster.append(l)
    if not cluster:
        cluster = [seed]

    seen = set()
    uniq = []
    for l in cluster:
        if id(l) in seen:
            continue
        seen.add(id(l))
        uniq.append(l)

    uniq.sort(key=lambda z: (float(getattr(z, "y0", 0.0) or 0.0), float(getattr(z, "x0", 0.0) or 0.0)))

    kept = []
    prev_y = None
    for l in uniq:
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if prev_y is None:
            kept.append(l)
            prev_y = y0
            continue
        if (y0 - prev_y) <= (line_gap * 1.05):
            kept.append(l)
            prev_y = y0

    parts = []
    for l in kept:
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if _looks_like_technical_annotation_text(t):
            continue
        parts.append(t)

    return _clean_label(" ".join(parts))


def _find_same_row_left_label(
    lines,
    id_y: float,
    body_size: float,
    left_margin: float,
    header_buckets: set,
    id_xc: float,
) -> Optional[str]:
    y_band = max(12.0, body_size * 1.45)
    size_lo = body_size - 2.9
    size_hi = body_size + 3.0

    # Allow labels to appear further right in wide grids, but keep them left of the id column.
    x_hi = max(left_margin + 230.0, min(left_margin + 520.0, id_xc - 18.0))

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
        if _line_is_header_like_for_id(l, id_y=id_y, body_size=body_size):
            continue
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if _looks_like_technical_annotation_text(t):
            continue
        cand = _clean_label(t)
        if not cand:
            continue
        if len(cand) <= 3 and _text_quality(cand) < 0.45:
            continue
        key = (x0, abs(y0 - id_y), -len(cand))
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
        y_min=id_y - (y_band * 1.9),
        y_max=id_y + (y_band * 1.9),
        id_y=id_y,
    )

    if not stitched or len(stitched) <= 2:
        return None
    return stitched


def _find_same_row_right_label(
    lines,
    id_y: float,
    body_size: float,
    header_buckets: set,
    id_x1: float,
) -> Optional[str]:
    y_band = max(12.0, body_size * 1.45)
    size_lo = body_size - 2.9
    size_hi = body_size + 3.0

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
        if x0 <= id_x1 + 8.0:
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if not (size_lo <= sz <= size_hi):
            continue
        if _line_is_header_like_for_id(l, id_y=id_y, body_size=body_size):
            continue
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if _looks_like_technical_annotation_text(t):
            continue
        cand = _clean_label(t)
        if not cand:
            continue
        if len(cand) <= 3 and _text_quality(cand) < 0.45:
            continue
        key = (x0 - id_x1, abs(y0 - id_y), -len(cand))
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
        y_min=id_y - (y_band * 1.7),
        y_max=id_y + (y_band * 1.7),
        id_y=id_y,
    )
    if not stitched or len(stitched) <= 2:
        return None
    return stitched


def _find_left_column_label(
    lines,
    id_y: float,
    body_size: float,
    left_margin: float,
    headers_present: bool,
    header_buckets: set,
) -> Optional[str]:
    y_window = 450.0
    size_lo = body_size - 2.9
    size_hi = body_size + 3.0
    x_hi = left_margin + 160.0

    best = None
    best_key = None

    for l in lines:
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
        if _line_is_header_like_for_id(l, id_y=id_y, body_size=body_size):
            continue
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if _looks_like_technical_annotation_text(t):
            continue
        cand = _clean_label(t)
        if not cand:
            continue
        if len(cand) <= 3 and _text_quality(cand) < 0.45:
            continue
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
        y_min=float(getattr(best, "y0", 0.0) or 0.0) - (max(18.0, body_size * 2.2) * 2.35),
        y_max=id_y + 6.0,
        id_y=id_y,
    )
    if not stitched or len(stitched) <= 2:
        return None
    return stitched


def _find_below_leftish_label(
    lines,
    id_y: float,
    body_size: float,
    left_margin: float,
    headers_present: bool,
    header_buckets: set,
    id_x0: float,
) -> Optional[str]:
    y_window = 235.0
    size_lo = body_size - 2.9
    size_hi = body_size + 3.1

    x_anchor = id_x0 if id_x0 <= (left_margin + 140.0) else left_margin
    x_lo = max(0.0, x_anchor - 55.0)
    x_hi = x_anchor + 190.0

    best = None
    best_key = None

    for l in lines:
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
        if _line_is_header_like_for_id(l, id_y=id_y, body_size=body_size):
            continue
        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if _looks_like_technical_annotation_text(t):
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
        id_y=id_y,
    )
    if not stitched or len(stitched) <= 2:
        return None
    return stitched


def _find_row_context(lines, id_y: float, body_size: float, left_margin: float, header_buckets: set, id_x: float) -> Optional[str]:
    # Find a row-item label near the id's row band (often left-ish). Avoid table header rows.
    y_lo = id_y - 100.0
    y_hi = id_y + 35.0
    x_cut = max(300.0, left_margin + 250.0)

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
        if float(getattr(l, "size", 0.0) or 0.0) >= body_size + 4.0 and y0 <= 260.0:
            continue
        if _line_is_header_like_for_id(l, id_y=id_y, body_size=body_size):
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        x1 = float(getattr(l, "x1", x0) or x0)
        xc = 0.5 * (x0 + x1)

        if x0 > x_cut and abs(xc - id_x) > 90.0:
            continue

        t = (getattr(l, "text", "") or "").strip()
        if not t:
            continue
        if _looks_like_technical_annotation_text(t):
            continue
        cand = _clean_label(t)
        if not cand:
            continue
        if len(cand) <= 4 and _text_quality(cand) < 0.45:
            continue

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
        y_min=id_y - (max(18.0, body_size * 2.2) * 1.85),
        y_max=id_y + (max(18.0, body_size * 2.2) * 1.35),
        id_y=id_y,
    )
    if not stitched or len(stitched) <= 2:
        return None
    return stitched


def _field_name_for_id(
    lines,
    id_idx: int,
    id_indices_by_y,
    headers,
    local_headers,
    body_size: float,
    left_margin: float,
    header_buckets: set,
    header_usage: Dict[str, int],
    choice_anchor_headers: set,
    inline_label_hint: Optional[str],
) -> Optional[str]:
    id_line = lines[id_idx]
    id_y = float(getattr(id_line, "y0", 0.0) or 0.0)
    id_x0 = float(getattr(id_line, "x0", 0.0) or 0.0)
    id_x1 = float(getattr(id_line, "x1", id_x0) or id_x0)
    id_xc = 0.5 * (id_x0 + id_x1)

    headers_present = bool(headers)
    col_header = _header_for_x(headers, id_xc) if headers_present else None

    local_col_header = _header_for_x(local_headers, id_xc) if local_headers else None
    if local_col_header and id_y > 220.0:
        col_header = local_col_header

    # Determine if this id shares a "row" with other ids (multi-column response).
    multi_col = False
    y_bucket = int(id_y / 3.0)
    sibs = []
    for bb in (y_bucket - 1, y_bucket, y_bucket + 1):
        sibs.extend(id_indices_by_y.get(bb, []))
    if len(sibs) >= 2:
        xs = [float(getattr(lines[k], "x0", 0.0) or 0.0) for k in sibs]
        if max(xs) - min(xs) > 80.0:
            multi_col = True

    base = None
    if inline_label_hint:
        base = _clean_label(inline_label_hint)

    if not base:
        same_row = _find_same_row_left_label(lines, id_y, body_size, left_margin, header_buckets, id_xc)
        left_label = _find_left_column_label(lines, id_y, body_size, left_margin, headers_present, header_buckets)
        row_label = _find_row_context(lines, id_y, body_size, left_margin, header_buckets, id_xc)
        below_label = _find_below_leftish_label(lines, id_y, body_size, left_margin, headers_present, header_buckets, id_x0)
        right_same_row = _find_same_row_right_label(lines, id_y, body_size, header_buckets, id_x1)

        base = same_row or left_label or row_label or below_label or right_same_row

    # Decide whether a column header should be appended.
    header_ok = False
    if col_header:
        ch = _clean_label(col_header)
        if ch and (not _looks_like_technical_annotation_text(ch)) and (not _BRACKET_RE.match(ch)):
            if _SHORT_QUAL_HDR_RE.match(ch):
                header_ok = True
            else:
                # Do not append choice/rating anchors ("Normal", "Abnormal", "Yes/No", etc.).
                if ch not in choice_anchor_headers:
                    header_ok = True

    field = None
    if base:
        if header_ok and (multi_col or id_x0 >= (left_margin + 190.0)):
            field = _clean_label(f"{base} - {col_header}")
        else:
            field = _clean_label(base)

        # If multi-col and header exists but wasn't appended, add it when it adds information.
        if field and header_ok and multi_col and col_header and (col_header not in field) and id_x0 >= (left_margin + 175.0):
            field = _clean_label(f"{field} - {col_header}")
    else:
        # Header-only fallback: extremely conservative to prevent emitting anchors/headers as fields.
        if col_header and id_y <= 240.0:
            ch = _clean_label(col_header)
            if ch and (not _looks_like_technical_annotation_text(ch)) and (not _BRACKET_RE.match(ch)):
                use_count = int(header_usage.get(ch, 0) or 0)
                # Require "field-like" header text (not single short anchor).
                if use_count <= 1 and (len(ch) >= 10 or (" " in ch)) and (ch not in choice_anchor_headers):
                    field = _clean_label(ch)

    if not field:
        return None
    if len(field) <= 2:
        return None

    q = _text_quality(field)
    if q < 0.12 and len(field) <= 10:
        return None
    if _PAGE_FOOTER_RE.match(field.strip()):
        return None
    if _looks_like_technical_annotation_text(field):
        return None
    if _BRACKET_RE.match(field.strip()):
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

        title = _detect_form_title(lines, body_size, left_margin)
        if title:
            current_form = title

        headers = _build_header_blocks(lines, body_size)

        # Collect field IDs:
        # - standalone ID lines: "[ABC123]"
        # - inline IDs: "Label ... [ABC123]"
        id_idxs: List[int] = []
        id_inline_hint: Dict[int, str] = {}
        id_buckets = set()

        for i, l in enumerate(lines):
            t = (getattr(l, "text", "") or "").strip()
            if not t:
                continue
            if _is_field_id_line(l):
                id_idxs.append(i)
                y0 = float(getattr(l, "y0", 0.0) or 0.0)
                id_buckets.add(_y_bucket(y0, 3.0))
                continue

            hint = _inline_id_label_hint(t)
            if hint:
                id_idxs.append(i)
                id_inline_hint[i] = hint
                y0 = float(getattr(l, "y0", 0.0) or 0.0)
                id_buckets.add(_y_bucket(y0, 3.0))

        if not id_idxs:
            continue

        # Detect table header rows (avoid mislabeling header cells as fields).
        header_row_buckets = _detect_table_header_buckets(lines, body_size, id_buckets, id_idxs, left_margin)

        # Bucket ids by y to detect multi-column rows.
        id_indices_by_y: Dict[int, List[int]] = {}
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
                    hh = _clean_label(h)
                    if hh:
                        header_usage[hh] = header_usage.get(hh, 0) + 1

        # Choice anchor headers: short headers repeated across many ids.
        choice_anchor_headers = set()
        for htxt, cnt in header_usage.items():
            if cnt >= 3 and _looks_like_choice_anchor_header_text(htxt):
                choice_anchor_headers.add(htxt)

        for idx in id_idxs:
            # Skip read-only fields (column-aware marker check).
            if _id_has_read_only_marker(lines, idx):
                continue

            id_line = lines[idx]
            id_y = float(getattr(id_line, "y0", 0.0) or 0.0)

            # Build local headers for mid-page grids near this id.
            local_headers = _find_local_header_blocks(lines, id_y=id_y, body_size=body_size, id_buckets=id_buckets)

            # Also treat repeated short local headers as choice anchors (so we don't append them).
            local_choice_anchors = set()
            if local_headers:
                # local_headers is a list of blocks with "text"
                counts: Dict[str, int] = {}
                for b in local_headers:
                    txt = _clean_label(b.get("text", "") or "")
                    if txt:
                        counts[txt] = counts.get(txt, 0) + 1
                for t, c in counts.items():
                    if c >= 2 and _looks_like_choice_anchor_header_text(t):
                        local_choice_anchors.add(t)

            field_name = _field_name_for_id(
                lines=lines,
                id_idx=idx,
                id_indices_by_y=id_indices_by_y,
                headers=headers,
                local_headers=local_headers,
                body_size=body_size,
                left_margin=left_margin,
                header_buckets=header_row_buckets,
                header_usage=header_usage,
                choice_anchor_headers=(choice_anchor_headers | local_choice_anchors),
                inline_label_hint=id_inline_hint.get(idx),
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
