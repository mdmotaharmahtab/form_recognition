```python
import re
import unicodedata
import statistics

_WS_RE = re.compile(r"\s+")
_DAY_RE = re.compile(r"(?i)\bday\b")
_NUM_TOKEN_RE = re.compile(r"\b-?\d+\b")
_DESC_RE = re.compile(r"(?i)^description\s*:")
_MULTI_DOT_RE = re.compile(r"\.{3,}")
_GAP_RE = re.compile(r"(?:\t| {3,})")

# Structural/technical annotation vocabulary (not field labels).
_TECH_ANNOT_RE = re.compile(
    r"(?i)\b("
    r"mandatory\?|"
    r"edit checks?|"
    r"requires barcode verification|"
    r"formal expression|"
    r"\bcontext\b|"
    r"\bname\b\s*:|"
    r"\bvalue should\b|"
    r"\bshort name\b|"
    r"\bdisallow future date\b|"
    r"decode\b\s*:|"
    r"\bcoded\b\s*:|"
    r"\bdescription\b\s*:"
    r")\b"
)

# "Radio/checkbox" glyphs often OCR as plain O/0
_BULLET_TOKENS = {"o", "O", "0", "○", "◯", "●", "□", "☐", "▢"}


def _get(l, attr, default=None):
    try:
        return getattr(l, attr)
    except Exception:
        return default


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def _has_letter_or_number(s: str) -> bool:
    for ch in s:
        cat = unicodedata.category(ch)
        if cat and (cat[0] == "L" or cat[0] == "N"):
            return True
    return False


def _is_bracketed_code(t: str) -> bool:
    t = (t or "").strip()
    return len(t) >= 2 and t[0] == "[" and t[-1] == "]"


def _is_mostly_box_art(t: str) -> bool:
    s = (t or "").strip()
    if not s:
        return True
    if any(c in s for c in ("_", "|", "[", "]", "□", "☐", "▢")):
        box_chars = set("_|[](){}<>-–—·. :;/\\+*=,")
        keep = 0
        for ch in s:
            if ch in box_chars or ch.isdigit() or ch.isspace() or ch in ("□", "☐", "▢"):
                keep += 1
        return keep / max(1, len(s)) > 0.65
    return False


def _token_stats(t: str):
    s = _norm(t)
    digits = sum(ch.isdigit() for ch in s)
    letters = sum(ch.isalpha() for ch in s)
    words = [w for w in s.split(" ") if w]
    starts_digit = bool(s) and s[0].isdigit()
    ends_punct = bool(s) and s[-1] in (":", "?", ";")
    upper_letters = sum(ch.isupper() for ch in s if ch.isalpha())
    lower_letters = sum(ch.islower() for ch in s if ch.isalpha())
    all_caps = (letters > 0 and lower_letters == 0 and upper_letters >= max(1, int(letters * 0.8)))
    return {
        "s": s,
        "digits": digits,
        "letters": letters,
        "words": words,
        "word_count": len(words),
        "starts_digit": starts_digit,
        "ends_punct": ends_punct,
        "all_caps": all_caps,
    }


def _looks_like_rating_anchor(t: str) -> bool:
    st = _token_stats(t)
    if not st["s"]:
        return True
    # "0 MILD", "1 SEVERE"
    if st["starts_digit"] and st["word_count"] <= 2 and st["letters"] > 0 and st["all_caps"]:
        return True
    return False


def _looks_like_tech_annotation_line(t: str) -> bool:
    s = _norm(t)
    if not s:
        return False
    if _TECH_ANNOT_RE.search(s):
        return True
    return False


def _looks_like_value_line(t: str) -> bool:
    s = _norm(t)
    if not s:
        return True
    if _is_bracketed_code(s) or _is_mostly_box_art(s):
        return True
    st = _token_stats(s)

    # Numeric-only or numeric-heavy short tokens are almost always filled values.
    if st["letters"] == 0 and st["digits"] >= 1:
        if len(s) <= 14 and st["word_count"] <= 3:
            return True

    # Short all-caps "selected value" lines (e.g., BODY SYSTEM = GASTROINTESTINAL).
    if st["all_caps"] and st["letters"] > 0 and st["word_count"] <= 4:
        if not any(ch in s for ch in ("?", ":", ";")):
            return True

    return False


def _starts_with_choice_bullet(s: str) -> bool:
    s = _norm(s)
    if not s:
        return False
    # bracket-like boxes
    if s.startswith(("[ ]", "[]", "( )", "()")):
        return True
    # plain O/0 bullet + space + label
    parts = s.split(" ")
    if len(parts) >= 2 and parts[0] in _BULLET_TOKENS:
        nxt = parts[1]
        if any(ch.isalpha() for ch in nxt) or nxt.isdigit():
            return True
    # Unicode box/circle at start
    if s[:1] in {"□", "☐", "▢", "○", "◯", "●"}:
        return True
    return False


def _count_choice_bullets(s: str) -> int:
    s = _norm(s)
    if not s:
        return 0
    toks = s.split(" ")
    c = sum(1 for t in toks if t in _BULLET_TOKENS)
    c += s.count("[ ]") + s.count("( )")
    return c


def _looks_like_unbulleted_option_row(raw: str, normed: str) -> bool:
    raw = raw or ""
    s = _norm(normed)
    if not s:
        return True
    st = _token_stats(s)
    if st["ends_punct"]:
        return False
    if "?" in s or ":" in s:
        return False
    if st["letters"] == 0:
        return False
    if st["word_count"] > 8:
        return False

    # Strong signal: large visual gaps between tokens (multiple spaces/tabs).
    if _GAP_RE.search(raw):
        # Avoid treating ordinary wrapped label text as options.
        # Options rows tend to be short, with multiple capitalized tokens.
        cap_tokens = 0
        for w in st["words"]:
            if w and w[0].isalpha() and (w[0].isupper() or w.isupper()):
                cap_tokens += 1
        if cap_tokens >= 2 and st["word_count"] <= 6:
            return True
    return False


def _looks_like_option_set_line(t: str, raw: str = "") -> bool:
    s = _norm(t)
    if not s:
        return True
    if _is_mostly_box_art(s) or _is_bracketed_code(s):
        return True
    if _count_choice_bullets(s) >= 2:
        return True
    if _looks_like_unbulleted_option_row(raw, s):
        return True
    return False


def _looks_like_single_option_line(t: str) -> bool:
    s = _norm(t)
    if not s:
        return True
    if _starts_with_choice_bullet(s):
        st = _token_stats(s)
        if st["word_count"] <= 4 and st["letters"] > 0 and not st["ends_punct"]:
            return True
    return False


def _looks_like_visit_timeline_line(t: str) -> bool:
    lt = _norm(t).lower()
    if not lt:
        return False
    if "day" not in lt:
        return False
    day_hits = len(_DAY_RE.findall(lt))
    num_hits = len(_NUM_TOKEN_RE.findall(lt))
    if day_hits >= 2 and num_hits >= 8 and len(lt) >= 28:
        return True
    return False


def _join_wrapped(lines) -> str:
    parts = [_norm(_get(l, "text", "")) for l in lines if _norm(_get(l, "text", ""))]
    if not parts:
        return ""
    out = parts[0]
    for nxt in parts[1:]:
        if not nxt:
            continue
        if out.endswith("-") and nxt and _has_letter_or_number(nxt[:1]):
            out = out[:-1] + nxt
        else:
            out = out + " " + nxt
    out = _norm(out)
    out = _MULTI_DOT_RE.sub("..", out)
    return out


def _page_dims(lines):
    w = 0.0
    h = 0.0
    for l in lines:
        x1 = _get(l, "x1", 0.0) or 0.0
        y1 = _get(l, "y1", 0.0) or 0.0
        if x1 > w:
            w = x1
        if y1 > h:
            h = y1
    if w <= 0:
        w = 612.0
    if h <= 0:
        h = 792.0
    return w, h


def _text_eq(t: str, s: str) -> bool:
    return _norm(t).lower() == s.lower()


def _is_codelist_page(lines, w, h) -> bool:
    y_min = h * 0.05
    y_max = h * 0.14
    coded = []
    decode = []
    for l in lines:
        y0 = _get(l, "y0", 0.0) or 0.0
        if y0 < y_min or y0 > y_max:
            continue
        t = _norm(_get(l, "text", ""))
        if not t:
            continue
        if _text_eq(t, "coded"):
            coded.append(l)
        elif _text_eq(t, "decode"):
            decode.append(l)

    if not coded or not decode:
        return False

    for c in coded:
        for d in decode:
            cy0 = _get(c, "y0", 0.0) or 0.0
            dy0 = _get(d, "y0", 0.0) or 0.0
            cx0 = _get(c, "x0", 0.0) or 0.0
            dx0 = _get(d, "x0", 0.0) or 0.0
            cs = _get(c, "size", 0.0) or 0.0
            ds = _get(d, "size", 0.0) or 0.0
            if abs(cy0 - dy0) <= max(4.0, (cs + ds) * 0.4) and (dx0 - cx0) > w * 0.25:
                return True
    return False


def _is_metadata_only_page(lines, w, h) -> bool:
    # A page dominated by right-column field definition metadata.
    right_x = w * 0.58
    y_min = h * 0.02
    y_max = h * 0.22

    keys = 0
    for l in lines:
        x0 = _get(l, "x0", 0.0) or 0.0
        y0 = _get(l, "y0", 0.0) or 0.0
        if x0 <= right_x:
            continue
        if y0 < y_min or y0 > y_max:
            continue
        t = _norm(_get(l, "text", "")).lower()
        if not t:
            continue
        if t.startswith("description"):
            keys += 1
        elif t.startswith("short name"):
            keys += 1
        elif t.startswith("mandatory?"):
            keys += 1
        elif t.startswith("disallow future date"):
            keys += 1
        if keys >= 3:
            return True
    return False


def _extract_description_field(lines, w, h) -> str:
    right_x = w * 0.58
    y_min = h * 0.02
    y_max = h * 0.28

    candidates = []
    for l in lines:
        x0 = _get(l, "x0", 0.0) or 0.0
        y0 = _get(l, "y0", 0.0) or 0.0
        if x0 <= right_x:
            continue
        if y0 < y_min or y0 > y_max:
            continue
        t = _norm(_get(l, "text", ""))
        if not t:
            continue
        if _DESC_RE.match(t):
            candidates.append(l)

    if not candidates:
        return ""

    candidates.sort(key=lambda l: ((_get(l, "y0", 0.0) or 0.0), (_get(l, "x0", 0.0) or 0.0)))
    first = candidates[0]

    group = [first]
    x0 = _get(first, "x0", 0.0) or 0.0
    base_size = _get(first, "size", 0.0) or 0.0
    cur = first

    right_lines = [
        l
        for l in lines
        if (
            (_get(l, "x0", 0.0) or 0.0) > right_x
            and y_min <= (_get(l, "y0", 0.0) or 0.0) <= h * 0.60
        )
    ]
    right_lines.sort(key=lambda l: ((_get(l, "y0", 0.0) or 0.0), (_get(l, "x0", 0.0) or 0.0)))

    start_idx = None
    for idx, rl in enumerate(right_lines):
        if rl is first:
            start_idx = idx
            break

    if start_idx is not None:
        for nxt in right_lines[start_idx + 1 :]:
            nx0 = _get(nxt, "x0", 0.0) or 0.0
            ns = _get(nxt, "size", 0.0) or 0.0
            if abs(nx0 - x0) > max(10.0, w * 0.02):
                break
            if base_size > 0 and abs(ns - base_size) > base_size * 0.55:
                break
            gap = (_get(nxt, "y0", 0.0) or 0.0) - (_get(cur, "y1", 0.0) or 0.0)
            if gap > max((_get(cur, "size", 0.0) or 0.0), ns) * 1.35 + 6.0:
                break
            nt = _norm(_get(nxt, "text", ""))
            if re.match(r"(?i)^(short name|mandatory\?|disallow future date)\b", nt):
                break
            group.append(nxt)
            cur = nxt

    joined = _join_wrapped(group)
    joined = _DESC_RE.sub("", joined).strip()
    return _norm(joined)


def _compute_right_annotation_boundary(lines, w, h) -> float:
    # Find a likely start-x of the right annotation/metadata column, then set content_x_max just left of it.
    y_low = h * 0.06
    y_high = h * 0.93

    xs = []
    for l in lines:
        y0 = _get(l, "y0", 0.0) or 0.0
        if y0 < y_low or y0 > y_high:
            continue
        x0 = _get(l, "x0", 0.0) or 0.0
        s = _norm(_get(l, "text", ""))
        if not s:
            continue
        sz = _get(l, "size", 0.0) or 0.0

        # Strong evidence: technical annotation terms or unusually small font.
        if _looks_like_tech_annotation_line(s):
            if x0 > w * 0.45:
                xs.append(x0)
            continue
        if sz > 0 and sz <= 7.6 and x0 > w * 0.52:
            xs.append(x0)

    if len(xs) < 6:
        return w * 0.62

    xs.sort()
    # Use an upper-quantile estimate for the column start cluster.
    q = xs[int(0.20 * (len(xs) - 1))]  # lower-ish quantile among right-ish xs
    # Move boundary slightly left to keep labels out of annotation column.
    boundary = q - max(10.0, w * 0.03)

    # Clamp to reasonable range.
    boundary = max(w * 0.45, min(boundary, w * 0.74))
    return boundary


def _looks_like_title_candidate(t: str, raw: str = "") -> bool:
    s = _norm(t)
    if not s:
        return False
    if _is_bracketed_code(s):
        return False
    if _is_mostly_box_art(s):
        return False
    if _looks_like_tech_annotation_line(s):
        return False
    # Avoid Coded/Decode headers becoming titles
    if _text_eq(s, "coded") or _text_eq(s, "decode"):
        return False
    if _looks_like_option_set_line(s, raw=raw) or _looks_like_single_option_line(s):
        return False
    st = _token_stats(s)
    if st["ends_punct"]:
        return False
    if _looks_like_rating_anchor(s):
        return False
    if st["letters"] == 0 and st["digits"] >= 2:
        return False
    return True


def _collect_title_band_candidates(lines, w, h):
    y_min = h * 0.01
    y_max = h * 0.30
    x_max = w * 0.88

    cands = []
    for l in lines:
        y0 = _get(l, "y0", 0.0) or 0.0
        x0 = _get(l, "x0", 0.0) or 0.0
        if y0 < y_min or y0 > y_max:
            continue
        if x0 > x_max:
            continue
        t_raw = _get(l, "text", "") or ""
        t = _norm(t_raw)
        if not _looks_like_title_candidate(t, raw=t_raw):
            continue

        # Titles often use larger font or non-black (e.g., white on dark header).
        sz = _get(l, "size", 0.0) or 0.0
        if sz > 0 and sz < 10.0:
            # Keep small only if it's clearly multi-word (avoid nav tabs).
            st = _token_stats(t)
            if st["word_count"] < 2:
                continue

        # Avoid very short tokens ("PR") becoming form titles.
        st = _token_stats(t)
        if st["word_count"] == 1 and len(t) <= 4:
            continue

        cands.append(l)
    return cands


def _join_multiline_title(seed, candidates, w, h):
    if seed is None:
        return ""
    x_tol = max(10.0, w * 0.03)
    y_gap = max((_get(seed, "size", 0.0) or 0.0) * 1.35, h * 0.012)
    sz_tol = max(1.4, (_get(seed, "size", 0.0) or 0.0) * 0.25)

    neighbors = []
    sy0 = _get(seed, "y0", 0.0) or 0.0
    sx0 = _get(seed, "x0", 0.0) or 0.0
    ss = _get(seed, "size", 0.0) or 0.0
    sy1 = _get(seed, "y1", sy0 + 1.0) or (sy0 + 1.0)

    for l in candidates:
        if l is seed:
            continue
        ly0 = _get(l, "y0", 0.0) or 0.0
        lx0 = _get(l, "x0", 0.0) or 0.0
        ls = _get(l, "size", 0.0) or 0.0
        ly1 = _get(l, "y1", ly0 + 1.0) or (ly0 + 1.0)

        if abs(lx0 - sx0) <= x_tol and abs(ls - ss) <= sz_tol:
            if abs(ly0 - sy0) <= (y_gap * 2.0) or (0 <= (ly0 - sy1) <= y_gap) or (0 <= (sy0 - ly1) <= y_gap):
                neighbors.append(l)

    block = [seed]
    above = [l for l in neighbors if (_get(l, "y1", 0.0) or 0.0) <= sy0 + (ss * 0.3)]
    below = [l for l in neighbors if (_get(l, "y0", 0.0) or 0.0) >= sy0 - (ss * 0.3)]
    if above:
        above.sort(key=lambda l: (-(_get(l, "y0", 0.0) or 0.0), (_get(l, "x0", 0.0) or 0.0)))
        block = [above[0]] + block
    if below:
        below.sort(key=lambda l: ((_get(l, "y0", 0.0) or 0.0), (_get(l, "x0", 0.0) or 0.0)))
        if below[0] is not seed:
            block = block + [below[0]]

    block.sort(key=lambda l: ((_get(l, "y0", 0.0) or 0.0), (_get(l, "x0", 0.0) or 0.0)))
    return _join_wrapped(block)


def _find_form_title(lines, w, h) -> str:
    cands = _collect_title_band_candidates(lines, w, h)
    if not cands:
        return ""

    # Prefer larger font and higher placement.
    best = None
    best_key = None

    for l in cands:
        t_raw = _get(l, "text", "") or ""
        t = _norm(t_raw)
        st = _token_stats(t)

        has_ln = 1 if _has_letter_or_number(t) else 0
        has_two_words = 1 if st["word_count"] >= 2 else 0
        not_digit_led = 1 if not st["starts_digit"] else 0
        low_digit_ratio = 1 if (len(t) == 0 or (st["digits"] / max(1, len(t)) <= 0.18)) else 0

        sz = _get(l, "size", 0.0) or 0.0
        y0 = _get(l, "y0", 0.0) or 0.0
        x0 = _get(l, "x0", 0.0) or 0.0

        key = (
            has_ln,
            has_two_words,
            not_digit_led,
            low_digit_ratio,
            sz,
            -y0,
            -(-x0),
            len(t),
        )
        if best is None or key > best_key:
            best = l
            best_key = key

    title = _join_multiline_title(best, cands, w, h)
    title = _norm(title)
    if not title or not _looks_like_title_candidate(title, raw=title):
        return ""
    st = _token_stats(title)
    if st["word_count"] == 1 and len(title) <= 5:
        return ""
    if _looks_like_tech_annotation_line(title):
        return ""
    return title


def _cluster_x0(lines, tol):
    xs = sorted((_get(l, "x0", 0.0) or 0.0) for l in lines)
    if not xs:
        return []
    clusters = []
    cur = [xs[0]]
    for x in xs[1:]:
        if abs(x - cur[-1]) <= tol:
            cur.append(x)
        else:
            clusters.append((sum(cur) / len(cur), len(cur)))
            cur = [x]
    clusters.append((sum(cur) / len(cur), len(cur)))
    clusters.sort(key=lambda t: (-t[1], t[0]))
    return clusters


def _nearest_anchor(x, anchors, tol):
    best = None
    best_d = None
    for a in anchors:
        d = abs(x - a)
        if best is None or d < best_d:
            best = a
            best_d = d
    if best is None or best_d is None or best_d > tol:
        return None
    return best


def _row_peers(l, peers, w, h):
    y_tol = max(4.0, (_get(l, "size", 0.0) or 0.0) * 0.85, h * 0.006)
    row = []
    ly0 = _get(l, "y0", 0.0) or 0.0
    ls = _get(l, "size", 0.0) or 0.0
    for p in peers:
        py0 = _get(p, "y0", 0.0) or 0.0
        ps = _get(p, "size", 0.0) or 0.0
        if abs(py0 - ly0) <= y_tol and abs(ps - ls) <= max(1.8, ls * 0.30):
            row.append(p)
    return row


def _is_header_row_member(l, peers, w, h):
    # Exclude navigation/table header rows (many labels on one y), but keep true field rows (e.g., PR/QRS/QT).
    row = _row_peers(l, peers, w, h)
    if len(row) < 3:
        return False

    xs = sorted((_get(p, "x0", 0.0) or 0.0) for p in row)
    spread = (xs[-1] - xs[0]) if xs else 0.0
    if spread < w * 0.38:
        return False

    y0 = _get(l, "y0", 0.0) or 0.0
    near_top = y0 < h * 0.22

    # Characterize row tokens.
    longish = 0
    slashy = 0
    puncty = 0
    all_caps_micro = 0
    for p in row:
        t = _norm(_get(p, "text", ""))
        st = _token_stats(t)
        if "/" in t:
            slashy += 1
        if any(ch in t for ch in ("?", ":", ";")):
            puncty += 1
        if st["word_count"] >= 2 and len(t) >= 7:
            longish += 1
        if st["word_count"] == 1 and st["all_caps"] and 1 <= len(t) <= 4:
            all_caps_micro += 1

    # If it's a nav/header row: top-ish, spread wide, mostly not acronym micro-fields.
    if near_top and (len(row) >= 4 or (len(row) == 3 and (slashy >= 1 or longish >= 2))):
        return True

    # Wider "table header" style: lots of short labels, multiple columns, and sits in upper half.
    short = 0
    for p in row:
        t = _norm(_get(p, "text", ""))
        if t and len(t) <= 5 and not _looks_like_option_set_line(t, raw=_get(p, "text", "") or "") and not _is_mostly_box_art(t):
            short += 1
    if len(row) >= 5 and short >= 3 and y0 < h * 0.60 and puncty == 0:
        return True

    # Don't treat acronym micro-rows as headers by default (keeps PR/QRS/QT).
    if len(row) == 3 and all_caps_micro == 3 and puncty == 0:
        return False

    return False


def _is_group_header_for_checklist(label_line, lines, w, h, content_x_max):
    y_start = (_get(label_line, "y1", 0.0) or 0.0)
    size = _get(label_line, "size", 0.0) or 0.0
    y_end = min(h * 0.92, y_start + max(size * 7.0, h * 0.10))
    x_min = (_get(label_line, "x0", 0.0) or 0.0) + max(6.0, w * 0.02)

    hits = 0
    for l in lines:
        y0 = _get(l, "y0", 0.0) or 0.0
        x0 = _get(l, "x0", 0.0) or 0.0
        if x0 <= x_min or x0 >= content_x_max:
            continue
        if y0 < y_start or y0 > y_end:
            continue
        t_raw = _get(l, "text", "") or ""
        t = _norm(t_raw)
        if not t or _is_bracketed_code(t):
            continue
        if _looks_like_option_set_line(t, raw=t_raw) or _looks_like_single_option_line(t):
            hits += 1
            if hits >= 2:
                return True
        if _is_mostly_box_art(t):
            hits += 1
            if hits >= 2:
                return True
    return False


def _looks_like_nonfield_label(t: str, raw: str = "") -> bool:
    s = _norm(t)
    if not s:
        return True
    if _is_bracketed_code(s) or _is_mostly_box_art(s):
        return True
    if _looks_like_tech_annotation_line(s):
        return True
    if _looks_like_rating_anchor(s):
        return True
    if _looks_like_option_set_line(s, raw=raw) or _looks_like_single_option_line(s):
        return True
    if _looks_like_visit_timeline_line(s):
        return True
    if _looks_like_value_line(s):
        return True
    return False


def _extract_fields_content(lines, w, h, form_name, page_1based, content_x_max):
    y_low = h * 0.07
    y_high = h * 0.93

    prelim = []
    for l in lines:
        y0 = _get(l, "y0", 0.0) or 0.0
        x0 = _get(l, "x0", 0.0) or 0.0
        if y0 < y_low or y0 > y_high:
            continue
        if x0 >= content_x_max:
            continue
        t_raw = _get(l, "text", "") or ""
        t = _norm(t_raw)
        if not t:
            continue
        if _looks_like_nonfield_label(t, raw=t_raw):
            continue
        prelim.append(l)

    if not prelim:
        return []

    sizes = [(_get(l, "size", 0.0) or 0.0) for l in prelim if (_get(l, "size", 0.0) or 0.0) > 0]
    med = statistics.median(sizes) if sizes else 0.0

    cand = []
    for l in prelim:
        sz = _get(l, "size", 0.0) or 0.0
        if med > 0 and sz > 0:
            # Allow slightly broader range to keep question/section-like labels that are still entry fields.
            if sz < med * 0.55 or sz > med * 2.25:
                # If it ends with a question mark/colon, it's often a real field label even when larger.
                t = _norm(_get(l, "text", "") or "")
                if not (t.endswith("?") or t.endswith(":")):
                    continue
        cand.append(l)

    if not cand:
        return []

    # Remove header/navigation row members.
    cand2 = []
    for l in cand:
        if _is_header_row_member(l, cand, w, h):
            continue
        cand2.append(l)
    cand = cand2
    if not cand:
        return []

    tol = max(8.0, w * 0.018)
    clusters = _cluster_x0(cand, tol=tol)
    anchors = [c[0] for c in clusters[:4]] if clusters else []

    by_col = {}
    for l in cand:
        x0 = _get(l, "x0", 0.0) or 0.0
        a = _nearest_anchor(x0, anchors, tol=tol)
        key = a if a is not None else x0
        by_col.setdefault(key, []).append(l)

    records = []
    seen = set()

    for _, items in by_col.items():
        items.sort(key=lambda l: ((_get(l, "y0", 0.0) or 0.0), (_get(l, "x0", 0.0) or 0.0)))

        i = 0
        while i < len(items):
            group = [items[i]]
            x0 = _get(items[i], "x0", 0.0) or 0.0
            base_size = _get(items[i], "size", 0.0) or 0.0
            j = i + 1

            while j < len(items):
                prev = group[-1]
                nxt = items[j]

                nx0 = _get(nxt, "x0", 0.0) or 0.0
                ns = _get(nxt, "size", 0.0) or 0.0
                if abs(nx0 - x0) > tol:
                    break
                if base_size > 0 and ns > 0 and abs(ns - base_size) > base_size * 0.45:
                    break

                gap = (_get(nxt, "y0", 0.0) or 0.0) - (_get(prev, "y1", 0.0) or 0.0)
                if gap > max((_get(prev, "size", 0.0) or 0.0), ns) * 1.15 + 4.0:
                    break

                pt = _norm(_get(prev, "text", "") or "")
                nt_raw = _get(nxt, "text", "") or ""
                nt = _norm(nt_raw)

                # Don't merge technical annotation lines or filled values into labels.
                if _looks_like_tech_annotation_line(nt):
                    break
                if _looks_like_value_line(nt):
                    break

                # If previous already looks like a complete question/label, avoid absorbing the next line.
                if pt.endswith("?") or pt.endswith(":"):
                    break

                group.append(nxt)
                j += 1

            field = _join_wrapped(group)
            field = _norm(field)

            if field and not _looks_like_nonfield_label(field, raw=field):
                if _is_group_header_for_checklist(group[0], lines, w, h, content_x_max):
                    pass
                else:
                    key = (form_name or "", field, page_1based)
                    if key not in seen:
                        records.append({"form_name": form_name or "", "field_name": field, "page": page_1based})
                        seen.add(key)

            i = j

    records.sort(key=lambda r: (r["page"], r["form_name"], r["field_name"]))
    return records


def extract(pages):
    out = []
    seen = set()
    current_form = ""

    def _add(form_name: str, field_name: str, page_1based: int):
        fn = _norm(form_name or "")
        fld = _norm(field_name or "")
        if not fld:
            return
        if _looks_like_nonfield_label(fld, raw=fld):
            return
        key = (fn, fld, page_1based)
        if key in seen:
            return
        out.append({"form_name": fn, "field_name": fld, "page": page_1based})
        seen.add(key)

    for page_idx0, lines in pages:
        if not lines:
            continue
        w, h = _page_dims(lines)
        page_1based = page_idx0 + 1

        title = _find_form_title(lines, w, h)
        if title:
            current_form = title

        # Coded/Decode table pages: treat the form title as the field label.
        if _is_codelist_page(lines, w, h):
            field_title = title or _find_form_title(lines, w, h)
            if field_title and _looks_like_title_candidate(field_title, raw=field_title):
                form_name = current_form or field_title
                _add(form_name, field_title, page_1based)
            continue

        # Metadata-only pages: use the Description text as the field label (human-readable).
        if _is_metadata_only_page(lines, w, h):
            desc = _extract_description_field(lines, w, h)
            if desc:
                _add(current_form, desc, page_1based)
            continue

        # Main extraction: run on all pages (no whole-page skip), excluding right annotation column dynamically.
        content_x_max = _compute_right_annotation_boundary(lines, w, h)

        for r in _extract_fields_content(
            lines=lines,
            w=w,
            h=h,
            form_name=current_form,
            page_1based=page_1based,
            content_x_max=content_x_max,
        ):
            _add(r.get("form_name", ""), r.get("field_name", ""), page_1based)

    return out
```
