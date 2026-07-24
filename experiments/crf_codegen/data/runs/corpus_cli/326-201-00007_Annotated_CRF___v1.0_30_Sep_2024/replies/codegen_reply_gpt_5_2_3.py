```python
import re
import unicodedata
from collections import Counter
from statistics import median

_WS_RE = re.compile(r"\s+")
_UNDERSCORE_RE = re.compile(r"_")
_MACHINEISH_RE = re.compile(r"^\s*\[[^\]]+\]\s*(?:SAS:)?", re.I)
_CODEY_TOKEN_RE = re.compile(r"\b[A-Z]{2,}\d{3,}\b|\b\d{5,}\b")
_TRAIL_PAREN_RE = re.compile(r"\s*\(([^()]*)\)\s*$")


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def _has_alpha(s: str) -> bool:
    for ch in s or "":
        if ch.isalpha():
            return True
        if unicodedata.category(ch).startswith("L"):
            return True
    return False


def _is_footer(ln) -> bool:
    return getattr(ln, "y0", 0.0) >= 720


def _contains_codey_token(t: str) -> bool:
    return bool(_CODEY_TOKEN_RE.search(t or ""))


def _all_capsish(t: str) -> bool:
    s = re.sub(r"[^A-Za-z]+", "", t or "")
    return bool(s) and s.isupper() and len(s) >= 10


def _max_us_run(t: str) -> int:
    best = 0
    cur = 0
    for ch in t or "":
        if ch == "_":
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


def _infer_body_size(lines) -> float:
    sizes = [
        getattr(ln, "size", 0.0)
        for ln in lines
        if 130 <= getattr(ln, "y0", 0.0) <= 710
        and not _is_footer(ln)
        and not getattr(ln, "non_black", False)
        and (getattr(ln, "text", "") or "").strip()
    ]
    return float(median(sizes)) if sizes else 10.0


def _infer_label_x(lines, body_size: float) -> float:
    xs = []
    for ln in lines:
        if getattr(ln, "y0", 0.0) < 120 or _is_footer(ln):
            continue
        if getattr(ln, "non_black", False):
            continue
        if not (body_size - 2.5 <= getattr(ln, "size", 0.0) <= body_size + 3.5):
            continue
        if not getattr(ln, "bold", False):
            continue
        if getattr(ln, "x0", 0.0) < 90:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        if _MACHINEISH_RE.match(t):
            continue
        if _UNDERSCORE_RE.search(t):
            continue
        if _contains_codey_token(t):
            continue
        if not _has_alpha(t):
            continue
        xs.append(getattr(ln, "x0", 0.0))
    return float(median(xs)) if xs else 170.0


def _is_date_placeholder_row(ln, body_size: float) -> bool:
    if getattr(ln, "x0", 0.0) > 90:
        return False
    if getattr(ln, "non_black", False):
        return False
    if not (body_size - 2.5 <= getattr(ln, "size", 0.0) <= body_size + 3.5):
        return False
    t = (getattr(ln, "text", "") or "").strip()
    if not t:
        return False
    if "-" not in t:
        return False
    if t.count("_") < 6:
        return False
    if len(t) < 8:
        return False
    return True


def _is_value_placeholder(ln, body_size: float) -> bool:
    # Generic input line mostly underscores (not the left-column date placeholder)
    if getattr(ln, "x0", 0.0) <= 90:
        return False
    if getattr(ln, "non_black", False):
        return False
    if not (body_size - 2.6 <= getattr(ln, "size", 0.0) <= body_size + 4.1):
        return False

    t = (getattr(ln, "text", "") or "").strip()
    if not t:
        return False

    # Must be underscore-dominant and not contain letters.
    if _has_alpha(t):
        return False

    us = t.count("_")
    if us < 3:
        return False
    if _max_us_run(t) < 4:
        return False
    if len(t) < 4:
        return False

    # Allow limited punctuation/spaces around underscores; avoid line-art noise.
    non_us = [ch for ch in t if ch != "_" and not ch.isspace()]
    if len(non_us) > max(6, len(t) // 5):
        return False

    return True


def _is_colonish_label_text(t: str) -> bool:
    tt = (t or "").strip()
    if not tt:
        return False
    # Includes full-width colon too.
    return tt.endswith(":") or tt.endswith("：")


def _strip_inline_placeholder_tail(t: str) -> str:
    s = _norm(t)
    if not s:
        return s
    if "_" not in s:
        return s
    # If there's a substantial underscore run and the tail has no alpha, drop it.
    pos = s.find("_")
    if pos <= 0:
        return s
    head = _norm(s[:pos])
    tail = s[pos:]
    if not head:
        return s
    if _has_alpha(tail):
        return s
    if _max_us_run(tail) >= 4 and tail.count("_") >= 4:
        return head
    return s


def _keep_parenthetical(inside: str) -> bool:
    s = _norm(inside)
    if not s:
        return False
    # Keep short, label-like qualifiers (e.g., "Specify"), drop long instruction blocks.
    if len(s) <= 18 and len(s.split()) <= 2 and all(ch not in s for ch in [",", ";", "—", "–"]):
        return True
    # Keep compact format hints like "mm/dd/yyyy" or "24-hour".
    if len(s) <= 16 and re.search(r"[0-9/]", s):
        return True
    return False


def _strip_trailing_annotations(t: str) -> str:
    s = _norm(t)
    if not s:
        return s

    # Remove trailing parenthetical blocks that are long/instructional.
    while True:
        m = _TRAIL_PAREN_RE.search(s)
        if not m:
            break
        inside = (m.group(1) or "").strip()
        if _keep_parenthetical(inside):
            break
        s = _norm(s[: m.start()])

    # Remove trailing dash-clause that reads like an instruction (not part of label).
    for sep in [" — ", " – ", " - "]:
        if sep in s:
            left, right = s.rsplit(sep, 1)
            r = _norm(right)
            if len(r) >= 28 and len(r.split()) >= 5:
                s = _norm(left)
                break

    return s


def _clean_field_label_text(t: str) -> str:
    s = _strip_inline_placeholder_tail(t)
    s = _norm(s)
    if not s:
        return ""
    if s.endswith(":") or s.endswith("："):
        s = _norm(s[:-1])
    s = _strip_trailing_annotations(s)
    s = _norm(s)
    if not s:
        return ""
    if not _has_alpha(s):
        return ""
    if _MACHINEISH_RE.match(s):
        return ""
    return s


def _find_top_field_y(lines, body_size: float):
    ys = []
    for ln in lines:
        y0 = getattr(ln, "y0", 0.0)
        if y0 < 120 or _is_footer(ln):
            continue
        if _is_date_placeholder_row(ln, body_size) or _is_value_placeholder(ln, body_size):
            ys.append(y0)
            continue
        if getattr(ln, "non_black", False):
            continue
        if not (body_size - 2.6 <= getattr(ln, "size", 0.0) <= body_size + 3.7):
            continue
        t = _norm(getattr(ln, "text", ""))
        if _is_colonish_label_text(t):
            ct = _clean_field_label_text(t)
            if ct:
                ys.append(y0)
    return min(ys) if ys else None


def _build_furniture_texts(pages):
    # Detect repeated header-like lines across many pages; used to suppress form titles.
    counts = Counter()
    total = 0
    for _page_idx0, lines in pages:
        total += 1
        seen = set()
        for ln in lines or []:
            if _is_footer(ln):
                continue
            if getattr(ln, "non_black", False):
                continue
            y0 = getattr(ln, "y0", 0.0)
            if y0 > 115:
                continue
            x0 = getattr(ln, "x0", 0.0)
            if x0 < 18:
                continue
            t = _norm(getattr(ln, "text", ""))
            if not t or len(t) < 10:
                continue
            if _UNDERSCORE_RE.search(t):
                continue
            if not _has_alpha(t):
                continue
            # Only treat as furniture candidate if it looks like metadata, not a plain title.
            if not (_contains_codey_token(t) or t.count(":") >= 2 or _all_capsish(t)):
                continue
            seen.add(t)
        for t in seen:
            counts[t] += 1

    if total <= 0:
        return set()

    thr = max(8, int(total * 0.16))
    return {t for t, c in counts.items() if c >= thr}


def _pick_form_title(lines, body_size: float, band_y_max: float, furniture_texts: set):
    cands = []
    for ln in lines:
        if _is_footer(ln):
            continue
        y0 = getattr(ln, "y0", 0.0)
        if y0 > band_y_max:
            continue
        if getattr(ln, "x0", 0.0) < 28:
            continue
        if getattr(ln, "non_black", False):
            continue

        raw = getattr(ln, "text", "") or ""
        t = _norm(raw)
        if not t:
            continue
        if t in furniture_texts:
            continue
        if _UNDERSCORE_RE.search(t):
            continue
        if _MACHINEISH_RE.match(t):
            continue
        if _is_colonish_label_text(t):
            continue
        if not _has_alpha(t):
            continue

        # Avoid header metadata / machine-code-bearing lines being used as form names.
        if _contains_codey_token(t):
            continue

        size = getattr(ln, "size", 0.0)
        size_up = size - body_size
        bold = getattr(ln, "bold", False)

        # Title-ish: larger, or bold in upper band.
        titleish = (size_up >= 0.7) or (bold and y0 <= 155 and size_up >= -0.25)
        if not titleish:
            continue

        cands.append(ln)

    if not cands:
        return None

    def line_score(ln):
        t = _norm(getattr(ln, "text", ""))
        size = getattr(ln, "size", 0.0)
        bold = getattr(ln, "bold", False)
        y0 = getattr(ln, "y0", 0.0)
        size_up = size - body_size
        # Prefer larger/bold and not too low in the band; modestly prefer longer.
        return (size * 120.0) + (28.0 if bold else 0.0) + (min(len(t), 140) / 2.2) + (size_up * 48.0) - (y0 / 42.0)

    anchor = max(cands, key=line_score)
    a_size = getattr(anchor, "size", 0.0)
    a_y = getattr(anchor, "y0", 0.0)

    block = []
    for ln in cands:
        if abs(getattr(ln, "size", 0.0) - a_size) > 1.5:
            continue
        y0 = getattr(ln, "y0", 0.0)
        if y0 < a_y - 2.0:
            continue
        if y0 > a_y + 34.0:
            continue
        if getattr(ln, "x0", 0.0) > 560:
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t or t in furniture_texts:
            continue
        if _contains_codey_token(t):
            continue
        block.append(ln)

    block.sort(key=lambda l: (getattr(l, "y0", 0.0), getattr(l, "x0", 0.0)))
    text = _norm(" ".join(_norm(getattr(l, "text", "")) for l in block if _norm(getattr(l, "text", ""))))

    text = _strip_trailing_annotations(text)

    if len(text) < 6:
        return None
    if not any((getattr(l, "size", 0.0) - body_size) >= 0.7 or getattr(l, "bold", False) for l in block):
        return None
    if _contains_codey_token(text):
        return None
    return text


def _find_aligned_label(lines, y, label_x, body_size: float):
    best = None
    best_dx = None
    for ln in lines:
        if abs(getattr(ln, "y0", 0.0) - y) > 3.2:
            continue
        if getattr(ln, "non_black", False):
            continue
        if not (body_size - 2.6 <= getattr(ln, "size", 0.0) <= body_size + 3.6):
            continue
        if getattr(ln, "x0", 0.0) < 110:
            continue
        if abs(getattr(ln, "x0", 0.0) - label_x) > 165:
            continue
        raw = getattr(ln, "text", "") or ""
        t = _norm(raw)
        if not t:
            continue
        if _MACHINEISH_RE.match(t):
            continue

        ct = _clean_field_label_text(t)
        if not ct:
            continue

        dx = abs(getattr(ln, "x0", 0.0) - label_x) + (0.0 if getattr(ln, "bold", False) else 55.0)
        if best is None or dx < best_dx:
            best = ln
            best_dx = dx
    return best


def _find_label_left_of_placeholder(lines, ph_ln, label_x, body_size: float):
    best = None
    best_score = None
    y = getattr(ph_ln, "y0", 0.0)
    x_limit = getattr(ph_ln, "x0", 0.0) - 6.0

    for ln in lines:
        if abs(getattr(ln, "y0", 0.0) - y) > 4.8:
            continue
        if getattr(ln, "non_black", False):
            continue
        if not (body_size - 2.8 <= getattr(ln, "size", 0.0) <= body_size + 3.8):
            continue
        x0 = getattr(ln, "x0", 0.0)
        if x0 < 70:
            continue
        if x0 >= x_limit:
            continue
        if abs(x0 - label_x) > 210:
            continue

        raw = getattr(ln, "text", "") or ""
        t = _norm(raw)
        if not t:
            continue
        if _MACHINEISH_RE.match(t):
            continue

        ct = _clean_field_label_text(t)
        if not ct:
            continue

        score = abs(x0 - label_x) + max(0.0, (x_limit - x0) / 42.0) + (0.0 if getattr(ln, "bold", False) else 18.0)
        if best is None or score < best_score:
            best = ln
            best_score = score

    return best


def _collect_wrapped(lines, start_ln, body_size: float):
    x0 = getattr(start_ln, "x0", 0.0)
    y0 = getattr(start_ln, "y0", 0.0)
    want_bold = bool(getattr(start_ln, "bold", False))
    parts = [_norm(getattr(start_ln, "text", ""))]
    prev_y = y0
    max_span = 46.0
    gap = 16.5

    cands = []
    for ln in lines:
        if ln is start_ln:
            continue
        y = getattr(ln, "y0", 0.0)
        if y <= y0:
            continue
        if y > y0 + max_span:
            continue
        if getattr(ln, "non_black", False):
            continue
        if not (body_size - 2.8 <= getattr(ln, "size", 0.0) <= body_size + 3.9):
            continue
        if abs(getattr(ln, "x0", 0.0) - x0) > 18.0:
            continue
        if want_bold and not getattr(ln, "bold", False):
            continue

        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        if _MACHINEISH_RE.match(t):
            continue
        if _UNDERSCORE_RE.search(t):
            continue
        if not _has_alpha(t):
            continue

        cands.append(ln)

    cands.sort(key=lambda l: (getattr(l, "y0", 0.0), getattr(l, "x0", 0.0)))
    for ln in cands:
        y = getattr(ln, "y0", 0.0)
        if y - prev_y > gap:
            break
        parts.append(_norm(getattr(ln, "text", "")))
        prev_y = y

    return _norm(" ".join(p for p in parts if p))


def _colon_has_input_evidence(lines, start_ln, body_size: float) -> bool:
    y0 = getattr(start_ln, "y0", 0.0)
    x0 = getattr(start_ln, "x0", 0.0)

    # Inline underscore tail on same line counts as evidence.
    t = _norm(getattr(start_ln, "text", ""))
    if t.count("_") >= 3 and _max_us_run(t) >= 4:
        tail = t[t.find("_") :]
        if not _has_alpha(tail):
            return True

    # Nearby placeholder on the same row (to the right).
    for ln in lines:
        if ln is start_ln:
            continue
        if abs(getattr(ln, "y0", 0.0) - y0) > 4.8:
            continue
        if getattr(ln, "x0", 0.0) <= x0 + 40:
            continue
        if _is_value_placeholder(ln, body_size):
            return True

    # Placeholder slightly below/right (common with colon label then line underneath).
    for ln in lines:
        if ln is start_ln:
            continue
        y = getattr(ln, "y0", 0.0)
        if y <= y0 or y > y0 + 22.0:
            continue
        if getattr(ln, "x0", 0.0) < x0 - 8:
            continue
        if _is_value_placeholder(ln, body_size):
            return True

    return False


def extract(pages):
    pages_list = list(pages or [])
    out = []
    current_form = ""

    furniture_texts = _build_furniture_texts(pages_list)

    for page_idx0, lines in pages_list:
        if not lines:
            continue

        body_size = _infer_body_size(lines)
        label_x = _infer_label_x(lines, body_size)

        # Update carried form name using a per-page title found above the first fields.
        top_field_y = _find_top_field_y(lines, body_size)
        band_y_max = 170.0
        if top_field_y is not None:
            band_y_max = max(140.0, min(270.0, top_field_y - 6.0))

        fm = _pick_form_title(lines, body_size, band_y_max, furniture_texts)
        if fm:
            current_form = fm

        seen = set()

        # Extract fields triggered by left-column date placeholders.
        for ln in lines:
            if _is_footer(ln) or getattr(ln, "y0", 0.0) < 120:
                continue
            if not _is_date_placeholder_row(ln, body_size):
                continue

            yk = int(round(getattr(ln, "y0", 0.0)))
            if ("date_row", yk) in seen:
                continue
            seen.add(("date_row", yk))

            start = _find_aligned_label(lines, getattr(ln, "y0", 0.0), label_x, body_size)
            if not start:
                continue

            field = _collect_wrapped(lines, start, body_size)
            field = _clean_field_label_text(field)
            if not field:
                continue

            out.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

        # Additional extraction: labels aligned to underscore input lines.
        for ln in lines:
            if _is_footer(ln) or getattr(ln, "y0", 0.0) < 120:
                continue
            if not _is_value_placeholder(ln, body_size):
                continue

            start = _find_label_left_of_placeholder(lines, ln, label_x, body_size)
            if not start:
                continue

            key = ("val_row", int(round(getattr(start, "y0", 0.0))), int(round(getattr(start, "x0", 0.0))))
            if key in seen:
                continue
            seen.add(key)

            field = _collect_wrapped(lines, start, body_size)
            field = _clean_field_label_text(field)
            if not field:
                continue

            out.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

        # Additional extraction: colon-ended labels (e.g., staff initials/comment boxes).
        for ln in lines:
            if _is_footer(ln) or getattr(ln, "y0", 0.0) < 120:
                continue
            if getattr(ln, "non_black", False):
                continue
            if not (body_size - 2.8 <= getattr(ln, "size", 0.0) <= body_size + 3.9):
                continue

            raw = getattr(ln, "text", "") or ""
            t = _norm(raw)
            if not _is_colonish_label_text(t):
                continue

            # Must look like a human label.
            if _MACHINEISH_RE.match(t):
                continue

            # Evidence gating: either inline/nearby placeholder, or in the bottom band.
            if not _colon_has_input_evidence(lines, ln, body_size):
                if getattr(ln, "y0", 0.0) < 610:
                    # Also allow colon fields near label column if bold (common for short fields),
                    # but still avoid pulling arbitrary "X:" headings.
                    if not getattr(ln, "bold", False):
                        continue
                    if abs(getattr(ln, "x0", 0.0) - label_x) > 220:
                        continue

            key = ("colon", int(round(getattr(ln, "y0", 0.0))), int(round(getattr(ln, "x0", 0.0))))
            if key in seen:
                continue

            field = _collect_wrapped(lines, ln, body_size)
            field = _clean_field_label_text(field)
            if not field:
                continue

            seen.add(key)
            out.append({"form_name": current_form or "", "field_name": field, "page": page_idx0 + 1})

    return out
```
