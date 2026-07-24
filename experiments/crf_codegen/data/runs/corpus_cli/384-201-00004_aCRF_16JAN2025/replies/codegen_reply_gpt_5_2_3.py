import re
import unicodedata
import statistics

_WS_RE = re.compile(r"\s+")
_DAY_NUM_RE = re.compile(r"(?i)\bday\b")
_NUM_TOKEN_RE = re.compile(r"\b-?\d+\b")
_DESC_RE = re.compile(r"(?i)^description\s*:")


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def _has_letter_or_number(s: str) -> bool:
    for ch in s:
        cat = unicodedata.category(ch)
        if cat and (cat[0] == "L" or cat[0] == "N"):
            return True
    return False


def _is_bracketed_code(t: str) -> bool:
    t = t.strip()
    return len(t) >= 2 and t[0] == "[" and t[-1] == "]"


def _is_mostly_box_art(t: str) -> bool:
    s = (t or "").strip()
    if not s:
        return True
    # Typical entry widgets: "[____]", "[ ]", "____", lots of underscores/pipes/brackets/box glyphs.
    if any(c in s for c in ("_", "|", "[", "]", "□", "☐", "▢")):
        box_chars = set("_|[](){}<>-–—·. :;/\\+*=,")
        keep = 0
        for ch in s:
            if ch in box_chars or ch.isdigit() or ch.isspace() or ch in ("□", "☐", "▢"):
                keep += 1
        return keep / max(1, len(s)) > 0.65
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
    return _norm(out)


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
    # Pattern: leading index/grade + short all-caps label (e.g., "0 MILD", "1 SEVERE")
    if st["starts_digit"] and st["word_count"] <= 2 and st["letters"] > 0 and st["all_caps"]:
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
    st = _token_stats(s)
    if st["ends_punct"]:
        return False
    if _looks_like_rating_anchor(s):
        return False
    # Exclude things that are overwhelmingly numeric (visit timelines)
    if st["letters"] == 0 and st["digits"] >= 2:
        return False
    return True


def _find_form_title(lines, w, h) -> str:
    # Top band; left/mid content only (exclude right metadata column).
    y_min = h * 0.01
    y_max = h * 0.18
    x_max = w * 0.66

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
        cands.append(l)

    if not cands:
        return ""

    # Score: prefer human-ish titles, discourage digit-led short anchors, prefer larger font.
    best = None
    best_key = None
    for l in cands:
        t = _norm(l.text)
        st = _token_stats(t)
        has_ln = 1 if _has_letter_or_number(t) else 0
        has_two_words = 1 if st["word_count"] >= 2 else 0
        not_digit_led = 1 if not st["starts_digit"] else 0
        low_digit_ratio = 1 if (len(t) == 0 or (st["digits"] / max(1, len(t)) <= 0.18)) else 0
        # Title tends to be left-ish; prefer smaller x0 slightly, and very top.
        key = (
            has_ln,
            has_two_words,
            not_digit_led,
            low_digit_ratio,
            l.size,
            -l.y0,
            -(-l.x0),  # smaller x0 wins
            len(t),
        )
        if best is None or key > best_key:
            best = l
            best_key = key

    return _norm(best.text) if best else ""


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


def _is_visit_schedule_matrix(lines, w, h) -> bool:
    # Structural: a visit timeline row with many day numbers (e.g., "Day -28 ... Day 37").
    y_min = h * 0.06
    y_max = h * 0.40
    x_max = w * 0.70

    for l in lines:
        if l.y0 < y_min or l.y0 > y_max:
            continue
        if l.x0 > x_max:
            continue
        t = _norm(l.text)
        if not t:
            continue
        lt = t.lower()
        if "day" not in lt:
            continue
        day_hits = len(_DAY_NUM_RE.findall(lt))
        num_hits = len(_NUM_TOKEN_RE.findall(lt))
        # One long timeline line is enough to classify.
        if day_hits >= 2 and num_hits >= 10 and len(lt) >= 35:
            return True

    # Alternative: many small header tokens across a single top row.
    top = []
    for l in lines:
        if l.y0 < h * 0.06 or l.y0 > h * 0.26:
            continue
        if l.x0 > x_max:
            continue
        if getattr(l, "non_black", False):
            continue
        t = _norm(l.text)
        if not t or _is_bracketed_code(t) or _is_mostly_box_art(t):
            continue
        top.append(l)

    if len(top) >= 8:
        # If many distinct x-buckets in the same band, it's likely a matrix header.
        bucket = max(1.0, w * 0.08)
        xs = {int(l.x0 / bucket) for l in top}
        if len(xs) >= 6:
            return True

    return False


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


def _is_header_row_member(l, peers, w):
    # Exclude wide header rows (many labels on the same y).
    y_tol = max(3.0, l.size * 0.65)
    row = []
    for p in peers:
        if abs(p.y0 - l.y0) <= y_tol and abs(p.size - l.size) <= max(1.5, l.size * 0.22):
            row.append(p)
    if len(row) < 4:
        return False
    # Must be spread across the page width (not just a wrapped paragraph).
    xs = sorted(p.x0 for p in row)
    spread = xs[-1] - xs[0] if xs else 0.0
    if spread < w * 0.35:
        return False
    # Header rows often sit in upper half.
    return l.y0 < 0.45 * max(1.0, getattr(l, "y1", l.y0 + 1.0))


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
        if _is_mostly_box_art(t):
            hits += 1
            if hits >= 2:
                return True
        # Some extracts put the box glyph with the option text.
        if t.startswith(("□", "☐", "▢", "[ ]", "[]")):
            hits += 1
            if hits >= 2:
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
        if _is_bracketed_code(t):
            continue
        if _is_mostly_box_art(t):
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
        if _is_header_row_member(l, cand, w):
            continue
        cand2.append(l)
    cand = cand2
    if not cand:
        return []

    # Column anchors from x0 clustering; keep top few by frequency.
    tol = max(8.0, w * 0.018)
    clusters = _cluster_x0(cand, tol=tol)
    anchors = [c[0] for c in clusters[:4]] if clusters else []

    # Assign each line to an anchor (column) when possible.
    by_col = {}
    for l in cand:
        a = _nearest_anchor(l.x0, anchors, tol=tol)
        key = a if a is not None else l.x0
        by_col.setdefault(key, []).append(l)

    records = []
    seen = set()

    for col_x, items in by_col.items():
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
            if field:
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
        if _is_bracketed_code(fld) or _is_mostly_box_art(fld):
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

        # Always try to update form title when a plausible title is present.
        title = _find_form_title(lines, w, h)
        if title and _looks_like_title_candidate(title):
            current_form = title

        content_x_max = w * 0.62

        # Structural exclusion of matrix/schedule headers (no extraction, but keep form title).
        if _is_visit_schedule_matrix(lines, w, h):
            continue

        annotated = _is_annotated_crf_page(lines, w, h)
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
            continue

        # Coded/Decode table pages: treat the top title as the field label.
        if _is_codelist_page(lines, w, h):
            field_title = title or _find_form_title(lines, w, h)
            if field_title:
                form_name = current_form or field_title
                _add(form_name, field_title, page_1based)
            continue

        # Metadata-only pages: use "Description: ..." as the field label.
        if _is_metadata_only_page(lines, w, h):
            desc = _extract_description_field(lines, w, h)
            if desc:
                _add(current_form, desc, page_1based)
            continue

    return out
