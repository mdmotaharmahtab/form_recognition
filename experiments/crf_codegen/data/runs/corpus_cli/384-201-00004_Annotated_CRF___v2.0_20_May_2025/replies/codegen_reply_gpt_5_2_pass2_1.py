```python
# Layout observed: cover-style approval form page with a large bold title near top,
# then repeated left-column bold labels (bigger font) with right-column non-bold values.
# Strategy: detect pages with >=3 left-column bold label lines and aligned right-column value lines,
# extract only the merged label text as field_name, and use the largest bold title as form_name.

import re
from typing import List, Tuple, Dict, Any


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        max_x1 = max((ln.x1 for ln in lines), default=0.0)
        max_y1 = max((ln.y1 for ln in lines), default=0.0)

        title = _find_form_title(lines, max_x1, max_y1)
        if title:
            current_form = title

        labels = _extract_left_labels_if_layout_matches(lines, max_x1, max_y1)
        if not labels:
            continue

        form_name = title or current_form or ""
        seen = set()
        for lab in labels:
            key = (form_name, lab)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": form_name, "field_name": lab, "page": page_idx0 + 1})

    return out


# ---------------- helpers ----------------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _only_punct_or_rules(s: str) -> bool:
    s2 = re.sub(r"\s+", "", s or "")
    if not s2:
        return True
    if re.fullmatch(r"[_\-–—\.]{6,}", s2):
        return True
    if re.fullmatch(r"[\*\.\-–—]+", s2):
        return True
    return False


def _meaningful_text(s: str) -> bool:
    s = _norm(s)
    if not s or _only_punct_or_rules(s):
        return False
    # Must not be only digits/symbols; allow non-Latin scripts by using isalnum density
    alnum = sum(1 for ch in s if ch.isalnum())
    digits = sum(1 for ch in s if ch.isdigit())
    if alnum < 3:
        return False
    if digits == alnum and alnum >= 3:
        return False
    return True


def _find_form_title(lines, max_x1: float, max_y1: float) -> str:
    # Largest bold line in upper area, excluding top header band and bottom footer band.
    # If multiple lines share similar size and are vertically adjacent, join them.
    top_cut = 110.0
    bot_cut = max_y1 - 90.0

    cands = []
    for ln in lines:
        if not ln.bold:
            continue
        if ln.y0 < top_cut or ln.y0 > bot_cut:
            continue
        if ln.size < 16.0:
            continue
        txt = _norm(ln.text)
        if not _meaningful_text(txt):
            continue
        # avoid narrow left-column labels: require reasonably wide or centered-ish
        if ln.x0 < 45.0:
            continue
        cands.append(ln)

    if not cands:
        return ""

    max_size = max(ln.size for ln in cands)
    near = [ln for ln in cands if ln.size >= max_size - 0.6]

    # Prefer ones not hugging the left edge (likely title)
    near.sort(key=lambda ln: (abs(((ln.x0 + ln.x1) / 2.0) - (max_x1 / 2.0)), ln.y0))

    base = near[0]
    base_txt = _norm(base.text)

    # Join with following lines of same size that are very close vertically and overlap in x span
    join = [base]
    for ln in cands:
        if ln is base:
            continue
        if abs(ln.size - base.size) > 0.6:
            continue
        if abs(ln.x0 - base.x0) > 80.0 and abs(((ln.x0 + ln.x1) / 2.0) - ((base.x0 + base.x1) / 2.0)) > 80.0:
            continue
        if 0.0 < (ln.y0 - base.y0) <= (base.size * 1.6 + 6.0):
            # require some horizontal overlap (titles often aligned)
            overlap = min(base.x1, ln.x1) - max(base.x0, ln.x0)
            if overlap >= 40.0:
                join.append(ln)

    join.sort(key=lambda ln: ln.y0)
    txt = _norm(" ".join(_norm(ln.text) for ln in join))
    if _meaningful_text(txt):
        return txt
    return base_txt if _meaningful_text(base_txt) else ""


def _extract_left_labels_if_layout_matches(lines, max_x1: float, max_y1: float) -> List[str]:
    # Identify left-column bold labels and ensure there is a right-column value column
    # aligned with at least a couple of those labels.
    top_cut = 140.0
    bot_cut = max_y1 - 110.0

    left = []
    right = []

    for ln in lines:
        if ln.y0 < top_cut or ln.y0 > bot_cut:
            continue
        txt = _norm(ln.text)
        if not txt:
            continue

        # left label candidates: bold, larger font, near left margin
        if ln.bold and ln.size >= 14.6 and ln.x0 <= 150.0 and _meaningful_text(txt):
            # avoid long paragraph-like bold statements by requiring modest width
            if (ln.x1 - ln.x0) <= 350.0:
                left.append(ln)

        # right value candidates: non-bold, standard body size, right of label column
        if (not ln.bold) and 10.0 <= ln.size <= 13.2 and 160.0 <= ln.x0 <= 320.0 and _meaningful_text(txt):
            right.append(ln)

    if len(left) < 3:
        return []

    # Build quick y index for right-column lines
    # Use banding because y positions can vary slightly.
    y_bins = {}
    for ln in right:
        key = int(round(ln.y0 / 3.0))
        y_bins.setdefault(key, []).append(ln)

    # Check alignment: at least 2 left labels have a right value line close in y
    aligned = 0
    for ln in left:
        key = int(round(ln.y0 / 3.0))
        found = False
        for k in (key - 1, key, key + 1):
            for rln in y_bins.get(k, []):
                if abs(rln.y0 - ln.y0) <= 4.0:
                    found = True
                    break
            if found:
                break
        if found:
            aligned += 1
    if aligned < 2:
        return []

    # Sort and merge wrapped label lines
    left.sort(key=lambda ln: (ln.y0, ln.x0))

    merged = []
    i = 0
    while i < len(left):
        a = left[i]
        parts = [_norm(a.text)]
        j = i + 1
        while j < len(left):
            b = left[j]
            # continuation if same left margin-ish, similar font, and small vertical gap
            if abs(b.x0 - a.x0) <= 14.0 and abs(b.size - a.size) <= 0.8 and b.bold == a.bold:
                gap = b.y0 - left[j - 1].y0
                if 0.0 < gap <= (a.size * 1.25 + 6.0):
                    parts.append(_norm(b.text))
                    j += 1
                    continue
            break

        lab = _norm(" ".join(p for p in parts if p))
        # Avoid pulling column headers, legends, etc. by rejecting overly short or rule-like strings
        if _meaningful_text(lab) and not _only_punct_or_rules(lab):
            merged.append(lab)

        i = j

    return merged
```
