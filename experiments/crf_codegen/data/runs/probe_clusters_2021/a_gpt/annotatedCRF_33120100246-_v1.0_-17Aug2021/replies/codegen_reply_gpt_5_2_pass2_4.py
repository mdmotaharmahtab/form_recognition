```python
import re
from typing import List, Tuple, Dict, Any, Optional


_RE_NUM_PREFIX = re.compile(r"^\s*\d+\s*[\.\)]\s+\S")
_RE_TOC_NUM = re.compile(r"^\s*\d+(\.\d+)+\.\s+\S")
_RE_ROW_PREFIX = re.compile(r"^\s*Row\s*\d+\b", re.IGNORECASE)
_RE_JUST_NUMBER = re.compile(r"^\s*\d+\s*$")
_RE_YES_NO_ONLY = re.compile(r"^\s*(yes|no|n/?a|na|unknown)\s*$", re.IGNORECASE)

_RE_TECH_START = re.compile(r"^\s*\[\s*(type|visibility|read[-\s]*only|readonly)\b", re.IGNORECASE)
_RE_TECH_ANY = re.compile(r"\b(type|visibility)\s*:\s*", re.IGNORECASE)
_RE_LB_CODE = re.compile(r"^\s*LB[A-Z0-9_]+\s*$", re.IGNORECASE)


def _norm_space(s: str) -> str:
    return " ".join((s or "").strip().split())


def _is_bracket_line(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("[") and t.endswith("]") and len(t) >= 2


def _parse_leading_brackets(s: str) -> List[str]:
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
    t0 = (text or "").strip()
    if not t0:
        return t0

    t = t0.lstrip()
    if not t.startswith("["):
        return t0

    bodies = _parse_leading_brackets(t)
    if bodies:
        for b in bodies:
            if not (_is_meta_bracket_body(b) or _is_var_code_body(b) or _RE_LB_CODE.match(b.strip() or "")):
                return t0
        span = _leading_brackets_span(t)
        if span > 0:
            return t[span:].strip()
        return t0

    # If this is a technical bracket fragment without a closing ']' on the line,
    # treat it as non-label technical spillover.
    if _RE_TECH_START.match(t):
        return ""

    # Unknown fragment: keep as-is (conservative).
    return t0


def _strip_trailing_technical_bracket_tail(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    # Remove trailing technical bracket tails like "... [TYPE:" or "... [VISIBILITY:"
    m = re.search(r"\s+\[\s*(type|visibility|read[-\s]*only|readonly)\b[^\]]*$", t, re.IGNORECASE)
    if m:
        t = t[: m.start()].rstrip()
    return t


def _looks_like_technical_text(t: str) -> bool:
    tt = (t or "").strip()
    if not tt:
        return False
    if tt.startswith("[") and (_RE_TECH_START.match(tt) or _RE_TECH_ANY.search(tt)):
        return True
    if _RE_TECH_ANY.search(tt) and ("[" in tt or "]" in tt):
        return True
    return False


def _page_dims(lines) -> Tuple[float, float, float, float]:
    xs0 = [ln.x0 for ln in lines if getattr(ln, "text", None)]
    xs1 = [ln.x1 for ln in lines if getattr(ln, "text", None)]
    ys0 = [ln.y0 for ln in lines if getattr(ln, "text", None)]
    ys1 = [ln.y1 for ln in lines if getattr(ln, "text", None)]
    if not xs0 or not xs1 or not ys0 or not ys1:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs0), max(xs1), min(ys0), max(ys1)


def _footer_band_y(y_max: float) -> float:
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
    if "?" in tt or ":" in tt:
        return False
    return True


def _is_candidate_label_text(text: str) -> bool:
    t = _norm_space(_strip_trailing_technical_bracket_tail(_strip_leading_bracket_annotations(text)))
    if not t:
        return False
    if _is_bracket_line(t):
        return False
    if t.strip().startswith("["):
        return False
    if _looks_like_technical_text(t):
        return False
    if _RE_ROW_PREFIX.match(t):
        return False
    if _RE_YES_NO_ONLY.match(t):
        return False
    return True


def _clean_label_text(text: str) -> str:
    t = _strip_leading_bracket_annotations(text)
    if not t:
        return ""
    t = _strip_trailing_technical_bracket_tail(t)
    t = _norm_space(t)
    if not t:
        return ""
    if t.startswith("[") and _looks_like_technical_text(t):
        return ""
    # If a technical tag leaked mid-string, drop it and anything after.
    m = re.search(r"\s+\[\s*(type|visibility|read[-\s]*only|readonly)\b", t, re.IGNORECASE)
    if m:
        t = t[: m.start()].rstrip()
    return _norm_space(t)


def _is_good_field_label(label: str) -> bool:
    t = _norm_space(label)
    if not t:
        return False
    if t.strip().startswith("["):
        return False
    if _looks_like_technical_text(t):
        return False
    if _RE_ROW_PREFIX.match(t):
        return False
    if _RE_YES_NO_ONLY.match(t):
        return False
    if _RE_JUST_NUMBER.match(t):
        return False

    # Reject definition paragraphs unless clearly a prompt.
    if len(t) > 160 and ("?" not in t):
        return False
    if len(t) > 120 and not ("?" in t or ":" in t or _RE_NUM_PREFIX.match(t)):
        return False

    # Reject option/anchor lines: numbered but not prompt-like.
    if _RE_NUM_PREFIX.match(t) and ("?" not in t) and (":" not in t) and len(t) >= 55:
        return False

    # Avoid long enumerated-option fragments.
    if re.search(r"\(\s*\d+\s*\)", t) and ("?" not in t) and (":" not in t) and (len(t) > 70):
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
    if len(tt) <= 30 and ln.size >= 7.8:
        return True
    return False


def _wrap_continues(prev_t: str, cur_t: str) -> bool:
    p = (prev_t or "").strip()
    c = (cur_t or "").strip()
    if not p or not c:
        return False
    if p.endswith("?") or p.endswith(":"):
        return False
    # Common wrap signals
    if p.endswith((",", ";", "-", "(", "/", "–")):
        return True
    # Continuation usually begins mid-sentence (lowercase / digit / punctuation).
    if c[0].islower() or c[0].isdigit() or c[0] in "([/":
        return True
    # Allow wrap if the previous line is long (likely wrapped).
    if len(p) >= 40:
        return True
    return False


def _join_wrapped_label(
    lines,
    anchor_idx: int,
    x_tol: float,
    y_gap_tol: float,
    up_limit: int = 2,
    down_limit: int = 4,
) -> str:
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
        pt = _clean_label_text(prev.text)
        ct = _clean_label_text(cur.text)
        if not pt or not ct:
            return False
        if _looks_like_long_body(ct, cur.bold):
            return False
        if not _wrap_continues(pt, ct):
            return False
        return True

    idxs = [anchor_idx]

    # Up
    up = 0
    k = anchor_idx - 1
    prev_top = anchor
    while k >= 0 and up < up_limit:
        cur = lines[k]
        if not ok_wrap(cur, prev_top):
            break
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
    while k < len(lines) and down < down_limit:
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
    # Merge vertically stacked bracket fragments (often colored), e.g.:
    # [TYPE: partialdate
    # (value stuff ...)]
    used = [False] * len(lines)
    merged = []
    for i, ln in enumerate(lines):
        if used[i]:
            continue
        t = (ln.text or "").strip()
        if not t or not t.lstrip().startswith("["):
            continue

        t2 = t.lstrip()
        if not (_RE_TECH_START.match(t2) or t2.upper().startswith("[LB") or t2.upper().startswith("[READ-ONLY") or t2.upper().startswith("[READ ONLY") or t2.upper().startswith("[READONLY")):
            # Still allow full bracket blocks; they may be LB codes etc.
            if "]" not in t2:
                continue

        if t2.startswith("[") and ("]" not in t2):
            acc = t2
            used[i] = True
            y0 = ln.y0
            x0 = ln.x0
            size0 = ln.size
            lasty = ln.y1
            for j in range(i + 1, min(len(lines), i + 9)):
                ln2 = lines[j]
                if used[j]:
                    continue
                if abs(ln2.x0 - x0) > 6.5:
                    continue
                if abs(ln2.size - size0) > 2.0:
                    continue
                if ln2.y0 - lasty > 20.0:
                    break
                tj = (ln2.text or "").strip()
                if not tj:
                    continue
                acc += " " + tj
                used[j] = True
                lasty = ln2.y1
                if "]" in acc:
                    break
            merged.append((x0, y0, size0, acc))
        else:
            if t2.startswith("[") and "]" in t2:
                merged.append((ln.x0, ln.y0, ln.size, t2))
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

        if ln.non_black and ln.size <= 8.4 and ln.x0 >= left_max and not _is_bracket_line(t):
            blue_like += 1

        if _RE_JUST_NUMBER.match(t) and ln.size <= 8.6 and (x_min + 0.30 * w) <= ln.x0 <= (x_min + 0.55 * w):
            numbers_col += 1

    schedule_like = schedule_tag or (blue_like >= 10 and numbers_col >= 5)
    toc_like = (toc_num >= 8) or (blue_like >= 12 and numbers_col >= 8)

    return {"schedule_like": schedule_like, "toc_like": toc_like}


def _detect_form_title(lines, x_min: float, x_max: float, y_max: float) -> Optional[str]:
    w = max(1.0, x_max - x_min)
    top_band = 0.24 * y_max if y_max else 160.0

    cands = []
    for i, ln in enumerate(lines):
        t0 = (ln.text or "").strip()
        if not t0:
            continue
        if _is_probably_footer_header(ln, y_max):
            continue
        if ln.y0 > top_band:
            continue
        if ln.x0 > x_min + 0.78 * w:
            continue

        t = _clean_label_text(t0)
        if not t:
            continue
        if _RE_TOC_NUM.match(t):
            continue
        if _looks_like_technical_text(t):
            continue

        # Avoid picking individual field labels as the form title.
        if (("?" in t) or (":" in t) or _RE_NUM_PREFIX.match(t)) and ln.size <= 12.2:
            continue

        # Titles are usually larger OR emphasized OR link-colored.
        if ln.size < 7.8 and not (ln.bold or ln.non_black):
            continue

        # Prefer explicit page/title phrasing.
        page_bonus = -10.0 if re.search(r"\bpage\s*\d+\b", t, re.IGNORECASE) else 0.0
        cssrs_bonus = -10.0 if re.search(r"\bC-SSRS\b", t) else 0.0

        score = ln.y0 * 1.0 + (-ln.size) * 7.0 + (0.02 * max(0.0, ln.x0 - x_min)) + page_bonus + cssrs_bonus
        if ln.bold or ln.non_black:
            score -= 6.0
        cands.append((score, i, t))

    if not cands:
        return None
    cands.sort()
    _, idx, t0 = cands[0]

    base = lines[idx]
    parts = [t0]
    last = base
    for _, j, tj in cands[1:10]:
        ln = lines[j]
        if ln.y0 < base.y0 - 2:
            continue
        if ln.y0 - last.y1 > max(5.0, 2.2 * base.size):
            continue
        if abs(ln.x0 - base.x0) > 55:
            continue
        if abs(ln.size - base.size) > 3.8:
            continue
        if _RE_TOC_NUM.match(tj):
            continue
        if _looks_like_technical_text(tj):
            continue
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


def _detect_option_block(lines, x_min: float, x_max: float, y_max: float) -> Optional[Tuple[float, float, float]]:
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
        if ln.size > 8.8:
            continue
        if ln.x0 < left_max:
            continue
        if _looks_like_technical_text(t) or _is_bracket_line(t):
            continue
        if re.search(r"\(\s*\d+\s*\)", t) or re.search(r"\bdoes not apply\b", t, re.IGNORECASE):
            opts.append(ln)

    if len(opts) < 4:
        return None

    ys = [ln.y0 for ln in opts]
    y0, y1 = min(ys), max(ys)
    if (y1 - y0) < 28:
        return None

    # Return band and representative x (right column anchor)
    x_anchor = sorted([ln.x0 for ln in opts])[len(opts) // 2]
    return (y0, y1, x_anchor)


def _extract_label_near_option_band(lines, band: Tuple[float, float, float], x_min: float, x_max: float, y_max: float) -> List[int]:
    w = max(1.0, x_max - x_min)
    left_max = x_min + 0.44 * w
    y0, y1, x_anchor = band

    best_idx = None
    best_sc = None

    for i, ln in enumerate(lines):
        if _is_probably_footer_header(ln, y_max):
            continue
        if ln.y0 < (y0 - 95) or ln.y0 > (y1 + 65):
            continue
        if ln.size < 7.2 or ln.size > 14.2:
            continue

        raw = (ln.text or "").strip()
        t = _clean_label_text(raw)
        if not _is_candidate_label_text(t):
            continue
        if _looks_like_long_body(t, ln.bold):
            continue
        if _looks_like_technical_text(t):
            continue

        # Candidate region: prefer left-column, but allow a right-column header above options.
        col_ok = (ln.x0 < left_max) or (abs(ln.x0 - x_anchor) <= max(65.0, 0.12 * w) and ln.y0 <= y0 + 18)
        if not col_ok:
            continue

        # Prefer bold / emphasized / question-like.
        if not ln.bold and not ln.non_black and not ("?" in t or ":" in t or _RE_NUM_PREFIX.match(t)) and ln.size < 8.6:
            continue

        dy = y0 - ln.y0
        sc = abs(dy)
        if ln.bold:
            sc *= 0.78
        if ln.non_black:
            sc *= 0.90
        if ln.size >= 9.2:
            sc *= 0.86
        if ("?" in t) or (":" in t) or _RE_NUM_PREFIX.match(t):
            sc *= 0.90

        # Slightly prefer left/near-left positions.
        sc += 0.01 * (max(0.0, ln.x0 - x_min))
        if ln.x0 >= left_max:
            sc += 0.25 * abs(ln.x0 - x_anchor)

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
    left_max = x_min + 0.52 * w
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

        if _RE_NUM_PREFIX.match(t):
            # In row tables, numbered prompts can be fields, but reject long non-prompt anchors.
            if len(t) <= 140 and ("?" in t or ":" in t or len(t) <= 60):
                idxs.append(i)
            continue

        if "?" in t:
            if len(t) <= 175:
                idxs.append(i)
            continue

        if ":" in t and len(t) <= 150:
            idxs.append(i)
            continue

        if re.search(r"\bif\b", t, re.IGNORECASE) and re.search(r"\bdescribe\b", t, re.IGNORECASE) and len(t) <= 100:
            idxs.append(i)
            continue

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


def _extract_markers(lines):
    merged = _merge_bracket_fragments(lines)
    markers = []
    for x0, y0, _sz, txt in merged:
        t = (txt or "").strip()
        if not t.startswith("[") or "]" not in t:
            continue
        # Scan all bracket bodies on the line
        for body in re.findall(r"\[([^\]]+)\]", t):
            inner = (body or "").strip()
            if _is_var_code_body(inner) or _is_meta_bracket_body(inner) or _RE_LB_CODE.match(inner):
                markers.append((x0, y0))
                break
    return markers


def _find_inline_left_label(mx: float, my: float, lines, x_min: float, x_max: float, y_max: float) -> str:
    w = max(1.0, x_max - x_min)
    left_max = x_min + 0.44 * w

    # Y tolerance based on typical small font, plus slack.
    y_tol = 7.0 + 0.55 * 8.0

    best_idx = None
    best_sc = None

    for i, ln in enumerate(lines):
        if _is_probably_footer_header(ln, y_max):
            continue

        raw = (ln.text or "").strip()
        if not raw:
            continue
        t = _clean_label_text(raw)
        if not t or not _is_candidate_label_text(t):
            continue
        if _looks_like_long_body(t, ln.bold):
            continue

        # Must be to the left of the marker.
        if ln.x1 > mx - 2.0:
            continue

        cy = 0.5 * (ln.y0 + ln.y1)
        if abs(cy - my) > (y_tol + 0.25 * ln.size):
            continue

        # If marker is in the right column, allow either left-column labels or same-column labels.
        if mx >= left_max:
            # Avoid picking right-column option text by requiring label-ish style.
            if ln.x0 >= left_max and not _looks_like_headerish(t, ln):
                continue
        else:
            # Left column marker: keep same column.
            if abs(ln.x0 - mx) > max(80.0, 0.15 * w):
                continue

        # Avoid single-word section headers far from marker.
        if len(t.split()) == 1 and (mx - ln.x1) > max(70.0, 0.13 * w) and not ln.bold:
            continue

        dx = max(0.0, mx - ln.x1)
        sc = 1.15 * abs(cy - my) + 0.55 * dx + 0.02 * abs(ln.x0 - (mx - 140.0))

        if ln.bold:
            sc *= 0.82
        if ("?" in t) or (":" in t):
            sc *= 0.90
        if _RE_NUM_PREFIX.match(t):
            sc *= 0.93

        if best_sc is None or sc < best_sc:
            best_sc = sc
            best_idx = i

    if best_idx is None:
        return ""

    return _join_wrapped_label(
        lines,
        best_idx,
        x_tol=max(22.0, 0.04 * w),
        y_gap_tol=max(4.8, 0.012 * max(1.0, y_max)),
        up_limit=2,
        down_limit=4,
    )


def _find_label_near_marker(mx: float, my: float, lines, x_min: float, x_max: float, y_max: float) -> str:
    # Fallback: broader search (kept from previous approach), but tightened to avoid options/tech.
    w = max(1.0, x_max - x_min)
    left_max = x_min + 0.44 * w

    x_tol_wrap = max(22.0, 0.04 * w)
    y_gap_tol = 5.0 + 1.9 * 8.0

    def looks_like_optionish(t: str, ln) -> bool:
        tt = (t or "").strip()
        if not tt:
            return False
        if ln.non_black and ln.size <= 8.6 and ln.x0 >= left_max:
            if re.search(r"\(\s*\d+\s*\)", tt):
                return True
            if tt.lower().startswith(("yes ", "no ")):
                return True
        return False

    def candidate_score(i: int, ln) -> Optional[float]:
        if _is_probably_footer_header(ln, y_max):
            return None

        raw = (ln.text or "").strip()
        if not raw:
            return None
        t = _clean_label_text(raw)
        if not t or not _is_candidate_label_text(t):
            return None
        if _looks_like_technical_text(t) or _looks_like_optionish(t, ln):
            return None
        if _looks_like_long_body(t, ln.bold):
            return None

        dy = ln.y0 - my
        if dy < -280 or dy > 220:
            return None

        if mx >= left_max:
            left_ok = ln.x0 < left_max
            same_col_ok = abs(ln.x0 - mx) <= max(70.0, 0.12 * w)
            if not (left_ok or same_col_ok):
                return None
            if same_col_ok:
                if dy > 70:
                    return None
                if not _looks_like_headerish(t, ln):
                    return None
        else:
            if abs(ln.x0 - mx) > max(65.0, 0.12 * w):
                return None
            if dy > 80:
                return None
            if not _looks_like_headerish(t, ln) and not ln.bold:
                if not ("?" in t or ":" in t or _RE_NUM_PREFIX.match(t)):
                    return None

        sc = abs(dy) * (0.92 if dy < 0 else 1.12)
        sc += 0.03 * abs(ln.x0 - mx)

        if ln.bold:
            sc *= 0.82
        if ("?" in t) or (":" in t) or _RE_NUM_PREFIX.match(t):
            sc *= 0.88

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

        # 1) Marker-anchored extraction (improved: prefer inline-left labels).
        markers = _extract_markers(lines)
        for mx, my in markers:
            label = _find_inline_left_label(mx, my, lines, x_min, x_max, y_max)
            if not label:
                label = _find_label_near_marker(mx, my, lines, x_min, x_max, y_max)

            label = _norm_space(_clean_label_text(label))
            if not _is_good_field_label(label):
                continue

            key = (current_form, label)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1})

        # 2) Option-block recovery (right-column definitions/options) -> find the question/field label nearby.
        band = _detect_option_block(lines, x_min, x_max, y_max)
        if band is not None:
            q_idxs = _extract_label_near_option_band(lines, band, x_min, x_max, y_max)
            for qi in q_idxs:
                if qi is None:
                    continue
                w = max(1.0, x_max - x_min)
                label = _join_wrapped_label(
                    lines,
                    qi,
                    x_tol=max(26.0, 0.05 * w),
                    y_gap_tol=max(4.8, 0.013 * max(1.0, y_max)),
                    up_limit=2,
                    down_limit=4,
                )
                label = _norm_space(_clean_label_text(label))
                if not _is_good_field_label(label):
                    continue
                key = (current_form, label)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1})

        # 3) Row-table pages: extract question + row headings, avoiding definition paragraphs.
        if _row_table_like(lines):
            idxs = _extract_row_table_questions(lines, x_min, x_max, y_max)
            for i in idxs:
                label = _join_wrapped_label(
                    lines,
                    i,
                    x_tol=max(28.0, 0.055 * max(1.0, x_max - x_min)),
                    y_gap_tol=max(5.0, 0.014 * max(1.0, y_max)),
                    up_limit=2,
                    down_limit=4,
                )
                label = _norm_space(_clean_label_text(label))
                if not _is_good_field_label(label):
                    continue
                key = (current_form, label)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1})

        # 4) Conservative fallback: bold left-column labels, but suppress on schedule/TOC-like pages.
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

                if ln.y0 < top_guard and ln.size >= 11.0 and ("?" not in t and ":" not in t and not _RE_NUM_PREFIX.match(t)):
                    continue

                if not ("?" in t or ":" in t or _RE_NUM_PREFIX.match(t) or (len(t) <= 65 and ln.y0 >= top_guard)):
                    continue

                label = _join_wrapped_label(
                    lines,
                    i,
                    x_tol=max(24.0, 0.045 * w),
                    y_gap_tol=max(4.8, 0.012 * max(1.0, y_max)),
                    up_limit=2,
                    down_limit=4,
                )
                label = _norm_space(_clean_label_text(label))
                if not _is_good_field_label(label):
                    continue

                key = (current_form, label)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1})

    return out
```
