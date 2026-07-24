# Observed layouts: (1) an approval cover page with a large bold form title and a left column
# of bold labels; (2) annotated eCRF pages with a colored form title band and many right-margin
# small bold machine-code anchors for each field, with the human label near the left margin.
# Strategy: detect annotated pages via machine-code anchors; extract form title from the top
# colored title lines; for each anchor, capture the nearest left-margin label and wrap lines.

import re
import unicodedata
from bisect import bisect_left

_RE_CODE = re.compile(r"^[A-Za-z0-9_]{2,30}$")
_RE_UNDERS = re.compile(r"^_+$")


def _norm(s: str) -> str:
    return " ".join((s or "").split()).strip()


def _has_letter_or_digit(s: str) -> bool:
    s = s or ""
    for ch in s:
        if ch.isalnum():
            return True
        # safety for scripts where isalnum may be conservative (rare)
        if unicodedata.category(ch).startswith("L"):
            return True
    return False


def _is_bracketed_machine(s: str) -> bool:
    s = (s or "").strip()
    return len(s) >= 2 and s[0] == "[" and s[-1] == "]"


def _is_code_anchor(line) -> bool:
    t = (line.text or "").strip()
    if " " in t:
        return False
    if not line.bold:
        return False
    if not (5.0 <= float(line.size) <= 6.6):
        return False
    if float(line.x0) < 280:
        return False
    if not _RE_CODE.match(t):
        return False
    return True


def _is_left_label_candidate(line) -> bool:
    t = (line.text or "").strip()
    if not t:
        return False
    if float(line.x0) > 150:
        return False
    if line.non_black:
        return False
    sz = float(line.size)
    if not (6.3 <= sz <= 9.4):
        return False
    if _RE_UNDERS.match(t):
        return False
    if _is_bracketed_machine(t):
        return False
    if not _has_letter_or_digit(t):
        return False
    return True


def _extract_form_title_annotated(lines) -> str:
    # Prefer the colored title band text near top-left.
    cand = []
    for ln in lines:
        if float(ln.y0) > 90:
            break
        if ln.non_black and float(ln.size) >= 11.0 and float(ln.x0) < 220:
            txt = _norm(ln.text)
            if txt:
                cand.append((float(ln.y0), float(ln.x0), txt))
    if cand:
        cand.sort()
        parts = []
        last_y = None
        for y, x, txt in cand:
            if last_y is None or abs(y - last_y) <= 14:
                parts.append(txt)
                last_y = y
        return _norm(" ".join(parts))
    # Fallback: any prominent non-black header line near top-left.
    best = None
    for ln in lines:
        if float(ln.y0) > 120:
            break
        if float(ln.x0) < 240 and float(ln.size) >= 9.5 and (ln.bold or ln.non_black):
            txt = _norm(ln.text)
            if not txt:
                continue
            score = float(ln.size) + (1.0 if ln.non_black else 0.0) + (0.5 if ln.bold else 0.0)
            if best is None or score > best[0]:
                best = (score, txt)
    return best[1] if best else ""


def _extract_annotated_fields(lines, page_1based: int):
    anchors = [(i, ln) for i, ln in enumerate(lines) if _is_code_anchor(ln)]
    if not anchors:
        return []

    form_name = _extract_form_title_annotated(lines)

    # Precompute candidate indices by y for fast seeking.
    cand_idx = []
    cand_y = []
    for i, ln in enumerate(lines):
        if _is_left_label_candidate(ln):
            cand_idx.append(i)
            cand_y.append(float(ln.y0))

    out = []
    seen = set()

    for ai, (idx_a, a) in enumerate(anchors):
        y_a = float(a.y0)
        y_stop = float("inf")
        if ai + 1 < len(anchors):
            y_stop = float(anchors[ai + 1][1].y0) - 1.0

        # Find first left-label candidate in the expected label zone under the anchor.
        start_y = y_a - 2.0
        end_y = min(y_a + 60.0, y_stop)
        k = bisect_left(cand_y, start_y)
        label_start_raw_idx = None
        while k < len(cand_idx) and cand_y[k] <= end_y:
            ri = cand_idx[k]
            ln = lines[ri]
            # Avoid picking up unrelated left text far above anchor on very dense pages.
            if float(ln.y0) >= start_y:
                label_start_raw_idx = ri
                break
            k += 1

        if label_start_raw_idx is None:
            continue

        base = lines[label_start_raw_idx]
        base_x = float(base.x0)
        parts = [_norm(base.text)]
        prev_y = float(base.y0)

        # Collect wrapped label lines until bracketed machine line or big gap/new block.
        max_y = min(prev_y + 75.0, y_stop)
        for j in range(label_start_raw_idx + 1, len(lines)):
            ln = lines[j]
            y = float(ln.y0)
            if y > max_y:
                break

            if float(ln.x0) < 160:
                t = (ln.text or "").strip()
                if t.startswith("["):
                    break
                # Stop if we hit another left block after a large vertical gap.
                if (y - prev_y) > 20.0 and _has_letter_or_digit(t):
                    break

            if _is_left_label_candidate(ln) and abs(float(ln.x0) - base_x) <= 25.0 and (y - prev_y) <= 16.0:
                parts.append(_norm(ln.text))
                prev_y = y

        field_name = _norm(" ".join([p for p in parts if p]))
        if not field_name:
            continue

        key = (form_name, field_name)
        if key in seen:
            continue
        seen.add(key)
        out.append({"form_name": form_name, "field_name": field_name, "page": page_1based})

    return out


def _extract_approval_cover(lines, page_1based: int):
    # Large bold title near upper middle.
    title = None
    for ln in lines:
        if not ln.bold:
            continue
        sz = float(ln.size)
        if sz < 18.0:
            continue
        y = float(ln.y0)
        if not (80.0 <= y <= 260.0):
            continue
        txt = _norm(ln.text)
        if not txt:
            continue
        if title is None or sz > title[0]:
            title = (sz, txt)

    if title is None:
        return []

    form_name = title[1]
    out = []
    seen = set()

    for ln in lines:
        if not ln.bold:
            continue
        sz = float(ln.size)
        if not (14.0 <= sz <= 18.5):
            continue
        x = float(ln.x0)
        y = float(ln.y0)
        if not (35.0 <= x <= 140.0 and 180.0 <= y <= 560.0):
            continue
        if ln.non_black:
            continue
        txt = _norm(ln.text)
        if not txt or not _has_letter_or_digit(txt):
            continue
        key = (form_name, txt)
        if key in seen:
            continue
        seen.add(key)
        out.append({"form_name": form_name, "field_name": txt, "page": page_1based})

    return out


def extract(pages):
    results = []
    for page_idx0, lines in pages:
        page_1based = int(page_idx0) + 1

        # Layout family 1: approval cover (extract left bold labels).
        cover = _extract_approval_cover(lines, page_1based)
        if cover:
            results.extend(cover)
            continue

        # Layout family 2: annotated CRF pages (extract via right-margin code anchors).
        ann = _extract_annotated_fields(lines, page_1based)
        if ann:
            results.extend(ann)
            continue

        # Other layouts: intentionally emit nothing.
    return results
