import re
import statistics


_RE_ROW = re.compile(r"^\s*Row\s*\d+\s*$", re.IGNORECASE)


def _norm(s: str) -> str:
    return " ".join((s or "").split()).strip()


def _is_bracketed(s: str) -> bool:
    s = (s or "").strip()
    return len(s) >= 2 and s[0] == "[" and s[-1] == "]"


def _is_row_line(s: str) -> bool:
    return bool(_RE_ROW.match(s or ""))


def _has_letter(s: str) -> bool:
    s = s or ""
    for ch in s:
        if ch.isalpha():
            return True
    return False


def _is_code_line_text(t: str) -> bool:
    t = (t or "").strip()
    if not _is_bracketed(t):
        return False
    u = t.upper()
    # Keep true "field code" lines; ignore technical annotations used as metadata.
    if u.startswith("[TYPE:") or u.startswith("[VISIBILITY:") or u.startswith("[READ-ONLY"):
        return False
    return True


def _page_xmax(lines) -> float:
    xm = 0.0
    for ln in lines:
        if ln.x1 > xm:
            xm = ln.x1
    return xm if xm > 0 else 600.0


def _page_median_size(lines) -> float:
    sizes = [ln.size for ln in lines if getattr(ln, "text", "").strip()]
    if not sizes:
        return 0.0
    return float(statistics.median(sizes))


def _has_red_markers(lines) -> bool:
    for ln in lines:
        if ln.non_black and (ln.text.startswith("[") or "TYPE:" in ln.text or "Read-only field" in ln.text):
            return True
    return False


def _detect_form_title(lines, mid_x) -> str:
    # Prominent header near top-left, usually blue and larger font.
    cand = []
    for ln in lines:
        t = (ln.text or "").strip()
        if not t or _is_bracketed(t):
            continue
        if ln.y0 > 120:
            continue
        if ln.x0 > mid_x * 0.9:
            continue
        if ln.size < 12.0:
            continue
        if not (ln.non_black or ln.bold):
            continue
        if _is_row_line(t):
            continue
        if not _has_letter(t):
            continue
        cand.append(ln)

    if not cand:
        return ""
    cand.sort(key=lambda l: (-l.size, l.y0, l.x0))
    return _norm(cand[0].text)


def _find_label_block_above(lines, y_anchor, mid_x, median_size):
    # Find candidate left-column label lines above anchor.
    left_max = max(120.0, mid_x - 30.0)
    candidates = []
    for i, ln in enumerate(lines):
        t = (ln.text or "").strip()
        if not t or ln.non_black or _is_bracketed(t):
            continue
        if ln.x0 > left_max:
            continue
        if ln.y0 > y_anchor + 6:
            continue
        if ln.y0 < y_anchor - 140:
            continue
        if _is_row_line(t):
            continue
        # Avoid very tiny footer-ish text when page has a clear median size.
        if median_size and ln.size < max(5.5, median_size - 3.5):
            continue
        candidates.append(i)

    if not candidates:
        return []

    # Prefer nearest bold/question-ish line; otherwise nearest non-row line.
    def score_idx(idx: int) -> float:
        ln = lines[idx]
        t = (ln.text or "").strip()
        dist = max(0.0, y_anchor - ln.y0)
        sc = 0.0
        if ln.bold:
            sc += 3.0
        if t.endswith("?"):
            sc += 2.0
        if t.endswith(":"):
            sc += 1.0
        if 6 <= len(t) <= 140:
            sc += 1.0
        if t and t[0].isupper():
            sc += 0.5
        sc -= dist / 60.0  # closer is better
        # Penalize likely mid-paragraph continuation sentences
        if len(t) > 160 and (t[:1].islower() or (not ln.bold and not t.endswith("?"))):
            sc -= 2.0
        return sc

    base = max(candidates, key=score_idx)

    # Grow block around base using tight vertical spacing and similar left alignment.
    block = [base]
    bx = lines[base].x0

    j = base - 1
    while j >= 0:
        ln = lines[j]
        t = (ln.text or "").strip()
        if not t or ln.non_black or _is_bracketed(t) or _is_row_line(t):
            break
        if ln.x0 > left_max or abs(ln.x0 - bx) > 30:
            break
        if lines[j + 1].y0 - ln.y0 > 16:
            break
        if median_size and ln.size < max(5.5, median_size - 3.5):
            break
        block.append(j)
        j -= 1

    block.sort()
    k = base + 1
    while k < len(lines):
        ln = lines[k]
        t = (ln.text or "").strip()
        if not t or ln.non_black or _is_bracketed(t) or _is_row_line(t):
            break
        if ln.x0 > left_max or abs(ln.x0 - bx) > 30:
            break
        if ln.y0 > y_anchor - 1:
            break
        if ln.y0 - lines[k - 1].y0 > 16:
            break
        if median_size and ln.size < max(5.5, median_size - 3.5):
            break
        block.append(k)
        k += 1

    # If there's any bold in block, keep only bold (common pattern: bold question + non-bold explanation).
    if any(lines[i].bold for i in block):
        block = [i for i in block if lines[i].bold and not _is_row_line((lines[i].text or "").strip())]

    return block


def _find_label_block_below(lines, y_anchor, mid_x, median_size):
    # Some layouts place red codes above the visible label/options (e.g. repeating table rows).
    left_max = max(120.0, mid_x - 30.0)
    candidates = []
    for i, ln in enumerate(lines):
        t = (ln.text or "").strip()
        if not t or ln.non_black or _is_bracketed(t):
            continue
        if ln.x0 > left_max:
            continue
        if ln.y0 < y_anchor - 2:
            continue
        if ln.y0 > y_anchor + 180:
            continue
        if _is_row_line(t):
            continue
        if median_size and ln.size < max(5.5, median_size - 3.5):
            continue
        # Avoid grabbing small continuation sentences as "labels"
        if len(t) > 200 and not ln.bold and not t.endswith((":","?")):
            continue
        candidates.append(i)

    if not candidates:
        return []

    def score_idx(idx: int) -> float:
        ln = lines[idx]
        t = (ln.text or "").strip()
        dist = max(0.0, ln.y0 - y_anchor)
        sc = 0.0
        if ln.bold:
            sc += 2.0
        if t.endswith("?"):
            sc += 1.5
        if t.endswith(":"):
            sc += 0.7
        if 3 <= len(t) <= 140:
            sc += 1.0
        if t and t[0].isupper():
            sc += 0.5
        # Prefer labels not too far below the code anchor
        sc -= dist / 45.0
        return sc

    base = max(candidates, key=score_idx)

    block = [base]
    bx = lines[base].x0

    j = base - 1
    while j >= 0:
        ln = lines[j]
        t = (ln.text or "").strip()
        if not t or ln.non_black or _is_bracketed(t) or _is_row_line(t):
            break
        if ln.x0 > left_max or abs(ln.x0 - bx) > 30:
            break
        if lines[j + 1].y0 - ln.y0 > 16:
            break
        if ln.y0 < y_anchor - 2:
            break
        if median_size and ln.size < max(5.5, median_size - 3.5):
            break
        block.append(j)
        j -= 1

    block.sort()
    k = base + 1
    while k < len(lines):
        ln = lines[k]
        t = (ln.text or "").strip()
        if not t or ln.non_black or _is_bracketed(t) or _is_row_line(t):
            break
        if ln.x0 > left_max or abs(ln.x0 - bx) > 30:
            break
        if ln.y0 > y_anchor + 190:
            break
        if ln.y0 - lines[k - 1].y0 > 16:
            break
        if median_size and ln.size < max(5.5, median_size - 3.5):
            break
        block.append(k)
        k += 1

    if any(lines[i].bold for i in block):
        block = [i for i in block if lines[i].bold and not _is_row_line((lines[i].text or "").strip())]

    return block


def _is_read_only_near(lines, y_anchor, x_anchor) -> bool:
    # Template marker; used to skip true non-entry fields.
    for ln in lines:
        if not ln.non_black:
            continue
        t = (ln.text or "").strip()
        if "Read-only field" in t and (y_anchor - 120) <= ln.y0 <= (y_anchor + 60):
            if abs(ln.x0 - x_anchor) <= 90:
                return True
    return False


def _group_has_editable_anchor(lines, group) -> bool:
    # If at least one code anchor isn't paired with a nearby "Read-only field" marker
    # at a similar x-position, treat the group as a data-entry field.
    for (_i, y, x) in group:
        if not _is_read_only_near(lines, y, x):
            return True
    return False


def _extract_fields_from_page(lines, page_1based, form_name):
    xmax = _page_xmax(lines)
    mid = xmax * 0.5
    med_size = _page_median_size(lines)

    # Collect red code anchors (not TYPE/VISIBILITY/etc).
    anchors = []
    for i, ln in enumerate(lines):
        if ln.non_black and _is_code_line_text(ln.text):
            anchors.append((i, ln.y0, ln.x0))
    if not anchors:
        return []

    anchors.sort(key=lambda t: (t[1], t[2], t[0]))

    # Group anchors by y (multi-column repeated code lines for same question).
    groups = []
    cur = []
    for a in anchors:
        if not cur:
            cur = [a]
            continue
        if abs(a[1] - cur[-1][1]) <= 3.0:
            cur.append(a)
        else:
            groups.append(cur)
            cur = [a]
    if cur:
        groups.append(cur)

    out = []
    seen = set()

    for g in groups:
        if not _group_has_editable_anchor(lines, g):
            continue

        y = float(statistics.median([t[1] for t in g]))

        block = _find_label_block_above(lines, y, mid, med_size)
        if not block:
            block = _find_label_block_below(lines, y, mid, med_size)
        if not block:
            continue

        label = _norm(" ".join((lines[i].text or "").strip() for i in block))
        if not label:
            continue
        if _is_row_line(label):
            continue
        if not _has_letter(label) and not any(p in label for p in ("?", ":")):
            continue

        key = (form_name or "", label)
        if key in seen:
            continue
        seen.add(key)
        out.append({"form_name": form_name or "", "field_name": label, "page": page_1based})

    return out


def extract(pages):
    results = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        xmax = _page_xmax(lines)
        mid = xmax * 0.5

        title = _detect_form_title(lines, mid)
        has_markers = _has_red_markers(lines)

        # Use page title if present, but only "commit" it to carry-forward when the page looks like a form page.
        effective_form = title or current_form

        page_fields = _extract_fields_from_page(lines, page_idx0 + 1, effective_form)

        if title and (has_markers or page_fields):
            current_form = title

        results.extend(page_fields)

    return results
