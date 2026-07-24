```python
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple


_RE_BRACKET_CODE = re.compile(r"^\[[A-Z0-9_]{2,}\]$")
_RE_BRACKET_CODE_L = re.compile(r"^\[[A-Z0-9_]{2,}$")  # e.g. "[SCANNE"
_RE_BRACKET_CODE_R = re.compile(r"^[A-Z0-9_]{1,}\]$")  # e.g. "R]"
_RE_ROW = re.compile(r"^Row\s+\d+\s*$", re.IGNORECASE)


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        texts = [_norm(getattr(l, "text", "")) for l in lines]
        sizes = sorted(
            float(getattr(l, "size", 0.0) or 0.0)
            for l, t in zip(lines, texts)
            if t
        )
        if not sizes:
            continue

        med = _quantile_sorted(sizes, 0.5)
        p90 = _quantile_sorted(sizes, 0.9)
        p97 = _quantile_sorted(sizes, 0.97)

        # Prefer robust form-title detection; only fall back to section title if we have no form yet.
        title = _detect_form_title(lines, texts, med, p90, p97)
        if title:
            current_form = title
        elif not current_form:
            sect = _detect_section_title(lines, texts, med, p90)
            if sect:
                current_form = sect

        anchors = _collect_field_anchors(lines, texts, med)

        seen_on_page = set()
        consumed_code_idx = set()

        # 1) Option-list pass: emit only the question label per group (never the choices).
        option_questions = _extract_option_list_questions(lines, texts, anchors, med)
        for qlab in option_questions:
            form_name = current_form or ""
            if _sameish(form_name, qlab):
                continue
            key = (form_name, qlab)
            if key in seen_on_page:
                continue
            seen_on_page.add(key)
            out.append({"form_name": form_name, "field_name": qlab, "page": page_idx0 + 1})

        for idx in getattr(option_questions, "_consumed_code_line_indices", []):
            consumed_code_idx.add(idx)

        # 2) Per-anchor extraction (skip option-list anchors so we don't output the option tokens).
        if anchors:
            code_ys = sorted(
                float(getattr(lines[a["i"]], "y0", 0.0) or 0.0)
                for a in anchors
                if a["kind"] == "code_full"
            )

            for a in anchors:
                if a["kind"] != "code_full":
                    continue
                i = a["i"]
                if i in consumed_code_idx:
                    continue

                code_l = lines[i]
                label = _label_for_code(lines, texts, code_l, code_ys, med)
                if not label:
                    continue

                form_name = current_form or ""
                if _sameish(form_name, label):
                    continue

                key = (form_name, label)
                if key in seen_on_page:
                    continue
                seen_on_page.add(key)
                out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})

        # 3) Punctuated prompts pass (catches pages without usable anchors; also catches missed labels).
        for label in _extract_punctuated_prompts(lines, texts, med, p90):
            form_name = current_form or ""
            if _sameish(form_name, label):
                continue
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


def _sameish(a: str, b: str) -> bool:
    a = _norm(a).casefold()
    b = _norm(b).casefold()
    return bool(a) and a == b


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
    if not t or not _RE_BRACKET_CODE.match(t):
        return False
    up = t.upper()
    if up.startswith("[TYPE") or up.startswith("[VISIBILITY") or up.startswith("[READ") or up.startswith("[OID"):
        return False
    sz = float(getattr(l, "size", 0.0) or 0.0)
    if sz and med_size:
        if sz < max(5.3, med_size * 0.50):
            return False
        if sz > max(14.5, med_size * 1.90):
            return False
    return True


def _is_machine_code_fragment(t: str) -> bool:
    if not t:
        return False
    if ":" in t or " " in t:
        return False
    up = t.upper()
    if up.startswith("[TYPE") or up.startswith("[VISIBILITY") or up.startswith("[READ") or up.startswith("[OID"):
        return False
    return bool(_RE_BRACKET_CODE.match(t) or _RE_BRACKET_CODE_L.match(t) or _RE_BRACKET_CODE_R.match(t))


def _is_type_annotation_line(t: str) -> bool:
    if not t or not t.startswith("["):
        return False
    up = t.upper()
    return (
        up.startswith("[TYPE")
        or up.startswith("[READ-ONLY")
        or up.startswith("[READ ONLY")
        or up.startswith("[VISIBILITY")
        or up.startswith("[OID")
    )


def _looks_like_tech_bracket(t: str) -> bool:
    return bool(t) and t.startswith("[")


def _looks_like_long_rubric(label: str) -> bool:
    t = label
    if len(t) < 55:
        return False
    punct = sum(1 for ch in t if unicodedata.category(ch).startswith("P"))
    if punct >= 10:
        return True
    if t.count(";") >= 1 and len(t) >= 70:
        return True
    if t.count(")") >= 3 and t.count("(") >= 2:
        return True
    # narrative-ish multi-clause examples
    low = t.lower()
    if len(t) >= 65 and ((" but " in low) or (" so " in low) or (" before " in low) or (" after " in low)):
        return True
    if len(t) >= 70 and t.count(",") >= 3:
        return True
    return False


def _is_instruction_block(l: Any, t: str, med: float) -> bool:
    # Common right-column red instruction/value-anchor paragraphs; never field labels.
    if not t:
        return True
    if not bool(getattr(l, "non_black", False)):
        return False
    x0 = float(getattr(l, "x0", 0.0) or 0.0)
    y0 = float(getattr(l, "y0", 0.0) or 0.0)
    sz = float(getattr(l, "size", 0.0) or 0.0)
    if x0 >= 300 and y0 <= 140 and (sz <= max(med * 1.05, 9.0)):
        return True
    return False


def _is_labelish_line(
    l: Any,
    t: str,
    *,
    allow_colored: bool = False,
    allow_short: bool = True,
    med: float = 0.0,
) -> bool:
    if not t:
        return False
    if _RE_ROW.match(t):
        return False
    if _looks_like_tech_bracket(t):
        return False
    if not allow_colored and bool(getattr(l, "non_black", False)):
        return False
    if not allow_colored and med and _is_instruction_block(l, t, med):
        return False
    if all(unicodedata.category(ch).startswith("P") or ch.isspace() for ch in t):
        return False

    has_letter = any(unicodedata.category(ch).startswith("L") for ch in t)
    if not has_letter:
        if len(t) < (4 if allow_short else 8):
            return False
        if sum(ch.isalnum() for ch in t) < (3 if allow_short else 5):
            return False

    if not allow_short and len(t) < 6:
        return False
    if len(t) > 200:
        return False
    return True


def _plausible_field_label(label: str, *, x0: float) -> bool:
    label = _norm(label)
    if not label:
        return False
    if _RE_ROW.match(label):
        return False
    if _looks_like_tech_bracket(label):
        return False
    if _RE_BRACKET_CODE.match(label):
        return False
    if len(label) <= 2 or len(label) > 180:
        return False

    # Avoid rubric/anchor paragraphs.
    if _looks_like_long_rubric(label) and not (label.endswith(":") or label.endswith("?")):
        return False

    # Very long right-column text is almost never a data-entry field label on these forms.
    if x0 > 300 and len(label) > 55 and not (label.endswith(":") or label.endswith("?")):
        return False

    # Metadata-like fragments.
    if "values:" in label.lower() and len(label) > 24 and not label.endswith(":"):
        return False

    return True


def _collect_field_anchors(lines: List[Any], texts: List[str], med: float) -> List[Dict[str, Any]]:
    anchors: List[Dict[str, Any]] = []
    for i, (l, t) in enumerate(zip(lines, texts)):
        if not t:
            continue
        if _is_field_code_line(l, t, med):
            anchors.append({"i": i, "kind": "code_full"})
        elif _is_type_annotation_line(t):
            anchors.append({"i": i, "kind": "type_annot"})
        elif _is_machine_code_fragment(t):
            anchors.append({"i": i, "kind": "code_frag"})
    return anchors


def _detect_form_title(lines: List[Any], texts: List[str], med: float, p90: float, p97: float) -> str:
    # Robust to centered titles; still resists small red instruction blocks.
    candidates = []
    for l, t in zip(lines, texts):
        if not t or t.startswith("[") or _RE_ROW.match(t):
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)
        if y0 > 125:
            continue

        if _is_instruction_block(l, t, med):
            continue

        is_bold = bool(getattr(l, "bold", False))
        is_colored = bool(getattr(l, "non_black", False))

        # Must be clearly larger than body.
        min_sz = max(10.0, med * 1.22, p90 * 1.02)
        if not (sz and sz >= min_sz):
            continue

        if not (is_bold or is_colored):
            continue

        if not _is_labelish_line(l, t, allow_colored=True, allow_short=False, med=med):
            continue
        if len(t) < 6 or len(t) > 90:
            continue

        # Score: large + near top + near left/center.
        score = 0.0
        score += (sz / (p97 or sz or 1.0)) * 3.2
        score += (1.0 - min(y0, 125.0) / 125.0) * 2.2
        # prefer left-ish but allow centered
        score += (1.0 - min(abs(x0 - 260.0), 260.0) / 260.0) * 0.9
        score += min(len(t), 80) / 80.0
        if is_colored:
            score += 0.4
        if is_bold:
            score += 0.4

        candidates.append((score, t))

    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


def _detect_section_title(lines: List[Any], texts: List[str], med: float, p90: float) -> str:
    # Small section title near top-left; avoid capturing single-word response options.
    best = None
    best_score = -1e9
    for l, t in zip(lines, texts):
        if not t or t.startswith("[") or _RE_ROW.match(t):
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)

        if not (x0 <= 190 and 32 <= y0 <= 105):
            continue
        if len(t) < 8 or len(t) > 60:
            continue
        if t.endswith(":") or t.endswith("?"):
            continue
        if bool(getattr(l, "non_black", False)):
            continue

        # Must stand out a bit.
        if sz and (sz < max(9.0, med * 1.06, p90 * 0.96)):
            continue

        if not _is_labelish_line(l, t, allow_colored=False, allow_short=False, med=med):
            continue

        score = 0.0
        score += (1.0 - min(y0, 105.0) / 105.0) * 1.4
        score += (1.0 - min(x0, 190.0) / 190.0) * 1.0
        if sz:
            score += min(sz / (p90 or sz or 1.0), 1.35) * 0.9
        if getattr(l, "bold", False):
            score += 0.8

        if score > best_score:
            best_score = score
            best = t

    return best or ""


def _is_option_token(t: str) -> bool:
    tt = _norm(t)
    if not tt:
        return False
    if ":" in tt or "?" in tt:
        return False
    if tt.endswith("."):
        return False
    if _looks_like_tech_bracket(tt) or _RE_BRACKET_CODE.match(tt):
        return False
    if _looks_like_long_rubric(tt):
        return False
    # compact (often single/two-word) choices like "Never", "Per Week", "None"
    words = tt.split()
    if len(tt) <= 14 and 1 <= len(words) <= 3 and not any(ch.isdigit() for ch in tt):
        return True
    return False


def _nearest_right_text(
    lines: List[Any],
    texts: List[str],
    code_l: Any,
    *,
    dx_max: float,
    dy_max: float,
    med: float,
    allow_colored: bool = False,
    require_fieldlike: bool = False,
    require_not_option_token: bool = False,
) -> Optional[int]:
    cx = float(getattr(code_l, "x0", 0.0) or 0.0)
    cy = float(getattr(code_l, "y0", 0.0) or 0.0)

    best_i = None
    best_score = -1e9
    for i, (l, t) in enumerate(zip(lines, texts)):
        if not _is_labelish_line(l, t, allow_colored=allow_colored, allow_short=True, med=med):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if x0 <= cx + 2:
            continue
        dx = x0 - cx
        dy = abs(y0 - cy)
        if dx > dx_max or dy > dy_max:
            continue

        if require_not_option_token and _is_option_token(t):
            continue

        if require_fieldlike:
            if not _plausible_field_label(t, x0=x0):
                continue

        sz = float(getattr(l, "size", 0.0) or 0.0)
        score = -(dy * 2.2) - (dx * 0.08) + min(len(t), 40) * 0.02
        if sz and med and abs(sz - med) <= 2.5:
            score += 0.6
        if getattr(l, "bold", False):
            score += 0.3
        if score > best_score:
            best_score = score
            best_i = i

    return best_i


def _merge_wrapped_label(
    lines: List[Any],
    texts: List[str],
    start_i: int,
    *,
    band,
    med: float,
    allow_colored: bool = False,
    max_lines: int = 3,
) -> str:
    band_top, band_bot = band
    if start_i < 0 or start_i >= len(lines):
        return ""

    base_l = lines[start_i]
    base_x = float(getattr(base_l, "x0", 0.0) or 0.0)
    base_sz = float(getattr(base_l, "size", 0.0) or 0.0)

    max_gap = max(11.0, (base_sz or med or 8.0) * 1.7)
    x_tol = max(34.0, (base_sz or med or 8.0) * 4.0)

    parts: List[str] = []
    prev_y = None
    lines_used = 0

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

        if not allow_colored and bool(getattr(l, "non_black", False)):
            if parts:
                break
            continue

        if _looks_like_tech_bracket(t) or _RE_BRACKET_CODE.match(t):
            if parts:
                break
            continue

        if not _is_labelish_line(l, t, allow_colored=allow_colored, allow_short=True, med=med):
            if parts and prev_y is not None and (y0 - prev_y) > max_gap:
                break
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)

        if not parts:
            parts.append(t)
            prev_y = y0
            lines_used = 1
            if t.endswith("?") or t.endswith(":"):
                break
            continue

        if prev_y is not None and (y0 - prev_y) > max_gap:
            break
        if abs(x0 - base_x) > x_tol and x0 > base_x:
            break
        if base_sz and sz and abs(sz - base_sz) > 3.2:
            break

        # Avoid swallowing long narrative/instruction paragraphs as "label wraps".
        if len(t.split()) >= 12 and not (t.endswith("?") or t.endswith(":")):
            break

        parts.append(t)
        prev_y = y0
        lines_used += 1
        if lines_used >= max_lines:
            break
        if t.endswith("?") or t.endswith(":"):
            break

    return _norm(" ".join(parts))


def _final_label_sanitize(label: str, *, x0: float) -> str:
    label = _norm(label)
    if not _plausible_field_label(label, x0=x0):
        return ""
    return label


def _right_label_strict_enough(t: str) -> bool:
    tt = _norm(t)
    if not tt:
        return False
    if tt.endswith(":") or tt.endswith("?"):
        return True
    words = tt.split()
    if len(words) >= 2 and len(tt) >= 10:
        return True
    if len(tt) >= 14:
        return True
    return False


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

    # 1) Right-of-code label: only if it's clearly a label (prevents emitting choice tokens like "Never", "Current").
    right_i = _nearest_right_text(
        lines,
        texts,
        code_l,
        dx_max=max(260.0, med * 24.0),
        dy_max=max(14.0, med * 1.4),
        med=med,
        allow_colored=False,
        require_fieldlike=True,
        require_not_option_token=True,
    )
    if right_i is not None:
        rt = texts[right_i]
        if _right_label_strict_enough(rt):
            rx0 = float(getattr(lines[right_i], "x0", 0.0) or 0.0)
            merged = _merge_wrapped_label(lines, texts, right_i, band=(band_top, band_bot), med=med, allow_colored=False)
            merged = _final_label_sanitize(merged, x0=rx0)
            if merged:
                return merged

    # 2) Left-of-code near same y (most common).
    best_i = None
    best_score = -1e9
    for i, (l, t) in enumerate(zip(lines, texts)):
        if not _is_labelish_line(l, t, allow_colored=False, allow_short=True, med=med):
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

        if not _plausible_field_label(t, x0=x0):
            continue

        # Avoid selecting compact option-like tokens as "labels".
        if _is_option_token(t) and not (t.endswith(":") or t.endswith("?")):
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

    # 3) Above-left fallback.
    if best_i is None:
        for i, (l, t) in enumerate(zip(lines, texts)):
            if not _is_labelish_line(l, t, allow_colored=False, allow_short=False, med=med):
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

            if not _plausible_field_label(t, x0=x0):
                continue
            if _is_option_token(t) and not (t.endswith(":") or t.endswith("?")):
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

    lx0 = float(getattr(lines[best_i], "x0", 0.0) or 0.0)
    merged = _merge_wrapped_label(lines, texts, best_i, band=(band_top, band_bot), med=med, allow_colored=False)
    return _final_label_sanitize(merged, x0=lx0)


def _extract_option_list_questions(lines: List[Any], texts: List[str], anchors: List[Dict[str, Any]], med: float):
    # Returns a list-like object with attribute `_consumed_code_line_indices`.
    code_is = [a["i"] for a in anchors if a["kind"] == "code_full"]
    nodes = []
    for i in code_is:
        code_l = lines[i]
        ri = _nearest_right_text(
            lines,
            texts,
            code_l,
            dx_max=max(280.0, med * 26.0),
            dy_max=max(18.0, med * 1.9),
            med=med,
            allow_colored=False,
            require_fieldlike=False,
            require_not_option_token=False,
        )
        if ri is None:
            continue
        rt = texts[ri]
        # choice tokens: compact, not punctuated as a prompt label
        if len(rt) > 24:
            continue
        if rt.endswith(":") or rt.endswith("?"):
            continue
        if _looks_like_tech_bracket(rt):
            continue
        if _looks_like_long_rubric(rt):
            continue
        nodes.append(
            {
                "code_i": i,
                "x": float(getattr(code_l, "x0", 0.0) or 0.0),
                "y": float(getattr(code_l, "y0", 0.0) or 0.0),
            }
        )

    if len(nodes) < 3:
        class _Res(list):
            _consumed_code_line_indices: List[int] = []
        return _Res()

    parent = list(range(len(nodes)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int):
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra

    # More forgiving clustering to avoid falling back to per-option extraction.
    x_tol_v = max(45.0, med * 4.8)
    y_gap_v = max(44.0, med * 4.2)
    y_tol_h = max(20.0, med * 2.0)
    x_gap_h = max(240.0, med * 24.0)

    for a in range(len(nodes)):
        for b in range(a + 1, len(nodes)):
            xa, ya = nodes[a]["x"], nodes[a]["y"]
            xb, yb = nodes[b]["x"], nodes[b]["y"]
            dx = abs(xa - xb)
            dy = abs(ya - yb)

            if dx <= x_tol_v and dy <= y_gap_v:
                union(a, b)
                continue
            if dy <= y_tol_h and dx <= x_gap_h:
                union(a, b)

    comps: Dict[int, List[int]] = {}
    for idx in range(len(nodes)):
        r = find(idx)
        comps.setdefault(r, []).append(idx)

    consumed: List[int] = []
    qlabels: List[str] = []

    for comp_idxs in comps.values():
        if len(comp_idxs) < 3:
            continue

        xs = [nodes[k]["x"] for k in comp_idxs]
        ys = [nodes[k]["y"] for k in comp_idxs]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)

        # Reject huge components that likely span multiple questions.
        if (y_max - y_min) > max(260.0, med * 26.0):
            continue

        q = _question_label_for_box(lines, texts, x_min, x_max, y_min, y_max, med)
        if not q:
            continue

        qlabels.append(q)
        for k in comp_idxs:
            consumed.append(nodes[k]["code_i"])

    class _Res(list):
        _consumed_code_line_indices: List[int] = []

    res = _Res(qlabels)
    res._consumed_code_line_indices = consumed
    return res


def _question_label_for_box(
    lines: List[Any],
    texts: List[str],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    med: float,
) -> str:
    band_top = max(0.0, y_min - max(90.0, med * 10.0))
    band_bot = y_max + max(34.0, med * 4.0)

    best_i = None
    best_score = -1e9

    for i, (l, t) in enumerate(zip(lines, texts)):
        if not _is_labelish_line(l, t, allow_colored=False, allow_short=False, med=med):
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)

        if y0 < band_top or y0 > band_bot:
            continue

        left_ok = x0 <= x_min - max(18.0, med * 1.8)
        above_ok = (y0 <= y_min - max(4.0, med * 0.4)) and (x0 <= x_max + max(40.0, med * 4.0))
        if not (left_ok or above_ok):
            continue

        if not _plausible_field_label(t, x0=x0):
            continue

        # Must look like a prompt (avoid selecting any of the choice tokens).
        if _is_option_token(t) and not (t.endswith(":") or t.endswith("?")):
            continue

        dy = abs(y0 - (y_min - max(10.0, med * 1.2)))
        score = -(dy * 0.8)
        score += min(len(t), 140) * 0.02
        if t.endswith(":") or t.endswith("?"):
            score += 1.3
        if getattr(l, "bold", False):
            score += 0.6
        if x0 < 220:
            score += 0.4

        if score > best_score:
            best_score = score
            best_i = i

    if best_i is None:
        return ""

    bx0 = float(getattr(lines[best_i], "x0", 0.0) or 0.0)
    merged = _merge_wrapped_label(lines, texts, best_i, band=(band_top, band_bot), med=med, allow_colored=False, max_lines=3)
    return _final_label_sanitize(merged, x0=bx0)


def _extract_punctuated_prompts(lines: List[Any], texts: List[str], med: float, p90: float) -> List[str]:
    # Find prompt-like labels even when there are no machine anchors.
    # Focus on left/middle column; require ":" present (end or internal) or ending "?".
    cands: List[Tuple[float, int]] = []
    for i, (l, t) in enumerate(zip(lines, texts)):
        if not t:
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)

        if y0 < 65:
            continue
        if x0 > 420:
            continue
        if bool(getattr(l, "non_black", False)):
            continue
        if _looks_like_tech_bracket(t) or _RE_BRACKET_CODE.match(t) or _RE_ROW.match(t):
            continue
        if med and _is_instruction_block(l, t, med):
            continue
        if sz and med:
            if sz < max(6.8, med * 0.72):
                continue
            if sz > max(13.5, med * 1.55, p90 * 1.15):
                continue

        tt = _norm(t)
        if len(tt) < 4 or len(tt) > 140:
            continue
        if _looks_like_long_rubric(tt):
            continue

        has_prompt_punct = tt.endswith("?") or tt.endswith(":") or (":" in tt and tt.split(":", 1)[0].strip() and len(tt.split(":", 1)[0].strip()) <= 45)
        if not has_prompt_punct:
            continue

        if not _is_labelish_line(l, tt, allow_colored=False, allow_short=False, med=med):
            continue

        if not _plausible_field_label(tt, x0=x0):
            continue

        # Prefer bold and left-ish.
        score = 0.0
        score += (1.0 - min(x0, 420.0) / 420.0) * 0.7
        score += (1.0 - min(y0, 800.0) / 800.0) * 0.2
        if getattr(l, "bold", False):
            score += 0.5
        if tt.endswith("?") or tt.endswith(":"):
            score += 0.25
        cands.append((score, i))

    # Merge wrapped prompt lines and de-dup.
    used = set()
    labels: List[str] = []
    for _, i in sorted(cands, key=lambda p: (-p[0], p[1])):
        if i in used:
            continue
        l = lines[i]
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)

        band_top = max(0.0, y0 - max(8.0, med * 1.0))
        band_bot = y0 + max(60.0, med * 7.0)

        merged = _merge_wrapped_label(lines, texts, i, band=(band_top, band_bot), med=med, allow_colored=False, max_lines=3)
        merged = _final_label_sanitize(merged, x0=x0)
        if not merged:
            continue

        # mark near lines as used
        for j, l2 in enumerate(lines):
            y2 = float(getattr(l2, "y0", 0.0) or 0.0)
            x2 = float(getattr(l2, "x0", 0.0) or 0.0)
            if abs(y2 - y0) <= max(26.0, med * 2.8) and abs(x2 - x0) <= max(40.0, med * 4.0):
                used.add(j)

        if merged not in labels:
            labels.append(merged)

    return labels
```
