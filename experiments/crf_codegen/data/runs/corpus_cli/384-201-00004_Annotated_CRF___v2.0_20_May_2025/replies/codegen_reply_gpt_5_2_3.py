```python
import re
from collections import Counter
from statistics import median

_WS_RE = re.compile(r"\s+")
_UNDERSCORE_RE = re.compile(r"_{10,}")
_BRACKET_CODE_RE = re.compile(r"^\s*\[[^\]]*\]\s*$")


def _norm(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    return _WS_RE.sub(" ", s)


def _get(l, name, default=None):
    return getattr(l, name, default)


def _x0(l) -> float:
    return float(_get(l, "x0", 0.0) or 0.0)


def _y0(l) -> float:
    return float(_get(l, "y0", 0.0) or 0.0)


def _x1(l) -> float:
    v = _get(l, "x1", None)
    if v is not None:
        try:
            return float(v)
        except Exception:
            pass
    # fallback: crude width estimate from glyph count
    t = _norm(_get(l, "text", "") or "")
    sz = float(_get(l, "size", 0.0) or 0.0)
    return _x0(l) + max(5.0, 0.55 * sz * max(1, len(t)))


def _y1(l) -> float:
    v = _get(l, "y1", None)
    if v is not None:
        try:
            return float(v)
        except Exception:
            pass
    return _y0(l)


def _size(l) -> float:
    return float(_get(l, "size", 0.0) or 0.0)


def _bold(l) -> bool:
    return bool(_get(l, "bold", False))


def _non_black(l) -> bool:
    return bool(_get(l, "non_black", False))


def _text(l) -> str:
    return _get(l, "text", "") or ""


def _page_ymax(lines) -> float:
    if not lines:
        return 0.0
    return max(_y1(l) for l in lines)


def _page_xminmax(lines):
    if not lines:
        return (0.0, 0.0)
    xs0 = [_x0(l) for l in lines]
    xs1 = [_x1(l) for l in lines]
    return (min(xs0), max(xs1))


def _page_width(lines) -> float:
    xmn, xmx = _page_xminmax(lines)
    return max(1.0, xmx - xmn)


def _line_width(l) -> float:
    return max(0.0, _x1(l) - _x0(l))


def _is_underscore_line(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    if _UNDERSCORE_RE.search(t):
        return True
    core = re.sub(r"\s+", "", t)
    if len(core) >= 20 and all(ch in "_-—–" for ch in core):
        return True
    return False


def _is_bracket_code_line(t: str) -> bool:
    return bool(_BRACKET_CODE_RE.match((t or "").strip()))


def _letters_count(t: str) -> int:
    return sum(1 for ch in (t or "") if ch.isalpha())


def _looks_like_input_marker(t: str) -> bool:
    tt = (t or "").strip()
    if not tt:
        return False
    if len(tt) >= 2 and tt[0] == "O" and tt[1].isspace():
        return True
    if "[" in tt and "]" in tt and ("_" in tt or "|" in tt):
        return True
    if ("_|" in tt) or ("|_" in tt):
        return True
    return False


def _rounded_mode(vals, step=0.1):
    if not vals:
        return None
    r = [round(v / step) * step for v in vals]
    c = Counter(r)
    return c.most_common(1)[0][0]


def _top_bar_candidates(lines):
    """
    Candidate "colored title bar" text:
    - near top
    - left-ish (avoid right-column repeating lists)
    - non_black and reasonably large
    """
    if not lines:
        return []
    yhi = 90.0
    ylo = 18.0
    c = []
    for l in lines:
        t = _norm(_text(l))
        if not t:
            continue
        y = _y0(l)
        x = _x0(l)
        if not (ylo <= y <= yhi):
            continue
        if x > 0 and x > (_page_xminmax(lines)[0] + 0.38 * _page_width(lines)):
            continue
        if not _non_black(l):
            continue
        c.append(l)
    return c


def _detect_top_bar_title(lines) -> str:
    """
    Detect a stable form/section title from the top bar without getting fooled by
    right-column lists or protocol/footer furniture.
    """
    cand = _top_bar_candidates(lines)
    if not cand:
        return ""

    max_sz = max(_size(l) for l in cand)
    if max_sz < 10.0:
        return ""

    xs = sorted(_x0(l) for l in cand)
    x_left = xs[0]
    left_cluster = [l for l in cand if (_x0(l) - x_left) <= 0.12 * _page_width(lines)]

    max_left_sz = max(_size(l) for l in left_cluster)
    keep = [l for l in left_cluster if _size(l) >= (max_left_sz - 1.2)]
    if not keep:
        return ""

    keep.sort(key=lambda l: (_y0(l), _x0(l)))

    parts = []
    last_y = None
    for l in keep:
        t = _norm(_text(l))
        if not t:
            continue
        if last_y is None:
            parts.append(t)
            last_y = _y0(l)
            continue
        if (_y0(l) - last_y) <= 18 and len(parts) < 2:
            parts.append(t)
            last_y = _y0(l)

    return _norm(" ".join(parts))


def _detect_approval_title(lines) -> str:
    """
    Approval/title page: very large black bold around upper-middle.
    """
    if not lines:
        return ""
    big = [
        l
        for l in lines
        if _y0(l) <= 260
        and _x0(l) <= (_page_xminmax(lines)[0] + 0.8 * _page_width(lines))
        and _bold(l)
        and _size(l) >= 16
        and _norm(_text(l))
        and (not _non_black(l))
    ]
    if not big:
        return ""
    max_sz = max(_size(l) for l in big)
    cand2 = [l for l in big if _size(l) >= max_sz - 2.0]
    cand2.sort(key=lambda l: (_y0(l), _x0(l)))
    return _norm(" ".join(_norm(_text(l)) for l in cand2))


def _extract_fields_approval_page(lines) -> list:
    if not lines:
        return []

    title_sz = None
    for l in lines:
        if _bold(l) and _size(l) >= 18 and _x0(l) <= (_page_xminmax(lines)[0] + 0.7 * _page_width(lines)) and _y0(l) <= 260 and _norm(_text(l)):
            title_sz = _size(l)
            break

    y_max = _page_ymax(lines)
    cand = []
    for l in lines:
        t = _norm(_text(l))
        if not t:
            continue
        if _is_underscore_line(t):
            continue
        if _x0(l) > (_page_xminmax(lines)[0] + 0.36 * _page_width(lines)):
            continue
        if _y0(l) < 170 or _y0(l) > (y_max - 80):
            continue
        if not _bold(l):
            continue
        if title_sz is not None and abs(_size(l) - title_sz) <= 2.5:
            continue
        cand.append(l)

    if not cand:
        return []

    sz_mode = _rounded_mode([_size(l) for l in cand], step=0.5) or median([_size(l) for l in cand])
    out = []
    for l in cand:
        if abs(_size(l) - sz_mode) <= max(2.0, 0.2 * sz_mode):
            out.append(_norm(_text(l)))

    seen = set()
    fields = []
    for t in out:
        if t and t not in seen:
            seen.add(t)
            fields.append(t)
    return fields


def _extract_fields_signature_page(lines) -> list:
    if not lines:
        return []

    y_max = _page_ymax(lines)
    body_cut = y_max - 120 if y_max else 650

    unders = [l for l in lines if _is_underscore_line(_text(l)) and _y0(l) <= body_cut]
    unders.sort(key=lambda l: (_y0(l), _x0(l)))

    all_sorted = sorted(lines, key=lambda l: (_y0(l), _x0(l)))

    fields = []
    for u in unders:
        ux = _x0(u)
        uy = _y0(u)
        nxt = None
        for l in all_sorted:
            if _y0(l) <= uy:
                continue
            if _y0(l) - uy > 40:
                break
            if abs(_x0(l) - ux) <= 10 and _norm(_text(l)) and not _is_underscore_line(_text(l)):
                nxt = l
                break
        if nxt:
            t = _norm(_text(nxt))
            if t:
                fields.append(t)

    seen = set()
    out = []
    for t in fields:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _estimate_label_size(lines) -> float:
    candidates = []
    y_max = _page_ymax(lines)
    footer_cut = y_max - 70 if y_max else 760
    xmn, _ = _page_xminmax(lines)
    w = _page_width(lines)

    for l in lines:
        if _x0(l) > (xmn + 0.42 * w):
            continue
        if _y0(l) < 60 or _y0(l) > footer_cut:
            continue
        if _non_black(l):
            continue
        t = _norm(_text(l))
        if not t or _is_bracket_code_line(t) or _is_underscore_line(t):
            continue
        if _letters_count(t) == 0 and not re.search(r"\d+\.", t):
            continue
        if _size(l) < 6.0:
            continue
        candidates.append(_size(l))

    if not candidates:
        return 7.5

    mode = _rounded_mode(candidates, step=0.1)
    if mode is not None:
        return float(mode)
    return float(median(candidates))


def _is_field_page_annotated(lines) -> bool:
    if not lines:
        return False
    xmn, _ = _page_xminmax(lines)
    w = _page_width(lines)

    left_brackets = sum(1 for l in lines if _x0(l) <= (xmn + 0.45 * w) and _is_bracket_code_line(_text(l)))
    if left_brackets >= 2:
        return True
    marker_ct = sum(1 for l in lines if _looks_like_input_marker(_text(l)))
    if marker_ct >= 3:
        return True
    return False


def _table_header_ybands(lines) -> set:
    """
    Detect dense multi-column header rows so we can exclude them from "field label" candidates.
    """
    if not lines:
        return set()

    y_max = _page_ymax(lines)
    footer_cut = y_max - 70 if y_max else 760
    xmn, xmx = _page_xminmax(lines)
    w = max(1.0, xmx - xmn)

    groups = {}
    for l in lines:
        t = _norm(_text(l))
        if not t:
            continue
        y = _y0(l)
        if y < 45 or y > min(220, footer_cut):
            continue
        if _is_underscore_line(t) or _is_bracket_code_line(t):
            continue
        yb = int(y / 4.0) * 4
        groups.setdefault(yb, []).append(l)

    bad = set()
    for yb, ls in groups.items():
        if len(ls) < 7:
            continue
        xs = sorted(_x0(l) for l in ls)
        if (xs[-1] - xs[0]) < 0.6 * w:
            continue
        szs = [_size(l) for l in ls]
        if (max(szs) - min(szs)) > 3.0:
            continue
        bins = Counter(int((x - xmn) / max(28.0, 0.06 * w)) for x in xs)
        if sum(1 for _, n in bins.items() if n >= 2) >= 3:
            bad.add(yb)
    return bad


def _extract_fields_annotated(lines) -> list:
    if not lines:
        return []

    y_max = _page_ymax(lines)
    footer_cut = y_max - 55 if y_max else 760
    xmn, _ = _page_xminmax(lines)
    w = _page_width(lines)

    label_sz = _estimate_label_size(lines)
    sz_tol = max(1.3, 0.22 * label_sz)

    bad_ybands = _table_header_ybands(lines)

    cand = []
    for l in lines:
        if _x0(l) > (xmn + 0.41 * w):
            continue
        if _y0(l) < 60 or _y0(l) > footer_cut:
            continue
        if _non_black(l):
            continue

        t = _norm(_text(l))
        if not t:
            continue
        if _is_underscore_line(t):
            continue
        if _is_bracket_code_line(t):
            continue
        if t.startswith("["):
            continue

        yb = int(_y0(l) / 4.0) * 4
        if yb in bad_ybands:
            continue

        # extra guard: top-of-page table/schedule headers can be very wide
        if _y0(l) <= 120 and _line_width(l) >= 0.55 * w and _letters_count(t) >= 10:
            continue

        # exclude overly wide lines that span multiple columns (common in headers)
        if _line_width(l) >= 0.72 * w and _letters_count(t) >= 6:
            continue

        if abs(_size(l) - label_sz) > sz_tol:
            continue

        if _letters_count(t) == 0 and not re.search(r"\d+\.", t):
            continue

        cand.append(l)

    if not cand:
        return []

    cand.sort(key=lambda l: (_y0(l), _x0(l)))

    fields = []
    block = []
    prev = None
    for l in cand:
        if prev is None:
            block = [l]
            prev = l
            continue

        same_col = abs(_x0(l) - _x0(prev)) <= 10
        y_gap = _y0(l) - _y0(prev)
        cont_gap = y_gap <= max(12.5, 1.75 * label_sz)

        if same_col and cont_gap and abs(_size(l) - _size(prev)) <= 0.8:
            block.append(l)
            prev = l
        else:
            parts = [_norm(_text(x)) for x in block if _norm(_text(x))]
            if parts:
                merged = parts[0]
                for p in parts[1:]:
                    if merged.endswith("-"):
                        merged = merged[:-1] + p
                    else:
                        merged = merged + " " + p
                merged = _norm(merged)
                if merged:
                    fields.append(merged)
            block = [l]
            prev = l

    if block:
        parts = [_norm(_text(x)) for x in block if _norm(_text(x))]
        if parts:
            merged = parts[0]
            for p in parts[1:]:
                if merged.endswith("-"):
                    merged = merged[:-1] + p
                else:
                    merged = merged + " " + p
            merged = _norm(merged)
            if merged:
                fields.append(merged)

    seen = set()
    out = []
    for f in fields:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _code_decode_header_row(lines):
    """
    Detect a two-column "Coded | Decode" style header row structurally:
    bold-ish headers near the same y, one in left col, one in right col.
    Returns a representative header y (float) or None.
    """
    if not lines:
        return None

    y_max = _page_ymax(lines)
    footer_cut = y_max - 70 if y_max else 760
    xmn, _ = _page_xminmax(lines)
    w = _page_width(lines)

    left_max = xmn + 0.30 * w
    right_min = xmn + 0.55 * w

    rows = {}
    for l in lines:
        t = _norm(_text(l))
        if not t:
            continue
        y = _y0(l)
        if y < 45 or y > min(110, footer_cut):
            continue
        if _is_bracket_code_line(t) or _is_underscore_line(t):
            continue
        if not _bold(l):
            continue
        sz = _size(l)
        if sz < 8.5 or sz > 13.5:
            continue
        yb = int(y / 3.0) * 3
        rows.setdefault(yb, []).append(l)

    for yb, ls in rows.items():
        has_left = any(_x0(l) <= left_max for l in ls)
        has_right = any(_x0(l) >= right_min for l in ls)
        if has_left and has_right and len(ls) >= 2:
            return float(yb)
    return None


def _looks_like_code_list_definition_page(lines) -> bool:
    """
    Structural code-list / decode-table pages that enumerate answer options.
    These are NOT data-entry fields and must not be extracted.
    """
    hy = _code_decode_header_row(lines)
    if hy is None:
        return False

    y_max = _page_ymax(lines)
    footer_cut = y_max - 70 if y_max else 760
    xmn, _ = _page_xminmax(lines)
    w = _page_width(lines)

    left_max = xmn + 0.34 * w
    right_min = xmn + 0.55 * w

    # gather body candidates below header
    body = []
    for l in lines:
        t = _norm(_text(l))
        if not t:
            continue
        y = _y0(l)
        if y <= hy + 6 or y > footer_cut:
            continue
        if _is_bracket_code_line(t) or _is_underscore_line(t):
            continue
        if _non_black(l):
            continue
        sz = _size(l)
        if sz < 7.0 or sz > 11.5:
            continue
        x = _x0(l)
        if x <= left_max or x >= right_min:
            body.append(l)

    if not body:
        return True  # header present but empty body: still a definition-style page

    # pair left/right by y band
    pairs = []
    rows = {}
    for l in body:
        yb = int(_y0(l) / 3.0) * 3
        rows.setdefault(yb, []).append(l)

    for yb, ls in rows.items():
        lefts = [l for l in ls if _x0(l) <= left_max]
        rights = [l for l in ls if _x0(l) >= right_min]
        if not lefts or not rights:
            continue
        # choose "best" text in each side
        lefts.sort(key=lambda l: (-_letters_count(_norm(_text(l))), _x0(l)))
        rights.sort(key=lambda l: (-_letters_count(_norm(_text(l))), _x0(l)))
        lt = _norm(_text(lefts[0]))
        rt = _norm(_text(rights[0]))
        if lt and rt:
            pairs.append((lt, rt))

    if len(pairs) < 3:
        return True

    same = sum(1 for lt, rt in pairs if lt == rt)
    right_longer = sum(1 for lt, rt in pairs if len(rt) >= len(lt) + 6 and _letters_count(rt) >= 4)
    left_codey = sum(
        1
        for lt, _ in pairs
        if (len(lt) <= 4 and (lt.isdigit() or lt.isupper())) or (len(lt) <= 7 and lt.isdigit())
    )

    n = len(pairs)
    if same / n >= 0.55:
        return True
    if right_longer / n >= 0.55:
        return True
    if left_codey / n >= 0.55:
        return True

    # also: lots of short, repeated-ish row entries in two columns is strongly indicative
    shortish = sum(1 for lt, rt in pairs if len(lt) <= 14 and len(rt) <= 30)
    if shortish / n >= 0.7:
        return True

    return False


def _looks_like_schedule_matrix_page(lines) -> bool:
    """
    Structural schedule/table pages: dense multi-column headers and little/no field evidence.
    We should not extract "headers" as fields (e.g., page 4 issue).
    """
    if not lines:
        return False
    if _is_field_page_annotated(lines):
        return False
    if _looks_like_code_list_definition_page(lines):
        return False

    bad_ybands = _table_header_ybands(lines)
    if not bad_ybands:
        return False

    marker_ct = sum(1 for l in lines if _looks_like_input_marker(_text(l)))
    xmn, _ = _page_xminmax(lines)
    w = _page_width(lines)
    left_brackets = sum(1 for l in lines if _x0(l) <= (xmn + 0.45 * w) and _is_bracket_code_line(_text(l)))
    underscore_ct = sum(1 for l in lines if _is_underscore_line(_text(l)))

    # if there is any meaningful field evidence, don't classify as schedule matrix
    if marker_ct >= 2 or left_brackets >= 2 or underscore_ct >= 2:
        return False

    y_max = _page_ymax(lines)
    mid = 0.55 * (y_max if y_max else 800)

    # require a lot of small, black, non-annotated fragments in the top half
    frags = []
    for l in lines:
        t = _norm(_text(l))
        if not t:
            continue
        y = _y0(l)
        if y < 40 or y > mid:
            continue
        if _non_black(l):
            continue
        if _is_bracket_code_line(t) or _is_underscore_line(t):
            continue
        if _letters_count(t) < 2:
            continue
        sz = _size(l)
        if sz < 6.0 or sz > 10.5:
            continue
        frags.append(l)

    if len(frags) < 18:
        return False

    # x spread across many bins implies matrix/schedule
    bins = Counter(int((_x0(l) - xmn) / max(35.0, 0.08 * w)) for l in frags)
    wide_bins = sum(1 for _, n in bins.items() if n >= 3)
    if wide_bins >= 4:
        return True

    return False


def extract(pages):
    results = []
    current_form = ""
    seen = set()  # (form_name, field_name, page1based)

    for page_idx0, lines in pages:
        page1 = page_idx0 + 1
        y_max = _page_ymax(lines)

        # approval pages: update form title from big black title and extract bold left labels
        has_big_title = any(
            _bold(l) and _size(l) >= 18 and _x0(l) <= (_page_xminmax(lines)[0] + 0.75 * _page_width(lines)) and _y0(l) <= 260
            for l in lines
        )
        if has_big_title:
            title = _detect_approval_title(lines)
            if title:
                current_form = title
            fields = _extract_fields_approval_page(lines)
            for fn in fields:
                form_name = current_form or ""
                key = (form_name, fn, page1)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"form_name": form_name, "field_name": fn, "page": page1})
            continue

        # signature pages
        body_cut = (y_max - 120) if y_max else 650
        underscore_ct = sum(1 for l in lines if _is_underscore_line(_text(l)) and _y0(l) <= body_cut)
        if underscore_ct >= 2 and not _is_field_page_annotated(lines):
            tb = _detect_top_bar_title(lines)
            if tb:
                current_form = tb
            fields = _extract_fields_signature_page(lines)
            for fn in fields:
                form_name = current_form or ""
                key = (form_name, fn, page1)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"form_name": form_name, "field_name": fn, "page": page1})
            continue

        # code/decode definition pages (answer option tables): extract nothing
        if _looks_like_code_list_definition_page(lines):
            continue

        # schedule/matrix pages: extract nothing
        if _looks_like_schedule_matrix_page(lines):
            continue

        # annotated field pages (primary coverage)
        if _is_field_page_annotated(lines):
            tb = _detect_top_bar_title(lines)
            if tb:
                current_form = tb
            fields = _extract_fields_annotated(lines)
            for fn in fields:
                form_name = current_form or ""
                key = (form_name, fn, page1)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"form_name": form_name, "field_name": fn, "page": page1})
            continue

        # conservative fallback: only extract when there is strong marker evidence
        # (prevents table/schedule headers and other furniture from leaking in)
        marker_ct = sum(1 for l in lines if _looks_like_input_marker(_text(l)))
        xmn, _ = _page_xminmax(lines)
        w = _page_width(lines)
        left_brackets = sum(1 for l in lines if _x0(l) <= (xmn + 0.45 * w) and _is_bracket_code_line(_text(l)))

        if (left_brackets >= 2 and marker_ct >= 1) or marker_ct >= 7:
            tb = _detect_top_bar_title(lines)
            if tb:
                current_form = tb
            fields = _extract_fields_annotated(lines)
            for fn in fields:
                form_name = current_form or ""
                key = (form_name, fn, page1)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"form_name": form_name, "field_name": fn, "page": page1})

    return results
```
