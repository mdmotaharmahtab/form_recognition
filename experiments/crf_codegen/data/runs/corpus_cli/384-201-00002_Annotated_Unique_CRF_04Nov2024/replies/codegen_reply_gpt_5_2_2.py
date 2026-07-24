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
            fields = _extract_fields_standard(lines, stats)

        # If a page has no markers and doesn't look like a table, try prompt-based fallback.
        if not fields and not _looks_like_table_page(lines, stats):
            fields = _extract_fields_prompt_fallback(lines, stats)

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
    # Keep a generous header band (covers table headers that sit below the "Form:" line).
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


def _looks_like_code(s: str) -> bool:
    t = _norm(s)
    if not t:
        return False

    # Exclude technical/cost artifacts that show up in definition columns.
    if "$" in t:
        return True

    compact = re.sub(r"\s+", "", t)
    if "_" in compact and re.fullmatch(r"[A-Z0-9_]+", compact or ""):
        return True

    # Single-token all-caps/alnum codes (e.g., VISDAT, PCDTTM, EGTPT).
    if " " not in t and re.fullmatch(r"[A-Z0-9]+", t) and 2 <= len(t) <= 25:
        return True

    # Mostly-code tokens even with an accidental wrap space (e.g., "FOLDER_OI D").
    if re.fullmatch(r"[A-Z0-9_ ]+", t) and 2 <= len(re.sub(r"\s+", "", t)) <= 30:
        # Require some structure that human labels rarely are: underscores or long uninterrupted caps.
        if "_" in t or len(re.sub(r"\s+", "", t)) >= 8:
            return True

    return False


def _looks_like_technical_annotation(s: str) -> bool:
    t = _norm(s).lower()
    if not t:
        return False
    # "OID" and auto-population/definition hints are not data-entry fields.
    if "oid" in t and ("auto" in t or "populat" in t or "field oid" in t):
        return True
    return False


def _contains_words(text: str, words: List[str]) -> bool:
    t = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    return all((" " + w + " ") in t for w in words)


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

    # Join bold continuation lines aligned with the "Form:" line.
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

    # Strong match: Field Name + Data Type + Field OID somewhere in the header band.
    if has_fieldname and has_datatype and has_fieldoid:
        return True

    # Some variants omit "Field OID" in the first header row; accept if Field Name + Data Type
    # appear and a typical multi-column header exists ("Units"/"Values"/"Include").
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

    # Locate header row y and column x landmarks.
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

    # Define Field Name column bounds using header landmarks.
    min_x = stats["min_x"]
    w = stats["w"]

    col_left = min_x + 0.02 * w
    if x_fieldname is not None:
        col_left = min(col_left, x_fieldname - 0.02 * w)

    if x_units is not None:
        col_right = x_units - 0.02 * w
    else:
        col_right = min_x + 0.45 * w

    # Candidate lines in Field Name column below the header.
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
        # Exclude value/anchor-like lines that sometimes appear in the left area.
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
        t = _norm(getattr(ln, "text", ""))
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
            # Allow wraps within a row (close in y + roughly aligned in x).
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

        # Strip a row index if it was merged into the first token (structural cleanup).
        s2 = re.sub(r"^\s*\d+\s+", "", s)
        if _has_letter(s2):
            s = _norm(s2)

        if _looks_like_code(s) or _looks_like_technical_annotation(s):
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

    # Detect right-side numeric markers (item numbers).
    markers = []
    marker_min_x = min_x + 0.62 * w
    for ln in body:
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        x = _x0(ln)
        if x >= marker_min_x and t.isdigit() and 1 <= len(t) <= 4:
            markers.append(ln)

    if not markers:
        return []

    markers.sort(key=lambda z: (_y0(z), _x0(z)))
    marker_x = max(_x0(mk) for mk in markers)  # representative right column
    left_max_x = marker_x - 0.15 * w

    # Candidate label lines left of marker column.
    left = []
    for ln in body:
        x = _x0(ln)
        if x > left_max_x:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t or _is_digits_only(t):
            continue
        # Avoid capturing obvious option anchors (e.g., "1=Yes") if they appear.
        if re.match(r"^\d+\s*=", t):
            continue
        left.append(ln)

    if not left:
        return []

    # Link each marker to nearest left label line by y.
    y_tol = 0.016 * h
    starts: List[Tuple[float, object]] = []
    for mk in markers:
        my = _y0(mk)
        cands = [ln for ln in left if abs(_y0(ln) - my) <= y_tol]
        if not cands:
            cands = [ln for ln in left if abs(_y0(ln) - my) <= 1.35 * y_tol]
        if not cands:
            continue

        # Prefer the left-most among close y matches (prompt column).
        cands.sort(key=lambda ln: (abs(_y0(ln) - my), _x0(ln)))
        lbl = cands[0]
        starts.append((_y0(lbl), lbl))

    if not starts:
        return []

    # Deduplicate starts that resolve to the same line object.
    seen_ids = set()
    uniq_starts: List[Tuple[float, object]] = []
    for y, ln in sorted(starts, key=lambda p: p[0]):
        lid = id(ln)
        if lid in seen_ids:
            continue
        seen_ids.add(lid)
        uniq_starts.append((y, ln))

    left_sorted = sorted(left, key=lambda ln: (_y0(ln), _x0(ln)))

    wrap_gap = 0.040 * h
    cont_x_slack = 0.20 * w

    results: List[str] = []
    subfields: List[str] = []

    for i, (sy, sline) in enumerate(uniq_starts):
        ey = (uniq_starts[i + 1][0] - 0.001 * h) if i + 1 < len(uniq_starts) else (stats["min_y"] + 0.92 * h)
        base_x = _x0(sline)

        # Build the main field label for this marker row.
        parts = []
        prev_y = None

        st = _norm(getattr(sline, "text", ""))
        if st:
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

            # If we see a clearly indented, colon-ended prompt, treat it as a dependent field (not a wrap).
            if x > base_x + 0.06 * w and t.endswith(":") and len(t) <= 80 and not _is_bold(ln):
                sf = _collect_wrapped_label(ln, left_sorted, y, ey, stats)
                if sf and not _looks_like_code(sf) and not _looks_like_technical_annotation(sf):
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
        if _looks_like_code(field) or _looks_like_technical_annotation(field):
            continue
        results.append(field)

    # Add dependent subfields (e.g., indented "If yes, describe:") detected structurally.
    for sf in subfields:
        if sf and _has_letter(sf) and not _looks_like_code(sf) and not _looks_like_technical_annotation(sf):
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
        if not t or _is_digits_only(t):
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

    # Consider label-like prompts in the left portion of the page.
    # Use structural constraints to avoid paragraphs and furniture.
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
        if _looks_like_code(t) or _looks_like_technical_annotation(t):
            continue

        span = _x1(ln) - _x0(ln)
        if span > max_span:
            continue

        # Prefer prompt-like line endings.
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
            if not t or _is_digits_only(t):
                continue
            if _looks_like_code(t) or _looks_like_technical_annotation(t):
                continue
            # Stop if another prompt-start is encountered.
            if (t.endswith(":") or t.endswith("?")) and _x0(nxt) <= base_x + 0.02 * w and parts:
                break
            parts.append(t)
            used_ids.add(id(nxt))
            prev_y = y

        field = _norm(" ".join(parts))
        if not field or not _has_letter(field):
            continue
        if _looks_like_code(field) or _looks_like_technical_annotation(field):
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
