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
    sz = [float(getattr(l, "size", 0.0) or 0.0) for l in lines if getattr(l, "size", None) and not getattr(l, "non_black", False)]
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
    # Use a low quantile so far-left table row labels aren't excluded.
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
    # Allow long questions.
    if "?" in t[-14:]:
        return False
    # Paragraph-ish sentence: lots of words and a terminal period (or near-terminal).
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
    return _norm_text(" ".join(_norm_text(getattr(b, "text", "") or "") for b in block if _norm_text(getattr(b, "text", "") or "")))


def _line_heading_like(l, med_sz_all, med_sz_black):
    if getattr(l, "non_black", False):
        return True
    sz = float(getattr(l, "size", 0.0) or 0.0)
    if med_sz_all and sz >= med_sz_all + 3.3:
        return True
    if med_sz_black and sz >= med_sz_black + 3.6:
        return True
    return False


def _detect_form_title(lines, var_codes, prev_form):
    """
    Prefer a top non-black title (typical eCRF section title).
    Fallback to a clearly title-sized black heading when present.
    """
    if not lines:
        return prev_form

    _, med_all, _ = _page_sizes(lines)
    _, med_black, _ = _page_sizes_black(lines)
    min_code_y = None
    if var_codes:
        min_code_y = min(float(getattr(vc["line"], "y0", 0.0) or 0.0) for vc in var_codes)

    # --- Non-black title candidates ---
    nb = []
    for idx, l in enumerate(lines):
        if not getattr(l, "non_black", False):
            continue
        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if y0 > 165 or x0 > 340:
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if sz < max(7.0, med_all + 1.4):
            continue
        if min_code_y is not None and (min_code_y - y0) < 14:
            continue
        nb.append((idx, l, sz, x0, y0, t))

    if nb:
        thr = _percentile([x[2] for x in nb], 0.75)
        cand = [x for x in nb if x[2] >= thr - 0.15]
        cand.sort(key=lambda x: (x[4], x[3]))  # y then x
        return _norm_text(cand[0][5]) or prev_form

    # --- Black title fallback (only if clearly title-ish) ---
    blk = []
    for idx, l in enumerate(lines):
        if getattr(l, "non_black", False):
            continue
        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t):
            continue
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        if y0 > 95 or x0 > 340:
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if sz < max(7.2, med_black + 2.2, med_all + 2.0):
            continue
        if min_code_y is not None and (min_code_y - y0) < 18:
            continue
        if _looks_instruction_like(t):
            continue
        blk.append((idx, l, sz, x0, y0, t))

    if blk:
        blk.sort(key=lambda x: (-x[2], x[4], x[3]))  # largest size, then y, then x
        return _norm_text(blk[0][5]) or prev_form

    return prev_form


def _inline_left_label(lines, code_idx, code_line, left_margin):
    """
    Find black label on same row to the left of the code.
    More permissive on far-left x to capture table row labels (HEENT/Thorax/etc).
    """
    cx = float(getattr(code_line, "x0", 0.0) or 0.0)
    cy = float(getattr(code_line, "y0", 0.0) or 0.0)

    best_idx = None
    best_dx = None

    j0 = max(0, code_idx - 14)
    for j in range(code_idx - 1, j0 - 1, -1):
        l = lines[j]
        if getattr(l, "non_black", False):
            continue
        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t):
            continue
        dy = abs(float(getattr(l, "y0", 0.0) or 0.0) - cy)
        if dy > 5.8:
            continue
        lx = float(getattr(l, "x0", 0.0) or 0.0)
        if lx >= cx - 6:
            continue
        # Allow far-left, but avoid true margin furniture by requiring sane text anyway.
        if lx < max(4.0, left_margin - 120.0):
            continue
        dx = (cx - lx)
        if best_dx is None or dx < best_dx:
            best_dx = dx
            best_idx = j

    if best_idx is None:
        return ""

    x_cap = min(cx - 4, left_margin + 650.0)
    up = _gather_block_up(lines, best_idx, x_cap=x_cap, max_gap=14.5, x_drift=75.0)
    label = _join_block_text(up)
    return label


def _label_from_above_band(lines, code_idx, code_line, left_margin, header_y_cap, med_sz_all, med_sz_black):
    """
    Find a black label above the code in a reasonable x band, avoiding table header rows and headings.
    """
    cx = float(getattr(code_line, "x0", 0.0) or 0.0)
    cy = float(getattr(code_line, "y0", 0.0) or 0.0)

    best_idx = None
    best_score = None

    j = code_idx - 1
    while j >= 0:
        l = lines[j]
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if (cy - y0) > 210:
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
        if lx < left_margin - 120:
            j -= 1
            continue
        if lx > cx + 65:
            j -= 1
            continue

        if _header_row_is_multicol(lines, j):
            j -= 1
            continue
        if _line_heading_like(l, med_sz_all, med_sz_black):
            j -= 1
            continue

        dy = (cy - y0)
        dx = abs(cx - lx)
        score = (-dy, -dx)
        if best_score is None or score > best_score:
            best_score = score
            best_idx = j
        j -= 1

    if best_idx is None:
        return ""

    x_cap = min(cx + 65.0, left_margin + 700.0)
    up = _gather_block_up(lines, best_idx, x_cap=x_cap, max_gap=14.5, x_drift=85.0)
    down = _gather_block_down(
        lines,
        best_idx,
        x_ref=float(getattr(lines[best_idx], "x0", 0.0) or 0.0),
        y_limit=cy - 10,
        x_band=110.0,
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


def _has_black_peer_text_same_row(lines, code_idx, code_line):
    """
    Evidence a code is part of an option line: any black, non-bracket text near same y.
    """
    cx = float(getattr(code_line, "x0", 0.0) or 0.0)
    cy = float(getattr(code_line, "y0", 0.0) or 0.0)
    j0 = max(0, code_idx - 10)
    j1 = min(len(lines) - 1, code_idx + 10)
    for j in range(j0, j1 + 1):
        if j == code_idx:
            continue
        l = lines[j]
        if getattr(l, "non_black", False):
            continue
        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t):
            continue
        if abs(float(getattr(l, "y0", 0.0) or 0.0) - cy) > 5.8:
            continue
        lx = float(getattr(l, "x0", 0.0) or 0.0)
        if abs(lx - cx) > 520:
            continue
        if _looks_instruction_like(t):
            continue
        return True
    return False


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
                # Avoid grouping distant fields: keep runs compact.
                if (max(ys) - min(ys)) <= 240:
                    for rvi in run_:
                        membership[rvi] = gid
                    groups[gid] = {
                        "members": list(run_),
                        "x_key": key,
                        "y_min": min(ys),
                        "y_max": max(ys),
                    }
                    gid += 1

        for vi in idxs_sorted:
            y = float(getattr(var_codes[vi]["line"], "y0", 0.0) or 0.0)
            if prev_y is None:
                run = [vi]
                prev_y = y
                continue
            dy = (y - prev_y)
            if 7.0 <= dy <= 36.0:
                run.append(vi)
            else:
                flush(run)
                run = [vi]
            prev_y = y

        flush(run)

    return membership, groups


def _classify_group(lines, var_codes, group_info, left_margin):
    """
    Decide if a vertical group is:
      - 'row_table': each row has its own left label (e.g., HEENT/Thorax/Abdomen)
      - 'option_list': codes correspond to options/anchors, so we want ONE question label
    """
    members = group_info.get("members") or []
    if not members:
        return "unknown"

    inline = []
    peer_row_text = 0
    for vi in members:
        vc = var_codes[vi]
        idx = int(vc["idx"])
        line = vc["line"]
        if _has_black_peer_text_same_row(lines, idx, line):
            peer_row_text += 1
        lab = _inline_left_label(lines, idx, line, left_margin)
        lab = _norm_text(lab)
        if _label_basic_sane(lab):
            inline.append(lab)

    # Row table: many distinct inline-left labels.
    if inline:
        distinct = len(set(inline))
        if distinct >= max(2, int(0.6 * len(inline))) and (len(inline) / max(1, len(members))) >= 0.55:
            return "row_table"

    # Option list: strong evidence of per-row text near codes.
    if (peer_row_text / max(1, len(members))) >= 0.60:
        return "option_list"

    # Default: if very short run, avoid collapsing unless it looks like options.
    if len(members) <= 2:
        return "row_table"

    return "option_list"


def _group_question_label(lines, var_codes, group_info, left_margin, header_y_cap, med_sz_all, med_sz_black):
    """
    Find a shared question/field label above an option-list group.
    Avoid table header rows and page headings.
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

    best_idx = None
    best_score = None

    j = code_idx - 1
    while j >= 0:
        l = lines[j]
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if (top_y - y0) > 300:
            break
        if getattr(l, "non_black", False):
            j -= 1
            continue
        if y0 < header_y_cap:
            j -= 1
            continue

        # Require a real gap above the options.
        if (top_y - y0) < 14:
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
        if lx < left_margin - 120:
            j -= 1
            continue
        if lx > cx + 95:
            j -= 1
            continue

        if _header_row_is_multicol(lines, j):
            j -= 1
            continue
        if _line_heading_like(l, med_sz_all, med_sz_black):
            j -= 1
            continue

        dy = (top_y - y0)
        dx = abs(cx - lx)
        score = (-dy, -dx)
        if best_score is None or score > best_score:
            best_score = score
            best_idx = j
        j -= 1

    if best_idx is None:
        return ""

    x_cap = min(cx + 95.0, left_margin + 740.0)
    up = _gather_block_up(lines, best_idx, x_cap=x_cap, max_gap=14.5, x_drift=95.0)
    down = _gather_block_down(
        lines,
        best_idx,
        x_ref=float(getattr(lines[best_idx], "x0", 0.0) or 0.0),
        y_limit=top_y - 12,
        x_band=120.0,
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
        header_y_cap = max(42.0, min(92.0, min_code_y - 60.0))

        # Update form title (do NOT use as a field label fallback)
        current_form = _detect_form_title(lines, var_codes, current_form)
        form_name = _norm_text(current_form)

        # Group codes by vertical runs
        membership, groups = _compute_vertical_groups(var_codes, min_len=2)
        group_kind = {}
        for gid, ginfo in groups.items():
            group_kind[gid] = _classify_group(lines, var_codes, ginfo, left_margin)

        # Emit fields, collapsing option-list groups to ONE record
        emitted_option_groups = set()

        for vi, vc in enumerate(var_codes):
            idx = int(vc["idx"])
            code_line = vc["line"]

            gid = membership.get(vi)
            if gid is not None and group_kind.get(gid) == "option_list":
                if gid in emitted_option_groups:
                    continue
                emitted_option_groups.add(gid)

                label = _group_question_label(
                    lines,
                    var_codes,
                    groups[gid],
                    left_margin=left_margin,
                    header_y_cap=header_y_cap,
                    med_sz_all=med_sz_all,
                    med_sz_black=med_sz_black,
                )
                label = _norm_text(label)
                if not _label_basic_sane(label):
                    # Fallback for option groups: try above-band from the first member.
                    top_vi = min(groups[gid]["members"], key=lambda v: float(getattr(var_codes[v]["line"], "y0", 0.0) or 0.0))
                    label = _label_from_above_band(
                        lines,
                        int(var_codes[top_vi]["idx"]),
                        var_codes[top_vi]["line"],
                        left_margin=left_margin,
                        header_y_cap=header_y_cap,
                        med_sz_all=med_sz_all,
                        med_sz_black=med_sz_black,
                    )
                    label = _norm_text(label)
                if not _label_basic_sane(label):
                    continue

                out.append({"form_name": form_name, "field_name": label, "page": int(page_idx0) + 1})
                continue

            # Non-option (including row_table groups): per-code labeling
            label = _inline_left_label(lines, idx, code_line, left_margin)
            label = _norm_text(label)

            if not _label_basic_sane(label):
                label = _label_from_above_band(
                    lines,
                    idx,
                    code_line,
                    left_margin=left_margin,
                    header_y_cap=header_y_cap,
                    med_sz_all=med_sz_all,
                    med_sz_black=med_sz_black,
                )
                label = _norm_text(label)

            if not _label_basic_sane(label):
                continue

            out.append({"form_name": form_name, "field_name": label, "page": int(page_idx0) + 1})

    return out
```
