```python
# Observed layouts: annotated CRF pages with (a) prominent section/form title near top-left (often larger and colored),
# (b) per-field machine IDs in red like "[XXXX]" followed by "[TYPE: ...]" lines, and (c) answer options in a right column.
# Strategy: carry forward the current form title; extract fields by anchoring on red machine-ID lines and pulling the
# nearest left-column black label text block (joining wrapped lines), while excluding option lists and technical annotations.

import re
import statistics
import unicodedata

_CODE_RE = re.compile(r"^\[[A-Za-z0-9_]+\]$")

def _norm(s: str) -> str:
    return " ".join((s or "").split())

def _has_letter(s: str) -> bool:
    for ch in s:
        if unicodedata.category(ch).startswith("L"):
            return True
    return False

def _is_machine_code_line_text(t: str) -> bool:
    t = t.strip()
    if not t.startswith("[") or not t.endswith("]"):
        return False
    if ":" in t or " " in t or "\t" in t:
        return False
    return bool(_CODE_RE.match(t))

def _is_technical_bracket_line(t: str) -> bool:
    t = t.strip()
    if not (t.startswith("[") and t.endswith("]")):
        return False
    # Includes things like "[TYPE: ...]" "[VISIBILITY: ...]"
    return (":" in t) or (" " in t) or ("\t" in t)

def _looks_like_row_marker(line) -> bool:
    # Language-agnostic-ish: very short, bold, contains a digit, mostly non-letters.
    t = _norm(line.text)
    if not t or not line.bold:
        return False
    if len(t) > 14:
        return False
    if not any(ch.isdigit() for ch in t):
        return False
    letters = sum(1 for ch in t if unicodedata.category(ch).startswith("L"))
    return letters <= 4

def _page_meta(lines):
    if not lines:
        return {"max_x1": 1.0, "min_x0": 0.0, "median_size": 0.0, "p90_size": 0.0}
    xs1 = [l.x1 for l in lines]
    xs0 = [l.x0 for l in lines]
    sizes = [l.size for l in lines if getattr(l, "text", "").strip()]
    sizes_sorted = sorted(sizes) if sizes else [0.0]
    median_size = statistics.median(sizes_sorted) if sizes_sorted else 0.0
    p90_size = sizes_sorted[int(0.9 * (len(sizes_sorted) - 1))] if len(sizes_sorted) >= 2 else median_size
    return {
        "max_x1": max(xs1) if xs1 else 1.0,
        "min_x0": min(xs0) if xs0 else 0.0,
        "median_size": median_size,
        "p90_size": p90_size,
    }

def _detect_form_title(lines, meta):
    if not lines:
        return ""
    max_x1 = meta["max_x1"]
    med = meta["median_size"]
    p90 = meta["p90_size"]

    # Candidates: near top, left-ish, clearly larger than typical content.
    candidates = []
    for l in lines:
        t = _norm(l.text)
        if not t:
            continue
        if l.y0 > 115:
            continue
        if l.x0 > max_x1 * 0.55:
            continue
        if t.startswith("["):
            continue
        if _is_machine_code_line_text(t) or _is_technical_bracket_line(t):
            continue
        if not _has_letter(t):
            continue

        big_enough = (l.size >= max(med * 1.35, med + 3.0, p90))
        if not big_enough:
            continue

        # Titles are often colored; accept bold black too.
        if not (l.non_black or l.bold):
            continue

        candidates.append(l)

    if not candidates:
        return ""

    # Choose largest font; then highest on page.
    candidates.sort(key=lambda l: (-l.size, l.y0, l.x0))
    return _norm(candidates[0].text)

def _segment_by_y(lines_sorted):
    segs = []
    cur = []
    prev = None
    for l in lines_sorted:
        if prev is None:
            cur = [l]
        else:
            gap = l.y0 - prev.y1
            if gap <= 22:  # tolerant line spacing
                cur.append(l)
            else:
                if cur:
                    segs.append(cur)
                cur = [l]
        prev = l
    if cur:
        segs.append(cur)
    return segs

def _choose_best_segment(segs, target_y):
    if not segs:
        return []
    best = None
    best_score = None
    for seg in segs:
        y0 = seg[0].y0
        y1 = seg[-1].y1
        center = (y0 + y1) / 2.0
        score = -abs(center - target_y)
        # Prefer longer (more wrapped lines) when equally close.
        score2 = score + 0.5 * min(len(seg), 6)
        if best is None or score2 > best_score:
            best = seg
            best_score = score2
    return best or []

def _extract_label_for_code(lines, code_line, meta):
    max_x1 = meta["max_x1"]
    min_x0 = meta["min_x0"]
    code_x = code_line.x0
    code_center_y = (code_line.y0 + code_line.y1) / 2.0
    left_code = code_x <= 0.40 * max_x1

    # Build a pool of black label candidates in an x-band and y-window.
    candidates = []
    if left_code:
        # Usually label is above in same left column. Allow slight below to catch mid-row right-column codes.
        x_lo = code_x - 40
        x_hi = code_x + 90
        y_lo = code_center_y - 220
        y_hi = code_center_y + 110
        for l in lines:
            if l.non_black:
                continue
            t = _norm(l.text)
            if not t or t.startswith("["):
                continue
            if _looks_like_row_marker(l):
                continue
            if t.isdigit():
                continue
            if l.x0 < x_lo or l.x0 > x_hi:
                continue
            if l.y1 < y_lo or l.y0 > y_hi:
                continue
            candidates.append(l)
    else:
        # Code is in right column; label is in left column near same y.
        y_lo = code_center_y - 230
        y_hi = code_center_y + 130

        prelim = []
        for l in lines:
            if l.non_black:
                continue
            t = _norm(l.text)
            if not t or t.startswith("["):
                continue
            if _looks_like_row_marker(l):
                continue
            if t.isdigit():
                continue
            if l.x0 > code_x - 35:
                continue
            if l.y1 < y_lo or l.y0 > y_hi:
                continue
            prelim.append(l)

        if prelim:
            target_x = min(l.x0 for l in prelim)
            x_lo = target_x - 25
            x_hi = target_x + 120
            for l in prelim:
                if l.x0 < x_lo or l.x0 > x_hi:
                    continue
                candidates.append(l)

    if candidates:
        candidates.sort(key=lambda l: (l.y0, l.x0))
        segs = _segment_by_y(candidates)
        seg = _choose_best_segment(segs, code_center_y)
        if seg:
            # Limit runaway blocks: keep at most ~8 lines closest to the code band.
            seg_sorted = sorted(seg, key=lambda l: (l.y0, l.x0))
            if len(seg_sorted) > 10:
                # Keep a window around the line whose y is closest to code.
                seg_sorted.sort(key=lambda l: abs(((l.y0 + l.y1) / 2.0) - code_center_y))
                keep = seg_sorted[:10]
                keep.sort(key=lambda l: (l.y0, l.x0))
                seg_sorted = keep
            label = _norm(" ".join(_norm(l.text) for l in seg_sorted))
            if label:
                return label

    # Fallback for pages where code appears far below its label due to printed enumeration lists.
    # Detect a dense right/center option-list column and attach the nearest preceding left-margin header line.
    if left_code and code_x <= min_x0 + 85:
        # Find a dense column of black lines in the right half (likely printed option list).
        right_lines = []
        for l in lines:
            if l.non_black:
                continue
            t = _norm(l.text)
            if not t or t.startswith("["):
                continue
            if l.x0 < 0.45 * max_x1:
                continue
            if l.y0 < 70 or l.y0 > code_line.y0 - 20:
                continue
            right_lines.append(l)

        if len(right_lines) >= 8:
            option_min_y = min(l.y0 for l in right_lines)
            # Find nearest left-margin black line above option list start.
            left_headers = []
            for l in lines:
                if l.non_black:
                    continue
                t = _norm(l.text)
                if not t or t.startswith("["):
                    continue
                if l.x0 > min_x0 + 90:
                    continue
                if l.y0 >= option_min_y:
                    continue
                if _looks_like_row_marker(l):
                    continue
                if t.isdigit():
                    continue
                # keep fairly close to the options start to avoid earlier unrelated fields
                if option_min_y - l.y0 > 160:
                    continue
                left_headers.append(l)
            if left_headers:
                left_headers.sort(key=lambda l: (-l.y0, l.x0))
                return _norm(left_headers[0].text)

    return ""

def extract(pages):
    out = []
    seen = set()
    current_form = ""

    for page_idx0, lines in pages:
        meta = _page_meta(lines)

        title = _detect_form_title(lines, meta)
        if title:
            current_form = title

        # Anchor extraction on machine code lines (red bracket IDs).
        for l in lines:
            t = _norm(l.text)
            if not t:
                continue
            if not l.non_black:
                continue
            if not _is_machine_code_line_text(t):
                continue

            field_name = _extract_label_for_code(lines, l, meta)
            if not field_name:
                continue

            # Basic structural sanity: avoid harvesting pure furniture.
            if not _has_letter(field_name) and not any(ch.isdigit() for ch in field_name):
                continue
            if len(field_name) <= 1:
                continue

            rec = (current_form or "", field_name, page_idx0 + 1)
            if rec in seen:
                continue
            seen.add(rec)
            out.append({"form_name": current_form or "", "field_name": field_name, "page": page_idx0 + 1})

    return out
```
