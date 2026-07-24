```python
import re
from statistics import median
from typing import Any, Dict, List, Optional, Tuple


_RE_LINE_NO = re.compile(r"^\s*\d+(?:\.\d+)?\s*(?:\([^)]*\))?\s*$", re.UNICODE)
_RE_SAS_ANNOT = re.compile(r"^\s*\[[A-Z0-9_]+\]\s+SAS:\[", re.UNICODE)
_RE_CODE_PREFIX = re.compile(r"^\s*[A-Z]{2,}\d{3,}\s*,\s*", re.UNICODE)
_RE_SPACED_UNDERSCORES = re.compile(r"(?:_\s*){3,}", re.UNICODE)

# IMPORTANT: do NOT treat a plain bullet "•" as a checkbox; it causes narrative lists
# (e.g., exclusion criterion paragraphs) to be misclassified as option rows.
_CHECKBOX_GLYPHS = set("□☐☑■▢▣◻◼✓✔✗✘●○◯")


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()

    # Emission meta for structural furniture suppression
    emitted_meta: List[Dict[str, Any]] = []

    pages_total = len(pages) if pages else 0
    if pages_total <= 0:
        return out

    current_form_title = ""
    last_nonempty_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1
        if not lines:
            continue

        xs = [float(getattr(ln, "x0", 0.0)) for ln in lines]
        ys = [float(getattr(ln, "y0", 0.0)) for ln in lines]
        if not xs or not ys:
            continue

        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        width = max(1.0, x_max - x_min)
        height = max(1.0, y_max - y_min)

        y_tol = max(2.2, 0.0035 * height)

        # --- column estimates (same overall approach) ---
        line_no_xs = [
            float(getattr(ln, "x0", 0.0))
            for ln in lines
            if _is_line_number_cell(str(getattr(ln, "text", "")) or "")
        ]
        if line_no_xs:
            line_col_left = float(median(line_no_xs)) - 0.05 * width
        else:
            line_col_left = x_min + 0.82 * width

        option_xs = []
        for ln in lines:
            t = str(getattr(ln, "text", "")) or ""
            if _looks_like_option_text(t):
                option_xs.append(float(getattr(ln, "x0", 0.0)))
        if option_xs:
            option_col_left = float(median(option_xs)) - 0.05 * width
            option_col_left = max(option_col_left, x_min + 0.35 * width)
            option_col_left = min(option_col_left, line_col_left - 0.08 * width)
        else:
            option_col_left = min(line_col_left - 0.30 * width, x_min + 0.60 * width)

        colon_left_xs = [
            float(getattr(ln, "x0", 0.0))
            for ln in lines
            if getattr(ln, "bold", False)
            and getattr(ln, "non_black", False)
            and (str(getattr(ln, "text", "")) or "").strip().endswith(":")
            and float(getattr(ln, "x0", 0.0)) <= x_min + 0.35 * width
        ]
        if colon_left_xs:
            left_col_right = max(x_min + 0.18 * width, max(colon_left_xs) + 0.10 * width)
            left_col_right = min(left_col_right, x_min + 0.38 * width)
        else:
            left_col_right = x_min + 0.25 * width

        # --- header/body split (structural) ---
        body_top_y = _estimate_body_top_y(
            lines=lines,
            y_tol=y_tol,
            y_min=y_min,
            y_max=y_max,
            x_min=x_min,
            x_max=x_max,
            left_col_right=left_col_right,
            option_col_left=option_col_left,
            line_col_left=line_col_left,
        )
        # Keep more of the bottom; footer furniture will be removed structurally later.
        footer_cut_y = y_max - 0.03 * height

        # --- robust form title extraction (avoid table column headers like "Activity"/"Answer(s)") ---
        schedule_name = _extract_schedule_name(
            lines=lines,
            y_min=y_min,
            y_max=y_max,
            x_min=x_min,
            x_max=x_max,
            y_tol=y_tol,
            left_col_right=left_col_right,
            option_col_left=option_col_left,
            line_col_left=line_col_left,
        )
        page_form_title = _extract_form_title(
            lines=lines,
            y_min=y_min,
            y_max=y_max,
            x_min=x_min,
            x_max=x_max,
            y_tol=y_tol,
            left_col_right=left_col_right,
            option_col_left=option_col_left,
            line_col_left=line_col_left,
        )

        if page_form_title:
            current_form_title = page_form_title
        elif schedule_name and (not current_form_title):
            current_form_title = schedule_name

        page_form_fallback = _clean(current_form_title or schedule_name or last_nonempty_form or "")
        if page_form_fallback:
            last_nonempty_form = page_form_fallback

        # Work region
        work_lines = [
            ln
            for ln in lines
            if float(getattr(ln, "y0", 0.0)) >= body_top_y - y_tol
            and float(getattr(ln, "y0", 0.0)) <= footer_cut_y + y_tol
        ]

        # Header region (for entry fields like date/time/part/version, etc.)
        header_lines = [
            ln
            for ln in lines
            if float(getattr(ln, "y0", 0.0)) < body_top_y - 0.6 * y_tol
            and float(getattr(ln, "y0", 0.0)) >= y_min - y_tol
            and float(getattr(ln, "y0", 0.0)) <= y_min + 0.50 * height + y_tol
        ]

        _extract_header_fields(
            header_lines=header_lines,
            y_tol=y_tol,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            left_col_right=left_col_right,
            option_col_left=option_col_left,
            line_col_left=line_col_left,
            form_name=page_form_fallback,
            page_num=page_num,
            out=out,
            seen=seen,
            emitted_meta=emitted_meta,
        )

        # Footer colon entry fields (e.g., "Staff Initials:", "Comment:" often have drawn lines not captured as text)
        _extract_footer_colon_fields(
            lines=lines,
            y_tol=y_tol,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            left_col_right=left_col_right,
            option_col_left=option_col_left,
            line_col_left=line_col_left,
            form_name=page_form_fallback,
            page_num=page_num,
            out=out,
            seen=seen,
            emitted_meta=emitted_meta,
        )

        # --- item segmentation by line number (primary) ---
        item_starts = _find_item_start_bands(work_lines, y_tol, line_col_left)

        bands = _cluster_by_y(work_lines, y_tol) if not item_starts else None
        if item_starts:
            for i, (start_y, _start_band) in enumerate(item_starts):
                end_y = item_starts[i + 1][0] if i + 1 < len(item_starts) else (y_max + 1.0)
                seg_lines = [
                    ln
                    for ln in work_lines
                    if float(getattr(ln, "y0", 0.0)) >= start_y - y_tol
                    and float(getattr(ln, "y0", 0.0)) < end_y - 0.4 * y_tol
                ]

                seg_bands = _cluster_by_y(seg_lines, y_tol)
                _scan_bands_for_fields(
                    bands=seg_bands,
                    y_tol=y_tol,
                    body_top_y=body_top_y,
                    footer_cut_y=footer_cut_y,
                    x_min=x_min,
                    x_max=x_max,
                    y_min=y_min,
                    y_max=y_max,
                    left_col_right=left_col_right,
                    option_col_left=option_col_left,
                    line_col_left=line_col_left,
                    form_name=page_form_fallback,
                    page_num=page_num,
                    out=out,
                    seen=seen,
                    emitted_meta=emitted_meta,
                )
        else:
            _scan_bands_for_fields(
                bands=bands or [],
                y_tol=y_tol,
                body_top_y=body_top_y,
                footer_cut_y=footer_cut_y,
                x_min=x_min,
                x_max=x_max,
                y_min=y_min,
                y_max=y_max,
                left_col_right=left_col_right,
                option_col_left=option_col_left,
                line_col_left=line_col_left,
                form_name=page_form_fallback,
                page_num=page_num,
                out=out,
                seen=seen,
                emitted_meta=emitted_meta,
            )

    # --- structural furniture suppression (frequency + position), but only for "label-only" emissions ---
    if emitted_meta and pages_total >= 10:
        by_label: Dict[str, Dict[str, Any]] = {}
        for r in emitted_meta:
            k = (r.get("field_name_norm") or "").lower().strip()
            if not k:
                continue
            d = by_label.setdefault(
                k, {"pages": set(), "xs": [], "ys": [], "lens": [], "evidence": [], "forms": set()}
            )
            d["pages"].add(int(r.get("page", 0)))
            d["xs"].append(float(r.get("x_norm", 0.0)))
            d["ys"].append(float(r.get("y_norm", 0.0)))
            d["lens"].append(int(r.get("field_len", 0)))
            d["evidence"].append(str(r.get("evidence", "")))
            d["forms"].add(str(r.get("form_name_norm", "")) or "")

        furniture_keys = set()
        for k, d in by_label.items():
            page_count = len(d["pages"])
            frac = page_count / max(1, pages_total)

            # Only suppress extremely high-frequency items that also look like template furniture.
            if frac < 0.90:
                continue
            if not d["xs"] or not d["ys"]:
                continue

            # Do not suppress if it was ever seen as a real data-entry signal (placeholder/question/footer-field).
            ev = set([e for e in d.get("evidence", []) if e])
            if ev.intersection({"placeholder", "question", "footer_colon_field", "blank_entry"}):
                continue

            x_med = float(median(d["xs"]))
            y_med = float(median(d["ys"]))
            len_med = int(median(d["lens"])) if d["lens"] else 0

            in_margin = (x_med >= 0.86) or (x_med <= 0.07)
            in_footer = (y_med >= 0.82)
            in_header = (y_med <= 0.12)
            shortish = (len_med <= 22)

            # Also require that it tends to appear under many forms (typical of page furniture).
            multi_form = len([f for f in d.get("forms", set()) if f]) >= 2

            if shortish and multi_form and (in_footer or in_margin or in_header):
                furniture_keys.add(k)

        if furniture_keys:
            filtered: List[Dict[str, Any]] = []
            for r in out:
                kk = (r.get("field_name", "") or "").strip().lower()
                if kk in furniture_keys:
                    continue
                filtered.append(r)
            out = filtered

    return out


def _scan_bands_for_fields(
    bands: List[List[Any]],
    y_tol: float,
    body_top_y: float,
    footer_cut_y: float,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    left_col_right: float,
    option_col_left: float,
    line_col_left: float,
    form_name: str,
    page_num: int,
    out: List[Dict[str, Any]],
    seen: set,
    emitted_meta: List[Dict[str, Any]],
) -> None:
    n = len(bands)
    j = 0
    while j < n:
        band = bands[j]
        if not band:
            j += 1
            continue

        yb = float(getattr(band[0], "y0", 0.0))
        if yb < body_top_y - y_tol or yb > footer_cut_y + y_tol:
            j += 1
            continue

        if _band_looks_like_table_header(
            band=band,
            x_min=x_min,
            x_max=x_max,
            left_col_right=left_col_right,
            option_col_left=option_col_left,
            line_col_left=line_col_left,
        ):
            j += 1
            continue

        nonempty = [ln for ln in band if _clean(str(getattr(ln, "text", "")) or "")]
        line_no_lines = [
            ln
            for ln in nonempty
            if float(getattr(ln, "x0", 0.0)) >= line_col_left
            and _is_line_number_cell(str(getattr(ln, "text", "")) or "")
        ]
        non_line_lines = [ln for ln in nonempty if ln not in line_no_lines]

        # Skip bands that are effectively just the line number cell.
        if nonempty and (not non_line_lines):
            j += 1
            continue

        has_option = any(
            float(getattr(ln, "x0", 0.0)) >= option_col_left
            and _looks_like_option_text(str(getattr(ln, "text", "")) or "")
            for ln in non_line_lines
        )

        # Placeholder evidence (including token-style date/time boxes)
        has_placeholder_left = any(
            float(getattr(ln, "x0", 0.0)) < left_col_right
            and _looks_like_fillable_placeholder(str(getattr(ln, "text", "")) or "")
            for ln in non_line_lines
        )
        has_placeholder_mid = any(
            left_col_right <= float(getattr(ln, "x0", 0.0)) < option_col_left
            and _looks_like_fillable_placeholder(str(getattr(ln, "text", "")) or "")
            for ln in non_line_lines
        )
        has_placeholder_opt = any(
            option_col_left <= float(getattr(ln, "x0", 0.0)) < line_col_left
            and _looks_like_fillable_placeholder(str(getattr(ln, "text", "")) or "")
            for ln in non_line_lines
        )
        has_token_boxes = _band_has_token_placeholders(
            band=non_line_lines,
            left_col_right=left_col_right,
            option_col_left=option_col_left,
            line_col_left=line_col_left,
        )

        has_placeholder = has_placeholder_left or has_placeholder_mid or has_placeholder_opt or has_token_boxes

        # Colon labels that are stand-alone labels (rare), keep but avoid column-header bands.
        if (not has_option) and (not has_placeholder) and _band_looks_like_single_field_label(non_line_lines, x_min, x_max):
            for lbl in _extract_colon_labels_in_band(non_line_lines):
                if _looks_like_machine_annotation(lbl):
                    continue
                _emit_with_meta(
                    form_name=form_name,
                    field_name=lbl,
                    page_num=page_num,
                    band=band,
                    x_min=x_min,
                    x_max=x_max,
                    y_min=y_min,
                    y_max=y_max,
                    out=out,
                    seen=seen,
                    emitted_meta=emitted_meta,
                    evidence="label_only",
                )
            j += 1
            continue

        # Placeholder-driven entry rows
        if has_placeholder:
            label, consumed = _extract_multiline_entry_label(
                bands=bands,
                start_idx=j,
                y_tol=y_tol,
                left_col_right=left_col_right,
                option_col_left=option_col_left,
                line_col_left=line_col_left,
                mode="placeholder",
            )
            if label:
                _emit_with_meta(
                    form_name=form_name,
                    field_name=label,
                    page_num=page_num,
                    band=bands[j],
                    x_min=x_min,
                    x_max=x_max,
                    y_min=y_min,
                    y_max=y_max,
                    out=out,
                    seen=seen,
                    emitted_meta=emitted_meta,
                    evidence="placeholder",
                )
            j += max(1, consumed)
            continue

        # Checkbox/radio question rows
        if has_option:
            q_label, consumed = _extract_multiline_question_label(
                bands=bands,
                start_idx=j,
                y_tol=y_tol,
                left_col_right=left_col_right,
                option_col_left=option_col_left,
                line_col_left=line_col_left,
            )
            if q_label:
                _emit_with_meta(
                    form_name=form_name,
                    field_name=q_label,
                    page_num=page_num,
                    band=bands[j],
                    x_min=x_min,
                    x_max=x_max,
                    y_min=y_min,
                    y_max=y_max,
                    out=out,
                    seen=seen,
                    emitted_meta=emitted_meta,
                    evidence="question",
                )
            j += max(1, consumed)
            continue

        # Blank-value entry rows: line number present + label text, but drawn underline/boxes not captured as text.
        if line_no_lines:
            label, consumed = _extract_multiline_entry_label(
                bands=bands,
                start_idx=j,
                y_tol=y_tol,
                left_col_right=left_col_right,
                option_col_left=option_col_left,
                line_col_left=line_col_left,
                mode="blank",
            )
            if label and _looks_like_entry_row_label(label, non_line_lines, x_min, x_max, option_col_left, line_col_left):
                _emit_with_meta(
                    form_name=form_name,
                    field_name=label,
                    page_num=page_num,
                    band=bands[j],
                    x_min=x_min,
                    x_max=x_max,
                    y_min=y_min,
                    y_max=y_max,
                    out=out,
                    seen=seen,
                    emitted_meta=emitted_meta,
                    evidence="blank_entry",
                )
                j += max(1, consumed)
                continue

        j += 1


def _emit_with_meta(
    form_name: str,
    field_name: str,
    page_num: int,
    band: List[Any],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    out: List[Dict[str, Any]],
    seen: set,
    emitted_meta: List[Dict[str, Any]],
    evidence: str,
) -> None:
    form_name_c = _clean(form_name)
    field_name_c = _clean(field_name)
    if not field_name_c:
        return

    if not any(ch.isalpha() for ch in field_name_c):
        return
    if _looks_like_machine_annotation(field_name_c):
        return
    if not _looks_human_label(field_name_c):
        return

    key = (form_name_c, field_name_c, page_num)
    if key in seen:
        return
    seen.add(key)

    out.append({"form_name": form_name_c, "field_name": field_name_c, "page": page_num})

    bx = []
    by = []
    for ln in band:
        t = _clean(str(getattr(ln, "text", "")) or "")
        if not t:
            continue
        bx.append(float(getattr(ln, "x0", 0.0)))
        by.append(float(getattr(ln, "y0", 0.0)))

    if bx and by:
        x_norm = (median(bx) - x_min) / max(1e-6, (x_max - x_min))
        y_norm = (median(by) - y_min) / max(1e-6, (y_max - y_min))
        emitted_meta.append(
            {
                "page": page_num,
                "form_name_norm": form_name_c,
                "field_name_norm": field_name_c,
                "x_norm": float(x_norm),
                "y_norm": float(y_norm),
                "field_len": len(field_name_c),
                "evidence": evidence or "",
            }
        )


def _clean(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" \t\r\n-–—•·")
    return s.strip()


def _is_line_number_cell(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if "page" in t.lower():
        return False
    if len(t) > 20:
        return False
    return bool(_RE_LINE_NO.match(t))


def _looks_like_option_text(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    # Checkbox/radio glyphs
    if t[0] in _CHECKBOX_GLYPHS:
        # Require some payload after the glyph to avoid misclassifying stray marks
        rest = t[1:].strip()
        if not rest:
            return True
        alpha = sum(ch.isalpha() for ch in rest)
        digit = sum(ch.isdigit() for ch in rest)
        if (alpha + digit) == 0:
            return False
        # Options are typically short-ish phrases, not paragraphs
        return len(rest) <= 80
    # OCR-like radio "O " / "o "
    if t.startswith("O ") or t.startswith("o "):
        return True
    return False


def _looks_like_machine_annotation(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _RE_SAS_ANNOT.match(t):
        return True
    if t.startswith("[") and ("SAS:[" in t or t.count("[") >= 2):
        return True
    return False


def _looks_like_fillable_placeholder(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False

    if t.count("_") >= 3:
        return True
    if _RE_SPACED_UNDERSCORES.search(t):
        return True

    alpha = sum(ch.isalpha() for ch in t)
    digit = sum(ch.isdigit() for ch in t)
    sep = sum(ch in "-:/." for ch in t)
    if sep >= 2 and (alpha + digit) >= 2 and (alpha + digit) <= 24 and len(t) <= 28:
        letters = max(1, alpha)
        if (digit + sep) >= letters:
            return True

    if t.count("_") >= 2 and any(ch.isalpha() for ch in t) and t.upper() == t:
        return True

    return False


def _looks_like_token_placeholder(text: str) -> bool:
    t = _clean(text)
    if not t:
        return False
    # Very short uppercase tokens often used in printed date/time boxes (DD / MM / YYYY / HH / MM)
    if not t.isalpha():
        return False
    if t.upper() != t:
        return False
    if len(t) < 2 or len(t) > 4:
        return False
    # Require low diversity (repeated letters), typical of DD/MM/YY/HH
    return len(set(t)) <= 2


def _band_has_token_placeholders(
    band: List[Any],
    left_col_right: float,
    option_col_left: float,
    line_col_left: float,
) -> bool:
    toks = 0
    for ln in band:
        x = float(getattr(ln, "x0", 0.0))
        if x >= line_col_left:
            continue
        if x < left_col_right:
            continue
        if x >= option_col_left:
            continue
        t = str(getattr(ln, "text", "")) or ""
        if _looks_like_token_placeholder(t):
            toks += 1
    return toks >= 2


def _looks_human_label(text: str) -> bool:
    t = _clean(text)
    if len(t) < 4:
        return False

    alpha = sum(ch.isalpha() for ch in t)
    digit = sum(ch.isdigit() for ch in t)
    total = max(1, len(t))

    if digit >= 6 and digit / total > 0.35:
        return False

    no_space = t.replace(" ", "")
    if len(no_space) >= 8 and no_space.isupper() and digit >= 2:
        return False

    if alpha / total < 0.25:
        return False

    return True


def _strip_schedule_code(s: str) -> str:
    s = _clean(s)
    s = _RE_CODE_PREFIX.sub("", s)
    return _clean(s)


def _band_looks_like_table_header(
    band: List[Any],
    x_min: float,
    x_max: float,
    left_col_right: float,
    option_col_left: float,
    line_col_left: float,
) -> bool:
    if not band:
        return False
    colored_bold = [ln for ln in band if getattr(ln, "bold", False) and getattr(ln, "non_black", False)]
    if len(colored_bold) < 2:
        return False
    xs = [float(getattr(ln, "x0", 0.0)) for ln in colored_bold]
    if not xs:
        return False
    spread = max(xs) - min(xs)
    width = max(1.0, (x_max - x_min))
    if spread < 0.40 * width:
        return False
    leftish = any(x < left_col_right for x in xs)
    midish = any(left_col_right <= x < option_col_left for x in xs)
    rightish = any(x >= line_col_left - 0.03 * width for x in xs)
    return sum([leftish, midish, rightish]) >= 2


def _extract_schedule_name(
    lines: List[Any],
    y_min: float,
    y_max: float,
    x_min: float,
    x_max: float,
    y_tol: float,
    left_col_right: float,
    option_col_left: float,
    line_col_left: float,
) -> str:
    height = max(1.0, y_max - y_min)
    width = max(1.0, x_max - x_min)

    top_region_max_y = y_min + 0.26 * height
    top_lines = [ln for ln in lines if float(getattr(ln, "y0", 0.0)) <= top_region_max_y]
    top_bands = _cluster_by_y(top_lines, y_tol)

    # Exclude table header bands from title candidates
    header_band_ids = set()
    for idx, b in enumerate(top_bands):
        if _band_looks_like_table_header(b, x_min, x_max, left_col_right, option_col_left, line_col_left):
            header_band_ids.add(idx)

    def band_index_of(ln: Any) -> Optional[int]:
        y = float(getattr(ln, "y0", 0.0))
        for i, b in enumerate(top_bands):
            if not b:
                continue
            if abs(y - float(getattr(b[0], "y0", 0.0))) <= y_tol:
                return i
        return None

    # Primary: "schedule name slot" in top header (structural)
    y0 = y_min + 0.03 * height
    y1 = y_min + 0.22 * height
    x0 = x_min + 0.12 * width
    x1 = x_min + 0.88 * width

    cands = []
    for ln in lines:
        raw = str(getattr(ln, "text", "")) or ""
        t = (raw or "").strip()
        if len(t) < 6:
            continue
        if _is_line_number_cell(t):
            continue
        if t.endswith(":"):
            continue
        if _looks_like_machine_annotation(t):
            continue
        if _looks_like_fillable_placeholder(t):
            continue
        if _looks_like_option_text(t):
            continue

        alpha = sum(ch.isalpha() for ch in t)
        if alpha < 4:
            continue

        y = float(getattr(ln, "y0", 0.0))
        x = float(getattr(ln, "x0", 0.0))
        if not (y0 <= y <= y1 and x0 <= x <= x1):
            continue

        bi = band_index_of(ln)
        if bi is not None and bi in header_band_ids:
            continue

        x_center = (x - x_min) / max(1.0, width)
        score = (
            0 if getattr(ln, "bold", False) else 1,
            abs(0.50 - x_center),
            abs((y_min + 0.10 * height) - y),
            -len(t),
        )
        cands.append((score, t))

    if cands:
        cands.sort(key=lambda z: z[0])
        name = _strip_schedule_code(cands[0][1])
        if name and (not _looks_like_fillable_placeholder(name)) and _looks_human_label(name):
            return name

    # Fallback: top-center bold title line, excluding header bands
    title_cands = []
    for ln in lines:
        t = _clean(str(getattr(ln, "text", "")) or "")
        if len(t) < 8:
            continue
        if _looks_like_machine_annotation(t) or _looks_like_fillable_placeholder(t) or _looks_like_option_text(t):
            continue
        if t.endswith(":"):
            continue
        if sum(ch.isalpha() for ch in t) < 6:
            continue

        y = float(getattr(ln, "y0", 0.0))
        if not (y_min <= y <= y_min + 0.20 * height):
            continue

        bi = band_index_of(ln)
        if bi is not None and bi in header_band_ids:
            continue

        x = float(getattr(ln, "x0", 0.0))
        x_center = (x - x_min) / max(1.0, width)
        score = (
            0 if getattr(ln, "bold", False) else 1,
            abs(0.50 - x_center),
            -len(t),
        )
        title_cands.append((score, t))

    if not title_cands:
        return ""

    title_cands.sort(key=lambda z: z[0])
    name = _strip_schedule_code(title_cands[0][1])
    if name and _looks_human_label(name):
        return name
    return ""


def _extract_form_title(
    lines: List[Any],
    y_min: float,
    y_max: float,
    x_min: float,
    x_max: float,
    y_tol: float,
    left_col_right: float,
    option_col_left: float,
    line_col_left: float,
) -> str:
    # Form/section title should be shared by many fields and printed as a header/title.
    # Structural approach: look near top, prefer bold/non-black, avoid table header bands.
    height = max(1.0, y_max - y_min)
    width = max(1.0, x_max - x_min)

    top_region_max_y = y_min + 0.28 * height
    top_lines = [ln for ln in lines if float(getattr(ln, "y0", 0.0)) <= top_region_max_y]
    bands = _cluster_by_y(top_lines, y_tol)

    bad_band_ys = set()
    for b in bands:
        if _band_looks_like_table_header(b, x_min, x_max, left_col_right, option_col_left, line_col_left):
            yb = float(getattr(b[0], "y0", 0.0))
            bad_band_ys.add(yb)

    cands = []
    for ln in top_lines:
        t = _clean(str(getattr(ln, "text", "")) or "")
        if len(t) < 6:
            continue
        if _looks_like_machine_annotation(t) or _looks_like_fillable_placeholder(t) or _looks_like_option_text(t):
            continue
        if _is_line_number_cell(t):
            continue
        if t.endswith(":"):
            continue
        if sum(ch.isalpha() for ch in t) < 5:
            continue

        y = float(getattr(ln, "y0", 0.0))
        # Skip if in a table header band (approx by y clustering)
        if any(abs(y - yb) <= y_tol for yb in bad_band_ys):
            continue

        x = float(getattr(ln, "x0", 0.0))
        x_center = (x - x_min) / max(1.0, width)

        # Prefer centered and visually title-like
        score = (
            0 if getattr(ln, "bold", False) else 1,
            0 if getattr(ln, "non_black", False) else 1,
            abs(0.52 - x_center),
            abs((y_min + 0.10 * height) - y),
            -len(t),
        )
        cands.append((score, t))

    if not cands:
        return ""

    cands.sort(key=lambda z: z[0])
    title = _strip_schedule_code(cands[0][1])
    if title and _looks_human_label(title):
        return title
    return ""


def _cluster_by_y(lines: List[Any], tol: float) -> List[List[Any]]:
    if not lines:
        return []
    lines = sorted(lines, key=lambda ln: (float(getattr(ln, "y0", 0.0)), float(getattr(ln, "x0", 0.0))))
    bands: List[List[Any]] = []
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if not bands:
            bands.append([ln])
            continue
        if abs(y - float(getattr(bands[-1][0], "y0", 0.0))) <= tol:
            bands[-1].append(ln)
        else:
            bands.append([ln])
    return bands


def _find_item_start_bands(lines: List[Any], y_tol: float, line_col_left: float) -> List[Tuple[float, List[Any]]]:
    bands = _cluster_by_y(lines, y_tol)
    starts: List[Tuple[float, List[Any]]] = []
    for band in bands:
        has_line_no = any(
            float(getattr(ln, "x0", 0.0)) >= line_col_left
            and _is_line_number_cell(str(getattr(ln, "text", "")) or "")
            for ln in band
        )
        if has_line_no:
            starts.append((float(getattr(band[0], "y0", 0.0)), band))

    starts.sort(key=lambda t: t[0])

    dedup: List[Tuple[float, List[Any]]] = []
    for y, band in starts:
        if not dedup or abs(y - dedup[-1][0]) > y_tol:
            dedup.append((y, band))
    return dedup


def _estimate_body_top_y(
    lines: List[Any],
    y_tol: float,
    y_min: float,
    y_max: float,
    x_min: float,
    x_max: float,
    left_col_right: float,
    option_col_left: float,
    line_col_left: float,
) -> float:
    height = max(1.0, y_max - y_min)
    top_region_max_y = y_min + 0.32 * height

    bands = _cluster_by_y([ln for ln in lines if float(getattr(ln, "y0", 0.0)) <= top_region_max_y], y_tol)

    best_y: Optional[float] = None
    for band in bands:
        yb = float(getattr(band[0], "y0", 0.0))
        colored_bold = [ln for ln in band if getattr(ln, "bold", False) and getattr(ln, "non_black", False)]
        if len(colored_bold) < 2:
            continue
        xs = [float(getattr(ln, "x0", 0.0)) for ln in colored_bold]
        if not xs:
            continue
        spread = max(xs) - min(xs)

        leftish = any(x < left_col_right for x in xs)
        midish = any(left_col_right <= x < option_col_left for x in xs)
        rightish = any(x >= line_col_left - 0.02 * (x_max - x_min) for x in xs)

        if spread < 0.35 * (x_max - x_min):
            continue
        if sum([leftish, midish, rightish]) < 2:
            continue

        if best_y is None or yb > best_y:
            best_y = yb

    if best_y is not None:
        return best_y + 2.2 * y_tol

    return y_min + 0.18 * height


def _extract_colon_labels_in_band(band: List[Any]) -> List[str]:
    lbls = []
    for ln in band:
        t = _clean(str(getattr(ln, "text", "")) or "")
        if not t.endswith(":"):
            continue
        # colon labels tend to be bold/colored in these templates, but do not require it
        t = _clean(t[:-1])
        if not t:
            continue
        if not any(ch.isalpha() for ch in t):
            continue
        lbls.append(t)
    out = []
    seen = set()
    for t in lbls:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def _band_looks_like_single_field_label(band: List[Any], x_min: float, x_max: float) -> bool:
    xs = [float(getattr(ln, "x0", 0.0)) for ln in band if _clean(str(getattr(ln, "text", "")) or "")]
    if not xs:
        return False
    spread = max(xs) - min(xs)
    return spread <= 0.55 * max(1.0, (x_max - x_min))


def _extract_field_label_from_band(
    band: List[Any],
    left_col_right: float,
    option_col_left: float,
    line_col_left: float,
    allow_left: bool,
    prefer_leftish: bool,
) -> str:
    parts: List[Tuple[float, str]] = []
    for ln in band:
        x = float(getattr(ln, "x0", 0.0))
        if x >= option_col_left:
            continue
        if x >= line_col_left:
            continue
        if (not allow_left) and (x < left_col_right):
            continue

        t = _clean(str(getattr(ln, "text", "")) or "")
        if not t:
            continue
        if _is_line_number_cell(t):
            continue
        if _looks_like_option_text(t):
            continue
        if _looks_like_machine_annotation(t):
            continue
        if _looks_like_fillable_placeholder(t):
            continue
        if not any(ch.isalpha() for ch in t):
            continue

        parts.append((x, t))

    if not parts:
        return ""

    parts.sort(key=lambda z: z[0])
    label = _clean(" ".join([t for _, t in parts]))
    if not label:
        return ""

    if label.endswith(":"):
        label = _clean(label[:-1])

    # Structural guard against column headers near options boundary
    if prefer_leftish and len(label) <= 16 and label.count(" ") <= 1:
        x0 = min([x for x, _ in parts])
        if x0 >= left_col_right + 0.62 * max(1.0, (option_col_left - left_col_right)):
            return ""

    return label


def _extract_multiline_question_label(
    bands: List[List[Any]],
    start_idx: int,
    y_tol: float,
    left_col_right: float,
    option_col_left: float,
    line_col_left: float,
) -> Tuple[str, int]:
    if start_idx < 0 or start_idx >= len(bands):
        return ("", 1)

    def band_has_line_no(b: List[Any]) -> bool:
        return any(
            float(getattr(ln, "x0", 0.0)) >= line_col_left
            and _is_line_number_cell(str(getattr(ln, "text", "")) or "")
            for ln in b
        )

    def band_has_placeholder(b: List[Any]) -> bool:
        if _band_has_token_placeholders(b, left_col_right, option_col_left, line_col_left):
            return True
        for ln in b:
            x = float(getattr(ln, "x0", 0.0))
            if x >= line_col_left:
                continue
            if _looks_like_fillable_placeholder(str(getattr(ln, "text", "")) or ""):
                return True
        return False

    def band_has_option(b: List[Any]) -> bool:
        return any(
            float(getattr(ln, "x0", 0.0)) >= option_col_left
            and _looks_like_option_text(str(getattr(ln, "text", "")) or "")
            for ln in b
        )

    # Allow one preceding wrapped band (no options/placeholders/line-no)
    k0 = start_idx
    if start_idx - 1 >= 0:
        prev = bands[start_idx - 1]
        y_prev = float(getattr(prev[0], "y0", 0.0))
        y_cur = float(getattr(bands[start_idx][0], "y0", 0.0))
        if (y_cur - y_prev) <= 1.85 * y_tol and (not band_has_option(prev)) and (not band_has_placeholder(prev)) and (not band_has_line_no(prev)):
            prev_label = _extract_field_label_from_band(
                band=prev,
                left_col_right=left_col_right,
                option_col_left=option_col_left,
                line_col_left=line_col_left,
                allow_left=True,
                prefer_leftish=True,
            )
            if prev_label and len(prev_label) >= 8:
                k0 = start_idx - 1

    parts: List[str] = []
    consumed = 0
    k = k0
    while k < len(bands):
        b = bands[k]
        if band_has_line_no(b) and k > k0:
            break

        if k > k0 and band_has_placeholder(b):
            break

        if k > k0:
            y_prev = float(getattr(bands[k - 1][0], "y0", 0.0))
            y_cur = float(getattr(b[0], "y0", 0.0))
            if (y_cur - y_prev) > 2.20 * y_tol:
                break

        lbl = _extract_field_label_from_band(
            band=b,
            left_col_right=left_col_right,
            option_col_left=option_col_left,
            line_col_left=line_col_left,
            allow_left=True,
            prefer_leftish=True,
        )
        if lbl:
            parts.append(lbl)

        consumed += 1
        k += 1

        # Continue through immediate wrapped lines; allow option bands interleaved.
        if k < len(bands):
            continue

    label = _clean(" ".join(parts))
    if not label:
        return ("", max(1, consumed))

    # Structural guard: very short single-token header-like labels (even if punctuated by parentheses)
    if len(label) <= 12 and label.count(" ") <= 1 and (not any(ch in "?:./" for ch in label)):
        return ("", max(1, consumed))

    return (label, max(1, consumed))


def _extract_multiline_entry_label(
    bands: List[List[Any]],
    start_idx: int,
    y_tol: float,
    left_col_right: float,
    option_col_left: float,
    line_col_left: float,
    mode: str,
) -> Tuple[str, int]:
    # For placeholder rows or "blank" entry rows (drawn lines not captured),
    # join wrapped label text around the start band.
    if start_idx < 0 or start_idx >= len(bands):
        return ("", 1)

    def band_has_line_no(b: List[Any]) -> bool:
        return any(
            float(getattr(ln, "x0", 0.0)) >= line_col_left
            and _is_line_number_cell(str(getattr(ln, "text", "")) or "")
            for ln in b
        )

    def band_has_option(b: List[Any]) -> bool:
        return any(
            float(getattr(ln, "x0", 0.0)) >= option_col_left
            and _looks_like_option_text(str(getattr(ln, "text", "")) or "")
            for ln in b
        )

    def band_has_placeholder(b: List[Any]) -> bool:
        if _band_has_token_placeholders(b, left_col_right, option_col_left, line_col_left):
            return True
        for ln in b:
            x = float(getattr(ln, "x0", 0.0))
            if x >= line_col_left:
                continue
            if _looks_like_fillable_placeholder(str(getattr(ln, "text", "")) or ""):
                return True
        return False

    # Expand backward modestly if prior band looks like wrapped label text
    k0 = start_idx
    if start_idx - 1 >= 0:
        prev = bands[start_idx - 1]
        y_prev = float(getattr(prev[0], "y0", 0.0))
        y_cur = float(getattr(bands[start_idx][0], "y0", 0.0))
        if (y_cur - y_prev) <= 1.70 * y_tol and (not band_has_option(prev)) and (not band_has_placeholder(prev)) and (not band_has_line_no(prev)):
            prev_lbl = _extract_field_label_from_band(
                band=prev,
                left_col_right=left_col_right,
                option_col_left=option_col_left,
                line_col_left=line_col_left,
                allow_left=True,
                prefer_leftish=True,
            )
            if prev_lbl and len(prev_lbl) >= 8:
                k0 = start_idx - 1

    parts: List[str] = []
    consumed = 0
    k = k0
    while k < len(bands):
        b = bands[k]

        if k > k0 and band_has_line_no(b):
            break

        if k > k0:
            y_prev = float(getattr(bands[k - 1][0], "y0", 0.0))
            y_cur = float(getattr(b[0], "y0", 0.0))
            if (y_cur - y_prev) > 2.10 * y_tol:
                break

        # Stop conditions differ by mode
        if k > k0:
            if mode == "placeholder":
                # Once we leave the main band, stop at options or a new placeholder row
                if band_has_option(b) or band_has_placeholder(b):
                    break
            else:
                # For blank rows, stop at options/placeholder since it indicates a different row type
                if band_has_option(b) or band_has_placeholder(b):
                    break

        lbl = _extract_field_label_from_band(
            band=b,
            left_col_right=left_col_right,
            option_col_left=option_col_left,
            line_col_left=line_col_left,
            allow_left=True,
            prefer_leftish=True,
        )
        if lbl:
            parts.append(lbl)

        consumed += 1
        k += 1

    label = _clean(" ".join(parts))
    return (label, max(1, consumed))


def _looks_like_entry_row_label(
    label: str,
    band_lines: List[Any],
    x_min: float,
    x_max: float,
    option_col_left: float,
    line_col_left: float,
) -> bool:
    # Generic structural filters to avoid extracting long narrative paragraphs as blank entry fields.
    t = _clean(label)
    if not t:
        return False
    if len(t) < 5 or len(t) > 180:
        return False
    if _looks_like_machine_annotation(t):
        return False

    # If it is extremely long and has no question/colon punctuation, treat as narrative.
    if len(t) > 120 and (not any(ch in "?:;" for ch in t)):
        return False

    # Prefer "row label" structure: limited number of text chunks in the band.
    nonempty = [ln for ln in band_lines if _clean(str(getattr(ln, "text", "")) or "")]
    if len(nonempty) >= 6 and len(t) > 80:
        return False

    # Avoid labels that already reach into the option column area (typical of paragraph blocks).
    xs = [float(getattr(ln, "x0", 0.0)) for ln in nonempty]
    if xs:
        x_spread = max(xs) - min(xs)
        width = max(1.0, (x_max - x_min))
        if x_spread > 0.78 * width and len(t) > 80:
            return False

    # Also reject if band text already encroaches well past the option column boundary.
    max_x = 0.0
    for ln in nonempty:
        max_x = max(max_x, float(getattr(ln, "x0", 0.0)))
    if max_x >= min(line_col_left, option_col_left + 0.12 * max(1.0, (line_col_left - option_col_left))):
        if len(t) > 90 and (not t.endswith("?")):
            return False

    return True


def _extract_footer_colon_fields(
    lines: List[Any],
    y_tol: float,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    left_col_right: float,
    option_col_left: float,
    line_col_left: float,
    form_name: str,
    page_num: int,
    out: List[Dict[str, Any]],
    seen: set,
    emitted_meta: List[Dict[str, Any]],
) -> None:
    # Footer fields often render as "Label:" + a drawn line (no underscore text). Capture structurally.
    height = max(1.0, y_max - y_min)
    footer_top = y_max - 0.24 * height

    footer_lines = [ln for ln in lines if float(getattr(ln, "y0", 0.0)) >= footer_top - 1.2 * y_tol]
    if not footer_lines:
        return

    bands = _cluster_by_y(footer_lines, y_tol)
    for band in bands:
        if not band:
            continue
        yb = float(getattr(band[0], "y0", 0.0))
        if yb < footer_top - 1.5 * y_tol:
            continue

        if _band_looks_like_table_header(band, x_min, x_max, left_col_right, option_col_left, line_col_left):
            continue

        nonempty = [ln for ln in band if _clean(str(getattr(ln, "text", "")) or "")]
        if not nonempty:
            continue

        # Exclude if it's clearly a page footer marker.
        if any("page" in _clean(str(getattr(ln, "text", "")) or "").lower() for ln in nonempty):
            continue

        # Find left-column colon labels.
        colon_lbls = []
        for ln in nonempty:
            x = float(getattr(ln, "x0", 0.0))
            if x >= left_col_right:
                continue
            t = _clean(str(getattr(ln, "text", "")) or "")
            if not t.endswith(":"):
                continue
            base = _clean(t[:-1])
            if not base:
                continue
            if not any(ch.isalpha() for ch in base):
                continue
            if _looks_like_machine_annotation(base):
                continue
            colon_lbls.append(base)

        if not colon_lbls:
            continue

        # Structural check: there should not be other label-like text in the value columns
        # (often it's empty/drawn line). We still allow small tokens.
        value_text = []
        for ln in nonempty:
            x = float(getattr(ln, "x0", 0.0))
            if x < left_col_right or x >= line_col_left:
                continue
            t = _clean(str(getattr(ln, "text", "")) or "")
            if not t:
                continue
            if _is_line_number_cell(t):
                continue
            # Ignore tiny tokens
            if len(t) <= 2:
                continue
            value_text.append(t)

        if len(value_text) > 2:
            continue

        for lbl in colon_lbls:
            _emit_with_meta(
                form_name=form_name,
                field_name=lbl,
                page_num=page_num,
                band=band,
                x_min=x_min,
                x_max=x_max,
                y_min=y_min,
                y_max=y_max,
                out=out,
                seen=seen,
                emitted_meta=emitted_meta,
                evidence="footer_colon_field",
            )


def _extract_header_fields(
    header_lines: List[Any],
    y_tol: float,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    left_col_right: float,
    option_col_left: float,
    line_col_left: float,
    form_name: str,
    page_num: int,
    out: List[Dict[str, Any]],
    seen: set,
    emitted_meta: List[Dict[str, Any]],
) -> None:
    if not header_lines or not form_name:
        return

    bands = _cluster_by_y(header_lines, y_tol)
    for band in bands:
        if _band_looks_like_table_header(band, x_min, x_max, left_col_right, option_col_left, line_col_left):
            continue

        placeholders = []
        for ln in band:
            x = float(getattr(ln, "x0", 0.0))
            if x >= line_col_left:
                continue
            if x < left_col_right:
                continue
            t = str(getattr(ln, "text", "")) or ""
            if _looks_like_fillable_placeholder(t) or _looks_like_token_placeholder(t):
                placeholders.append(ln)

        if not placeholders and (not _band_has_token_placeholders(band, left_col_right, option_col_left, line_col_left)):
            continue

        label = _extract_field_label_from_band(
            band=band,
            left_col_right=left_col_right,
            option_col_left=option_col_left,
            line_col_left=line_col_left,
            allow_left=True,
            prefer_leftish=True,
        )
        if not label:
            continue

        _emit_with_meta(
            form_name=form_name,
            field_name=label,
            page_num=page_num,
            band=band,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            out=out,
            seen=seen,
            emitted_meta=emitted_meta,
            evidence="placeholder",
        )
```
