```python
# Observed layouts: annotated CRF with (a) blue section titles near top-left, and
# (b) red bracketed machine field codes near the entry area. Field labels are
# black text near each code (often to the left, sometimes aligned by x/y).
# Strategy: carry forward the last detected section title as form_name; extract
# field_name by anchoring on bracketed codes and merging wrapped label lines.

import re
import unicodedata
from typing import List, Tuple, Dict, Any

_RE_BRACKET_CODE = re.compile(r"^\[[A-Z0-9]{2,}\]$")
_RE_TOC_NUM = re.compile(r"^\d+(?:\.\d+)*\.\s+\S")
_RE_ROW = re.compile(r"^Row\s+\d+\s*$", re.IGNORECASE)


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        # Precompute size stats for tolerant title detection
        sizes = sorted([float(getattr(l, "size", 0.0) or 0.0) for l in lines if getattr(l, "text", "").strip()])
        if not sizes:
            continue
        med = _quantile_sorted(sizes, 0.5)
        p90 = _quantile_sorted(sizes, 0.9)
        p97 = _quantile_sorted(sizes, 0.97)

        # Identify bracket-code anchors
        code_lines = []
        for i, l in enumerate(lines):
            t = _norm(l.text)
            if _is_field_code_line(l, t):
                code_lines.append((i, l, t))

        # Detect TOC-like pages (numbered blue lists) and skip extraction
        if not code_lines and _looks_like_toc(lines, med):
            # Still allow a document-wide title update if strongly present
            title = _detect_title(lines, med, p90, p97)
            if title:
                current_form = title
            continue

        # Detect/update current form title
        title = _detect_title(lines, med, p90, p97)
        if title:
            current_form = title

        # Extract fields primarily via code anchors
        seen_on_page = set()
        if code_lines:
            code_y = [cl[1].y0 for cl in code_lines]
            code_y_sorted = sorted(code_y)

            for idx, code_l, _code_t in code_lines:
                label = _label_for_code(lines, code_l, code_y_sorted)
                if not label:
                    continue
                form_name = current_form or ""
                key = (form_name, label)
                if key in seen_on_page:
                    continue
                seen_on_page.add(key)
                out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})
        else:
            # Fallback: if no codes, extract prominent left-column questions (rare in annotated CRFs)
            # Keep conservative to avoid furniture/options.
            for label in _fallback_left_questions(lines, med, p90):
                form_name = current_form or ""
                key = (form_name, label)
                if key in seen_on_page:
                    continue
                seen_on_page.add(key)
                out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})

    return out


def _norm(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _quantile_sorted(xs: List[float], q: float) -> float:
    if not xs:
        return 0.0
    if q <= 0:
        return float(xs[0])
    if q >= 1:
        return float(xs[-1])
    n = len(xs)
    pos = (n - 1) * q
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return float(xs[lo] * (1.0 - frac) + xs[hi] * frac)


def _is_field_code_line(l: Any, t: str) -> bool:
    if not t:
        return False
    if not getattr(l, "non_black", False):
        return False
    if not _RE_BRACKET_CODE.match(t):
        return False
    # Exclude common technical brackets (they include spaces/colons anyway, but be safe)
    if t.startswith("[TYPE") or t.startswith("[VISIBILITY") or t.startswith("[Read"):
        return False
    return True


def _looks_like_toc(lines: List[Any], med_size: float) -> bool:
    # TOC pages in samples are dominated by non-black (blue) numbered entries at left.
    n = len(lines)
    if n < 12:
        return False
    left = [l for l in lines if getattr(l, "x0", 0.0) < 200 and getattr(l, "y0", 0.0) > 20]
    if len(left) < 10:
        return False
    num_like = 0
    blue_like = 0
    for l in left:
        t = _norm(l.text)
        if _RE_TOC_NUM.match(t):
            num_like += 1
        if getattr(l, "non_black", False) and float(getattr(l, "size", 0.0) or 0.0) >= max(10.0, med_size * 0.9):
            blue_like += 1
    return num_like >= 8 and blue_like >= 8


def _detect_title(lines: List[Any], med: float, p90: float, p97: float) -> str:
    # Prefer prominent colored title near top-left (common in CRFs).
    # Also allow bold large black titles.
    candidates = []
    for l in lines:
        t = _norm(l.text)
        if not t:
            continue
        if t.startswith("[") and t.endswith("]"):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if y0 > 130 or x0 > 260:
            continue

        is_big = sz >= max(p90 * 0.88, med * 1.35, 12.0)
        is_colored = bool(getattr(l, "non_black", False))
        is_bold = bool(getattr(l, "bold", False))

        if is_big and (is_colored or is_bold):
            # Score: larger, higher on page, more left, longer text
            score = (sz / (p97 or sz or 1.0)) * 3.0 + (1.0 - min(y0, 130.0) / 130.0) * 2.0 + (1.0 - min(x0, 260.0) / 260.0)
            score += min(len(t), 80) / 80.0
            if is_colored:
                score += 0.5
            candidates.append((score, t))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


def _looks_like_option(l: Any, t: str) -> bool:
    if not t:
        return True
    x0 = float(getattr(l, "x0", 0.0) or 0.0)
    sz = float(getattr(l, "size", 0.0) or 0.0)
    if x0 < 320:
        return False
    if sz < 7.0 or sz > 12.0:
        return False
    # Very short, 1-2 token, mostly letters/digits -> likely option cell text.
    toks = t.split()
    if len(toks) <= 2 and len(t) <= 10:
        alnum = sum(1 for ch in t if ch.isalnum())
        if alnum >= max(2, len(t) - 1):
            return True
    return False


def _is_labelish_line(l: Any, t: str) -> bool:
    if not t:
        return False
    if t.startswith("[") and t.endswith("]"):
        return False
    if _RE_ROW.match(t):
        return False
    if _looks_like_option(l, t):
        return False
    # Must contain at least one letter (any script) or be long enough with digits/words.
    has_letter = any(unicodedata.category(ch).startswith("L") for ch in t)
    if not has_letter:
        # allow some non-letter labels if clearly not furniture
        if len(t) < 6:
            return False
        if sum(ch.isalnum() for ch in t) < 4:
            return False
    # Avoid pure punctuation
    if all(unicodedata.category(ch).startswith("P") or ch.isspace() for ch in t):
        return False
    return True


def _label_for_code(lines: List[Any], code_l: Any, code_y_sorted: List[float]) -> str:
    cx = float(getattr(code_l, "x0", 0.0) or 0.0)
    cy = float(getattr(code_l, "y0", 0.0) or 0.0)

    # Define a local band bounded by neighboring codes to avoid swallowing across fields.
    prev_y = None
    next_y = None
    # find neighbors in sorted y list
    for y in code_y_sorted:
        if y < cy - 1e-6:
            prev_y = y
        elif y > cy + 1e-6:
            next_y = y
            break
    band_top = max(0.0, (prev_y + cy) / 2.0) if prev_y is not None else max(0.0, cy - 80.0)
    band_bot = (cy + next_y) / 2.0 if next_y is not None else cy + 120.0

    # Candidate 1: label to the left, near same y
    best = None
    best_score = -1e9
    for l in lines:
        t = _norm(l.text)
        if not _is_labelish_line(l, t):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if y0 < band_top or y0 > band_bot:
            continue
        if x0 >= cx - 20:
            continue
        dy = abs(y0 - cy)
        if dy > 80:
            continue
        # Prefer lines just above/at the code's y (common)
        bias = 0.2 if y0 <= cy + 8 else 0.0
        score = -dy + bias * 10.0 + (1.5 if getattr(l, "bold", False) else 0.0) + sz * 0.05
        # Prefer left-column labels
        if x0 < 200:
            score += 1.0
        # Prefer longer text
        score += min(len(t), 80) * 0.01
        if score > best_score:
            best_score = score
            best = l

    # Candidate 2: same-x association (for repeated groups like row labels)
    if best is None:
        for l in lines:
            t = _norm(l.text)
            if not _is_labelish_line(l, t):
                continue
            x0 = float(getattr(l, "x0", 0.0) or 0.0)
            y0 = float(getattr(l, "y0", 0.0) or 0.0)
            sz = float(getattr(l, "size", 0.0) or 0.0)
            if y0 < band_top or y0 > band_bot:
                continue
            dx = abs(x0 - cx)
            dy = abs(y0 - cy)
            if dx > 70 or dy > 70:
                continue
            score = -(dy * 1.2 + dx * 0.6) + (1.0 if getattr(l, "bold", False) else 0.0) + sz * 0.03
            score += min(len(t), 80) * 0.01
            if score > best_score:
                best_score = score
                best = l

    # Candidate 3: label below-left if needed
    if best is None:
        for l in lines:
            t = _norm(l.text)
            if not _is_labelish_line(l, t):
                continue
            x0 = float(getattr(l, "x0", 0.0) or 0.0)
            y0 = float(getattr(l, "y0", 0.0) or 0.0)
            if y0 < cy + 2 or y0 > cy + 110:
                continue
            if y0 < band_top or y0 > band_bot:
                continue
            if x0 >= cx - 20:
                continue
            dy = y0 - cy
            score = -dy + (1.0 if getattr(l, "bold", False) else 0.0) + min(len(t), 80) * 0.01
            if score > best_score:
                best_score = score
                best = l

    if best is None:
        return ""

    # Merge wrapped lines starting at best
    start_i = _find_line_index(lines, best)
    if start_i < 0:
        return _norm(best.text)

    base_x = float(getattr(best, "x0", 0.0) or 0.0)
    base_sz = float(getattr(best, "size", 0.0) or 0.0)
    max_gap = max(12.0, base_sz * 1.9)

    parts = []
    prev_y = None
    for j in range(start_i, len(lines)):
        l = lines[j]
        t = _norm(l.text)
        if not t:
            continue

        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 < band_top or y0 > band_bot:
            if parts:
                break
            continue

        # Stop if we hit another code/technical bracket line in the label flow
        if t.startswith("[") and t.endswith("]"):
            if parts:
                break
            continue

        if not _is_labelish_line(l, t):
            if parts and prev_y is not None and (y0 - prev_y) > max_gap:
                break
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)

        if not parts:
            parts.append(t)
            prev_y = y0
            continue

        # Continuation criteria: near in y, similar x, similar size, and not drifting to far-right option column.
        if prev_y is not None and (y0 - prev_y) > max_gap:
            break
        if abs(x0 - base_x) > 28 and x0 > 220:
            break
        if base_sz and sz and abs(sz - base_sz) > 2.6:
            # allow bold header followed by same-size continuation; otherwise stop
            if not (getattr(lines[start_i], "bold", False) and not getattr(l, "bold", False) and abs(sz - base_sz) <= 3.5):
                break
        if _looks_like_option(l, t):
            break

        parts.append(t)
        prev_y = y0

        # If line ends with strong terminator, likely end of label
        if t.endswith("?") or t.endswith(":"):
            break

    label = _norm(" ".join(parts))
    # Final sanity filters
    if not label or _RE_ROW.match(label):
        return ""
    if label.startswith("[") and label.endswith("]"):
        return ""
    if len(label) <= 2:
        return ""
    return label


def _find_line_index(lines: List[Any], target: Any) -> int:
    # Prefer identity match; fallback to coordinate/text match.
    for i, l in enumerate(lines):
        if l is target:
            return i
    tx = getattr(target, "x0", None)
    ty = getattr(target, "y0", None)
    tt = _norm(getattr(target, "text", ""))
    for i, l in enumerate(lines):
        if _norm(getattr(l, "text", "")) == tt and getattr(l, "x0", None) == tx and getattr(l, "y0", None) == ty:
            return i
    return -1


def _fallback_left_questions(lines: List[Any], med: float, p90: float) -> List[str]:
    # Conservative: left-column, black-ish, sentence-like (longer), not furniture/options.
    labels = []
    seen = set()
    for l in lines:
        t = _norm(l.text)
        if not t:
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)

        if y0 < 70:  # likely header zone
            continue
        if x0 > 220:
            continue
        if getattr(l, "non_black", False):
            continue  # avoid colored/gray option-like text
        if sz > p90 * 0.95:
            continue  # likely title/subtitle handled elsewhere
        if sz < max(6.5, med * 0.6) or sz > max(11.5, med * 1.25):
            continue
        if not _is_labelish_line(l, t):
            continue
        if len(t) < 12:
            continue

        if t in seen:
            continue
        seen.add(t)
        labels.append(t)

    return labels
```
