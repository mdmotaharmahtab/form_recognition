import re
import unicodedata
import statistics

_WS_RE = re.compile(r"\s+")


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
    # Typical entry widgets: "[____]", "[_|_|_]", lots of underscores/pipes/brackets.
    s = t.strip()
    if not s:
        return True
    box_chars = set("_|[](){}<>-–—·. ")
    if any(c in s for c in ("_", "|")):
        keep = 0
        for ch in s:
            if ch in box_chars or ch.isdigit():
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
        if l.x1 > w:
            w = l.x1
        if l.y1 > h:
            h = l.y1
    # Fallback to typical US Letter if something is off
    if w <= 0:
        w = 612.0
    if h <= 0:
        h = 792.0
    return w, h


def _is_annotated_crf_page(lines, w, h) -> bool:
    # Dense right metadata column: many small-size black lines around x ~ 0.7w-0.95w
    right = 0
    for l in lines:
        if l.non_black:
            continue
        if l.x0 > w * 0.62 and l.size <= 7.1 and l.y0 < h * 0.93:
            right += 1
            if right >= 6:
                return True
    return False


def _find_form_title(lines, w, h) -> str:
    # Title typically in top band, left-ish; choose the largest text in that band.
    top_band = []
    y_min = h * 0.02
    y_max = h * 0.10
    x_max = w * 0.62
    for l in lines:
        if l.y0 < y_min or l.y0 > y_max:
            continue
        if l.x0 > x_max:
            continue
        t = _norm(l.text)
        if not t:
            continue
        if _is_bracketed_code(t):
            continue
        top_band.append(l)

    if not top_band:
        return ""

    # Prefer candidates that look like human titles (letters) but fall back to any.
    best = None
    best_key = None
    for l in top_band:
        t = _norm(l.text)
        has_ln = _has_letter_or_number(t)
        # Key: has_letters, size, earlier y, earlier x
        key = (1 if has_ln else 0, l.size, -l.y0, -l.x0)
        if best is None or key > best_key:
            best = l
            best_key = key

    if not best:
        return ""
    return _norm(best.text)


def _extract_fields_annotated(lines, w, h, form_name, page_1based):
    # Candidate labels: black text in left column, excluding bracket codes and footer.
    left_x_max = w * 0.40
    y_low = h * 0.07
    y_high = h * 0.93

    prelim = []
    for l in lines:
        if l.y0 < y_low or l.y0 > y_high:
            continue
        if l.x0 >= left_x_max:
            continue
        if l.non_black:
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

    # Robust size window based on median of prelim sizes.
    sizes = [l.size for l in prelim]
    med = statistics.median(sizes) if sizes else 0.0

    cand = []
    for l in prelim:
        if med > 0:
            if l.size < med * 0.65 or l.size > med * 1.75:
                continue
        cand.append(l)

    cand.sort(key=lambda l: (l.y0, l.x0))

    records = []
    seen = set()

    i = 0
    while i < len(cand):
        group = [cand[i]]
        x0 = cand[i].x0
        base_size = cand[i].size
        j = i + 1
        while j < len(cand):
            prev = group[-1]
            nxt = cand[j]
            # Must stay aligned in left column and similar font size.
            if abs(nxt.x0 - x0) > max(8.0, w * 0.015):
                break
            if base_size > 0 and abs(nxt.size - base_size) > base_size * 0.40:
                break
            # Wrap proximity check.
            gap = nxt.y0 - prev.y1
            if gap > max(prev.size, nxt.size) * 1.15 + 4.0:
                break
            group.append(nxt)
            j += 1

        field = _join_wrapped(group)
        if field:
            key = (form_name or "", field, page_1based)
            if key not in seen:
                records.append({"form_name": form_name or "", "field_name": field, "page": page_1based})
                seen.add(key)

        i = j

    return records


def _text_eq(t: str, s: str) -> bool:
    return _norm(t).lower() == s.lower()


def _is_codelist_page(lines, w, h) -> bool:
    # "Coded" / "Decode" header table pages (typically no right-side metadata column).
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

    # Need plausible two-column separation
    for c in coded:
        for d in decode:
            if abs(c.y0 - d.y0) <= max(4.0, (c.size + d.size) * 0.4) and (d.x0 - c.x0) > w * 0.25:
                return True
    return False


def _is_metadata_only_page(lines, w, h) -> bool:
    # Pages that show only right-column field metadata like:
    # "Description: ...", "Short Name", "Mandatory?: ...", etc.
    right_x = w * 0.62
    y_min = h * 0.02
    y_max = h * 0.20

    keys = 0
    for l in lines:
        if l.x0 <= right_x:
            continue
        if l.y0 < y_min or l.y0 > y_max:
            continue
        if l.non_black:
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

    # Find the "Description:" line in the right column.
    candidates = []
    for l in lines:
        if l.x0 <= right_x:
            continue
        if l.y0 < y_min or l.y0 > y_max:
            continue
        if l.non_black:
            continue
        t = _norm(l.text)
        if not t:
            continue
        if re.match(r"(?i)^description\s*:", t):
            candidates.append(l)

    if not candidates:
        return ""

    candidates.sort(key=lambda l: (l.y0, l.x0))
    first = candidates[0]

    # Include wrapped continuation lines under the Description line.
    group = [first]
    x0 = first.x0
    base_size = first.size
    cur = first
    # Scan downward in reading order among right-column lines.
    right_lines = [l for l in lines if (l.x0 > right_x and not l.non_black and y_min <= l.y0 <= h * 0.60)]
    right_lines.sort(key=lambda l: (l.y0, l.x0))
    try:
        start_idx = right_lines.index(first)
    except ValueError:
        start_idx = None

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
    joined = re.sub(r"(?i)^description\s*:\s*", "", joined).strip()
    return _norm(joined)


def extract(pages):
    out = []
    current_form = ""
    seen = set()

    def _add(form_name: str, field_name: str, page_1based: int):
        fn = _norm(form_name or "")
        fld = _norm(field_name or "")
        if not fld:
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

        annotated = _is_annotated_crf_page(lines, w, h)
        if annotated:
            title = _find_form_title(lines, w, h)
            if title:
                current_form = title
            for r in _extract_fields_annotated(lines=lines, w=w, h=h, form_name=current_form, page_1based=page_1based):
                _add(r.get("form_name", ""), r.get("field_name", ""), page_1based)
            continue

        # Coded/Decode table pages: treat the top title as the field label.
        if _is_codelist_page(lines, w, h):
            field_title = _find_form_title(lines, w, h)
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
