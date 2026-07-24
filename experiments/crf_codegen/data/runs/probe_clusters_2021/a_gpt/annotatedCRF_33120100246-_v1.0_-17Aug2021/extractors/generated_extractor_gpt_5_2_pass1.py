# Observed layout: annotated CRF pages with red bracketed machine codes + [TYPE: ...] lines;
# human form titles are either a large colored header near the top-left or (on some lab pages)
# a small black heading near top-left with no nearby code. Field labels are black text lines
# immediately above the red variable code, sometimes wrapped across multiple lines.
# Strategy: carry forward detected form title; for each red variable code, backtrack by geometry
# to assemble its nearest left-column label block (fallback to same-x column header, else form title).

import re
import unicodedata
from statistics import median

_RE_WS = re.compile(r"\s+")
_RE_BRACKETED = re.compile(r"^\[.*\]$")
_RE_VAR_INNER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,}$")
_RE_HAS_ALNUM = re.compile(r"[0-9A-Za-z]")

def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00ad", "")  # soft hyphen
    s = _RE_WS.sub(" ", s).strip()
    return s

def _is_bracketed(text: str) -> bool:
    return bool(text) and text[0] == "[" and text[-1] == "]" and _RE_BRACKETED.match(text) is not None

def _is_type_like_bracket(inner: str) -> bool:
    # Disqualify technical annotations inside brackets (language-agnostic via punctuation patterns).
    # We avoid literal word blocklists; instead, exclude bracketed items containing ":" or spaces.
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
    y0 = lines[i].y0
    size0 = lines[i].size

    parts = [t0]
    j = i
    # allow up to 3-line join
    for _ in range(2):
        if j + 1 >= len(lines):
            break
        nxt = lines[j + 1]
        t1 = _norm_text(nxt.text)
        if not t1:
            break
        if ":" in t1 or " " in t1:
            break
        # geometry: same column, adjacent lines, similar size, and colored (non_black)
        if not nxt.non_black:
            break
        if abs(nxt.x0 - x0) > 6:
            break
        if (nxt.y0 - lines[j].y0) > 18:
            break
        if size0 and nxt.size and abs(nxt.size - size0) > 1.2:
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
        t = _norm_text(l.text)
        if not t or _is_bracketed(t):
            continue
        if l.non_black:
            continue
        # ignore far-right header furniture
        if l.x0 > 300:
            continue
        xs.append(float(l.x0))
    if not xs:
        return 50.0
    xs.sort()
    # robust: near-min but tolerant
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
        t = _norm_text(l.text)
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

    # 1) Large colored title near top-left
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
        # avoid top-right pack/version blocks
        if l.x0 > 300:
            continue
        if best is None or (l.y0 < best.y0) or (abs(l.y0 - best.y0) <= 2 and l.x0 < best.x0):
            best = l
    if best is not None:
        return _norm_text(best.text) or prev_form

    # 2) Small black heading near top-left (lab-style), but only if not "immediately label-like"
    #    We accept it only when no variable code occurs within the next ~200pts vertically.
    cand = None
    for l in lines:
        t = _norm_text(l.text)
        if not t or _is_bracketed(t):
            continue
        if l.non_black:
            continue
        if l.y0 > 90 or l.x0 > 140:
            continue
        # ignore tiny fonts and top-right furniture
        if l.size < 6.0 or l.x0 > 250:
            continue
        cand = l
        break

    if cand is None:
        return prev_form

    cy = cand.y0
    for vc in var_codes:
        if vc["line"].y0 < cy + 200:
            # looks like an ordinary field label page-start; keep previous form
            return prev_form

    return _norm_text(cand.text) or prev_form

def _gather_label_block(lines, start_idx, left_margin, x_cap, max_gap=14.5):
    """
    Given an index of a black label line, gather wrapped lines upward into one label block.
    """
    if start_idx is None:
        return []
    block = [lines[start_idx]]
    x0_ref = lines[start_idx].x0
    y_prev = lines[start_idx].y0

    j = start_idx - 1
    while j >= 0:
        l = lines[j]
        t = _norm_text(l.text)
        if not t or _is_bracketed(t) or l.non_black:
            break
        # must remain in the same left-ish column
        if l.x0 > x_cap:
            break
        # wrap continuation: close vertical spacing + similar x
        if (y_prev - l.y0) > max_gap:
            break
        if abs(l.x0 - x0_ref) > 55:
            break
        # avoid accidentally absorbing unrelated left headers far above
        block.append(l)
        y_prev = l.y0
        x0_ref = (x0_ref * 0.7 + l.x0 * 0.3)
        j -= 1

    block.reverse()
    return block

def _label_from_left_context(lines, code_idx, code_line, left_margin):
    """
    Find nearest black left-column label above this code line.
    """
    cy = code_line.y0
    x_cap = left_margin + 220.0

    best_idx = None
    best_y = -1e9
    j = code_idx - 1
    while j >= 0:
        l = lines[j]
        if (cy - l.y0) > 110:
            break
        t = _norm_text(l.text)
        if not t or _is_bracketed(t):
            j -= 1
            continue
        if l.non_black:
            j -= 1
            continue
        if l.x0 > x_cap:
            j -= 1
            continue
        # pick closest in y
        if l.y0 > best_y:
            best_y = l.y0
            best_idx = j
        j -= 1

    if best_idx is None:
        return ""

    block = _gather_label_block(lines, best_idx, left_margin, x_cap=x_cap, max_gap=14.5)
    label = _norm_text(" ".join(_norm_text(b.text) for b in block if _norm_text(b.text)))
    return label

def _label_from_same_x_header(lines, code_idx, code_line, med_sz):
    """
    Fallback for table-like structures: find a header above in the same x band with larger font.
    """
    cx = code_line.x0
    cy = code_line.y0
    best_idx = None
    best_score = None

    j = code_idx - 1
    while j >= 0:
        l = lines[j]
        if (cy - l.y0) > 280:
            break
        t = _norm_text(l.text)
        if not t or _is_bracketed(t) or l.non_black:
            j -= 1
            continue
        # must be near the code x (column header)
        if abs(l.x0 - cx) > 95:
            j -= 1
            continue
        # prefer larger font (table headers often larger)
        if l.size < med_sz + 0.4:
            j -= 1
            continue
        # score: closer y, closer x, bigger size
        score = (-(cy - l.y0), -abs(l.x0 - cx), l.size)
        if best_score is None or score > best_score:
            best_score = score
            best_idx = j
        j -= 1

    if best_idx is None:
        return ""

    # gather multi-line header downward/upward near same x
    header_lines = [lines[best_idx]]
    # look a bit downward (split headers)
    k = best_idx + 1
    while k < len(lines):
        l = lines[k]
        if l.y0 > lines[best_idx].y0 + 40:
            break
        t = _norm_text(l.text)
        if not t or _is_bracketed(t) or l.non_black:
            k += 1
            continue
        if abs(l.x0 - lines[best_idx].x0) > 95:
            k += 1
            continue
        if abs(l.size - lines[best_idx].size) > 1.2:
            k += 1
            continue
        if (l.y0 - header_lines[-1].y0) > 16:
            k += 1
            continue
        header_lines.append(l)
        k += 1

    label = _norm_text(" ".join(_norm_text(l.text) for l in header_lines if _norm_text(l.text)))
    return label

def extract(pages):
    out = []
    current_form = ""

    for page_idx0, lines in pages:
        lines = list(lines or [])
        var_codes = _collect_var_codes(lines)

        # update form context only when page looks like it has form content (codes present)
        if var_codes:
            current_form = _detect_form_title(lines, var_codes, current_form)

        if not var_codes:
            continue

        _, med_sz, _ = _page_sizes(lines)
        left_margin = _compute_left_margin(lines)

        for vc in var_codes:
            idx = vc["idx"]
            code_line = vc["line"]

            label = _label_from_left_context(lines, idx, code_line, left_margin)
            if not label:
                label = _label_from_same_x_header(lines, idx, code_line, med_sz)
            if not label:
                label = current_form

            label = _norm_text(label)

            # structural sanity filters (avoid empty / pure punctuation)
            if not label:
                continue
            if not _RE_HAS_ALNUM.search(label):
                continue

            out.append(
                {
                    "form_name": _norm_text(current_form),
                    "field_name": label,
                    "page": int(page_idx0) + 1,
                }
            )

    return out
