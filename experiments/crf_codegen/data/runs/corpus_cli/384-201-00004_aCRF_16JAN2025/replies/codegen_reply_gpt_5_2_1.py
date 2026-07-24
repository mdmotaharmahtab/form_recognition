```python
# Observed layout: Most field-bearing pages use an "Annotated CRF" template with
# a form title in the top band (often white text) and a right-side metadata column.
# Field labels are black text in the left column; machine codes are bracketed like "[XYZ]".
# Strategy: detect annotated pages by dense right-column metadata; carry forward form title;
# extract left-column black label blocks, merge wrapped lines, and drop bracket-codes/options.

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
        # Avoid picking obvious tiny page chrome (study id / header codes)
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
    title = _norm(best.text)
    return title


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
                records.append(
                    {"form_name": form_name or "", "field_name": field, "page": page_1based}
                )
                seen.add(key)

        i = j

    return records


def extract(pages):
    out = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue
        w, h = _page_dims(lines)

        annotated = _is_annotated_crf_page(lines, w, h)
        if annotated:
            title = _find_form_title(lines, w, h)
            if title:
                current_form = title

            out.extend(
                _extract_fields_annotated(
                    lines=lines,
                    w=w,
                    h=h,
                    form_name=current_form,
                    page_1based=page_idx0 + 1,
                )
            )

    return out
```
