```python
import re
import statistics
from collections import Counter


_RE_FIELD_ID = re.compile(r"^\[[A-Za-z0-9_][A-Za-z0-9_\-]{1,}\]$")  # allow "-"
_RE_SPLIT_OPEN = re.compile(r"^\[[A-Za-z0-9_][A-Za-z0-9_\-]{1,}$")  # "[SCANNE"
_RE_SPLIT_CLOSE = re.compile(r"^[A-Za-z0-9_\-]{1,40}\]$")           # "R]"
_RE_TYPE_LINE = re.compile(r"^\[TYPE\s*:\s*.+\]\s*$", re.IGNORECASE)

_RE_ROW = re.compile(r"^\s*Row\s*\d+\s*$", re.IGNORECASE)
_RE_JUST_PUNCT = re.compile(r"^\W+$", re.UNICODE)

_RE_ENUM_PAREN_START = re.compile(r"^\s*\(\s*\d+\s*\)\s*")
_RE_ENUM_PAREN_ANY = re.compile(r"\(\s*\d+\s*\)")
_RE_ENUM_RPAREN_START = re.compile(r"^\s*\d+\)\s+")
_RE_QUESTION_STEM_NUM = re.compile(r"^\s*\d+\.\s+\S+")
_RE_TIMEPOINT_H = re.compile(r"^\s*\d+(?:\.\d+)?\s*h\b", re.IGNORECASE)
_RE_TIMEPOINTISH = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*h\b|(?:pre|post)\s*dose\b|postdose\b|predose\b)\b",
    re.IGNORECASE,
)


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _norm_text(s: str) -> str:
    s = (s or "").replace("\\", "")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    return s


def _looks_like_chrome_or_empty(text: str) -> bool:
    if not text:
        return True
    t = text.strip()
    if not t:
        return True
    if _RE_JUST_PUNCT.match(t):
        return True
    if re.fullmatch(r"\d{1,4}", t):
        return True
    return False


def _is_field_id_text(t: str) -> bool:
    t = (t or "").strip()
    if ":" in t or " " in t:
        return False
    return bool(_RE_FIELD_ID.match(t))


def _is_type_line(ln) -> bool:
    if not getattr(ln, "non_black", False):
        return False
    t = (getattr(ln, "text", "") or "").strip()
    return bool(_RE_TYPE_LINE.match(t))


def _is_timepointish_text(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    if _RE_TIMEPOINT_H.match(t):
        return True
    return bool(_RE_TIMEPOINTISH.search(t))


def _merge_split_bracket_ids(lines):
    out = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        t = (getattr(ln, "text", "") or "").strip()
        if _RE_SPLIT_OPEN.match(t) and (":" not in t) and (" " not in t) and i + 1 < n:
            nxt = lines[i + 1]
            t2 = (getattr(nxt, "text", "") or "").strip()
            if (
                _RE_SPLIT_CLOSE.match(t2)
                and abs(_f(getattr(nxt, "size", 0.0)) - _f(getattr(ln, "size", 0.0))) <= 0.8
                and abs(_f(getattr(nxt, "x0", 0.0)) - _f(getattr(ln, "x0", 0.0))) <= 8.0
                and 0.0 <= _f(getattr(nxt, "y0", 0.0)) - _f(getattr(ln, "y0", 0.0)) <= 18.0
            ):
                merged_text = t + t2

                class _L:
                    __slots__ = ("text", "x0", "y0", "x1", "y1", "size", "bold", "non_black")

                m = _L()
                m.text = merged_text
                m.x0 = getattr(ln, "x0", 0.0)
                m.y0 = getattr(ln, "y0", 0.0)
                m.x1 = getattr(ln, "x1", 0.0)
                m.y1 = getattr(nxt, "y1", getattr(nxt, "y0", 0.0))
                m.size = getattr(ln, "size", 0.0)
                m.bold = bool(getattr(ln, "bold", False))
                m.non_black = bool(getattr(ln, "non_black", False)) or bool(getattr(nxt, "non_black", False))
                out.append(m)
                i += 2
                continue
        out.append(ln)
        i += 1
    return out


def _page_small_font_size(lines) -> float:
    sizes = []
    for ln in lines:
        if ln is None:
            continue
        sz = _f(getattr(ln, "size", 0.0))
        if 6.0 <= sz <= 11.2:
            t = (getattr(ln, "text", "") or "").strip()
            if not t or t.startswith("["):
                continue
            sizes.append(round(sz, 1))
    if not sizes:
        allsz = [_f(getattr(ln, "size", 0.0)) for ln in lines if ln is not None]
        allsz = [s for s in allsz if s > 0]
        return float(statistics.median(allsz)) if allsz else 8.0
    c = Counter(sizes)
    best = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return float(best)


def _page_colored_title(lines, small_sz: float):
    cands = []
    for ln in lines:
        t = (getattr(ln, "text", "") or "").strip()
        if _looks_like_chrome_or_empty(t):
            continue
        if not getattr(ln, "non_black", False):
            continue
        y = _f(getattr(ln, "y0", 0.0))
        x = _f(getattr(ln, "x0", 0.0))
        sz = _f(getattr(ln, "size", 0.0))
        if y <= 140.0 and x <= 290.0 and sz >= max(small_sz * 1.45, small_sz + 3.6):
            if t.startswith("[") and t.endswith("]"):
                continue
            cands.append((sz, -y, -x, t))
    if not cands:
        return ""
    cands.sort(reverse=True)
    return _norm_text(cands[0][3])


def _page_top_black_heading(lines, small_sz: float):
    cands = []
    for ln in lines:
        if getattr(ln, "non_black", False):
            continue
        t = (getattr(ln, "text", "") or "").strip()
        if _looks_like_chrome_or_empty(t):
            continue
        if t.startswith("["):
            continue
        y = _f(getattr(ln, "y0", 0.0))
        x = _f(getattr(ln, "x0", 0.0))
        sz = _f(getattr(ln, "size", 0.0))
        if y <= 95.0 and x <= 160.0 and abs(sz - small_sz) <= 1.6:
            cands.append((y, x, t))
    if not cands:
        return ""
    cands.sort(key=lambda a: (a[0], a[1]))
    return _norm_text(cands[0][2])


def _page_looks_like_lab_enum_list(lines, small_sz: float) -> bool:
    cnt = 0
    for ln in lines:
        if getattr(ln, "non_black", False):
            continue
        sz = _f(getattr(ln, "size", 0.0))
        x = _f(getattr(ln, "x0", 0.0))
        y = _f(getattr(ln, "y0", 0.0))
        if 70.0 <= y <= 640.0 and x >= 240.0 and (small_sz + 1.0) <= sz <= (small_sz + 3.8):
            t = (getattr(ln, "text", "") or "").strip()
            if _looks_like_chrome_or_empty(t) or t.startswith("["):
                continue
            cnt += 1
    return cnt >= 5


def _looks_like_choice_legend(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return True
    if len(_RE_ENUM_PAREN_ANY.findall(t)) >= 2:
        return True
    if _RE_ENUM_PAREN_START.match(t) or _RE_ENUM_RPAREN_START.match(t):
        return True
    return False


def _looks_like_definition_sentence(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    if "?" not in t and t.count(".") >= 2:
        return True
    if "?" not in t and t.endswith(".") and len(t) >= 90 and t.count(",") >= 2:
        return True
    if "?" not in t and len(t) >= 80 and (t.count(";") >= 2 or (t.count(",") >= 4)):
        return True
    return False


def _label_candidate(ln, small_sz: float) -> bool:
    t = (getattr(ln, "text", "") or "").strip()
    if _looks_like_chrome_or_empty(t):
        return False
    if t.startswith("["):
        return False
    if _RE_ROW.match(t):
        return False
    sz = _f(getattr(ln, "size", 0.0))
    if not (small_sz - 1.4 <= sz <= small_sz + 4.2):
        return False
    return True


def _promptish_text(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    if "?" in t or ":" in t:
        return True
    if _RE_QUESTION_STEM_NUM.match(t):
        return True
    if " - " in t and len(t) <= 90:
        return True
    return False


def _header_like(ln, small_sz: float) -> bool:
    if getattr(ln, "non_black", False):
        return False
    t = (getattr(ln, "text", "") or "").strip()
    if _looks_like_chrome_or_empty(t):
        return False
    if t.startswith("["):
        return False
    sz = _f(getattr(ln, "size", 0.0))
    if not (small_sz + 0.9 <= sz <= small_sz + 5.6):
        return False
    if len(t) > 70:
        return False
    return True


def _nearest_header(headers, code_x: float, code_y: float):
    best = None
    best_score = None
    for h in headers:
        hy = _f(getattr(h, "y0", 0.0))
        if hy >= code_y:
            continue
        dy = code_y - hy
        if dy > 380.0:
            continue
        dx = abs(code_x - _f(getattr(h, "x0", 0.0)))
        score = dy * 1.0 + dx * 0.35
        if best_score is None or score < best_score:
            best_score = score
            best = (getattr(h, "text", "") or "").strip()
    return _norm_text(best) if best else ""


def _two_col_split_x(label_lines):
    xs = sorted({_f(getattr(ln, "x0", 0.0)) for ln in label_lines})
    if len(xs) < 24:
        return None
    gaps = []
    for i in range(1, len(xs)):
        gaps.append((xs[i] - xs[i - 1], i))
    gap, idx = max(gaps, key=lambda t: t[0])
    if gap < 170.0:
        return None
    left_ct = idx
    right_ct = len(xs) - idx
    if left_ct < 10 or right_ct < 10:
        return None
    return (xs[idx - 1] + xs[idx]) / 2.0


def _gather_same_row_text(cands, anchor_ln, y_tol: float, x_min: float, x_max: float) -> str:
    ay = _f(getattr(anchor_ln, "y0", 0.0))
    parts = []
    for ln in cands:
        y = _f(getattr(ln, "y0", 0.0))
        if abs(y - ay) > y_tol:
            continue
        x0 = _f(getattr(ln, "x0", 0.0))
        if x0 < x_min or x0 > x_max:
            continue
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        parts.append((y, x0, t))
    if not parts:
        return ""
    parts.sort(key=lambda p: (p[0], p[1]))
    return _norm_text(" ".join(p[2] for p in parts))


def _is_optionish_shape(t: str, x: float, left_margin_x: float) -> bool:
    t = (t or "").strip()
    if not t:
        return True
    if _RE_ENUM_PAREN_START.match(t) or _RE_ENUM_RPAREN_START.match(t):
        return True
    if len(t) <= 4 and x >= left_margin_x + 130.0 and ("?" not in t) and (":" not in t):
        return True
    if len(t) <= 6 and x >= left_margin_x + 170.0 and ("?" not in t) and (":" not in t):
        return True
    if re.fullmatch(r"[A-Za-z]\)", t) and x >= left_margin_x + 130.0:
        return True
    return False


def _same_row_left_anchor(label_lines, code_ln, left_margin_x: float, small_sz: float):
    cy = _f(getattr(code_ln, "y0", 0.0))
    cx = _f(getattr(code_ln, "x0", 0.0))
    y_tol = max(9.5, 1.15 * small_sz)

    best = None
    best_score = None
    for ln in label_lines:
        y = _f(getattr(ln, "y0", 0.0))
        if abs(y - cy) > y_tol:
            continue
        x = _f(getattr(ln, "x0", 0.0))
        if x >= cx - 12.0:
            continue
        dx = cx - x
        if dx > 380.0:
            continue

        t = (getattr(ln, "text", "") or "").strip()
        if not t:
            continue

        too_close_to_widget = dx < 38.0 and x > left_margin_x + 85.0

        score = abs(y - cy) * 2.0 + dx * 0.18
        score += 0.03 * max(0.0, x - left_margin_x)
        score += 18.0 if _looks_like_choice_legend(t) else 0.0
        score += 10.0 if _looks_like_definition_sentence(t) else 0.0
        score += 10.0 if too_close_to_widget else 0.0
        score += 12.0 if _is_optionish_shape(t, x, left_margin_x) else 0.0

        if best_score is None or score < best_score:
            best_score = score
            best = ln

    return best


def _find_prompt_above(label_lines, code_ln, left_margin_x: float, small_sz: float):
    cy = _f(getattr(code_ln, "y0", 0.0))
    cx = _f(getattr(code_ln, "x0", 0.0))
    best = None
    best_score = None
    for ln in label_lines:
        y = _f(getattr(ln, "y0", 0.0))
        if y >= cy:
            continue
        dy = cy - y
        if dy > 280.0:
            continue
        x = _f(getattr(ln, "x0", 0.0))
        t = (getattr(ln, "text", "") or "").strip()
        if not t:
            continue

        score = dy * 1.0 + 0.08 * abs(cx - x)
        score += 0.05 * max(0.0, x - left_margin_x)
        score += 10.0 if _looks_like_choice_legend(t) else 0.0
        score += 8.0 if _looks_like_definition_sentence(t) else 0.0
        score += 8.0 if _is_optionish_shape(t, x, left_margin_x) else 0.0
        score += -6.0 if _promptish_text(t) else 0.0

        if best_score is None or score < best_score:
            best_score = score
            best = ln
    return best


def _find_column_header_above(label_lines, code_ln, left_margin_x: float, small_sz: float):
    cy = _f(getattr(code_ln, "y0", 0.0))
    cx = _f(getattr(code_ln, "x0", 0.0))
    best = None
    best_score = None

    for ln in label_lines:
        y = _f(getattr(ln, "y0", 0.0))
        if y >= cy:
            continue
        dy = cy - y
        if dy > 140.0:
            continue
        x = _f(getattr(ln, "x0", 0.0))
        dx = abs(cx - x)
        if dx > 95.0:
            continue

        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_chrome_or_empty(t):
            continue
        if _looks_like_choice_legend(t) or _looks_like_definition_sentence(t):
            continue

        score = dy * 1.0 + dx * 0.55
        score += 10.0 if _is_optionish_shape(t, x, left_margin_x) else 0.0
        score += 3.0 if len(t) > 30 else 0.0

        if best_score is None or score < best_score:
            best_score = score
            best = ln

    return best


def _bare_phrase(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    if "?" in t or ":" in t:
        return False
    if _RE_QUESTION_STEM_NUM.match(t):
        return False
    if t.count("-") >= 2:
        return False
    if _RE_TIMEPOINT_H.match(t):
        return True
    words = [w for w in re.split(r"\s+", t) if w]
    if len(words) <= 4 and len(t) <= 26 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\s\-/]*", t):
        return True
    return False


def _infer_field_label(lines, code_ln, small_sz: float, label_lines, left_margin_x: float, header_lines, two_col_split):
    cx = _f(getattr(code_ln, "x0", 0.0))
    cy = _f(getattr(code_ln, "y0", 0.0))

    anchor = _same_row_left_anchor(label_lines, code_ln, left_margin_x, small_sz)
    if anchor is not None:
        ax = _f(getattr(anchor, "x0", 0.0))
        text = _gather_same_row_text(
            label_lines,
            anchor,
            y_tol=max(9.5, 1.15 * small_sz),
            x_min=max(left_margin_x - 3.0, ax - 2.0),
            x_max=min(cx - 14.0, ax + 380.0),
        )
        text = _norm_text(text)

        if text:
            if _is_timepointish_text(text) or _looks_like_choice_legend(text) or _is_optionish_shape(
                text, ax, left_margin_x
            ):
                pab = _find_prompt_above(label_lines, code_ln, left_margin_x, small_sz)
                if pab is not None:
                    t2 = _norm_text((getattr(pab, "text", "") or "").strip())
                    if t2 and not _looks_like_choice_legend(t2) and not _is_optionish_shape(
                        t2, _f(getattr(pab, "x0", 0.0)), left_margin_x
                    ):
                        return t2

            if _bare_phrase(text) or _looks_like_definition_sentence(text) or _is_optionish_shape(text, ax, left_margin_x):
                pab = _find_prompt_above(label_lines, code_ln, left_margin_x, small_sz)
                if pab is not None:
                    t2 = _norm_text((getattr(pab, "text", "") or "").strip())
                    if t2 and (_promptish_text(t2) or len(t2) >= 18) and not _looks_like_choice_legend(
                        t2
                    ) and not _looks_like_definition_sentence(t2):
                        return t2

                colh = _find_column_header_above(label_lines, code_ln, left_margin_x, small_sz)
                if colh is not None:
                    t3 = _norm_text((getattr(colh, "text", "") or "").strip())
                    if t3 and (not _is_timepointish_text(t3)) and (not _looks_like_choice_legend(t3)):
                        if len(t3) <= 28 and not _looks_like_definition_sentence(t3):
                            return t3

            hdr = _nearest_header(header_lines, cx, cy)
            if hdr and (hdr.lower() not in text.lower()) and (not _looks_like_choice_legend(hdr)) and (not _is_timepointish_text(hdr)):
                if _bare_phrase(text) and two_col_split is None:
                    return _norm_text(hdr)

            return text

    pab = _find_prompt_above(label_lines, code_ln, left_margin_x, small_sz)
    if pab is not None:
        base = _norm_text((getattr(pab, "text", "") or "").strip())
        if base and not _looks_like_choice_legend(base) and not _looks_like_definition_sentence(base):
            ay = _f(getattr(pab, "y0", 0.0))
            ax = _f(getattr(pab, "x0", 0.0))
            cont = []
            for ln in label_lines:
                y = _f(getattr(ln, "y0", 0.0))
                if y < ay - 0.5:
                    continue
                if y > ay + 34.0:
                    continue
                x = _f(getattr(ln, "x0", 0.0))
                if x < ax - 5.0 or x > ax + 460.0:
                    continue
                t = (getattr(ln, "text", "") or "").strip()
                if not t or t.startswith("["):
                    continue
                if _looks_like_choice_legend(t) or _looks_like_definition_sentence(t):
                    continue
                if _is_optionish_shape(t, x, left_margin_x):
                    continue
                cont.append((y, x, t))
            if cont:
                cont.sort(key=lambda p: (p[0], p[1]))
                base = _norm_text(" ".join(p[2] for p in cont))
            return base

    best = None
    best_score = None
    for ln in label_lines:
        y = _f(getattr(ln, "y0", 0.0))
        if y >= cy:
            continue
        dy = cy - y
        if dy > 360.0:
            continue
        x = _f(getattr(ln, "x0", 0.0))
        t = (getattr(ln, "text", "") or "").strip()
        if not t:
            continue
        score = dy * 1.0 + 0.25 * abs(cx - x) + 0.06 * max(0.0, x - left_margin_x)
        score += 16.0 if _looks_like_choice_legend(t) else 0.0
        score += 10.0 if _looks_like_definition_sentence(t) else 0.0
        score += 10.0 if _is_optionish_shape(t, x, left_margin_x) else 0.0
        score += -5.0 if _promptish_text(t) else 0.0
        if best_score is None or score < best_score:
            best_score = score
            best = ln

    if best is None:
        return ""
    return _norm_text((getattr(best, "text", "") or "").strip())


def _infer_field_label_for_type_line(lines, type_ln, small_sz: float, label_lines, left_margin_x: float):
    cx = _f(getattr(type_ln, "x0", 0.0))
    cy = _f(getattr(type_ln, "y0", 0.0))

    cands = []
    for ln in label_lines:
        t = (getattr(ln, "text", "") or "").strip()
        if not t:
            continue
        x = _f(getattr(ln, "x0", 0.0))
        y = _f(getattr(ln, "y0", 0.0))

        if y < cy - 40.0 or y > cy + 260.0:
            continue
        if x < left_margin_x - 10.0 or x > left_margin_x + 560.0:
            continue
        if _looks_like_choice_legend(t) or _looks_like_definition_sentence(t):
            continue
        if _is_optionish_shape(t, x, left_margin_x):
            continue

        score = abs(y - cy) * 1.1 + 0.18 * abs(x - cx)
        score += -7.0 if _promptish_text(t) else 0.0
        score += 6.0 if _bare_phrase(t) else 0.0
        cands.append((score, t))

    if not cands:
        return ""
    cands.sort(key=lambda z: z[0])
    return _norm_text(cands[0][1])


def _marker_points(code_lines, type_lines):
    pts = []
    for ln in code_lines:
        pts.append((ln, "code"))
    for ln in type_lines:
        pts.append((ln, "type"))
    if not pts:
        return []

    keep = []
    for ln, kind in pts:
        x = _f(getattr(ln, "x0", 0.0))
        y = _f(getattr(ln, "y0", 0.0))
        sz = _f(getattr(ln, "size", 0.0))
        dup = False
        for ln2, kind2 in keep:
            x2 = _f(getattr(ln2, "x0", 0.0))
            y2 = _f(getattr(ln2, "y0", 0.0))
            sz2 = _f(getattr(ln2, "size", 0.0))
            if abs(x - x2) <= 45.0 and abs(y - y2) <= 18.0 and abs(sz - sz2) <= 1.2:
                if kind2 == "code":
                    dup = True
                    break
                if kind == "code":
                    keep.remove((ln2, kind2))
                    break
        if not dup:
            keep.append((ln, kind))
    return keep


def extract(pages):
    out = []
    current_form = ""

    for page_index, lines in pages:
        if not lines:
            continue

        lines2 = _merge_split_bracket_ids(lines)
        small_sz = _page_small_font_size(lines2)

        code_lines = []
        type_lines = []
        for ln in lines2:
            t = (getattr(ln, "text", "") or "").strip()
            if not t:
                continue
            if _is_field_id_text(t):
                code_lines.append(ln)
            elif _is_type_line(ln):
                type_lines.append(ln)

        markers = _marker_points(code_lines, type_lines)
        if not markers:
            continue

        title = _page_colored_title(lines2, small_sz)
        if title:
            current_form = title
        else:
            heading = _page_top_black_heading(lines2, small_sz)
            if heading and (not current_form or _page_looks_like_lab_enum_list(lines2, small_sz)):
                current_form = heading

        form_name = _norm_text(current_form)

        label_lines = [ln for ln in lines2 if _label_candidate(ln, small_sz)]
        left_margin = min((_f(getattr(ln, "x0", 0.0)) for ln in label_lines), default=0.0)

        header_lines = [ln for ln in lines2 if _header_like(ln, small_sz)]
        two_col_split = _two_col_split_x(label_lines)

        recs = []
        for mk, kind in markers:
            if kind == "type" and not code_lines:
                base = _infer_field_label_for_type_line(lines2, mk, small_sz, label_lines, left_margin)
            elif kind == "type":
                base = _infer_field_label_for_type_line(lines2, mk, small_sz, label_lines, left_margin)
                if not base:
                    base = _infer_field_label(lines2, mk, small_sz, label_lines, left_margin, header_lines, two_col_split)
            else:
                base = _infer_field_label(lines2, mk, small_sz, label_lines, left_margin, header_lines, two_col_split)

            base = _norm_text(base)
            if not base:
                continue
            if _looks_like_chrome_or_empty(base):
                continue
            if _looks_like_choice_legend(base) or _looks_like_definition_sentence(base):
                continue
            recs.append({"base": base, "x": _f(getattr(mk, "x0", 0.0)), "y": _f(getattr(mk, "y0", 0.0))})

        if not recs:
            continue

        by_base = {}
        for r in recs:
            by_base.setdefault(r["base"], []).append(r)

        for base, rs in by_base.items():
            if len(rs) == 1:
                rs[0]["field_name"] = base
                continue

            xs = [r["x"] for r in rs]
            ys = [r["y"] for r in rs]
            try:
                x_med = float(statistics.median(xs))
            except Exception:
                x_med = xs[len(xs) // 2] if xs else 0.0

            same_rowish = (max(ys) - min(ys)) <= 9.0 if ys else False

            for r in rs:
                hdr = _nearest_header(header_lines, r["x"], r["y"])
                if hdr and (hdr.lower() not in base.lower()) and (not _looks_like_choice_legend(hdr)) and (not _is_timepointish_text(hdr)):
                    r["field_name"] = _norm_text(f"{base} - {hdr}")
                else:
                    if two_col_split is not None:
                        side = "Left" if r["x"] <= x_med else "Right"
                        r["field_name"] = _norm_text(f"{base} - {side}")
                    else:
                        r["field_name"] = base

            if two_col_split is None and same_rowish:
                names = {_norm_text(r.get("field_name", base)) for r in rs}
                if len(names) == 1:
                    rs.sort(key=lambda d: (d["y"], d["x"]))
                    keep = rs[0]
                    for r in rs[1:]:
                        r["drop"] = True
                    keep["drop"] = False

        emitted = []
        for r in sorted(recs, key=lambda d: (d["y"], d["x"])):
            if r.get("drop"):
                continue
            field_name = _norm_text(r.get("field_name", r["base"]))
            if not field_name:
                continue
            if _looks_like_chrome_or_empty(field_name):
                continue
            if _looks_like_choice_legend(field_name) or _looks_like_definition_sentence(field_name):
                continue

            key = (form_name, field_name)
            y = r["y"]
            dup = False
            for (k2, y2) in emitted:
                if k2 == key and abs(y2 - y) < 12.0:
                    dup = True
                    break
            if dup:
                continue

            out.append({"form_name": form_name, "field_name": field_name, "page": page_index + 1})
            emitted.append((key, y))

    return out
```
