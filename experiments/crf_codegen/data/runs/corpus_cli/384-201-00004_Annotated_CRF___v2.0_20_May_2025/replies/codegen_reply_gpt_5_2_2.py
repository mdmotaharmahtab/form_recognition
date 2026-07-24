```python
import re
from collections import Counter
from statistics import median

_WS_RE = re.compile(r"\s+")
_UNDERSCORE_RE = re.compile(r"_{10,}")
_BRACKET_CODE_RE = re.compile(r"^\s*\[[^\]]*\]\s*$")


def _norm(s: str) -> str:
    s = s.strip()
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
    t = t.strip()
    if not t:
        return False
    if _UNDERSCORE_RE.search(t):
        return True
    core = re.sub(r"\s+", "", t)
    if len(core) >= 20 and all(ch in "_-—–" for ch in core):
        return True
    return False


def _is_bracket_code_line(t: str) -> bool:
    return bool(_BRACKET_CODE_RE.match(t.strip()))


def _letters_count(t: str) -> int:
    return sum(1 for ch in t if ch.isalpha())


def _looks_like_input_marker(t: str) -> bool:
    tt = t.strip()
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
    - left-ish (avoid right-column repeating blue items)
    - non_black (white/colored) and reasonably large
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
        if x > 170:  # avoid right-side repeated list columns
            continue
        if not _non_black(l):
            continue
        c.append(l)
    return c


def _detect_top_bar_title(lines) -> str:
    """
    Detect a stable form/section title from the top bar without getting fooled by:
    - protocol number at y~10 (black, small)
    - repeating right-column blue lists (x>200)
    """
    cand = _top_bar_candidates(lines)
    if not cand:
        return ""

    # require that the band has a genuinely "title-like" size
    max_sz = max(_size(l) for l in cand)
    if max_sz < 10.0:
        return ""

    # prefer the leftmost cluster (titles usually start near the left edge)
    xs = sorted(_x0(l) for l in cand)
    x_left = xs[0]
    left_cluster = [l for l in cand if (_x0(l) - x_left) <= 60]

    # among the left cluster, keep near-max font size
    max_left_sz = max(_size(l) for l in left_cluster)
    keep = [l for l in left_cluster if _size(l) >= (max_left_sz - 1.2)]
    if not keep:
        return ""

    keep.sort(key=lambda l: (_y0(l), _x0(l)))

    # join up to 2 wrapped lines (avoid long multi-line lists)
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

    title = _norm(" ".join(parts))
    return title


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
        and _x0(l) <= 380
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
        if _bold(l) and _size(l) >= 18 and _x0(l) <= 320 and _y0(l) <= 260 and _norm(_text(l)):
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
        if _x0(l) > 180:
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
    for l in lines:
        if _x0(l) > 210:
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
    left_brackets = sum(1 for l in lines if _x0(l) <= 220 and _is_bracket_code_line(_text(l)))
    if left_brackets >= 2:
        return True
    marker_ct = sum(1 for l in lines if _looks_like_input_marker(_text(l)))
    if marker_ct >= 3:
        return True
    return False


def _table_header_ybands(lines) -> set:
    """
    Detect dense multi-column header rows (e.g., schedule/table headers) so we can
    exclude them from "field label" candidates without skipping the whole page.
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
        if y < 45 or y > min(200, footer_cut):
            continue
        if _is_underscore_line(t) or _is_bracket_code_line(t):
            continue
        # bin by coarse y to merge same-row fragments
        yb = int(y / 4.0) * 4
        groups.setdefault(yb, []).append(l)

    bad = set()
    for yb, ls in groups.items():
        if len(ls) < 6:
            continue
        xs = sorted(_x0(l) for l in ls)
        if (xs[-1] - xs[0]) < 0.55 * w:
            continue
        # similar-ish sizes and mostly black (table headers often black)
        szs = [_size(l) for l in ls]
        if (max(szs) - min(szs)) > 3.0:
            continue
        # multiple x-clusters
        bins = Counter(int((x - xmn) / 40.0) for x in xs)
        if sum(1 for _, n in bins.items() if n >= 2) >= 3:
            bad.add(yb)
    return bad


def _extract_fields_annotated(lines) -> list:
    if not lines:
        return []

    y_max = _page_ymax(lines)
    footer_cut = y_max - 55 if y_max else 760
    w = _page_width(lines)

    label_sz = _estimate_label_size(lines)
    sz_tol = max(1.3, 0.22 * label_sz)

    bad_ybands = _table_header_ybands(lines)

    cand = []
    for l in lines:
        if _x0(l) > 205:
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

        # exclude dense multi-column header rows
        yb = int(_y0(l) / 4.0) * 4
        if yb in bad_ybands:
            continue

        # exclude overly wide lines that span multiple columns (common in table headers)
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


def _looks_like_decode_table_page(lines) -> bool:
    """
    Structural "code/decode" pages: two header cells and many short numeric codes on the left,
    longer decode text on the right. We must not extract options; typically we emit one field
    label from the top bar (if present) while keeping form_name stable.
    """
    if not lines:
        return False

    y_max = _page_ymax(lines)
    footer_cut = y_max - 70 if y_max else 760

    # many left numeric-only rows
    left_codes = 0
    right_text = 0
    header_like = 0

    for l in lines:
        t = _norm(_text(l))
        if not t:
            continue
        y = _y0(l)
        if y < 45 or y > footer_cut:
            continue

        x = _x0(l)
        sz = _size(l)

        # header cells often bold and slightly larger, near y~55-75 at both left and right
        if 50 <= y <= 90 and _bold(l) and 9.0 <= sz <= 12.5:
            if x <= 120 or x >= 220:
                header_like += 1

        if x <= 120:
            if len(t) <= 3 and t.isdigit():
                left_codes += 1
        if x >= 220:
            if len(t) >= 12 and _letters_count(t) >= 6 and not _is_bracket_code_line(t):
                right_text += 1

    if header_like >= 2 and left_codes >= 4 and right_text >= 4:
        return True
    return False


def _extract_field_from_decode_page(lines) -> str:
    """
    Pull the page's main label (usually in the colored top bar at left).
    """
    header = _detect_top_bar_title(lines)
    if header:
        return header

    # fallback: largest bold-ish line near top-left (avoid protocol line)
    c = []
    for l in lines:
        t = _norm(_text(l))
        if not t:
            continue
        if _y0(l) < 18 or _y0(l) > 140:
            continue
        if _x0(l) > 220:
            continue
        if _non_black(l):
            continue
        if _size(l) < 10.5:
            continue
        if _is_bracket_code_line(t) or _is_underscore_line(t):
            continue
        c.append(l)

    if not c:
        return ""
    max_sz = max(_size(l) for l in c)
    top = [l for l in c if _size(l) >= max_sz - 1.0]
    top.sort(key=lambda l: (_y0(l), _x0(l)))
    return _norm(" ".join(_norm(_text(l)) for l in top))


def _looks_like_right_col_colored_list_page(lines) -> bool:
    """
    Pages like schedule/interval lists: many colored (non_black) lines in one right-side column.
    These were previously 0% covered and should yield fields (as labels), not form titles.
    """
    if not lines:
        return False

    y_max = _page_ymax(lines)
    footer_cut = y_max - 70 if y_max else 760

    # avoid mixing with annotated pages (those are already covered well)
    left_brackets = sum(1 for l in lines if _x0(l) <= 220 and _is_bracket_code_line(_text(l)))
    if left_brackets >= 1:
        return False

    colored = []
    for l in lines:
        t = _norm(_text(l))
        if not t:
            continue
        if not _non_black(l):
            continue
        y = _y0(l)
        if y < 25 or y > min(320, footer_cut):
            continue
        x = _x0(l)
        if x < 160:
            continue
        # filter tiny technical crumbs
        if _size(l) < 7.8:
            continue
        colored.append(l)

    if len(colored) < 6:
        return False

    # require a dominant x0 cluster
    bins = Counter(int(_x0(l) / 15.0) for l in colored)
    b, n = bins.most_common(1)[0]
    if n < 6:
        return False

    return True


def _extract_right_col_fields_as_form_and_field(lines):
    """
    Extract field labels from a dominant right-side colored column.
    When a repeated "prefix" line appears, treat it as form_name (shared),
    and the subsequent (often wrapped) line(s) as field_name.
    """
    if not lines:
        return []

    y_max = _page_ymax(lines)
    footer_cut = y_max - 70 if y_max else 760

    colored = []
    for l in lines:
        t = _norm(_text(l))
        if not t:
            continue
        if not _non_black(l):
            continue
        y = _y0(l)
        if y < 25 or y > min(420, footer_cut):
            continue
        x = _x0(l)
        if x < 160:
            continue
        if _size(l) < 7.8:
            continue
        colored.append(l)

    if not colored:
        return []

    # dominant x-cluster
    bins = Counter(int(_x0(l) / 15.0) for l in colored)
    dom_bin, _ = bins.most_common(1)[0]
    cluster = [l for l in colored if int(_x0(l) / 15.0) == dom_bin]
    cluster.sort(key=lambda l: (_y0(l), _x0(l)))

    # typical size in this column
    sz_mode = _rounded_mode([_size(l) for l in cluster], step=0.5) or median([_size(l) for l in cluster])
    keep = [l for l in cluster if abs(_size(l) - sz_mode) <= 1.6]
    keep.sort(key=lambda l: (_y0(l), _x0(l)))

    # identify "start lines" (often long multi-word labels)
    def is_start_line(t: str) -> bool:
        if not t:
            return False
        if t.startswith(("–", "-")):
            return False
        words = re.findall(r"[A-Za-z]{2,}", t)
        if len(words) >= 4 and len(t) >= 18:
            return True
        # allow shorter-but-still-label-ish starts
        if len(words) >= 3 and len(t) >= 14 and (" " in t):
            return True
        return False

    # build blocks: each start line begins a new block
    blocks = []
    cur = []
    for l in keep:
        t = _norm(_text(l))
        if not t:
            continue
        if cur and is_start_line(t):
            blocks.append(cur)
            cur = [l]
        else:
            cur.append(l)
    if cur:
        blocks.append(cur)

    # merge each block to a single label string
    labels = []
    for bl in blocks:
        parts = []
        prev_t = None
        for l in bl:
            tt = _norm(_text(l))
            if not tt:
                continue
            # if there are big y gaps inside a block, split (defensive)
            if parts:
                pass
            parts.append(tt)

        if not parts:
            continue
        merged = parts[0]
        for p in parts[1:]:
            if merged.endswith("-"):
                merged = merged[:-1] + p
            else:
                merged = merged + " " + p
        merged = _norm(merged)
        if merged:
            labels.append(merged)

    if not labels:
        return []

    # Split into (form_name, field_name) using repeated prefix lines when available.
    # If a full label repeats verbatim, treat it as a form_name marker and attach subsequent labels.
    freq = Counter(labels)

    results = []
    current_form = ""
    for lab in labels:
        if freq[lab] >= 2 and _letters_count(lab) >= 8 and len(lab) >= 12:
            current_form = lab
            continue
        if current_form:
            results.append((current_form, lab))
        else:
            # Try a shared word-prefix within this page as form_name (must be printed as substring).
            # Only apply if it yields a 3+ word prefix and the remainder is non-trivial.
            toks = lab.split()
            best_prefix = ""
            if len(toks) >= 6:
                # choose a prefix ending before a parenthetical, if present, else first 4 words
                cut = None
                for i, tok in enumerate(toks):
                    if "(" in tok:
                        cut = i
                        break
                if cut is not None and cut >= 3:
                    best_prefix = _norm(" ".join(toks[:cut]))
                else:
                    best_prefix = _norm(" ".join(toks[:4]))

            if best_prefix and len(best_prefix.split()) >= 3 and len(best_prefix) >= 12:
                remainder = _norm(lab[len(best_prefix) :].lstrip(" -–:"))
                if remainder and remainder != lab:
                    results.append((best_prefix, remainder))
                else:
                    results.append(("", lab))
            else:
                results.append(("", lab))

    # de-dupe while preserving order
    seen = set()
    out = []
    for fn, fld in results:
        key = (fn, fld)
        if not fld:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append((fn, fld))
    return out


def extract(pages):
    results = []
    current_form = ""
    seen = set()  # (form_name, field_name, page1based)

    for page_idx0, lines in pages:
        page1 = page_idx0 + 1
        y_max = _page_ymax(lines)

        # approval pages: update form title from big black title and extract bold left labels
        has_big_title = any(_bold(l) and _size(l) >= 18 and _x0(l) <= 350 and _y0(l) <= 260 for l in lines)
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
        underscore_ct = sum(
            1
            for l in lines
            if _is_underscore_line(_text(l)) and _y0(l) <= (y_max - 120 if y_max else 650)
        )
        if underscore_ct >= 2 and not _is_field_page_annotated(lines):
            # update current_form only if we can safely detect a title-bar form name
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

        # cluster-1: right-column colored list pages (previously 0% coverage)
        if _looks_like_right_col_colored_list_page(lines):
            pairs = _extract_right_col_fields_as_form_and_field(lines)
            # do not overwrite current_form from these pages (often they carry per-field titles)
            for form_like, fld in pairs:
                form_name = form_like or current_form or ""
                key = (form_name, fld, page1)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"form_name": form_name, "field_name": fld, "page": page1})
            continue

        # cluster-1: decode table pages
        if _looks_like_decode_table_page(lines):
            fld = _extract_field_from_decode_page(lines)
            if fld:
                form_name = current_form or _detect_top_bar_title(lines) or ""
                # If we have no stable carried form name, fall back to using the page header as form_name too.
                # This is a last resort for single-field forms whose only printed label is in the top bar.
                if not current_form:
                    form_name = form_name or fld
                key = (form_name, fld, page1)
                if key not in seen:
                    seen.add(key)
                    results.append({"form_name": form_name, "field_name": fld, "page": page1})
            continue

        # annotated field pages (already good coverage)
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

        # conservative fallback: only extract if there is meaningful marker evidence
        # (avoid pulling table headers like page 4)
        marker_ct = sum(1 for l in lines if _looks_like_input_marker(_text(l)))
        left_brackets = sum(1 for l in lines if _x0(l) <= 220 and _is_bracket_code_line(_text(l)))

        if (left_brackets >= 1 and marker_ct >= 1) or marker_ct >= 5:
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

        # otherwise: no extract
        continue

    return results
```
