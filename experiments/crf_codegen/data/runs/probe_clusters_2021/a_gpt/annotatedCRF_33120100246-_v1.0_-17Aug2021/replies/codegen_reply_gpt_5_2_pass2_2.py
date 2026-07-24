import re
from typing import List, Tuple, Dict, Any, Optional

_RE_ROW = re.compile(r"^\s*Row\s*\d+\s*$", re.IGNORECASE)
_RE_NUM_PREFIX = re.compile(r"^\s*\d+\s*[\.\)]\s+\S")
_RE_TOC_NUM = re.compile(r"^\s*\d+(\.\d+)+\.\s+\S")

def _norm_space(s: str) -> str:
    return " ".join((s or "").strip().split())

def _is_bracket_line(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("[") and t.endswith("]") and len(t) >= 2

def _is_meta_bracket(text: str) -> bool:
    t = (text or "").strip()
    if not _is_bracket_line(t):
        return False
    inner = t[1:-1].strip().lower()
    return (
        inner.startswith("type:")
        or inner.startswith("visibility:")
        or inner.startswith("read-only")
        or inner.startswith("readonly")
    )

def _is_var_code_bracket(text: str) -> bool:
    t = (text or "").strip()
    if not _is_bracket_line(t):
        return False
    if _is_meta_bracket(t):
        return False
    inner = t[1:-1].strip()
    if " " in inner:
        return False
    if not inner:
        return False
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", inner):
        return False
    return True

def _is_probably_footer_header(line, y_max: float) -> bool:
    return (y_max is not None and line.y0 > y_max - 18 and line.size <= 9.5)

def _is_schedule_page(lines) -> bool:
    for ln in lines:
        t = (ln.text or "").strip()
        if t.startswith("Schedule_") and ln.x0 < 120 and ln.size >= 9.0:
            return True
    return False

def _is_toc_like_page(lines) -> bool:
    cnt = 0
    ys = []
    for ln in lines:
        t = (ln.text or "").strip()
        if not t:
            continue
        if ln.non_black and ln.x0 < 220 and 11.5 <= ln.size <= 15.5 and _RE_TOC_NUM.match(t):
            cnt += 1
            ys.append(ln.y0)
    if cnt >= 8:
        ys.sort()
        if ys[-1] - ys[0] > 200:
            return True
    return False

def _detect_form_title(lines, page_ymax: float) -> Optional[str]:
    cands = []
    for i, ln in enumerate(lines):
        t = (ln.text or "").strip()
        if not t:
            continue
        if _is_bracket_line(t):
            continue
        if _is_probably_footer_header(ln, page_ymax):
            continue
        if ln.y0 > 140:
            continue
        if ln.x0 > 220:
            continue
        if ln.size < 11.5:
            continue
        if ln.non_black or ln.bold:
            cands.append((ln.y0, -ln.size, ln.x0, i, t))
    if not cands:
        return None
    cands.sort()
    _, _, _, idx, t0 = cands[0]
    parts = [t0]
    base = lines[idx]
    last = base
    for _, _, _, j, tj in cands[1:6]:
        ln = lines[j]
        if ln.y0 - last.y1 > max(3.0, 1.8 * base.size):
            continue
        if abs(ln.x0 - base.x0) > 30:
            continue
        if abs(ln.size - base.size) > 3.5:
            continue
        if _RE_TOC_NUM.match(tj):
            continue
        parts.append(tj)
        last = ln
    title = _norm_space(" ".join(parts))
    if _RE_TOC_NUM.match(title):
        return None
    return title or None

def _merge_bracket_fragments(lines):
    used = [False] * len(lines)
    merged = []
    for i, ln in enumerate(lines):
        if used[i]:
            continue
        t = (ln.text or "").strip()
        if not t or not ("[" in t):
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
            for j in range(i + 1, min(len(lines), i + 6)):
                ln2 = lines[j]
                if used[j]:
                    continue
                if not ln2.non_black:
                    break
                if abs(ln2.x0 - x0) > 4.0:
                    continue
                if abs(ln2.size - size0) > 1.5:
                    continue
                if ln2.y0 - lasty > 18.0:
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

def _line_is_candidate_label(ln) -> bool:
    t = (ln.text or "").strip()
    if not t:
        return False
    if _is_bracket_line(t):
        return False
    if _RE_ROW.match(t):
        return False
    return True

def _looks_like_long_body(t: str, bold: bool) -> bool:
    tt = (t or "").strip()
    if bold:
        return False
    if len(tt) <= 90:
        return False
    if "?" in tt or ":" in tt:
        return False
    return True

def _join_wrapped_label(lines, anchor_idx: int, max_up: int = 2, max_down: int = 4) -> str:
    anchor = lines[anchor_idx]
    if not _line_is_candidate_label(anchor):
        return ""
    idxs = [anchor_idx]
    base_x = anchor.x0
    base_size = anchor.size

    def ok_wrap(prev, cur) -> bool:
        if not _line_is_candidate_label(cur):
            return False
        if abs(cur.x0 - base_x) > 26.0:
            return False
        if abs(cur.size - base_size) > max(2.2, 0.35 * base_size):
            return False
        gap = cur.y0 - prev.y1
        if gap > max(4.0, 1.9 * base_size):
            return False
        if _looks_like_long_body((cur.text or "").strip(), cur.bold):
            return False
        return True

    up = 0
    k = anchor_idx - 1
    prev_top = anchor
    while k >= 0 and up < max_up:
        cur = lines[k]
        if not ok_wrap(cur, prev_top):
            break
        idxs.insert(0, k)
        prev_top = cur
        up += 1
        k -= 1

    down = 0
    prev = anchor
    k = anchor_idx + 1
    while k < len(lines) and down < max_down:
        cur = lines[k]
        if not ok_wrap(prev, cur):
            break
        idxs.append(k)
        prev = cur
        down += 1
        k += 1

    parts = [_norm_space(lines[i].text) for i in idxs]
    return _norm_space(" ".join([p for p in parts if p]))

def _looks_like_header_label(t: str, ln) -> bool:
    tt = (t or "").strip()
    if not tt:
        return False
    if _looks_like_long_body(tt, ln.bold):
        return False
    if len(tt) > 55:
        return False
    if tt.endswith("."):
        return False
    if "(" in tt and ")" in tt and len(tt) > 35:
        return False
    if ln.bold:
        return True
    # Small headers are often colored hyperlinks in schedules, but we avoid schedule pages elsewhere.
    if ln.size >= 8.4 and (":" in tt or "?" in tt or _RE_NUM_PREFIX.match(tt) or len(tt) <= 22):
        return True
    return False

def _find_label_for_marker(marker_x: float, marker_y: float, lines) -> str:
    def score_candidate(i: int, ln, t: str, mode: str) -> Optional[float]:
        if not _line_is_candidate_label(ln):
            return None
        if ln.x0 > 560:
            return None
        dy = ln.y0 - marker_y

        if mode == "left_only":
            # Intended for value-column markers where labels are on the left.
            if marker_x >= 260:
                if ln.x0 > 260:
                    return None
            else:
                if ln.x0 > 320:
                    return None
                if abs(ln.x0 - marker_x) > 160 and ln.x0 > 260:
                    return None
            if dy < -140 or dy > 220:
                return None

        elif mode == "same_column_header":
            # For table-style columns: label sits above in the same column as the marker.
            if abs(ln.x0 - marker_x) > 70:
                return None
            if dy < -260 or dy > 80:
                return None
            if not _looks_like_header_label(t, ln):
                return None

        else:
            return None

        if _looks_like_long_body(t, ln.bold):
            return None
        if _RE_ROW.match(t):
            return None

        base = abs(dy)

        if dy > 0:
            base *= 1.15 if marker_y >= 90 else 0.95
        else:
            base *= 0.95

        base += max(0.0, (ln.x0 - 70.0)) * 0.02

        if marker_x >= 260 and ln.bold and mode == "left_only":
            base *= 0.82

        if ("?" in t) or (":" in t) or _RE_NUM_PREFIX.match(t):
            base *= 0.85

        if mode == "same_column_header":
            # Slight penalty so left labels win when available.
            base += 12.0

        return base

    best_idx = None
    best_score = None

    # Primary pass (existing behavior): marker -> nearby label (usually left of value column).
    for i, ln in enumerate(lines):
        t = (ln.text or "").strip()
        sc = score_candidate(i, ln, t, "left_only")
        if sc is None:
            continue
        if best_score is None or sc < best_score:
            best_score = sc
            best_idx = i

    # Secondary pass: for right-column markers, allow same-column header labels above.
    if marker_x >= 260:
        best2_idx = None
        best2_score = None
        for i, ln in enumerate(lines):
            t = (ln.text or "").strip()
            sc = score_candidate(i, ln, t, "same_column_header")
            if sc is None:
                continue
            if best2_score is None or sc < best2_score:
                best2_score = sc
                best2_idx = i

        if best2_idx is not None:
            # Prefer same-column header only if it is clearly better, or no left label exists.
            if best_idx is None or (best_score is not None and best2_score is not None and best2_score < best_score * 0.92):
                best_idx = best2_idx

    if best_idx is None:
        return ""
    return _join_wrapped_label(lines, best_idx)

def _extract_question_like_from_option_block(lines, page_ymax: float) -> List[int]:
    # Detect pages dominated by small red enumeration/option text (definitions/options) and
    # try to capture the corresponding question/field label on the left, if printed.
    opt = []
    for i, ln in enumerate(lines):
        t = (ln.text or "").strip()
        if not t:
            continue
        if _is_probably_footer_header(ln, page_ymax):
            continue
        if not ln.non_black:
            continue
        if ln.size > 8.6:
            continue
        if ln.x0 < 280:
            continue
        if re.search(r"\(\s*\d+\s*\)", t) or "does not apply" in t.lower() or "not applicable" in t.lower():
            opt.append((i, ln))
    if len(opt) < 4:
        return []

    ys = [ln.y0 for _, ln in opt]
    y_min = min(ys)
    y_max = max(ys)
    if (y_max - y_min) < 35:
        return []

    # Find the best question/label line near this option block on the left side.
    best_idx = None
    best_score = None
    for i, ln in enumerate(lines):
        t = (ln.text or "").strip()
        if not _line_is_candidate_label(ln):
            continue
        if _is_probably_footer_header(ln, page_ymax):
            continue
        if ln.x0 >= 280:
            continue
        if ln.size < 7.6 or ln.size > 12.0:
            continue
        if ln.y0 < (y_min - 70) or ln.y0 > (y_max + 50):
            continue
        if _looks_like_long_body(t, ln.bold):
            continue

        # Must look like a question/field label if not bold.
        if not ln.bold:
            if not ("?" in t or ":" in t or _RE_NUM_PREFIX.match(t)):
                continue

        dy = y_min - ln.y0
        sc = abs(dy)
        if ln.bold:
            sc *= 0.82
        if "?" in t or ":" in t or _RE_NUM_PREFIX.match(t):
            sc *= 0.88
        sc += max(0.0, (ln.x0 - 70.0)) * 0.02

        if best_score is None or sc < best_score:
            best_score = sc
            best_idx = i

    return [best_idx] if best_idx is not None else []

def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        page_ymax = max((ln.y1 for ln in lines), default=0.0)

        if _is_toc_like_page(lines) or _is_schedule_page(lines):
            continue

        title = _detect_form_title(lines, page_ymax)
        if title:
            current_form = title

        merged = _merge_bracket_fragments(lines)
        markers = []
        for x0, y0, _sz, txt in merged:
            t = (txt or "").strip()
            if _is_var_code_bracket(t):
                markers.append((x0, y0, t))

        seen = set()

        # Marker-anchored labels (primary).
        for mx, my, _code in markers:
            label = _find_label_for_marker(mx, my, lines)
            label = _norm_space(label)
            if not label:
                continue
            key = (current_form, label)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1})

        # If no markers, try to recover question labels paired with printed option/definition blocks.
        if not markers:
            q_idxs = _extract_question_like_from_option_block(lines, page_ymax)
            for qi in q_idxs:
                if qi is None:
                    continue
                label = _join_wrapped_label(lines, qi)
                label = _norm_space(label)
                if not label or _RE_ROW.match(label):
                    continue
                key = (current_form, label)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1})

        # Extra: left-column bold question/label lines even if no code shown nearby.
        for i, ln in enumerate(lines):
            if not ln.bold:
                continue
            if ln.x0 > 260:
                continue
            if ln.size > 11.5:
                continue
            if _is_probably_footer_header(ln, page_ymax):
                continue
            if not _line_is_candidate_label(ln):
                continue
            t = (ln.text or "").strip()
            if _RE_ROW.match(t):
                continue
            if not ("?" in t or ":" in t or _RE_NUM_PREFIX.match(t) or len(t) <= 55):
                continue

            label = _join_wrapped_label(lines, i)
            label = _norm_space(label)
            if not label or _RE_ROW.match(label):
                continue
            key = (current_form, label)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1})

    return out
