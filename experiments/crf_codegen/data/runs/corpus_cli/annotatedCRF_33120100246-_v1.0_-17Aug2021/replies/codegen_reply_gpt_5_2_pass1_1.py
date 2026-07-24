```python
# Observed layout: annotated CRF where each data-entry field is tagged by a red bracketed ID line
# (e.g., "[ABC123]") followed by red technical lines ("[TYPE: ...]", "[VISIBILITY: ...]").
# Form/section titles are usually a large colored line near the top-left; some lab pages lack it and
# instead have a small black heading plus a right-side list of choices. Strategy: find field ID tags,
# infer the nearest small black label text (wrapping across lines), carry forward the last seen title.

import re
import statistics
from collections import Counter


_RE_FIELD_ID = re.compile(r"^\[[A-Z0-9_]{2,}\]$")
_RE_SPLIT_OPEN = re.compile(r"^\[[A-Z0-9_]{2,}$")          # "[SCANNE"
_RE_SPLIT_CLOSE = re.compile(r"^[A-Z0-9_]{1,20}\]$")       # "R]"
_RE_ROW = re.compile(r"^\s*Row\s*\d+\s*$", re.IGNORECASE)
_RE_JUST_PUNCT = re.compile(r"^\W+$", re.UNICODE)


def _norm_text(s: str) -> str:
    s = s.replace("\\", "")  # CRF export often shows stray "\" markers
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    return s


def _is_field_id_text(t: str) -> bool:
    # Must be a clean bracket token without ":" or spaces; avoids "[TYPE: ...]" etc.
    return bool(_RE_FIELD_ID.match(t))


def _merge_split_bracket_ids(lines):
    # Merge cases where an ID is split across two lines like "[SCANNE" + "R]"
    out = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        t = (ln.text or "").strip()
        if ln.non_black and _RE_SPLIT_OPEN.match(t) and (":" not in t) and (" " not in t) and i + 1 < n:
            nxt = lines[i + 1]
            t2 = (nxt.text or "").strip()
            if (
                nxt.non_black
                and _RE_SPLIT_CLOSE.match(t2)
                and abs(float(nxt.size) - float(ln.size)) <= 0.6
                and abs(float(nxt.x0) - float(ln.x0)) <= 6.0
                and 0.0 <= float(nxt.y0) - float(ln.y0) <= 16.0
            ):
                merged_text = t + t2
                # create a lightweight proxy object with needed attributes
                class _L:
                    __slots__ = ("text", "x0", "y0", "x1", "y1", "size", "bold", "non_black")
                m = _L()
                m.text = merged_text
                m.x0, m.y0, m.x1, m.y1 = ln.x0, ln.y0, ln.x1, nxt.y1
                m.size, m.bold, m.non_black = ln.size, ln.bold, True
                out.append(m)
                i += 2
                continue
        out.append(ln)
        i += 1
    return out


def _page_small_font_size(lines) -> float:
    # Estimate the "label" font as the most common black size in a broad small-text band.
    sizes = []
    for ln in lines:
        if ln is None:
            continue
        if ln.non_black:
            continue
        sz = float(getattr(ln, "size", 0.0) or 0.0)
        if 6.0 <= sz <= 10.8:
            sizes.append(round(sz, 1))
    if not sizes:
        # fallback: use any size median
        allsz = [float(getattr(ln, "size", 0.0) or 0.0) for ln in lines if ln is not None]
        allsz = [s for s in allsz if s > 0]
        return float(statistics.median(allsz)) if allsz else 8.0
    c = Counter(sizes)
    # pick most frequent; break ties by smaller size (labels tend to be smallest common size)
    best = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return float(best)


def _looks_like_chrome_or_empty(text: str) -> bool:
    if not text:
        return True
    t = text.strip()
    if not t:
        return True
    if _RE_JUST_PUNCT.match(t):
        return True
    # very short numeric tokens are often page furniture
    if re.fullmatch(r"\d{1,4}", t):
        return True
    return False


def _page_colored_title(lines, small_sz: float):
    # Large colored heading near top-left (typical form name)
    cands = []
    for ln in lines:
        t = (ln.text or "").strip()
        if _looks_like_chrome_or_empty(t):
            continue
        if not ln.non_black:
            continue
        y = float(ln.y0)
        x = float(ln.x0)
        sz = float(ln.size)
        if y <= 130.0 and x <= 260.0 and sz >= max(small_sz * 1.45, small_sz + 3.5):
            # Avoid colored TOC section headers far down the page (already excluded by y<=130)
            if t.startswith("[") and t.endswith("]"):
                continue
            cands.append((sz, -y, -x, t))
    if not cands:
        return ""
    # choose largest font; then highest on page; then leftmost
    cands.sort(reverse=True)
    return _norm_text(cands[0][3])


def _page_top_black_heading(lines, small_sz: float):
    # Small black heading at very top-left used on some lab pages without colored title.
    cands = []
    for ln in lines:
        if ln.non_black:
            continue
        t = (ln.text or "").strip()
        if _looks_like_chrome_or_empty(t):
            continue
        if t.startswith("["):
            continue
        y = float(ln.y0)
        x = float(ln.x0)
        sz = float(ln.size)
        if y <= 85.0 and x <= 140.0 and abs(sz - small_sz) <= 1.2:
            cands.append((y, x, t))
    if not cands:
        return ""
    cands.sort(key=lambda a: (a[0], a[1]))
    return _norm_text(cands[0][2])


def _page_looks_like_lab_enum_list(lines, small_sz: float) -> bool:
    # Heuristic signature for families C/D/E: many medium black items in a right-side column list.
    cnt = 0
    for ln in lines:
        if ln.non_black:
            continue
        sz = float(ln.size)
        x = float(ln.x0)
        y = float(ln.y0)
        if 70.0 <= y <= 640.0 and x >= 240.0 and (small_sz + 1.0) <= sz <= (small_sz + 3.5):
            t = (ln.text or "").strip()
            if _looks_like_chrome_or_empty(t) or t.startswith("["):
                continue
            cnt += 1
    return cnt >= 5


def _label_like(ln, small_sz: float) -> bool:
    if ln.non_black:
        return False
    t = (ln.text or "").strip()
    if _looks_like_chrome_or_empty(t):
        return False
    if t.startswith("["):
        return False
    if _RE_ROW.match(t):
        return False
    sz = float(ln.size)
    if abs(sz - small_sz) > 1.25:
        return False
    return True


def _header_like(ln, small_sz: float) -> bool:
    # Column headers are black and noticeably larger than label font, often ~9-10pt.
    if ln.non_black:
        return False
    t = (ln.text or "").strip()
    if _looks_like_chrome_or_empty(t):
        return False
    if t.startswith("["):
        return False
    sz = float(ln.size)
    if not (small_sz + 0.9 <= sz <= small_sz + 5.0):
        return False
    # keep relatively short header-like text
    if len(t) > 60:
        return False
    return True


def _nearest_header(headers, code_x: float, code_y: float):
    best = None
    best_score = None
    for h in headers:
        if float(h.y0) >= code_y:
            continue
        dy = code_y - float(h.y0)
        if dy > 320.0:
            continue
        dx = abs(code_x - float(h.x0))
        score = dy * 1.0 + dx * 0.35
        if best_score is None or score < best_score:
            best_score = score
            best = (h.text or "").strip()
    return _norm_text(best) if best else ""


def _infer_field_label(lines, code_ln, small_sz: float, label_lines, left_margin_x: float):
    cy = float(code_ln.y0)
    cx = float(code_ln.x0)

    # Prefer labels above within a generous window; labels below only in a tight window (tables).
    above = []
    below = []
    for ln in label_lines:
        y = float(ln.y0)
        if y < cy and (cy - y) <= 220.0:
            above.append(ln)
        elif y >= cy and (y - cy) <= 40.0:
            below.append(ln)

    def score(candidate, is_above: bool):
        y = float(candidate.y0)
        x = float(candidate.x0)
        dy = (cy - y) if is_above else (y - cy)
        s = dy
        # bold is often the actual question line in tables
        s += 0.0 if bool(candidate.bold) else 3.0
        # prefer left-aligned label column
        s += 0.45 * max(0.0, x - left_margin_x)
        # if code is far right, don't overfit x; if code is left, prefer closeness
        if cx <= 220.0:
            s += 0.08 * abs(cx - x)
        return s

    anchor = None
    is_above = True
    if above:
        anchor = min(above, key=lambda ln: score(ln, True))
        is_above = True
    elif below:
        anchor = min(below, key=lambda ln: score(ln, False))
        is_above = False

    if anchor is None:
        # fallback: top-most label-like line near the top of the page
        top = None
        top_y = None
        for ln in label_lines:
            y = float(ln.y0)
            if y <= 110.0:
                if top_y is None or y < top_y:
                    top_y = y
                    top = ln
        anchor = top
        is_above = True

    if anchor is None:
        return ""

    # Expand around anchor through nearby label-like lines (wraps), tolerant of minor indentation.
    ax = float(anchor.x0)
    ay = float(anchor.y0)
    parts = [(ay, ax, (anchor.text or "").strip(), bool(anchor.bold))]

    # gather neighbors by scanning all label lines around anchor y
    # include contiguous lines with small y gaps and similar x (indent allowed)
    # decide direction bounds
    sorted_lbls = sorted(label_lines, key=lambda ln: (float(ln.y0), float(ln.x0)))
    # find a close index
    idx = min(range(len(sorted_lbls)), key=lambda i: abs(float(sorted_lbls[i].y0) - ay) + 0.02 * abs(float(sorted_lbls[i].x0) - ax))

    def ok_neighbor(prev_ln, ln):
        py, px = float(prev_ln.y0), float(prev_ln.x0)
        y, x = float(ln.y0), float(ln.x0)
        if (y - py) > 13.8:
            return False
        if abs(float(ln.size) - small_sz) > 1.25:
            return False
        # allow indenting, but stay in the same left label column
        if x - ax > 110.0:
            return False
        if x < left_margin_x - 5.0:
            return False
        t = (ln.text or "").strip()
        if not t or t.startswith("[") or _RE_ROW.match(t):
            return False
        return True

    # walk backward
    prev = sorted_lbls[idx]
    j = idx - 1
    while j >= 0:
        ln = sorted_lbls[j]
        if not ok_neighbor(ln, prev):
            break
        # don't include if it is far below/above the code in the "below-label" case
        if not is_above and float(ln.y0) < cy - 10.0:
            break
        parts.append((float(ln.y0), float(ln.x0), (ln.text or "").strip(), bool(ln.bold)))
        prev = ln
        j -= 1

    # walk forward
    prev = sorted_lbls[idx]
    j = idx + 1
    while j < len(sorted_lbls):
        ln = sorted_lbls[j]
        if not ok_neighbor(prev, ln):
            break
        # for typical fields, avoid swallowing the next field label far below the code
        if is_above and float(ln.y0) > cy + 25.0:
            break
        parts.append((float(ln.y0), float(ln.x0), (ln.text or "").strip(), bool(ln.bold)))
        prev = ln
        j += 1

    parts.sort(key=lambda p: (p[0], p[1]))
    text = _norm_text(" ".join(p[2] for p in parts))
    return text


def extract(pages):
    out = []
    current_form = ""

    for page_index, lines in pages:
        if not lines:
            continue

        lines2 = _merge_split_bracket_ids(lines)
        small_sz = _page_small_font_size(lines2)

        # Collect field ID tags
        code_lines = []
        for ln in lines2:
            if not ln.non_black:
                continue
            t = (ln.text or "").strip()
            if _is_field_id_text(t):
                code_lines.append(ln)

        if not code_lines:
            # No annotated field IDs: treat as non-field page (TOC/cover/etc.)
            continue

        # Update form name from colored title when present
        title = _page_colored_title(lines2, small_sz)
        if title:
            current_form = title
        else:
            # Only use top black heading as a form name on lab-enumeration style pages,
            # or when we otherwise have no form context yet.
            heading = _page_top_black_heading(lines2, small_sz)
            if heading and (not current_form or _page_looks_like_lab_enum_list(lines2, small_sz)):
                current_form = heading

        form_name = _norm_text(current_form)

        # Build label candidates and header candidates for this page
        label_lines = [ln for ln in lines2 if _label_like(ln, small_sz)]
        left_margin = min((float(ln.x0) for ln in label_lines), default=0.0)
        header_lines = [ln for ln in lines2 if _header_like(ln, small_sz)]

        # Infer base labels per code
        recs = []
        for cl in code_lines:
            base = _infer_field_label(lines2, cl, small_sz, label_lines, left_margin)
            base = _norm_text(base)
            if not base:
                continue
            recs.append(
                {
                    "base": base,
                    "x": float(cl.x0),
                    "y": float(cl.y0),
                }
            )

        if not recs:
            continue

        # Disambiguate same-label multiple codes on a page (multi-column tables)
        by_base = {}
        for r in recs:
            by_base.setdefault(r["base"], []).append(r)

        for base, rs in by_base.items():
            if len(rs) == 1:
                rs[0]["field_name"] = base
                continue

            xs = [r["x"] for r in rs]
            try:
                x_med = float(statistics.median(xs))
            except Exception:
                x_med = xs[len(xs) // 2] if xs else 0.0

            for r in rs:
                hdr = _nearest_header(header_lines, r["x"], r["y"])
                if hdr and hdr.lower() not in base.lower():
                    r["field_name"] = _norm_text(f"{base} - {hdr}")
                else:
                    side = "Left" if r["x"] <= x_med else "Right"
                    r["field_name"] = _norm_text(f"{base} - {side}")

        # Emit with conservative near-duplicate suppression (same label at same y band)
        emitted = []
        for r in sorted(recs, key=lambda d: (d["y"], d["x"])):
            field_name = _norm_text(r.get("field_name", r["base"]))
            if not field_name:
                continue
            key = (form_name, field_name)
            y = r["y"]
            dup = False
            for (k2, y2) in emitted:
                if k2 == key and abs(y2 - y) < 12.0:
                    dup = True
                    break
            if dup:
                continue
            out.append({"form_name": form_name, "field_name": field_name, "page": page_index + 1})
            emitted.append((key, y))

    return out
```
