# Observed layouts: (1) standard CRF pages with a bold header containing "Form:" and
# left-column field prompts aligned with right-side numeric field markers; (2) annotated
# table pages with a fixed header band ("Field Name Data Type" ...) and row-wise fields.
# Strategy: carry forward the current Form title from the header; extract field labels by
# geometry (columns + y-banding) and right-marker linkage; join wrapped label lines.

import re
import unicodedata
from typing import List, Tuple, Dict, Optional


def extract(pages):
    out: List[Dict[str, object]] = []
    seen = set()

    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1

        # Update form context if present on this page
        form = _extract_form_name(lines)
        if form:
            current_form = form

        # Try table handler first if it strongly matches, else standard handler
        if _looks_like_table_page(lines):
            fields = _extract_fields_table(lines)
        else:
            fields = _extract_fields_standard(lines)

        for field in fields:
            form_name = current_form or ""
            field_name = field
            if not form_name and not field_name:
                continue
            key = (page_num, form_name, field_name)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": field_name, "page": page_num})

    return out


# ---------------- helpers ----------------

_RE_FORM = re.compile(r"^\s*Form\s*:\s*(.+?)\s*$", re.IGNORECASE)
_RE_GENERATED = re.compile(r"^\s*Generated\s+On\s*:\s*", re.IGNORECASE)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_digits_only(s: str) -> bool:
    s = _norm(s)
    return bool(s) and s.isdigit()


def _has_letter(s: str) -> bool:
    s = _norm(s)
    for ch in s:
        if ch.isalpha():
            return True
        # Some scripts/marks may not be isalpha after normalization; keep this permissive:
        cat = unicodedata.category(ch)
        if cat.startswith("L"):
            return True
    return False


def _y0(line) -> float:
    return float(getattr(line, "y0", 0.0))


def _x0(line) -> float:
    return float(getattr(line, "x0", 0.0))


def _x1(line) -> float:
    return float(getattr(line, "x1", 0.0))


def _is_bold(line) -> bool:
    return bool(getattr(line, "bold", False))


def _extract_form_name(lines) -> Optional[str]:
    # Search only in header band
    header = [ln for ln in lines if _y0(ln) <= 160.0]
    form_ln = None
    form_text = None

    for ln in header:
        m = _RE_FORM.match(_norm(ln.text))
        if m:
            form_ln = ln
            form_text = m.group(1)
            break
    if not form_ln or not form_text:
        return None

    # Join wrapped bold continuation lines between "Form:" and "Generated On:"
    base_x = _x0(form_ln)
    base_y = _y0(form_ln)

    gen_y = None
    for ln in header:
        if _RE_GENERATED.match(_norm(ln.text)):
            gen_y = _y0(ln)
            break
    if gen_y is None:
        gen_y = base_y + 60.0

    parts = [form_text]
    for ln in header:
        y = _y0(ln)
        if y <= base_y + 0.5 or y >= gen_y - 0.5:
            continue
        if not _is_bold(ln):
            continue
        if abs(_x0(ln) - base_x) > 6.0:
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _RE_GENERATED.match(t):
            break
        # Avoid accidentally pulling the study name line above
        if _RE_FORM.match(t):
            continue
        parts.append(t)

    joined = _norm(" ".join(parts))
    return joined or None


def _looks_like_table_page(lines) -> bool:
    # Template marker for the annotated CRF table header (allowed invariant landmark).
    for ln in lines:
        t = _norm(ln.text).lower()
        if "field name" in t and "data type" in t:
            # Usually in header band
            if 120.0 <= _y0(ln) <= 220.0:
                return True
    return False


def _body_lines(lines):
    # Exclude header + footer furniture bands based on observed positions
    return [ln for ln in lines if 140.0 <= _y0(ln) <= 680.0]


def _extract_fields_standard(lines) -> List[str]:
    body = _body_lines(lines)
    if not body:
        return []

    # Right-side numeric markers that correspond to fields (item numbers)
    markers = []
    for ln in body:
        t = _norm(ln.text)
        if not t:
            continue
        if _x0(ln) >= 430.0 and t.isdigit() and 1 <= len(t) <= 4:
            markers.append(ln)

    if not markers:
        return []

    # Candidate label lines in left column
    left = [ln for ln in body if _x0(ln) <= 320.0 and _x0(ln) <= 260.0 + 60.0 and _norm(ln.text)]
    left = [ln for ln in left if not _is_digits_only(ln.text)]

    # For each marker, link to nearest left label line by y
    starts = []
    for mk in markers:
        my = _y0(mk)
        # Prefer true left column
        cand = [ln for ln in left if _x0(ln) <= 260.0 and abs(_y0(ln) - my) <= 8.0]
        if not cand:
            cand = [ln for ln in left if _x0(ln) <= 320.0 and abs(_y0(ln) - my) <= 10.0]
        if not cand:
            continue
        cand.sort(key=lambda ln: (abs(_y0(ln) - my), _x0(ln)))
        lbl = cand[0]
        starts.append((float(_y0(lbl)), lbl))

    if not starts:
        return []

    # Deduplicate starts that resolve to same label line
    seen_lbl_ids = set()
    uniq_starts = []
    for y, ln in sorted(starts, key=lambda p: p[0]):
        lid = id(ln)
        if lid in seen_lbl_ids:
            continue
        seen_lbl_ids.add(lid)
        uniq_starts.append((y, ln))

    # Build fields by collecting wrapped lines until next start
    results = []
    left_by_y = sorted([ln for ln in left if _x0(ln) <= 260.0], key=lambda ln: (_y0(ln), _x0(ln)))

    for i, (sy, sलाइन) in enumerate(uniq_starts):
        ey = uniq_starts[i + 1][0] - 0.1 if i + 1 < len(uniq_starts) else 680.0
        base_x = _x0(sलाइन)

        parts = []
        prev_y = None

        # Include the start line
        st = _norm(sलाइन.text)
        if st:
            parts.append(st)
            prev_y = _y0(sलाइन)

        # Include wrapped continuation lines: close y spacing + aligned x
        for ln in left_by_y:
            y = _y0(ln)
            if y <= sy + 0.01 or y >= ey:
                continue
            if abs(_x0(ln) - base_x) > 95.0:
                continue
            t = _norm(ln.text)
            if not t or _is_digits_only(t):
                continue
            if prev_y is None:
                prev_y = y
            gap = y - prev_y
            if gap <= 24.0:
                parts.append(t)
                prev_y = y
            else:
                # Too far to be a wrap; stop to avoid swallowing instructions/paragraphs
                break

        field = _norm(" ".join(parts))
        if not field:
            continue
        if not _has_letter(field):
            continue
        results.append(field)

    return results


def _extract_fields_table(lines) -> List[str]:
    body = _body_lines(lines)
    if not body:
        return []

    header_y = None
    for ln in lines:
        t = _norm(ln.text).lower()
        if "field name" in t and "data type" in t:
            header_y = _y0(ln)
            break
    if header_y is None:
        header_y = 150.0

    # Left-side area where "Field Name" column lives
    left = [
        ln for ln in body
        if _y0(ln) >= header_y + 10.0 and _x0(ln) <= 260.0 and _norm(ln.text)
    ]

    # Row-start markers: either a separate row index (digits only near far-left),
    # or an entry starting with digits + space (combined index + field token).
    markers = []
    for ln in left:
        t = _norm(ln.text)
        x = _x0(ln)
        if x <= 120.0 and _is_digits_only(t):
            markers.append(ln)
        elif x <= 150.0 and re.match(r"^\d+\s+\S", t):
            markers.append(ln)

    markers.sort(key=lambda ln: _y0(ln))

    def pick_label_in_span(span_start_y: float, span_end_y: float) -> Optional[str]:
        cands = [
            ln for ln in left
            if span_start_y <= _y0(ln) < span_end_y and not _is_digits_only(ln.text)
        ]
        if not cands:
            return None
        # Prefer the left-most (field-name) subcolumn; ignore other subcolumns like Units at x~170.
        min_x = min(_x0(ln) for ln in cands)
        x_cut = min_x + 45.0
        cands = [ln for ln in cands if _x0(ln) <= x_cut]
        cands.sort(key=lambda ln: (_y0(ln), _x0(ln)))

        parts = []
        prev_y = None
        for ln in cands:
            t = _norm(ln.text)
            if not t:
                continue
            y = _y0(ln)
            if prev_y is None:
                parts.append(t)
                prev_y = y
                continue
            if y - prev_y <= 18.0:
                parts.append(t)
                prev_y = y
            else:
                break

        s = _norm(" ".join(parts))
        if not s or not _has_letter(s):
            return None
        return s

    results = []

    if markers:
        for i, mk in enumerate(markers):
            sy = _y0(mk) - 10.0
            ey = (_y0(markers[i + 1]) - 10.0) if i + 1 < len(markers) else 680.0
            label = pick_label_in_span(sy, ey)
            if label:
                results.append(label)
        return results

    # Fallback: no explicit markers; split by y gaps and digit-prefixed starts
    left2 = [ln for ln in left if _x0(ln) <= 200.0 and not _is_digits_only(ln.text)]
    left2.sort(key=lambda ln: (_y0(ln), _x0(ln)))

    groups = []
    cur = []
    prev_y = None
    for ln in left2:
        t = _norm(ln.text)
        y = _y0(ln)
        new_row = False
        if prev_y is not None and y - prev_y > 26.0:
            new_row = True
        if re.match(r"^\d+\s+\S", t) and cur:
            new_row = True

        if new_row:
            groups.append(cur)
            cur = []
        cur.append(ln)
        prev_y = y
    if cur:
        groups.append(cur)

    for grp in groups:
        if not grp:
            continue
        min_x = min(_x0(ln) for ln in grp)
        x_cut = min_x + 45.0
        grp2 = [ln for ln in grp if _x0(ln) <= x_cut and not _is_digits_only(ln.text)]
        grp2.sort(key=lambda ln: (_y0(ln), _x0(ln)))
        parts = []
        prev_y = None
        for ln in grp2:
            t = _norm(ln.text)
            y = _y0(ln)
            if not t:
                continue
            if prev_y is None or y - prev_y <= 18.0:
                parts.append(t)
                prev_y = y
            else:
                break
        s = _norm(" ".join(parts))
        if s and _has_letter(s):
            results.append(s)

    return results
