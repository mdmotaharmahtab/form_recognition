```python
import re
from typing import List, Tuple, Dict, Any, Optional


_RE_NUM_PREFIX = re.compile(r"^\s*\d+\s*[\.\)]\s+\S")
_RE_TOC_NUM = re.compile(r"^\s*\d+(\.\d+)+\.\s+\S")
_RE_ROW_PREFIX = re.compile(r"^\s*Row\s*\d+\b", re.IGNORECASE)
_RE_JUST_NUMBER = re.compile(r"^\s*\d+\s*$")
_RE_YES_NO_ONLY = re.compile(r"^\s*(yes|no|n/?a|na|unknown)\s*$", re.IGNORECASE)


def _norm_space(s: str) -> str:
    return " ".join((s or "").strip().split())


def _is_bracket_line(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("[") and t.endswith("]") and len(t) >= 2


def _parse_leading_brackets(s: str) -> List[str]:
    # Returns list of bracket bodies for leading [ ... ] blocks.
    t = (s or "").lstrip()
    out = []
    i = 0
    while i < len(t) and t[i] == "[":
        j = t.find("]", i + 1)
        if j == -1:
            break
        body = t[i + 1 : j].strip()
        out.append(body)
        k = j + 1
        # Require whitespace between consecutive leading brackets
        while k < len(t) and t[k].isspace():
            k += 1
        if k < len(t) and t[k] == "[":
            i = k
            continue
        break
    return out


def _leading_brackets_span(s: str) -> int:
    t = (s or "").lstrip()
    i = 0
    last_end = 0
    while i < len(t) and t[i] == "[":
        j = t.find("]", i + 1)
        if j == -1:
            break
        last_end = j + 1
        k = last_end
        while k < len(t) and t[k].isspace():
            k += 1
        if k < len(t) and t[k] == "[":
            i = k
            continue
        break
    return last_end


def _is_meta_bracket_body(body: str) -> bool:
    b = (body or "").strip().lower()
    return (
        b.startswith("type:")
        or b.startswith("visibility:")
        or b.startswith("read-only")
        or b.startswith("readonly")
        or b == "read-only field"
        or b == "read only field"
    )


def _is_var_code_body(body: str) -> bool:
    b = (body or "").strip()
    if not b or " " in b:
        return False
    return re.match(r"^[A-Za-z][A-Za-z0-9_]*$", b) is not None


def _strip_leading_bracket_annotations(text: str) -> str:
    # Remove leading bracketed technical annotations like:
    # [TYPE: ...] [Read-only field] [LBREQ1]
    t = (text or "").strip()
    if not t or not t.lstrip().startswith("["):
        return t

    bodies = _parse_leading_brackets(t)
    if not bodies:
        return t

    # Only strip if ALL leading brackets are "technical"
    for b in bodies:
        if not (_is_meta_bracket_body(b) or _is_var_code_body(b)):
            return t

    span = _leading_brackets_span(t)
    if span <= 0:
        return t
    return t.lstrip()[span:].strip()


def _page_dims(lines) -> Tuple[float, float, float, float]:
    xs0 = [ln.x0 for ln in lines if getattr(ln, "text", None)]
    xs1 = [ln.x1 for ln in lines if getattr(ln, "text", None)]
    ys0 = [ln.y0 for ln in lines if getattr(ln, "text", None)]
    ys1 = [ln.y1 for ln in lines if getattr(ln, "text", None)]
    if not xs0 or not xs1 or not ys0 or not ys1:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs0), max(xs1), min(ys0), max(ys1)


def _footer_band_y(y_max: float) -> float:
    # Dynamic footer band: last ~3% of page height, but at least 18 units.
    if not y_max:
        return 10**9
    return y_max - max(18.0, 0.03 * y_max)


def _is_probably_footer_header(ln, y_max: float) -> bool:
    return (y_max is not None and ln.y0 > _footer_band_y(y_max) and ln.size <= 9.6)


def _looks_like_long_body(t: str, bold: bool) -> bool:
    tt = (t or "").strip()
    if bold:
        return False
    if len(tt) <= 90:
        return False
    # Questions/labels often use ?/: ; long paragraphs tend not to be fields.
    if "?" in tt or ":" in tt:
        return False
    return True


def _is_candidate_label_text(text: str) -> bool:
    t = _norm_space(_strip_leading_bracket_annotations(text))
    if not t:
        return False
    if _is_bracket_line(t):
        return False
    if _RE_ROW_PREFIX.match(t):
        return False
    if _RE_YES_NO_ONLY.match(t):
        return False
    return True


def _clean_label_text(text: str) -> str:
    t = _norm_space(_strip_leading_bracket_annotations(text))
    # If there are still stray bracket artifacts inside, they’re usually technical spillover
    # (labels should not include these).
    if "[" in t and "]" in t and t.strip().startswith("["):
        # Conservative: if it still starts with [, drop it.
        t = _strip_leading_bracket_annotations(t)
        t = _norm_space(t)
    return t


def _is_good_field_label(label: str) -> bool:
    t = _norm_space(label)
    if not t:
        return False
    if _RE_ROW_PREFIX.match(t):
        return False
    if _RE_YES_NO_ONLY.match(t):
        return False
    if _RE_JUST_NUMBER.match(t):
        return False

    # Reject very long “definition paragraph” captures unless they are clearly a question.
    if len(t) > 160 and ("?" not in t):
        return False

    # If moderately long, require it to look like a label/question (not a paragraph).
    if len(t) > 120 and not ("?" in t or ":" in t or _RE_NUM_PREFIX.match(t)):
        return False

    # Avoid option/legend text fragments (usually small, enumerated, and not questions).
    if re.search(r"\(\s*\d+\s*\)", t) and ("?" not in t) and (len(t) > 70):
        return False

    return True


def _looks_like_headerish(t: str, ln) -> bool:
    tt = (t or "").strip()
    if not tt:
        return False
    if _looks_like_long_body(tt, ln.bold):
        return False
    if len(tt) > 70:
        return False
    if ln.bold:
        return True
    if ":" in tt or "?" in tt or _RE_NUM_PREFIX.match(tt):
        return True
    if len(tt) <= 26 and ln.size >= 8.2:
        return True
    return False


def _join_wrapped_label(lines, anchor_idx: int, x_tol: float, y_gap_tol: float) -> str:
    anchor = lines[anchor_idx]
    if not _is_candidate_label_text(anchor.text):
        return ""

    base_x = anchor.x0
    base_size = anchor.size

    def ok_wrap(prev, cur) -> bool:
        if not _is_candidate_label_text(cur.text):
            return False
        if abs(cur.x0 - base_x) > x_tol:
            return False
        if abs(cur.size - base_size) > max(2.4, 0.38 * base_size):
            return False
        gap = cur.y0 - prev.y1
        if gap > y_gap_tol:
            return False
        ct = _clean_label_text(cur.text)
        if _looks_like_long_body(ct, cur.bold):
            return False
        return True

    # Grow up/down with tight geometry, but avoid accidentally pulling in big titles.
    idxs = [anchor_idx]

    # Up
    up = 0
    k = anchor_idx - 1
    prev_top = anchor
    while k >= 0 and up < 2:
        cur = lines[k]
        if not ok_wrap(cur, prev_top):
            break
        # Don’t pull in a “title-like” larger line above.
        if cur.size > base_size + 2.4 and cur.y0 < anchor.y0 - 18:
            break
        idxs.insert(0, k)
        prev_top = cur
        up += 1
        k -= 1

    # Down
    down = 0
    k = anchor_idx + 1
    prev = anchor
    while k < len(lines) and down < 4:
        cur = lines[k]
        if not ok_wrap(prev, cur):
            break
        idxs.append(k)
        prev = cur
        down += 1
        k += 1

    parts = []
    for i in idxs:
        ct = _clean_label_text(lines[i].text)
        if ct:
            parts.append(ct)
    return _norm_space(" ".join(parts))


def _merge_bracket_fragments(lines):
    # Merge vertically stacked non-black bracket fragments like:
    # [TYPE: partialdate]
    # [TYPE: partialtime ...]
    used = [False] * len(lines)
    merged = []
    for i, ln in enumerate(lines):
        if used[i]:
            continue
        t = (ln.text or "").strip()
        if not t or "[" not in t:
            continue
        if not ln.non_black:
            continue

        if t.startswith("[") and ("]" not in t):
            acc = t
            used[i] = True
            y0 = ln.y0
            x0 = ln.x0
            size0 = ln.size
            lasty = ln.y1
            for j in range(i + 1, min(len(lines), i + 7)):
                ln2 = lines[j]
                if used[j]:
                    continue
                if not ln2.non_black:
                    break
                if abs(ln2.x0 - x0) > 4.5:
                    continue
                if abs(ln2.size - size0) > 1.7:
                    continue
                if ln2.y0 - lasty > 18.5:
                    break
                t2 = (ln2.text or "").strip()
                if not t2:
                    continue
                acc += t2
                used[j] = True
                lasty = ln2.y1
                if "]" in acc:
                    break
            merged.append((x0, y0, size0, acc))
        else:
            if t.startswith("[") and "]" in t:
                merged.append((ln.x0, ln.y0, ln.size, t))
    return merged


def _detect_layout_flags(lines, x_min: float, x_max: float, y_max: float) -> Dict[str, bool]:
    w = max(1.0, x_max - x_min)
    left_max = x_min + 0.44 * w

    blue_like = 0
    numbers_col = 0
    schedule_tag = False
    toc_num = 0

    for ln in lines:
        t = (ln.text or "").strip()
        if not t or _is_probably_footer_header(ln, y_max):
            continue

        if t.startswith("Schedule_") and ln.x0 < left_max and ln.size >= 9.0:
            schedule_tag = True

        if _RE_TOC_NUM.match(t) and ln.non_black and ln.x0 < left_max and 10.5 <= ln.size <= 16.5:
            toc_num += 1

        # “Blue links” in these documents are rendered as non-black at small size on the right.
        if ln.non_black and ln.size <= 8.4 and ln.x0 >= left_max and not _is_bracket_line(t):
            blue_like += 1

        if _RE_JUST_NUMBER.match(t) and ln.size <= 8.6 and (x_min + 0.30 * w) <= ln.x0 <= (x_min + 0.55 * w):
            numbers_col += 1

    schedule_like = schedule_tag or (blue_like >= 10 and numbers_col >= 5)
    toc_like = (toc_num >= 8) or (blue_like >= 12 and numbers_col >= 8)

    return {"schedule_like": schedule_like, "toc_like": toc_like}


def _detect_form_title(lines, x_min: float, x_max: float, y_max: float) -> Optional[str]:
    w = max(1.0, x_max - x_min)
    top_band = 0.22 * y_max if y_max else 140.0

    cands = []
    for i, ln in enumerate(lines):
        t0 = (ln.text or "").strip()
        if not t0:
            continue
        if _is_probably_footer_header(ln, y_max):
            continue
        if ln.y0 > top_band:
            continue
        # Keep to left/center area.
        if ln.x0 > x_min + 0.70 * w:
            continue

        t = _clean_label_text(t0)
        if not t:
            continue
        if _RE_TOC_NUM.match(t):
            continue

        # Avoid picking individual field labels as the form title.
        if (("?" in t) or (":" in t) or _RE_NUM_PREFIX.match(t)) and ln.size <= 12.2:
            continue

        # Titles are usually larger or emphasized.
        if ln.size < 9.0 and not (ln.bold and ln.size >= 7.4):
            continue

        # Prefer “... - Page N” style titles when present.
        page_bonus = -8.0 if re.search(r"\bpage\s*\d+\b", t, re.IGNORECASE) else 0.0

        score = ln.y0 * 1.0 + (-ln.size) * 7.0 + (0.02 * max(0.0, ln.x0 - x_min)) + page_bonus
        if ln.bold or ln.non_black:
            score -= 6.0
        cands.append((score, i, t))

    if not cands:
        return None
    cands.sort()
    _, idx, t0 = cands[0]

    # Merge adjacent title lines.
    base = lines[idx]
    parts = [t0]
    last = base
    for _, j, tj in cands[1:8]:
        ln = lines[j]
        if ln.y0 < base.y0 - 2:
            continue
        if ln.y0 - last.y1 > max(4.0, 2.0 * base.size):
            continue
        if abs(ln.x0 - base.x0) > 40:
            continue
        if abs(ln.size - base.size) > 3.8:
            continue
        if _RE_TOC_NUM.match(tj):
            continue
        # Don’t merge something that looks like a field label.
        if ("?" in tj or ":" in tj or _RE_NUM_PREFIX.match(tj)) and ln.size <= 12.2:
            continue
        parts.append(tj)
        last = ln

    title = _norm_space(" ".join(parts))
    if not title or _RE_TOC_NUM.match(title):
        return None
    if len(title) < 4:
        return None
    return title


def _find_label_near_marker(mx: float, my: float, lines, x_min: float, x_max: float, y_max: float) -> str:
    w = max(1.0, x_max - x_min)
    left_max = x_min + 0.44 * w

    x_tol_wrap = max(22.0, 0.04 * w)
    y_gap_tol = 5.0 + 1.9 * 8.0  # typical small font

    def candidate_score(i: int, ln) -> Optional[float]:
        if _is_probably_footer_header(ln, y_max):
            return None

        raw = (ln.text or "").strip()
        if not raw:
            return None
        t = _clean_label_text(raw)
        if not _is_candidate_label_text(t):
            return None
        if _looks_like_long_body(t, ln.bold):
            return None

        dy = ln.y0 - my
        if dy < -280 or dy > 220:
            return None

        # If marker is in right/second column, labels are usually left or above.
        if mx >= left_max:
            # Favor left-column labels close in y, or same-column headers above.
            left_ok = ln.x0 < left_max
            same_col_ok = abs(ln.x0 - mx) <= max(60.0, 0.10 * w)

            if not (left_ok or same_col_ok):
                return None

            if same_col_ok:
                # header above marker
                if dy > 60:
                    return None
                if not _looks_like_headerish(t, ln):
                    return None

            # Avoid picking right-column option/legend text.
            if ln.non_black and ln.size <= 8.4 and ln.x0 >= left_max and ("?" not in t and ":" not in t):
                return None

        else:
            # Left/first column marker: label is typically above in same column.
            if abs(ln.x0 - mx) > max(55.0, 0.10 * w):
                return None
            if dy > 70:
                return None
            if not _looks_like_headerish(t, ln) and not ln.bold:
                # allow non-bold if it's clearly a question/label
                if not ("?" in t or ":" in t or _RE_NUM_PREFIX.match(t)):
                    return None

        sc = abs(dy) * (0.92 if dy < 0 else 1.12)

        # Prefer closer x alignment (esp. same-column headers).
        sc += 0.03 * abs(ln.x0 - mx)

        # Prefer emphasized labels.
        if ln.bold:
            sc *= 0.82
        if ("?" in t) or (":" in t) or _RE_NUM_PREFIX.match(t):
            sc *= 0.88

        # Downweight very top-of-page “title-ish” lines.
        if ln.y0 < 0.18 * y_max and ln.size >= 11.0:
            sc *= 1.25

        return sc

    best_idx = None
    best_sc = None
    for i, ln in enumerate(lines):
        sc = candidate_score(i, ln)
        if sc is None:
            continue
        if best_sc is None or sc < best_sc:
            best_sc = sc
            best_idx = i

    if best_idx is None:
        return ""

    return _join_wrapped_label(lines, best_idx, x_tol=x_tol_wrap, y_gap_tol=y_gap_tol)


def _detect_option_block(lines, x_min: float, x_max: float, y_max: float) -> Optional[Tuple[float, float]]:
    w = max(1.0, x_max - x_min)
    left_max = x_min + 0.44 * w

    opts = []
    for ln in lines:
        t = (ln.text or "").strip()
        if not t:
            continue
        if _is_probably_footer_header(ln, y_max):
            continue
        if not ln.non_black:
            continue
        if ln.size > 8.6:
            continue
        if ln.x0 < left_max:
            continue
        # Structural signal: enumerated options/definitions
        if re.search(r"\(\s*\d+\s*\)", t) or re.search(r"\bdoes not apply\b", t, re.IGNORECASE):
            opts.append(ln)

    if len(opts) < 4:
        return None

    ys = [ln.y0 for ln in opts]
    y_min, y_max2 = min(ys), max(ys)
    if (y_max2 - y_min) < 30:
        return None

    return (y_min, y_max2)


def _extract_left_label_near_band(lines, band: Tuple[float, float], x_min: float, x_max: float, y_max: float) -> List[int]:
    w = max(1.0, x_max - x_min)
    left_max = x_min + 0.44 * w
    y0, y1 = band

    best_idx = None
    best_sc = None

    for i, ln in enumerate(lines):
        if _is_probably_footer_header(ln, y_max):
            continue
        if ln.x0 >= left_max:
            continue
        if ln.y0 < (y0 - 85) or ln.y0 > (y1 + 60):
            continue
        if ln.size < 7.4 or ln.size > 13.8:
            continue

        t = _clean_label_text((ln.text or "").strip())
        if not _is_candidate_label_text(t):
            continue
        if _looks_like_long_body(t, ln.bold):
            continue

        # Prefer bold or slightly larger left labels even if they don't contain punctuation.
        if not ln.bold and ln.size < 8.6 and not ("?" in t or ":" in t or _RE_NUM_PREFIX.match(t)):
            continue

        dy = y0 - ln.y0
        sc = abs(dy)
        if ln.bold:
            sc *= 0.78
        if ln.size >= 9.2:
            sc *= 0.86
        if ("?" in t) or (":" in t) or _RE_NUM_PREFIX.match(t):
            sc *= 0.90
        sc += 0.02 * max(0.0, ln.x0 - x_min)

        if best_sc is None or sc < best_sc:
            best_sc = sc
            best_idx = i

    return [best_idx] if best_idx is not None else []


def _row_table_like(lines) -> bool:
    c = 0
    for ln in lines:
        t = (ln.text or "").strip()
        if not t:
            continue
        if _RE_ROW_PREFIX.match(t):
            c += 1
            if c >= 3:
                return True
    return False


def _extract_row_table_questions(lines, x_min: float, x_max: float, y_max: float) -> List[int]:
    w = max(1.0, x_max - x_min)
    left_max = x_min + 0.52 * w  # row headings may extend a bit right
    idxs = []

    for i, ln in enumerate(lines):
        if _is_probably_footer_header(ln, y_max):
            continue
        if ln.x0 > left_max:
            continue
        if ln.size < 7.2 or ln.size > 12.8:
            continue

        t = _clean_label_text((ln.text or "").strip())
        if not _is_candidate_label_text(t):
            continue
        if _looks_like_long_body(t, ln.bold):
            continue

        # Row headings / numbered items are often fields; keep them shortish.
        if _RE_NUM_PREFIX.match(t):
            if len(t) <= 140:
                idxs.append(i)
            continue

        # Questions / prompts
        if "?" in t:
            if len(t) <= 160:
                idxs.append(i)
            continue

        # Section labels with colon
        if ":" in t and len(t) <= 140:
            idxs.append(i)
            continue

        # “If … describe …” prompts are often free-text fields.
        if re.search(r"\bif\b", t, re.IGNORECASE) and re.search(r"\bdescribe\b", t, re.IGNORECASE) and len(t) <= 90:
            idxs.append(i)
            continue

    # De-dup nearby lines (keep earlier/upper ones)
    idxs_sorted = sorted(set(idxs), key=lambda k: (lines[k].y0, lines[k].x0))
    out = []
    last_y = None
    for k in idxs_sorted:
        y = lines[k].y0
        if last_y is not None and abs(y - last_y) < 6.5:
            continue
        out.append(k)
        last_y = y
    return out


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines0 in pages:
        if not lines0:
            continue

        lines = sorted(lines0, key=lambda ln: (ln.y0, ln.x0))
        x_min, x_max, _y_min, y_max = _page_dims(lines)

        flags = _detect_layout_flags(lines, x_min, x_max, y_max)

        title = _detect_form_title(lines, x_min, x_max, y_max)
        if title:
            current_form = title

        seen = set()

        # 1) Marker-anchored extraction:
        merged = _merge_bracket_fragments(lines)

        markers = []
        for x0, y0, _sz, txt in merged:
            t = (txt or "").strip()
            if not t.startswith("[") or "]" not in t:
                continue
            # Consider both var codes and meta markers as anchors.
            inner = t[1 : t.find("]")].strip()
            if _is_var_code_body(inner) or _is_meta_bracket_body(inner):
                markers.append((x0, y0))

        for mx, my in markers:
            label = _find_label_near_marker(mx, my, lines, x_min, x_max, y_max)
            label = _clean_label_text(label)
            label = _norm_space(label)

            if not _is_good_field_label(label):
                continue
            key = (current_form, label)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1})

        # 2) Option-block (right-column definitions/options) recovery:
        band = _detect_option_block(lines, x_min, x_max, y_max)
        if band is not None:
            q_idxs = _extract_left_label_near_band(lines, band, x_min, x_max, y_max)
            for qi in q_idxs:
                if qi is None:
                    continue
                label = _join_wrapped_label(
                    lines,
                    qi,
                    x_tol=max(24.0, 0.045 * max(1.0, x_max - x_min)),
                    y_gap_tol=max(4.6, 0.012 * max(1.0, y_max)),
                )
                label = _clean_label_text(label)
                label = _norm_space(label)
                if not _is_good_field_label(label):
                    continue
                key = (current_form, label)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1})

        # 3) Row-table pages (e.g., C-SSRS / lethality tables): extract question + row headings,
        #    and avoid capturing long definition paragraphs.
        if _row_table_like(lines):
            idxs = _extract_row_table_questions(lines, x_min, x_max, y_max)
            for i in idxs:
                label = _join_wrapped_label(
                    lines,
                    i,
                    x_tol=max(26.0, 0.05 * max(1.0, x_max - x_min)),
                    y_gap_tol=max(4.8, 0.013 * max(1.0, y_max)),
                )
                label = _clean_label_text(label)
                label = _norm_space(label)
                if not _is_good_field_label(label):
                    continue
                key = (current_form, label)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1})

        # 4) Conservative fallback: bold left-column labels (mid-page), but suppress on schedule/TOC-like pages.
        if not (flags["schedule_like"] or flags["toc_like"]):
            w = max(1.0, x_max - x_min)
            left_max = x_min + 0.44 * w
            top_guard = 0.18 * y_max if y_max else 140.0

            for i, ln in enumerate(lines):
                if not ln.bold:
                    continue
                if _is_probably_footer_header(ln, y_max):
                    continue
                if ln.x0 > left_max:
                    continue

                t = _clean_label_text((ln.text or "").strip())
                if not _is_candidate_label_text(t):
                    continue
                if _RE_ROW_PREFIX.match(t):
                    continue
                if _looks_like_long_body(t, ln.bold):
                    continue

                # Avoid pulling the page title as a “field”.
                if ln.y0 < top_guard and ln.size >= 11.0 and ("?" not in t and ":" not in t and not _RE_NUM_PREFIX.match(t)):
                    continue

                # Accept if it looks like a field prompt or a section field label.
                if not ("?" in t or ":" in t or _RE_NUM_PREFIX.match(t) or (len(t) <= 65 and ln.y0 >= top_guard)):
                    continue

                label = _join_wrapped_label(
                    lines,
                    i,
                    x_tol=max(24.0, 0.045 * w),
                    y_gap_tol=max(4.6, 0.012 * max(1.0, y_max)),
                )
                label = _clean_label_text(label)
                label = _norm_space(label)
                if not _is_good_field_label(label):
                    continue

                key = (current_form, label)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1})

    return out
```
