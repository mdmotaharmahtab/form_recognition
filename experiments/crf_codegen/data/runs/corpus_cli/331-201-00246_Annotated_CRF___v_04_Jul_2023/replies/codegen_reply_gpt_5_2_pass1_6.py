```python
import re
import statistics
import unicodedata
from typing import Any, Dict, List, Optional, Tuple


# ----------------------------
# Low-level helpers (dict/obj)
# ----------------------------
def _get(o: Any, k: str, default: Any = None) -> Any:
    if o is None:
        return default
    if isinstance(o, dict):
        return o.get(k, default)
    return getattr(o, k, default)


def _txt(o: Any) -> str:
    return (_get(o, "text", "") or "").strip()


def _f(o: Any, k: str, default: float = 0.0) -> float:
    try:
        v = _get(o, k, default)
        if v is None:
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _b(o: Any, k: str, default: bool = False) -> bool:
    try:
        v = _get(o, k, default)
        return bool(v)
    except Exception:
        return bool(default)


# ---------------------------------
# Regexes + text normalization
# ---------------------------------
_ID_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_ID_LINE_RE = re.compile(r"^\s*\[[A-Za-z0-9][A-Za-z0-9_-]*\]\s*[:;]?\s*$")
_BRACKET_RE = re.compile(r"^\s*\[.*\]\s*$")
_PAGE_FOOTER_RE = re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)
_INLINE_ID_TOKEN_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9_-]*)\]")
_TECH_BRACKET_PREFIX_RE = re.compile(r"^\s*\[([^\]]{2,250})\]\s*")
_TRAILING_ID_TOKEN_RE = re.compile(r"\s*\[[A-Za-z0-9][A-Za-z0-9_-]*\]\s*$")
_TITLE_PAGE_SUFFIX_RE = re.compile(r"(\s*[-–—]\s*)?Page\s+\d+(\s*(of|/)\s*\d+)?\s*$", re.IGNORECASE)
_SHORT_QUAL_HDR_RE = re.compile(r"^\s*#?\s*\d+\s*$")


def _norm_space(s: str) -> str:
    return " ".join((s or "").split())


def _strip_leading_ordinals(s: str) -> str:
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

    if _BRACKET_RE.match(tt):
        inner = tt.strip()[1:-1].strip().lower()
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
    if ("type:" in low) or ("values:" in low) or ("enumeration" in low and "values" in low):
        return True
    if ("read-only" in low) or ("readonly" in low) or ("read only" in low):
        return True
    if "format:" in low:
        return True
    return False


def _strip_technical_bracket_prefixes(s: str) -> str:
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

    s = _TRAILING_ID_TOKEN_RE.sub("", s).strip()
    s = s.strip(":-").strip()

    if _BRACKET_RE.match(s.strip()) and _looks_like_technical_annotation_text(s.strip()):
        return ""
    return s


def _median(vals: List[float], default: float) -> float:
    vals = [v for v in vals if v is not None]
    if not vals:
        return default
    try:
        return float(statistics.median(vals))
    except Exception:
        vals2 = sorted(vals)
        return float(vals2[len(vals2) // 2])


def _y_bucket(y: float, step: float = 3.0) -> int:
    try:
        return int(float(y) / step)
    except Exception:
        return 0


def _looks_like_unit_token(tok: str) -> bool:
    t = (tok or "").strip()
    if not t:
        return True
    # Conservative: treat short alphabetic bracket tokens as units, not IDs.
    if len(t) <= 6 and t.isalpha() and not any(ch.isdigit() for ch in t):
        return True
    return False


# ---------------------------------
# ID detection (line + inline)
# ---------------------------------
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
    tok = inner[1:-1].strip()
    if not _ID_TOKEN_RE.match(tok):
        return False
    low = tok.lower()
    if low in ("type", "read-only", "readonly"):
        return False
    if _looks_like_unit_token(tok):
        return False
    # Keep IDs mostly code-like; inline IDs elsewhere typically contain digits/_/-
    if not any(ch.isdigit() for ch in tok) and ("_" not in tok) and ("-" not in tok) and len(tok) <= 8:
        return False
    return True


def _is_field_id_line(line: Any) -> bool:
    return _is_field_id_text(_txt(line))


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
        if _looks_like_unit_token(tok):
            continue
        # Strongly prefer code-like inline IDs.
        if not any(ch.isdigit() for ch in tok) and ("_" not in tok) and ("-" not in tok):
            continue
        yield tok


def _inline_id_label_hint(t: str) -> Optional[str]:
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

    stripped = _INLINE_ID_TOKEN_RE.sub("", tt)
    cand = _clean_label(stripped)
    if not cand:
        return None
    if len(cand) <= 2:
        return None
    if _text_quality(cand) < 0.18 and len(cand) <= 10:
        return None
    return cand


# ---------------------------------
# Page-scale detection
# ---------------------------------
def _detect_body_size(lines: List[Any]) -> float:
    sizes = []
    for l in lines:
        t = _txt(l)
        if not t:
            continue
        if _b(l, "non_black", False):
            continue
        sz = _f(l, "size", 0.0)
        if 6.0 <= sz <= 12.8:
            sizes.append(sz)
    return _median(sizes, 9.0)


def _detect_left_margin(lines: List[Any], body_size: float) -> float:
    xs = []
    for l in lines:
        t = _txt(l)
        if not t:
            continue
        if _b(l, "non_black", False):
            continue
        if _is_field_id_line(l):
            continue
        sz = _f(l, "size", 0.0)
        if sz > body_size + 1.3:
            continue
        x0 = _f(l, "x0", 0.0)
        y0 = _f(l, "y0", 0.0)
        if 35.0 <= x0 <= 170.0 and 85.0 <= y0 <= 745.0:
            xs.append(x0)
    return _median(xs, 64.0)


# ---------------------------------
# Skips / header-like detection
# ---------------------------------
def _is_bracket_meta(line: Any) -> bool:
    t = _txt(line)
    return bool(_BRACKET_RE.match(t))


def _is_skippable_text_line(line: Any) -> bool:
    t = _txt(line)
    if not t:
        return True
    if _PAGE_FOOTER_RE.match(t):
        return True
    if _is_bracket_meta(line):
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
    if len(tt) > 14:
        return False
    if any(ch.isdigit() for ch in tt):
        return False
    toks = tt.split()
    if len(toks) > 2:
        return False
    if _text_quality(tt) < 0.25:
        return False
    return True


def _line_is_header_like_for_id(line: Any, id_y: float, body_size: float) -> bool:
    if line is None:
        return False
    t0 = _txt(line)
    if not t0:
        return False
    if _is_field_id_line(line):
        return False
    if _PAGE_FOOTER_RE.match(t0) or _looks_like_technical_annotation_text(t0) or _BRACKET_RE.match(t0):
        return True

    y0 = _f(line, "y0", 0.0)
    # If it's above the data row even slightly, allow header classification.
    if y0 >= id_y - max(0.8, body_size * 0.18):
        return False

    sz = _f(line, "size", 0.0)
    tt = _clean_label(t0)
    if not tt:
        return True

    # Header-ish typography + short content, no digits.
    if sz >= body_size + 0.55 and len(tt) <= 16 and not any(ch.isdigit() for ch in tt):
        if len(tt.split()) <= 3:
            return True
    return False


# ---------------------------------
# Header blocks (for stripping prefixes)
# ---------------------------------
def _build_header_blocks_from_lines(header_lines: List[Any], body_size: float) -> List[Dict[str, Any]]:
    header_lines = list(header_lines or [])
    header_lines.sort(key=lambda z: (_f(z, "x0", 0.0), _f(z, "y0", 0.0)))

    blocks: List[Dict[str, Any]] = []
    for l in header_lines:
        placed = False
        lx0, lx1 = _f(l, "x0", 0.0), _f(l, "x1", _f(l, "x0", 0.0))
        for b in blocks:
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
        b["lines"].sort(key=lambda z: (_f(z, "y0", 0.0), _f(z, "x0", 0.0)))
        raw = " ".join(_txt(ln) for ln in b["lines"] if _txt(ln))
        if not raw:
            continue
        if _looks_like_technical_annotation_text(raw):
            continue
        txt = _clean_label(raw)
        if not txt:
            continue
        if _looks_like_technical_annotation_text(txt):
            continue
        if _BRACKET_RE.match(txt.strip()):
            continue

        if len(txt) <= 2:
            if not _SHORT_QUAL_HDR_RE.match(txt):
                continue
        if len(txt) <= 6 and _text_quality(txt) < 0.2:
            if not _SHORT_QUAL_HDR_RE.match(txt):
                continue

        out.append(
            {"x0": b["x0"], "x1": b["x1"], "x_center": 0.5 * (b["x0"] + b["x1"]), "text": txt}
        )

    out.sort(key=lambda z: z["x_center"])
    return out


def _find_local_header_blocks(lines: List[Any], id_y: float, body_size: float, id_buckets: set) -> List[Dict[str, Any]]:
    y_top = max(80.0, id_y - 175.0)
    y_bot = id_y - 6.0
    if y_bot <= y_top:
        return []

    cand_buckets: Dict[int, List[Any]] = {}
    for l in lines:
        if _is_skippable_text_line(l) or _is_field_id_line(l):
            continue
        y0 = _f(l, "y0", 0.0)
        if not (y_top <= y0 <= y_bot):
            continue

        b = _y_bucket(y0, 3.0)
        if b in id_buckets:
            continue

        sz = _f(l, "size", 0.0)
        non_black = _b(l, "non_black", False)
        if non_black:
            if sz < body_size + 0.1:
                continue
        else:
            if sz < body_size + 0.3:
                continue

        t = _txt(l)
        if not t or _looks_like_technical_annotation_text(t) or _is_bracket_meta(l) or _PAGE_FOOTER_RE.match(t):
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
            x0 = _f(l, "x0", 0.0)
            x1 = _f(l, "x1", x0)
            xcs.append(0.5 * (x0 + x1))
            ys.append(_f(l, "y0", 0.0))
        if not xcs or (max(xcs) - min(xcs)) < 155.0:
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


def _header_for_x(headers: List[Dict[str, Any]], x: float) -> Optional[str]:
    if not headers:
        return None
    best = None
    best_d = 1e18
    for h in headers:
        d = abs(float(h["x_center"]) - float(x))
        if d < best_d:
            best_d = d
            best = h
    if best is None or best_d > 130.0:
        return None
    txt = (best.get("text") or "").strip()
    if not txt:
        return None
    if _looks_like_technical_annotation_text(txt) or _BRACKET_RE.match(txt):
        return None
    return txt


def _strip_leading_header_prefix(label: str, hdr: Optional[str]) -> str:
    if not label or not hdr:
        return label
    a = _norm_space(label).strip()
    h = _norm_space(hdr).strip()
    if not a or not h:
        return label

    al = a.lower()
    hl = h.lower()
    if al.startswith(hl + " "):
        return _clean_label(a[len(h) :].strip())
    if al.startswith(hl + ":"):
        return _clean_label(a[len(h) + 1 :].strip())
    if al.startswith(hl + " - "):
        return _clean_label(a[len(h) + 3 :].strip())
    return label


# ---------------------------------
# Label stitching / searching
# ---------------------------------
def _stitch_wrapped_lines(
    lines: List[Any],
    seed: Any,
    body_size: float,
    x_ref: float,
    header_buckets: set,
    y_min: float,
    y_max: float,
    id_y: Optional[float] = None,
) -> str:
    if seed is None:
        return ""

    size_lo = body_size - 2.6
    size_hi = body_size + 2.6
    line_gap = max(18.0, body_size * 2.35)

    seed_y = _f(seed, "y0", 0.0)
    seed_x0 = _f(seed, "x0", 0.0)
    seed_sz = _f(seed, "size", 0.0)
    iy = float(id_y) if (id_y is not None) else seed_y

    cands = []
    for l in lines:
        if _is_skippable_text_line(l) or _is_field_id_line(l):
            continue
        y0 = _f(l, "y0", 0.0)
        if y0 < y_min or y0 > y_max:
            continue
        if _y_bucket(y0, 3.0) in header_buckets:
            continue
        if _line_is_header_like_for_id(l, id_y=iy, body_size=body_size):
            continue

        x0 = _f(l, "x0", 0.0)
        if abs(x0 - x_ref) > 85.0 and abs(x0 - seed_x0) > 95.0:
            continue

        sz = _f(l, "size", 0.0)
        if not (size_lo <= sz <= size_hi) and abs(sz - seed_sz) > 1.6:
            continue

        t = _txt(l)
        if not t or _looks_like_technical_annotation_text(t):
            continue
        cands.append(l)

    if not cands:
        return _clean_label(_txt(seed))

    cands.sort(key=lambda z: (_f(z, "y0", 0.0), _f(z, "x0", 0.0)))
    cluster = [l for l in cands if abs(_f(l, "y0", 0.0) - seed_y) <= (line_gap * 1.25)]
    if not cluster:
        cluster = [seed]

    seen = set()
    uniq = []
    for l in cluster:
        if id(l) in seen:
            continue
        seen.add(id(l))
        uniq.append(l)

    uniq.sort(key=lambda z: (_f(z, "y0", 0.0), _f(z, "x0", 0.0)))

    kept = []
    prev_y = None
    for l in uniq:
        y0 = _f(l, "y0", 0.0)
        if prev_y is None or (y0 - prev_y) <= (line_gap * 1.05):
            kept.append(l)
            prev_y = y0

    parts = []
    for l in kept:
        t = _txt(l)
        if not t or _looks_like_technical_annotation_text(t):
            continue
        parts.append(t)

    return _clean_label(" ".join(parts))


def _find_same_row_left_label(
    lines: List[Any],
    id_y: float,
    body_size: float,
    left_margin: float,
    header_buckets: set,
    id_xc: float,
) -> Optional[Tuple[str, float]]:
    y_band = max(12.0, body_size * 1.45)
    size_lo = body_size - 2.9
    size_hi = body_size + 3.0

    # Allow further right in wide grids; must still be left of ID column.
    x_hi = max(left_margin + 250.0, min(left_margin + 650.0, id_xc - 8.0))

    best = None
    best_key = None

    for l in lines:
        if _is_skippable_text_line(l) or _is_field_id_line(l):
            continue
        y0 = _f(l, "y0", 0.0)
        if abs(y0 - id_y) > y_band:
            continue
        if _y_bucket(y0, 3.0) in header_buckets:
            continue
        x0 = _f(l, "x0", 0.0)
        if x0 > x_hi:
            continue
        sz = _f(l, "size", 0.0)
        if not (size_lo <= sz <= size_hi):
            continue
        if _line_is_header_like_for_id(l, id_y=id_y, body_size=body_size):
            continue

        t = _txt(l)
        if not t or _looks_like_technical_annotation_text(t):
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
        x_ref=_f(best, "x0", 0.0),
        header_buckets=header_buckets,
        y_min=id_y - (y_band * 1.8),
        y_max=id_y + (y_band * 1.8),
        id_y=id_y,
    )
    if not stitched or len(stitched) <= 2:
        return None
    return stitched, _f(best, "x0", 0.0)


def _find_same_row_right_label(
    lines: List[Any],
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
        if _is_skippable_text_line(l) or _is_field_id_line(l):
            continue
        y0 = _f(l, "y0", 0.0)
        if abs(y0 - id_y) > y_band:
            continue
        if _y_bucket(y0, 3.0) in header_buckets:
            continue
        x0 = _f(l, "x0", 0.0)
        if x0 <= id_x1 + 8.0:
            continue
        sz = _f(l, "size", 0.0)
        if not (size_lo <= sz <= size_hi):
            continue
        if _line_is_header_like_for_id(l, id_y=id_y, body_size=body_size):
            continue
        t = _txt(l)
        if not t or _looks_like_technical_annotation_text(t):
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
        x_ref=_f(best, "x0", 0.0),
        header_buckets=header_buckets,
        y_min=id_y - (y_band * 1.6),
        y_max=id_y + (y_band * 1.6),
        id_y=id_y,
    )
    if not stitched or len(stitched) <= 2:
        return None
    return stitched


def _find_above_same_column_label(
    lines: List[Any],
    id_y: float,
    id_x0: float,
    id_x1: float,
    body_size: float,
    header_buckets: set,
) -> Optional[str]:
    y_top = max(75.0, id_y - 165.0)
    y_bot = id_y - 6.0
    if y_bot <= y_top:
        return None

    size_lo = body_size - 2.8
    size_hi = body_size + 3.2

    best = None
    best_key = None
    for l in lines:
        if _is_skippable_text_line(l) or _is_field_id_line(l):
            continue
        y0 = _f(l, "y0", 0.0)
        if y0 < y_top or y0 > y_bot:
            continue
        if _y_bucket(y0, 3.0) in header_buckets:
            continue

        x0 = _f(l, "x0", 0.0)
        x1 = _f(l, "x1", x0)
        # Require some horizontal overlap with the ID cell/column.
        if x1 < id_x0 - 18.0 or x0 > id_x1 + 18.0:
            continue

        sz = _f(l, "size", 0.0)
        if not (size_lo <= sz <= size_hi):
            continue

        if _line_is_header_like_for_id(l, id_y=id_y, body_size=body_size):
            continue

        t = _txt(l)
        if not t or _looks_like_technical_annotation_text(t):
            continue
        cand = _clean_label(t)
        if not cand:
            continue

        key = (id_y - y0, -len(cand))
        if best_key is None or key < best_key:
            best = l
            best_key = key

    if best is None:
        return None

    stitched = _stitch_wrapped_lines(
        lines=lines,
        seed=best,
        body_size=body_size,
        x_ref=_f(best, "x0", 0.0),
        header_buckets=header_buckets,
        y_min=max(70.0, _f(best, "y0", 0.0) - (max(18.0, body_size * 2.2) * 1.9)),
        y_max=id_y - 6.0,
        id_y=id_y,
    )
    if not stitched or len(stitched) <= 2:
        return None
    return stitched


def _find_row_context(
    lines: List[Any],
    id_y: float,
    body_size: float,
    left_margin: float,
    header_buckets: set,
    id_x: float,
) -> Optional[str]:
    y_lo = id_y - 95.0
    y_hi = id_y + 35.0
    x_cut = max(300.0, left_margin + 260.0)

    best_line = None
    best_key = None

    for l in lines:
        if _is_skippable_text_line(l) or _is_field_id_line(l):
            continue
        y0 = _f(l, "y0", 0.0)
        if not (y_lo <= y0 <= y_hi):
            continue
        if _y_bucket(y0, 3.0) in header_buckets:
            continue
        if _line_is_header_like_for_id(l, id_y=id_y, body_size=body_size):
            continue

        x0 = _f(l, "x0", 0.0)
        x1 = _f(l, "x1", x0)
        xc = 0.5 * (x0 + x1)

        if x0 > x_cut and abs(xc - id_x) > 90.0:
            continue

        t = _txt(l)
        if not t or _looks_like_technical_annotation_text(t):
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
        x_ref=_f(best_line, "x0", 0.0),
        header_buckets=header_buckets,
        y_min=id_y - (max(18.0, body_size * 2.2) * 1.75),
        y_max=id_y + (max(18.0, body_size * 2.2) * 1.35),
        id_y=id_y,
    )
    if not stitched or len(stitched) <= 2:
        return None
    return stitched


# ---------------------------------
# Table header bucket detection (conservative)
# ---------------------------------
def _detect_table_header_buckets(
    lines: List[Any], body_size: float, id_buckets: set, id_idxs: List[int], left_margin: float
) -> set:
    buckets: Dict[int, List[Any]] = {}
    for l in lines:
        if _is_skippable_text_line(l) or _is_field_id_line(l):
            continue
        y0 = _f(l, "y0", 0.0)
        if not (85.0 <= y0 <= 735.0):
            continue

        sz = _f(l, "size", 0.0)
        non_black = _b(l, "non_black", False)
        if non_black:
            if sz < body_size + 0.2:
                continue
        else:
            if sz < body_size + 0.55:
                continue

        t = _txt(l)
        if not t or _looks_like_technical_annotation_text(t):
            continue

        b = _y_bucket(y0, 3.0)
        buckets.setdefault(b, []).append(l)

    header_buckets = set()

    # Estimate whether this page really has multi-column ID structure.
    id_xcs = []
    for idx in id_idxs:
        l = lines[idx]
        x0 = _f(l, "x0", 0.0)
        x1 = _f(l, "x1", x0)
        id_xcs.append(0.5 * (x0 + x1))
    id_spread = (max(id_xcs) - min(id_xcs)) if id_xcs else 0.0

    for b, ls in buckets.items():
        if b in id_buckets:
            continue
        # Require that header-like row is actually multi-column (x spread).
        xcs = []
        for l in ls:
            x0 = _f(l, "x0", 0.0)
            x1 = _f(l, "x1", x0)
            xcs.append(0.5 * (x0 + x1))
        if len(xcs) >= 2 and (max(xcs) - min(xcs)) >= 170.0:
            header_buckets.add(b)

    # Neighbor support: mark b if its neighbor row completes a multi-column header.
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
            x0 = _f(l, "x0", 0.0)
            x1 = _f(l, "x1", x0)
            xcs.append(0.5 * (x0 + x1))
        if not xcs or (max(xcs) - min(xcs)) < 190.0:
            continue
        for bb in (b - 1, b, b + 1):
            if bb in buckets and bb not in id_buckets:
                header_buckets.add(bb)

    # Single-cell header rows only if page is clearly multi-column, the cell is short and anchor-like,
    # and it sits above IDs.
    if id_spread >= 220.0:
        id_buckets_list = sorted(list(id_buckets)) if id_buckets else []
        for b, ls in buckets.items():
            if b in id_buckets:
                continue
            if len(ls) != 1:
                continue
            l = ls[0]
            t = _txt(l)
            if not t:
                continue

            has_ids_below = False
            for ib in id_buckets_list:
                if 1 <= (ib - b) <= 28:
                    has_ids_below = True
                    break
            if not has_ids_below:
                continue

            x0 = _f(l, "x0", 0.0)
            if x0 <= left_margin + 40.0 and len(_clean_label(t)) > 18:
                continue

            if _looks_like_choice_anchor_header_text(t):
                header_buckets.add(b)

    return header_buckets


# ---------------------------------
# Title detection + segmentation
# ---------------------------------
def _clean_form_title(t: str) -> str:
    tt = _clean_label(t or "")
    tt = _TITLE_PAGE_SUFFIX_RE.sub("", tt).strip()
    tt = tt.rstrip("-–—:").strip()
    return tt


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


def _find_title_candidates(lines: List[Any], body_size: float, left_margin: float, y_cap: float) -> List[Dict[str, Any]]:
    cands = []
    for l in lines:
        t = _txt(l)
        if not t:
            continue
        y0 = _f(l, "y0", 0.0)
        if y0 > y_cap:
            continue

        if not _looks_like_title_text(t):
            continue

        x0 = _f(l, "x0", 0.0)
        if x0 > left_margin + 260.0:
            continue

        sz = _f(l, "size", 0.0)
        non_black = _b(l, "non_black", False)
        # Titles are typically noticeably larger or colored.
        if non_black:
            if sz < body_size + 1.2:
                continue
        else:
            if sz < body_size + 1.8:
                continue

        cands.append(
            {
                "line": l,
                "y0": y0,
                "x0": x0,
                "size": sz,
                "non_black": 1 if non_black else 0,
                "text": t,
            }
        )
    # Sort top-to-bottom, then left-to-right
    cands.sort(key=lambda z: (z["y0"], z["x0"], -z["size"], -z["non_black"]))
    return cands


def _merge_title_blocks(cands: List[Dict[str, Any]], body_size: float) -> List[Dict[str, Any]]:
    if not cands:
        return []

    merged = []
    i = 0
    max_gap = max(18.0, body_size * 2.4)

    while i < len(cands):
        base = cands[i]
        parts = [base["text"]]
        y0 = base["y0"]
        x0 = base["x0"]
        size = base["size"]
        non_black = base["non_black"]

        j = i + 1
        last_y = y0
        while j < len(cands):
            cj = cands[j]
            # Same title block if close vertically and roughly aligned.
            if cj["y0"] < y0:
                j += 1
                continue
            if (cj["y0"] - y0) > (max_gap * 2.8):
                break
            if abs(cj["x0"] - x0) > 220.0:
                break
            if abs(cj["size"] - size) > 3.2:
                break
            if (cj["y0"] - last_y) > (max_gap * 1.55):
                break
            parts.append(cj["text"])
            last_y = cj["y0"]
            j += 1

        title = _clean_form_title(" ".join(parts))
        if title and len(title) > 2:
            merged.append(
                {
                    "y0": y0,
                    "x0": x0,
                    "size": size,
                    "non_black": non_black,
                    "title": title,
                }
            )
        i = j

    # Deduplicate near-identical titles at same y (rare overlap).
    out = []
    seen = set()
    for m in merged:
        key = (round(m["y0"] / 2.0), m["title"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    out.sort(key=lambda z: z["y0"])
    return out


def _choose_form_for_y(title_blocks: List[Dict[str, Any]], y: float) -> Optional[str]:
    if not title_blocks:
        return None
    best = None
    best_d = None
    for tb in title_blocks:
        if tb["y0"] >= y - 6.0:
            continue
        d = y - tb["y0"]
        if d < 0:
            continue
        # Keep it reasonably close: avoid grabbing titles from far above unrelated sections.
        if d > 620.0:
            continue
        if best_d is None or d < best_d:
            best = tb["title"]
            best_d = d
    return best


# ---------------------------------
# Field naming for an ID anchor
# ---------------------------------
def _field_name_for_anchor(
    lines: List[Any],
    anchor_idx: int,
    id_indices_by_y: Dict[int, List[int]],
    body_size: float,
    left_margin: float,
    header_buckets: set,
    id_buckets: set,
    inline_label_hint: Optional[str],
) -> Optional[Tuple[str, float, float]]:
    anchor = lines[anchor_idx]
    id_y = _f(anchor, "y0", 0.0)
    id_x0 = _f(anchor, "x0", 0.0)
    id_x1 = _f(anchor, "x1", id_x0)
    id_xc = 0.5 * (id_x0 + id_x1)

    # Determine if multi-column response row (siblings at same y).
    multi_col = False
    yb = _y_bucket(id_y, 3.0)
    sibs = []
    for bb in (yb - 1, yb, yb + 1):
        sibs.extend(id_indices_by_y.get(bb, []))
    if len(sibs) >= 2:
        xs = [_f(lines[k], "x0", 0.0) for k in sibs]
        if xs and (max(xs) - min(xs)) > 80.0:
            multi_col = True

    local_headers = _find_local_header_blocks(lines, id_y, body_size, id_buckets)
    col_header = _header_for_x(local_headers, id_xc) if local_headers else None

    # Find row header for the left-most label column and for this ID column.
    row_label_x0 = None
    row_hdr = None

    # Primary: inline hint.
    base = _clean_label(inline_label_hint or "")
    if base:
        # Strip this column header if it accidentally prefixes the label text.
        if col_header:
            base = _strip_leading_header_prefix(base, col_header)

    # Then: same-row left label (preferred for grids like HEENT/Skin).
    if not base:
        same_left = _find_same_row_left_label(lines, id_y, body_size, left_margin, header_buckets, id_xc)
        if same_left:
            base, row_label_x0 = same_left
            # If the left column has a header (e.g. "Region/Body System"), strip it.
            if local_headers and row_label_x0 is not None:
                row_hdr = _header_for_x(local_headers, row_label_x0 + 8.0)
                if row_hdr:
                    base = _strip_leading_header_prefix(base, row_hdr)

    # Right label (common when ID is left of a free-text box label).
    if not base:
        base = _clean_label(_find_same_row_right_label(lines, id_y, body_size, header_buckets, id_x1) or "")

    # Above-in-column label (ID printed below its label).
    if not base:
        base = _clean_label(_find_above_same_column_label(lines, id_y, id_x0, id_x1, body_size, header_buckets) or "")

    # Row context fallback.
    if not base:
        base = _clean_label(_find_row_context(lines, id_y, body_size, left_margin, header_buckets, id_xc) or "")
        if base and col_header:
            # If this is a row-header + row-label stitch like "Test Amphetamines", strip it.
            base = _strip_leading_header_prefix(base, col_header)

    if not base:
        return None

    # Avoid using column headers / anchors as the field label itself.
    if col_header:
        if base.strip().lower() == col_header.strip().lower():
            return None
        if _looks_like_choice_anchor_header_text(base) and len(base) <= 14:
            return None

    # For multi-column rows: only append header when it's a disambiguating qualifier (numeric, or contains digits).
    if multi_col and col_header:
        ch = _clean_label(col_header)
        if ch and not _looks_like_choice_anchor_header_text(ch):
            if _SHORT_QUAL_HDR_RE.match(ch) or any(c.isdigit() for c in ch):
                base2 = _clean_label(base)
                if base2 and base2.lower() != ch.lower():
                    base = _clean_label(f"{base2} - {ch}")

    # Final guardrails against accidental header-row captures.
    if not base or len(base) <= 2:
        return None
    if len(base) <= 6 and _text_quality(base) < 0.22 and not _SHORT_QUAL_HDR_RE.match(base):
        return None

    return base, id_y, id_xc


# ---------------------------------
# extract(pages)
# ---------------------------------
def extract(pages: List[Any]) -> List[Dict[str, str]]:
    def _page_lines(page: Any) -> List[Any]:
        if page is None:
            return []
        for key in ("lines", "text_lines", "items", "spans", "elements"):
            v = _get(page, key, None)
            if isinstance(v, list):
                return v
        if isinstance(page, list):
            return page
        return []

    def _page_num(page: Any, idx: int) -> int:
        for k in ("page_num", "page_number", "number", "pageIndex", "index"):
            v = _get(page, k, None)
            if v is None:
                continue
            try:
                n = int(v)
                if n >= 1:
                    return n
            except Exception:
                pass
        return idx + 1

    records: List[Dict[str, str]] = []
    last_form: Optional[str] = None

    for pi, page in enumerate(pages or []):
        lines = list(_page_lines(page) or [])
        if not lines:
            continue

        # Stable sort: by y then x, so neighbor scans work.
        lines.sort(key=lambda z: (_f(z, "y0", 0.0), _f(z, "x0", 0.0)))

        body_size = _detect_body_size(lines)
        left_margin = _detect_left_margin(lines, body_size)

        # Anchor indices: explicit ID lines.
        id_idxs = [i for i, l in enumerate(lines) if _is_field_id_line(l)]
        id_buckets = set(_y_bucket(_f(lines[i], "y0", 0.0), 3.0) for i in id_idxs)

        # Inline ID anchors: treat the same line as anchor (so we can pick same-row text).
        inline_anchors: List[Tuple[int, str, Optional[str]]] = []
        for i, l in enumerate(lines):
            t = _txt(l)
            if not t or _is_skippable_text_line(l) or _is_field_id_line(l):
                continue
            toks = list(_iter_inline_id_tokens(t))
            if not toks:
                continue
            hint = _inline_id_label_hint(t)
            # Keep one anchor per line (most common); multiple tokens tend to be technical noise.
            inline_anchors.append((i, toks[0], hint))

        # Build y-bucket index for anchors (ID lines + inline anchors).
        anchor_idxs = sorted(set(id_idxs + [i for (i, _, _) in inline_anchors]))
        id_indices_by_y: Dict[int, List[int]] = {}
        for i in anchor_idxs:
            y = _f(lines[i], "y0", 0.0)
            id_indices_by_y.setdefault(_y_bucket(y, 3.0), []).append(i)

        # Header buckets (for excluding column headers from label stitches).
        header_buckets = _detect_table_header_buckets(lines, body_size, id_buckets, id_idxs, left_margin)

        # Title candidates: look above first anchor (or top band if no anchors).
        first_anchor_y = min((_f(lines[i], "y0", 0.0) for i in anchor_idxs), default=260.0)
        y_cap = min(360.0, max(210.0, first_anchor_y - 4.0))
        title_cands = _find_title_candidates(lines, body_size, left_margin, y_cap=y_cap)
        title_blocks = _merge_title_blocks(title_cands, body_size)

        # If we didn't find anything above anchors, also look a bit further (some templates start lower).
        if not title_blocks and anchor_idxs:
            y_cap2 = min(520.0, max(260.0, first_anchor_y - 4.0))
            title_cands2 = _find_title_candidates(lines, body_size, left_margin, y_cap=y_cap2)
            title_blocks = _merge_title_blocks(title_cands2, body_size)

        # Update last_form from top-most title if present.
        page_top_form = title_blocks[0]["title"] if title_blocks else None
        if page_top_form:
            last_form = page_top_form

        # Map inline anchor hints for quick lookup.
        inline_hint_by_idx: Dict[int, Optional[str]] = {}
        for i, _tok, hint in inline_anchors:
            if i not in inline_hint_by_idx:
                inline_hint_by_idx[i] = hint

        page_no = _page_num(page, pi)
        seen_page = set()
        last_form_used_on_page = None

        for aidx in anchor_idxs:
            hint = inline_hint_by_idx.get(aidx)
            field = _field_name_for_anchor(
                lines=lines,
                anchor_idx=aidx,
                id_indices_by_y=id_indices_by_y,
                body_size=body_size,
                left_margin=left_margin,
                header_buckets=header_buckets,
                id_buckets=id_buckets,
                inline_label_hint=hint,
            )
            if not field:
                continue

            field_name, fy, _fx = field
            if not field_name:
                continue

            # Decide form name using nearest title block above this field; fallback to last_form.
            form = _choose_form_for_y(title_blocks, fy) or last_form
            if not form:
                continue

            # Final cleanups.
            form = _clean_form_title(form)
            field_name = _clean_label(field_name)

            if not form or not field_name:
                continue
            if len(field_name) <= 2:
                continue
            if _looks_like_choice_anchor_header_text(field_name) and len(field_name) <= 14:
                continue

            key = (form.lower(), field_name.lower(), round(fy / 3.0))
            if key in seen_page:
                continue
            seen_page.add(key)

            records.append({"form_name": form, "field_name": field_name})
            last_form_used_on_page = form

        # Persistence: carry forward the form actually used on this page (handles mid-page new forms).
        if last_form_used_on_page:
            last_form = last_form_used_on_page

    return records
```
