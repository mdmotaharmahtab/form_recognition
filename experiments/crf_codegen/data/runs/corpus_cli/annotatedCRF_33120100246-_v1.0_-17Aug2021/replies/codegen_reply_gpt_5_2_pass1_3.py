```python
import re
import statistics
from collections import Counter


_RE_FIELD_ID = re.compile(r"^\[[A-Za-z0-9_]{2,}\]$")
_RE_SPLIT_OPEN = re.compile(r"^\[[A-Za-z0-9_]{2,}$")          # "[SCANNE"
_RE_SPLIT_CLOSE = re.compile(r"^[A-Za-z0-9_]{1,20}\]$")       # "R]"
_RE_TYPE_LINE = re.compile(r"^\[TYPE\s*:\s*.+\]\s*$", re.IGNORECASE)

_RE_ROW = re.compile(r"^\s*Row\s*\d+\s*$", re.IGNORECASE)
_RE_JUST_PUNCT = re.compile(r"^\W+$", re.UNICODE)

_RE_ENUM_PAREN_START = re.compile(r"^\s*\(\s*\d+\s*\)\s*")
_RE_ENUM_PAREN_ANY = re.compile(r"\(\s*\d+\s*\)")
_RE_ENUM_RPAREN_START = re.compile(r"^\s*\d+\)\s+")
_RE_QUESTION_STEM_NUM = re.compile(r"^\s*\d+\.\s+\S+")
_RE_TIMEPOINT_H = re.compile(r"^\s*\d+(?:\.\d+)?\s*h\b", re.IGNORECASE)


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _norm_text(s: str) -> str:
    s = (s or "").replace("\\", "")  # CRF export often shows stray "\" markers
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    return s


def _looks_like_chrome_or_empty(text: str) -> bool:
    if not text:
        return True
    t = text.strip()
    if not t:
        return True
    if _RE_JUST_PUNCT.match(t):
        return True
    if re.fullmatch(r"\d{1,4}", t):
        return True
    return False


def _is_field_id_text(t: str) -> bool:
    # Must be a clean bracket token without ":" or spaces; avoids "[TYPE: ...]" etc.
    t = (t or "").strip()
    if ":" in t or " " in t:
        return False
    return bool(_RE_FIELD_ID.match(t))


def _is_type_line(ln) -> bool:
    if not getattr(ln, "non_black", False):
        return False
    t = (getattr(ln, "text", "") or "").strip()
    return bool(_RE_TYPE_LINE.match(t))


def _merge_split_bracket_ids(lines):
    # Merge cases where an ID is split across two lines like "[SCANNE" + "R]"
    out = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        t = (getattr(ln, "text", "") or "").strip()
        if _RE_SPLIT_OPEN.match(t) and (":" not in t) and (" " not in t) and i + 1 < n:
            nxt = lines[i + 1]
            t2 = (getattr(nxt, "text", "") or "").strip()
            if (
                _RE_SPLIT_CLOSE.match(t2)
                and abs(_f(getattr(nxt, "size", 0.0)) - _f(getattr(ln, "size", 0.0))) <= 0.6
                and abs(_f(getattr(nxt, "x0", 0.0)) - _f(getattr(ln, "x0", 0.0))) <= 6.0
                and 0.0 <= _f(getattr(nxt, "y0", 0.0)) - _f(getattr(ln, "y0", 0.0)) <= 16.0
            ):
                merged_text = t + t2

                class _L:
                    __slots__ = ("text", "x0", "y0", "x1", "y1", "size", "bold", "non_black")

                m = _L()
                m.text = merged_text
                m.x0, m.y0, m.x1, m.y1 = getattr(ln, "x0", 0.0), getattr(ln, "y0", 0.0), getattr(ln, "x1", 0.0), getattr(nxt, "y1", getattr(nxt, "y0", 0.0))
                m.size = getattr(ln, "size", 0.0)
                m.bold = bool(getattr(ln, "bold", False))
                m.non_black = bool(getattr(ln, "non_black", False)) or bool(getattr(nxt, "non_black", False))
                out.append(m)
                i += 2
                continue
        out.append(ln)
        i += 1
    return out


def _page_small_font_size(lines) -> float:
    # Estimate the "label" font as the most common black size in a broad small-text band.
    sizes = []
    for ln in lines:
        if ln is None:
            continue
        if getattr(ln, "non_black", False):
            continue
        sz = _f(getattr(ln, "size", 0.0))
        if 6.0 <= sz <= 10.8:
            sizes.append(round(sz, 1))
    if not sizes:
        allsz = [_f(getattr(ln, "size", 0.0)) for ln in lines if ln is not None]
        allsz = [s for s in allsz if s > 0]
        return float(statistics.median(allsz)) if allsz else 8.0
    c = Counter(sizes)
    best = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return float(best)


def _page_colored_title(lines, small_sz: float):
    # Large colored heading near top-left (typical form name)
    cands = []
    for ln in lines:
        t = (getattr(ln, "text", "") or "").strip()
        if _looks_like_chrome_or_empty(t):
            continue
        if not getattr(ln, "non_black", False):
            continue
        y = _f(getattr(ln, "y0", 0.0))
        x = _f(getattr(ln, "x0", 0.0))
        sz = _f(getattr(ln, "size", 0.0))
        if y <= 130.0 and x <= 260.0 and sz >= max(small_sz * 1.45, small_sz + 3.5):
            if t.startswith("[") and t.endswith("]"):
                continue
            cands.append((sz, -y, -x, t))
    if not cands:
        return ""
    cands.sort(reverse=True)
    return _norm_text(cands[0][3])


def _page_top_black_heading(lines, small_sz: float):
    # Small black heading at very top-left used on some lab pages without colored title.
    cands = []
    for ln in lines:
        if getattr(ln, "non_black", False):
            continue
        t = (getattr(ln, "text", "") or "").strip()
        if _looks_like_chrome_or_empty(t):
            continue
        if t.startswith("["):
            continue
        y = _f(getattr(ln, "y0", 0.0))
        x = _f(getattr(ln, "x0", 0.0))
        sz = _f(getattr(ln, "size", 0.0))
        if y <= 85.0 and x <= 140.0 and abs(sz - small_sz) <= 1.4:
            cands.append((y, x, t))
    if not cands:
        return ""
    cands.sort(key=lambda a: (a[0], a[1]))
    return _norm_text(cands[0][2])


def _page_looks_like_lab_enum_list(lines, small_sz: float) -> bool:
    # Heuristic signature for families C/D/E: many medium black items in a right-side column list.
    cnt = 0
    for ln in lines:
        if getattr(ln, "non_black", False):
            continue
        sz = _f(getattr(ln, "size", 0.0))
        x = _f(getattr(ln, "x0", 0.0))
        y = _f(getattr(ln, "y0", 0.0))
        if 70.0 <= y <= 640.0 and x >= 240.0 and (small_sz + 1.0) <= sz <= (small_sz + 3.5):
            t = (getattr(ln, "text", "") or "").strip()
            if _looks_like_chrome_or_empty(t) or t.startswith("["):
                continue
            cnt += 1
    return cnt >= 5


def _looks_like_choice_legend(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return True
    # Multi-anchor legends (single line listing many anchors) are almost never the field label.
    if len(_RE_ENUM_PAREN_ANY.findall(t)) >= 2:
        return True
    # Single anchor lines are often option lists; treat them as poor anchors unless nothing else exists.
    if _RE_ENUM_PAREN_START.match(t) or _RE_ENUM_RPAREN_START.match(t):
        return True
    return False


def _looks_like_definition_sentence(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    # Penalize multi-sentence definitions (common in C-SSRS explanatory text)
    if "?" not in t and t.count(".") >= 2:
        return True
    if "?" not in t and t.endswith(".") and len(t) >= 90 and t.count(",") >= 2:
        return True
    return False


def _label_candidate(ln, small_sz: float) -> bool:
    if getattr(ln, "non_black", False):
        return False
    t = (getattr(ln, "text", "") or "").strip()
    if _looks_like_chrome_or_empty(t):
        return False
    if t.startswith("["):
        return False
    if _RE_ROW.match(t):
        return False
    sz = _f(getattr(ln, "size", 0.0))
    # Broader than before: allows slightly larger stems (e.g., numbered item labels).
    if not (small_sz - 1.2 <= sz <= small_sz + 3.8):
        return False
    return True


def _promptish_text(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    if "?" in t or ":" in t:
        return True
    if _RE_QUESTION_STEM_NUM.match(t):
        return True
    # Hyphenated stems are common (“… - Lifetime”) but don't require it.
    if " - " in t and len(t) <= 80:
        return True
    return False


def _header_like(ln, small_sz: float) -> bool:
    # Column headers are black and noticeably larger than label font, often ~9-10pt.
    if getattr(ln, "non_black", False):
        return False
    t = (getattr(ln, "text", "") or "").strip()
    if _looks_like_chrome_or_empty(t):
        return False
    if t.startswith("["):
        return False
    sz = _f(getattr(ln, "size", 0.0))
    if not (small_sz + 0.9 <= sz <= small_sz + 5.4):
        return False
    if len(t) > 70:
        return False
    return True


def _nearest_header(headers, code_x: float, code_y: float):
    best = None
    best_score = None
    for h in headers:
        hy = _f(getattr(h, "y0", 0.0))
        if hy >= code_y:
            continue
        dy = code_y - hy
        if dy > 360.0:
            continue
        dx = abs(code_x - _f(getattr(h, "x0", 0.0)))
        score = dy * 1.0 + dx * 0.35
        if best_score is None or score < best_score:
            best_score = score
            best = (getattr(h, "text", "") or "").strip()
    return _norm_text(best) if best else ""


def _two_col_split_x(label_lines):
    xs = sorted({_f(getattr(ln, "x0", 0.0)) for ln in label_lines})
    if len(xs) < 24:
        return None
    gaps = []
    for i in range(1, len(xs)):
        gaps.append((xs[i] - xs[i - 1], i))
    gap, idx = max(gaps, key=lambda t: t[0])
    if gap < 170.0:
        return None
    left_ct = idx
    right_ct = len(xs) - idx
    if left_ct < 10 or right_ct < 10:
        return None
    return (xs[idx - 1] + xs[idx]) / 2.0


def _gather_same_row_text(cands, anchor_ln, y_tol: float, x_min: float, x_max: float) -> str:
    ay = _f(getattr(anchor_ln, "y0", 0.0))
    parts = []
    for ln in cands:
        y = _f(getattr(ln, "y0", 0.0))
        if abs(y - ay) > y_tol:
            continue
        x0 = _f(getattr(ln, "x0", 0.0))
        if x0 < x_min or x0 > x_max:
            continue
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        parts.append((y, x0, t))
    if not parts:
        return ""
    parts.sort(key=lambda p: (p[0], p[1]))
    return _norm_text(" ".join(p[2] for p in parts))


def _same_row_left_anchor(label_lines, code_ln, left_margin_x: float, small_sz: float):
    cy = _f(getattr(code_ln, "y0", 0.0))
    cx = _f(getattr(code_ln, "x0", 0.0))
    y_tol = max(9.5, 1.15 * small_sz)

    best = None
    best_score = None
    for ln in label_lines:
        y = _f(getattr(ln, "y0", 0.0))
        if abs(y - cy) > y_tol:
            continue
        x = _f(getattr(ln, "x0", 0.0))
        if x >= cx - 12.0:
            continue
        dx = cx - x
        if dx > 360.0:
            continue

        t = (getattr(ln, "text", "") or "").strip()
        if not t:
            continue

        # Prefer true row labels; avoid grabbing "filled values" sitting close to the widget.
        too_close_to_widget = dx < 38.0 and x > left_margin_x + 85.0

        score = abs(y - cy) * 2.0 + dx * 0.18
        score += 0.03 * max(0.0, x - left_margin_x)  # indented text is less likely the primary stem
        score += 18.0 if _looks_like_choice_legend(t) else 0.0
        score += 10.0 if _looks_like_definition_sentence(t) else 0.0
        score += 10.0 if too_close_to_widget else 0.0

        if best_score is None or score < best_score:
            best_score = score
            best = ln

    return best


def _find_prompt_above(label_lines, code_ln, left_margin_x: float, small_sz: float):
    cy = _f(getattr(code_ln, "y0", 0.0))
    cx = _f(getattr(code_ln, "x0", 0.0))
    best = None
    best_score = None
    for ln in label_lines:
        y = _f(getattr(ln, "y0", 0.0))
        if y >= cy:
            continue
        dy = cy - y
        if dy > 260.0:
            continue
        x = _f(getattr(ln, "x0", 0.0))
        t = (getattr(ln, "text", "") or "").strip()
        if not t:
            continue

        score = dy * 1.0 + 0.08 * abs(cx - x)
        score += 0.04 * max(0.0, x - left_margin_x)
        score += 8.0 if _looks_like_choice_legend(t) else 0.0
        score += 6.0 if _looks_like_definition_sentence(t) else 0.0
        score += -5.0 if _promptish_text(t) else 0.0  # promptish is good

        if best_score is None or score < best_score:
            best_score = score
            best = ln
    return best


def _bare_phrase(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    if "?" in t or ":" in t:
        return False
    if _RE_QUESTION_STEM_NUM.match(t):
        return False
    if t.count("-") >= 2:
        return False
    # Avoid treating obvious timepoints as field labels when they behave like column headers.
    if _RE_TIMEPOINT_H.match(t):
        return True
    # Short noun phrases often show up as display rows (e.g., analyte names) and table furniture.
    words = [w for w in re.split(r"\s+", t) if w]
    if len(words) <= 4 and len(t) <= 26 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\s\-/]*", t):
        return True
    return False


def _infer_field_label(lines, code_ln, small_sz: float, label_lines, left_margin_x: float, header_lines, two_col_split):
    cx = _f(getattr(code_ln, "x0", 0.0))
    cy = _f(getattr(code_ln, "y0", 0.0))

    # 1) Prefer same-row stems (critical for grid layouts like C-SSRS and timepoint tables).
    anchor = _same_row_left_anchor(label_lines, code_ln, left_margin_x, small_sz)
    if anchor is not None:
        ax = _f(getattr(anchor, "x0", 0.0))
        text = _gather_same_row_text(
            label_lines,
            anchor,
            y_tol=max(9.5, 1.15 * small_sz),
            x_min=max(left_margin_x - 3.0, ax - 2.0),
            x_max=min(cx - 14.0, ax + 360.0),
        )
        if text and not _looks_like_choice_legend(text) and not _looks_like_chrome_or_empty(text):
            hdr = _nearest_header(header_lines, cx, cy)
            # If the row stem is likely a display-only row label (bare phrase), prefer the column header.
            if hdr and _bare_phrase(text) and not _looks_like_choice_legend(hdr):
                # In two-column pages, the same bare stem can still be a real field; keep stem there.
                if two_col_split is None:
                    return _norm_text(hdr)
            # If we accidentally latched onto a timepoint-like header (e.g., "8h postdose"),
            # walk upward for the prompt.
            if _RE_TIMEPOINT_H.match(text) or _looks_like_choice_legend(text):
                pab = _find_prompt_above(label_lines, code_ln, left_margin_x, small_sz)
                if pab is not None:
                    t2 = _norm_text((getattr(pab, "text", "") or "").strip())
                    if t2 and not _looks_like_choice_legend(t2):
                        return t2
            return _norm_text(text)

    # 2) Above-prompt fallback (handles cases where the stem sits above a choice legend).
    pab = _find_prompt_above(label_lines, code_ln, left_margin_x, small_sz)
    if pab is not None:
        base = _norm_text((getattr(pab, "text", "") or "").strip())
        if base and not _looks_like_choice_legend(base):
            # Expand multi-line prompt by grabbing nearby continuation lines.
            ay = _f(getattr(pab, "y0", 0.0))
            ax = _f(getattr(pab, "x0", 0.0))
            cont = []
            for ln in label_lines:
                y = _f(getattr(ln, "y0", 0.0))
                if y < ay - 0.5:
                    continue
                if y > ay + 32.0:
                    continue
                x = _f(getattr(ln, "x0", 0.0))
                if x < ax - 5.0 or x > ax + 420.0:
                    continue
                t = (getattr(ln, "text", "") or "").strip()
                if not t or t.startswith("["):
                    continue
                if _looks_like_choice_legend(t):
                    continue
                cont.append((y, x, t))
            if cont:
                cont.sort(key=lambda p: (p[0], p[1]))
                base = _norm_text(" ".join(p[2] for p in cont))
            return base

    # 3) Last resort: nearest reasonable label anywhere above within a wider band.
    best = None
    best_score = None
    for ln in label_lines:
        y = _f(getattr(ln, "y0", 0.0))
        if y >= cy:
            continue
        dy = cy - y
        if dy > 340.0:
            continue
        x = _f(getattr(ln, "x0", 0.0))
        t = (getattr(ln, "text", "") or "").strip()
        if not t:
            continue
        score = dy * 1.0 + 0.25 * abs(cx - x) + 0.05 * max(0.0, x - left_margin_x)
        score += 18.0 if _looks_like_choice_legend(t) else 0.0
        score += 10.0 if _looks_like_definition_sentence(t) else 0.0
        score += -4.0 if _promptish_text(t) else 0.0
        if best_score is None or score < best_score:
            best_score = score
            best = ln

    if best is None:
        return ""
    return _norm_text((getattr(best, "text", "") or "").strip())


def _infer_field_label_for_type_line(lines, type_ln, small_sz: float, label_lines, left_margin_x: float):
    # TYPE lines are technical annotations; find the nearest prompt/label around them.
    cx = _f(getattr(type_ln, "x0", 0.0))
    cy = _f(getattr(type_ln, "y0", 0.0))

    # Prefer prompt just below/right of the TYPE line (common on sparse pages with only TYPE in layer).
    cands = []
    for ln in label_lines:
        t = (getattr(ln, "text", "") or "").strip()
        if not t:
            continue
        x = _f(getattr(ln, "x0", 0.0))
        y = _f(getattr(ln, "y0", 0.0))
        if y < cy - 10.0 or y > cy + 220.0:
            continue
        if x < left_margin_x - 5.0 or x > left_margin_x + 520.0:
            continue
        score = abs(y - cy) * 1.2 + 0.25 * abs(x - cx)
        score += -6.0 if _promptish_text(t) else 0.0
        score += 12.0 if _looks_like_choice_legend(t) else 0.0
        score += 8.0 if _looks_like_definition_sentence(t) else 0.0
        cands.append((score, t))
    if not cands:
        return ""
    cands.sort(key=lambda z: z[0])
    return _norm_text(cands[0][1])


def extract(pages):
    out = []
    current_form = ""

    for page_index, lines in pages:
        if not lines:
            continue

        lines2 = _merge_split_bracket_ids(lines)
        small_sz = _page_small_font_size(lines2)

        # Collect field markers:
        # - bracket IDs (black or colored)
        # - red TYPE technical markers (colored)
        code_lines = []
        type_lines = []
        for ln in lines2:
            t = (getattr(ln, "text", "") or "").strip()
            if not t:
                continue
            if _is_field_id_text(t):
                code_lines.append(ln)
            elif _is_type_line(ln):
                type_lines.append(ln)

        # If no bracket codes exist on the page, fall back to TYPE lines (some sparse exports).
        markers = code_lines if code_lines else type_lines
        if not markers:
            continue

        title = _page_colored_title(lines2, small_sz)
        if title:
            current_form = title
        else:
            heading = _page_top_black_heading(lines2, small_sz)
            if heading and (not current_form or _page_looks_like_lab_enum_list(lines2, small_sz)):
                current_form = heading

        form_name = _norm_text(current_form)

        label_lines = [ln for ln in lines2 if _label_candidate(ln, small_sz)]
        left_margin = min((_f(getattr(ln, "x0", 0.0)) for ln in label_lines), default=0.0)

        header_lines = [ln for ln in lines2 if _header_like(ln, small_sz)]
        two_col_split = _two_col_split_x(label_lines)

        recs = []
        for mk in markers:
            if mk in type_lines:
                base = _infer_field_label_for_type_line(lines2, mk, small_sz, label_lines, left_margin)
            else:
                base = _infer_field_label(lines2, mk, small_sz, label_lines, left_margin, header_lines, two_col_split)

            base = _norm_text(base)
            if not base:
                continue
            if _looks_like_chrome_or_empty(base):
                continue
            recs.append({"base": base, "x": _f(getattr(mk, "x0", 0.0)), "y": _f(getattr(mk, "y0", 0.0))})

        if not recs:
            continue

        # Group by base label
        by_base = {}
        for r in recs:
            by_base.setdefault(r["base"], []).append(r)

        # Enhance disambiguation:
        # - Use column headers when present (preferred).
        # - Only use Left/Right when the page actually looks two-column.
        # - If neither applies and duplicates are same-row, keep a single field (avoid spurious left/right).
        for base, rs in by_base.items():
            if len(rs) == 1:
                rs[0]["field_name"] = base
                continue

            xs = [r["x"] for r in rs]
            ys = [r["y"] for r in rs]
            try:
                x_med = float(statistics.median(xs))
            except Exception:
                x_med = xs[len(xs) // 2] if xs else 0.0

            # Same-row duplicates in single-column pages are often multiple widgets for one field or artifacts.
            same_rowish = (max(ys) - min(ys)) <= 9.0 if ys else False

            for r in rs:
                hdr = _nearest_header(header_lines, r["x"], r["y"])
                if hdr and hdr.lower() not in base.lower() and not _looks_like_choice_legend(hdr):
                    r["field_name"] = _norm_text(f"{base} - {hdr}")
                else:
                    if two_col_split is not None:
                        side = "Left" if r["x"] <= x_med else "Right"
                        r["field_name"] = _norm_text(f"{base} - {side}")
                    else:
                        r["field_name"] = base

            # If we ended up with identical names and same-row duplicates in a single-column layout,
            # keep only the leftmost instance for that base (prevents spurious “Left/Right” artifacts
            # and reduces mislabeling against nearby legends).
            if two_col_split is None and same_rowish:
                rs.sort(key=lambda d: (d["y"], d["x"]))
                keep = rs[0]
                for r in rs[1:]:
                    r["drop"] = True
                keep["drop"] = False

        emitted = []
        for r in sorted(recs, key=lambda d: (d["y"], d["x"])):
            if r.get("drop"):
                continue
            field_name = _norm_text(r.get("field_name", r["base"]))
            if not field_name:
                continue
            if _looks_like_chrome_or_empty(field_name):
                continue

            # De-dup: same (form, field) within a tight vertical band
            key = (form_name, field_name)
            y = r["y"]
            dup = False
            for (k2, y2) in emitted:
                if k2 == key and abs(y2 - y) < 12.0:
                    dup = True
                    break
            if dup:
                continue

            out.append({"form_name": form_name, "field_name": field_name, "page": page_index + 1})
            emitted.append((key, y))

    return out
```
