```python
# Observed layouts: (1) blue form title near top; (2) annotated fields where black label text
# sits near a red bracketed machine code line and a red [TYPE: ...] line; (3) repeatable
# tables with a black multi-column header band. Strategy: carry forward the last detected
# form title, extract field labels anchored by red bracketed codes, plus table header labels.

import re
from typing import List, Dict, Tuple, Optional


_WS_RE = re.compile(r"\s+")
_BRACKET_CODE_RE = re.compile(r"^\[[A-Za-z0-9]+\]$")  # no ':' inside
_ENUM_PREFIX_RE = re.compile(r"^\(\s*\d+\s*\)|^\d+[\)\.]\s")  # rating-scale options etc.


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def _is_bracketed(s: str) -> bool:
    s = (s or "").strip()
    return len(s) >= 2 and s[0] == "[" and s[-1] == "]"


def _is_field_code_line(line) -> bool:
    # Machine code lines look like [DSAEYN], [AP1], [CSS0218A] and are printed in color (red).
    t = (line.text or "").strip()
    if not t:
        return False
    if not line.non_black:
        return False
    if ":" in t:
        return False
    if not _BRACKET_CODE_RE.match(t):
        return False
    inner = t[1:-1]
    if len(inner) < 2 or len(inner) > 24:
        return False
    if re.fullmatch(r"\d+", inner):
        return False
    return True


def _looks_like_noise_text(t: str) -> bool:
    t = _norm(t)
    if not t:
        return True
    if re.fullmatch(r"[\d\W_]+", t):
        return True
    # avoid bare single characters
    if len(t) == 1:
        return True
    return False


def _page_width(lines) -> float:
    mx = 0.0
    for l in lines:
        if getattr(l, "x1", 0.0) > mx:
            mx = float(l.x1)
    return mx or 600.0


def _median(nums: List[float]) -> float:
    if not nums:
        return 0.0
    s = sorted(nums)
    n = len(s)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return float((s[mid - 1] + s[mid]) / 2.0)


def _is_toc_like(lines) -> bool:
    # Navigation pages: many same-styled non-black (blue) lines in the body, typically lists.
    body = [l for l in lines if getattr(l, "y0", 0.0) >= 140.0]
    if len(body) < 14:
        return False
    big = [l for l in body if float(getattr(l, "size", 0.0)) >= 10.0]
    if len(big) < 12:
        return False
    non_black = sum(1 for l in big if getattr(l, "non_black", False))
    if non_black / max(1, len(big)) < 0.75:
        return False
    sizes = [float(l.size) for l in big]
    if not sizes:
        return False
    # TOC-like pages tend to have tight size range in the list.
    if (max(sizes) - min(sizes)) > 3.0:
        return False
    return True


def _detect_form_title(lines) -> str:
    # Prefer top non-black (blue) line with largest font size; ignore bracket annotations.
    cand = []
    for l in lines:
        if float(getattr(l, "y0", 1e9)) > 125.0:
            continue
        if not getattr(l, "non_black", False):
            continue
        t = _norm(l.text)
        if not t or _is_bracketed(t):
            continue
        cand.append(l)
    if not cand:
        return ""
    cand.sort(key=lambda l: (-float(l.size), float(l.y0), float(l.x0)))
    title = _norm(cand[0].text)
    return title


def _label_candidate(line, title_size: float) -> bool:
    if getattr(line, "non_black", False):
        return False
    t = _norm(line.text)
    if _looks_like_noise_text(t):
        return False
    if _is_bracketed(t):
        return False
    if float(getattr(line, "y0", 0.0)) < 30.0:
        return False
    if title_size and float(getattr(line, "size", 0.0)) >= (title_size * 0.95):
        return False
    return True


def _score_label(line, code_line, pw: float) -> float:
    t = _norm(line.text)
    dy = float(code_line.y0) - float(line.y0)
    x = float(line.x0)

    score = 0.0
    # closer above is better
    score += max(-200.0, -dy)

    # prefer left-column prompts
    if x <= pw * 0.25:
        score += 14.0
    elif x <= pw * 0.40:
        score += 7.0

    # bold often marks the real question/prompt
    if getattr(line, "bold", False):
        score += 10.0

    # penalize very long narrative paragraphs
    L = len(t)
    if L <= 80:
        score += 4.0
    elif L >= 160:
        score -= 8.0
    else:
        score -= (L - 80) / 20.0

    # penalize short "row marker"-like lines (very short + digits)
    toks = t.split()
    if len(toks) <= 2 and re.search(r"\d", t):
        score -= 12.0

    return score


def _expand_wrapped(lines, start_idx: int, stop_idx_exclusive: int) -> str:
    # Merge contiguous lines in the same column as wrapped label text.
    base = lines[start_idx]
    base_x = float(base.x0)
    parts = [_norm(base.text)]

    # upward
    j = start_idx - 1
    prev_y = float(base.y0)
    while j >= 0:
        l = lines[j]
        if getattr(l, "non_black", False):
            break
        if _is_bracketed(_norm(l.text)):
            break
        if abs(float(l.x0) - base_x) > 40.0:
            break
        if (prev_y - float(l.y0)) > 16.0:
            break
        tt = _norm(l.text)
        if _looks_like_noise_text(tt):
            break
        parts.insert(0, tt)
        prev_y = float(l.y0)
        j -= 1

    # downward until stop
    k = start_idx + 1
    prev_y = float(base.y0)
    while k < stop_idx_exclusive:
        l = lines[k]
        if getattr(l, "non_black", False):
            break
        if _is_bracketed(_norm(l.text)):
            break
        if abs(float(l.x0) - base_x) > 40.0:
            break
        if (float(l.y0) - prev_y) > 18.0:
            break
        tt = _norm(l.text)
        if _looks_like_noise_text(tt):
            break
        parts.append(tt)
        prev_y = float(l.y0)
        k += 1

    return _norm(" ".join(parts))


def _label_for_code(lines, code_idx: int, title_size: float) -> str:
    code_line = lines[code_idx]
    pw = _page_width(lines)

    best_j = None
    best_score = None

    # search window above code line
    for j in range(code_idx - 1, -1, -1):
        l = lines[j]
        dy = float(code_line.y0) - float(l.y0)
        if dy > 140.0:
            break
        if not _label_candidate(l, title_size):
            continue
        sc = _score_label(l, code_line, pw)
        if best_score is None or sc > best_score:
            best_score = sc
            best_j = j

    if best_j is None:
        return ""

    label = _expand_wrapped(lines, best_j, code_idx)
    # final sanity: avoid extracting obvious enumerated options
    if _ENUM_PREFIX_RE.match(label):
        return ""
    # avoid labels that are only punctuation/digits
    if _looks_like_noise_text(label):
        return ""
    return label


def _detect_table_headers(lines, title_size: float) -> List[str]:
    pw = _page_width(lines)
    black_sizes = [float(l.size) for l in lines if not getattr(l, "non_black", False) and float(l.y0) > 120.0]
    body_med = _median(black_sizes) or 7.0

    # candidates in a header band
    band = []
    for i, l in enumerate(lines):
        y = float(l.y0)
        if y < 135.0 or y > 220.0:
            continue
        if getattr(l, "non_black", False):
            continue
        if title_size and float(l.size) >= title_size * 0.95:
            continue
        t = _norm(l.text)
        if _looks_like_noise_text(t) or _is_bracketed(t):
            continue
        if _ENUM_PREFIX_RE.match(t):
            continue
        sz = float(l.size)
        if sz < body_med * 1.08 or sz > body_med * 1.7:
            continue
        band.append((i, l, t))

    if len(band) < 3:
        return []

    # require multi-column spread and a leftmost header
    xs = sorted(float(l.x0) for _, l, _ in band)
    if (max(xs) - min(xs)) < pw * 0.40:
        return []
    if min(xs) > pw * 0.20:
        return []

    # merge wrapped headers per column (x proximity)
    used = set()
    headers = []
    for idx, l, _ in band:
        if idx in used:
            continue
        x0 = float(l.x0)
        # find continuation lines close in x and within a small y window
        col = [(idx, l)]
        used.add(idx)
        y0 = float(l.y0)
        for jdx, l2, _t2 in band:
            if jdx in used:
                continue
            if abs(float(l2.x0) - x0) <= 45.0 and 0.0 < (float(l2.y0) - y0) <= 20.0:
                col.append((jdx, l2))
                used.add(jdx)
                y0 = float(l2.y0)

        col.sort(key=lambda p: float(p[1].y0))
        label = _norm(" ".join(_norm(p[1].text) for p in col))
        if label and not _looks_like_noise_text(label) and not _ENUM_PREFIX_RE.match(label):
            headers.append(label)

    # avoid over-extracting: header bands are usually small
    if len(headers) > 10:
        return []
    return headers


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    seen = set()

    current_form = ""

    for page_idx0, lines in pages:
        page_num = int(page_idx0) + 1
        if not lines:
            continue

        toc_like = _is_toc_like(lines)

        title = _detect_form_title(lines)
        if title and not toc_like:
            current_form = title

        # title font size (for filtering)
        max_size = 0.0
        for l in lines:
            sz = float(getattr(l, "size", 0.0))
            if sz > max_size:
                max_size = sz
        title_size = max_size

        # extract via codes
        for i, l in enumerate(lines):
            if not _is_field_code_line(l):
                continue
            label = _label_for_code(lines, i, title_size)
            if not label:
                continue
            rec = {"form_name": current_form or "", "field_name": label, "page": page_num}
            key = (rec["page"], rec["form_name"], rec["field_name"])
            if key not in seen:
                seen.add(key)
                out.append(rec)

        # extract table header band fields (often repeatable grids)
        if not toc_like:
            for h in _detect_table_headers(lines, title_size):
                rec = {"form_name": current_form or "", "field_name": h, "page": page_num}
                key = (rec["page"], rec["form_name"], rec["field_name"])
                if key not in seen:
                    seen.add(key)
                    out.append(rec)

    return out
```
