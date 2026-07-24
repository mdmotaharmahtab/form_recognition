```python
import re
import unicodedata
from typing import List, Tuple, Dict, Any, Optional


_RE_BRACKET_CODE = re.compile(r"^\[[A-Z0-9_]{2,}\]$")
_RE_BRACKET_CODE_L = re.compile(r"^\[[A-Z0-9_]{2,}$")          # e.g. "[SCANNE"
_RE_BRACKET_CODE_R = re.compile(r"^[A-Z0-9_]{1,}\]$")          # e.g. "R]"
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

        # Update current form title if we see one (big bold/colored title)
        title = _detect_title(lines, texts, med, p90, p97)
        if title:
            current_form = title

        # If no big title, allow a small left-top section title (e.g., "Urinalysis")
        sect = _detect_section_title(lines, texts, med, p90)
        if sect:
            current_form = sect

        # Collect anchors: full codes, code fragments, and type/visibility/read-only annotations
        anchors = _collect_field_anchors(lines, texts, med)

        seen_on_page = set()

        # 1) Option-list pass: emit question label once per component, never the individual choices.
        consumed_code_idx = set()
        option_questions = _extract_option_list_questions(lines, texts, anchors, med)
        for qlab in option_questions:
            form_name = current_form or ""
            key = (form_name, qlab)
            if key in seen_on_page:
                continue
            seen_on_page.add(key)
            out.append({"form_name": form_name, "field_name": qlab, "page": page_idx0 + 1})

        for idx in option_questions._consumed_code_line_indices:  # type: ignore[attr-defined]
            consumed_code_idx.add(idx)

        # 2) Table-header extraction (e.g., "Collected", "Scan") based on anchor columns.
        for hdr in _extract_table_column_headers(lines, texts, anchors, med):
            form_name = current_form or ""
            key = (form_name, hdr)
            if key in seen_on_page:
                continue
            seen_on_page.add(key)
            out.append({"form_name": form_name, "field_name": hdr, "page": page_idx0 + 1})

        # 3) Per-anchor label extraction for remaining anchors
        #    (prefer left/above label; right labels only when clearly field-like).
        if anchors:
            # Build a y-sorted list of full code y's to band searches (keeps behavior close to prior version)
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
                key = (form_name, label)
                if key in seen_on_page:
                    continue
                seen_on_page.add(key)
                out.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})
        else:
            # Fallback: conservative extraction of left-column black/near-black question labels (no anchors present/recognized)
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
    up = t.upper()
    if up.startswith("[TYPE") or up.startswith("[VISIBILITY") or up.startswith("[READ"):
        return False
    sz = float(getattr(l, "size", 0.0) or 0.0)
    if sz and med_size and (sz < max(5.3, med_size * 0.50) or sz > max(14.0, med_size * 1.75)):
        return False
    return True


def _is_machine_code_fragment(t: str) -> bool:
    if not t:
        return False
    if ":" in t or " " in t:
        return False
    if t.upper().startswith("[TYPE") or t.upper().startswith("[VISIBILITY") or t.upper().startswith("[READ"):
        return False
    if _RE_BRACKET_CODE.match(t):
        return True
    if _RE_BRACKET_CODE_L.match(t):
        return True
    if _RE_BRACKET_CODE_R.match(t):
        return True
    return False


def _is_type_annotation_line(t: str) -> bool:
    if not t:
        return False
    if not t.startswith("["):
        return False
    up = t.upper()
    # Technical metadata lines that commonly sit directly under a field label or widget.
    return (
        up.startswith("[TYPE")
        or up.startswith("[READ-ONLY")
        or up.startswith("[READ ONLY")
        or up.startswith("[VISIBILITY")
        or up.startswith("[OID")
    )


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


def _detect_section_title(lines: List[Any], texts: List[str], med: float, p90: float) -> str:
    # Small section title near top-left (used when forms use small headers like "Urinalysis")
    best = None
    best_score = -1e9
    for l, t in zip(lines, texts):
        if not t or t.startswith("["):
            continue
        if _RE_ROW.match(t):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)

        if not (x0 <= 170 and 35 <= y0 <= 95):
            continue
        if len(t) < 5 or len(t) > 60:
            continue

        # avoid treating normal field labels as section titles
        if t.endswith(":") or t.endswith("?"):
            continue

        # prefer slightly larger/bolder lines in that band
        score = 0.0
        score += (1.0 - min(y0, 95.0) / 95.0) * 1.4
        score += (1.0 - min(x0, 170.0) / 170.0) * 1.0
        if sz:
            score += min(sz / (p90 or sz or 1.0), 1.2) * 0.9
        if getattr(l, "bold", False):
            score += 0.8

        # must look label-ish
        if not _is_labelish_line(l, t, allow_colored=True, allow_short=False):
            continue

        if score > best_score:
            best_score = score
            best = t

    return best or ""


def _looks_like_tech_bracket(t: str) -> bool:
    if not t:
        return False
    if not t.startswith("["):
        return False
    # Any bracketed technical annotation line (including wrapped ones) should not be a label.
    # Real machine field codes are handled separately and must match _RE_BRACKET_CODE (or fragment checks when anchoring).
    return True


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

    if len(t) > 180:
        return False

    return True


def _looks_like_long_rubric(label: str) -> bool:
    t = label
    if len(t) < 60:
        return False
    # Rubrics/anchors tend to be punctuation-heavy and enumerate examples.
    punct = sum(1 for ch in t if unicodedata.category(ch).startswith("P"))
    if punct < 8:
        return False
    # Common enumeration patterns without being a field label.
    enum_hits = len(re.findall(r"\b[0-9]\.\s", t))
    if enum_hits >= 1:
        return True
    if t.count(";") >= 2:
        return True
    if t.count(")") >= 3 and t.count("(") >= 2:
        return True
    return False


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
    if len(label) <= 2:
        return False
    if len(label) > 180:
        return False

    # Very long right-column text is almost never a data-entry field label on these forms.
    if x0 > 330 and len(label) > 60 and not (label.endswith(":") or label.endswith("?")):
        return False

    # Avoid rubric/anchor paragraphs.
    if _looks_like_long_rubric(label) and not (label.endswith(":") or label.endswith("?")):
        return False

    # Avoid metadata-like "values:" fragments that are not user-facing labels.
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
            continue
        if _is_type_annotation_line(t):
            anchors.append({"i": i, "kind": "type_annot"})
            continue
        if _is_machine_code_fragment(t):
            anchors.append({"i": i, "kind": "code_frag"})
            continue
    return anchors


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
) -> Optional[int]:
    cx = float(getattr(code_l, "x0", 0.0) or 0.0)
    cy = float(getattr(code_l, "y0", 0.0) or 0.0)

    best_i = None
    best_score = -1e9
    for i, (l, t) in enumerate(zip(lines, texts)):
        if not _is_labelish_line(l, t, allow_colored=allow_colored, allow_short=True):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)
        if x0 <= cx + 2:
            continue
        dx = x0 - cx
        dy = abs(y0 - cy)
        if dx > dx_max or dy > dy_max:
            continue

        if require_fieldlike:
            # Don't choose rubric-ish / long instruction snippets as right labels.
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


def _merge_wrapped_label(lines: List[Any], texts: List[str], start_i: int, *, band, med: float, allow_colored: bool = False) -> str:
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

        if _looks_like_tech_bracket(t) or _RE_BRACKET_CODE.match(t):
            if parts:
                break
            continue

        if not _is_labelish_line(l, t, allow_colored=allow_colored, allow_short=True):
            if parts and prev_y is not None and (y0 - prev_y) > max_gap:
                break
            continue

        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        sz = float(getattr(l, "size", 0.0) or 0.0)

        if not parts:
            parts.append(t)
            prev_y = y0
            continue

        if prev_y is not None and (y0 - prev_y) > max_gap:
            break

        if abs(x0 - base_x) > x_tol and x0 > base_x:
            break

        if base_sz and sz and abs(sz - base_sz) > 3.2:
            break

        parts.append(t)
        prev_y = y0

        if t.endswith("?") or t.endswith(":"):
            break

    return _norm(" ".join(parts))


def _final_label_sanitize(label: str, *, x0: float) -> str:
    label = _norm(label)
    if not _plausible_field_label(label, x0=x0):
        return ""
    return label


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

    # 1) Right-of-code label only when it looks like a real field label (prevents "Current/Never" options)
    right_i = _nearest_right_text(
        lines,
        texts,
        code_l,
        dx_max=max(260.0, med * 24.0),
        dy_max=max(14.0, med * 1.4),
        med=med,
        allow_colored=False,
        require_fieldlike=True,
    )
    if right_i is not None:
        rx0 = float(getattr(lines[right_i], "x0", 0.0) or 0.0)
        merged = _merge_wrapped_label(lines, texts, right_i, band=(band_top, band_bot), med=med, allow_colored=False)
        merged = _final_label_sanitize(merged, x0=rx0)
        if merged:
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

        if not _plausible_field_label(t, x0=x0):
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

            if not _plausible_field_label(t, x0=x0):
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
        if not _plausible_field_label(t, x0=x0):
            continue
        if t in seen:
            continue
        seen.add(t)
        labels.append(t)

    return labels


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
            dx_max=max(260.0, med * 24.0),
            dy_max=max(16.0, med * 1.6),
            med=med,
            allow_colored=False,
            require_fieldlike=False,
        )
        if ri is None:
            continue
        rt = texts[ri]
        # "choice tokens" are usually short and not punctuated as labels
        if len(rt) > 22:
            continue
        if rt.endswith(":") or rt.endswith("?"):
            continue
        if _looks_like_tech_bracket(rt):
            continue
        # Keep very short/compact tokens as option candidates.
        nodes.append({"code_i": i, "x": float(getattr(code_l, "x0", 0.0) or 0.0), "y": float(getattr(code_l, "y0", 0.0) or 0.0)})

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

    x_tol_v = max(28.0, med * 2.8)
    y_gap_v = max(28.0, med * 2.8)
    y_tol_h = max(16.0, med * 1.6)
    x_gap_h = max(160.0, med * 16.0)

    for a in range(len(nodes)):
        for b in range(a + 1, len(nodes)):
            xa, ya = nodes[a]["x"], nodes[a]["y"]
            xb, yb = nodes[b]["x"], nodes[b]["y"]
            dx = abs(xa - xb)
            dy = abs(ya - yb)

            # Vertical adjacency (same column)
            if dx <= x_tol_v and dy <= y_gap_v:
                union(a, b)
                continue
            # Horizontal adjacency (same row)
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
    # Search both: (a) left-of options spanning the box, (b) just above the box (for horizontal rows).
    band_top = max(0.0, y_min - max(80.0, med * 9.0))
    band_bot = y_max + max(32.0, med * 3.8)

    # Candidate must be clearly a label (longer; often ends with ":" or "?")
    best_i = None
    best_score = -1e9

    for i, (l, t) in enumerate(zip(lines, texts)):
        if not _is_labelish_line(l, t, allow_colored=False, allow_short=False):
            continue
        x0 = float(getattr(l, "x0", 0.0) or 0.0)
        y0 = float(getattr(l, "y0", 0.0) or 0.0)

        if y0 < band_top or y0 > band_bot:
            continue

        left_ok = x0 <= x_min - max(18.0, med * 1.8)
        above_ok = (y0 <= y_min - max(4.0, med * 0.4)) and (x0 <= x_max) and (x0 >= x_min - max(120.0, med * 12.0))
        if not (left_ok or above_ok):
            continue

        if not _plausible_field_label(t, x0=x0):
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
    merged = _merge_wrapped_label(lines, texts, best_i, band=(band_top, band_bot), med=med, allow_colored=False)
    return _final_label_sanitize(merged, x0=bx0)


def _extract_table_column_headers(lines: List[Any], texts: List[str], anchors: List[Dict[str, Any]], med: float) -> List[str]:
    # Cluster anchors by x; for each cluster with multiple anchors, look for a short label just above the first anchor.
    if not anchors:
        return []

    # Use a subset of anchors that likely reflect field/widget columns.
    pts = []
    for a in anchors:
        i = a["i"]
        l = lines[i]
        t = texts[i]
        if not t:
            continue
        x = float(getattr(l, "x0", 0.0) or 0.0)
        y = float(getattr(l, "y0", 0.0) or 0.0)
        if y < 60:
            continue
        # Avoid using right-column instruction blocks as columns.
        if x > 520:
            continue
        pts.append((x, y))

    if len(pts) < 2:
        return []

    x_tol = max(30.0, med * 3.0)
    cols: List[Dict[str, Any]] = []
    for x, y in sorted(pts, key=lambda p: p[0]):
        placed = False
        for c in cols:
            if abs(x - c["x_mean"]) <= x_tol:
                c["xs"].append(x)
                c["ys"].append(y)
                c["x_mean"] = sum(c["xs"]) / len(c["xs"])
                placed = True
                break
        if not placed:
            cols.append({"xs": [x], "ys": [y], "x_mean": x})

    headers: List[str] = []
    for c in cols:
        if len(c["ys"]) < 2:
            continue
        y_first = min(c["ys"])
        x_col = c["x_mean"]

        # Search in a tight band just above the first widget/code in that column.
        y_top = max(0.0, y_first - max(48.0, med * 5.0))
        y_bot = y_first - max(3.0, med * 0.25)

        best_i = None
        best_score = -1e9
        for i, (l, t) in enumerate(zip(lines, texts)):
            if not _is_labelish_line(l, t, allow_colored=True, allow_short=True):
                continue
            x0 = float(getattr(l, "x0", 0.0) or 0.0)
            y0 = float(getattr(l, "y0", 0.0) or 0.0)

            if y0 < y_top or y0 > y_bot:
                continue
            if abs(x0 - x_col) > max(70.0, med * 7.0):
                continue
            if x0 > 520:
                continue

            # Must not be rubric-ish; allow short words here (these are column headers).
            if _looks_like_long_rubric(t):
                continue
            if len(t) > 40:
                continue

            score = -abs(x0 - x_col) * 0.05 - abs(y0 - (y_first - max(18.0, med * 2.0))) * 0.08
            score += min(len(t), 20) * 0.05
            if getattr(l, "bold", False):
                score += 0.3

            if score > best_score:
                best_score = score
                best_i = i

        if best_i is None:
            continue

        hx0 = float(getattr(lines[best_i], "x0", 0.0) or 0.0)
        merged = _merge_wrapped_label(lines, texts, best_i, band=(y_top, y_first + max(8.0, med * 0.9)), med=med, allow_colored=True)
        merged = _norm(merged)
        if not merged:
            continue
        if _looks_like_tech_bracket(merged) or _RE_BRACKET_CODE.match(merged):
            continue
        if len(merged) <= 2 or len(merged) > 60:
            continue
        if _looks_like_long_rubric(merged):
            continue
        # Avoid obvious option-phrasey punctuation at the end.
        if merged.endswith("."):
            continue

        headers.append(merged)

    # De-dup within page
    seen = set()
    uniq = []
    for h in headers:
        if h in seen:
            continue
        seen.add(h)
        uniq.append(h)
    return uniq
```
