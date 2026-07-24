```python
import re
import statistics
from bisect import bisect_left, bisect_right

_RE_WS = re.compile(r"\s+")
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

        title = _pick_page_title(lines, page_w, page_h, title_min)
        if title:
            current_form = title

        ys = [ln.y0 for ln in lines]  # already sorted by y then x
        header_bands = _detect_header_bands(lines, page_w, med_sz)

        page_seen = set()

        # 1) Code-anchored extraction (primary).
        var_codes = [ln for ln in lines if _is_var_code_line(ln)]
        for code_ln in var_codes:
            label = _label_for_code(code_ln, lines, ys, page_w, med_sz, header_bands)
            if label:
                key = (current_form, label)
                if key not in page_seen:
                    page_seen.add(key)
                    out.append({"form_name": current_form or "", "field_name": label, "page": page_index0 + 1})

        # 2) Row labels with clear options to the right (table rows/blocks).
        for label in _row_labels_with_right_options(lines, ys, page_w, med_sz, header_bands):
            key = (current_form, label)
            if key not in page_seen:
                page_seen.add(key)
                out.append({"form_name": current_form or "", "field_name": label, "page": page_index0 + 1})

        # 3) Labels followed shortly by a var code (plain label->code patterns).
        for label in _labels_followed_by_code(lines, ys, page_w, med_sz, header_bands):
            key = (current_form, label)
            if key not in page_seen:
                page_seen.add(key)
                out.append({"form_name": current_form or "", "field_name": label, "page": page_index0 + 1})

    return out


def _clean_text(s):
    s = (s or "").strip()
    return _RE_WS.sub(" ", s)


def _word_count(s):
    s = _clean_text(s)
    if not s:
        return 0
    return len([w for w in s.split(" ") if w])


def _is_annotation_text(t):
    t = (t or "").lstrip()
    return t.startswith("[")


def _is_var_code_line(ln):
    if not ln.text or not ln.non_black:
        return False
    t = ln.text.strip()
    if not _RE_VAR_CODE.match(t):
        return False
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
    cands.sort(reverse=True)
    return cands[0][3]


def _detect_header_bands(lines, page_w, med_sz):
    # Identify y-bands that look like header rows (multiple spanning labels across the page).
    bands = set()
    buckets = {}
    for ln in lines:
        if not ln.text:
            continue
        if _is_annotation_text(ln.text):
            continue
        txt = _clean_text(ln.text)
        if not txt:
            continue
        # Allow slightly smaller headers if bold; many option headers are not much larger than body.
        if not (ln.size >= med_sz + 0.2 or ln.bold):
            continue
        yb = int(round(ln.y0 / 4.0))
        buckets.setdefault(yb, []).append(ln)

    for yb, group in buckets.items():
        if len(group) < 3:
            continue
        xs = [g.x0 for g in group]
        if (max(xs) - min(xs)) < page_w * 0.55:
            continue
        bold_n = sum(1 for g in group if g.bold)
        avg_sz = sum(g.size for g in group) / float(len(group))
        if bold_n >= 2 or avg_sz >= med_sz + 0.6:
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
    t = (txt or "").strip()
    if len(t) <= 8 and re.match(r"^[A-Za-z]{2,5}\s*\d+\s*$", t):
        return True
    if len(t) <= 6 and re.match(r"^\d+\s*$", t):
        return True
    return False


def _looks_like_paragraph(txt):
    t = _clean_text(txt)
    if not t:
        return False
    wc = _word_count(t)
    if wc < 16:
        return False
    punct = t.count(".") + t.count(";") + t.count("!") + t.count("?")
    # Long narrative tends to contain punctuation and start mid-sentence/lowercase.
    if punct >= 1 and not t.rstrip().endswith("?") and ":" not in t:
        if t and t[0].islower():
            return True
        if punct >= 2:
            return True
    return False


def _label_quality_ok(label):
    if not label:
        return False
    if len(label) > 240:
        return False
    if _looks_like_short_row_marker(label):
        return False
    if _looks_like_paragraph(label):
        return False
    # Structural junk: bracket artifacts usually indicate technical annotations leaking in.
    if "[" in label or "]" in label:
        return False
    return True


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


def _count_peer_short_items_same_row(lines, ys, ln, page_w, max_len=18):
    # Count other short non-annotation texts near same y; used to detect option rows.
    y0 = ln.y0 - 5.0
    y1 = ln.y0 + 5.0
    lo, hi = _window(lines, ys, y0, y1)
    n = 0
    for j in range(lo, hi):
        r = lines[j]
        if r is ln:
            continue
        if not r.text or _is_annotation_text(r.text):
            continue
        t = _clean_text(r.text)
        if not t:
            continue
        if len(t) <= max_len and r.size >= ln.size - 0.8 and r.size <= ln.size + 1.2:
            # ignore far-left tiny artifacts; focus on row-like clusters across the page
            if r.x0 > page_w * 0.18:
                n += 1
    return n


def _is_option_like_candidate(lines, ys, ln, label_txt):
    # Option-like: short token among multiple peers on same row, without label cues.
    t = _clean_text(label_txt)
    if not t:
        return True
    if t.endswith(":") or t.endswith("?"):
        return False
    wc = _word_count(t)
    if wc >= 4:
        return False
    if len(t) > 14:
        return False
    peer = _count_peer_short_items_same_row(lines, ys, ln, page_w=max((x.x1 for x in lines), default=1.0) or 1.0)
    return peer >= 2


def _nearest_left_label(lines, ys, code_ln, page_w, header_bands, y_pad=70.0):
    lo, hi = _window(lines, ys, code_ln.y0 - y_pad, code_ln.y0 + y_pad)
    best = None
    best_score = None
    for i in range(lo, hi):
        ln = lines[i]
        if not ln.text or _is_annotation_text(ln.text):
            continue
        if ln.x0 > page_w * 0.65:
            continue
        if _in_header_band(ln, header_bands):
            continue

        # Must be to the left of the code for right-column codes (prevents picking option tokens).
        if code_ln.x0 > page_w * 0.52 and ln.x1 > code_ln.x0 - 8.0:
            continue

        txt = _clean_text(ln.text)
        if not _label_quality_ok(txt):
            continue

        dy = abs(ln.y0 - code_ln.y0)
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
        if ln.x0 > page_w * 0.78:
            continue
        txt = _clean_text(ln.text)
        if not _label_quality_ok(txt):
            continue
        dy = code_ln.y0 - ln.y0
        if dy < 0:
            continue
        if best_dy is None or dy < best_dy:
            best_dy = dy
            best = i
    return best


def _nearest_above_near_code(lines, ys, code_ln, page_w, header_bands, y_pad=140.0):
    # Catch "label above entry area" patterns (e.g., conditional follow-ups like "If ... describe").
    lo, hi = _window(lines, ys, code_ln.y0 - y_pad, code_ln.y0 - 4.0)
    best = None
    best_score = None
    code_cx = (code_ln.x0 + code_ln.x1) / 2.0
    for i in range(hi - 1, lo - 1, -1):
        ln = lines[i]
        if not ln.text or _is_annotation_text(ln.text):
            continue
        if _in_header_band(ln, header_bands):
            continue
        if ln.x0 > page_w * 0.78:
            continue

        txt = _clean_text(ln.text)
        if not _label_quality_ok(txt):
            continue

        # Must plausibly be a label for this entry area: near in x and not to the right of the code.
        ln_cx = (ln.x0 + ln.x1) / 2.0
        if abs(ln_cx - code_cx) > 140.0 and abs(ln.x0 - code_ln.x0) > 120.0:
            continue
        if ln.x0 > code_ln.x0 + 25.0:
            continue

        # Avoid selecting short option tokens in clustered rows.
        if _is_option_like_candidate(lines, ys, ln, txt):
            continue

        dy = code_ln.y0 - ln.y0
        dx = abs(ln_cx - code_cx)
        score = dy + 0.10 * dx
        if best_score is None or score < best_score:
            best_score = score
            best = i
    return best


def _nearest_col_header(lines, ys, code_ln, page_w, med_sz, header_bands, y_pad=160.0):
    lo, hi = _window(lines, ys, code_ln.y0 - y_pad, code_ln.y0 - 10.0)
    best = None
    best_score = None
    for i in range(lo, hi):
        ln = lines[i]
        if not ln.text or _is_annotation_text(ln.text):
            continue
        if ln.size < med_sz + 0.2 and not ln.bold:
            continue
        if not _in_header_band(ln, header_bands):
            continue

        if abs(ln.x0 - code_ln.x0) > 85.0 and abs((ln.x0 + ln.x1) / 2.0 - code_ln.x0) > 95.0:
            continue

        txt = _clean_text(ln.text)
        if not txt:
            continue
        if len(txt) <= 3:
            continue
        if _looks_like_short_row_marker(txt):
            continue
        if "[" in txt or "]" in txt:
            continue

        dy = code_ln.y0 - ln.y0
        dx = abs((ln.x0 + ln.x1) / 2.0 - code_ln.x0)
        score = dy + 0.15 * dx
        if best_score is None or score < best_score:
            best_score = score
            best = i
    return best


def _label_for_code(code_ln, lines, ys, page_w, med_sz, header_bands):
    # 0) Prefer a nearby label just above the entry area (works for many layouts).
    idx = _nearest_above_near_code(lines, ys, code_ln, page_w, header_bands, y_pad=150.0)

    # 1) If not found, fall back to the older heuristics.
    if idx is None:
        if code_ln.x0 > page_w * 0.52:
            idx = _nearest_left_label(lines, ys, code_ln, page_w, header_bands, y_pad=90.0)
            if idx is None:
                idx = _nearest_left_label(lines, ys, code_ln, page_w, header_bands, y_pad=240.0)
        else:
            idx = _nearest_aligned_above(lines, ys, code_ln, page_w, header_bands, y_pad=95.0, x_tol=38.0)
            if idx is None:
                idx = _nearest_left_label(lines, ys, code_ln, page_w, header_bands, y_pad=80.0)

    if idx is None:
        return ""

    base = lines[idx]
    label = _join_wrapped(lines, idx, page_w, max_lines=6)
    if not _label_quality_ok(label):
        return ""

    # Avoid option tokens/anchors accidentally selected as "labels".
    if _is_option_like_candidate(lines, ys, base, label):
        return ""

    # If a table header applies, append it to disambiguate per-column entry fields.
    col_idx = _nearest_col_header(lines, ys, code_ln, page_w, med_sz, header_bands, y_pad=170.0)
    if col_idx is not None:
        col = _clean_text(lines[col_idx].text)
        if col and _label_quality_ok(col) and len(col) > 3 and col.lower() != label.lower():
            # Prevent turning option headers into fields; only use as disambiguating suffix.
            if not _is_option_like_candidate(lines, ys, lines[col_idx], col):
                label = _clean_text(label + " " + col)

    # Don't emit headers alone for left-column codes.
    if _in_header_band(base, header_bands) and code_ln.x0 < page_w * 0.52:
        return ""

    return label


def _row_labels_with_right_options(lines, ys, page_w, med_sz, header_bands):
    labels = []
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
        if not _label_quality_ok(txt):
            continue

        # Avoid short option tokens (e.g., single-word anchors in option blocks).
        if _word_count(txt) < 2 and len(txt) < 10:
            continue
        if _is_option_like_candidate(lines, ys, ln, txt):
            continue

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
            if len(rtxt) <= 22 and r.size >= med_sz + 0.5:
                opt += 1
        if opt >= 2:
            labels.append(txt)

    return _dedupe_preserve_order(labels)


def _labels_followed_by_code(lines, ys, page_w, med_sz, header_bands):
    labels = []
    var_codes = [ln for ln in lines if _is_var_code_line(ln)]
    if not var_codes:
        return labels

    for i, ln in enumerate(lines):
        if not ln.text or _is_annotation_text(ln.text):
            continue
        if ln.x0 > page_w * 0.70:
            continue
        if _in_header_band(ln, header_bands):
            continue
        if ln.size > med_sz + 2.3:
            continue

        txt0 = _clean_text(ln.text)
        if not _label_quality_ok(txt0):
            continue

        # Extra guard: prevent long narrative instructions from becoming fields.
        if _word_count(txt0) >= 14 and not (ln.bold or txt0.endswith("?") or txt0.endswith(":")):
            continue

        if _is_option_like_candidate(lines, ys, ln, txt0):
            continue

        y0 = ln.y0 + 4.0
        y1 = ln.y0 + 90.0
        lo, hi = _window(lines, ys, y0, y1)

        code_found = False
        for j in range(lo, hi):
            c = lines[j]
            if not _is_var_code_line(c):
                continue
            # Accept either vertical alignment OR "entry area to the right" patterns.
            if abs(c.x0 - ln.x0) <= 65.0:
                code_found = True
                break
            if c.x0 > ln.x1 + 18.0 and c.x0 < page_w * 0.92:
                code_found = True
                break

        if not code_found:
            continue

        label = _join_wrapped(lines, i, page_w, max_lines=6)
        if _label_quality_ok(label) and not _is_option_like_candidate(lines, ys, ln, label):
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
```
