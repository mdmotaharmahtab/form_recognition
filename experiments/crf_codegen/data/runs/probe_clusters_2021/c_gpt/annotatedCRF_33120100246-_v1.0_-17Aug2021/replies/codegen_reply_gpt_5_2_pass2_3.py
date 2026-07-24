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
    s = " ".join(s.split())
    # Strip trailing label punctuation commonly used as a visual cue.
    while s and s[-1] in ":;":
        s = s[:-1].rstrip()
    return s


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
    # Very short, bold, contains a digit, mostly non-letters.
    t = _norm(getattr(line, "text", ""))
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
        return {
            "max_x1": 1.0,
            "min_x0": 0.0,
            "width": 1.0,
            "median_size": 0.0,
            "p90_size": 0.0,
        }
    xs1 = [getattr(l, "x1", 0.0) for l in lines]
    xs0 = [getattr(l, "x0", 0.0) for l in lines]
    sizes = [getattr(l, "size", 0.0) for l in lines if getattr(l, "text", "").strip()]
    sizes_sorted = sorted(sizes) if sizes else [0.0]
    median_size = statistics.median(sizes_sorted) if sizes_sorted else 0.0
    p90_size = sizes_sorted[int(0.9 * (len(sizes_sorted) - 1))] if len(sizes_sorted) >= 2 else median_size

    max_x1 = max(xs1) if xs1 else 1.0
    min_x0 = min(xs0) if xs0 else 0.0
    width = max(1.0, max_x1 - min_x0)

    return {
        "max_x1": max_x1,
        "min_x0": min_x0,
        "width": width,
        "median_size": median_size,
        "p90_size": p90_size,
    }


def _detect_form_title(lines, meta):
    if not lines:
        return ""
    max_x1 = meta["max_x1"]
    min_x0 = meta["min_x0"]
    width = meta["width"]
    med = meta["median_size"]
    p90 = meta["p90_size"]

    candidates = []
    for l in lines:
        t = _norm(getattr(l, "text", ""))
        if not t:
            continue
        if getattr(l, "y0", 999999) > 115:
            continue
        # Typically title is left-ish.
        if getattr(l, "x0", 0.0) > (min_x0 + 0.55 * width):
            continue
        if t.startswith("["):
            continue
        if _is_machine_code_line_text(t) or _is_technical_bracket_line(t):
            continue
        if not _has_letter(t):
            continue

        size = getattr(l, "size", 0.0)
        big_enough = (size >= max(med * 1.35, med + 3.0, p90))
        if not big_enough:
            continue

        # Titles are often colored; accept bold black too.
        if not (getattr(l, "non_black", False) or getattr(l, "bold", False)):
            continue

        candidates.append(l)

    if not candidates:
        return ""

    candidates.sort(key=lambda l: (-getattr(l, "size", 0.0), getattr(l, "y0", 0.0), getattr(l, "x0", 0.0)))
    return _norm(getattr(candidates[0], "text", ""))


def _segment_by_y(lines_sorted, meta):
    segs = []
    cur = []
    prev = None
    # Use page typography to choose a tolerant but not over-wide gap.
    med = meta.get("median_size", 0.0) or 0.0
    gap_thresh = max(18.0, med * 1.7)  # tolerant across slightly scaled prints
    for l in lines_sorted:
        if prev is None:
            cur = [l]
        else:
            gap = getattr(l, "y0", 0.0) - getattr(prev, "y1", 0.0)
            if gap <= gap_thresh:
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
        y0 = getattr(seg[0], "y0", 0.0)
        y1 = getattr(seg[-1], "y1", 0.0)
        center = (y0 + y1) / 2.0
        score = -abs(center - target_y)
        score2 = score + 0.5 * min(len(seg), 6)
        if best is None or score2 > best_score:
            best = seg
            best_score = score2
    return best or []


def _looks_like_value_list_text(t: str) -> bool:
    t = _norm(t)
    if not t:
        return False
    # Long comma/semicolon-separated enumerations (e.g., lab analyte lists).
    if len(t) < 60:
        return False
    if t.endswith("?") or ":" in t:
        return False
    seps = t.count(",") + t.count(";")
    if seps < 5:
        return False
    tokens = [tok.strip() for tok in re.split(r"[,;]", t) if tok.strip()]
    if len(tokens) < 6:
        return False
    avg_len = sum(len(tok) for tok in tokens) / max(1, len(tokens))
    if avg_len > 22:
        return False
    return True


def _looks_like_value_list_line(line, meta) -> bool:
    if getattr(line, "bold", False):
        return False
    t = _norm(getattr(line, "text", ""))
    if not _looks_like_value_list_text(t):
        return False
    # Often appears as bracketed/parenthetical payload.
    if ")]" in t or t.endswith(")") or t.endswith("]") or "]" in t:
        return True
    # Still treat as value-list even without brackets if very list-like.
    return True


def _is_probable_option_line(line, meta):
    t = _norm(getattr(line, "text", ""))
    if not t or t.startswith("["):
        return False
    if _is_machine_code_line_text(t) or _is_technical_bracket_line(t):
        return False

    max_x1 = meta["max_x1"]
    min_x0 = meta["min_x0"]
    width = meta["width"]

    # Option lists tend to sit in the right column.
    if getattr(line, "x0", 0.0) < (min_x0 + 0.55 * width):
        return False
    if getattr(line, "bold", False):
        return False

    # Exclude long list-like content (not a label).
    if _looks_like_value_list_line(line, meta):
        return True

    med = meta["median_size"] or 0.0
    if med and getattr(line, "size", 0.0) > med * 1.15:
        return False

    # Short-ish phrases are more likely options than labels.
    if len(t) <= 28 and not t.endswith("?") and ":" not in t:
        return True
    return False


def _label_candidate_ok(line, meta):
    t = _norm(getattr(line, "text", ""))
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
    if _looks_like_value_list_line(line, meta):
        return False
    if _is_probable_option_line(line, meta):
        return False
    # Prefer real labels: must have letters, or be clearly a mixed token label.
    if not _has_letter(t) and not any(ch.isdigit() for ch in t):
        return False
    return True


def _listish_prefix(prefix: str) -> bool:
    p = _norm(prefix)
    if not p:
        return False
    seps = p.count(",") + p.count(";")
    if seps >= 5 and len(p) >= 55:
        return True
    # Also treat very dense punctuation as listish.
    punct = sum(1 for ch in p if ch in ",;")
    return punct >= 6 and len(p) >= 55


def _clean_label_text(label: str) -> str:
    t = _norm(label)
    if not t:
        return ""

    # Remove a leading parenthetical/bracketed value-list payload.
    if t.startswith("("):
        close = t.find(")")
        if 0 < close < 200:
            inner = t[1:close]
            if _listish_prefix(inner):
                rest = _norm(t[close + 1 :])
                if rest:
                    t = rest

    # Remove list-like prefixes ending in "]" or ")]" that get pulled in from adjacent columns.
    idx = t.rfind(")]")
    if idx != -1 and idx < len(t) - 2:
        prefix = t[: idx + 2]
        suffix = _norm(t[idx + 2 :])
        if suffix and _listish_prefix(prefix):
            # Strip stray leading punctuation from suffix.
            suffix = suffix.lstrip(")]} ").lstrip()
            t = _norm(suffix)

    idx2 = t.rfind("]")
    if idx2 != -1 and idx2 < len(t) - 1:
        prefix = t[: idx2 + 1]
        suffix = _norm(t[idx2 + 1 :])
        if suffix and _listish_prefix(prefix) and len(suffix) >= 6:
            suffix = suffix.lstrip("] ").lstrip()
            t = _norm(suffix)

    # Final safety: avoid returning something that is still obviously a value list.
    if _looks_like_value_list_text(t):
        return ""

    return t


def _extract_label_for_code(lines, code_line, meta):
    max_x1 = meta["max_x1"]
    min_x0 = meta["min_x0"]
    width = meta["width"]

    code_x = getattr(code_line, "x0", 0.0)
    code_center_y = (getattr(code_line, "y0", 0.0) + getattr(code_line, "y1", 0.0)) / 2.0
    left_code = code_x <= (min_x0 + 0.42 * width)

    candidates = []
    if left_code:
        # Usually label is above in same left column. Allow slight below for mid-row codes.
        x_lo = code_x - 0.07 * width
        x_hi = code_x + 0.18 * width
        y_lo = code_center_y - 0.33 * width
        y_hi = code_center_y + 0.18 * width
        for l in lines:
            lx0 = getattr(l, "x0", 0.0)
            if lx0 < x_lo or lx0 > x_hi:
                continue
            if getattr(l, "y1", 0.0) < y_lo or getattr(l, "y0", 0.0) > y_hi:
                continue
            if not _label_candidate_ok(l, meta):
                continue
            candidates.append(l)
    else:
        # Code is in right column; label may be in left column OR just left of the code in the same row.
        y_lo = code_center_y - 0.36 * width
        y_hi = code_center_y + 0.22 * width

        leftish = []
        mid = []
        for l in lines:
            if getattr(l, "y1", 0.0) < y_lo or getattr(l, "y0", 0.0) > y_hi:
                continue
            if not _label_candidate_ok(l, meta):
                continue

            # Keep anything not to the right of the code start (with slack).
            if getattr(l, "x0", 0.0) > code_x + 0.02 * width:
                continue

            if getattr(l, "x0", 0.0) <= (min_x0 + 0.55 * width):
                leftish.append(l)
            else:
                # Mid/right label fragments: require stronger "label-ish" signal to avoid options.
                med = meta["median_size"] or 0.0
                text = _norm(getattr(l, "text", ""))
                strong = getattr(l, "bold", False) or (med and getattr(l, "size", 0.0) >= med * 1.08) or (":" in text) or text.endswith("?")
                if strong:
                    mid.append(l)

        pool = leftish if leftish else (leftish + mid)

        if pool:
            # Determine a stable x band near the left edge of the label block.
            target_x = min(getattr(l, "x0", 0.0) for l in pool)
            x_lo = target_x - 0.05 * width
            x_hi = target_x + 0.26 * width
            for l in pool:
                lx0 = getattr(l, "x0", 0.0)
                if lx0 < x_lo or lx0 > x_hi:
                    continue
                candidates.append(l)

    if candidates:
        candidates.sort(key=lambda l: (getattr(l, "y0", 0.0), getattr(l, "x0", 0.0)))
        segs = _segment_by_y(candidates, meta)
        seg = _choose_best_segment(segs, code_center_y)
        if seg:
            seg_sorted = sorted(seg, key=lambda l: (getattr(l, "y0", 0.0), getattr(l, "x0", 0.0)))

            # Prefer not to concatenate too many unrelated wrapped lines.
            if len(seg_sorted) > 10:
                seg_sorted.sort(key=lambda l: abs(((getattr(l, "y0", 0.0) + getattr(l, "y1", 0.0)) / 2.0) - code_center_y))
                keep = seg_sorted[:10]
                keep.sort(key=lambda l: (getattr(l, "y0", 0.0), getattr(l, "x0", 0.0)))
                seg_sorted = keep

            label_raw = " ".join(_norm(getattr(l, "text", "")) for l in seg_sorted)
            label = _clean_label_text(label_raw)
            if label:
                return label

    # Fallback: option-list table cases where the label is a left-margin header above a dense right-side list.
    if left_code and code_x <= min_x0 + 0.14 * width:
        right_lines = []
        for l in lines:
            if not _label_candidate_ok(l, meta):
                continue
            if getattr(l, "x0", 0.0) < (min_x0 + 0.45 * width):
                continue
            if getattr(l, "y0", 0.0) < 70 or getattr(l, "y0", 0.0) > getattr(code_line, "y0", 0.0) - 20:
                continue
            # value-list payload isn't a label
            if _looks_like_value_list_line(l, meta):
                continue
            right_lines.append(l)

        if len(right_lines) >= 8:
            option_min_y = min(getattr(l, "y0", 0.0) for l in right_lines)
            left_headers = []
            for l in lines:
                if not _label_candidate_ok(l, meta):
                    continue
                if getattr(l, "x0", 0.0) > min_x0 + 0.15 * width:
                    continue
                if getattr(l, "y0", 0.0) >= option_min_y:
                    continue
                # keep fairly close to options start to avoid earlier unrelated fields
                if option_min_y - getattr(l, "y0", 0.0) > 0.25 * width:
                    continue
                left_headers.append(l)
            if left_headers:
                left_headers.sort(key=lambda l: (-getattr(l, "y0", 0.0), getattr(l, "x0", 0.0)))
                return _clean_label_text(getattr(left_headers[0], "text", "")) or ""

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
            t = _norm(getattr(l, "text", ""))
            if not t:
                continue

            # Anchor on machine code lines (colored or not).
            if not _is_machine_code_line_text(t):
                continue

            field_name = _extract_label_for_code(lines, l, meta)
            if not field_name:
                continue
            field_name = _clean_label_text(field_name)
            if not field_name:
                continue

            if len(field_name) <= 1:
                continue
            # Avoid returning machine code-like or bracket technical artifacts as "labels".
            if _is_machine_code_line_text(field_name) or _is_technical_bracket_line(field_name):
                continue

            rec = (current_form or "", field_name, page_idx0 + 1)
            if rec in seen:
                continue
            seen.add(rec)
            out.append({"form_name": current_form or "", "field_name": field_name, "page": page_idx0 + 1})

    return out
```
