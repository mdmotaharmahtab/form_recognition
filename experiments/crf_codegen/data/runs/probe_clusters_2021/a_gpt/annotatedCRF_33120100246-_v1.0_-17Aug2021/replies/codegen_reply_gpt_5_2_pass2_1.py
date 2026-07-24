```python
# Observed layouts: (1) TOC/schedule listing pages with many blue links; (2) eCRF form pages
# with a prominent top-left title (often blue ~14–16pt) and many red bracketed codes/TYPE lines;
# (3) instrument-style pages (C-SSRS) with left-column bold questions and right-column answer cells.
# Strategy: track the current form title from prominent top-left titles; extract field labels by
# anchoring on red bracketed variable codes and, additionally, on left-column bold question lines.
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
    # Variable-like: alnum/underscore, starts with a letter, no spaces/punctuation.
    if " " in inner:
        return False
    if not inner:
        return False
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", inner):
        return False
    return True

def _is_probably_footer_header(line, y_max: float) -> bool:
    # Very light touch: keep near-top labels (forms often start at y~35),
    # but exclude extreme bottom furniture.
    return (y_max is not None and line.y0 > y_max - 18 and line.size <= 9.5)

def _is_schedule_page(lines) -> bool:
    for ln in lines:
        t = (ln.text or "").strip()
        if t.startswith("Schedule_") and ln.x0 < 120 and ln.size >= 9.0:
            return True
    return False

def _is_toc_like_page(lines) -> bool:
    # Many blue-ish numbered entries down the page.
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
        # ensure they span meaningfully (not a single header block)
        ys.sort()
        if ys[-1] - ys[0] > 200:
            return True
    return False

def _detect_form_title(lines, page_ymax: float) -> Optional[str]:
    # Prominent top-left title: usually non-black blue ~14–16pt; sometimes black bold ~12–16pt.
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
    # Join consecutive title lines if they look like wrapped title.
    y0, _, x0, idx, t0 = cands[0]
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
    # Avoid treating TOC entry as title.
    if _RE_TOC_NUM.match(title):
        return None
    return title or None

def _merge_bracket_fragments(lines):
    # Create "virtual" bracket lines by merging wrapped colored bracket fragments like "[SCANNE" + "R]".
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
            # keep normal single-line bracket code as-is for convenience
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
    # Exclude very long non-bold paragraphs (instrument disclaimers / explanations).
    tt = (t or "").strip()
    if bold:
        return False
    if len(tt) <= 90:
        return False
    # keep if it has strong "label-ish" punctuation
    if "?" in tt or ":" in tt:
        return False
    return True

def _join_wrapped_label(lines, anchor_idx: int, max_up: int = 2, max_down: int = 4) -> str:
    anchor = lines[anchor_idx]
    if not _line_is_candidate_label(anchor):
        return ""
    # Grow upward
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
        # Don't pull in obvious long body paragraphs unless anchor is already long/bold-ish.
        if _looks_like_long_body((cur.text or "").strip(), cur.bold):
            return False
        return True

    # Up
    up = 0
    k = anchor_idx - 1
    prev_top = anchor
    while k >= 0 and up < max_up:
        cur = lines[k]
        if not ok_wrap(cur, prev_top):  # note: "prev" for upward is reversed
            break
        idxs.insert(0, k)
        prev_top = cur
        up += 1
        k -= 1

    # Down
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

def _find_label_for_marker(marker_x: float, marker_y: float, lines) -> str:
    # Search around marker for nearest label line(s).
    # If marker is on right side, prefer left-column bold lines near same y band.
    best_idx = None
    best_score = None

    for i, ln in enumerate(lines):
        if not _line_is_candidate_label(ln):
            continue
        # exclude far-right option blocks as labels
        if ln.x0 > 560:
            continue
        dy = ln.y0 - marker_y
        if dy < -140 or dy > 220:
            continue

        # Candidate region depends on marker position
        if marker_x >= 260:
            # marker on value column; label expected on left
            if ln.x0 > 260:
                continue
        else:
            # marker on left; label may be left/nearby (sometimes below for table rows)
            if ln.x0 > 320:
                continue
            if abs(ln.x0 - marker_x) > 160 and ln.x0 > 260:
                continue

        t = (ln.text or "").strip()
        if _looks_like_long_body(t, ln.bold):
            continue
        if _RE_ROW.match(t):
            continue

        # Score: prefer close in y; prefer slightly above marker (typical label-above-code),
        # but allow label-below for header-like markers near the top.
        base = abs(dy)
        if dy > 0:
            # below marker: slightly penalize unless marker is near top
            base *= 1.15 if marker_y >= 90 else 0.95
        else:
            # above marker: slight preference
            base *= 0.95

        # Prefer left margin labels
        base += max(0.0, (ln.x0 - 70.0)) * 0.02

        # Prefer bold lines for right-side markers (C-SSRS etc.)
        if marker_x >= 260 and ln.bold:
            base *= 0.82

        # Prefer label-ish punctuation/numbering
        if ("?" in t) or (":" in t) or _RE_NUM_PREFIX.match(t):
            base *= 0.85

        if best_score is None or base < best_score:
            best_score = base
            best_idx = i

    if best_idx is None:
        return ""
    return _join_wrapped_label(lines, best_idx)

def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        page_ymax = max((ln.y1 for ln in lines), default=0.0)

        # Skip known non-form templates (but do not globally skip unknown pages).
        if _is_toc_like_page(lines) or _is_schedule_page(lines):
            continue

        title = _detect_form_title(lines, page_ymax)
        if title:
            current_form = title

        # Build merged bracket fragments then select variable code markers.
        merged = _merge_bracket_fragments(lines)
        markers = []
        for x0, y0, _sz, txt in merged:
            t = (txt or "").strip()
            if _is_var_code_bracket(t):
                markers.append((x0, y0, t))

        seen = set()

        # Marker-anchored labels (primary, high precision).
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

        # Extra: left-column bold question/label lines even if no code shown nearby (e.g., some enumerations).
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
            # Avoid pulling in generic bold table headings unless they look question/label-like.
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
```
