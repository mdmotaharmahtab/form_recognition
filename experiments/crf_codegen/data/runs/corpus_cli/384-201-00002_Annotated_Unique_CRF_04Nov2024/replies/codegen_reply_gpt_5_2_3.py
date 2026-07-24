```python
import re
import unicodedata
from typing import List, Dict, Optional, Tuple


def extract(pages):
    out: List[Dict[str, object]] = []
    seen = set()
    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1
        if not lines:
            continue

        stats = _page_stats(lines)

        form = _extract_form_name(lines, stats)
        if form:
            current_form = form

        if _looks_like_table_page(lines, stats):
            fields = _extract_fields_table(lines, stats)
        else:
            # Keep the original working path first.
            fields = _extract_fields_standard(lines, stats)

            # Extend: handle pages without numeric markers (date-format anchors, Yes/No anchors, etc).
            if not fields:
                fields = _extract_fields_anchored(lines, stats)

            # Extend: numbered questionnaire layouts (e.g., "3. ...", "4. ...") without numeric markers.
            if not fields:
                fields = _extract_fields_numbered_questions(lines, stats)

            # Existing last-resort prompt-like fallback.
            if not fields:
                fields = _extract_fields_prompt_fallback(lines, stats)

        # Final safety filter (prevents format-hints like "dd MMM yyyy" and single-token anchors).
        cleaned: List[str] = []
        for f in fields or []:
            t = _norm(f)
            if not t:
                continue
            if _is_bad_field_label(t):
                continue
            cleaned.append(t)
        fields = _dedupe_preserve_order(cleaned)

        for field_name in fields:
            fn = current_form or ""
            fld = _norm(field_name)
            if not fn and not fld:
                continue

            key = (page_num, fn, fld)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": fn, "field_name": fld, "page": page_num})

    return out


# ---------------- helpers ----------------

_RE_FORM = re.compile(r"^\s*Form\s*:\s*(.+?)\s*$", re.IGNORECASE)
_RE_GENERATED = re.compile(r"^\s*Generated\s+On\s*:\s*", re.IGNORECASE)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _y0(line) -> float:
    return float(getattr(line, "y0", 0.0))


def _x0(line) -> float:
    return float(getattr(line, "x0", 0.0))


def _x1(line) -> float:
    return float(getattr(line, "x1", _x0(line)))


def _is_bold(line) -> bool:
    return bool(getattr(line, "bold", False))


def _page_stats(lines) -> Dict[str, float]:
    xs0 = [_x0(ln) for ln in lines]
    xs1 = [_x1(ln) for ln in lines]
    ys0 = [_y0(ln) for ln in lines]
    min_x = min(xs0) if xs0 else 0.0
    max_x = max(xs1) if xs1 else (max(xs0) if xs0 else 0.0)
    min_y = min(ys0) if ys0 else 0.0
    max_y = max(ys0) if ys0 else 1.0
    w = max(1.0, max_x - min_x)
    h = max(1.0, max_y - min_y)
    return {"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y, "w": w, "h": h}


def _header_max_y(stats: Dict[str, float]) -> float:
    return stats["min_y"] + 0.30 * stats["h"]


def _footer_min_y(stats: Dict[str, float]) -> float:
    return stats["min_y"] + 0.93 * stats["h"]


def _header_lines(lines, stats):
    hy = _header_max_y(stats)
    return [ln for ln in lines if _y0(ln) <= hy + 0.01 * stats["h"]]


def _body_lines(lines, stats):
    hy = _header_max_y(stats)
    fy = _footer_min_y(stats)
    lo = stats["min_y"] + 0.10 * stats["h"]
    hi = fy
    return [ln for ln in lines if lo <= _y0(ln) <= hi and _y0(ln) >= hy - 0.02 * stats["h"]]


def _has_letter(s: str) -> bool:
    s = _norm(s)
    for ch in s:
        if ch.isalpha():
            return True
        if unicodedata.category(ch).startswith("L"):
            return True
    return False


def _is_digits_only(s: str) -> bool:
    s = _norm(s)
    return bool(s) and s.isdigit()


def _contains_words(text: str, words: List[str]) -> bool:
    t = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    return all((" " + w + " ") in t for w in words)


def _looks_like_code(s: str) -> bool:
    t = _norm(s)
    if not t:
        return False

    if "$" in t:
        return True

    compact = re.sub(r"\s+", "", t)
    if "_" in compact and re.fullmatch(r"[A-Z0-9_]+", compact or ""):
        return True

    if " " not in t and re.fullmatch(r"[A-Z0-9]+", t) and 2 <= len(t) <= 25:
        return True

    if re.fullmatch(r"[A-Z0-9_ ]+", t) and 2 <= len(re.sub(r"\s+", "", t)) <= 30:
        if "_" in t or len(re.sub(r"\s+", "", t)) >= 8:
            return True

    return False


def _looks_like_technical_annotation(s: str) -> bool:
    t = _norm(s).lower()
    if not t:
        return False
    if "oid" in t and ("auto" in t or "populat" in t or "field oid" in t):
        return True
    return False


def _looks_like_format_hint(s: str) -> bool:
    """
    Detect date/time format hints like:
    dd MMM yyyy
    HH:nn
    dd MMM yyyy HH:nn
    D / DD / MMM / YYYY-like tokens
    """
    t = _norm(s)
    if not t:
        return False

    low = t.lower()
    low = re.sub(r"\s+", " ", low).strip()

    # Single-token format anchors (D, DD, M, MM, MMM, YYYY, HH, NN, etc.)
    if re.fullmatch(r"(d{1,4}|m{1,4}|y{2,4}|h{1,2}|n{1,2}|s{1,2})", low):
        return True
    if low == "mmm":
        return True

    # Multi-token patterns separated by space or punctuation.
    parts = re.split(r"[ \-/:]+", low)
    if len(parts) >= 2 and len(parts) <= 8:
        ok = 0
        for p in parts:
            if not p:
                continue
            if p == "mmm":
                ok += 1
                continue
            if re.fullmatch(r"(d{1,4}|m{1,4}|y{2,4}|h{1,2}|n{1,2}|s{1,2})", p):
                ok += 1
                continue
            ok = -999
            break
        if ok == len([p for p in parts if p]):
            return True

    return False


def _is_bad_field_label(s: str) -> bool:
    t = _norm(s)
    if not t:
        return True
    if _is_digits_only(t):
        return True
    if _looks_like_code(t) or _looks_like_technical_annotation(t):
        return True
    if _looks_like_format_hint(t):
        return True
    # Very short, single-token anchors are rarely real fields in CRFs.
    if len(t) <= 1 and _has_letter(t):
        return True
    return False


def _extract_form_name(lines, stats) -> Optional[str]:
    header = _header_lines(lines, stats)
    form_ln = None
    form_text = None

    for ln in sorted(header, key=lambda z: (_y0(z), _x0(z))):
        m = _RE_FORM.match(_norm(getattr(ln, "text", "")))
        if m:
            form_ln = ln
            form_text = m.group(1)
            break

    if not form_ln or not form_text:
        return None

    base_x = _x0(form_ln)
    base_y = _y0(form_ln)

    gen_y = None
    for ln in header:
        if _RE_GENERATED.match(_norm(getattr(ln, "text", ""))):
            gen_y = _y0(ln)
            break
    if gen_y is None:
        gen_y = base_y + 0.08 * stats["h"]

    parts = [form_text]

    for ln in sorted(header, key=lambda z: (_y0(z), _x0(z))):
        y = _y0(ln)
        if y <= base_y + 0.001 * stats["h"] or y >= gen_y - 0.001 * stats["h"]:
            continue
        if not _is_bold(ln):
            continue
        if abs(_x0(ln) - base_x) > 0.02 * stats["w"]:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        if _RE_GENERATED.match(t):
            break
        if _RE_FORM.match(t):
            continue
        parts.append(t)

    joined = _norm(" ".join(parts))
    return joined or None


def _looks_like_table_page(lines, stats) -> bool:
    header = _header_lines(lines, stats)
    has_fieldname = False
    has_datatype = False
    has_fieldoid = False

    for ln in header:
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        if _contains_words(t, ["field", "name"]):
            has_fieldname = True
        if _contains_words(t, ["data", "type"]):
            has_datatype = True
        if _contains_words(t, ["field", "oid"]):
            has_fieldoid = True

    if has_fieldname and has_datatype and has_fieldoid:
        return True

    if has_fieldname and has_datatype:
        for ln in header:
            t = _norm(getattr(ln, "text", "")).lower()
            if "units" in t or "include" in t or (t == "values"):
                return True

    return False


def _extract_fields_table(lines, stats) -> List[str]:
    header = _header_lines(lines, stats)
    body = _body_lines(lines, stats)
    if not body:
        return []

    header_y = None
    x_fieldname = None
    x_units = None

    for ln in header:
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        if _contains_words(t, ["field", "name"]):
            y = _y0(ln)
            if header_y is None or y < header_y:
                header_y = y
                x_fieldname = _x0(ln)

    for ln in header:
        t = _norm(getattr(ln, "text", "")).lower()
        if t == "units" or " units" in (" " + t + " "):
            x_units = _x0(ln)
            break

    if header_y is None:
        header_y = stats["min_y"] + 0.15 * stats["h"]

    min_x = stats["min_x"]
    w = stats["w"]

    col_left = min_x + 0.02 * w
    if x_fieldname is not None:
        col_left = min(col_left, x_fieldname - 0.02 * w)

    if x_units is not None:
        col_right = x_units - 0.02 * w
    else:
        col_right = min_x + 0.45 * w

    start_y = header_y + 0.04 * stats["h"]
    cands = []
    for ln in body:
        y = _y0(ln)
        if y < start_y:
            continue
        x = _x0(ln)
        if x < col_left - 0.01 * w or x > col_right + 0.01 * w:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        if _is_digits_only(t):
            continue
        if re.match(r"^\d+\s*=", t):
            continue
        cands.append(ln)

    if not cands:
        return []

    cands.sort(key=lambda z: (_y0(z), _x0(z)))

    row_gap = 0.030 * stats["h"]
    wrap_gap = 0.024 * stats["h"]
    x_slack = 0.12 * stats["w"]

    groups: List[List[object]] = []
    cur: List[object] = []
    base_x = None
    prev_y = None

    for ln in cands:
        y = _y0(ln)
        x = _x0(ln)

        if not cur:
            cur = [ln]
            base_x = x
            prev_y = y
            continue

        new_row = False
        if prev_y is not None and (y - prev_y) > row_gap:
            new_row = True
        if base_x is not None and abs(x - base_x) > x_slack and prev_y is not None and (y - prev_y) > wrap_gap:
            new_row = True

        if new_row:
            groups.append(cur)
            cur = [ln]
            base_x = x
            prev_y = y
        else:
            if prev_y is not None and (y - prev_y) <= wrap_gap and (base_x is None or abs(x - base_x) <= x_slack):
                cur.append(ln)
                prev_y = y
            else:
                groups.append(cur)
                cur = [ln]
                base_x = x
                prev_y = y

    if cur:
        groups.append(cur)

    results: List[str] = []
    for grp in groups:
        parts = []
        for ln in grp:
            t = _norm(getattr(ln, "text", ""))
            if not t:
                continue
            parts.append(t)

        s = _norm(" ".join(parts))
        if not s or not _has_letter(s):
            continue

        s2 = re.sub(r"^\s*\d+\s+", "", s)
        if _has_letter(s2):
            s = _norm(s2)

        if _is_bad_field_label(s):
            continue

        results.append(s)

    return _dedupe_preserve_order(results)


def _extract_fields_standard(lines, stats) -> List[str]:
    body = _body_lines(lines, stats)
    if not body:
        return []

    min_x = stats["min_x"]
    w = stats["w"]
    h = stats["h"]

    # Relaxed marker detection to catch slightly-left markers, but require small visual span.
    markers = []
    marker_min_x = min_x + 0.52 * w
    max_marker_span = 0.10 * w

    for ln in body:
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        x = _x0(ln)
        if x >= marker_min_x and t.isdigit() and 1 <= len(t) <= 4:
            if (_x1(ln) - _x0(ln)) <= max_marker_span:
                markers.append(ln)

    if not markers:
        return []

    markers.sort(key=lambda z: (_y0(z), _x0(z)))
    marker_x = max(_x0(mk) for mk in markers)
    left_max_x = marker_x - 0.15 * w

    left = []
    for ln in body:
        x = _x0(ln)
        if x > left_max_x:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t or _is_digits_only(t):
            continue
        if re.match(r"^\d+\s*=", t):
            continue
        if _is_bad_field_label(t):
            continue
        left.append(ln)

    if not left:
        return []

    left_sorted = sorted(left, key=lambda ln: (_y0(ln), _x0(ln)))

    y_tol = 0.016 * h
    starts: List[Tuple[float, object]] = []

    for mk in markers:
        my = _y0(mk)

        # Wider candidate window; then choose the best "start-like" label.
        pool = [ln for ln in left_sorted if abs(_y0(ln) - my) <= 2.5 * y_tol]
        if not pool:
            continue

        best = _choose_best_start(pool, my, stats)
        if best is None:
            continue
        starts.append((_y0(best), best))

    if not starts:
        return []

    seen_ids = set()
    uniq_starts: List[Tuple[float, object]] = []
    for y, ln in sorted(starts, key=lambda p: p[0]):
        lid = id(ln)
        if lid in seen_ids:
            continue
        seen_ids.add(lid)
        uniq_starts.append((y, ln))

    wrap_gap = 0.040 * h
    cont_x_slack = 0.20 * w

    results: List[str] = []
    subfields: List[str] = []

    for i, (sy, sline) in enumerate(uniq_starts):
        ey = (uniq_starts[i + 1][0] - 0.001 * h) if i + 1 < len(uniq_starts) else (stats["min_y"] + 0.92 * h)
        base_x = _x0(sline)

        parts = []
        prev_y = None

        st = _norm(getattr(sline, "text", ""))
        if st and not _is_bad_field_label(st):
            parts.append(st)
            prev_y = _y0(sline)

        for ln in left_sorted:
            y = _y0(ln)
            if y <= sy + 0.0005 * h or y >= ey:
                continue

            x = _x0(ln)
            t = _norm(getattr(ln, "text", ""))
            if not t or _is_digits_only(t):
                continue
            if _is_bad_field_label(t):
                continue

            # Dependent prompt: indented and prompt-like (not a wrap).
            if x > base_x + 0.06 * w and _looks_like_dependent_prompt(t, ln):
                sf = _collect_wrapped_label(ln, left_sorted, y, ey, stats)
                if sf and not _is_bad_field_label(sf):
                    subfields.append(sf)
                continue

            if abs(x - base_x) > cont_x_slack:
                continue

            if prev_y is None:
                parts.append(t)
                prev_y = y
                continue

            gap = y - prev_y
            if gap <= wrap_gap:
                parts.append(t)
                prev_y = y
            else:
                break

        field = _norm(" ".join(parts))
        if not field or not _has_letter(field):
            continue
        if _is_bad_field_label(field):
            continue
        results.append(field)

    for sf in subfields:
        if sf and _has_letter(sf) and not _is_bad_field_label(sf):
            results.append(sf)

    return _dedupe_preserve_order(results)


def _looks_like_dependent_prompt(t: str, ln) -> bool:
    s = _norm(t)
    if not s:
        return False
    low = s.lower()

    # Common prompt endings.
    if s.endswith(":") or s.endswith("?"):
        return True

    # Conditional/clarification prompts often begin with "If" or include "please/specify".
    # This is used as an inclusion signal (not a junk blocklist).
    if low.startswith("if "):
        return True
    if "specify" in low or "please" in low or "describe" in low:
        return True

    # Short indented fragments shouldn't be treated as dependent prompts.
    if len(s) < 8:
        return False

    # If bold, treat as a normal label rather than dependent prompt.
    if _is_bold(ln):
        return False

    return False


def _choose_best_start(cands: List[object], anchor_y: float, stats: Dict[str, float]) -> Optional[object]:
    w = stats["w"]
    min_x = stats["min_x"]

    best = None
    best_key = None

    for ln in cands:
        t = _norm(getattr(ln, "text", ""))
        if not t or _is_bad_field_label(t):
            continue
        x = _x0(ln)
        y = _y0(ln)

        # "Start-likeness" scoring: prefer bold, leftmost, uppercase/digit starts, numbered prompts.
        low = t.lstrip()
        starts_num = bool(re.match(r"^\d+[\.\)]\s+\S", low))
        starts_upper = bool(low[:1].isupper())
        starts_digit = bool(low[:1].isdigit())
        starts_lower = bool(low[:1].islower())

        score = 0.0
        if _is_bold(ln):
            score += 3.0
        if starts_num:
            score += 2.0
        if starts_upper or starts_digit:
            score += 1.0
        if starts_lower and not _is_bold(ln):
            score -= 1.0

        # Penalize clearly indented continuation fragments.
        if x > min_x + 0.14 * w and starts_lower and not starts_num and not _is_bold(ln):
            score -= 1.0

        ydiff = abs(y - anchor_y)
        # Key: higher score first, then closer in y, then leftmost x.
        key = (-score, ydiff, x)

        if best is None or key < best_key:
            best = ln
            best_key = key

    return best


def _extract_fields_anchored(lines, stats) -> List[str]:
    """
    Extract labels by associating left-side prompts with right-side structural anchors:
    - date/time format hints (dd MMM yyyy, HH:nn, etc.)
    - clusters of short option words in the right half (e.g., Yes/No-style layouts)
    """
    body = _body_lines(lines, stats)
    if not body:
        return []

    min_x = stats["min_x"]
    w = stats["w"]
    h = stats["h"]

    left_limit = min_x + 0.62 * w
    right_start = min_x + 0.48 * w

    body_sorted = sorted(body, key=lambda ln: (_y0(ln), _x0(ln)))

    left_lines = []
    right_lines = []
    for ln in body_sorted:
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        x = _x0(ln)
        if x <= left_limit:
            left_lines.append(ln)
        if x >= right_start:
            right_lines.append(ln)

    if not left_lines or not right_lines:
        return []

    # Build anchor y-positions from:
    # (1) format-hint lines on the right
    anchors: List[float] = []
    for ln in right_lines:
        t = _norm(getattr(ln, "text", ""))
        if _looks_like_format_hint(t):
            anchors.append(_y0(ln))

    # (2) clusters of short option-like words on the right (structural, not literal)
    # Group by y buckets.
    y_bucket = 0.012 * h
    buckets: Dict[int, List[object]] = {}
    for ln in right_lines:
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        if len(t) > 10:
            continue
        # avoid pure digits (handled elsewhere)
        if t.isdigit():
            continue
        # keep short alpha-ish tokens, often used for option labels
        if not re.fullmatch(r"[A-Za-z][A-Za-z/\-]*", t):
            continue
        bid = int(round(_y0(ln) / max(1e-6, y_bucket)))
        buckets.setdefault(bid, []).append(ln)

    for bid, grp in buckets.items():
        if len(grp) >= 2:
            # If the group spans a narrow y-range, treat it as an anchor row.
            ys = sorted(_y0(ln) for ln in grp)
            if (ys[-1] - ys[0]) <= 0.020 * h:
                anchors.append(sum(ys) / len(ys))

    if not anchors:
        return []

    # De-duplicate anchors.
    anchors = sorted(anchors)
    merged: List[float] = []
    tol = 0.018 * h
    for y in anchors:
        if not merged or abs(y - merged[-1]) > tol:
            merged.append(y)
    anchors = merged

    left_sorted = sorted(left_lines, key=lambda ln: (_y0(ln), _x0(ln)))

    results: List[str] = []
    subfields: List[str] = []

    y_tol = 0.020 * h
    wrap_gap = 0.040 * h
    cont_x_slack = 0.22 * w

    for i, ay in enumerate(anchors):
        # Bound this anchor block by next anchor (prevents over-collecting wraps).
        next_ay = anchors[i + 1] if i + 1 < len(anchors) else (stats["min_y"] + 0.92 * h)
        ey = min(next_ay - 0.0005 * h, stats["min_y"] + 0.92 * h)

        pool = [ln for ln in left_sorted if (_y0(ln) >= ay - 2.2 * y_tol) and (_y0(ln) <= ay + 1.2 * y_tol)]
        if not pool:
            continue

        start_ln = _choose_best_start(pool, ay, stats)
        if start_ln is None:
            continue

        base_x = _x0(start_ln)
        sy = _y0(start_ln)

        # Collect wrapped label lines.
        parts = []
        prev_y = None

        t0 = _norm(getattr(start_ln, "text", ""))
        if t0 and not _is_bad_field_label(t0):
            parts.append(t0)
            prev_y = sy

        for ln in left_sorted:
            y = _y0(ln)
            if y <= sy + 0.0005 * h or y >= ey:
                continue
            x = _x0(ln)
            t = _norm(getattr(ln, "text", ""))
            if not t or _is_digits_only(t) or _is_bad_field_label(t):
                continue

            # Dependent prompts inside this block.
            if x > base_x + 0.06 * w and _looks_like_dependent_prompt(t, ln):
                sf = _collect_wrapped_label(ln, left_sorted, y, ey, stats)
                if sf and not _is_bad_field_label(sf):
                    subfields.append(sf)
                continue

            # Regular wrap continuation.
            if abs(x - base_x) > cont_x_slack:
                continue

            if prev_y is None:
                parts.append(t)
                prev_y = y
                continue
            if (y - prev_y) <= wrap_gap:
                parts.append(t)
                prev_y = y
            else:
                break

        field = _norm(" ".join(parts))
        if field and _has_letter(field) and not _is_bad_field_label(field):
            results.append(field)

    for sf in subfields:
        if sf and _has_letter(sf) and not _is_bad_field_label(sf):
            results.append(sf)

    return _dedupe_preserve_order(results)


def _extract_fields_numbered_questions(lines, stats) -> List[str]:
    """
    Handles questionnaire layouts where each data-entry field is a numbered prompt
    (e.g., "3. ...", "4. ...") and options are not marked with right-side numeric markers.
    """
    body = _body_lines(lines, stats)
    if not body:
        return []

    min_x = stats["min_x"]
    w = stats["w"]
    h = stats["h"]

    left_limit = min_x + 0.62 * w
    lines_left = []
    for ln in sorted(body, key=lambda ln: (_y0(ln), _x0(ln))):
        if _x0(ln) > left_limit:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        # Keep prompt-like text; drop obvious junk.
        if _is_bad_field_label(t):
            continue
        lines_left.append(ln)

    if not lines_left:
        return []

    # Find numbered starts near left margin.
    starts = []
    for ln in lines_left:
        t = _norm(getattr(ln, "text", ""))
        if re.match(r"^\s*\d+[\.\)]\s+\S", t):
            # Avoid capturing value-list numbering by requiring reasonably left position.
            if _x0(ln) <= min_x + 0.30 * w:
                starts.append(ln)

    if len(starts) < 2:
        return []

    starts = sorted(starts, key=lambda ln: (_y0(ln), _x0(ln)))

    results: List[str] = []
    subfields: List[str] = []

    wrap_gap = 0.045 * h
    cont_x_slack = 0.24 * w

    for i, sline in enumerate(starts):
        sy = _y0(sline)
        ey = _y0(starts[i + 1]) - 0.0005 * h if i + 1 < len(starts) else (stats["min_y"] + 0.92 * h)
        base_x = _x0(sline)

        parts = []
        prev_y = None

        t0 = _norm(getattr(sline, "text", ""))
        if t0 and not _is_bad_field_label(t0):
            parts.append(t0)
            prev_y = sy

        for ln in lines_left:
            y = _y0(ln)
            if y <= sy + 0.0005 * h or y >= ey:
                continue

            x = _x0(ln)
            t = _norm(getattr(ln, "text", ""))
            if not t or _is_digits_only(t) or _is_bad_field_label(t):
                continue

            # If we hit the next numbered start (safety), stop.
            if re.match(r"^\s*\d+[\.\)]\s+\S", t) and abs(x - base_x) <= 0.10 * w:
                break

            # Dependent prompt: strongly indented prompt-like line.
            if x > base_x + 0.10 * w and _looks_like_dependent_prompt(t, ln):
                sf = _collect_wrapped_label(ln, lines_left, y, ey, stats)
                if sf and not _is_bad_field_label(sf):
                    subfields.append(sf)
                continue

            # Wrap continuation of the numbered prompt.
            if abs(x - base_x) > cont_x_slack and x > base_x:
                continue

            if prev_y is None:
                parts.append(t)
                prev_y = y
                continue

            if (y - prev_y) <= wrap_gap:
                parts.append(t)
                prev_y = y
            else:
                # allow a bit more whitespace within long prompts if aligned
                if abs(x - base_x) <= 0.12 * w and (y - prev_y) <= 1.5 * wrap_gap:
                    parts.append(t)
                    prev_y = y
                else:
                    break

        field = _norm(" ".join(parts))
        if field and _has_letter(field) and not _is_bad_field_label(field):
            results.append(field)

    for sf in subfields:
        if sf and _has_letter(sf) and not _is_bad_field_label(sf):
            results.append(sf)

    return _dedupe_preserve_order(results)


def _collect_wrapped_label(start_ln, left_sorted, sy: float, ey: float, stats: Dict[str, float]) -> str:
    w = stats["w"]
    h = stats["h"]
    base_x = _x0(start_ln)
    wrap_gap = 0.040 * h
    x_slack = 0.18 * w

    parts = []
    prev_y = None

    t0 = _norm(getattr(start_ln, "text", ""))
    if t0:
        parts.append(t0)
        prev_y = _y0(start_ln)

    for ln in left_sorted:
        y = _y0(ln)
        if y <= sy + 0.0005 * h or y >= ey:
            continue
        x = _x0(ln)
        if abs(x - base_x) > x_slack:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t or _is_digits_only(t) or _is_bad_field_label(t):
            continue
        if prev_y is None:
            parts.append(t)
            prev_y = y
            continue
        if (y - prev_y) <= wrap_gap:
            parts.append(t)
            prev_y = y
        else:
            break

    return _norm(" ".join(parts))


def _extract_fields_prompt_fallback(lines, stats) -> List[str]:
    body = _body_lines(lines, stats)
    if not body:
        return []

    min_x = stats["min_x"]
    w = stats["w"]
    h = stats["h"]
    header_y = _header_max_y(stats)

    left_limit = min_x + 0.58 * w
    max_span = 0.68 * w
    wrap_gap = 0.040 * h
    x_slack = 0.18 * w

    cands = []
    for ln in body:
        if _y0(ln) <= header_y - 0.01 * h:
            continue
        if _y0(ln) >= _footer_min_y(stats):
            continue

        x0 = _x0(ln)
        if x0 > left_limit:
            continue

        t = _norm(getattr(ln, "text", ""))
        if not t or not _has_letter(t):
            continue
        if _is_digits_only(t):
            continue
        if _is_bad_field_label(t):
            continue

        span = _x1(ln) - _x0(ln)
        if span > max_span:
            continue

        low = t.lower()
        is_prompt = t.endswith(":") or t.endswith("?") or ("specify" in low and "(" in low and ")" in low)
        if not is_prompt:
            continue
        if t.endswith("."):
            continue

        cands.append(ln)

    if not cands:
        return []

    cands.sort(key=lambda z: (_y0(z), _x0(z)))

    results: List[str] = []
    used_ids = set()

    for ln in cands:
        if id(ln) in used_ids:
            continue

        base_x = _x0(ln)
        sy = _y0(ln)
        parts = [_norm(getattr(ln, "text", ""))]
        used_ids.add(id(ln))
        prev_y = sy

        for nxt in body:
            if id(nxt) in used_ids:
                continue
            y = _y0(nxt)
            if y <= sy + 0.0005 * h:
                continue
            if (y - prev_y) > wrap_gap:
                continue
            if abs(_x0(nxt) - base_x) > x_slack:
                continue
            t = _norm(getattr(nxt, "text", ""))
            if not t or _is_digits_only(t) or _is_bad_field_label(t):
                continue
            if (t.endswith(":") or t.endswith("?")) and _x0(nxt) <= base_x + 0.02 * w and parts:
                break
            parts.append(t)
            used_ids.add(id(nxt))
            prev_y = y

        field = _norm(" ".join(parts))
        if not field or not _has_letter(field):
            continue
        if _is_bad_field_label(field):
            continue
        results.append(field)

    return _dedupe_preserve_order(results)


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for s in items:
        t = _norm(s)
        if not t:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out
```
