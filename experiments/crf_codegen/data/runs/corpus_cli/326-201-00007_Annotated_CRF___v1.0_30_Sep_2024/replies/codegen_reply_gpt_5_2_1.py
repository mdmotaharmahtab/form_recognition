```python
# Observed layout: every page has a fixed top header band and repeated "activity" blocks below.
# Each data-entry question label is printed in the main label column (mid-page x) and is aligned
# to a left-column date placeholder line made of underscores (with hyphens). Labels may wrap to
# 2–4 nearby lines in the same column. Strategy: carry forward the header's schedule/name as
# form_name; for each date-placeholder row, grab the aligned label and its wrapped continuations.

import re
import unicodedata
from statistics import median


_WS_RE = re.compile(r"\s+")
_UNDERSCORE_RE = re.compile(r"_")
_MACHINEISH_RE = re.compile(r"^\s*\[[^\]]+\]\s*(?:SAS:)?", re.I)


def _norm(s: str) -> str:
    s = _WS_RE.sub(" ", (s or "").strip())
    return s


def _has_alpha(s: str) -> bool:
    for ch in s:
        if ch.isalpha():
            return True
        # Some PDFs may render letters oddly; consider any Letter category as alpha-like.
        if unicodedata.category(ch).startswith("L"):
            return True
    return False


def _is_footer(line) -> bool:
    # Footer sits near bottom; avoid page number/date created lines.
    return line.y0 >= 720


def _infer_body_size(lines):
    sizes = [ln.size for ln in lines if 120 <= ln.y0 <= 715 and not _is_footer(ln)]
    return median(sizes) if sizes else 10.0


def _infer_label_x(lines, body_size):
    xs = []
    for ln in lines:
        if ln.y0 < 120 or _is_footer(ln):
            continue
        if ln.non_black:
            continue
        if not (body_size - 2.5 <= ln.size <= body_size + 3.5):
            continue
        if not ln.bold:
            continue
        if ln.x0 < 90:
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _MACHINEISH_RE.match(t):
            continue
        xs.append(ln.x0)
    if not xs:
        return 170.0
    return median(xs)


def _pick_form_name(lines):
    # Pick the one prominent non-bold value line in header band, right of the left labels.
    cands = []
    for ln in lines:
        if ln.y0 > 115:
            break
        if ln.bold:
            continue
        if ln.non_black:
            continue
        if not (10.0 <= ln.size <= 13.5):
            continue
        if ln.x0 < 120:
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _UNDERSCORE_RE.search(t):
            continue
        # Prefer slightly lower (schedule/name row), and larger size.
        score = (ln.size * 100.0) + (ln.y0 / 10.0)
        cands.append((score, t))
    if not cands:
        return None
    cands.sort(reverse=True)
    return cands[0][1]


def _is_date_placeholder_row(ln, body_size):
    if ln.x0 > 90:
        return False
    if ln.non_black:
        return False
    if not (body_size - 2.5 <= ln.size <= body_size + 3.5):
        return False
    t = (ln.text or "").strip()
    if not t:
        return False
    # Date placeholder typically includes underscores and a hyphen separator.
    if "-" not in t:
        return False
    u = t.count("_")
    if u < 6:
        return False
    # Avoid accidental matches on other short underscore artifacts.
    if len(t) < 8:
        return False
    return True


def _find_aligned_label(lines, y, label_x, body_size):
    # Find label line aligned with placeholder row y.
    best = None
    best_dx = None
    for ln in lines:
        if abs(ln.y0 - y) > 3.0:
            continue
        if ln.non_black:
            continue
        if not (body_size - 2.5 <= ln.size <= body_size + 3.5):
            continue
        if ln.x0 < 110:
            continue
        if abs(ln.x0 - label_x) > 140:
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _UNDERSCORE_RE.search(t):
            continue
        if _MACHINEISH_RE.match(t):
            continue
        if not _has_alpha(t):
            continue
        # Prefer bold; but allow non-bold fallback if nothing else.
        if best is None:
            best = ln
            best_dx = abs(ln.x0 - label_x) + (0.0 if ln.bold else 50.0)
        else:
            dx = abs(ln.x0 - label_x) + (0.0 if ln.bold else 50.0)
            if dx < best_dx:
                best = ln
                best_dx = dx
    return best


def _collect_wrapped(lines, start_ln, body_size):
    # Greedily collect up to a small vertical span of wrapped lines in same column.
    x0 = start_ln.x0
    y0 = start_ln.y0
    want_bold = start_ln.bold
    parts = [ _norm(start_ln.text) ]
    prev_y = y0
    max_span = 42.0   # enough for 3-4 lines at ~12pt leading
    gap = 16.0

    # Consider candidates in (y0, y0+max_span] that are in same column.
    cands = []
    for ln in lines:
        if ln is start_ln:
            continue
        if ln.y0 <= y0:
            continue
        if ln.y0 > y0 + max_span:
            continue
        if ln.non_black:
            continue
        if not (body_size - 2.5 <= ln.size <= body_size + 3.5):
            continue
        if abs(ln.x0 - x0) > 16.0:
            continue
        if want_bold and not ln.bold:
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _MACHINEISH_RE.match(t):
            continue
        # Avoid pulling in answer-choice content (often starts with bullets/circles/brackets)
        # by requiring at least one letter for wrapped label lines as well.
        if not _has_alpha(t):
            continue
        cands.append(ln)

    cands.sort(key=lambda l: (l.y0, l.x0))
    for ln in cands:
        if ln.y0 - prev_y > gap:
            break
        parts.append(_norm(ln.text))
        prev_y = ln.y0

    return _norm(" ".join(p for p in parts if p))


def extract(pages):
    out = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        # Update carried form name from header when present.
        fm = _pick_form_name(lines)
        if fm:
            current_form = fm

        body_size = _infer_body_size(lines)
        label_x = _infer_label_x(lines, body_size)

        # Find all date-placeholder rows and extract aligned question labels.
        # De-dupe triggers by y (rounded) to avoid double processing due to tiny drift.
        seen_y = set()
        for ln in lines:
            if _is_footer(ln) or ln.y0 < 120:
                continue
            if not _is_date_placeholder_row(ln, body_size):
                continue
            yk = int(round(ln.y0))
            if yk in seen_y:
                continue
            seen_y.add(yk)

            start = _find_aligned_label(lines, ln.y0, label_x, body_size)
            if not start:
                continue

            field = _collect_wrapped(lines, start, body_size)
            if not field or not _has_alpha(field):
                continue

            out.append(
                {"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1}
            )

    return out
```
