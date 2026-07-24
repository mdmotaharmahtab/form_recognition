import re
import statistics
from bisect import bisect_left, bisect_right

_RE_WS = re.compile(r"\s+")
_RE_TOC_ITEM = re.compile(r"^\s*\d+(?:\.\d+)+\.\s+")
_RE_VAR_CODE = re.compile(r"^\[[A-Z][A-Z0-9_]{1,}\]$")


def extract(pages):
    out = []
    current_form = ""

    for page_index0, lines in pages:
        if not lines:
            continue

        page_w = max((ln.x1 for ln in lines), default=0.0) or 1.0
        page_h = max((ln.y1 for ln in lines), default=0.0) or 1.0

        sizes = [ln.size for ln in lines if ln.text]
        if not sizes:
            continue
        med_sz = statistics.median(sizes)
        max_sz = max(sizes)
        title_min = max(med_sz + 4.0, max_sz - 1.6)

        # Update form_name if a prominent top title exists.
        title = _pick_page_title(lines, page_w, page_h, title_min)
        if title:
            current_form = title

        # Skip TOC/index-like listing pages.
        if _is_toc_page(lines, page_w, med_sz):
            continue

        ys = [ln.y0 for ln in lines]  # already sorted by y then x
        header_bands = _detect_header_bands(lines, page_w, med_sz)

        page_seen = set()

        # 1) Code-anchored extraction (covers most fields, including table cells).
        var_codes = [ln for ln in lines if _is_var_code_line(ln)]
        for code_ln in var_codes:
            label = _label_for_code(code_ln, lines, ys, page_w, med_sz, header_bands)
            if label:
                key = (current_form, label)
                if key not in page_seen:
                    page_seen.add(key)
                    out.append(
                        {"form_name": current_form or "", "field_name": label, "page": page_index0 + 1}
                    )

        # 2) Row labels that clearly have fillable options to the right (table rows/blocks).
        for label in _row_labels_with_right_options(lines, ys, page_w, med_sz, header_bands):
            key = (current_form, label)
            if key not in page_seen:
                page_seen.add(key)
                out.append({"form_name": current_form or "", "field_name": label, "page": page_index0 + 1})

        # 3) Labels followed shortly by a var code at similar x (for plain label->code patterns).
        for label in _labels_followed_by_code(lines, ys, page_w, med_sz, header_bands):
            key = (current_form, label)
            if key not in page_seen:
                page_seen.add(key)
                out.append({"form_name": current_form or "", "field_name": label, "page": page_index0 + 1})

    return out


def _clean_text(s):
    s = (s or "").strip()
    return _RE_WS.sub(" ", s)


def _is_annotation_text(t):
    t = (t or "").lstrip()
    return t.startswith("[")


def _is_var_code_line(ln):
    if not ln.text or not ln.non_black:
        return False
    t = ln.text.strip()
    if not _RE_VAR_CODE.match(t):
        return False
    # Exclude common technical markers even if uppercase-bracketed (rare but safe).
    inner = t[1:-1]
    if inner.startswith("TYPE") or inner.startswith("VISIBILITY") or inner.startswith("READ"):
        return False
    return True


def _pick_page_title(lines, page_w, page_h, title_min):
    cands = []
    for ln in lines:
        if not ln.text:
            continue
        if _is_annotation_text(ln.text):
            continue
        if ln.y0 > page_h * 0.28:
            continue
        if ln.x0 > page_w * 0.70:
            continue
        if ln.size < title_min:
            continue
        if not (ln.non_black or ln.bold):
            continue
        txt = _clean_text(ln.text)
        if not txt:
            continue
        cands.append((ln.size, -ln.y0, -ln.x0, txt))
    if not cands:
        return ""
    # Prefer largest font; then highest on page; then leftmost.
    cands.sort(reverse=True)
    return cands[0][3]


def _is_toc_page(lines, page_w, med_sz):
    # Many blue-ish non-black numbered items, aligned left, no red annotations.
    toc_like = 0
    ann = 0
    for ln in lines:
        t = (ln.text or "").strip()
        if not t:
            continue
        if _is_annotation_text(t):
            ann += 1
            continue
        if ln.non_black and ln.x0 < page_w * 0.55 and ln.size >= med_sz + 3.0 and _RE_TOC_ITEM.match(t):
            toc_like += 1
    return toc_like >= 10 and ann == 0


def _detect_header_bands(lines, page_w, med_sz):
    # Identify y-bands that look like table header rows (multiple larger labels spanning page).
    bands = set()
    buckets = {}
    for ln in lines:
        if not ln.text:
            continue
        if _is_annotation_text(ln.text):
            continue
        if ln.size < med_sz + 0.8:
            continue
        yb = int(round(ln.y0 / 4.0))  # tolerant binning
        buckets.setdefault(yb, []).append(ln)

    for yb, group in buckets.items():
        if len(group) < 3:
            continue
        xs = [g.x0 for g in group]
        if (max(xs) - min(xs)) < page_w * 0.55:
            continue
        bands.add(yb)
    return bands


def _yb(ln):
    return int(round(ln.y0 / 4.0))


def _in_header_band(ln, header_bands):
    yb = _yb(ln)
    return (yb in header_bands) or ((yb - 1) in header_bands) or ((yb + 1) in header_bands)


def _window(lines, ys, y0, y1):
    lo = bisect_left(ys, y0)
    hi = bisect_right(ys, y1)
    return lo, hi


def _looks_like_short_row_marker(txt):
    # Avoid emitting "Row 1"-like markers without hardcoding the word.
    t = (txt or "").strip()
    if len(t) <= 8 and re.match(r"^[A-Za-z]{2,5}\s*\d+\s*$", t):
        return True
    if len(t) <= 6 and re.match(r"^\d+\s*$", t):
        return True
    return False


def _join_wrapped(lines, start_i, page_w, max_lines=6):
    base = lines[start_i]
    parts = [_clean_text(base.text)]
    if not parts[0]:
        return ""

    base_x = base.x0
    base_sz = base.size
    base_bold = base.bold

    last = base
    taken = 1
    i = start_i + 1
    while i < len(lines) and taken < max_lines:
        ln = lines[i]
        if not ln.text or _is_annotation_text(ln.text):
            break
        if ln.x0 > page_w * 0.58:
            break
        gap = ln.y0 - last.y1
        if gap > 14.0:
            break

        same_col = abs(ln.x0 - base_x) <= 26.0
        indented_cont = (ln.x0 >= base_x + 16.0) and (ln.x0 <= base_x + 80.0)
        size_ok = abs(ln.size - base_sz) <= 1.6
        bold_ok = (ln.bold == base_bold)

        if size_ok and ((same_col and bold_ok) or indented_cont):
            txt = _clean_text(ln.text)
            if not txt:
                break
            parts.append(txt)
            last = ln
            taken += 1
            i += 1
            continue
        break

    return _clean_text(" ".join(parts))


def _nearest_left_label(lines, ys, code_ln, page_w, header_bands, y_pad=70.0):
    # Find nearest plausible label in the left question column near the code's y.
    lo, hi = _window(lines, ys, code_ln.y0 - y_pad, code_ln.y0 + y_pad)
    best = None
    best_score = None
    for i in range(lo, hi):
        ln = lines[i]
        if not ln.text or _is_annotation_text(ln.text):
            continue
        if ln.x0 > page_w * 0.48:
            continue
        if _in_header_band(ln, header_bands):
            continue
        txt = _clean_text(ln.text)
        if not txt or _looks_like_short_row_marker(txt):
            continue

        dy = abs(ln.y0 - code_ln.y0)
        # Prefer bold / question-like by a small bonus, but keep language-agnostic.
        bonus = 0.0
        if ln.bold:
            bonus -= 6.0
        if "?" in txt:
            bonus -= 4.0
        score = dy + 0.05 * abs(ln.x0 - (page_w * 0.08)) + bonus
        if best_score is None or score < best_score:
            best_score = score
            best = i
    return best


def _nearest_aligned_above(lines, ys, code_ln, page_w, header_bands, y_pad=90.0, x_tol=34.0):
    # For left-column codes, prefer a label just above at similar x.
    lo, hi = _window(lines, ys, code_ln.y0 - y_pad, code_ln.y0 + 5.0)
    best = None
    best_dy = None
    for i in range(hi - 1, lo - 1, -1):
        ln = lines[i]
        if not ln.text or _is_annotation_text(ln.text):
            continue
        if _in_header_band(ln, header_bands):
            continue
        if abs(ln.x0 - code_ln.x0) > x_tol:
            continue
        if ln.x0 > page_w * 0.65:
            continue
        txt = _clean_text(ln.text)
        if not txt or _looks_like_short_row_marker(txt):
            continue
        dy = code_ln.y0 - ln.y0
        if dy < 0:
            continue
        if best_dy is None or dy < best_dy:
            best_dy = dy
            best = i
    return best


def _nearest_col_header(lines, ys, code_ln, page_w, med_sz, header_bands, y_pad=160.0):
    # Look for a table/question column header above the code near the same x.
    lo, hi = _window(lines, ys, code_ln.y0 - y_pad, code_ln.y0 - 10.0)
    best = None
    best_score = None
    for i in range(lo, hi):
        ln = lines[i]
        if not ln.text or _is_annotation_text(ln.text):
            continue
        if ln.size < med_sz + 0.7:
            continue
        if not _in_header_band(ln, header_bands):
            continue

        # x proximity
        if abs(ln.x0 - code_ln.x0) > 85.0 and abs((ln.x0 + ln.x1) / 2.0 - code_ln.x0) > 95.0:
            continue

        txt = _clean_text(ln.text)
        if not txt:
            continue
        # Avoid option-like 1-3 char headers (e.g., Yes/No)
        if len(txt) <= 3:
            continue
        if _looks_like_short_row_marker(txt):
            continue

        dy = code_ln.y0 - ln.y0
        dx = abs((ln.x0 + ln.x1) / 2.0 - code_ln.x0)
        score = dy + 0.15 * dx
        if best_score is None or score < best_score:
            best_score = score
            best = i
    return best


def _label_for_code(code_ln, lines, ys, page_w, med_sz, header_bands):
    # Prefer a nearby left label; fall back to aligned-above label for same-column fields.
    idx = None
    if code_ln.x0 > page_w * 0.52:
        # Some layouts place the red var code well below the human label (after answer options).
        # Try a tight window first; if nothing found, expand upward/downward substantially.
        idx = _nearest_left_label(lines, ys, code_ln, page_w, header_bands, y_pad=90.0)
        if idx is None:
            idx = _nearest_left_label(lines, ys, code_ln, page_w, header_bands, y_pad=240.0)
    else:
        idx = _nearest_aligned_above(lines, ys, code_ln, page_w, header_bands, y_pad=95.0, x_tol=38.0)
        if idx is None:
            idx = _nearest_left_label(lines, ys, code_ln, page_w, header_bands, y_pad=70.0)

    if idx is None:
        return ""

    base = lines[idx]
    label = _join_wrapped(lines, idx, page_w, max_lines=6)
    if not label:
        return ""

    # If a table header applies, append it to disambiguate per-column entry fields.
    col_idx = _nearest_col_header(lines, ys, code_ln, page_w, med_sz, header_bands, y_pad=170.0)
    if col_idx is not None:
        col = _clean_text(lines[col_idx].text)
        if col and len(col) > 3 and col.lower() != label.lower():
            label = _clean_text(label + " " + col)

    # Structural junk filtering (no literal blocklists).
    if len(label) > 240:
        return ""
    if _looks_like_short_row_marker(label):
        return ""
    # Don't emit headers alone.
    if _in_header_band(base, header_bands) and code_ln.x0 < page_w * 0.52:
        return ""

    return label


def _row_labels_with_right_options(lines, ys, page_w, med_sz, header_bands):
    labels = []
    # Find left-side row labels that have multiple short option texts to the right on same y band.
    for i, ln in enumerate(lines):
        if not ln.text or _is_annotation_text(ln.text):
            continue
        if ln.x0 > page_w * 0.40:
            continue
        if _in_header_band(ln, header_bands):
            continue
        if ln.size > med_sz + 1.8:
            continue
        txt = _clean_text(ln.text)
        if not txt or _looks_like_short_row_marker(txt):
            continue

        # Count right-side short items at similar y (options).
        y0 = ln.y0 - 6.0
        y1 = ln.y0 + 6.0
        lo, hi = _window(lines, ys, y0, y1)
        opt = 0
        for j in range(lo, hi):
            r = lines[j]
            if not r.text or _is_annotation_text(r.text):
                continue
            if r.x0 < page_w * 0.55:
                continue
            rtxt = _clean_text(r.text)
            if not rtxt:
                continue
            if len(rtxt) <= 22 and r.size >= med_sz + 0.7:
                opt += 1
        if opt >= 2:
            labels.append(txt)
    return _dedupe_preserve_order(labels)


def _labels_followed_by_code(lines, ys, page_w, med_sz, header_bands):
    labels = []
    # A label is a non-annotation line in left/mid columns followed shortly by a var-code at similar x.
    var_codes = [ln for ln in lines if _is_var_code_line(ln)]
    if not var_codes:
        return labels

    # Build quick access of code lines by y window (linear scan via bisect).
    for i, ln in enumerate(lines):
        if not ln.text or _is_annotation_text(ln.text):
            continue
        if ln.x0 > page_w * 0.65:
            continue
        if _in_header_band(ln, header_bands):
            continue
        if ln.size > med_sz + 2.3:
            continue
        txt0 = _clean_text(ln.text)
        if not txt0 or _looks_like_short_row_marker(txt0):
            continue

        # Look ahead for a var code within ~70 pts and similar x.
        y0 = ln.y0 + 4.0
        y1 = ln.y0 + 75.0
        lo, hi = _window(lines, ys, y0, y1)
        code_found = False
        for j in range(lo, hi):
            c = lines[j]
            if not _is_var_code_line(c):
                continue
            if abs(c.x0 - ln.x0) <= 40.0:
                code_found = True
                break
        if not code_found:
            continue

        # Join wrapped label lines until the code (bounded).
        label = _join_wrapped(lines, i, page_w, max_lines=6)
        if label and len(label) <= 240 and not _looks_like_short_row_marker(label):
            labels.append(label)

    return _dedupe_preserve_order(labels)


def _dedupe_preserve_order(seq):
    seen = set()
    out = []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
