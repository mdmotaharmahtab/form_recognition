```python
import re
from typing import List, Dict, Tuple, Optional


_WS_RE = re.compile(r"\s+")
_ENUM_PREFIX_RE = re.compile(r"^\(\s*\d+\s*\)|^\d+[\)\.]\s")
_BRACKET_TOKEN_RE = re.compile(r"\[[^\[\]]+\]")
_WORD_NUM_RE = re.compile(r"^[A-Za-z]{2,20}\s+\d{1,4}$")


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def _looks_like_noise_text(t: str) -> bool:
    t = _norm(t)
    if not t:
        return True
    if re.fullmatch(r"[\d\W_]+", t):
        return True
    if len(t) == 1:
        return True
    return False


def _is_bracketed(s: str) -> bool:
    s = (s or "").strip()
    return len(s) >= 2 and s[0] == "[" and s[-1] == "]"


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


def _token_is_codeish(token: str) -> bool:
    inner = (token or "").strip()
    if not inner:
        return False
    if len(inner) < 2 or len(inner) > 48:
        return False
    # allow common code punctuation but keep it bounded
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:\-_/\.]{1,47}", inner):
        return False
    if re.fullmatch(r"\d+", inner):
        return False
    if not re.search(r"[A-Za-z]", inner):
        return False
    return True


def _extract_code_tokens(text: str) -> List[str]:
    t = text or ""
    out = []
    for m in _BRACKET_TOKEN_RE.finditer(t):
        tok = m.group(0)
        inner = tok[1:-1]
        if _token_is_codeish(inner):
            out.append(tok)
    return out


def _strip_code_tokens(text: str) -> str:
    t = text or ""
    # remove only codeish bracket tokens, keep other bracketed text as-is
    def _repl(m):
        tok = m.group(0)
        inner = tok[1:-1]
        return " " if _token_is_codeish(inner) else tok

    t2 = _BRACKET_TOKEN_RE.sub(_repl, t)
    return _norm(t2)


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
        if _looks_like_noise_text(t):
            continue
        cand.append(l)
    if not cand:
        return "", 0.0
    cand.sort(
        key=lambda l: (
            -float(getattr(l, "size", 0.0) or 0.0),
            float(getattr(l, "y0", 0.0) or 0.0),
            float(getattr(l, "x0", 0.0) or 0.0),
        )
    )
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


def _label_candidate(line, title_size: float, ph: float, allow_non_black: bool) -> bool:
    if (not allow_non_black) and getattr(line, "non_black", False):
        return False
    t = _norm(getattr(line, "text", ""))
    if _looks_like_noise_text(t):
        return False
    if _is_bracketed(t):
        return False
    # don't treat pure code-bearing lines as labels
    if _extract_code_tokens(t) and not _strip_code_tokens(t):
        return False
    y0 = float(getattr(line, "y0", 0.0) or 0.0)
    if y0 < ph * 0.025:
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

    if getattr(line, "non_black", False):
        score -= 4.0

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


def _expand_wrapped(lines, start_idx: int, stop_idx_exclusive: int, allow_non_black: bool) -> str:
    base = lines[start_idx]
    base_x = float(getattr(base, "x0", 0.0) or 0.0)
    parts = [_norm(getattr(base, "text", ""))]

    j = start_idx - 1
    prev_y = float(getattr(base, "y0", 0.0) or 0.0)
    while j >= 0:
        l = lines[j]
        if (not allow_non_black) and getattr(l, "non_black", False):
            break
        tt = _norm(getattr(l, "text", ""))
        if not tt or _is_bracketed(tt) or _ENUM_PREFIX_RE.match(tt) or _looks_like_noise_text(tt):
            break
        if _extract_code_tokens(tt) and not _strip_code_tokens(tt):
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
        if (not allow_non_black) and getattr(l, "non_black", False):
            break
        tt = _norm(getattr(l, "text", ""))
        if not tt or _is_bracketed(tt) or _ENUM_PREFIX_RE.match(tt) or _looks_like_noise_text(tt):
            break
        if _extract_code_tokens(tt) and not _strip_code_tokens(tt):
            break
        if abs(float(getattr(l, "x0", 0.0) or 0.0) - base_x) > 52.0:
            break
        if (float(getattr(l, "y0", 0.0) or 0.0) - prev_y) > 20.0:
            break
        parts.append(tt)
        prev_y = float(getattr(l, "y0", 0.0) or 0.0)
        k += 1

    return _norm(" ".join(parts))


def _inline_neighbor_label(lines, code_idx: int, title_size: float, ph: float, allow_non_black: bool) -> str:
    code = lines[code_idx]
    y = float(getattr(code, "y0", 0.0) or 0.0)
    x0c = float(getattr(code, "x0", 0.0) or 0.0)
    x1c = float(getattr(code, "x1", x0c) or x0c)

    best = None  # (score, idx)
    for i, l in enumerate(lines):
        if i == code_idx:
            continue
        if not _label_candidate(l, title_size, ph, allow_non_black=allow_non_black):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if abs(y0 - y) > 10.0:
            continue

        lx0 = float(getattr(l, "x0", 0.0) or 0.0)
        lx1 = float(getattr(l, "x1", lx0) or lx0)
        if lx1 <= x0c - 4.0:
            dist = x0c - lx1
            sc = 50.0 - min(50.0, dist / 3.0)
            if getattr(l, "bold", False):
                sc += 4.0
            if getattr(l, "non_black", False):
                sc -= 3.0
            if best is None or sc > best[0]:
                best = (sc, i)
        elif lx0 >= x1c + 4.0:
            dist = lx0 - x1c
            sc = 44.0 - min(44.0, dist / 3.0)
            if getattr(l, "bold", False):
                sc += 3.0
            if getattr(l, "non_black", False):
                sc -= 3.0
            if best is None or sc > best[0]:
                best = (sc, i)

    if best is None:
        return ""
    label = _expand_wrapped(lines, best[1], len(lines), allow_non_black=allow_non_black)
    if not label or _looks_like_noise_text(label) or _ENUM_PREFIX_RE.match(label):
        return ""
    return label


def _nearby_label_above_below(lines, code_idx: int, title_size: float, ph: float, allow_non_black: bool) -> str:
    code_line = lines[code_idx]
    pw = _page_width(lines)

    best_j = None
    best_score = None

    cy = float(getattr(code_line, "y0", 0.0) or 0.0)
    for j in range(code_idx - 1, -1, -1):
        l = lines[j]
        dy = cy - float(getattr(l, "y0", 0.0) or 0.0)
        if dy > 180.0:
            break
        if not _label_candidate(l, title_size, ph, allow_non_black=allow_non_black):
            continue
        sc = _score_label(l, code_line, pw, prefer_left=True)
        if best_score is None or sc > best_score:
            best_score = sc
            best_j = j

    if best_j is not None:
        label = _expand_wrapped(lines, best_j, code_idx, allow_non_black=allow_non_black)
        if label and not _looks_like_noise_text(label) and not _ENUM_PREFIX_RE.match(label):
            return label

    best_j = None
    best_score = None
    for j in range(code_idx + 1, min(len(lines), code_idx + 55)):
        l = lines[j]
        dy = float(getattr(l, "y0", 0.0) or 0.0) - cy
        if dy <= 0:
            continue
        if dy > 95.0:
            break
        if not _label_candidate(l, title_size, ph, allow_non_black=allow_non_black):
            continue
        lx0 = float(getattr(l, "x0", 0.0) or 0.0)
        if abs(lx0 - float(getattr(code_line, "x0", 0.0) or 0.0)) > 85.0 and lx0 > pw * 0.55:
            continue
        sc = 20.0 - dy
        if lx0 <= pw * 0.40:
            sc += 8.0
        if getattr(l, "bold", False):
            sc += 5.0
        if getattr(l, "non_black", False):
            sc -= 3.0
        L = len(_norm(getattr(l, "text", "")))
        sc += 4.0 if L <= 90 else -2.0
        if best_score is None or sc > best_score:
            best_score = sc
            best_j = j

    if best_j is not None:
        label = _expand_wrapped(lines, best_j, len(lines), allow_non_black=allow_non_black)
        if label and not _looks_like_noise_text(label) and not _ENUM_PREFIX_RE.match(label):
            return label

    return ""


def _label_near_code(lines, code_idx: int, title_size: float) -> str:
    ph = _page_height(lines)

    label = _inline_neighbor_label(lines, code_idx, title_size, ph, allow_non_black=True)
    if label:
        return label

    label = _nearby_label_above_below(lines, code_idx, title_size, ph, allow_non_black=True)
    if label:
        return label

    return ""


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
        if dy > 220.0:
            break
        if not _label_candidate(l, title_size, ph, allow_non_black=False):
            continue

        t0 = _norm(getattr(l, "text", ""))
        if len(t0) < 10:
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if x0 > pw * 0.62:
            continue

        sc = 0.0
        sc += 60.0 - min(60.0, dy / 2.8)
        sc += 10.0 if x0 <= pw * 0.42 else 2.0
        sc -= min(12.0, abs(x0 - (pw * 0.10)) / 20.0)
        sc -= min(8.0, abs(x0 - opt_x) / 30.0)
        if getattr(l, "bold", False):
            sc += 8.0
        if "?" in t0:
            sc += 5.0

        if best is None or sc > best[0]:
            best = (sc, j)

    if best is None:
        return ""

    label = _expand_wrapped(lines, best[1], min_i, allow_non_black=False)
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


def _row_marker_buckets(lines) -> set:
    pw = _page_width(lines)
    ph = _page_height(lines)

    black_sizes = [
        float(getattr(l, "size", 0.0) or 0.0)
        for l in lines
        if not getattr(l, "non_black", False)
    ]
    body_med = _median(black_sizes) or 7.0

    buckets: Dict[int, List[str]] = {}
    for l in lines:
        if float(getattr(l, "y0", 0.0) or 0.0) < ph * 0.12:
            continue
        if float(getattr(l, "x0", 0.0) or 0.0) > pw * 0.28:
            continue
        if getattr(l, "non_black", False):
            continue
        t = _norm(getattr(l, "text", ""))
        if not t or _looks_like_noise_text(t) or _ENUM_PREFIX_RE.match(t) or _is_bracketed(t):
            continue
        if not _WORD_NUM_RE.fullmatch(t):
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if not (body_med * 0.85 <= sz <= body_med * 1.25):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        b = int(round(x0 / 25.0))
        buckets.setdefault(b, []).append(t)

    out = set()
    for b, vals in buckets.items():
        if len(vals) < 5:
            continue
        nums = set()
        for v in vals:
            m = re.search(r"(\d{1,4})$", v)
            if m:
                nums.add(m.group(1))
        if len(nums) >= 4:
            out.add(b)
    return out


def _label_is_row_marker(label: str, x0: float, row_buckets: set) -> bool:
    if not label:
        return False
    if not _WORD_NUM_RE.fullmatch(label):
        return False
    b = int(round((x0 or 0.0) / 25.0))
    return b in row_buckets


def _is_option_like_label(lines, label_idx: int, pw: float) -> bool:
    l = lines[label_idx]
    t = _norm(getattr(l, "text", ""))
    if not t or _looks_like_noise_text(t) or _ENUM_PREFIX_RE.match(t) or _is_bracketed(t):
        return False
    if "?" in t:
        return False
    if t.endswith(":"):
        return False
    if len(t) > 45:
        return False

    x0 = float(getattr(l, "x0", 0.0) or 0.0)
    y0 = float(getattr(l, "y0", 0.0) or 0.0)
    if x0 <= pw * 0.30:
        return False

    # parent label above: longer and more left-aligned
    parent_found = False
    for j in range(label_idx - 1, max(-1, label_idx - 45), -1):
        p = lines[j]
        dy = y0 - float(getattr(p, "y0", 0.0) or 0.0)
        if dy <= 0:
            continue
        if dy > 95.0:
            break
        if getattr(p, "non_black", False):
            continue
        pt = _norm(getattr(p, "text", ""))
        if not pt or _looks_like_noise_text(pt) or _ENUM_PREFIX_RE.match(pt) or _is_bracketed(pt):
            continue
        px0 = float(getattr(p, "x0", 0.0) or 0.0)
        if px0 >= x0 - 18.0:
            continue
        if len(pt) >= 16 or ("?" in pt):
            parent_found = True
            break

    if not parent_found:
        return False

    # siblings nearby with similar indentation
    sib = 0
    for k in range(max(0, label_idx - 18), min(len(lines), label_idx + 18)):
        if k == label_idx:
            continue
        q = lines[k]
        qt = _norm(getattr(q, "text", ""))
        if not qt or _looks_like_noise_text(qt) or _ENUM_PREFIX_RE.match(qt) or _is_bracketed(qt):
            continue
        if "?" in qt or qt.endswith(":") or len(qt) > 45:
            continue
        qx0 = float(getattr(q, "x0", 0.0) or 0.0)
        qy0 = float(getattr(q, "y0", 0.0) or 0.0)
        if abs(qy0 - y0) > 65.0:
            continue
        if abs(qx0 - x0) <= 30.0:
            sib += 1
        if sib >= 1:
            break

    return sib >= 1


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    seen = set()
    current_form = ""

    for page_idx0, lines in pages:
        page_num = int(page_idx0) + 1
        if not lines:
            continue

        pw = _page_width(lines)
        ph = _page_height(lines)
        toc_like = _is_toc_like(lines)

        title, title_size = _detect_form_title_and_size(lines)
        if title and not toc_like:
            current_form = title

        row_buckets = _row_marker_buckets(lines)

        # Build code anchors: bracket-code-only lines and inline code+label lines
        code_only_idxs: List[int] = []
        inline_code_anchors: List[Tuple[int, str]] = []  # (idx, inline_label)
        for i, l in enumerate(lines):
            txt = _norm(getattr(l, "text", ""))
            if not txt:
                continue
            toks = _extract_code_tokens(txt)
            if not toks:
                continue

            # consider only when the line is colored OR mostly looks like a code carrier (small-ish)
            colored = bool(getattr(l, "non_black", False))
            if not colored and len(txt) > 80:
                continue

            stripped = _strip_code_tokens(txt)
            if stripped:
                # inline label candidate
                if not _looks_like_noise_text(stripped) and not _is_bracketed(stripped) and not _ENUM_PREFIX_RE.match(stripped):
                    inline_code_anchors.append((i, stripped))
            else:
                # bracket-only
                if colored:
                    code_only_idxs.append(i)

        # Helper to fetch an option-label for a code-only anchor
        label_cache: Dict[int, str] = {}
        def _label_for_anchor_idx(idx: int) -> str:
            if idx in label_cache:
                return label_cache[idx]
            lb = _label_near_code(lines, idx, title_size)
            label_cache[idx] = lb
            return lb

        # Cluster anchors into potential option groups (connected components by proximity)
        # Represent anchors as points: (kind, idx, x0, y0)
        anchors = []
        for idx in code_only_idxs:
            l = lines[idx]
            anchors.append(("code", idx, float(getattr(l, "x0", 0.0) or 0.0), float(getattr(l, "y0", 0.0) or 0.0)))
        for idx, _lb in inline_code_anchors:
            l = lines[idx]
            anchors.append(("inline", idx, float(getattr(l, "x0", 0.0) or 0.0), float(getattr(l, "y0", 0.0) or 0.0)))

        anchors.sort(key=lambda a: (a[3], a[2], a[1]))
        parent = {a[1]: a[1] for a in anchors}

        def _find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(a, b):
            ra, rb = _find(a), _find(b)
            if ra != rb:
                parent[rb] = ra

        # sliding window by y
        for ii in range(len(anchors)):
            kind_i, idx_i, x_i, y_i = anchors[ii]
            for jj in range(ii + 1, len(anchors)):
                kind_j, idx_j, x_j, y_j = anchors[jj]
                dy = y_j - y_i
                if dy > 44.0:
                    break
                dx = abs(x_j - x_i)

                close = False
                if dy <= 30.0 and dx <= 85.0:
                    close = True
                elif dy <= 12.0 and dx <= 460.0:
                    close = True
                elif dy <= 40.0 and x_i >= pw * 0.32 and x_j >= pw * 0.32 and dx <= 260.0:
                    close = True

                if close:
                    _union(idx_i, idx_j)

        comps: Dict[int, List[int]] = {}
        for _kind, idx, _x, _y in anchors:
            comps.setdefault(_find(idx), []).append(idx)

        option_group_handled = set()

        # Decide which components are option groups and extract their question label
        for comp_root, member_idxs in comps.items():
            if len(member_idxs) < 2:
                continue

            member_idxs_sorted = sorted(member_idxs)
            yvals = [float(getattr(lines[i], "y0", 0.0) or 0.0) for i in member_idxs_sorted]
            if (max(yvals) - min(yvals)) > 170.0:
                continue

            opt_labels: List[str] = []
            for mi in member_idxs_sorted:
                # prefer inline label; fallback to nearby label for code-only
                inline_match = None
                for ii, lb in inline_code_anchors:
                    if ii == mi:
                        inline_match = lb
                        break
                if inline_match:
                    opt_labels.append(inline_match)
                else:
                    opt_labels.append(_label_for_anchor_idx(mi) or "")

            nonempty = [x for x in opt_labels if x]
            if len(nonempty) < 2:
                continue

            lens = [len(x) for x in nonempty]
            med_len = _median([float(x) for x in lens]) or 999.0
            has_questiony_parent = False

            qlabel = _find_group_question_label(lines, member_idxs_sorted, title_size)
            if qlabel:
                has_questiony_parent = ("?" in qlabel) or (len(qlabel) >= 16)

            # option-group heuristics:
            # - for >=3, allow non-question parent; for ==2, require a question-like parent
            if len(member_idxs_sorted) >= 3:
                if med_len > 35.0:
                    continue
            else:
                if not (qlabel and ("?" in qlabel)):
                    continue
                if med_len > 22.0:
                    continue

            # ensure the member labels look like options (not standalone field labels)
            optish = 0
            for x in nonempty:
                if ("?" not in x) and (not x.endswith(":")) and (len(x) <= 45):
                    optish += 1
            if optish / max(1, len(nonempty)) < 0.7:
                continue

            if not qlabel:
                continue

            rec = {"form_name": current_form or "", "field_name": qlabel, "page": page_num}
            key = (rec["page"], rec["form_name"], rec["field_name"])
            if key not in seen:
                seen.add(key)
                out.append(rec)

            for mi in member_idxs_sorted:
                option_group_handled.add(mi)

        # Emit inline-code fields (unless treated as options group members)
        for idx, inline_label in inline_code_anchors:
            if idx in option_group_handled:
                continue
            l = lines[idx]
            # Inline label is already the non-code portion
            label = _norm(inline_label)
            if not label or _looks_like_noise_text(label) or _ENUM_PREFIX_RE.match(label) or _is_bracketed(label):
                continue

            x0 = float(getattr(l, "x0", 0.0) or 0.0)
            if _label_is_row_marker(label, x0, row_buckets):
                continue

            # If this inline label looks like an option under a parent question, skip it
            if _is_option_like_label(lines, idx, pw):
                continue

            rec = {"form_name": current_form or "", "field_name": label, "page": page_num}
            key = (rec["page"], rec["form_name"], rec["field_name"])
            if key not in seen:
                seen.add(key)
                out.append(rec)

        # Emit code-only anchored fields (unless part of an option group)
        for i in code_only_idxs:
            if i in option_group_handled:
                continue

            label = _label_for_anchor_idx(i)
            if not label:
                continue

            x0 = float(getattr(lines[i], "x0", 0.0) or 0.0)
            if _label_is_row_marker(label, float(getattr(lines[i], "x0", 0.0) or 0.0), row_buckets):
                continue

            # If the label line itself appears to be an option under a parent question, skip
            # (prevents single-option leakage when grouping misses)
            # Find the label's actual line index best-effort: prefer inline neighbor search results; fallback none.
            # Here, approximate by scanning for an exact-text line near the code.
            skip_as_option = False
            cy = float(getattr(lines[i], "y0", 0.0) or 0.0)
            for j in range(max(0, i - 25), min(len(lines), i + 25)):
                if abs(float(getattr(lines[j], "y0", 0.0) or 0.0) - cy) > 95.0:
                    continue
                if _norm(getattr(lines[j], "text", "")) == label:
                    if _is_option_like_label(lines, j, pw):
                        skip_as_option = True
                    break
            if skip_as_option:
                continue

            rec = {"form_name": current_form or "", "field_name": label, "page": page_num}
            key = (rec["page"], rec["form_name"], rec["field_name"])
            if key not in seen:
                seen.add(key)
                out.append(rec)

        # Keep existing header extraction, but avoid TOC-like pages and row-marker headers
        if not toc_like:
            for h in _detect_table_headers(lines, title_size):
                # attempt to filter table row index headers structurally
                hx0 = None
                for l in lines:
                    if _norm(getattr(l, "text", "")) == h:
                        hx0 = float(getattr(l, "x0", 0.0) or 0.0)
                        break
                if hx0 is not None and _label_is_row_marker(h, hx0, row_buckets):
                    continue

                rec = {"form_name": current_form or "", "field_name": h, "page": page_num}
                key = (rec["page"], rec["form_name"], rec["field_name"])
                if key not in seen:
                    seen.add(key)
                    out.append(rec)

    return out
```
