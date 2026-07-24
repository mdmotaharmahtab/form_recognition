```python
# Observed layout: annotated CRF pages where each data-entry field is followed by red bracketed
# machine IDs like "[XXXX]" and red "[TYPE: ...]" lines; human form titles are larger near top.
# Strategy: detect field anchors via red bracketed IDs (excluding TYPE/VISIBILITY/Read-only),
# infer/propagate `form_name` from prominent top title on field pages, and recover `field_name`
# by scoring nearby non-annotation text lines (column header vs left-question area) and joining wraps.

import re
import unicodedata
import statistics
from typing import List, Tuple, Dict, Any, Optional


_ROW_RE = re.compile(r"^\s*Row\s*\d+\b", re.IGNORECASE)


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    def norm_ws(s: str) -> str:
        return " ".join((s or "").strip().split())

    def is_row_line(t: str) -> bool:
        return bool(_ROW_RE.match(t or ""))

    def is_annotation_line_text(t: str) -> bool:
        tt = (t or "").strip()
        if not tt:
            return True
        if tt.startswith("["):
            up = tt.upper()
            if up.startswith("[TYPE"):
                return True
            if up.startswith("[VISIBILITY"):
                return True
            if up.startswith("[READ-ONLY"):
                return True
            return False
        # Continuation fragments of TYPE blocks often appear without leading '[' (e.g., "enumeration", "(values: ...")
        up = tt.upper()
        if up in {"ENUMERATION", "ON"}:
            return True
        if up.startswith("(VALUES:"):
            return True
        return False

    def is_code_marker_line(line: Any) -> bool:
        t = (line.text or "").strip()
        if not t.startswith("["):
            return False
        up = t.upper()
        if up.startswith("[TYPE") or up.startswith("[VISIBILITY") or up.startswith("[READ-ONLY"):
            return False
        # bracketed machine ids usually live in colored (red) text, but keep tolerant
        return True

    def has_letter(s: str) -> bool:
        for ch in s:
            if unicodedata.category(ch).startswith("L"):
                return True
        return False

    def looks_like_title_candidate(line: Any, page_left: float, body_size: float) -> bool:
        t = (line.text or "").strip()
        if not t:
            return False
        if is_annotation_line_text(t) or is_row_line(t):
            return False
        if line.y0 > 130:
            return False
        if line.x0 > page_left + 140:
            return False
        # title tends to be distinctly larger than body labels
        return line.size >= max(body_size * 1.35, body_size + 2.5)

    def detect_form_title(lines: List[Any]) -> str:
        # Only trust title detection on pages that actually look like annotated forms (have field markers)
        if not any(is_code_marker_line(ln) for ln in lines):
            return ""
        non_ann = [ln for ln in lines if not is_annotation_line_text((ln.text or "").strip())]
        if not non_ann:
            return ""
        page_left = min(ln.x0 for ln in non_ann)
        body_sizes = sorted(
            ln.size for ln in non_ann
            if 5.5 <= ln.size <= 12.5 and not is_row_line((ln.text or "").strip())
        )
        body_size = statistics.median(body_sizes) if body_sizes else statistics.median([ln.size for ln in non_ann])

        cands = [ln for ln in non_ann if looks_like_title_candidate(ln, page_left, body_size)]
        if not cands:
            return ""
        # Prefer largest; break ties by being higher on page
        cands.sort(key=lambda l: (-l.size, l.y0, l.x0))
        best = cands[0]

        # Join immediate wrapped title lines (same left edge, similar size, close y)
        parts = [norm_ws(best.text)]
        y_end = best.y1
        x0 = best.x0
        sz = best.size
        for ln in cands[1:]:
            if ln.y0 <= best.y0:
                continue
            if abs(ln.x0 - x0) > 18:
                continue
            if abs(ln.size - sz) > 1.2:
                continue
            if ln.y0 - y_end > max(16.0, 1.6 * sz):
                continue
            t = norm_ws(ln.text)
            if t:
                parts.append(t)
                y_end = ln.y1
        return norm_ws(" ".join(parts))

    def page_stats(lines: List[Any]) -> Dict[str, float]:
        non_ann = [ln for ln in lines if not is_annotation_line_text((ln.text or "").strip())]
        if not non_ann:
            return {"left": 0.0, "body": 8.0, "big": 12.0}
        page_left = min(ln.x0 for ln in non_ann)
        body_sizes = sorted(
            ln.size for ln in non_ann
            if 5.5 <= ln.size <= 12.5 and not is_row_line((ln.text or "").strip())
        )
        body = statistics.median(body_sizes) if body_sizes else statistics.median([ln.size for ln in non_ann])
        big = max(body * 1.35, body + 2.5)
        return {"left": page_left, "body": body, "big": big}

    def choose_anchor(lines: List[Any], marker_line: Any, stats: Dict[str, float]) -> Optional[int]:
        my = marker_line.y0
        mx = (marker_line.x0 + marker_line.x1) / 2.0
        page_left = stats["left"]
        big = stats["big"]

        best_j = None
        best_score = -1e18

        y_window = 75.0
        for j, ln in enumerate(lines):
            t = (ln.text or "").strip()
            if not t:
                continue
            if is_annotation_line_text(t) or is_row_line(t):
                continue
            if ln.size >= big and ln.y0 < 160:
                # likely title/section heading, not field label
                continue
            if abs(ln.y0 - my) > y_window:
                continue

            cx = (ln.x0 + ln.x1) / 2.0
            dx = abs(cx - mx)
            dy = abs(ln.y0 - my)
            length = len(t)

            leftish = ln.x0 <= page_left + 130
            colish = dx <= 85.0

            score = 0.0
            score += 22.0 if leftish else 0.0
            score += 12.0 if colish else 0.0
            score -= 0.33 * dy
            score -= 0.02 * dx
            score += 0.22 * min(length, 90)

            # Prefer black text (non-colored) slightly, but allow gray labels (tables)
            if not getattr(ln, "non_black", False):
                score += 3.5

            # Penalize very short tokens on right side (often option values like Yes/No/Met)
            if length <= 4 and ln.x0 > page_left + 250:
                score -= 10.0

            # Slightly penalize obviously instructional prefixes (keep structural, but "Disclaimer:"-style blocks)
            if length > 160:
                score -= 8.0

            if score > best_score:
                best_score = score
                best_j = j

        return best_j

    def expand_wrapped_label(lines: List[Any], anchor_j: int, stats: Dict[str, float]) -> str:
        page_left = stats["left"]
        big = stats["big"]

        anchor = lines[anchor_j]
        ax = anchor.x0
        ay0 = anchor.y0
        ay1 = anchor.y1

        def ok_line(ln: Any) -> bool:
            t = (ln.text or "").strip()
            if not t:
                return False
            if is_annotation_line_text(t) or is_row_line(t):
                return False
            if ln.size >= big and ln.y0 < 160:
                return False
            return True

        def x_compatible(ln: Any) -> bool:
            # allow small indent drift for wraps
            return (ln.x0 >= ax - 14.0) and (ln.x0 <= ax + 60.0)

        included = [anchor_j]

        # Walk upward
        prev_y0 = ay0
        prev_y1 = ay1
        for j in range(anchor_j - 1, -1, -1):
            ln = lines[j]
            if not ok_line(ln):
                continue
            if not x_compatible(ln):
                continue
            gap = prev_y0 - ln.y1
            if gap > max(18.0, 2.2 * max(ln.size, anchor.size)):
                break
            if ay0 - ln.y0 > 95.0:
                break
            included.append(j)
            prev_y0 = ln.y0
            prev_y1 = ln.y1

        # Walk downward
        prev_y0 = ay0
        prev_y1 = ay1
        for j in range(anchor_j + 1, len(lines)):
            ln = lines[j]
            if not ok_line(ln):
                continue
            if not x_compatible(ln):
                continue
            gap = ln.y0 - prev_y1
            if gap > max(18.0, 2.2 * max(ln.size, anchor.size)):
                break
            if ln.y0 - ay0 > 95.0:
                break
            included.append(j)
            prev_y0 = ln.y0
            prev_y1 = ln.y1

        # Sort in reading order for this block: y then x
        included = sorted(set(included), key=lambda k: (lines[k].y0, lines[k].x0))
        text = norm_ws(" ".join(norm_ws(lines[k].text) for k in included))
        return text

    def is_label_like(label: str) -> bool:
        t = norm_ws(label)
        if not t:
            return False
        if t.startswith("["):
            return False
        if len(t) < 2:
            return False
        if is_row_line(t):
            return False
        # Avoid returning pure numeric / symbol fragments
        if not has_letter(t):
            has_digit = any(ch.isdigit() for ch in t)
            has_other = any((not ch.isdigit()) and (not ch.isspace()) for ch in t)
            if not (has_digit and has_other and len(t) >= 4):
                return False
        return True

    results: List[Dict[str, Any]] = []
    current_form_name = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        # Build marker list (merge trivial split codes like "[SCANNE" + "R]")
        markers: List[int] = []
        i = 0
        while i < len(lines):
            ln = lines[i]
            if is_code_marker_line(ln):
                t = (ln.text or "").strip()
                if (not t.endswith("]")) and (i + 1 < len(lines)):
                    ln2 = lines[i + 1]
                    t2 = (ln2.text or "").strip()
                    if (
                        getattr(ln2, "non_black", False)
                        and ("]" in t2)
                        and abs(ln2.x0 - ln.x0) < 8.0
                        and (ln2.y0 - ln.y0) < 20.0
                        and not is_annotation_line_text(t2)
                    ):
                        markers.append(i)
                        i += 2
                        continue
                markers.append(i)
            i += 1

        if not markers:
            continue

        # Update form title context if this is a field-bearing page
        title = detect_form_title(lines)
        if title:
            current_form_name = title

        stats = page_stats(lines)

        seen_on_page = set()
        for mi in markers:
            mline = lines[mi]
            anchor_j = choose_anchor(lines, mline, stats)
            if anchor_j is None:
                continue
            label = expand_wrapped_label(lines, anchor_j, stats)
            if not is_label_like(label):
                continue
            key = (current_form_name, label)
            if key in seen_on_page:
                continue
            seen_on_page.add(key)
            results.append(
                {
                    "form_name": current_form_name,
                    "field_name": label,
                    "page": page_idx0 + 1,
                }
            )

    return results
```
