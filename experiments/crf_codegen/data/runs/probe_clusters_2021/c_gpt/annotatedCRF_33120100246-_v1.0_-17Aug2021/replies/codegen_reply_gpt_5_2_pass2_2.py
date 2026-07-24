```python
import re
import statistics
import unicodedata

# Allow common machine-id characters seen in annotated CRFs (underscore, hyphen, dot).
_CODE_RE = re.compile(r"^\[[A-Za-z0-9][A-Za-z0-9_.-]*\]$")

_LEADING_ENUM_FIX_RE = re.compile(r"^\\(\d+\.)\s*")

def _norm(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = _LEADING_ENUM_FIX_RE.sub(r"\1 ", s)
    return " ".join(s.split())

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
    if not t or not getattr(line, "bold", False):
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
        if not (getattr(l, "non_black", False) or getattr(l, "bold", False)):
            continue

        candidates.append(l)

    if not candidates:
        return ""

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
            if gap <= 22:
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
        score2 = score + 0.5 * min(len(seg), 6)
        if best is None or score2 > best_score:
            best = seg
            best_score = score2
    return best or []

def _is_probable_option_line(line, meta):
    # Option lists tend to sit in the right column and be short, normal-weight, and not larger than body text.
    t = _norm(line.text)
    if not t or t.startswith("["):
        return False
    if _is_machine_code_line_text(t) or _is_technical_bracket_line(t):
        return False
    max_x1 = meta["max_x1"]
    if line.x0 < 0.55 * max_x1:
        return False
    if getattr(line, "bold", False):
        return False
    med = meta["median_size"] or 0.0
    if med and line.size > med * 1.15:
        return False
    # Short-ish phrases are more likely options than labels.
    if len(t) <= 28 and not t.endswith("?") and ":" not in t:
        return True
    return False

def _label_candidate_ok(line, meta):
    t = _norm(line.text)
    if not t:
        return False
    if t.startswith("["):
        return False
    if _is_machine_code_line_text(t) or _is_technical_bracket_line(t):
        return False
    if _looks_like_row_marker(line):
        return False
    if t.isdigit():
        return False
    if _is_probable_option_line(line, meta):
        return False
    # Prefer real labels: must have letters, or be clearly a mixed token label.
    if not _has_letter(t) and not any(ch.isdigit() for ch in t):
        return False
    return True

def _extract_label_for_code(lines, code_line, meta):
    max_x1 = meta["max_x1"]
    min_x0 = meta["min_x0"]
    code_x = code_line.x0
    code_center_y = (code_line.y0 + code_line.y1) / 2.0
    left_code = code_x <= 0.40 * max_x1

    candidates = []
    if left_code:
        # Usually label is above in same left column. Allow slight below for mid-row codes.
        x_lo = code_x - 45
        x_hi = code_x + 110
        y_lo = code_center_y - 235
        y_hi = code_center_y + 125
        for l in lines:
            if l.x0 < x_lo or l.x0 > x_hi:
                continue
            if l.y1 < y_lo or l.y0 > y_hi:
                continue
            # Labels may be black or colored; filter structurally instead of by color.
            if not _label_candidate_ok(l, meta):
                continue
            candidates.append(l)
    else:
        # Code is in right column; label may be in left column OR just left of the code in the same row.
        y_lo = code_center_y - 250
        y_hi = code_center_y + 145

        leftish = []
        mid = []
        for l in lines:
            if l.y1 < y_lo or l.y0 > y_hi:
                continue
            if not _label_candidate_ok(l, meta):
                continue

            # Keep anything not to the right of the code start (with slack).
            if l.x0 > code_x + 12:
                continue

            if l.x0 <= 0.55 * max_x1:
                leftish.append(l)
            else:
                # Mid/right label fragments: require stronger "label-ish" signal to avoid options.
                med = meta["median_size"] or 0.0
                if getattr(l, "bold", False) or (med and l.size >= med * 1.08) or ":" in _norm(l.text) or _norm(l.text).endswith("?"):
                    mid.append(l)

        pool = leftish if leftish else (leftish + mid)

        if pool:
            # Determine a stable x band near the left edge of the label block.
            target_x = min(l.x0 for l in pool)
            x_lo = target_x - 30
            # Wider band helps capture wrapped labels that indent.
            x_hi = target_x + 165
            for l in pool:
                if l.x0 < x_lo or l.x0 > x_hi:
                    continue
                candidates.append(l)

    if candidates:
        candidates.sort(key=lambda l: (l.y0, l.x0))
        segs = _segment_by_y(candidates)
        seg = _choose_best_segment(segs, code_center_y)
        if seg:
            seg_sorted = sorted(seg, key=lambda l: (l.y0, l.x0))
            if len(seg_sorted) > 10:
                seg_sorted.sort(key=lambda l: abs(((l.y0 + l.y1) / 2.0) - code_center_y))
                keep = seg_sorted[:10]
                keep.sort(key=lambda l: (l.y0, l.x0))
                seg_sorted = keep
            label = _norm(" ".join(_norm(l.text) for l in seg_sorted))
            if label:
                return label

    # Fallback: option-list table cases where the label is a left-margin header above a dense right-side list.
    if left_code and code_x <= min_x0 + 85:
        right_lines = []
        for l in lines:
            if not _label_candidate_ok(l, meta):
                continue
            if l.x0 < 0.45 * max_x1:
                continue
            if l.y0 < 70 or l.y0 > code_line.y0 - 20:
                continue
            right_lines.append(l)

        if len(right_lines) >= 8:
            option_min_y = min(l.y0 for l in right_lines)
            left_headers = []
            for l in lines:
                if not _label_candidate_ok(l, meta):
                    continue
                if l.x0 > min_x0 + 90:
                    continue
                if l.y0 >= option_min_y:
                    continue
                # keep fairly close to options start to avoid earlier unrelated fields
                if option_min_y - l.y0 > 180:
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

        for l in lines:
            t = _norm(l.text)
            if not t:
                continue
            # Anchor on machine code lines (typically red).
            if not getattr(l, "non_black", False):
                continue
            if not _is_machine_code_line_text(t):
                continue

            field_name = _extract_label_for_code(lines, l, meta)
            if not field_name:
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
