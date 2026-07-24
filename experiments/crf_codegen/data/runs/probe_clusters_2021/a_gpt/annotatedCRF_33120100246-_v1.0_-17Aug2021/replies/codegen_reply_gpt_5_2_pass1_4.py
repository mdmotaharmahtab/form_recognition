```python
import re
import unicodedata
from statistics import median

_RE_WS = re.compile(r"\s+")
_RE_BRACKETED = re.compile(r"^\[.*\]$")
_RE_VAR_INNER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,}$")
_RE_HAS_ALNUM = re.compile(r"[0-9A-Za-z]")
_RE_ROWLIKE = re.compile(r"^(row)\s*\d+\b", re.IGNORECASE)
_RE_ONLY_PUNCT = re.compile(r"^[^0-9A-Za-z]+$")
_RE_STRIP_NON_ALNUM = re.compile(r"[^0-9A-Za-z]+")
_RE_NUM_PREFIX = re.compile(r"^\(?\d{1,3}[\.\)]\s+\S+")
_RE_BARE_NUMBER_DOT = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\s+\S+")


def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00ad", "")  # soft hyphen
    s = _RE_WS.sub(" ", s).strip()
    return s


def _is_bracketed(text: str) -> bool:
    return bool(text) and text[0] == "[" and text[-1] == "]" and _RE_BRACKETED.match(text) is not None


def _is_type_like_bracket(inner: str) -> bool:
    return (":" in inner) or (" " in inner)


def _is_var_code_text(text: str) -> bool:
    text = _norm_text(text)
    if not _is_bracketed(text):
        return False
    inner = text[1:-1].strip()
    if not inner or _is_type_like_bracket(inner):
        return False
    if not _RE_VAR_INNER.match(inner):
        return False
    return True


def _try_join_broken_bracket(lines, i):
    """
    Join broken bracket tokens across consecutive colored lines, e.g. '[SCANNE' + 'R]' => '[SCANNER]'.
    Only joins when fragments contain no ':' and no spaces to avoid [TYPE: ...] blocks.
    Returns (joined_text, j) where j is last index consumed, or (None, i) if not joinable.
    """
    t0 = _norm_text(getattr(lines[i], "text", "") or "")
    if not t0 or not t0.startswith("[") or t0.endswith("]"):
        return (None, i)
    if ":" in t0 or " " in t0:
        return (None, i)

    x0 = float(getattr(lines[i], "x0", 0.0) or 0.0)
    y0 = float(getattr(lines[i], "y0", 0.0) or 0.0)
    size0 = getattr(lines[i], "size", None)

    parts = [t0]
    j = i
    for _ in range(3):  # allow up to 4-line join
        if j + 1 >= len(lines):
            break
        nxt = lines[j + 1]
        t1 = _norm_text(getattr(nxt, "text", "") or "")
        if not t1:
            break
        if ":" in t1 or " " in t1:
            break
        if not getattr(nxt, "non_black", False):
            break

        x1 = float(getattr(nxt, "x0", 0.0) or 0.0)
        y1 = float(getattr(nxt, "y0", 0.0) or 0.0)
        if abs(x1 - x0) > 7.5:
            break
        if (y1 - y0) > 22:
            break

        size1 = getattr(nxt, "size", None)
        if size0 and size1 and abs(float(size1) - float(size0)) > 1.4:
            break

        parts.append(t1)
        j += 1
        y0 = y1
        joined = _norm_text("".join(parts))
        if joined.endswith("]") and joined.startswith("["):
            return (joined, j)

    return (None, i)


def _percentile(vals, q):
    if not vals:
        return 0.0
    xs = sorted(float(v) for v in vals)
    if q <= 0:
        return xs[0]
    if q >= 1:
        return xs[-1]
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(len(xs) - 1, lo + 1)
    frac = pos - lo
    return xs[lo] * (1 - frac) + xs[hi] * frac


def _page_sizes(lines):
    sz = [float(getattr(l, "size", 0.0) or 0.0) for l in lines if getattr(l, "size", None)]
    if not sz:
        return (0.0, 0.0, 0.0)
    sz_sorted = sorted(sz)
    return (sz_sorted[0], median(sz_sorted), sz_sorted[-1])


def _page_sizes_black(lines):
    sz = [
        float(getattr(l, "size", 0.0) or 0.0)
        for l in lines
        if getattr(l, "size", None) and not getattr(l, "non_black", False)
    ]
    if not sz:
        return (0.0, 0.0, 0.0)
    sz_sorted = sorted(sz)
    return (sz_sorted[0], median(sz_sorted), sz_sorted[-1])


def _compute_left_margin(lines):
    xs = []
    for l in lines:
        if getattr(l, "non_black", False):
            continue
        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if x0 <= 2 or x0 > 360:
            continue
        xs.append(x0)
    if not xs:
        return 50.0
    return _percentile(xs, 0.05)


def _collect_var_codes(lines):
    """
    Returns list of dicts: {"idx": int, "line": Line, "code_text": str}
    Uses both direct bracketed codes and joined broken ones.
    """
    out = []
    i = 0
    while i < len(lines):
        l = lines[i]
        t = _norm_text(getattr(l, "text", "") or "")
        if not t:
            i += 1
            continue

        joined, j = (None, i)
        if getattr(l, "non_black", False) and t.startswith("[") and not t.endswith("]") and ":" not in t and " " not in t:
            joined, j = _try_join_broken_bracket(lines, i)

        if joined is not None and _is_var_code_text(joined):
            out.append({"idx": i, "line": l, "code_text": joined})
            i = j + 1
            continue

        if getattr(l, "non_black", False) and _is_var_code_text(t):
            out.append({"idx": i, "line": l, "code_text": t})
        i += 1
    return out


def _is_rowlike_label(label: str) -> bool:
    t = _norm_text(label)
    if not t:
        return False
    return _RE_ROWLIKE.match(t) is not None


def _looks_instruction_like(label: str) -> bool:
    t = _norm_text(label)
    if not t:
        return False
    if "?" in t[-14:]:
        return False
    if len(t) >= 110 and t.count(" ") >= 14:
        tail = t[-18:]
        if "." in tail:
            return True
    return False


def _label_basic_sane(label: str) -> bool:
    label = _norm_text(label)
    if not label:
        return False
    if _RE_ONLY_PUNCT.match(label or ""):
        return False
    if not _RE_HAS_ALNUM.search(label):
        return False
    if _is_bracketed(label):
        return False
    if _is_rowlike_label(label):
        return False
    if _looks_instruction_like(label):
        return False
    alnum = _RE_STRIP_NON_ALNUM.sub("", label)
    if len(alnum) <= 1:
        return False
    return True


def _label_is_too_optionish(label: str) -> bool:
    """
    Structural-ish filter for very short, non-question fragments that are often answer options.
    Do NOT blocklist words; just shape.
    """
    t = _norm_text(label)
    if not t:
        return True
    if "?" in t:
        return False
    # Very short, few words, no punctuation signal.
    if len(t) <= 18 and t.count(" ") <= 2 and ":" not in t and ";" not in t and "," not in t:
        return True
    return False


def _header_row_is_multicol(lines, header_idx):
    """
    If the chosen header sits on a row with multiple similarly-styled headers across columns,
    treat it as a table header row (often not a per-field label).
    """
    h = lines[header_idx]
    if getattr(h, "non_black", False):
        return False
    hy = float(getattr(h, "y0", 0.0) or 0.0)
    hs = float(getattr(h, "size", 0.0) or 0.0)
    hx = float(getattr(h, "x0", 0.0) or 0.0)

    peers = 0
    for k, l in enumerate(lines):
        if k == header_idx:
            continue
        if getattr(l, "non_black", False):
            continue
        if abs(float(getattr(l, "y0", 0.0) or 0.0) - hy) > 3.5:
            continue
        ls = float(getattr(l, "size", 0.0) or 0.0)
        if hs and ls and abs(ls - hs) > 1.2:
            continue
        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t):
            continue
        if abs(float(getattr(l, "x0", 0.0) or 0.0) - hx) > 85:
            peers += 1
            if peers >= 2:
                return True
    return False


def _has_code_below_near(var_codes, hx, hy, max_dy=55.0, x_band=120.0):
    for vc in var_codes:
        l = vc["line"]
        cy = float(getattr(l, "y0", 0.0) or 0.0)
        if cy <= hy:
            continue
        if (cy - hy) > max_dy:
            continue
        cx = float(getattr(l, "x0", 0.0) or 0.0)
        if abs(cx - hx) <= x_band:
            return True
    return False


def _gather_block_up(lines, start_idx, x_cap, max_gap=14.5, x_drift=70.0):
    if start_idx is None:
        return []
    block = [lines[start_idx]]
    x0_ref = float(getattr(lines[start_idx], "x0", 0.0) or 0.0)
    y_prev = float(getattr(lines[start_idx], "y0", 0.0) or 0.0)

    j = start_idx - 1
    while j >= 0:
        l = lines[j]
        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t) or getattr(l, "non_black", False):
            break
        if float(getattr(l, "x0", 0.0) or 0.0) > x_cap:
            break
        if (y_prev - float(getattr(l, "y0", 0.0) or 0.0)) > max_gap:
            break
        if abs(float(getattr(l, "x0", 0.0) or 0.0) - x0_ref) > x_drift:
            break
        block.append(l)
        y_prev = float(getattr(l, "y0", 0.0) or 0.0)
        x0_ref = (x0_ref * 0.7 + float(getattr(l, "x0", 0.0) or 0.0) * 0.3)
        j -= 1

    block.reverse()
    return block


def _gather_block_down(lines, start_idx, x_ref, y_limit, x_band=90.0, max_gap=14.5):
    block = [lines[start_idx]]
    y_prev = float(getattr(lines[start_idx], "y0", 0.0) or 0.0)
    k = start_idx + 1
    while k < len(lines):
        l = lines[k]
        if float(getattr(l, "y0", 0.0) or 0.0) > y_limit:
            break
        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t) or getattr(l, "non_black", False):
            k += 1
            continue
        if abs(float(getattr(l, "x0", 0.0) or 0.0) - float(x_ref)) > x_band:
            k += 1
            continue
        if (float(getattr(l, "y0", 0.0) or 0.0) - y_prev) > max_gap:
            break
        block.append(l)
        y_prev = float(getattr(l, "y0", 0.0) or 0.0)
        k += 1
    return block


def _join_block_text(block):
    return _norm_text(
        " ".join(
            _norm_text(getattr(b, "text", "") or "")
            for b in block
            if _norm_text(getattr(b, "text", "") or "")
        )
    )


def _line_heading_like(l, med_sz_all, med_sz_black, y0=None, header_y_cap=None):
    """
    Used to avoid pulling page headings as field labels.
    Make this conservative: only treat as heading-like if it's clearly larger.
    """
    if getattr(l, "non_black", False):
        return True
    sz = float(getattr(l, "size", 0.0) or 0.0)
    if y0 is None:
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
    # Extra strict near top.
    top_bias = 0.0
    if header_y_cap is not None and y0 < (header_y_cap + 25.0):
        top_bias = 0.7
    if med_sz_all and sz >= med_sz_all + (4.0 + top_bias):
        return True
    if med_sz_black and sz >= med_sz_black + (4.3 + top_bias):
        return True
    return False


def _detect_form_title(lines, var_codes, prev_form):
    """
    Prefer a top non-black title (typical eCRF section title).
    Fallback to a clearly title-sized black heading when present.
    If multiple candidates exist, prefer the one closest above the first code.
    """
    if not lines:
        return prev_form

    _, med_all, _ = _page_sizes(lines)
    _, med_black, _ = _page_sizes_black(lines)

    min_code_y = None
    if var_codes:
        min_code_y = min(float(getattr(vc["line"], "y0", 0.0) or 0.0) for vc in var_codes)

    def is_plausible_title_text(t):
        if not t or _is_bracketed(t):
            return False
        if _looks_instruction_like(t):
            return False
        # Avoid TOC-like numbering (structural pattern).
        if _RE_BARE_NUMBER_DOT.match(t):
            return False
        # Titles are rarely extremely long.
        if len(t) > 90 and "?" not in t:
            return False
        return True

    cands = []
    for idx, l in enumerate(lines):
        t = _norm_text(getattr(l, "text", "") or "")
        if not is_plausible_title_text(t):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if y0 > 175 or x0 > 420:
            continue

        sz = float(getattr(l, "size", 0.0) or 0.0)
        nb = bool(getattr(l, "non_black", False))

        # Non-black titles can be closer to body size; black titles should be clearly larger.
        if nb:
            if sz < max(7.0, med_all + 0.8):
                continue
        else:
            if sz < max(7.0, med_black + 1.6, med_all + 1.4):
                continue

        # Must be above first code with some separation (avoid per-field labels).
        if min_code_y is not None:
            if y0 >= (min_code_y - 8.0):
                continue
            gap = (min_code_y - y0)
        else:
            gap = 999.0

        # Score: prefer non-black, larger size, and nearer above first code (smaller gap),
        # while not being at extreme top margin.
        top_pen = 0.0
        if y0 < 18.0:
            top_pen = 35.0

        score = 0.0
        score += 60.0 if nb else 0.0
        score += 9.0 * sz
        score += -0.20 * gap
        score += -0.03 * x0
        score += -top_pen

        cands.append((score, idx, t))

    if not cands:
        return prev_form

    cands.sort(key=lambda x: (-x[0], x[1]))
    return _norm_text(cands[0][2]) or prev_form


def _same_row_black_texts(lines, code_line, y_tol=5.8, x_window=620.0):
    """
    Return black, non-bracket texts on same row as code_line, with side info.
    """
    cx = float(getattr(code_line, "x0", 0.0) or 0.0)
    cy = float(getattr(code_line, "y0", 0.0) or 0.0)
    out = []
    for l in lines:
        if getattr(l, "non_black", False):
            continue
        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t):
            continue
        ly = float(getattr(l, "y0", 0.0) or 0.0)
        if abs(ly - cy) > y_tol:
            continue
        lx = float(getattr(l, "x0", 0.0) or 0.0)
        if abs(lx - cx) > x_window:
            continue
        if _looks_instruction_like(t):
            continue
        side = 1 if (lx > cx + 10.0) else (-1 if (lx < cx - 10.0) else 0)
        out.append((l, t, lx, ly, side))
    return out


def _inline_left_label(lines, code_idx, code_line, left_margin, header_y_cap):
    """
    Find black label on same row to the left of the code.
    More permissive for far-left row labels (e.g. HEENT/Thorax/Abdomen),
    but still avoids top header furniture.
    """
    cx = float(getattr(code_line, "x0", 0.0) or 0.0)
    cy = float(getattr(code_line, "y0", 0.0) or 0.0)

    best_idx = None
    best_dx = None

    j0 = max(0, code_idx - 18)
    for j in range(code_idx - 1, j0 - 1, -1):
        l = lines[j]
        if getattr(l, "non_black", False):
            continue
        ly = float(getattr(l, "y0", 0.0) or 0.0)
        if ly < header_y_cap:
            continue

        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t):
            continue

        dy = abs(ly - cy)
        if dy > 5.8:
            continue
        lx = float(getattr(l, "x0", 0.0) or 0.0)
        if lx >= cx - 6:
            continue

        # Default bound (typical field labels).
        min_x_ok = max(4.0, left_margin - 120.0)

        # If it's a short, clean label, allow farther-left (row tables often start near page edge).
        short_ok = _label_basic_sane(t) and (len(t) <= 22) and (t.count(" ") <= 2) and (":" not in t)
        if short_ok:
            min_x_ok = 4.0

        if lx < min_x_ok:
            continue

        dx = (cx - lx)
        if best_dx is None or dx < best_dx:
            best_dx = dx
            best_idx = j

    if best_idx is None:
        return ""

    x_cap = min(cx - 4, left_margin + 650.0)
    up = _gather_block_up(lines, best_idx, x_cap=x_cap, max_gap=14.5, x_drift=80.0)
    return _join_block_text(up)


def _label_from_above_band(lines, var_codes, code_idx, code_line, left_margin, header_y_cap, med_sz_all, med_sz_black):
    """
    Find a black label above the code in a reasonable x band, avoiding table header rows and page headings.
    Allows some bold-ish labels when they clearly feed a code below.
    """
    cx = float(getattr(code_line, "x0", 0.0) or 0.0)
    cy = float(getattr(code_line, "y0", 0.0) or 0.0)

    best_idx = None
    best_score = None

    # Evidence of option text column (to avoid picking anchors).
    peers = _same_row_black_texts(lines, code_line)
    right_xs = [x for (_, _, x, _, side) in peers if side == 1]
    opt_x = _percentile(right_xs, 0.2) if right_xs else None

    j = code_idx - 1
    while j >= 0:
        l = lines[j]
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if (cy - y0) > 240:
            break
        if getattr(l, "non_black", False):
            j -= 1
            continue
        if y0 < header_y_cap:
            j -= 1
            continue

        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t):
            j -= 1
            continue
        if _looks_instruction_like(t):
            j -= 1
            continue

        lx = float(getattr(l, "x0", 0.0) or 0.0)
        if lx < left_margin - 135:
            j -= 1
            continue
        if lx > cx + 85:
            j -= 1
            continue

        # If it looks like a multi-column header, normally skip, unless a code sits directly below.
        if _header_row_is_multicol(lines, j):
            if not _has_code_below_near(var_codes, lx, y0, max_dy=55.0, x_band=120.0):
                j -= 1
                continue

        # Avoid huge headings, except when they're not at the very top and they clearly label a field.
        if _line_heading_like(l, med_sz_all, med_sz_black, y0=y0, header_y_cap=header_y_cap):
            if not _has_code_below_near(var_codes, lx, y0, max_dy=55.0, x_band=120.0):
                j -= 1
                continue

        dy = (cy - y0)
        dx = abs(cx - lx)

        score = -1.0 * dy - 0.02 * dx
        if "?" in t:
            score += 14.0
        if _RE_NUM_PREFIX.match(t):
            score += 10.0
        if opt_x is not None:
            if lx <= (opt_x - 15.0):
                score += 7.5
            if abs(lx - opt_x) <= 22.0 and ("?" not in t) and (len(t) >= 60):
                score -= 18.0

        if best_score is None or score > best_score:
            best_score = score
            best_idx = j

        j -= 1

    if best_idx is None:
        return ""

    x_cap = min(cx + 85.0, left_margin + 720.0)
    up = _gather_block_up(lines, best_idx, x_cap=x_cap, max_gap=14.5, x_drift=90.0)
    down = _gather_block_down(
        lines,
        best_idx,
        x_ref=float(getattr(lines[best_idx], "x0", 0.0) or 0.0),
        y_limit=cy - 10,
        x_band=130.0,
        max_gap=14.5,
    )

    merged = []
    seen = set()
    for l in up + down:
        if id(l) in seen:
            continue
        seen.add(id(l))
        merged.append(l)

    return _join_block_text(merged)


def _compute_vertical_groups(var_codes, min_len=2):
    """
    Identify vertical repeating code runs by x-band + consistent y gaps.
    Returns:
      membership: var_code_index -> group_id
      groups: group_id -> info
    """
    if not var_codes:
        return {}, {}

    buckets = {}
    for vi, vc in enumerate(var_codes):
        x = float(getattr(vc["line"], "x0", 0.0) or 0.0)
        key = int(round(x / 10.0))  # tolerant binning
        buckets.setdefault(key, []).append(vi)

    membership = {}
    groups = {}
    gid = 0

    for key, idxs in buckets.items():
        idxs_sorted = sorted(idxs, key=lambda i: float(getattr(var_codes[i]["line"], "y0", 0.0) or 0.0))
        run = []
        prev_y = None

        def flush(run_):
            nonlocal gid
            if len(run_) >= min_len:
                ys = [float(getattr(var_codes[rvi]["line"], "y0", 0.0) or 0.0) for rvi in run_]
                if (max(ys) - min(ys)) <= 260:
                    for rvi in run_:
                        membership[rvi] = gid
                    groups[gid] = {"members": list(run_), "x_key": key, "y_min": min(ys), "y_max": max(ys)}
                    gid += 1

        for vi in idxs_sorted:
            y = float(getattr(var_codes[vi]["line"], "y0", 0.0) or 0.0)
            if prev_y is None:
                run = [vi]
                prev_y = y
                continue
            dy = (y - prev_y)
            if 7.0 <= dy <= 38.0:
                run.append(vi)
            else:
                flush(run)
                run = [vi]
            prev_y = y

        flush(run)

    return membership, groups


def _compute_horizontal_groups(var_codes, y_tol=5.8, min_len=2):
    """
    Detect option-sets laid out across a single row (codes aligned by y, separated by x).
    Returns membership_h: var_code_index -> hgroup_id, and groups_h: hgroup_id -> members.
    """
    if not var_codes:
        return {}, {}

    items = []
    for vi, vc in enumerate(var_codes):
        l = vc["line"]
        y = float(getattr(l, "y0", 0.0) or 0.0)
        x = float(getattr(l, "x0", 0.0) or 0.0)
        items.append((vi, y, x))
    items.sort(key=lambda t: (t[1], t[2]))

    groups = {}
    membership = {}
    gid = 0

    i = 0
    while i < len(items):
        vi0, y0, _ = items[i]
        members = [vi0]
        j = i + 1
        while j < len(items):
            vij, yj, xj = items[j]
            if abs(yj - y0) <= y_tol:
                members.append(vij)
                j += 1
                continue
            break

        if len(members) >= min_len:
            xs = sorted(float(getattr(var_codes[v]["line"], "x0", 0.0) or 0.0) for v in members)
            # Require that they are genuinely across columns.
            if (xs[-1] - xs[0]) >= 60.0:
                groups[gid] = {"members": list(members), "y_ref": y0, "x_min": xs[0], "x_max": xs[-1]}
                for v in members:
                    membership[v] = gid
                gid += 1

        i = j

    return membership, groups


def _classify_group(lines, var_codes, group_info, left_margin, header_y_cap):
    """
    Decide if a vertical group is:
      - 'row_table': each row has its own left label (e.g., HEENT/Thorax/Abdomen)
      - 'option_list': codes correspond to options/anchors, so we want ONE question label
    Uses geometric evidence (peer text side) rather than literal strings.
    """
    members = group_info.get("members") or []
    if not members:
        return "unknown"

    left_labels = []
    right_peer_rows = 0
    left_peer_rows = 0
    any_peer_rows = 0

    for vi in members:
        vc = var_codes[vi]
        idx = int(vc["idx"])
        line = vc["line"]

        peers = _same_row_black_texts(lines, line)
        if peers:
            any_peer_rows += 1
            if any(side == 1 for (_, _, _, _, side) in peers):
                right_peer_rows += 1
            if any(side == -1 for (_, _, _, _, side) in peers):
                left_peer_rows += 1

        lab = _inline_left_label(lines, idx, line, left_margin, header_y_cap)
        lab = _norm_text(lab)
        if _label_basic_sane(lab):
            left_labels.append(lab)

    n = max(1, len(members))
    right_ratio = right_peer_rows / n
    left_ratio = left_peer_rows / n

    # Strong signal: option lists tend to have descriptive text to the right of the code.
    if right_ratio >= 0.45 and right_ratio >= (left_ratio + 0.15):
        return "option_list"

    # Row tables: many distinct per-row labels to the left of code column.
    if left_labels:
        distinct = len(set(left_labels))
        if distinct >= max(2, int(0.6 * len(left_labels))) and (len(left_labels) / n) >= 0.55:
            return "row_table"

    # Short runs: if there's still right-side text evidence, treat as options to avoid emitting anchors.
    if len(members) <= 2 and right_ratio >= 0.35:
        return "option_list"

    # Default.
    return "row_table"


def _group_question_label(lines, var_codes, group_info, left_margin, header_y_cap, med_sz_all, med_sz_black):
    """
    Find a shared question/field label above an option-list group.
    Prefer text left of the option-description column and question-like punctuation/numbering.
    """
    members = group_info.get("members") or []
    if not members:
        return ""

    # Topmost member by y.
    top_vi = min(members, key=lambda vi: float(getattr(var_codes[vi]["line"], "y0", 0.0) or 0.0))
    code_idx = int(var_codes[top_vi]["idx"])
    code_line = var_codes[top_vi]["line"]
    cx = float(getattr(code_line, "x0", 0.0) or 0.0)
    top_y = float(getattr(code_line, "y0", 0.0) or 0.0)

    # Estimate option-text column x (right-side peers near the options).
    opt_xs = []
    for vi in members:
        peers = _same_row_black_texts(lines, var_codes[vi]["line"])
        for (_, t, lx, _, side) in peers:
            if side == 1 and _label_basic_sane(t):
                opt_xs.append(lx)
    opt_x = _percentile(opt_xs, 0.25) if opt_xs else None

    best_idx = None
    best_score = None

    j = code_idx - 1
    while j >= 0:
        l = lines[j]
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if (top_y - y0) > 440:
            break
        if getattr(l, "non_black", False):
            j -= 1
            continue
        if y0 < header_y_cap:
            j -= 1
            continue

        # Require a real gap above the options.
        if (top_y - y0) < 12:
            j -= 1
            continue

        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t):
            j -= 1
            continue
        if _looks_instruction_like(t):
            j -= 1
            continue

        lx = float(getattr(l, "x0", 0.0) or 0.0)
        if lx < left_margin - 140:
            j -= 1
            continue
        if lx > cx + 110:
            j -= 1
            continue

        # Avoid multi-column header rows unless there's a code right below.
        if _header_row_is_multicol(lines, j):
            if not _has_code_below_near(var_codes, lx, y0, max_dy=60.0, x_band=120.0):
                j -= 1
                continue

        # Avoid huge headings near top, but allow bold-ish question labels in-body.
        if _line_heading_like(l, med_sz_all, med_sz_black, y0=y0, header_y_cap=header_y_cap):
            if not _has_code_below_near(var_codes, lx, y0, max_dy=60.0, x_band=130.0):
                j -= 1
                continue

        dy = (top_y - y0)
        dx = abs(cx - lx)

        score = -1.0 * dy - 0.02 * dx

        if "?" in t:
            score += 18.0
        if _RE_NUM_PREFIX.match(t):
            score += 12.0
        if t.endswith(":"):
            score += 4.0

        if opt_x is not None:
            if lx <= (opt_x - 15.0):
                score += 9.0
            if abs(lx - opt_x) <= 22.0 and ("?" not in t) and (not _RE_NUM_PREFIX.match(t)) and (len(t) >= 55):
                score -= 28.0

        if best_score is None or score > best_score:
            best_score = score
            best_idx = j

        j -= 1

    if best_idx is None:
        return ""

    x_cap = min(cx + 110.0, left_margin + 760.0)
    up = _gather_block_up(lines, best_idx, x_cap=x_cap, max_gap=14.5, x_drift=105.0)
    down = _gather_block_down(
        lines,
        best_idx,
        x_ref=float(getattr(lines[best_idx], "x0", 0.0) or 0.0),
        y_limit=top_y - 12,
        x_band=140.0,
        max_gap=14.5,
    )

    merged = []
    seen = set()
    for l in up + down:
        if id(l) in seen:
            continue
        seen.add(id(l))
        merged.append(l)

    return _join_block_text(merged)


def extract(pages):
    out = []
    current_form = ""

    for page_idx0, lines in pages:
        lines = list(lines or [])
        if not lines:
            continue

        var_codes = _collect_var_codes(lines)
        if not var_codes:
            continue

        # Page stats / bands
        _, med_sz_all, _ = _page_sizes(lines)
        _, med_sz_black, _ = _page_sizes_black(lines)
        left_margin = _compute_left_margin(lines)

        min_code_y = min(float(getattr(vc["line"], "y0", 0.0) or 0.0) for vc in var_codes)
        header_y_cap = max(42.0, min(100.0, min_code_y - 60.0))

        # Update form title (do NOT use as a field label fallback)
        current_form = _detect_form_title(lines, var_codes, current_form)
        form_name = _norm_text(current_form)

        # Group codes by vertical runs
        membership_v, groups_v = _compute_vertical_groups(var_codes, min_len=2)
        group_kind_v = {}
        for gid, ginfo in groups_v.items():
            group_kind_v[gid] = _classify_group(lines, var_codes, ginfo, left_margin, header_y_cap)

        # Group codes by horizontal rows (options across columns)
        membership_h, groups_h = _compute_horizontal_groups(var_codes, y_tol=5.8, min_len=2)

        emitted_v_option_groups = set()
        emitted_h_groups = set()

        for vi, vc in enumerate(var_codes):
            idx = int(vc["idx"])
            code_line = vc["line"]

            # Horizontal option-set collapse (e.g., multiple choices laid out across the row)
            hgid = membership_h.get(vi)
            if hgid is not None:
                if hgid in emitted_h_groups:
                    continue
                emitted_h_groups.add(hgid)

                # Prefer inline-left label from leftmost code; else fall back to above-band.
                members = groups_h[hgid]["members"]
                leftmost_vi = min(members, key=lambda v: float(getattr(var_codes[v]["line"], "x0", 0.0) or 0.0))
                li = int(var_codes[leftmost_vi]["idx"])
                ll = var_codes[leftmost_vi]["line"]

                label = _inline_left_label(lines, li, ll, left_margin, header_y_cap)
                label = _norm_text(label)
                if not _label_basic_sane(label) or _label_is_too_optionish(label):
                    label = _label_from_above_band(
                        lines,
                        var_codes,
                        li,
                        ll,
                        left_margin=left_margin,
                        header_y_cap=header_y_cap,
                        med_sz_all=med_sz_all,
                        med_sz_black=med_sz_black,
                    )
                    label = _norm_text(label)

                if not _label_basic_sane(label) or _label_is_too_optionish(label):
                    # Last resort: treat like option group and find question above the row.
                    label = _group_question_label(
                        lines,
                        var_codes,
                        {"members": members},
                        left_margin=left_margin,
                        header_y_cap=header_y_cap,
                        med_sz_all=med_sz_all,
                        med_sz_black=med_sz_black,
                    )
                    label = _norm_text(label)

                if not _label_basic_sane(label) or _label_is_too_optionish(label):
                    continue

                out.append({"form_name": form_name, "field_name": label, "page": int(page_idx0) + 1})
                continue

            # Vertical option-list collapse
            vgid = membership_v.get(vi)
            if vgid is not None and group_kind_v.get(vgid) == "option_list":
                if vgid in emitted_v_option_groups:
                    continue
                emitted_v_option_groups.add(vgid)

                label = _group_question_label(
                    lines,
                    var_codes,
                    groups_v[vgid],
                    left_margin=left_margin,
                    header_y_cap=header_y_cap,
                    med_sz_all=med_sz_all,
                    med_sz_black=med_sz_black,
                )
                label = _norm_text(label)

                if not _label_basic_sane(label) or _label_is_too_optionish(label):
                    # Fallback: above-band from topmost member.
                    top_vi = min(
                        groups_v[vgid]["members"],
                        key=lambda v: float(getattr(var_codes[v]["line"], "y0", 0.0) or 0.0),
                    )
                    label = _label_from_above_band(
                        lines,
                        var_codes,
                        int(var_codes[top_vi]["idx"]),
                        var_codes[top_vi]["line"],
                        left_margin=left_margin,
                        header_y_cap=header_y_cap,
                        med_sz_all=med_sz_all,
                        med_sz_black=med_sz_black,
                    )
                    label = _norm_text(label)

                if not _label_basic_sane(label) or _label_is_too_optionish(label):
                    continue

                out.append({"form_name": form_name, "field_name": label, "page": int(page_idx0) + 1})
                continue

            # Non-option: per-code labeling (including row-table groups)
            label = _inline_left_label(lines, idx, code_line, left_margin, header_y_cap)
            label = _norm_text(label)

            if not _label_basic_sane(label) or _label_is_too_optionish(label):
                label = _label_from_above_band(
                    lines,
                    var_codes,
                    idx,
                    code_line,
                    left_margin=left_margin,
                    header_y_cap=header_y_cap,
                    med_sz_all=med_sz_all,
                    med_sz_black=med_sz_black,
                )
                label = _norm_text(label)

            # Final sanity: avoid emitting obvious option-ish short fragments.
            if not _label_basic_sane(label) or _label_is_too_optionish(label):
                continue

            out.append({"form_name": form_name, "field_name": label, "page": int(page_idx0) + 1})

    return out
```
