```python
import re
import statistics
from typing import List, Tuple, Dict, Any, Optional


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    # ---------- small utils ----------
    _WS_RE = re.compile(r"\s+")
    _META_BRACKET_RE = re.compile(r"^\[(TYPE|VISIBIL|READ-ONLY|REQUIRED|DEFAULT|CALC)\b", re.I)
    _CODE_BRACKET_CLOSED_RE = re.compile(r"^\[[A-Za-z0-9][A-Za-z0-9_/-]{1,}\]$")
    _CODE_BRACKET_OPEN_RE = re.compile(r"^\[[^\[\]]{2,}$")  # "[SCANNE" style (truncated)
    _NUM_PREFIX_RE = re.compile(r"^\s*\d+\s*[\.\)]\s+")
    _TECH_HINT_RE = re.compile(
        r"\b(values?\s*:|enumerat(?:ion|e|ed)?|read-?only|required|visibility|calculated|calc|default)\b",
        re.I,
    )

    def f(v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except Exception:
            return float(default)

    def t(ln: Any) -> str:
        return (getattr(ln, "text", "") or "")

    def norm(s: str) -> str:
        return _WS_RE.sub(" ", (s or "").strip())

    def x0(ln: Any) -> float:
        return f(getattr(ln, "x0", 0.0))

    def x1(ln: Any) -> float:
        return f(getattr(ln, "x1", 0.0))

    def y0(ln: Any) -> float:
        return f(getattr(ln, "y0", 0.0))

    def y1(ln: Any) -> float:
        return f(getattr(ln, "y1", y0(ln)))

    def size(ln: Any) -> float:
        return f(getattr(ln, "size", 0.0))

    def cx(ln: Any) -> float:
        return (x0(ln) + x1(ln)) / 2.0

    def is_bracket_line(s: str) -> bool:
        return (s or "").lstrip().startswith("[")

    def is_meta_bracket(s: str) -> bool:
        return bool(_META_BRACKET_RE.match((s or "").lstrip()))

    def is_code_line(ln: Any) -> bool:
        s = norm(t(ln))
        if not s:
            return False
        if not is_bracket_line(s):
            return False
        if is_meta_bracket(s):
            return False

        if _CODE_BRACKET_CLOSED_RE.match(s):
            return True
        if _CODE_BRACKET_OPEN_RE.match(s):
            return True
        # short bracket token without ":" is usually a code even if clipped
        if len(s) <= 22 and ":" not in s:
            return True
        return False

    def looks_like_tech_annotation(s: str, ln: Any, med_sz: float) -> bool:
        ss = norm(s)
        if not ss:
            return False
        if is_meta_bracket(ss):
            return True
        # OCR may drop opening "["; catch typical technical fragments structurally.
        if _TECH_HINT_RE.search(ss):
            # Stronger when small-ish and not bold.
            smallish = size(ln) <= (med_sz * 1.05 + 0.4) if med_sz > 0 else True
            not_bold = not bool(getattr(ln, "bold", False))
            if smallish and not_bold:
                return True
            # If it contains "values:" it's almost never a human label.
            if re.search(r"\bvalues?\s*:", ss, re.I):
                return True
        # fragments that look like code-adjacent bracket garbage
        if ("]" in ss or "[" in ss) and _TECH_HINT_RE.search(ss):
            return True
        return False

    def looks_like_junk_label(s: str, ln: Any, med_sz: float) -> bool:
        ss = norm(s)
        if not ss:
            return True
        if is_bracket_line(ss):
            return True
        if re.fullmatch(r"[\d\W]+", ss):
            return True
        if re.fullmatch(r"Row\s*\d+\b.*", ss, flags=re.I):
            return True
        if looks_like_tech_annotation(ss, ln, med_sz):
            return True
        return False

    def is_labelish(ln: Any, med_sz: float) -> bool:
        ss = t(ln)
        if looks_like_junk_label(ss, ln, med_sz):
            return False
        return True

    def clean_field_name(s: str) -> str:
        ss = norm(s)
        ss = re.sub(r"\s*[:\-–]\s*$", "", ss).strip()
        ss = norm(ss)
        return ss

    # ---------- title detection ----------
    def pick_form_title(lines: List[Any], page_w: float, med_sz: float) -> Optional[str]:
        if not lines:
            return None
        sizes = [size(ln) for ln in lines if norm(t(ln))]
        if not sizes:
            return None
        mx = max(sizes)
        med = statistics.median(sizes)
        min_big = med + (mx - med) * 0.45

        # relative top-left envelope
        top_y = max(110.0, 0.18 * (max(y1(ln) for ln in lines) if lines else 600.0))
        left_x = max(140.0, 0.28 * page_w)

        cands = []
        for ln in lines:
            s = norm(t(ln))
            if not s or is_bracket_line(s):
                continue
            if y0(ln) > top_y:
                continue
            if x0(ln) > left_x:
                continue
            if size(ln) < min_big and size(ln) < (med + 2.0):
                continue
            style_bonus = 0.0
            if bool(getattr(ln, "non_black", False)):
                style_bonus -= 8.0
            if bool(getattr(ln, "bold", False)):
                style_bonus -= 3.0
            score = (y0(ln) * 1.0) + (x0(ln) * 0.12) - (size(ln) * 2.2) + style_bonus
            cands.append((score, s))
        if not cands:
            return None
        cands.sort(key=lambda z: z[0])
        return cands[0][1]

    # ---------- multiline collection (flexible indent) ----------
    def collect_wrapped_flexible(
        lines: List[Any],
        anchor_idx: int,
        y_min: float,
        y_max: float,
        page_w: float,
        med_sz: float,
    ) -> str:
        if anchor_idx < 0 or anchor_idx >= len(lines):
            return ""
        a = lines[anchor_idx]
        ax = x0(a)
        asz = size(a)
        abold = bool(getattr(a, "bold", False))

        # allow small indent changes (e.g., numbered question wraps)
        x_back = max(18.0, 0.04 * page_w)
        x_fwd = max(32.0, 0.065 * page_w)
        y_gap = max(10.0, asz * 1.55, med_sz * 1.35)

        def compatible(i: int) -> bool:
            ln = lines[i]
            if not is_labelish(ln, med_sz):
                return False
            yy = y0(ln)
            if yy < y_min - 1e-3 or yy > y_max + 1e-3:
                return False
            # column membership with indent tolerance
            dx = x0(ln) - ax
            if dx < -x_back or dx > x_fwd:
                return False
            # similar size (wrapped blocks tend to share size)
            if abs(size(ln) - asz) > max(1.8, asz * 0.32):
                return False
            # boldness usually matches; allow one-line mismatch close by
            if bool(getattr(ln, "bold", False)) != abold and abs(y0(ln) - y0(a)) > y_gap:
                return False
            return True

        idxs = [anchor_idx]

        # upward
        i = anchor_idx - 1
        last = y0(a)
        while i >= 0:
            ln = lines[i]
            if y0(ln) < y_min - 1e-3:
                break
            if not compatible(i):
                if is_bracket_line(norm(t(ln))):
                    break
                i -= 1
                continue
            if last - y0(ln) > y_gap * 1.7:
                break
            idxs.append(i)
            last = y0(ln)
            i -= 1

        # downward
        i = anchor_idx + 1
        last = y0(a)
        while i < len(lines):
            ln = lines[i]
            if y0(ln) > y_max + 1e-3:
                break
            if not compatible(i):
                if is_bracket_line(norm(t(ln))):
                    break
                i += 1
                continue
            if y0(ln) - last > y_gap * 1.7:
                break
            idxs.append(i)
            last = y0(ln)
            i += 1

        idxs = sorted(set(idxs))
        parts = [norm(t(lines[i])) for i in idxs if norm(t(lines[i]))]

        out = ""
        for p in parts:
            if not out:
                out = p
            else:
                if out.endswith("-"):
                    out = out[:-1] + p
                else:
                    out = out + " " + p
        return norm(out)

    # ---------- neighbors / headers ----------
    def right_neighbor_text(
        lines: List[Any],
        code_ln: Any,
        page_w: float,
        med_sz: float,
    ) -> str:
        cy = y0(code_ln)
        cx_end = x1(code_ln)
        cs = max(1.0, size(code_ln))
        y_tol = max(3.5, cs * 0.65, med_sz * 0.55)
        min_gap = max(4.0, cs * 0.2)
        max_gap = max(55.0, 0.12 * page_w)

        best = None
        for ln in lines:
            if not is_labelish(ln, med_sz):
                continue
            yy = y0(ln)
            if abs(yy - cy) > y_tol:
                continue
            if x0(ln) < cx_end + min_gap:
                continue
            if x0(ln) > cx_end + max_gap:
                continue
            s = norm(t(ln))
            if not s:
                continue
            # prefer closest x start, similar size
            score = (x0(ln) - cx_end) + abs(size(ln) - cs) * 4.0
            if best is None or score < best[0]:
                best = (score, s)
        return best[1] if best else ""

    def best_col_header(
        lines: List[Any],
        code_ln: Any,
        page_w: float,
        med_sz: float,
    ) -> str:
        cy = y0(code_ln)
        cxc = cx(code_ln)
        cs = max(1.0, size(code_ln))

        y_hi = cy - max(6.0, cs * 0.35)
        y_lo = cy - max(170.0, 8.5 * med_sz)

        best = None
        for i, ln in enumerate(lines):
            if not is_labelish(ln, med_sz):
                continue
            yy = y0(ln)
            if yy < y_lo or yy > y_hi:
                continue
            s = norm(t(ln))
            if not s:
                continue
            # align by center x, allow slack
            dx = abs(cx(ln) - cxc)
            if dx > max(60.0, 0.11 * page_w):
                continue
            # downweight long paragraphs as headers
            para_pen = 0.0
            if len(s) > 60:
                para_pen += 25.0
            score = (cy - yy) + dx * 0.35 + para_pen - size(ln) * 1.0
            if best is None or score < best[0]:
                best = (score, i)
        if best is None:
            return ""
        _, idx = best
        s = collect_wrapped_flexible(lines, idx, y_min=y0(lines[idx]) - 2.0, y_max=y0(lines[idx]) + 20.0, page_w=page_w, med_sz=med_sz)
        return clean_field_name(s or norm(t(lines[idx])))

    def best_row_label_left_of_row(
        lines: List[Any],
        row_y: float,
        x_limit: float,
        page_w: float,
        med_sz: float,
    ) -> str:
        y_tol = max(8.0, 1.25 * med_sz)
        best = None
        for i, ln in enumerate(lines):
            if not is_labelish(ln, med_sz):
                continue
            yy = y0(ln)
            if abs(yy - row_y) > y_tol:
                continue
            # must be meaningfully left of the codes
            if x1(ln) > x_limit + max(10.0, 0.02 * page_w):
                continue
            s = norm(t(ln))
            if not s:
                continue
            bonus = 0.0
            if bool(getattr(ln, "bold", False)):
                bonus -= 10.0
            if "?" in s:
                bonus -= 8.0
            if _NUM_PREFIX_RE.match(s):
                bonus -= 6.0
            # prefer the closest label to the codes from the left side
            score = abs(yy - row_y) * 1.2 + (x_limit - x1(ln)) * 0.08 - size(ln) * 0.6 + bonus
            if best is None or score < best[0]:
                best = (score, i)
        if best is None:
            return ""
        _, idx = best
        s = collect_wrapped_flexible(
            lines,
            idx,
            y_min=max(0.0, row_y - 3.2 * max(1.0, med_sz)),
            y_max=row_y + 3.2 * max(1.0, med_sz),
            page_w=page_w,
            med_sz=med_sz,
        )
        return clean_field_name(s or norm(t(lines[idx])))

    def best_question_label_above(
        lines: List[Any],
        y_top: float,
        x_ref: float,
        page_w: float,
        page_h: float,
        med_sz: float,
        current_form: str,
    ) -> str:
        # Search above y_top for a likely question/field label block.
        max_up = max(220.0, 0.22 * page_h, 10.0 * med_sz)
        y_lo = max(0.0, y_top - max_up)
        y_hi = y_top - max(6.0, 0.35 * med_sz)

        best = None
        for i, ln in enumerate(lines):
            if not is_labelish(ln, med_sz):
                continue
            yy = y0(ln)
            if yy < y_lo or yy > y_hi:
                continue
            s = norm(t(ln))
            if not s:
                continue
            # avoid snapping to the persistent form title
            if current_form and norm(current_form).lower() == s.lower():
                continue
            # generally labels live on left/middle, not far right
            if x0(ln) > 0.78 * page_w:
                continue

            dy = y_top - yy
            dx = abs(x0(ln) - min(x_ref, 0.55 * page_w))

            bonus = 0.0
            if bool(getattr(ln, "bold", False)):
                bonus -= 14.0
            if "?" in s:
                bonus -= 10.0
            if _NUM_PREFIX_RE.match(s):
                bonus -= 7.0
            if size(ln) > med_sz * 1.05:
                bonus -= 5.0

            # Penalize sentence-like instruction fragments (period, no question mark, not bold)
            instr_pen = 0.0
            if s.endswith(".") and "?" not in s and not bool(getattr(ln, "bold", False)):
                instr_pen += 10.0
            if len(s) > 160 and "?" not in s:
                instr_pen += 12.0

            score = dy * 1.0 + dx * 0.08 + instr_pen - size(ln) * 0.9 + bonus
            if best is None or score < best[0]:
                best = (score, i)

        if best is None:
            return ""
        _, idx = best
        s = collect_wrapped_flexible(
            lines,
            idx,
            y_min=y0(lines[idx]) - 2.0,
            y_max=y_hi,
            page_w=page_w,
            med_sz=med_sz,
        )
        return clean_field_name(s or norm(t(lines[idx])))

    def best_label_for_single_field_code(
        lines: List[Any],
        code_ln: Any,
        page_w: float,
        page_h: float,
        med_sz: float,
        current_form: str,
    ) -> str:
        # Prefer label above; explicitly avoid picking the right-side option text on the same row.
        cy = y0(code_ln)
        cx0 = x0(code_ln)
        y_lo = cy - max(170.0, 9.0 * med_sz)
        y_hi = cy + max(70.0, 4.0 * med_sz)

        best = None
        for i, ln in enumerate(lines):
            if not is_labelish(ln, med_sz):
                continue
            s = norm(t(ln))
            if not s:
                continue
            if current_form and norm(current_form).lower() == s.lower():
                continue

            yy = y0(ln)
            if yy < y_lo or yy > y_hi:
                continue

            # Avoid choosing right-of-code same-row option text
            if abs(yy - cy) <= max(4.0, 0.6 * med_sz) and x0(ln) > x1(code_ln) + max(3.0, 0.6 * med_sz):
                continue

            # Prefer left/middle region for labels
            if cx0 < 0.55 * page_w and x0(ln) > 0.72 * page_w:
                continue

            dy = yy - cy
            # prefer above; below is allowed but penalized
            vy = abs(dy) * (0.9 if dy <= 0 else 2.0)
            vx = abs(cx(ln) - cx(code_ln)) * 0.30 + abs(x0(ln) - cx0) * 0.12

            bonus = 0.0
            if bool(getattr(ln, "bold", False)):
                bonus -= 9.0
            if "?" in s:
                bonus -= 7.0
            if _NUM_PREFIX_RE.match(s):
                bonus -= 5.0
            if len(s) > 140:
                bonus += 14.0

            score = vy + vx + bonus
            if best is None or score < best[0]:
                best = (score, i)

        if best is None:
            return ""

        _, idx = best
        # wrap mostly above the code line
        y_max = cy - max(5.0, 0.35 * med_sz)
        y_min = max(0.0, cy - max(240.0, 13.0 * med_sz))
        s = collect_wrapped_flexible(lines, idx, y_min=y_min, y_max=y_max, page_w=page_w, med_sz=med_sz)
        return clean_field_name(s or norm(t(lines[idx])))

    # ---------- grouping ----------
    def group_codes_by_y(code_items: List[Tuple[int, Any]], y_tol: float) -> List[List[Tuple[int, Any]]]:
        if not code_items:
            return []
        code_items = sorted(code_items, key=lambda it: (y0(it[1]), x0(it[1])))
        groups: List[List[Tuple[int, Any]]] = []
        cur = [code_items[0]]
        last_y = y0(code_items[0][1])
        for it in code_items[1:]:
            yy = y0(it[1])
            if abs(yy - last_y) <= y_tol:
                cur.append(it)
            else:
                groups.append(cur)
                cur = [it]
            last_y = yy
        groups.append(cur)
        return groups

    def split_vertical_clusters(
        items: List[Tuple[int, Any]],
        x_tol: float,
        max_y_gap: float,
    ) -> List[List[Tuple[int, Any]]]:
        if not items:
            return []
        items = sorted(items, key=lambda it: (x0(it[1]), y0(it[1])))
        clusters: List[List[Tuple[int, Any]]] = []
        cur = [items[0]]
        cur_x = x0(items[0][1])
        last_y = y0(items[0][1])
        for it in items[1:]:
            xx = x0(it[1])
            yy = y0(it[1])
            if abs(xx - cur_x) <= x_tol and (yy - last_y) <= max_y_gap:
                cur.append(it)
            else:
                clusters.append(cur)
                cur = [it]
                cur_x = xx
            last_y = yy
        clusters.append(cur)
        return clusters

    # ---------- main ----------
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        # page scale
        page_w = max(10.0, max(x1(ln) for ln in lines))
        page_h = max(10.0, max(y1(ln) for ln in lines))
        font_sizes = [size(ln) for ln in lines if norm(t(ln))]
        med_sz = statistics.median(font_sizes) if font_sizes else 9.0

        title = pick_form_title(lines, page_w=page_w, med_sz=med_sz)
        if title:
            current_form = title

        code_items = [(i, ln) for i, ln in enumerate(lines) if is_code_line(ln)]
        if not code_items:
            continue

        emitted = set()  # (form, field) per page
        consumed_code_idxs = set()

        y_tol_row = max(7.5, 0.95 * med_sz)
        row_groups = group_codes_by_y(code_items, y_tol=y_tol_row)

        # ---- handle multi-code rows (matrices) first ----
        for g in row_groups:
            if len(g) < 2:
                continue

            # mark all as consumed from the "single-code" path
            for idx, _ in g:
                consumed_code_idxs.add(idx)

            codes = [ln for _, ln in g]
            row_y = statistics.median([y0(ln) for ln in codes])
            min_x = min(x0(ln) for ln in codes)
            x_limit = min_x - max(10.0, 0.02 * page_w)

            row_label = best_row_label_left_of_row(
                lines,
                row_y=row_y,
                x_limit=x_limit,
                page_w=page_w,
                med_sz=med_sz,
            )

            # detect enumerated-option rows: many columns OR explicit right-side option text
            right_texts = [right_neighbor_text(lines, ln, page_w=page_w, med_sz=med_sz) for ln in codes]
            has_right_option_text = any(bool(rt) for rt in right_texts)

            # if 3+ codes in a row, it's overwhelmingly likely a single enumerated field (avoid per-column fields)
            enumerated_row = (len(g) >= 3) or has_right_option_text

            if enumerated_row:
                field = clean_field_name(row_label)
                if not field:
                    # fall back to the best question label above the row band
                    field = best_question_label_above(
                        lines,
                        y_top=min(y0(ln) for ln in codes),
                        x_ref=min_x,
                        page_w=page_w,
                        page_h=page_h,
                        med_sz=med_sz,
                        current_form=current_form,
                    )
                if field and not looks_like_junk_label(field, lines[0], med_sz):
                    key = (current_form, field)
                    if key not in emitted:
                        emitted.add(key)
                        out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})
                continue

            # otherwise treat as multiple real columns (e.g., timeframes)
            if not row_label:
                row_label = best_question_label_above(
                    lines,
                    y_top=min(y0(ln) for ln in codes),
                    x_ref=min_x,
                    page_w=page_w,
                    page_h=page_h,
                    med_sz=med_sz,
                    current_form=current_form,
                )

            row_label = clean_field_name(row_label)
            if not row_label:
                continue

            for _, code_ln in g:
                colh = best_col_header(lines, code_ln, page_w=page_w, med_sz=med_sz)
                colh = clean_field_name(colh)
                if not colh:
                    # if no header, at least emit the row label once
                    colh = ""
                field = clean_field_name(f"{row_label} - {colh}" if colh else row_label)
                if not field:
                    continue
                if looks_like_junk_label(field, lines[0], med_sz):
                    continue
                key = (current_form, field)
                if key in emitted:
                    continue
                emitted.add(key)
                out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})

        # ---- single-code rows: option-lists vs standalone fields ----
        single_code_items = [(idx, ln) for idx, ln in code_items if idx not in consumed_code_idxs]

        # option-like single codes (have text immediately to the right)
        opt_like_items = []
        for idx, ln in single_code_items:
            rt = right_neighbor_text(lines, ln, page_w=page_w, med_sz=med_sz)
            if rt:
                opt_like_items.append((idx, ln))

        # vertical clusters of option-like codes
        x_tol = max(14.0, 0.05 * page_w)
        max_y_gap = max(26.0, 3.7 * med_sz)
        opt_clusters = split_vertical_clusters(opt_like_items, x_tol=x_tol, max_y_gap=max_y_gap)

        # mark codes that belong to option clusters and emit one field per cluster
        for cl in opt_clusters:
            if len(cl) < 2:
                continue
            # confirm it's really option-like (ratio of right-neighbor text)
            hits = 0
            for _, ln in cl:
                if right_neighbor_text(lines, ln, page_w=page_w, med_sz=med_sz):
                    hits += 1
            if hits / max(1, len(cl)) < 0.6:
                continue

            y_top = min(y0(ln) for _, ln in cl)
            x_ref = statistics.median([x0(ln) for _, ln in cl])

            field = best_question_label_above(
                lines,
                y_top=y_top,
                x_ref=x_ref,
                page_w=page_w,
                page_h=page_h,
                med_sz=med_sz,
                current_form=current_form,
            )

            field = clean_field_name(field)
            if field and not looks_like_junk_label(field, lines[0], med_sz):
                key = (current_form, field)
                if key not in emitted:
                    emitted.add(key)
                    out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})

            for idx, _ in cl:
                consumed_code_idxs.add(idx)

        # ---- remaining single codes: treat as standalone fields ----
        for idx, code_ln in single_code_items:
            if idx in consumed_code_idxs:
                continue

            label = best_label_for_single_field_code(
                lines,
                code_ln,
                page_w=page_w,
                page_h=page_h,
                med_sz=med_sz,
                current_form=current_form,
            )
            label = clean_field_name(label)
            if not label or looks_like_junk_label(label, lines[0], med_sz):
                # try a broader "question above" fallback (helps when label is not tightly aligned)
                label = best_question_label_above(
                    lines,
                    y_top=y0(code_ln),
                    x_ref=x0(code_ln),
                    page_w=page_w,
                    page_h=page_h,
                    med_sz=med_sz,
                    current_form=current_form,
                )
                label = clean_field_name(label)

            if not label or looks_like_junk_label(label, lines[0], med_sz):
                continue

            key = (current_form, label)
            if key in emitted:
                continue
            emitted.add(key)
            out.append({"form_name": current_form, "field_name": label, "page": page_idx0 + 1})

    return out
```
