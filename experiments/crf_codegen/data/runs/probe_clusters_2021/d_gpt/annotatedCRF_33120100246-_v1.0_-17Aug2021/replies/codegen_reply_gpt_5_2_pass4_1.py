```python
# Observed annotated CRF pages where data-entry fields are indicated by nearby machine annotations
# like bracketed item codes ([XXXX]) and type/visibility markers ([TYPE: ...], enumeration/values).
# Strategy: track the current form title from prominent top-left headings, then for each page with
# machine annotations, anchor each field on code/type markers and recover the nearest human label
# text above/left, joining wrapped label lines and filtering obvious machine/option furniture.

import re
import unicodedata
from bisect import bisect_left


_WS_RE = re.compile(r"\s+")
_BRACKET_CODE_RE = re.compile(r"^\[[A-Za-z0-9]{2,}\]$")
_ROW_MARK_RE = re.compile(r"^[^\W\d_]{1,10}\s*\d{1,3}$", re.UNICODE)
_MOSTLY_PUNCT_NUM_RE = re.compile(r"^[\W\d_]+$", re.UNICODE)


def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00ad", "")  # soft hyphen
    s = s.replace("\u200b", "").replace("\ufeff", "")
    s = _WS_RE.sub(" ", s).strip()
    return s


def _has_letters(s: str) -> bool:
    for ch in s:
        if unicodedata.category(ch).startswith("L"):
            return True
    return False


def _looks_like_page_furniture(s: str) -> bool:
    s2 = s.strip()
    if not s2:
        return True
    if len(s2) <= 2 and (s2.isdigit() or _MOSTLY_PUNCT_NUM_RE.match(s2)):
        return True
    return False


def _is_machine_annotation_text(s: str) -> bool:
    t = s.strip()
    if not t:
        return False
    if t.startswith("["):
        return True
    tl = t.lower()
    # Template markers commonly used in annotated CRFs
    if "type:" in tl or "visibility" in tl or "read-only" in tl or "readonly" in tl:
        return True
    if "enumeration" in tl or "values:" in tl:
        return True
    if "partialdate" in tl or "partialtime" in tl:
        return True
    # Often ends with ")]" as part of type/value annotations
    if "values:" in tl and tl.endswith(")]"):
        return True
    return False


def _is_code_anchor_text(s: str) -> bool:
    t = s.strip()
    if not t:
        return False
    if _BRACKET_CODE_RE.match(t) and (":" not in t) and (" " not in t) and ("\t" not in t):
        return True
    return False


def _median(nums):
    if not nums:
        return 0.0
    nums = sorted(nums)
    n = len(nums)
    mid = n // 2
    if n % 2:
        return float(nums[mid])
    return 0.5 * (nums[mid - 1] + nums[mid])


def _estimate_page_width(lines) -> float:
    mx = 0.0
    for ln in lines:
        if ln.x1 > mx:
            mx = ln.x1
    return mx or 612.0


def _estimate_left_margin(lines) -> float:
    xs = []
    for ln in lines:
        t = _norm_text(ln.text)
        if not t:
            continue
        if _is_machine_annotation_text(t):
            continue
        if _looks_like_page_furniture(t):
            continue
        xs.append(ln.x0)
    if not xs:
        return 0.0
    xs.sort()
    return xs[max(0, min(len(xs) - 1, len(xs) // 10))]  # ~10th percentile


def _estimate_body_size(lines, page_w: float) -> float:
    sizes = []
    for ln in lines:
        t = _norm_text(ln.text)
        if not t or _is_machine_annotation_text(t):
            continue
        # ignore big titles in the top band
        if ln.y0 < 130 and ln.size >= 12:
            continue
        # ignore far-right option/value cells
        if ln.x0 > page_w * 0.75 and len(t) <= 6:
            continue
        sizes.append(float(ln.size))
    return _median(sizes) or 8.0


def _pick_form_title(lines, page_w: float, body_size: float) -> str:
    # Primary: prominent top-left heading (often colored) around 14+ pt
    cands = []
    for ln in lines:
        t = _norm_text(ln.text)
        if not t or _is_machine_annotation_text(t):
            continue
        if ln.y0 > 125:
            continue
        if ln.x0 > page_w * 0.55:
            continue
        if not _has_letters(t):
            continue
        if ln.size >= max(body_size + 3.0, 12.0):
            score = (ln.size * 3.0) + (2.0 if ln.bold else 0.0) + (1.0 if getattr(ln, "non_black", False) else 0.0) - (0.02 * ln.y0)
            cands.append((score, ln.y0, ln.x0, t))
    if cands:
        cands.sort(reverse=True)
        return cands[0][3]

    # Fallback: if no prominent heading exists, use best top-left short header-like line.
    cands2 = []
    for ln in lines:
        t = _norm_text(ln.text)
        if not t or _is_machine_annotation_text(t):
            continue
        if ln.y0 > 95:
            continue
        if ln.x0 > 140:
            continue
        if not _has_letters(t):
            continue
        if len(t) > 80:
            continue
        if ln.size >= max(body_size - 0.5, 7.0):
            score = (ln.size * 2.0) + (1.0 if ln.bold else 0.0) - (0.03 * ln.y0)
            cands2.append((score, ln.y0, ln.x0, t))
    if cands2:
        cands2.sort(reverse=True)
        return cands2[0][3]

    return ""


def _join_wrapped_label(lines, start_idx: int, page_w: float) -> str:
    base = lines[start_idx]
    base_x = base.x0
    base_size = float(base.size)
    parts = [_norm_text(base.text)]
    last_y = base.y0

    def ok_cont(ln):
        if not _norm_text(ln.text):
            return False
        if _is_machine_annotation_text(_norm_text(ln.text)):
            return False
        # keep in same label column
        if abs(ln.x0 - base_x) > 22:
            return False
        # similar font size
        if abs(float(ln.size) - base_size) > 2.0:
            return False
        # avoid far-right short option/value cells
        t = _norm_text(ln.text)
        if ln.x0 > page_w * 0.60 and len(t) <= 6:
            return False
        # avoid standalone numeric bullets/options
        if _looks_like_page_furniture(t):
            return False
        return True

    # Continue through subsequent y positions; ignore same-row right-side artifacts by y-gap logic
    for j in range(start_idx + 1, len(lines)):
        ln = lines[j]
        t = _norm_text(ln.text)
        if not t:
            continue
        dy = ln.y0 - last_y
        if dy < 0:
            continue
        if dy > 16:
            break
        if not ok_cont(ln):
            continue
        parts.append(t)
        last_y = ln.y0

    # Hyphenation join
    out_parts = []
    for p in parts:
        if not out_parts:
            out_parts.append(p)
            continue
        prev = out_parts[-1]
        if prev.endswith("-") and p and p[0].islower():
            out_parts[-1] = prev[:-1] + p
        else:
            out_parts.append(p)
    return _norm_text(" ".join(out_parts))


def _page_has_field_markers(lines) -> bool:
    for ln in lines:
        t = _norm_text(ln.text)
        if not t:
            continue
        if _is_machine_annotation_text(t):
            return True
    return False


def extract(pages):
    out = []
    current_form = ""
    for page_idx0, lines in pages:
        if not lines:
            continue
        page_w = _estimate_page_width(lines)
        left_margin = _estimate_left_margin(lines)
        body_size = _estimate_body_size(lines, page_w)

        title = _pick_form_title(lines, page_w, body_size)
        if title:
            current_form = title

        if not _page_has_field_markers(lines):
            continue

        # Build candidate label line indices (non-annotation, non-furniture)
        label_idxs = []
        y_list = []
        for i, ln in enumerate(lines):
            t = _norm_text(ln.text)
            if not t:
                continue
            if _is_machine_annotation_text(t):
                continue
            if _looks_like_page_furniture(t):
                continue
            # suppress far-right tiny option values
            if ln.x0 > page_w * 0.75 and len(t) <= 6:
                continue
            label_idxs.append(i)
            y_list.append(ln.y0)

        # Collect anchors: codes and TYPE markers (use both; codes preferred)
        anchors = []
        for i, ln in enumerate(lines):
            t = _norm_text(ln.text)
            if not t:
                continue
            if _is_code_anchor_text(t):
                anchors.append((ln.y0, ln.x0, i, "code"))
            elif t.startswith("[") and ("TYPE:" in t.upper()):
                anchors.append((ln.y0, ln.x0, i, "type"))

        if not anchors:
            continue

        anchors.sort()
        seen_fields = set()

        for ay, ax, aidx, akind in anchors:
            # Determine preferred x for label: right-side anchors often label on left margin
            preferred_x = left_margin if ax > page_w * 0.55 else ax

            # Search upward among label candidates within a tolerant window
            window = 220.0
            lo_y = ay - window
            hi_y = ay + 8.0

            # Find starting position in y_list (label candidates are in page y-order already)
            k = bisect_left(y_list, lo_y)
            best = None
            best_score = -1e9

            for pos in range(k, len(label_idxs)):
                li = label_idxs[pos]
                ln = lines[li]
                if ln.y0 > hi_y:
                    break
                if ln.y0 > ay + 1.0:
                    continue

                t = _norm_text(ln.text)
                if not t or not _has_letters(t):
                    continue

                # avoid selecting row markers like "Row 5"
                if ln.bold and _ROW_MARK_RE.match(t):
                    continue

                # avoid selecting long descriptive paragraphs unless nothing else fits
                is_long = len(t) >= 120

                dy = ay - ln.y0
                dx = abs(ln.x0 - preferred_x)

                score = 0.0
                score += 3.0 if ln.bold else 0.0
                score += 1.5 if ln.x0 <= left_margin + 55 else 0.0
                score -= dy / 14.0
                score -= dx / 60.0
                score -= 2.0 if is_long else 0.0
                # penalize colon-only headers at far right
                if ln.x0 > page_w * 0.60 and len(t) <= 12:
                    score -= 2.0

                if score > best_score:
                    best_score = score
                    best = li

            if best is None:
                continue

            field = _join_wrapped_label(lines, best, page_w)
            if not field or len(field) < 3:
                continue
            if not _has_letters(field):
                continue
            if _is_machine_annotation_text(field):
                continue

            # Final guard: drop very short right-column value-like strings
            if len(field) <= 6 and lines[best].x0 > page_w * 0.55:
                continue

            key = (current_form or "", field)
            if key in seen_fields:
                continue
            seen_fields.add(key)

            out.append(
                {
                    "form_name": current_form or "",
                    "field_name": field,
                    "page": int(page_idx0) + 1,
                }
            )

    return out
```
