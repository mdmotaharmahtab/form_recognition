```python
import re
import unicodedata
import statistics

_WS_RE = re.compile(r"\s+")
_DAY_RE = re.compile(r"(?i)\bday\b")
_NUM_TOKEN_RE = re.compile(r"\b-?\d+\b")
_DESC_RE = re.compile(r"(?i)^description\s*:")
_MULTI_DOT_RE = re.compile(r"\.{3,}")

# "Radio/checkbox" glyphs often OCR as plain O/0
_BULLET_TOKENS = {"o", "O", "0", "○", "◯", "●", "□", "☐", "▢"}


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
        # treat as bullet only if next token looks like a label word (not punctuation)
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
    # Token-level count for "O Yes O No" style
    toks = s.split(" ")
    c = sum(1 for t in toks if t in _BULLET_TOKENS)
    # Plus bracketed boxes
    c += s.count("[ ]") + s.count("( )")
    return c


def _looks_like_option_set_line(t: str) -> bool:
    s = _norm(t)
    if not s:
        return True
    if _is_mostly_box_art(s) or _is_bracketed_code(s):
        return True
    # Multiple bullets on one line => options row, not a data-entry field label
    if _count_choice_bullets(s) >= 2:
        return True
    # "Yes No" with bullets missing sometimes OCRs as "Yes   No" isn't safe to blocklist;
    # we only use structural bullet evidence.
    return False


def _looks_like_single_option_line(t: str) -> bool:
    s = _norm(t)
    if not s:
        return True
    if _starts_with_choice_bullet(s):
        # short bullet+label lines are options, not fields/titles
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
    # A dense timeline string
    if day_hits >= 2 and num_hits >= 8 and len(lt) >= 28:
        return True
    return False


def _join_wrapped(lines) -> str:
    parts = [_norm(l.text) for l in lines if _norm(l.text)]
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
        if getattr(l, "x1", 0.0) > w:
            w = l.x1
        if getattr(l, "y1", 0.0) > h:
            h = l.y1
    if w <= 0:
        w = 612.0
    if h <= 0:
        h = 792.0
    return w, h


def _text_eq(t: str, s: str) -> bool:
    return _norm(t).lower() == s.lower()


def _is_annotated_crf_page(lines, w, h) -> bool:
    right = 0
    for l in lines:
        if getattr(l, "non_black", False):
            continue
        if l.x0 > w * 0.62 and l.size <= 7.1 and l.y0 < h * 0.93:
            right += 1
            if right >= 6:
                return True
    return False


def _looks_like_title_candidate(t: str) -> bool:
    s = _norm(t)
    if not s:
        return False
    if _is_bracketed_code(s):
        return False
    if _is_mostly_box_art(s):
        return False
    if _looks_like_option_set_line(s) or _looks_like_single_option_line(s):
        return False
    st = _token_stats(s)
    if st["ends_punct"]:
        return False
    if _looks_like_rating_anchor(s):
        return False
    # exclude overwhelmingly numeric
    if st["letters"] == 0 and st["digits"] >= 2:
        return False
    return True


def _collect_title_band_candidates(lines, w, h):
    # Broader top band than before; titles can sit lower on some pages.
    y_min = h * 0.01
    y_max = h * 0.28
    x_max = w * 0.86  # allow centered titles, but still avoid far-right metadata dominance

    cands = []
    for l in lines:
        if getattr(l, "non_black", False):
            continue
        if l.y0 < y_min or l.y0 > y_max:
            continue
        if l.x0 > x_max:
            continue
        t = _norm(l.text)
        if not _looks_like_title_candidate(t):
            continue
        # avoid very short tokens ("PR") becoming form titles
        st = _token_stats(t)
        if st["word_count"] == 1 and len(t) <= 4:
            continue
        cands.append(l)
    return cands


def _join_multiline_title(seed, candidates, w, h):
    # Join with adjacent lines that look like the same title block.
    if seed is None:
        return ""
    # neighbors: similar font size, close vertical gap, near same x0 region
    x_tol = max(10.0, w * 0.03)
    y_gap = max(seed.size * 1.35, h * 0.012)
    sz_tol = max(1.4, seed.size * 0.25)

    # build list by scanning nearby lines (same top band)
    neighbors = []
    for l in candidates:
        if l is seed:
            continue
        if abs(l.x0 - seed.x0) <= x_tol and abs(l.size - seed.size) <= sz_tol:
            # above or below with small gap
            if abs(l.y0 - seed.y0) <= (y_gap * 2.0) or (0 <= (l.y0 - seed.y1) <= y_gap) or (0 <= (seed.y0 - l.y1) <= y_gap):
                neighbors.append(l)

    block = [seed]
    # include at most one line above and one below for stability
    above = [l for l in neighbors if l.y1 <= seed.y0 + (seed.size * 0.3)]
    below = [l for l in neighbors if l.y0 >= seed.y0 - (seed.size * 0.3)]
    if above:
        above.sort(key=lambda l: (-l.y0, l.x0))
        block = [above[0]] + block
    if below:
        below.sort(key=lambda l: (l.y0, l.x0))
        # avoid duplicating seed
        if below[0] is not seed:
            block = block + [below[0]]

    block.sort(key=lambda l: (l.y0, l.x0))
    return _join_wrapped(block)


def _find_form_title(lines, w, h) -> str:
    cands = _collect_title_band_candidates(lines, w, h)
    if not cands:
        return ""

    # Prefer larger font and top placement; require "title-ish" text.
    best = None
    best_key = None
    for l in cands:
        t = _norm(l.text)
        st = _token_stats(t)
        has_ln = 1 if _has_letter_or_number(t) else 0
        has_two_words = 1 if st["word_count"] >= 2 else 0
        not_digit_led = 1 if not st["starts_digit"] else 0
        low_digit_ratio = 1 if (len(t) == 0 or (st["digits"] / max(1, len(t)) <= 0.18)) else 0
        not_all_caps_micro = 1
        if st["all_caps"] and len(t) <= 6:
            not_all_caps_micro = 0
        key = (
            has_ln,
            has_two_words,
            not_digit_led,
            low_digit_ratio,
            not_all_caps_micro,
            l.size,
            -l.y0,
            -(-l.x0),
            len(t),
        )
        if best is None or key > best_key:
            best = l
            best_key = key

    title = _join_multiline_title(best, cands, w, h)
    title = _norm(title)
    # final guard: don't accept option-y lines as title
    if not title or not _looks_like_title_candidate(title):
        return ""
    st = _token_stats(title)
    if st["word_count"] == 1 and len(title) <= 5:
        return ""
    return title


def _is_codelist_page(lines, w, h) -> bool:
    y_min = h * 0.05
    y_max = h * 0.14
    coded = []
    decode = []
    for l in lines:
        if l.y0 < y_min or l.y0 > y_max:
            continue
        t = _norm(l.text)
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
            if abs(c.y0 - d.y0) <= max(4.0, (c.size + d.size) * 0.4) and (d.x0 - c.x0) > w * 0.25:
                return True
    return False


def _is_metadata_only_page(lines, w, h) -> bool:
    right_x = w * 0.62
    y_min = h * 0.02
    y_max = h * 0.20

    keys = 0
    for l in lines:
        if l.x0 <= right_x:
            continue
        if l.y0 < y_min or l.y0 > y_max:
            continue
        if getattr(l, "non_black", False):
            continue
        t = _norm(l.text).lower()
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
    right_x = w * 0.62
    y_min = h * 0.02
    y_max = h * 0.25

    candidates = []
    for l in lines:
        if l.x0 <= right_x:
            continue
        if l.y0 < y_min or l.y0 > y_max:
            continue
        if getattr(l, "non_black", False):
            continue
        t = _norm(l.text)
        if not t:
            continue
        if _DESC_RE.match(t):
            candidates.append(l)

    if not candidates:
        return ""

    candidates.sort(key=lambda l: (l.y0, l.x0))
    first = candidates[0]

    group = [first]
    x0 = first.x0
    base_size = first.size
    cur = first

    right_lines = [
        l
        for l in lines
        if (l.x0 > right_x and not getattr(l, "non_black", False) and y_min <= l.y0 <= h * 0.60)
    ]
    right_lines.sort(key=lambda l: (l.y0, l.x0))

    start_idx = None
    for idx, rl in enumerate(right_lines):
        if rl is first:
            start_idx = idx
            break

    if start_idx is not None:
        for nxt in right_lines[start_idx + 1 :]:
            if abs(nxt.x0 - x0) > max(10.0, w * 0.02):
                break
            if base_size > 0 and abs(nxt.size - base_size) > base_size * 0.55:
                break
            gap = nxt.y0 - cur.y1
            if gap > max(cur.size, nxt.size) * 1.35 + 6.0:
                break
            nt = _norm(nxt.text)
            if re.match(r"(?i)^(short name|mandatory\?|disallow future date)\b", nt):
                break
            group.append(nxt)
            cur = nxt

    joined = _join_wrapped(group)
    joined = _DESC_RE.sub("", joined).strip()
    return _norm(joined)


def _cluster_x0(lines, tol):
    xs = sorted(l.x0 for l in lines)
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


def _is_header_row_member(l, peers, w, h):
    # Exclude wide header rows (many labels on the same y).
    y_tol = max(4.0, l.size * 0.85, h * 0.006)
    row = []
    for p in peers:
        if abs(p.y0 - l.y0) <= y_tol and abs(p.size - l.size) <= max(1.8, l.size * 0.28):
            row.append(p)
    if len(row) < 4:
        return False
    xs = sorted(p.x0 for p in row)
    spread = xs[-1] - xs[0] if xs else 0.0
    if spread < w * 0.38:
        return False
    # Extra signal: several very short labels on same row (table headings like PR/QRS/QT...)
    short = 0
    for p in row:
        t = _norm(p.text)
        if t and len(t) <= 5 and not _looks_like_option_set_line(t) and not _is_mostly_box_art(t):
            short += 1
    if short >= 3:
        return True
    return l.y0 < 0.55 * max(1.0, getattr(l, "y1", l.y0 + 1.0))


def _is_group_header_for_checklist(label_line, lines, w, h, content_x_max):
    # If a label is followed by multiple indented checkbox-like option lines, it's a group heading.
    y_start = label_line.y1
    y_end = min(h * 0.92, label_line.y1 + max(label_line.size * 7.0, h * 0.10))
    x_min = label_line.x0 + max(6.0, w * 0.02)

    hits = 0
    for l in lines:
        if getattr(l, "non_black", False):
            continue
        if l.x0 <= x_min or l.x0 >= content_x_max:
            continue
        if l.y0 < y_start or l.y0 > y_end:
            continue
        t = _norm(l.text)
        if not t or _is_bracketed_code(t):
            continue
        if _looks_like_option_set_line(t) or _looks_like_single_option_line(t):
            hits += 1
            if hits >= 2:
                return True
        if _is_mostly_box_art(t):
            hits += 1
            if hits >= 2:
                return True
    return False


def _looks_like_nonfield_label(t: str) -> bool:
    s = _norm(t)
    if not s:
        return True
    if _is_bracketed_code(s) or _is_mostly_box_art(s):
        return True
    if _looks_like_rating_anchor(s):
        return True
    if _looks_like_option_set_line(s) or _looks_like_single_option_line(s):
        return True
    if _looks_like_visit_timeline_line(s):
        return True
    # very "code-ish" tiny all-caps token (but keep longer acronyms and normal text)
    st = _token_stats(s)
    if st["word_count"] == 1 and st["all_caps"] and 1 <= len(s) <= 3:
        return True
    return False


def _extract_fields_content(lines, w, h, form_name, page_1based, content_x_max):
    y_low = h * 0.07
    y_high = h * 0.93

    prelim = []
    for l in lines:
        if l.y0 < y_low or l.y0 > y_high:
            continue
        if l.x0 >= content_x_max:
            continue
        if getattr(l, "non_black", False):
            continue
        t = _norm(l.text)
        if not t:
            continue
        if _looks_like_nonfield_label(t):
            continue
        prelim.append(l)

    if not prelim:
        return []

    sizes = [l.size for l in prelim if getattr(l, "size", 0.0) > 0]
    med = statistics.median(sizes) if sizes else 0.0

    cand = []
    for l in prelim:
        if med > 0:
            if l.size < med * 0.60 or l.size > med * 1.90:
                continue
        cand.append(l)

    if not cand:
        return []

    # Remove wide header-row members (e.g., schedule table column headers).
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
        a = _nearest_anchor(l.x0, anchors, tol=tol)
        key = a if a is not None else l.x0
        by_col.setdefault(key, []).append(l)

    records = []
    seen = set()

    for _, items in by_col.items():
        items.sort(key=lambda l: (l.y0, l.x0))

        i = 0
        while i < len(items):
            group = [items[i]]
            x0 = items[i].x0
            base_size = items[i].size
            j = i + 1
            while j < len(items):
                prev = group[-1]
                nxt = items[j]
                if abs(nxt.x0 - x0) > tol:
                    break
                if base_size > 0 and abs(nxt.size - base_size) > base_size * 0.42:
                    break
                gap = nxt.y0 - prev.y1
                if gap > max(prev.size, nxt.size) * 1.15 + 4.0:
                    break
                group.append(nxt)
                j += 1

            field = _join_wrapped(group)
            field = _norm(field)

            if field and not _looks_like_nonfield_label(field):
                # Exclude checklist/group headers (not actual entry fields).
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
        if _looks_like_nonfield_label(fld):
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

        # Update form title whenever a plausible title is present (avoid option lines / tiny tokens).
        title = _find_form_title(lines, w, h)
        if title and _looks_like_title_candidate(title):
            current_form = title

        content_x_max = w * 0.62

        annotated = _is_annotated_crf_page(lines, w, h)

        # Coded/Decode table pages: treat the top title as the field label.
        if _is_codelist_page(lines, w, h):
            field_title = title or _find_form_title(lines, w, h)
            if field_title and _looks_like_title_candidate(field_title):
                form_name = current_form or field_title
                _add(form_name, field_title, page_1based)
            continue

        # Metadata-only pages: use "Description: ..." as the field label.
        if _is_metadata_only_page(lines, w, h):
            desc = _extract_description_field(lines, w, h)
            if desc:
                _add(current_form, desc, page_1based)
            continue

        # Main extraction: annotated pages (and only those), with stronger structural exclusions.
        if annotated:
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
