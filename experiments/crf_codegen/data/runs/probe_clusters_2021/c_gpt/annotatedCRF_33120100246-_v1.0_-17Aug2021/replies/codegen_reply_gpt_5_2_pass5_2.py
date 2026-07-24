import re
import unicodedata
from typing import List, Tuple, Dict, Any, Optional


_RE_BRACKET_CODE = re.compile(r"^\[[A-Z0-9]{2,}\]$")
_RE_ROW = re.compile(r"^Row\s+\d+\s*$", re.IGNORECASE)


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        texts = [_norm(getattr(l, "text", "")) for l in lines]
        sizes = sorted(
            [
                float(getattr(l, "size", 0.0) or 0.0)
                for l, t in zip(lines, texts)
                if t
            ]
        )
        if not sizes:
            continue

        med = _quantile_sorted(sizes, 0.5)
        p90 = _quantile_sorted(sizes, 0.9)
        p97 = _quantile_sorted(sizes, 0.97)

        # Update current form title if we see one
        title = _detect_title(lines, texts, med, p90, p97)
        if title:
            current_form = title

        # Find bracket-code anchors (prefer exact short codes; allow either color)
        codes = []
        for i, (l, t) in enumerate(zip(lines, texts)):
            if _is_field_code_line(l, t, med):
                codes.append((i, l, t))

        seen_on_page = set()

        if codes:
            # Group codes into vertical-ish groups by x and y continuity
            code_groups = _group_codes(codes, med)

            for group in code_groups:
                # Detect option-list groups (radio/enumeration): many codes in a column with short right-adjacent choice text
                if _group_looks_like_option_list(lines, texts, group, med):
                    qlab = _question_label_for_group(lines, texts, group, med)
                    if qlab:
                        form_name = current_form or ""
                        key = (form_name, qlab)
                        if key not in seen_on_page:
                            seen_on_page.add(key)
                            out.append({"form_name": form_name, "field_name": qlab, "page": page_idx0 + 1})
                    continue

                # Otherwise treat each code as a field (checkboxes/tables/singletons)
                group_code_ys = sorted([float(getattr(c[1], "y0", 0.0) or 0.0) for c in group])
                for idx, code_l, code_t in group:
                    label = _label_for_code(lines, texts, code_l, group_code_ys, med)
                    if not label:
                        continue
                    form_name = current_form or ""
                    key = (form_name, label)
                    if key in seen_on_page:
                        continue
                    seen_on_page.add(key)
                    out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})
        else:
            # Fallback: conservative extraction of left-column black question labels (no codes present/recognized)
            for label in _fallback_left_questions(lines, texts, med, p90):
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


def _is_field_code_line(l: Any, t: str, med_size: float) -> bool:
    if not t:
        return False
    if not _RE_BRACKET_CODE.match(t):
        return False
    # Exclude typical non-field bracket annotations (they are not exact [A-Z0-9]+ anyway, but be safe)
    if t.startswith("[TYPE") or t.startswith("[VISIBILITY") or t.startswith("[READ"):
        return False
    # Light geometry sanity: codes tend to be small-ish
    sz = float(getattr(l, "size", 0.0) or 0.0)
    if sz and med_size and (sz < max(5.5, med_size * 0.55) or sz > max(13.5, med_size * 1.6)):
        return False
    return True


def _detect_title(lines: List[Any], texts: List[str], med: float, p90: float, p97: float) -> str:
    candidates = []
    for l, t in zip(lines, texts):
        if not t:
            continue
        if t.startswith("["):
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
            score = (sz / (p97 or sz or 1.0)) * 3.0
            score += (1.0 - min(y0, 130.0) / 130.0) * 2.0
            score += (1.0 - min(x0, 260.0) / 260.0)
            score += min(len(t), 80) / 80.0
            if is_colored:
                score += 0.5
            candidates.append((score, t))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


def _looks_like_tech_bracket(t: str) -> bool:
    if not t:
        return False
    if not t.startswith("["):
        return False
    # Any bracketed technical annotation line (including wrapped ones) should not be a label.
    # Real machine field codes are handled separately and must match _RE_BRACKET_CODE.
    return True


def _looks_like_choice_token(t: str) -> bool:
    if not t:
        return False
    if _looks_like_tech_bracket(t):
        return False
    toks = t.split()
    if len(toks) <= 2 and len(t) <= 14:
        alnum = sum(1 for ch in t if ch.isalnum())
        if alnum >= max(2, len(t) - 1):
            return True
    return False


def _is_labelish_line(
    l: Any,
    t: str,
    *,
    allow_colored: bool = False,
    allow_short: bool = True,
) -> bool:
    if not t:
        return False
    if _looks_like_tech_bracket(t):
        return False
    if _RE_ROW.match(t):
        return False
    if not allow_colored and bool(getattr(l, "non_black", False)):
        # Avoid red definition text / blue headings as field labels
        return False

    # Avoid pure punctuation
    if all(unicodedata.category(ch).startswith("P") or ch.isspace() for ch in t):
        return False

    has_letter = any(unicodedata.category(ch).startswith("L") for ch in t)
    if not has_letter:
        if len(t) < (4 if allow_short else 8):
            return False
        if sum(ch.isalnum() for ch in t) < (3 if allow_short else 5):
            return False

    if not allow_short:
        if len(t) < 6:
            return False

    # Avoid absurdly long paragraphs as a single "label"
    if len(t) > 160:
        return False

    return True


def _group_codes(codes: List[Tuple[int, Any, str]], med: float) -> List[List[Tuple[int, Any, str]]]:
    if not codes:
        return []
    # Sort by y (top to bottom), then x
    sorted_codes = sorted(
        codes,
        key=lambda it: (float(getattr(it[1], "y0", 0.0) or 0.0), float(getattr(it[1], "x0", 0.0) or 0.0)),
    )

    x_tol = max(22.0, med * 2.2)
    y_gap = max(55.0, med * 6.5)

    groups: List[List[Tuple[int, Any, str]]] = []
    for item in sorted_codes:
        _, l, _ = item
        x = float(getattr(l, "x0", 0.0) or 0.0)
        y = float(getattr(l, "y0", 0.0) or 0.0)

        placed = False
        for g in groups:
            # Compare to last item in group
            _, gl, _ = g[-1]
            gx = float(getattr(gl, "x0", 0.0) or 0.0)
            gy = float(getattr(gl, "y0", 0.0) or 0.0)
            if abs(x - gx) <= x_tol and (y - gy) <= y_gap:
                g.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])

    return groups


def _nearest_right_text(
    lines: List[Any],
    texts: List[str],
    code_l: Any,
    *,
    dx_max: float,
    dy_max: float,
    med: float,
) -> Optional[int]:
    cx = float(getattr(code_l, "x0", 0.0) or 0.0)
    cy = float(getattr(code_l, "y0", 0.0) or 0.0)

    best_i = None
    best_score = -1e9
    for i, (l, t) in enumerate(zip(lines, texts)):
        if not _is_labelish_line(l, t, allow_colored=False, allow_short=True):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if x0 <= cx + 2:
            continue
        dx = x0 - cx
        dy = abs(y0 - cy)
        if dx > dx_max or dy > dy_max:
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)
        score = -(dy * 2.0) - (dx * 0.08) + min(len(t), 40) * 0.02
        if sz and med and abs(sz - med) <= 2.5:
            score += 0.6
        if getattr(l, "bold", False):
            score += 0.3
        if score > best_score:
            best_score = score
            best_i = i
    return best_i


def _group_looks_like_option_list(lines: List[Any], texts: List[str], group: List[Tuple[int, Any, str]], med: float) -> bool:
    if len(group) < 3:
        return False

    xs = [float(getattr(it[1], "x0", 0.0) or 0.0) for it in group]
    x_spread = max(xs) - min(xs) if xs else 9999.0
    if x_spread > max(18.0, med * 1.8):
        return False

    right_labels = []
    for _, code_l, _ in group:
        ri = _nearest_right_text(lines, texts, code_l, dx_max=max(220.0, med * 20.0), dy_max=max(13.0, med * 1.3), med=med)
        if ri is None:
            continue
        right_labels.append(texts[ri])

    if len(right_labels) < max(2, int(len(group) * 0.6)):
        return False

    shortish = sum(1 for t in right_labels if _looks_like_choice_token(t))
    if shortish < int(len(right_labels) * 0.7):
        return False

    # Must also have some plausible left-side "question" label; otherwise we might be looking at something else
    qlab = _question_label_for_group(lines, texts, group, med)
    return bool(qlab)


def _question_label_for_group(lines: List[Any], texts: List[str], group: List[Tuple[int, Any, str]], med: float) -> str:
    # Find a single longer left-side label spanning the group (question text)
    code_x = float(getattr(group[0][1], "x0", 0.0) or 0.0)
    ys = [float(getattr(it[1], "y0", 0.0) or 0.0) for it in group]
    if not ys:
        return ""
    y_min = min(ys)
    y_max = max(ys)

    y_top = max(0.0, y_min - max(70.0, med * 8.0))
    y_bot = y_max + max(25.0, med * 3.0)

    best_i = None
    best_score = -1e9
    for i, (l, t) in enumerate(zip(lines, texts)):
        if not _is_labelish_line(l, t, allow_colored=False, allow_short=False):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 < y_top or y0 > y_bot:
            continue
        if x0 >= code_x - max(28.0, med * 2.5):
            continue

        # Prefer lines closer to just above the first option
        dy = abs(y0 - (y_min - max(10.0, med * 1.2)))
        score = -(dy * 0.7)
        score += min(len(t), 120) * 0.02
        if t.endswith(":") or t.endswith("?"):
            score += 1.2
        if getattr(l, "bold", False):
            score += 0.6
        if x0 < 220:
            score += 0.6

        if score > best_score:
            best_score = score
            best_i = i

    if best_i is None:
        return ""

    merged = _merge_wrapped_label(lines, texts, best_i, band=(y_top, y_bot), med=med)
    return _final_label_sanitize(merged)


def _label_for_code(lines: List[Any], texts: List[str], code_l: Any, code_y_sorted: List[float], med: float) -> str:
    cx = float(getattr(code_l, "x0", 0.0) or 0.0)
    cy = float(getattr(code_l, "y0", 0.0) or 0.0)

    prev_y = None
    next_y = None
    for y in code_y_sorted:
        if y < cy - 1e-6:
            prev_y = y
        elif y > cy + 1e-6:
            next_y = y
            break

    band_top = max(0.0, (prev_y + cy) / 2.0) if prev_y is not None else max(0.0, cy - max(90.0, med * 10.0))
    band_bot = (cy + next_y) / 2.0 if next_y is not None else cy + max(140.0, med * 14.0)

    # 1) Prefer immediate right-of-code label (checkbox/table headers etc.)
    right_i = _nearest_right_text(lines, texts, code_l, dx_max=max(260.0, med * 24.0), dy_max=max(14.0, med * 1.4), med=med)
    if right_i is not None:
        merged = _merge_wrapped_label(lines, texts, right_i, band=(band_top, band_bot), med=med)
        merged = _final_label_sanitize(merged)
        if merged and not _looks_like_choice_token(merged) and len(merged) <= 160:
            return merged
        # If it looks like a short choice token, still allow it for singletons (e.g., table fields),
        # but never if it is a technical bracket or absurd.
        if merged and not _looks_like_tech_bracket(merged) and len(merged) <= 40:
            return merged

    # 2) Left-of-code near same y (most common)
    best_i = None
    best_score = -1e9
    for i, (l, t) in enumerate(zip(lines, texts)):
        if not _is_labelish_line(l, t, allow_colored=False, allow_short=True):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 < band_top or y0 > band_bot:
            continue
        if x0 >= cx - max(18.0, med * 1.8):
            continue
        dy = abs(y0 - cy)
        if dy > max(90.0, med * 10.0):
            continue
        sz = float(getattr(l, "size", 0.0) or 0.0)

        score = -dy + min(len(t), 120) * 0.012
        if t.endswith(":") or t.endswith("?"):
            score += 1.0
        if getattr(l, "bold", False):
            score += 0.5
        if x0 < 220:
            score += 0.5
        if sz and med and abs(sz - med) <= 2.5:
            score += 0.25

        if score > best_score:
            best_score = score
            best_i = i

    # 3) Above-left fallback (labels immediately above entry area)
    if best_i is None:
        for i, (l, t) in enumerate(zip(lines, texts)):
            if not _is_labelish_line(l, t, allow_colored=False, allow_short=False):
                continue
            x0 = float(getattr(l, "x0", 0.0) or 0.0)
            y0 = float(getattr(l, "y0", 0.0) or 0.0)
            if y0 < band_top or y0 > cy:
                continue
            if x0 >= cx - max(10.0, med * 1.0):
                continue
            dy = cy - y0
            if dy > max(55.0, med * 6.0):
                continue
            score = -dy + min(len(t), 120) * 0.01
            if t.endswith(":") or t.endswith("?"):
                score += 0.9
            if getattr(l, "bold", False):
                score += 0.4
            if score > best_score:
                best_score = score
                best_i = i

    if best_i is None:
        return ""

    merged = _merge_wrapped_label(lines, texts, best_i, band=(band_top, band_bot), med=med)
    return _final_label_sanitize(merged)


def _merge_wrapped_label(lines: List[Any], texts: List[str], start_i: int, *, band: Tuple[float, float], med: float) -> str:
    band_top, band_bot = band
    if start_i < 0 or start_i >= len(lines):
        return ""

    base_l = lines[start_i]
    base_x = float(getattr(base_l, "x0", 0.0) or 0.0)
    base_sz = float(getattr(base_l, "size", 0.0) or 0.0)

    max_gap = max(12.0, (base_sz or med or 8.0) * 1.9)
    x_tol = max(38.0, (base_sz or med or 8.0) * 4.6)

    parts: List[str] = []
    prev_y = None

    for j in range(start_i, len(lines)):
        l = lines[j]
        t = texts[j]
        if not t:
            continue

        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if y0 < band_top or y0 > band_bot:
            if parts:
                break
            continue

        # Stop on any bracket/technical annotation line
        if _looks_like_tech_bracket(t):
            if parts:
                break
            continue
        # Stop if we hit a standalone machine code line
        if _RE_BRACKET_CODE.match(t):
            if parts:
                break
            continue

        if not _is_labelish_line(l, t, allow_colored=False, allow_short=True):
            if parts and prev_y is not None and (y0 - prev_y) > max_gap:
                break
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)

        if not parts:
            parts.append(t)
            prev_y = y0
            continue

        # Continuation heuristics: close in y; not a huge x jump; similar-ish size
        if prev_y is not None and (y0 - prev_y) > max_gap:
            break

        # Allow typical wrapped indentation, but stop if it jumps far into a right column
        if abs(x0 - base_x) > x_tol and x0 > base_x:
            break

        if base_sz and sz and abs(sz - base_sz) > 3.2:
            break

        # Avoid accidentally swallowing far-right choice columns or definition blocks
        if x0 > 320 and _looks_like_choice_token(t):
            break

        parts.append(t)
        prev_y = y0

        if t.endswith("?") or t.endswith(":"):
            break

    return _norm(" ".join(parts))


def _final_label_sanitize(label: str) -> str:
    label = _norm(label)
    if not label:
        return ""
    if _RE_ROW.match(label):
        return ""
    if _looks_like_tech_bracket(label):
        return ""
    if _RE_BRACKET_CODE.match(label):
        return ""
    if len(label) <= 2:
        return ""
    # Prevent accidental paragraph captures
    if len(label) > 180:
        return ""
    return label


def _fallback_left_questions(lines: List[Any], texts: List[str], med: float, p90: float) -> List[str]:
    labels = []
    seen = set()

    for l, t in zip(lines, texts):
        if not t:
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)

        if y0 < 70:
            continue
        if x0 > 230:
            continue
        if bool(getattr(l, "non_black", False)):
            continue
        if sz > p90 * 0.95:
            continue
        if sz < max(6.5, med * 0.6) or sz > max(12.0, med * 1.3):
            continue
        if not _is_labelish_line(l, t, allow_colored=False, allow_short=False):
            continue
        if len(t) < 12:
            continue
        if t in seen:
            continue
        seen.add(t)
        labels.append(t)

    return labels
