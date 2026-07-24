```python
import re
from typing import List, Dict, Tuple


_WS_RE = re.compile(r"\s+")
_BRACKET_CODE_RE = re.compile(r"^\[[A-Za-z0-9]+\]$")  # no ':' inside
_ENUM_PREFIX_RE = re.compile(r"^\(\s*\d+\s*\)|^\d+[\)\.]\s")


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def _is_bracketed(s: str) -> bool:
    s = (s or "").strip()
    return len(s) >= 2 and s[0] == "[" and s[-1] == "]"


def _looks_like_noise_text(t: str) -> bool:
    t = _norm(t)
    if not t:
        return True
    if re.fullmatch(r"[\d\W_]+", t):
        return True
    if len(t) == 1:
        return True
    return False


def _page_width(lines) -> float:
    mx = 0.0
    for l in lines:
        x1 = float(getattr(l, "x1", 0.0) or 0.0)
        if x1 > mx:
            mx = x1
    return mx or 600.0


def _page_height(lines) -> float:
    mx = 0.0
    for l in lines:
        y1 = float(getattr(l, "y1", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y1 > mx:
            mx = y1
        if y0 > mx:
            mx = y0
    return mx or 800.0


def _median(nums: List[float]) -> float:
    if not nums:
        return 0.0
    s = sorted(nums)
    n = len(s)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return float((s[mid - 1] + s[mid]) / 2.0)


def _is_field_code_line(line) -> bool:
    t = (getattr(line, "text", "") or "").strip()
    if not t:
        return False
    if not getattr(line, "non_black", False):
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


def _detect_form_title_and_size(lines) -> Tuple[str, float]:
    cand = []
    for l in lines:
        if float(getattr(l, "y0", 1e9)) > 125.0:
            continue
        if not getattr(l, "non_black", False):
            continue
        t = _norm(getattr(l, "text", ""))
        if not t or _is_bracketed(t):
            continue
        cand.append(l)
    if not cand:
        return "", 0.0
    cand.sort(key=lambda l: (-float(getattr(l, "size", 0.0) or 0.0), float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))
    title_line = cand[0]
    return _norm(getattr(title_line, "text", "")), float(getattr(title_line, "size", 0.0) or 0.0)


def _is_toc_like(lines) -> bool:
    body = [l for l in lines if float(getattr(l, "y0", 0.0)) >= 140.0]
    if len(body) < 14:
        return False
    big = [l for l in body if float(getattr(l, "size", 0.0)) >= 10.0]
    if len(big) < 12:
        return False
    non_black = sum(1 for l in big if getattr(l, "non_black", False))
    if non_black / max(1, len(big)) < 0.75:
        return False
    sizes = [float(getattr(l, "size", 0.0) or 0.0) for l in big]
    if not sizes:
        return False
    if (max(sizes) - min(sizes)) > 3.0:
        return False
    return True


def _label_candidate(line, title_size: float, ph: float) -> bool:
    if getattr(line, "non_black", False):
        return False
    t = _norm(getattr(line, "text", ""))
    if _looks_like_noise_text(t):
        return False
    if _is_bracketed(t):
        return False
    y0 = float(getattr(line, "y0", 0.0) or 0.0)
    if y0 < ph * 0.04:
        return False
    if title_size and float(getattr(line, "size", 0.0) or 0.0) >= (title_size * 0.95):
        return False
    if _ENUM_PREFIX_RE.match(t):
        return False
    return True


def _score_label(line, code_line, pw: float, prefer_left: bool = True) -> float:
    t = _norm(getattr(line, "text", ""))
    dy = float(getattr(code_line, "y0", 0.0) or 0.0) - float(getattr(line, "y0", 0.0) or 0.0)
    x0 = float(getattr(line, "x0", 0.0) or 0.0)
    x1 = float(getattr(line, "x1", x0) or x0)

    score = 0.0
    score += max(-220.0, -abs(dy))

    if prefer_left:
        if x0 <= pw * 0.25:
            score += 16.0
        elif x0 <= pw * 0.40:
            score += 8.0
        elif x0 <= pw * 0.55:
            score += 1.0
        else:
            score -= 6.0

    if getattr(line, "bold", False):
        score += 10.0

    if "?" in t:
        score += 3.0

    L = len(t)
    if L <= 80:
        score += 5.0
    elif L >= 170:
        score -= 10.0
    else:
        score -= (L - 80) / 22.0

    toks = t.split()
    if len(toks) <= 2 and re.search(r"\d", t):
        score -= 14.0

    if x1 <= float(getattr(code_line, "x0", 0.0) or 0.0):
        score += 3.0

    return score


def _expand_wrapped(lines, start_idx: int, stop_idx_exclusive: int) -> str:
    base = lines[start_idx]
    base_x = float(getattr(base, "x0", 0.0) or 0.0)
    parts = [_norm(getattr(base, "text", ""))]

    j = start_idx - 1
    prev_y = float(getattr(base, "y0", 0.0) or 0.0)
    while j >= 0:
        l = lines[j]
        if getattr(l, "non_black", False):
            break
        tt = _norm(getattr(l, "text", ""))
        if not tt or _is_bracketed(tt) or _ENUM_PREFIX_RE.match(tt) or _looks_like_noise_text(tt):
            break
        if abs(float(getattr(l, "x0", 0.0) or 0.0) - base_x) > 48.0:
            break
        if (prev_y - float(getattr(l, "y0", 0.0) or 0.0)) > 18.0:
            break
        parts.insert(0, tt)
        prev_y = float(getattr(l, "y0", 0.0) or 0.0)
        j -= 1

    k = start_idx + 1
    prev_y = float(getattr(base, "y0", 0.0) or 0.0)
    while k < stop_idx_exclusive:
        l = lines[k]
        if getattr(l, "non_black", False):
            break
        tt = _norm(getattr(l, "text", ""))
        if not tt or _is_bracketed(tt) or _ENUM_PREFIX_RE.match(tt) or _looks_like_noise_text(tt):
            break
        if abs(float(getattr(l, "x0", 0.0) or 0.0) - base_x) > 52.0:
            break
        if (float(getattr(l, "y0", 0.0) or 0.0) - prev_y) > 20.0:
            break
        parts.append(tt)
        prev_y = float(getattr(l, "y0", 0.0) or 0.0)
        k += 1

    return _norm(" ".join(parts))


def _inline_neighbor_label(lines, code_idx: int, title_size: float, ph: float) -> str:
    code = lines[code_idx]
    y = float(getattr(code, "y0", 0.0) or 0.0)
    x0c = float(getattr(code, "x0", 0.0) or 0.0)
    x1c = float(getattr(code, "x1", x0c) or x0c)

    best = None  # (score, idx)
    for i, l in enumerate(lines):
        if i == code_idx:
            continue
        if not _label_candidate(l, title_size, ph):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if abs(y0 - y) > 7.0:
            continue

        lx0 = float(getattr(l, "x0", 0.0) or 0.0)
        lx1 = float(getattr(l, "x1", lx0) or lx0)
        if lx1 <= x0c - 4.0:
            dist = x0c - lx1
            sc = 50.0 - min(50.0, dist / 3.0)
            if getattr(l, "bold", False):
                sc += 4.0
            if best is None or sc > best[0]:
                best = (sc, i)
        elif lx0 >= x1c + 4.0:
            dist = lx0 - x1c
            sc = 44.0 - min(44.0, dist / 3.0)
            if getattr(l, "bold", False):
                sc += 3.0
            if best is None or sc > best[0]:
                best = (sc, i)

    if best is None:
        return ""
    label = _expand_wrapped(lines, best[1], len(lines))
    if not label or _looks_like_noise_text(label) or _ENUM_PREFIX_RE.match(label):
        return ""
    return label


def _nearby_label_above_below(lines, code_idx: int, title_size: float, ph: float) -> str:
    code_line = lines[code_idx]
    pw = _page_width(lines)

    best_j = None
    best_score = None

    cy = float(getattr(code_line, "y0", 0.0) or 0.0)
    for j in range(code_idx - 1, -1, -1):
        l = lines[j]
        dy = cy - float(getattr(l, "y0", 0.0) or 0.0)
        if dy > 160.0:
            break
        if not _label_candidate(l, title_size, ph):
            continue
        sc = _score_label(l, code_line, pw, prefer_left=True)
        if best_score is None or sc > best_score:
            best_score = sc
            best_j = j

    if best_j is not None:
        label = _expand_wrapped(lines, best_j, code_idx)
        if label and not _looks_like_noise_text(label) and not _ENUM_PREFIX_RE.match(label):
            return label

    best_j = None
    best_score = None
    for j in range(code_idx + 1, min(len(lines), code_idx + 40)):
        l = lines[j]
        dy = float(getattr(l, "y0", 0.0) or 0.0) - cy
        if dy <= 0:
            continue
        if dy > 85.0:
            break
        if not _label_candidate(l, title_size, ph):
            continue
        lx0 = float(getattr(l, "x0", 0.0) or 0.0)
        if abs(lx0 - float(getattr(code_line, "x0", 0.0) or 0.0)) > 80.0 and lx0 > pw * 0.55:
            continue
        sc = 20.0 - dy
        if lx0 <= pw * 0.40:
            sc += 8.0
        if getattr(l, "bold", False):
            sc += 5.0
        L = len(_norm(getattr(l, "text", "")))
        sc += 4.0 if L <= 90 else -2.0
        if best_score is None or sc > best_score:
            best_score = sc
            best_j = j

    if best_j is not None:
        label = _expand_wrapped(lines, best_j, len(lines))
        if label and not _looks_like_noise_text(label) and not _ENUM_PREFIX_RE.match(label):
            return label

    return ""


def _label_near_code(lines, code_idx: int, title_size: float) -> str:
    ph = _page_height(lines)

    label = _inline_neighbor_label(lines, code_idx, title_size, ph)
    if label:
        return label

    label = _nearby_label_above_below(lines, code_idx, title_size, ph)
    if label:
        return label

    return ""


def _group_code_lines(lines, code_idxs: List[int]) -> List[List[int]]:
    items = []
    for idx in code_idxs:
        l = lines[idx]
        items.append((float(getattr(l, "y0", 0.0) or 0.0), float(getattr(l, "x0", 0.0) or 0.0), idx))
    items.sort()

    groups: List[List[int]] = []
    cur: List[int] = []
    cur_x = None
    cur_y = None

    for y, x, idx in items:
        if not cur:
            cur = [idx]
            cur_x = x
            cur_y = y
            continue
        if abs(x - float(cur_x)) <= 18.0 and (y - float(cur_y)) <= 28.0:
            cur.append(idx)
            cur_x = (float(cur_x) * 0.7) + (x * 0.3)
            cur_y = y
        else:
            groups.append(cur)
            cur = [idx]
            cur_x = x
            cur_y = y

    if cur:
        groups.append(cur)
    return groups


def _find_group_question_label(lines, member_idxs: List[int], title_size: float) -> str:
    pw = _page_width(lines)
    ph = _page_height(lines)

    min_y = min(float(getattr(lines[i], "y0", 0.0) or 0.0) for i in member_idxs)
    min_i = min(member_idxs)

    opt_x = _median([float(getattr(lines[i], "x0", 0.0) or 0.0) for i in member_idxs])
    best = None  # (score, idx)

    for j in range(min_i - 1, -1, -1):
        l = lines[j]
        y = float(getattr(l, "y0", 0.0) or 0.0)
        dy = min_y - y
        if dy > 200.0:
            break
        if not _label_candidate(l, title_size, ph):
            continue

        t0 = _norm(getattr(l, "text", ""))
        if len(t0) < 18:
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if x0 > pw * 0.55:
            continue

        sc = 0.0
        sc += 60.0 - min(60.0, dy / 2.8)
        sc += 10.0 if x0 <= pw * 0.40 else 2.0
        sc -= min(12.0, abs(x0 - (pw * 0.10)) / 20.0)
        sc -= min(8.0, abs(x0 - opt_x) / 30.0)
        if getattr(l, "bold", False):
            sc += 8.0
        if "?" in t0:
            sc += 4.0

        if best is None or sc > best[0]:
            best = (sc, j)

    if best is None:
        return ""

    label = _expand_wrapped(lines, best[1], min_i)
    if not label or _looks_like_noise_text(label) or _ENUM_PREFIX_RE.match(label):
        return ""
    return label


def _detect_table_headers(lines, title_size: float) -> List[str]:
    pw = _page_width(lines)

    black_sizes = [
        float(getattr(l, "size", 0.0) or 0.0)
        for l in lines
        if (not getattr(l, "non_black", False)) and float(getattr(l, "y0", 0.0) or 0.0) > 120.0
    ]
    body_med = _median(black_sizes) or 7.0

    cands = []
    for i, l in enumerate(lines):
        y = float(getattr(l, "y0", 0.0) or 0.0)
        if y < 125.0 or y > 260.0:
            continue
        if getattr(l, "non_black", False):
            continue
        if title_size and float(getattr(l, "size", 0.0) or 0.0) >= title_size * 0.95:
            continue

        t = _norm(getattr(l, "text", ""))
        if _looks_like_noise_text(t) or _is_bracketed(t) or _ENUM_PREFIX_RE.match(t):
            continue

        sz = float(getattr(l, "size", 0.0) or 0.0)
        if sz < body_med * 1.10 or sz > body_med * 1.85:
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if x0 > pw * 0.75:
            continue

        cands.append((i, l, t))

    if len(cands) < 3:
        return []

    buckets: List[List[Tuple[int, object, str]]] = []
    cands_sorted = sorted(cands, key=lambda p: float(getattr(p[1], "y0", 0.0) or 0.0))
    for itm in cands_sorted:
        y = float(getattr(itm[1], "y0", 0.0) or 0.0)
        placed = False
        for b in buckets:
            by = float(getattr(b[0][1], "y0", 0.0) or 0.0)
            if abs(y - by) <= 8.0:
                b.append(itm)
                placed = True
                break
        if not placed:
            buckets.append([itm])

    def _distinct_cols(bucket):
        cols = set()
        for _i, l, _t in bucket:
            x0 = float(getattr(l, "x0", 0.0) or 0.0)
            cols.add(int(round(x0 / 60.0)))
        return len(cols)

    best_bucket = None
    best_key = None
    for b in buckets:
        dc = _distinct_cols(b)
        if dc < 3:
            continue
        xs = [float(getattr(l, "x0", 0.0) or 0.0) for _, l, _ in b]
        if (max(xs) - min(xs)) < pw * 0.40:
            continue
        if min(xs) > pw * 0.22:
            continue
        topy = min(float(getattr(l, "y0", 0.0) or 0.0) for _, l, _ in b)
        key = (dc, -topy)
        if best_key is None or key > best_key:
            best_key = key
            best_bucket = b

    if not best_bucket:
        return []

    header_items = sorted(best_bucket, key=lambda p: float(getattr(p[1], "x0", 0.0) or 0.0))
    used = set(i for i, _, _ in header_items)
    headers: List[str] = []

    for idx, l, _t in header_items:
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        parts = [(_norm(getattr(l, "text", "")), y0)]
        cur_y = y0

        for j in range(idx + 1, min(len(lines), idx + 20)):
            if j in used:
                continue
            l2 = lines[j]
            if getattr(l2, "non_black", False):
                continue
            t2 = _norm(getattr(l2, "text", ""))
            if not t2 or _looks_like_noise_text(t2) or _is_bracketed(t2) or _ENUM_PREFIX_RE.match(t2):
                continue
            if abs(float(getattr(l2, "x0", 0.0) or 0.0) - x0) > 45.0:
                continue
            y2 = float(getattr(l2, "y0", 0.0) or 0.0)
            if not (0.0 < (y2 - cur_y) <= 20.0):
                continue
            parts.append((t2, y2))
            used.add(j)
            cur_y = y2

        parts.sort(key=lambda p: p[1])
        label = _norm(" ".join(p[0] for p in parts))
        if label and not _looks_like_noise_text(label) and not _ENUM_PREFIX_RE.match(label):
            headers.append(label)

    if len(headers) > 12:
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

        title, title_size = _detect_form_title_and_size(lines)
        if title and not toc_like:
            current_form = title

        code_idxs = [i for i, l in enumerate(lines) if _is_field_code_line(l)]

        groups = _group_code_lines(lines, code_idxs)
        option_group_handled = set()

        for g in groups:
            if len(g) < 3:
                continue

            labels = [(_label_near_code(lines, idx, title_size) or "") for idx in g]
            shortish = [lb for lb in labels if lb and len(lb) <= 35]
            if len(shortish) < max(2, int(0.7 * len(g))):
                continue

            qlabel = _find_group_question_label(lines, g, title_size)
            if not qlabel:
                continue

            rec = {"form_name": current_form or "", "field_name": qlabel, "page": page_num}
            key = (rec["page"], rec["form_name"], rec["field_name"])
            if key not in seen:
                seen.add(key)
                out.append(rec)

            for idx in g:
                option_group_handled.add(idx)

        for i in code_idxs:
            if i in option_group_handled:
                continue

            label = _label_near_code(lines, i, title_size)
            if not label:
                continue

            rec = {"form_name": current_form or "", "field_name": label, "page": page_num}
            key = (rec["page"], rec["form_name"], rec["field_name"])
            if key not in seen:
                seen.add(key)
                out.append(rec)

        if not toc_like:
            for h in _detect_table_headers(lines, title_size):
                rec = {"form_name": current_form or "", "field_name": h, "page": page_num}
                key = (rec["page"], rec["form_name"], rec["field_name"])
                if key not in seen:
                    seen.add(key)
                    out.append(rec)

    return out
```
