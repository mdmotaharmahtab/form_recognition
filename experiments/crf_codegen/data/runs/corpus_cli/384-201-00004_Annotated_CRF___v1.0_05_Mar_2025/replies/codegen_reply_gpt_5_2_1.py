```python
# Observed layouts: (1) an approval form with large centered title and bold left labels,
# (2) many “annotated CRF” pages where true field labels live in a left black column
#     and entry widgets (radio “O …” or bracketed underscore boxes) appear to the right,
# (3) schedule/lookup table pages without entry widgets (no fields).
# Strategy: carry forward the top banner/title as form_name; on pages with widgets,
# extract left-column label groups (joining wrapped lines) that have a nearby widget.

import re
import statistics
from typing import List, Tuple, Dict, Optional


_RX_PROTOCOL = re.compile(r"^\d{2,6}-\d{2,6}-\d{4,8}$")
_RX_URL = re.compile(r"(?i)\bhttps?://\S+\b")
_RX_WIDGET_RADIO = re.compile(r"^\s*[Oo]\s+\S")
_RX_WIDGET_BOX = re.compile(r"[\[_][\s\|\._-]*[_\|]{2,}[\s\|\._-]*[\]_]")
_RX_UNDERSCORE_LINE = re.compile(r"^_{10,}$")


def _norm_space(s: str) -> str:
    return " ".join(s.split())


def _is_protocol_number(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 40:
        return False
    if _RX_PROTOCOL.match(t):
        return True
    # common variant: "384-201-00004" or similar; allow extra hyphens
    if all(ch.isdigit() or ch == "-" for ch in t) and sum(ch.isdigit() for ch in t) >= 8 and "-" in t:
        return True
    return False


def _is_junk_headerish(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if _RX_URL.search(t):
        return True
    # page furniture often includes separated letters "P a g e"
    if len(t) <= 30 and sum(ch.isalpha() for ch in t) >= 3 and " " in t and t.replace(" ", "").isalpha():
        return True
    return False


def _count_letters(text: str) -> int:
    # language-agnostic: any unicode letter
    return sum(1 for ch in text if ch.isalpha())


def _looks_like_code_bracket(text: str) -> bool:
    t = text.strip()
    return len(t) >= 3 and t[0] == "[" and t[-1] == "]"


def _looks_like_widget(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if _RX_WIDGET_RADIO.match(t):
        return True
    if _RX_WIDGET_BOX.search(t):
        return True
    # plain underscore fill line
    if _RX_UNDERSCORE_LINE.match(t):
        return True
    # dense underscores anywhere (common for signature lines)
    if t.count("_") >= 10 and (len(t) >= 12):
        return True
    return False


def _page_left_xmax(lines) -> float:
    # tolerant left column bound: based on smallest x0 cluster, but capped reasonably
    xs = [ln.x0 for ln in lines if ln.text and not _is_junk_headerish(ln.text)]
    if not xs:
        return 140.0
    xs_sorted = sorted(xs)
    n = len(xs_sorted)
    q = xs_sorted[max(0, min(n - 1, int(n * 0.15)))]
    mn = xs_sorted[0]
    # allow wider on pages where left column shifts; keep safe from mid-page columns
    return min(200.0, max(120.0, mn + 120.0, q + 90.0))


def _find_page_title(lines) -> Optional[str]:
    # choose prominent title-like text near top, ignoring protocol number and right-margin tech snippets
    top = [ln for ln in lines if ln.text and ln.y0 < 95 and ln.x0 < 560 and not _RX_URL.search(ln.text)]
    if not top:
        return None

    def score(ln) -> float:
        t = ln.text.strip()
        if _is_protocol_number(t):
            return -1e6
        if _is_junk_headerish(t):
            return -1e6
        s = float(ln.size)
        if ln.bold:
            s += 2.0
        if ln.non_black:
            s += 1.0
        # prefer left-ish titles; avoid far-right labels like "Origin: ..."
        s -= 0.004 * float(ln.x0)
        # very short tokens are rarely form titles
        if len(t) <= 2:
            s -= 3.0
        return s

    best = max(top, key=score)
    if score(best) < 0:
        return None

    base_x = best.x0
    base_y = best.y0
    base_sz = best.size

    # join contiguous title lines (same band) to handle wrapped titles
    parts = [best.text.strip()]
    for ln in top:
        if ln is best:
            continue
        if abs(ln.x0 - base_x) <= 40 and 0 <= (ln.y0 - base_y) <= 18 and abs(ln.size - base_sz) <= 2.0:
            t = ln.text.strip()
            if t and not _is_protocol_number(t) and not _is_junk_headerish(t):
                parts.append(t)

    title = _norm_space(" ".join(parts))
    if not title or _is_protocol_number(title) or _is_junk_headerish(title):
        return None
    return title


def _extract_approval_fields(lines, form_name: str, page_1based: int) -> List[Dict[str, object]]:
    out = []
    seen = set()

    # bold left labels
    for ln in lines:
        t = ln.text.strip()
        if not t:
            continue
        if ln.y0 < 110 or ln.y0 > 740:
            continue
        if ln.x0 > 180:
            continue
        if ln.bold and ln.size >= 13 and _count_letters(t) >= 2 and not _is_protocol_number(t):
            key = (form_name, _norm_space(t))
            if key not in seen:
                seen.add(key)
                out.append({"form_name": form_name, "field_name": key[1], "page": page_1based})

    # signature/approval underscore lines: use the immediately following descriptor lines as labels
    underscore_lines = [ln for ln in lines if ln.text and _looks_like_widget(ln.text) and ln.text.strip().count("_") >= 20]
    underscore_lines.sort(key=lambda z: (z.y0, z.x0))
    for ul in underscore_lines:
        # find next 1-2 textual lines near same x, shortly below
        cand = []
        for ln in lines:
            if not ln.text:
                continue
            if ln.y0 <= ul.y0:
                continue
            if ln.y0 - ul.y0 > 35:
                continue
            if abs(ln.x0 - ul.x0) <= 20 and not _looks_like_widget(ln.text):
                txt = ln.text.strip()
                if txt:
                    cand.append((ln.y0, txt))
        cand.sort()
        if cand:
            label = _norm_space(" ".join(txt for _, txt in cand[:2]))
            if _count_letters(label) >= 2 and not _is_protocol_number(label):
                key = (form_name, label)
                if key not in seen:
                    seen.add(key)
                    out.append({"form_name": form_name, "field_name": label, "page": page_1based})

    return out


def _group_wrapped_label_lines(label_lines, widget_lines, join_y_mult: float = 1.6):
    # label_lines are already filtered left-column candidates, sorted by y then x
    groups = []
    if not label_lines:
        return groups

    # quick y lookup for widgets
    wy = [w.y0 for w in widget_lines]
    wy.sort()

    def widget_between(y0: float, y1: float) -> bool:
        # any widget y strictly between
        # bisect without importing: linear is fine (page sizes are small), but keep it efficient
        for y in wy:
            if y <= y0:
                continue
            if y >= y1:
                break
            return True
        return False

    cur = [label_lines[0]]
    for ln in label_lines[1:]:
        prev = cur[-1]
        ygap = ln.y0 - prev.y0
        same_x = abs(ln.x0 - prev.x0) <= 14
        size_ok = abs(ln.size - prev.size) <= 1.2
        join_gap = join_y_mult * max(6.0, float(prev.size))
        if same_x and size_ok and 0 < ygap <= join_gap and not widget_between(prev.y0 + 0.1, ln.y0 - 0.1):
            cur.append(ln)
        else:
            groups.append(cur)
            cur = [ln]
    groups.append(cur)
    return groups


def _join_group_text(group) -> str:
    parts = [ln.text.strip() for ln in group if ln.text and ln.text.strip()]
    if not parts:
        return ""
    out = parts[0]
    for nxt in parts[1:]:
        if out.endswith("-") and nxt and not nxt.startswith(" "):
            out = out[:-1] + nxt
        else:
            out = out + " " + nxt
    return _norm_space(out)


def _extract_annotated_like_fields(lines, form_name: str, page_1based: int) -> List[Dict[str, object]]:
    left_xmax = _page_left_xmax(lines)

    widget_lines = [ln for ln in lines if ln.text and _looks_like_widget(ln.text) and ln.x0 >= (left_xmax + 40)]
    if not widget_lines:
        return []

    # candidate left labels: black, left column, mid-size, not bracketed codes
    left_lines = []
    for ln in lines:
        if not ln.text:
            continue
        t = ln.text.strip()
        if not t:
            continue
        if ln.x0 > left_xmax:
            continue
        if ln.non_black:
            continue
        if ln.y0 < 55 or ln.y0 > 770:
            continue
        if _looks_like_code_bracket(t):
            continue
        if _is_protocol_number(t) or _is_junk_headerish(t):
            continue
        # exclude pure widget-ish underscore lines from label side
        if _looks_like_widget(t) and t.count("_") >= 10:
            continue
        # mid label sizes in samples cluster around ~7.5; allow some drift
        if not (6.0 <= float(ln.size) <= 9.2):
            continue
        left_lines.append(ln)

    if not left_lines:
        return []

    # estimate typical label size from left column candidates
    sizes = [float(ln.size) for ln in left_lines]
    try:
        med = statistics.median(sizes)
    except Exception:
        med = 7.5

    # tighten around the typical label size to avoid grabbing narrative microtext
    label_lines = []
    for ln in left_lines:
        if abs(float(ln.size) - med) <= 1.2:
            label_lines.append(ln)

    label_lines.sort(key=lambda z: (z.y0, z.x0))
    widget_lines.sort(key=lambda z: (z.y0, z.x0))

    groups = _group_wrapped_label_lines(label_lines, widget_lines)

    # accept groups that have a nearby widget to the right
    out = []
    seen = set()

    for g in groups:
        gy0 = g[0].y0
        gy_last = g[-1].y0
        txt = _join_group_text(g)
        if not txt:
            continue
        if _count_letters(txt) < 2:
            continue

        # find a widget close in vertical band
        has_near_widget = False
        for w in widget_lines:
            dy = w.y0 - gy0
            if dy < -6:
                continue
            if dy > 65:
                break
            # also allow widgets aligned to any wrapped line
            if w.y0 >= gy0 - 6 and w.y0 <= gy_last + 75:
                has_near_widget = True
                break

        if not has_near_widget:
            continue

        key = (form_name, txt)
        if key in seen:
            continue
        seen.add(key)
        out.append({"form_name": form_name, "field_name": txt, "page": page_1based})

    return out


def _looks_like_approval_page(lines) -> bool:
    # large bold title near top is a strong structural signature
    for ln in lines:
        if not ln.text:
            continue
        if ln.y0 < 250 and ln.bold and ln.size >= 18 and ln.x0 < 420 and _count_letters(ln.text) >= 4:
            return True
    return False


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    current_form = ""

    for page_idx0, lines in pages:
        page_1based = page_idx0 + 1

        title = _find_page_title(lines)
        if title:
            current_form = title

        form_name = current_form or ""

        if _looks_like_approval_page(lines):
            recs = _extract_approval_fields(lines, form_name, page_1based)
            records.extend(recs)
            continue

        recs = _extract_annotated_like_fields(lines, form_name, page_1based)
        records.extend(recs)

    return records
```
