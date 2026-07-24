```python
import re
import statistics
from bisect import bisect_left, bisect_right

_RE_WS = re.compile(r"\s+")
_RE_VAR_CODE = re.compile(r"^\[[A-Z][A-Z0-9_]{1,}\]$")
_RE_ROW_MARKER_TAIL = re.compile(r"(?:\s+|\b)(?:Row|ROWS?)\s*\d+\s*$", re.IGNORECASE)
_RE_ARTICLE_START = re.compile(r"^(?:A|An|The)\b")


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
            if _is_read_only_near_code(lines, ys, code_ln, page_w):
                continue

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
    # Identify y-bands that look like header rows:
    # many short labels spanning across the page on same y.
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

        # Relax size gating: many column headers are body-sized.
        if not (ln.size >= med_sz - 0.2 or ln.bold or len(txt) <= 18):
            continue

        yb = int(round(ln.y0 / 4.0))
        buckets.setdefault(yb, []).append((ln, txt))

    for yb, group in buckets.items():
        if len(group) < 3:
            continue

        xs = [g[0].x0 for g in group]
        span = max(xs) - min(xs)
        if span < page_w * 0.55:
            continue

        texts = [g[1] for g in group]
        short_n = sum(1 for t in texts if len(t) <= 18 and _word_count(t) <= 3 and not t.endswith("?") and not t.endswith(":"))
        short_ratio = short_n / float(len(texts))

        avg_wc = sum(_word_count(t) for t in texts) / float(len(texts))
        bold_n = sum(1 for g in group if g[0].bold)

        # Heuristic: headers are mostly short, often bold, and wide-spanning.
        if short_ratio >= 0.75 and avg_wc <= 3.6:
            bands.add(yb)
            continue
        if len(group) >= 4 and span >= page_w * 0.60 and (bold_n >= 2 or short_ratio >= 0.60) and avg_wc <= 4.2:
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
    if t.endswith("?") or t.endswith(":"):
        return False

    wc = _word_count(t)
    if wc < 16:
        # Still treat short sentence fragments (common in definition blocks) as prose.
        if wc >= 6 and (t.endswith(".") or t.endswith(";")):
            return True
        if wc >= 8 and ("," in t) and not _is_promptish_text(t):
            return True
        return False

    periods = t.count(".")
    qmarks = t.count("?")
    excl = t.count("!")
    semis = t.count(";")
    commas = t.count(",")

    # Narrative/definitions tend to be long and punctuated; many are not questions.
    if wc >= 26:
        return True
    if wc >= 18 and (periods >= 1 or semis >= 1):
        return True
    if wc >= 20 and (periods >= 1 or semis >= 1 or commas >= 2):
        return True
    if (periods + semis + excl) >= 1 and qmarks == 0:
        return True

    # Often starts mid-sentence or reads like prose.
    if t and t[0].islower():
        return True
    return False


def _is_promptish_text(label):
    t = _clean_text(label)
    if not t:
        return False
    if t.endswith("?") or t.endswith(":"):
        return True

    first = (t.split(" ", 1)[0] if t else "").lower()
    # Generic prompt starters (kept broad; not doc-specific).
    if first in {
        "was", "were", "is", "are",
        "do", "does", "did",
        "have", "has", "had",
        "can", "could", "should", "would", "will",
        "if", "date", "time", "reason", "describe", "specify", "please"
    }:
        return True

    return False


def _is_definition_like_text(label):
    t = _clean_text(label)
    if not t:
        return False

    if t.endswith(".") or t.endswith(";"):
        return True

    wc = _word_count(t)
    if wc >= 8 and not _is_promptish_text(t):
        # Definition sentences commonly include clause punctuation but are not prompts.
        if "," in t or ";" in t:
            return True
        if "(" in t or ")" in t or "\"" in t:
            return True

    # Article-led definitional sentences (avoid over-matching short headings).
    if wc >= 10 and _RE_ARTICLE_START.match(t) and not _is_promptish_text(t):
        if "," in t or "." in t or ";" in t:
            return True

    return False


def _label_quality_ok(label):
    if not label:
        return False
    label = _clean_text(label)
    if not label:
        return False
    if len(label) > 240:
        return False

    if _RE_ROW_MARKER_TAIL.search(label):
        return False
    if _looks_like_short_row_marker(label):
        return False
    if _looks_like_paragraph(label):
        return False

    # Filter definition/instruction sentence fragments that sneak past paragraph heuristics.
    if _is_definition_like_text(label):
        return False

    # If it's long, require it to read like a prompt.
    wc = _word_count(label)
    if wc >= 18 and not (label.endswith("?") or label.endswith(":")):
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
        if len(t) <= max_len and r.size >= ln.size - 0.9 and r.size <= ln.size + 1.3:
            if r.x0 > page_w * 0.18:
                n += 1
    return n


def _count_peer_short_items_same_col(lines, ys, ln, page_w, y_pad=80.0, x_tol=34.0, max_len=18):
    lo, hi = _window(lines, ys, ln.y0 - y_pad, ln.y0 + y_pad)
    n = 0
    for j in range(lo, hi):
        r = lines[j]
        if r is ln:
            continue
        if not r.text or _is_annotation_text(r.text):
            continue
        if abs(r.x0 - ln.x0) > x_tol:
            continue
        t = _clean_text(r.text)
        if not t:
            continue
        if len(t) <= max_len and _word_count(t) <= 3 and not t.endswith("?") and not t.endswith(":"):
            if r.size >= ln.size - 0.9 and r.size <= ln.size + 1.3:
                n += 1
    return n


def _is_option_like_candidate(lines, ys, ln, label_txt, page_w):
    t = _clean_text(label_txt)
    if not t:
        return True

    # Prompts often end with ":" or "?".
    if t.endswith(":") or t.endswith("?"):
        return False

    wc = _word_count(t)
    if wc >= 4:
        return False
    if len(t) > 14:
        return False

    # Row-style option clusters across the page.
    peer_row = _count_peer_short_items_same_row(lines, ys, ln, page_w=page_w)
    if peer_row >= 2:
        return True

    # Vertical option lists (checkbox/radio stacks) usually aren't far-left labels.
    if ln.x0 > page_w * 0.22:
        peer_col = _count_peer_short_items_same_col(lines, ys, ln, page_w=page_w)
        if peer_col >= 2:
            return True

    return False


def _is_read_only_near_code(lines, ys, code_ln, page_w):
    # Be specific: only treat as read-only if the nearby annotation is in the same column/zone.
    lo, hi = _window(lines, ys, code_ln.y0 - 34.0, code_ln.y0 + 34.0)
    for i in range(lo, hi):
        ln = lines[i]
        if not ln.text:
            continue
        t = ln.text.strip()
        if not t.startswith("["):
            continue
        tl = t.lower()
        if "read-only" not in tl and "readonly" not in tl:
            continue

        # Require rough column alignment to avoid skipping unrelated codes on the same page.
        x_tol = 120.0 if code_ln.x0 <= page_w * 0.55 else 150.0
        if abs(ln.x0 - code_ln.x0) > x_tol and abs((ln.x0 + ln.x1) / 2.0 - (code_ln.x0 + code_ln.x1) / 2.0) > x_tol:
            continue

        return True
    return False


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

        if code_ln.x0 > page_w * 0.52 and ln.x1 > code_ln.x0 - 8.0:
            continue

        txt = _clean_text(ln.text)
        if not _label_quality_ok(txt):
            continue

        dy = abs(ln.y0 - code_ln.y0)
        bonus = 0.0
        label = _join_wrapped(lines, i, page_w, max_lines=6)
        if label and _label_quality_ok(label):
            if _is_promptish_text(label):
                bonus -= 7.0
            if ln.bold:
                bonus -= 4.0
        score = dy + 0.05 * abs(ln.x0 - (page_w * 0.08)) + bonus
        if best_score is None or score < best_score:
            best_score = score
            best = i
    return best


def _nearest_aligned_above(lines, ys, code_ln, page_w, header_bands, y_pad=90.0, x_tol=34.0):
    lo, hi = _window(lines, ys, code_ln.y0 - y_pad, code_ln.y0 + 5.0)
    best = None
    best_score = None
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

        label = _join_wrapped(lines, i, page_w, max_lines=6)
        if not _label_quality_ok(label):
            continue

        dy = code_ln.y0 - ln.y0
        if dy < 0:
            continue

        bonus = 0.0
        if _is_promptish_text(label):
            bonus -= 8.0
        if ln.bold:
            bonus -= 3.0

        score = dy + 0.02 * abs(ln.x0 - code_ln.x0) + bonus
        if best_score is None or score < best_score:
            best_score = score
            best = i
    return best


def _nearest_above_near_code(lines, ys, code_ln, page_w, header_bands, y_pad=140.0):
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

        label = _join_wrapped(lines, i, page_w, max_lines=6)
        if not _label_quality_ok(label):
            continue

        ln_cx = (ln.x0 + ln.x1) / 2.0
        if abs(ln_cx - code_cx) > 140.0 and abs(ln.x0 - code_ln.x0) > 120.0:
            continue
        if ln.x0 > code_ln.x0 + 25.0:
            continue

        if _is_option_like_candidate(lines, ys, ln, label, page_w):
            continue

        dy = code_ln.y0 - ln.y0
        dx = abs(ln_cx - code_cx)

        bonus = 0.0
        if _is_promptish_text(label):
            bonus -= 10.0
        if ln.bold:
            bonus -= 4.0

        score = dy + 0.10 * dx + bonus
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
        if not _in_header_band(ln, header_bands):
            continue

        # Column headers can be body-sized; keep a light size guard.
        if ln.size < med_sz - 0.2 and not ln.bold:
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

        # Prevent using long narrative definitions as "headers".
        if len(txt) > 42 or _word_count(txt) > 6:
            continue
        if _is_definition_like_text(txt):
            continue

        dy = code_ln.y0 - ln.y0
        dx = abs((ln.x0 + ln.x1) / 2.0 - code_ln.x0)
        score = dy + 0.15 * dx
        if best_score is None or score < best_score:
            best_score = score
            best = i
    return best


def _promote_option_to_question(lines, ys, option_ln, page_w, header_bands, med_sz):
    # When a short option token gets selected as a "label", try to find a prompt above it.
    lo, hi = _window(lines, ys, option_ln.y0 - 180.0, option_ln.y0 - 6.0)
    best = None
    best_score = None
    for i in range(hi - 1, lo - 1, -1):
        ln = lines[i]
        if not ln.text or _is_annotation_text(ln.text):
            continue
        if _in_header_band(ln, header_bands):
            continue
        if ln.x0 > option_ln.x0 + 60.0:
            continue

        label = _join_wrapped(lines, i, page_w, max_lines=6)
        if not _label_quality_ok(label):
            continue

        wc = _word_count(label)
        is_promptish = _is_promptish_text(label)

        if not is_promptish and wc < 4 and not ln.bold:
            continue

        # Avoid jumping to big form titles unless they really look like prompts.
        if ln.size > med_sz + 3.2 and not is_promptish:
            continue

        if _is_option_like_candidate(lines, ys, ln, label, page_w):
            continue

        dy = option_ln.y0 - ln.y0
        dx = abs(ln.x0 - option_ln.x0)
        bonus = -6.0 if is_promptish else 0.0
        bonus += -3.0 if ln.bold else 0.0
        score = dy + 0.06 * dx + bonus
        if best_score is None or score < best_score:
            best_score = score
            best = label

    return best or ""


def _label_for_code(code_ln, lines, ys, page_w, med_sz, header_bands):
    idx = _nearest_above_near_code(lines, ys, code_ln, page_w, header_bands, y_pad=160.0)

    if idx is None:
        if code_ln.x0 > page_w * 0.52:
            idx = _nearest_left_label(lines, ys, code_ln, page_w, header_bands, y_pad=90.0)
            if idx is None:
                idx = _nearest_left_label(lines, ys, code_ln, page_w, header_bands, y_pad=240.0)
        else:
            idx = _nearest_aligned_above(lines, ys, code_ln, page_w, header_bands, y_pad=105.0, x_tol=42.0)
            if idx is None:
                idx = _nearest_left_label(lines, ys, code_ln, page_w, header_bands, y_pad=90.0)

    if idx is None:
        return ""

    base = lines[idx]
    label = _join_wrapped(lines, idx, page_w, max_lines=6)
    if not _label_quality_ok(label):
        return ""

    # If we accidentally grabbed an option token, try to promote to the question/prompt above.
    if _is_option_like_candidate(lines, ys, base, label, page_w):
        promoted = _promote_option_to_question(lines, ys, base, page_w, header_bands, med_sz)
        if promoted and _label_quality_ok(promoted):
            label = promoted
        else:
            return ""

    # If a table header applies, append it to disambiguate per-column entry fields.
    col_idx = _nearest_col_header(lines, ys, code_ln, page_w, med_sz, header_bands, y_pad=175.0)
    if col_idx is not None:
        col = _clean_text(lines[col_idx].text)
        if col and _label_quality_ok(col) and len(col) > 3 and col.lower() != label.lower():
            if not _is_option_like_candidate(lines, ys, lines[col_idx], col, page_w):
                label = _clean_text(label + " " + col)

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

        label = _join_wrapped(lines, i, page_w, max_lines=4)
        if not _label_quality_ok(label):
            continue

        # Avoid short option tokens.
        if _word_count(label) < 2 and len(label) < 10:
            continue
        if _is_option_like_candidate(lines, ys, ln, label, page_w):
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
            if len(rtxt) <= 22 and r.size >= med_sz - 0.2 and not _looks_like_paragraph(rtxt):
                opt += 1
        if opt >= 2:
            labels.append(label)

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

        label = _join_wrapped(lines, i, page_w, max_lines=6)
        if not _label_quality_ok(label):
            continue

        wc0 = _word_count(label)
        if wc0 >= 14 and not (ln.bold or label.endswith("?") or label.endswith(":")):
            continue

        if _is_option_like_candidate(lines, ys, ln, label, page_w):
            continue

        y0 = ln.y0 + 4.0
        y1 = ln.y0 + 95.0
        lo, hi = _window(lines, ys, y0, y1)

        code_found = False
        for j in range(lo, hi):
            c = lines[j]
            if not _is_var_code_line(c):
                continue
            if _is_read_only_near_code(lines, ys, c, page_w):
                continue
            if abs(c.x0 - ln.x0) <= 65.0:
                code_found = True
                break
            if c.x0 > ln.x1 + 18.0 and c.x0 < page_w * 0.92:
                code_found = True
                break

        if not code_found:
            continue

        if _is_option_like_candidate(lines, ys, ln, label, page_w):
            promoted = _promote_option_to_question(lines, ys, ln, page_w, header_bands, med_sz)
            if promoted and _label_quality_ok(promoted):
                label = promoted
            else:
                continue

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
