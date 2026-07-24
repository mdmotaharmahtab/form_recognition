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

def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00ad", "")  # soft hyphen
    s = _RE_WS.sub(" ", s).strip()
    return s

def _is_bracketed(text: str) -> bool:
    return bool(text) and text[0] == "[" and text[-1] == "]" and _RE_BRACKETED.match(text) is not None

def _is_type_like_bracket(inner: str) -> bool:
    # Exclude technical annotations inside brackets without literal word blocklists.
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
    t0 = _norm_text(lines[i].text)
    if not t0 or not t0.startswith("[") or t0.endswith("]"):
        return (None, i)
    if ":" in t0 or " " in t0:
        return (None, i)

    x0 = lines[i].x0
    size0 = getattr(lines[i], "size", None)

    parts = [t0]
    j = i
    for _ in range(2):  # allow up to 3-line join
        if j + 1 >= len(lines):
            break
        nxt = lines[j + 1]
        t1 = _norm_text(nxt.text)
        if not t1:
            break
        if ":" in t1 or " " in t1:
            break
        if not nxt.non_black:
            break
        if abs(nxt.x0 - x0) > 6:
            break
        if (nxt.y0 - lines[j].y0) > 18:
            break
        size1 = getattr(nxt, "size", None)
        if size0 and size1 and abs(size1 - size0) > 1.2:
            break

        parts.append(t1)
        j += 1
        joined = _norm_text("".join(parts))
        if joined.endswith("]") and joined.startswith("["):
            return (joined, j)

    return (None, i)

def _page_sizes(lines):
    sz = [float(l.size) for l in lines if getattr(l, "size", None)]
    if not sz:
        return (0.0, 0.0, 0.0)
    sz_sorted = sorted(sz)
    return (sz_sorted[0], median(sz_sorted), sz_sorted[-1])

def _compute_left_margin(lines):
    xs = []
    for l in lines:
        t = _norm_text(getattr(l, "text", "") or "")
        if not t or _is_bracketed(t):
            continue
        if l.non_black:
            continue
        if l.x0 > 300:
            continue
        xs.append(float(l.x0))
    if not xs:
        return 50.0
    xs.sort()
    k = max(0, min(len(xs) - 1, len(xs) // 10))
    return xs[k]

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
        if l.non_black and t.startswith("[") and not t.endswith("]") and ":" not in t and " " not in t:
            joined, j = _try_join_broken_bracket(lines, i)

        if joined is not None and _is_var_code_text(joined):
            out.append({"idx": i, "line": l, "code_text": joined})
            i = j + 1
            continue

        if l.non_black and _is_var_code_text(t):
            out.append({"idx": i, "line": l, "code_text": t})
        i += 1
    return out

def _detect_form_title(lines, var_codes, prev_form):
    """
    Prefer large non-black title near top-left.
    Else allow small black heading near top-left only if no variable code appears nearby below it.
    """
    if not lines:
        return prev_form

    min_sz, med_sz, max_sz = _page_sizes(lines)

    best = None
    for l in lines:
        t = _norm_text(l.text)
        if not t or _is_bracketed(t):
            continue
        if l.y0 > 140 or l.x0 > 220:
            continue
        if not l.non_black:
            continue
        if l.size < (max_sz - 1.5):
            continue
        if l.x0 > 300:
            continue
        if best is None or (l.y0 < best.y0) or (abs(l.y0 - best.y0) <= 2 and l.x0 < best.x0):
            best = l
    if best is not None:
        return _norm_text(best.text) or prev_form

    cand = None
    for l in lines:
        t = _norm_text(l.text)
        if not t or _is_bracketed(t):
            continue
        if l.non_black:
            continue
        if l.y0 > 90 or l.x0 > 140:
            continue
        if l.size < 6.0 or l.x0 > 250:
            continue
        cand = l
        break

    if cand is None:
        return prev_form

    cy = cand.y0
    for vc in var_codes:
        if vc["line"].y0 < cy + 200:
            return prev_form

    return _norm_text(cand.text) or prev_form

def _gather_label_block_up(lines, start_idx, x_cap, max_gap=14.5, x_drift=55.0):
    if start_idx is None:
        return []
    block = [lines[start_idx]]
    x0_ref = float(lines[start_idx].x0)
    y_prev = float(lines[start_idx].y0)

    j = start_idx - 1
    while j >= 0:
        l = lines[j]
        t = _norm_text(l.text)
        if not t or _is_bracketed(t) or l.non_black:
            break
        if l.x0 > x_cap:
            break
        if (y_prev - l.y0) > max_gap:
            break
        if abs(float(l.x0) - x0_ref) > x_drift:
            break
        block.append(l)
        y_prev = float(l.y0)
        x0_ref = (x0_ref * 0.7 + float(l.x0) * 0.3)
        j -= 1

    block.reverse()
    return block

def _gather_label_block_down(lines, start_idx, x_ref, y_limit, x_band=60.0, max_gap=14.5):
    block = [lines[start_idx]]
    y_prev = float(lines[start_idx].y0)
    k = start_idx + 1
    while k < len(lines):
        l = lines[k]
        if float(l.y0) > y_limit:
            break
        t = _norm_text(l.text)
        if not t or _is_bracketed(t) or l.non_black:
            k += 1
            continue
        if abs(float(l.x0) - float(x_ref)) > x_band:
            k += 1
            continue
        if (float(l.y0) - y_prev) > max_gap:
            break
        block.append(l)
        y_prev = float(l.y0)
        k += 1
    return block

def _join_block_text(block):
    return _norm_text(" ".join(_norm_text(b.text) for b in block if _norm_text(b.text)))

def _is_rowlike_label(label: str) -> bool:
    t = _norm_text(label)
    if not t:
        return False
    return _RE_ROWLIKE.match(t) is not None

def _label_sane(label: str) -> bool:
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
    # avoid ultra-short ambiguous tokens (but keep common short labels like "ID", "AE")
    alnum = re.sub(r"[^0-9A-Za-z]+", "", label)
    if len(alnum) <= 1:
        return False
    return True

def _label_from_inline_left(lines, code_idx, code_line, left_margin):
    """
    Find a black label on the same row to the left of the code (common for tables/timepoint rows).
    """
    cx = float(code_line.x0)
    cy = float(code_line.y0)
    best_idx = None
    best_dx = None

    # search nearby lines for same-row labels
    j0 = max(0, code_idx - 12)
    for j in range(code_idx - 1, j0 - 1, -1):
        l = lines[j]
        if l.non_black:
            continue
        t = _norm_text(l.text)
        if not t or _is_bracketed(t):
            continue
        dy = abs(float(l.y0) - cy)
        if dy > 5.5:
            continue
        lx = float(l.x0)
        if lx >= cx - 6:
            continue
        # ignore far-left margins that are often row indices/structural furniture
        if lx < left_margin - 18:
            continue
        dx = (cx - lx)
        if best_dx is None or dx < best_dx:
            best_dx = dx
            best_idx = j

    if best_idx is None:
        return ""

    # allow wrapped label directly above the chosen line
    x_cap = min(cx - 4, left_margin + 520.0)
    up = _gather_label_block_up(lines, best_idx, x_cap=x_cap, max_gap=14.5, x_drift=65.0)
    label = _join_block_text(up)
    return label

def _label_from_nearby_block(lines, code_idx, code_line, left_margin):
    """
    Flexible: find nearest black label above the code, allowing wider columns and right-shifted layouts.
    Constrains candidates to start left of (or near) the code's x to avoid pulling unrelated right furniture.
    """
    cx = float(code_line.x0)
    cy = float(code_line.y0)

    best_idx = None
    best_score = None

    j = code_idx - 1
    while j >= 0:
        l = lines[j]
        if (cy - float(l.y0)) > 150:
            break
        t = _norm_text(l.text)
        if not t or _is_bracketed(t) or l.non_black:
            j -= 1
            continue

        lx = float(l.x0)
        if lx < left_margin - 18:
            j -= 1
            continue
        # must begin not too far to the right of the code; allow slight overlap slack
        if lx > cx + 30:
            j -= 1
            continue

        dy = (cy - float(l.y0))
        dx = abs(cx - lx)
        # closer vertically is primary; prefer nearer x secondarily
        score = (-dy, -dx)
        if best_score is None or score > best_score:
            best_score = score
            best_idx = j
        j -= 1

    if best_idx is None:
        return ""

    x_cap = min(cx + 30.0, left_margin + 560.0)
    up = _gather_label_block_up(lines, best_idx, x_cap=x_cap, max_gap=14.5, x_drift=70.0)
    label = _join_block_text(up)
    return label

def _label_from_left_context(lines, code_idx, code_line, left_margin):
    """
    Original behavior: nearest black left-ish label above code line.
    """
    cy = float(code_line.y0)
    x_cap = float(left_margin) + 220.0

    best_idx = None
    best_y = -1e9
    j = code_idx - 1
    while j >= 0:
        l = lines[j]
        if (cy - float(l.y0)) > 110:
            break
        t = _norm_text(l.text)
        if not t or _is_bracketed(t):
            j -= 1
            continue
        if l.non_black:
            j -= 1
            continue
        if float(l.x0) > x_cap:
            j -= 1
            continue
        if float(l.y0) > best_y:
            best_y = float(l.y0)
            best_idx = j
        j -= 1

    if best_idx is None:
        return ""

    block = _gather_label_block_up(lines, best_idx, x_cap=x_cap, max_gap=14.5, x_drift=55.0)
    label = _join_block_text(block)
    return label

def _header_row_is_multicol(lines, header_idx):
    """
    If the chosen header sits on a row with multiple similarly-styled headers across columns,
    treat it as a table header row (often not a per-field label).
    """
    h = lines[header_idx]
    hy = float(h.y0)
    hs = float(getattr(h, "size", 0.0) or 0.0)
    hx = float(h.x0)

    peers = 0
    for k, l in enumerate(lines):
        if k == header_idx:
            continue
        if l.non_black:
            continue
        if abs(float(l.y0) - hy) > 3.5:
            continue
        ls = float(getattr(l, "size", 0.0) or 0.0)
        if hs and ls and abs(ls - hs) > 1.2:
            continue
        t = _norm_text(l.text)
        if not t or _is_bracketed(t):
            continue
        if abs(float(l.x0) - hx) > 80:
            peers += 1
            if peers >= 1:
                return True
    return False

def _label_from_same_x_header(lines, code_idx, code_line, med_sz, left_margin):
    """
    Stricter fallback: find a black header above in the same x band with larger font,
    but avoid multi-column header rows (often analyte names / table headings).
    """
    cx = float(code_line.x0)
    cy = float(code_line.y0)

    best_idx = None
    best_score = None

    j = code_idx - 1
    while j >= 0:
        l = lines[j]
        if (cy - float(l.y0)) > 220:
            break
        t = _norm_text(l.text)
        if not t or _is_bracketed(t) or l.non_black:
            j -= 1
            continue
        if abs(float(l.x0) - cx) > 85:
            j -= 1
            continue
        if float(l.x0) < left_margin - 18:
            j -= 1
            continue
        if float(getattr(l, "size", 0.0) or 0.0) < float(med_sz) + 1.0:
            j -= 1
            continue

        score = (-(cy - float(l.y0)), -abs(float(l.x0) - cx), float(getattr(l, "size", 0.0) or 0.0))
        if best_score is None or score > best_score:
            best_score = score
            best_idx = j
        j -= 1

    if best_idx is None:
        return ""

    if _header_row_is_multicol(lines, best_idx):
        return ""

    header_lines = [lines[best_idx]]
    # Allow split header continuation just below
    k = best_idx + 1
    while k < len(lines):
        l = lines[k]
        if float(l.y0) > float(lines[best_idx].y0) + 40:
            break
        t = _norm_text(l.text)
        if not t or _is_bracketed(t) or l.non_black:
            k += 1
            continue
        if abs(float(l.x0) - float(lines[best_idx].x0)) > 85:
            k += 1
            continue
        if abs(float(getattr(l, "size", 0.0) or 0.0) - float(getattr(lines[best_idx], "size", 0.0) or 0.0)) > 1.2:
            k += 1
            continue
        if (float(l.y0) - float(header_lines[-1].y0)) > 16:
            k += 1
            continue
        header_lines.append(l)
        k += 1

    label = _norm_text(" ".join(_norm_text(l.text) for l in header_lines if _norm_text(l.text)))
    return label

def _find_any_nearby_black_label(lines, code_idx, code_line, left_margin):
    """
    Last-chance: find any reasonable black label near (above/left) the code, even if columns are unusual.
    """
    cx = float(code_line.x0)
    cy = float(code_line.y0)

    best_idx = None
    best_score = None

    j = code_idx - 1
    while j >= 0:
        l = lines[j]
        if (cy - float(l.y0)) > 260:
            break
        if l.non_black:
            j -= 1
            continue
        t = _norm_text(l.text)
        if not t or _is_bracketed(t):
            j -= 1
            continue
        if float(l.x0) < left_margin - 18:
            j -= 1
            continue
        if float(l.x0) > cx + 55:
            j -= 1
            continue
        dy = (cy - float(l.y0))
        dx = abs(cx - float(l.x0))
        score = (-dy, -dx)
        if best_score is None or score > best_score:
            best_score = score
            best_idx = j
        j -= 1

    if best_idx is None:
        return ""

    x_cap = min(cx + 55.0, left_margin + 620.0)
    up = _gather_label_block_up(lines, best_idx, x_cap=x_cap, max_gap=14.5, x_drift=80.0)
    label = _join_block_text(up)
    return label

def _compute_repeating_groups(var_codes):
    """
    Identify vertical repeating code runs (option lists / table rows) by x-band + regular y gaps.
    Returns mapping: var_code_entry_index -> group_id, and dict group_id -> group info.
    """
    if not var_codes:
        return {}, {}

    # Bucket by x0 bands
    buckets = {}
    for vi, vc in enumerate(var_codes):
        x = float(vc["line"].x0)
        key = int(round(x / 12.0))  # tolerant binning
        buckets.setdefault(key, []).append(vi)

    membership = {}
    groups = {}
    gid = 0

    for key, idxs in buckets.items():
        idxs_sorted = sorted(idxs, key=lambda i: float(var_codes[i]["line"].y0))
        run = []
        prev_y = None
        for vi in idxs_sorted:
            y = float(var_codes[vi]["line"].y0)
            if prev_y is None:
                run = [vi]
                prev_y = y
                continue
            dy = (y - prev_y)
            if 9.0 <= dy <= 26.0:
                run.append(vi)
            else:
                if len(run) >= 3:
                    for rvi in run:
                        membership[rvi] = gid
                    ys = [float(var_codes[rvi]["line"].y0) for rvi in run]
                    groups[gid] = {
                        "members": list(run),
                        "x_key": key,
                        "y_min": min(ys),
                        "y_max": max(ys),
                    }
                    gid += 1
                run = [vi]
            prev_y = y

        if len(run) >= 3:
            for rvi in run:
                membership[rvi] = gid
            ys = [float(var_codes[rvi]["line"].y0) for rvi in run]
            groups[gid] = {
                "members": list(run),
                "x_key": key,
                "y_min": min(ys),
                "y_max": max(ys),
            }
            gid += 1

    return membership, groups

def _group_header_label(lines, var_codes, group_info, left_margin):
    """
    Find a shared header/question above a repeating group; used to avoid per-option anchor/row labels.
    """
    members = group_info.get("members") or []
    if not members:
        return ""

    # Choose the first code on the page (by lines idx) among group
    first_member = min(members, key=lambda vi: int(var_codes[vi]["idx"]))
    code_idx = int(var_codes[first_member]["idx"])
    code_line = var_codes[first_member]["line"]
    cx = float(code_line.x0)
    top_y = float(code_line.y0)

    best_idx = None
    best_y = -1e9
    j = code_idx - 1
    while j >= 0:
        l = lines[j]
        if (top_y - float(l.y0)) > 220:
            break
        if l.non_black:
            j -= 1
            continue
        t = _norm_text(l.text)
        if not t or _is_bracketed(t):
            j -= 1
            continue
        if float(l.x0) < left_margin - 18:
            j -= 1
            continue
        if float(l.x0) > cx + 35:
            j -= 1
            continue
        # Prefer candidates that are clearly above the option list (gap)
        if (top_y - float(l.y0)) < 10:
            j -= 1
            continue
        if float(l.y0) > best_y:
            best_y = float(l.y0)
            best_idx = j
        j -= 1

    if best_idx is None:
        return ""

    x_cap = min(cx + 35.0, left_margin + 620.0)
    up = _gather_label_block_up(lines, best_idx, x_cap=x_cap, max_gap=14.5, x_drift=85.0)
    # allow multi-line question that may flow downwards a bit
    down = _gather_label_block_down(lines, best_idx, x_ref=float(lines[best_idx].x0), y_limit=top_y - 10, x_band=90.0, max_gap=14.5)
    # merge unique, preserving order
    merged = []
    seen = set()
    for l in up + down:
        if id(l) in seen:
            continue
        seen.add(id(l))
        merged.append(l)

    label = _join_block_text(merged)
    return label

def extract(pages):
    out = []
    current_form = ""

    for page_idx0, lines in pages:
        lines = list(lines or [])
        var_codes = _collect_var_codes(lines)

        if var_codes:
            current_form = _detect_form_title(lines, var_codes, current_form)

        if not var_codes:
            continue

        _, med_sz, _ = _page_sizes(lines)
        left_margin = _compute_left_margin(lines)

        # Detect repeating vertical groups to avoid per-row/option anchor capture
        membership, groups = _compute_repeating_groups(var_codes)
        group_labels = {}
        for gid, ginfo in groups.items():
            glab = _group_header_label(lines, var_codes, ginfo, left_margin)
            if _label_sane(glab):
                group_labels[gid] = _norm_text(glab)

        for vi, vc in enumerate(var_codes):
            idx = vc["idx"]
            code_line = vc["line"]

            label = ""

            gid = membership.get(vi)
            if gid is not None and gid in group_labels:
                label = group_labels[gid]

            if not label:
                label = _label_from_inline_left(lines, idx, code_line, left_margin)
            if not _label_sane(label):
                label = ""

            if not label:
                label = _label_from_nearby_block(lines, idx, code_line, left_margin)
            if not _label_sane(label):
                label = ""

            if not label:
                label = _label_from_left_context(lines, idx, code_line, left_margin)
            if not _label_sane(label):
                label = ""

            if not label:
                label = _label_from_same_x_header(lines, idx, code_line, med_sz, left_margin)
            if not _label_sane(label):
                label = ""

            if not label:
                label = _find_any_nearby_black_label(lines, idx, code_line, left_margin)
            if not _label_sane(label):
                label = ""

            # Final fallback: only use form title if there's no nearby black label evidence at all
            if not label:
                # if page has any nearby black text within range, prefer skipping over inventing a label
                nearby = _find_any_nearby_black_label(lines, idx, code_line, left_margin)
                if not _label_sane(nearby):
                    label = _norm_text(current_form)

            label = _norm_text(label)
            if not _label_sane(label):
                continue

            out.append(
                {
                    "form_name": _norm_text(current_form),
                    "field_name": label,
                    "page": int(page_idx0) + 1,
                }
            )

    return out
```
