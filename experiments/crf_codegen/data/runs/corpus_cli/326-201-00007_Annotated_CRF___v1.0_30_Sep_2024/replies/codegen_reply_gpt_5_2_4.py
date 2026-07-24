```python
import re
from collections import defaultdict


_WS_RE = re.compile(r"\s+")
_NUM_ONLY_RE = re.compile(r"^\s*\d+(?:\.\d+)?\s*$")
_OPT_PREFIX_RE = re.compile(r"^\s*(?:[Oo○◯□☐■▪•·\-–—✓✔☑]+)\s+")
_MOSTLY_PUNCT_RE = re.compile(r"^[\s\W_]+$")


def _norm(s: str) -> str:
    s = (s or "").strip()
    s = _WS_RE.sub(" ", s)
    return s


def _t(ln) -> str:
    return getattr(ln, "text", "") or ""


def _x(ln) -> float:
    return float(getattr(ln, "x0", 0.0) or 0.0)


def _y(ln) -> float:
    return float(getattr(ln, "y0", 0.0) or 0.0)


def _sz(ln) -> float:
    return float(getattr(ln, "size", 0.0) or 0.0)


def _is_boldish(ln) -> bool:
    for k in ("bold", "is_bold", "isBold"):
        if hasattr(ln, k):
            return bool(getattr(ln, k))
    for k in ("font_weight", "fontWeight", "weight"):
        if hasattr(ln, k):
            try:
                return float(getattr(ln, k)) >= 600
            except Exception:
                pass
    for k in ("flags", "style", "font_style", "fontStyle"):
        v = getattr(ln, k, None)
        if isinstance(v, str) and ("B" in v or "Bold" in v or "bold" in v):
            return True
    return False


def _is_non_black(ln) -> bool:
    if hasattr(ln, "non_black"):
        return bool(getattr(ln, "non_black"))
    c = getattr(ln, "color", None)
    if isinstance(c, str) and c:
        cc = c.strip().lower()
        if cc in ("black", "#000", "#000000", "rgb(0,0,0)", "rgba(0,0,0,1)"):
            return False
        return True
    return False


def _count_underscores(s: str) -> int:
    return (s or "").count("_")


def _looks_like_underscore_guide(text: str) -> bool:
    tx = text or ""
    if "_" not in tx:
        return False
    return _count_underscores(tx) >= 6


def _looks_like_option_row(text: str) -> bool:
    t = text or ""
    if not t.strip():
        return False
    if _OPT_PREFIX_RE.match(t):
        return True
    tn = _norm(t)
    if len(tn) >= 2 and tn[0] in ("O", "o", "○", "◯", "□", "☐") and tn[1].isspace():
        return True
    return False


def _is_plausible_field_name(text: str) -> bool:
    t = _norm(text)
    if not t:
        return False
    if _NUM_ONLY_RE.match(t):
        return False
    if _looks_like_option_row(t):
        return False
    if _looks_like_underscore_guide(t):
        return False
    if _MOSTLY_PUNCT_RE.match(t):
        return False

    alnum = sum(1 for ch in t if ch.isalnum())
    if alnum < 3:
        return False

    if _count_underscores(t) > max(10, len(t) // 2):
        return False

    punct = sum(1 for ch in t if ch in "[]{}()=:/\\|<>")
    if punct >= 4:
        letters = [ch for ch in t if ch.isalpha()]
        if letters:
            upper = sum(1 for ch in letters if ch.isupper())
            if upper / max(1, len(letters)) > 0.80 and punct / max(1, len(t)) > 0.10:
                return False

    return True


def _strip_trailing_punct(label: str) -> str:
    s = _norm(label)
    while s and s[-1] in ":;,. ":
        s = s[:-1].rstrip()
    return s


def _median(nums):
    if not nums:
        return 0.0
    a = sorted(nums)
    n = len(a)
    mid = n // 2
    if n % 2:
        return float(a[mid])
    return 0.5 * (float(a[mid - 1]) + float(a[mid]))


def _estimate_page_dims(lines):
    max_x = 0.0
    max_y = 0.0
    sizes = []
    for ln in lines:
        tx = _t(ln)
        if tx and tx.strip():
            sizes.append(_sz(ln) or 0.0)
        xx = _x(ln)
        yy = _y(ln)
        if xx > max_x:
            max_x = xx
        if yy > max_y:
            max_y = yy
    med_sz = _median([s for s in sizes if s > 0.0]) or 10.0
    page_w = max(600.0, max_x + 40.0)
    page_h = max(700.0, max_y + 60.0)
    return page_w, page_h, med_sz


def _row_key(y: float) -> int:
    return int(round(y))


def _get_form_name_schedule(lines, last_form: str, page_w: float, header_y: float) -> str:
    label_ln = None
    for ln in lines:
        tx = _t(ln)
        if not tx or not tx.strip():
            continue
        if _y(ln) > header_y:
            continue
        if "schedule category" in tx.lower():
            label_ln = ln
            break

    if label_ln is None:
        return last_form or ""

    best = None
    best_score = None
    y0 = _y(label_ln)

    for ln in lines:
        tx = _t(ln)
        if not tx or not tx.strip():
            continue
        if abs(_y(ln) - y0) > 4.5:
            continue
        if _x(ln) <= _x(label_ln) + 20:
            continue
        score = (
            abs(_y(ln) - y0),
            0 if not _is_boldish(ln) else 1,
            0 if len(_norm(tx)) >= 8 else 1,
            abs((_x(label_ln) + 140.0) - _x(ln)),
        )
        if best is None or score < best_score:
            best = ln
            best_score = score

    if best is None:
        for ln in sorted(lines, key=lambda l: (_y(l), _x(l))):
            tx = _t(ln)
            if not tx or not tx.strip():
                continue
            if _y(ln) <= y0:
                continue
            if _y(ln) - y0 > 24.0:
                break
            if _x(ln) >= max(_x(label_ln) + 40.0, 0.25 * page_w):
                best = ln
                break

    if best is None:
        return last_form or ""
    return _norm(_t(best))


def _infer_header_title(lines, page_w, page_h, med_sz, header_y):
    # Find prominent header title when explicit schedule line is absent.
    # Prefer bold/large near top, but allow very large non-bold titles too.
    cand = []
    for ln in lines:
        tx = _norm(_t(ln))
        if not tx:
            continue
        yy = _y(ln)
        if yy > header_y:
            continue

        if tx.endswith(":") or tx.endswith("?"):
            continue
        if _looks_like_option_row(tx) or _looks_like_underscore_guide(tx):
            continue
        if _NUM_ONLY_RE.match(tx):
            continue

        sz = _sz(ln) or 0.0
        is_b = _is_boldish(ln)

        if is_b:
            if sz < max(8.0, 1.18 * med_sz):
                continue
        else:
            if sz < max(10.0, 1.45 * med_sz):
                continue

        xx = _x(ln)
        if xx < 0.06 * page_w or xx > 0.90 * page_w:
            continue

        letters = sum(1 for ch in tx if ch.isalpha())
        if letters < 4:
            continue
        if tx.lower().startswith("page "):
            continue
        if "confidential" in tx.lower() and len(tx) <= 18:
            continue

        cand.append(ln)

    if not cand:
        return ""

    by_row = defaultdict(list)
    for ln in cand:
        by_row[_row_key(_y(ln))].append(ln)

    rows = []
    for rk, items in by_row.items():
        items.sort(key=lambda l: _x(l))
        txt = _norm(" ".join(_norm(_t(l)) for l in items))
        if not txt:
            continue
        if txt.endswith(":") or txt.endswith("?"):
            continue
        max_sz = max((_sz(l) or 0.0) for l in items)
        bold_cnt = sum(1 for l in items if _is_boldish(l))
        min_x = min(_x(l) for l in items)
        center_bias = abs((min_x / max(1.0, page_w)) - 0.18)
        rows.append((max_sz, bold_cnt, len(txt), -center_bias, -abs(rk), rk, txt, items))

    rows.sort(reverse=True)
    top = rows[0]
    txt0 = top[6]
    items0 = top[7]
    y0 = _y(items0[0])
    sz0 = top[0] or med_sz
    line_h = max(10.0, 1.55 * (sz0 or med_sz))

    next_rows = []
    for rk, items in by_row.items():
        yy = _y(items[0])
        if yy <= y0:
            continue
        if yy - y0 > 1.6 * line_h:
            continue
        max_sz = max((_sz(l) or 0.0) for l in items)
        if max_sz < 0.92 * sz0:
            continue
        items.sort(key=lambda l: _x(l))
        txt = _norm(" ".join(_norm(_t(l)) for l in items))
        if not txt:
            continue
        if txt.lower().startswith("schedule category"):
            continue
        if txt.endswith(":") or txt.endswith("?"):
            continue
        next_rows.append((abs(yy - y0), -len(txt), txt))

    next_rows.sort()
    if next_rows:
        txt0 = _norm(txt0 + " " + next_rows[0][2])

    return txt0


def _build_field_name(start_ln, lines, page_w: float, has_left_partner, require_bold: bool = True) -> str:
    x0 = _x(start_ln)
    y0 = _y(start_ln)
    line_h = max(10.0, (_sz(start_ln) or 10.0) * 1.6)
    col_tol = max(12.0, 0.03 * page_w)

    col = []
    for ln in lines:
        tx = _t(ln)
        if not tx or not tx.strip():
            continue
        if require_bold and (not _is_boldish(ln)):
            continue
        if abs(_x(ln) - x0) > col_tol:
            continue
        yy = _y(ln)
        if yy < y0 - 2.0 or yy > y0 + 90.0:
            continue
        col.append(ln)

    col.sort(key=lambda l: (_y(l), _x(l)))

    picked = []
    y_tol = max(4.2, 0.45 * line_h)
    for ln in col:
        if abs(_y(ln) - y0) <= y_tol:
            picked.append(ln)
            break
    if not picked:
        return ""

    prev_y = _y(picked[0])
    max_wrap_dy = max(14.0, 1.55 * line_h)
    for ln in col:
        if ln is picked[0]:
            continue
        yy = _y(ln)
        if yy <= prev_y + 0.2:
            continue
        dy = yy - prev_y
        if dy > max_wrap_dy:
            break
        picked.append(ln)
        prev_y = yy
        if len(picked) >= 10:
            break

    kept = [picked[0]]
    seen_left = False
    consecutive_no_left_after_left = 0

    for i in range(1, len(picked)):
        ln = picked[i]
        has_left = has_left_partner(_y(ln))

        if has_left:
            seen_left = True
            consecutive_no_left_after_left = 0
            kept.append(ln)
            continue

        if not seen_left:
            if i <= 2 and (_y(ln) - _y(kept[0])) <= max_wrap_dy:
                kept.append(ln)
                continue
            break

        consecutive_no_left_after_left += 1
        if consecutive_no_left_after_left == 1:
            kept.append(ln)
        else:
            kept.pop()
            break

    text = _norm(" ".join(_norm(_t(ln)) for ln in kept))
    return text


def extract(pages):
    pages_list = list(pages)
    total_pages = len(pages_list) if pages_list else 1

    # Pre-pass: detect repeated header/footer furniture labels structurally.
    occur_pages = defaultdict(set)  # text -> set(page_index_0)
    occur_band = defaultdict(lambda: [0, 0])  # text -> [header_count, footer_count]

    for page_index_0, lines in pages_list:
        page_w, page_h, med_sz = _estimate_page_dims(lines)
        header_y = 0.18 * page_h
        footer_y = 0.88 * page_h

        for ln in lines:
            tx = _norm(_t(ln))
            if not tx:
                continue
            if not _is_boldish(ln):
                continue
            if not _is_plausible_field_name(tx):
                continue

            yy = _y(ln)
            if yy <= header_y or yy >= footer_y:
                if (_sz(ln) or 0.0) >= 1.55 * (med_sz or 10.0):
                    continue
                occur_pages[tx].add(page_index_0)
                if yy <= header_y:
                    occur_band[tx][0] += 1
                else:
                    occur_band[tx][1] += 1

    furniture = set()
    for tx, pset in occur_pages.items():
        pct = len(pset) / max(1, total_pages)
        if pct < 0.70:
            continue
        hcnt, fcnt = occur_band.get(tx, [0, 0])
        if max(hcnt, fcnt) >= 0.85 * (hcnt + fcnt):
            furniture.add(tx)

    out = []
    last_form = ""

    for page_index_0, lines in pages_list:
        page_w, page_h, med_sz = _estimate_page_dims(lines)
        header_y = 0.18 * page_h
        footer_y = 0.88 * page_h

        form_name = _get_form_name_schedule(lines, last_form, page_w, header_y)
        if not form_name:
            inferred = _infer_header_title(lines, page_w, page_h, med_sz, header_y)
            if inferred:
                form_name = inferred

        if form_name:
            last_form = form_name
        else:
            form_name = last_form or ""

        # Index left-column lines by y for partner checks.
        left_by_y = defaultdict(list)
        left_x_cut = 0.30 * page_w
        for ln in lines:
            tx = _t(ln)
            if not tx or not tx.strip():
                continue
            if _x(ln) < left_x_cut:
                left_by_y[_row_key(_y(ln))].append(ln)

        def has_left_partner(y: float) -> bool:
            ky = _row_key(y)
            for d in (-2, -1, 0, 1, 2):
                bucket = left_by_y.get(ky + d)
                if not bucket:
                    continue
                for ll in bucket:
                    if abs(_y(ll) - y) <= 2.8:
                        return True
            return False

        # Same-row lookup.
        by_row = defaultdict(list)
        for ln in lines:
            tx = _t(ln)
            if not tx or not tx.strip():
                continue
            by_row[_row_key(_y(ln))].append(ln)

        # Underscore guide rows quick index.
        underscore_rows = defaultdict(list)
        for ln in lines:
            tx = _t(ln)
            if not tx or not tx.strip():
                continue
            if _looks_like_underscore_guide(tx):
                underscore_rows[_row_key(_y(ln))].append(ln)

        def has_placeholder_near(label_ln) -> bool:
            lx = _x(label_ln)
            ly = _y(label_ln)
            line_h = max(10.0, (_sz(label_ln) or med_sz or 10.0) * 1.6)
            for d in (-2, -1, 0, 1, 2, 3):
                row = underscore_rows.get(_row_key(ly) + d)
                if not row:
                    continue
                for uln in row:
                    if abs(_y(uln) - ly) > max(6.0, 0.50 * line_h) + abs(d) * 0.2:
                        continue
                    if _x(uln) <= lx + 20.0:
                        continue
                    if _count_underscores(_t(uln)) >= 6:
                        return True
            return False

        def _row_line_h(items):
            szs = [(_sz(l) or 0.0) for l in items if (_sz(l) or 0.0) > 0.0]
            base = _median(szs) or (med_sz or 10.0)
            return max(10.0, 1.6 * base)

        def looks_like_table_header(label_ln) -> bool:
            # Detect table header cells like "Answer(s)" / "Comment" / "Staff Initials"
            # by structure: multiple bold-ish labels on same row, with option/underscore activity beneath columns.
            rk = _row_key(_y(label_ln))
            row = by_row.get(rk, [])
            if not row:
                return False

            row_items = []
            for ln in row:
                tx = _norm(_t(ln))
                if not tx:
                    continue
                if not _is_boldish(ln):
                    continue
                if tx.endswith(":") or tx.endswith("?"):
                    continue
                if not _is_plausible_field_name(tx):
                    continue
                if _looks_like_underscore_guide(tx) or _looks_like_option_row(tx):
                    continue
                if len(tx) > 28:
                    continue
                row_items.append(ln)

            if len(row_items) < 2:
                return False

            # Similar-size constraint.
            sizes = [(_sz(l) or (med_sz or 10.0)) for l in row_items]
            msz = _median(sizes) or (med_sz or 10.0)
            row_items = [l for l in row_items if 0.75 * msz <= (_sz(l) or msz) <= 1.35 * msz]
            if len(row_items) < 2:
                return False

            row_items.sort(key=lambda l: _x(l))
            # Must have visible separation.
            if (_x(row_items[-1]) - _x(row_items[0])) < 0.18 * page_w:
                return False

            y0 = _y(row_items[0])
            line_h = _row_line_h(row_items)

            xs = [_x(l) for l in row_items]
            bounds = []
            for i, ln in enumerate(row_items):
                left = 0.0 if i == 0 else 0.5 * (xs[i - 1] + xs[i])
                right = page_w if i == len(row_items) - 1 else 0.5 * (xs[i] + xs[i + 1])
                bounds.append((left, right, ln))

            # Look beneath for column content (underscore guides or option rows).
            col_hits = 0
            for left, right, ln in bounds:
                hits = 0
                for l2 in lines:
                    yy = _y(l2)
                    if yy <= y0 + 0.35 * line_h:
                        continue
                    if yy > y0 + 6.2 * line_h:
                        continue
                    xx = _x(l2)
                    if xx < left - 2.0 or xx > right + 2.0:
                        continue
                    tx2 = _t(l2)
                    if not tx2 or not tx2.strip():
                        continue
                    if _looks_like_underscore_guide(tx2) or _looks_like_option_row(tx2):
                        hits += 1
                        if hits >= 2:
                            break
                if hits >= 2:
                    col_hits += 1

            # Header row if multiple columns show structured content beneath.
            return col_hits >= 2

        def looks_like_generic_header(label_ln, field_name: str) -> bool:
            fn = _norm(field_name)
            if not fn:
                return False
            if len(fn) > 18:
                return False
            if fn.endswith(":") or fn.endswith("?"):
                return False
            if has_placeholder_near(label_ln):
                return False
            if looks_like_table_header(label_ln):
                return True

            lx = _x(label_ln)
            ly = _y(label_ln)
            line_h = max(10.0, (_sz(label_ln) or med_sz or 10.0) * 1.6)

            # Look for multiple option rows nearby (right or below), a common pattern for "header" cells.
            opt_hits = 0
            for ln in lines:
                yy = _y(ln)
                if yy < ly - 0.3 * line_h:
                    continue
                if yy > ly + 5.6 * line_h:
                    continue
                xx = _x(ln)
                if xx <= lx - 5.0:
                    continue
                if xx > min(0.92 * page_w, lx + 0.60 * page_w):
                    continue
                if _looks_like_option_row(_t(ln)):
                    opt_hits += 1
                    if opt_hits >= 2:
                        return True
            return False

        def is_furniture_here(label_ln, field_name: str) -> bool:
            fn = _norm(field_name)
            if not fn:
                return False
            yy = _y(label_ln)
            in_band = (yy <= header_y) or (yy >= footer_y)
            if not in_band:
                return False
            if fn not in furniture:
                return False
            # Allow if there's a clear data-entry placeholder.
            return not has_placeholder_near(label_ln)

        used = set()
        y_tol = max(4.5, 0.45 * (med_sz or 10.0) * 1.6)

        # Pass A: underscore-guide anchored extraction.
        anchors = []
        for ln in lines:
            tx = _t(ln)
            if not tx or not tx.strip():
                continue
            if _y(ln) < header_y:
                continue
            if _sz(ln) and (_sz(ln) < max(6.5, 0.60 * (med_sz or 10.0))):
                continue
            if _looks_like_underscore_guide(tx):
                anchors.append(ln)

        for anch in anchors:
            ax = _x(anch)
            ay = _y(anch)
            leftish = ax <= 0.25 * page_w

            candidates = []
            for ln in lines:
                tx = _t(ln)
                if not tx or not tx.strip():
                    continue
                if abs(_y(ln) - ay) > y_tol:
                    continue
                if _looks_like_underscore_guide(tx):
                    continue
                if _looks_like_option_row(tx):
                    continue
                if _count_underscores(tx) >= 4:
                    continue
                if (_sz(ln) or 0.0) and (_sz(ln) < max(6.5, 0.62 * (med_sz or 10.0))):
                    continue

                lx = _x(ln)
                if leftish:
                    if lx < max(0.22 * page_w, ax + 35.0):
                        continue
                    if lx > 0.85 * page_w:
                        continue
                    candidates.append(ln)
                else:
                    if lx > ax - 5.0:
                        continue
                    if lx < 0.08 * page_w:
                        continue
                    candidates.append(ln)

            if not candidates:
                continue

            def _cand_score(l):
                tx = _norm(_t(l))
                # Prefer bold, larger, close in y, and more label-like.
                b = 1 if _is_boldish(l) else 0
                sz = _sz(l) or (med_sz or 10.0)
                dy = abs(_y(l) - ay)
                # Prefer non-black slightly if it helps avoid picking faint guides; keep weak.
                nb = 1 if _is_non_black(l) else 0
                # Penalize if it looks like a title-ish fragment (very large) far from anchor.
                return (-b, -sz, dy, -nb, len(tx))

            # Choose candidate closest to appropriate side edge.
            if leftish:
                start_ln = min(
                    candidates,
                    key=lambda l: (
                        _x(l),
                        *_cand_score(l),
                    ),
                )
            else:
                start_ln = max(
                    candidates,
                    key=lambda l: (
                        _x(l),
                        -(_cand_score(l)[0]),  # keep x primary; tie-break via score
                        -(_cand_score(l)[1]),
                        -(_cand_score(l)[2]),
                    ),
                )

            key = (_row_key(_y(start_ln)), int(round(_x(start_ln))), 1 if leftish else 2)
            if key in used:
                continue
            used.add(key)

            # Build name with bold first; if empty or implausible, try allowing non-bold wrapping.
            field_name = _build_field_name(start_ln, lines, page_w, has_left_partner, require_bold=True)
            field_name = _strip_trailing_punct(field_name)
            if not _is_plausible_field_name(field_name):
                field_name2 = _build_field_name(start_ln, lines, page_w, has_left_partner, require_bold=False)
                field_name2 = _strip_trailing_punct(field_name2)
                if _is_plausible_field_name(field_name2):
                    field_name = field_name2

            if not _is_plausible_field_name(field_name):
                continue
            if is_furniture_here(start_ln, field_name):
                continue
            if looks_like_generic_header(start_ln, field_name):
                continue

            out.append({"form_name": form_name, "field_name": field_name, "page": page_index_0 + 1})

        # Pass B: colon labels in the left column.
        # Extend: allow header/footer band only when a placeholder is present nearby/right (to capture footer fields like "Staff Initials:").
        left_field_x_max = 0.22 * page_w

        for ln in lines:
            tx = _t(ln)
            if not tx or not tx.strip():
                continue
            yy = _y(ln)
            in_band = (yy <= header_y) or (yy >= footer_y)
            if _x(ln) >= left_field_x_max:
                continue
            if not _is_boldish(ln):
                continue
            tnorm = _norm(tx)
            if not tnorm.endswith(":"):
                continue

            row = by_row.get(_row_key(yy), [])
            has_right_value = False
            has_right_placeholder = False
            for r in row:
                if r is ln:
                    continue
                if _x(r) <= _x(ln) + 25.0:
                    continue
                rv_raw = _t(r)
                rv = _norm(rv_raw)
                if not rv:
                    continue
                if _looks_like_underscore_guide(rv_raw) or _count_underscores(rv_raw) >= 6:
                    has_right_placeholder = True
                    continue
                if _count_underscores(rv_raw) >= 4:
                    continue
                if _NUM_ONLY_RE.match(rv):
                    continue
                if len(rv) >= 4:
                    has_right_value = True
                    break

            if has_right_value:
                continue

            # If in header/footer band, only accept if there's a clear placeholder.
            if in_band and not (has_right_placeholder or has_placeholder_near(ln)):
                continue

            field_name = _strip_trailing_punct(tnorm)
            if not _is_plausible_field_name(field_name):
                continue
            if is_furniture_here(ln, field_name):
                continue
            if looks_like_generic_header(ln, field_name):
                continue

            out.append({"form_name": form_name, "field_name": field_name, "page": page_index_0 + 1})

        # Pass C: main-column colon labels with a same-row underscore placeholder to the right.
        for ln in lines:
            tx = _t(ln)
            if not tx or not tx.strip():
                continue
            yy = _y(ln)
            if yy <= header_y:
                continue
            if not _is_boldish(ln):
                continue
            tnorm = _norm(tx)
            if not tnorm.endswith(":"):
                continue
            lx = _x(ln)
            if lx < 0.22 * page_w or lx > 0.70 * page_w:
                continue

            row = by_row.get(_row_key(yy), [])
            has_placeholder_right = False
            for r in row:
                if r is ln:
                    continue
                if _x(r) <= lx + 25.0:
                    continue
                rv = _t(r)
                if _looks_like_underscore_guide(rv) or _count_underscores(rv) >= 6:
                    has_placeholder_right = True
                    break
            if not has_placeholder_right:
                continue

            field_name = _strip_trailing_punct(tnorm)
            if not _is_plausible_field_name(field_name):
                continue
            if is_furniture_here(ln, field_name):
                continue
            if looks_like_generic_header(ln, field_name):
                continue

            out.append({"form_name": form_name, "field_name": field_name, "page": page_index_0 + 1})

    # De-duplicate within page/form/field.
    uniq = []
    seen = set()
    for rec in out:
        k = (rec["page"], rec["form_name"], rec["field_name"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(rec)

    return uniq
```
