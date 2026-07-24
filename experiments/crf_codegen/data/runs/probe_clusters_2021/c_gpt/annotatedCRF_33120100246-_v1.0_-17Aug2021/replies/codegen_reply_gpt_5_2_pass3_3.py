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
    _CHOICE_ANCHOR_RE = re.compile(r"\(\s*\d+\s*\)")  # (1) ... (2) ...
    _CHOICE_ANCHOR2_RE = re.compile(r"\b\d+\s*\)")  # 1) 2) ...

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

    def looks_like_choice_list(ss: str) -> bool:
        s = norm(ss)
        if not s:
            return True
        # Dense rating/value anchor lines like "(1) ... (2) ... (3) ..."
        if _CHOICE_ANCHOR_RE.findall(s) and len(_CHOICE_ANCHOR_RE.findall(s)) >= 2:
            return True
        if len(_CHOICE_ANCHOR2_RE.findall(s)) >= 3 and len(s) >= 28:
            return True
        # Technical enumeration/value annotation lines (treat as non-label unconditionally)
        if re.search(r"\bvalues?\s*:", s, flags=re.I):
            return True
        if re.search(r"\benumerat(?:ion|e|ed)?\b", s, flags=re.I) and re.search(r"\bvalues?\b", s, flags=re.I):
            return True
        return False

    def looks_like_tech_annotation(s: str, ln: Any, med_sz: float) -> bool:
        ss = norm(s)
        if not ss:
            return False
        if is_meta_bracket(ss):
            return True

        # Unconditional: these are almost never human field labels.
        if _TECH_HINT_RE.search(ss):
            # "values:" especially should never become a field label.
            if re.search(r"\bvalues?\s*:", ss, re.I):
                return True
            # Otherwise, treat as tech annotation broadly (OCR varies in size/bold).
            return True

        # Bracket/garbage fragments near annotations
        if looks_like_choice_list(ss):
            return True
        return False

    def looks_like_bracket_artifact(ss: str) -> bool:
        s = norm(ss)
        if not s:
            return True
        # Reject unbalanced square brackets (often OCR tail like "Done)]")
        has_l = "[" in s
        has_r = "]" in s
        if has_l != has_r:
            # especially when the stray bracket is near the end
            if s.endswith("]") or s.endswith(")]") or s.endswith("].") or s.endswith(")]."):
                return True
        return False

    def looks_like_junk_label(s: str, ln: Any, med_sz: float) -> bool:
        ss = norm(s)
        if not ss:
            return True
        if is_bracket_line(ss):
            return True
        if looks_like_bracket_artifact(ss):
            return True
        if looks_like_choice_list(ss):
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

        # Remove common OCR tail garbage when there is no matching opener.
        if ("]" in ss) and ("[" not in ss):
            ss = re.sub(r"[\]\)]+$", "", ss).strip()
            ss = norm(ss)
        return ss

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

        x_back = max(18.0, 0.04 * page_w)
        x_fwd = max(44.0, 0.085 * page_w)  # allow more wrap indentation (numbered questions)
        y_gap = max(10.0, asz * 1.55, med_sz * 1.35)

        def compatible(i: int) -> bool:
            ln = lines[i]
            if not is_labelish(ln, med_sz):
                return False
            yy = y0(ln)
            if yy < y_min - 1e-3 or yy > y_max + 1e-3:
                return False
            dx = x0(ln) - ax
            if dx < -x_back or dx > x_fwd:
                return False
            if abs(size(ln) - asz) > max(2.0, asz * 0.34):
                return False
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
            if looks_like_choice_list(s) or looks_like_tech_annotation(s, ln, med_sz):
                continue
            score = (x0(ln) - cx_end) + abs(size(ln) - cs) * 4.0
            if best is None or score < best[0]:
                best = (score, s)
        return best[1] if best else ""

    def best_col_header_info(
        lines: List[Any],
        code_ln: Any,
        page_w: float,
        med_sz: float,
    ) -> Tuple[str, float, float]:
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
            if looks_like_choice_list(s) or looks_like_tech_annotation(s, ln, med_sz):
                continue
            dx = abs(cx(ln) - cxc)
            if dx > max(60.0, 0.11 * page_w):
                continue
            para_pen = 0.0
            if len(s) > 60:
                para_pen += 25.0
            big_pen = 0.0
            if size(ln) > med_sz * 1.35:
                big_pen += 18.0
            score = (cy - yy) + dx * 0.35 + para_pen + big_pen - size(ln) * 1.0
            if best is None or score < best[0]:
                best = (score, i)
        if best is None:
            return ("", 0.0, 0.0)
        _, idx = best
        wrapped = collect_wrapped_flexible(
            lines,
            idx,
            y_min=y0(lines[idx]) - 2.0,
            y_max=y0(lines[idx]) + 22.0,
            page_w=page_w,
            med_sz=med_sz,
        )
        txt = clean_field_name(wrapped or norm(t(lines[idx])))
        return (txt, y0(lines[idx]), size(lines[idx]))

    def best_col_header(lines: List[Any], code_ln: Any, page_w: float, med_sz: float) -> str:
        return best_col_header_info(lines, code_ln, page_w=page_w, med_sz=med_sz)[0]

    def best_row_label_left_of_row(
        lines: List[Any],
        row_y: float,
        min_x_code: float,
        page_w: float,
        med_sz: float,
    ) -> str:
        y_tol = max(9.0, 1.35 * med_sz)
        start_slack = max(8.0, 0.012 * page_w)

        best = None
        for i, ln in enumerate(lines):
            if not is_labelish(ln, med_sz):
                continue
            yy = y0(ln)
            if abs(yy - row_y) > y_tol:
                continue

            # Start must be meaningfully left of the code columns.
            if x0(ln) > (min_x_code - start_slack):
                continue

            s = norm(t(ln))
            if not s:
                continue
            if looks_like_choice_list(s) or looks_like_tech_annotation(s, ln, med_sz):
                continue

            bonus = 0.0
            if bool(getattr(ln, "bold", False)):
                bonus -= 10.0
            if "?" in s:
                bonus -= 8.0
            if _NUM_PREFIX_RE.match(s):
                bonus -= 6.0
            big_pen = 0.0
            if size(ln) > med_sz * 1.35:
                big_pen += 16.0

            # Prefer proximity from the left edge of the codes, but allow long text to overlap.
            overlap_pen = 0.0
            if x1(ln) > min_x_code + max(10.0, 0.02 * page_w):
                overlap_pen += (x1(ln) - min_x_code) * 0.03

            score = abs(yy - row_y) * 1.2 + (min_x_code - x0(ln)) * 0.02 + overlap_pen + big_pen - size(ln) * 0.6 + bonus
            if best is None or score < best[0]:
                best = (score, i)

        if best is None:
            return ""
        _, idx = best
        s = collect_wrapped_flexible(
            lines,
            idx,
            y_min=max(0.0, row_y - 3.4 * max(1.0, med_sz)),
            y_max=row_y + 3.4 * max(1.0, med_sz),
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
        max_up = max(240.0, 0.24 * page_h, 11.0 * med_sz)
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
            if current_form and norm(current_form).lower() == s.lower():
                continue
            if x0(ln) > 0.80 * page_w:
                continue
            if looks_like_choice_list(s) or looks_like_tech_annotation(s, ln, med_sz):
                continue

            dy = y_top - yy
            dx = abs(x0(ln) - min(x_ref, 0.55 * page_w))

            bonus = 0.0
            if bool(getattr(ln, "bold", False)):
                bonus -= 14.0
            if "?" in s:
                bonus -= 12.0
            if _NUM_PREFIX_RE.match(s):
                bonus -= 8.0
            if size(ln) > med_sz * 1.05:
                bonus -= 6.0

            instr_pen = 0.0
            if s.endswith(".") and "?" not in s and not bool(getattr(ln, "bold", False)):
                instr_pen += 14.0
            if len(s) > 170 and "?" not in s:
                instr_pen += 14.0

            big_pen = 0.0
            if size(ln) > med_sz * 1.35:
                big_pen += 22.0

            score = dy * 1.0 + dx * 0.08 + instr_pen + big_pen - size(ln) * 0.9 + bonus
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
        cy = y0(code_ln)
        cx0 = x0(code_ln)
        y_lo = cy - max(180.0, 9.5 * med_sz)
        y_hi = cy + max(75.0, 4.2 * med_sz)

        best = None
        for i, ln in enumerate(lines):
            if not is_labelish(ln, med_sz):
                continue
            s = norm(t(ln))
            if not s:
                continue
            if current_form and norm(current_form).lower() == s.lower():
                continue
            if looks_like_choice_list(s) or looks_like_tech_annotation(s, ln, med_sz):
                continue

            yy = y0(ln)
            if yy < y_lo or yy > y_hi:
                continue

            # Avoid choosing right-of-code same-row option text
            if abs(yy - cy) <= max(4.0, 0.6 * med_sz) and x0(ln) > x1(code_ln) + max(3.0, 0.6 * med_sz):
                continue

            if cx0 < 0.55 * page_w and x0(ln) > 0.74 * page_w:
                continue

            dy = yy - cy
            vy = abs(dy) * (0.9 if dy <= 0 else 2.1)
            vx = abs(cx(ln) - cx(code_ln)) * 0.30 + abs(x0(ln) - cx0) * 0.12

            bonus = 0.0
            if bool(getattr(ln, "bold", False)):
                bonus -= 9.0
            if "?" in s:
                bonus -= 8.0
            if _NUM_PREFIX_RE.match(s):
                bonus -= 6.0
            if len(s) > 150:
                bonus += 16.0

            big_pen = 0.0
            if size(ln) > med_sz * 1.35:
                big_pen += 18.0

            score = vy + vx + bonus + big_pen
            if best is None or score < best[0]:
                best = (score, i)

        if best is None:
            return ""

        _, idx = best
        y_max = cy - max(5.0, 0.35 * med_sz)
        y_min = max(0.0, cy - max(260.0, 13.5 * med_sz))
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

    def header_is_optionish(h: str) -> bool:
        hh = clean_field_name(h)
        if not hh:
            return False
        if looks_like_choice_list(hh):
            return True
        # short, low-content headers tend to be option anchors in grids
        words = [w for w in re.split(r"\s+", hh) if w]
        if len(hh) <= 16 and len(words) <= 2 and "?" not in hh:
            return True
        return False

    # ---------- main ----------
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

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

        # Precompute repeated header signatures to identify option-grids (e.g., Positive/Negative tables)
        sig_freq: Dict[Tuple[str, ...], int] = {}
        row_group_headers: Dict[int, Tuple[str, ...]] = {}
        for gi, g in enumerate(row_groups):
            if len(g) < 2:
                continue
            hdrs = []
            for _, code_ln in g:
                h = best_col_header(lines, code_ln, page_w=page_w, med_sz=med_sz)
                h = clean_field_name(h)
                if h and not looks_like_choice_list(h):
                    hdrs.append(h.lower())
                else:
                    hdrs.append("")
            sig = tuple(hdrs)
            nonempty = [h for h in sig if h]
            if len(nonempty) >= 2 and all(header_is_optionish(h) for h in nonempty):
                sig_freq[sig] = sig_freq.get(sig, 0) + 1
                row_group_headers[gi] = sig

        # ---- handle multi-code rows first ----
        for gi, g in enumerate(row_groups):
            if len(g) < 2:
                continue

            for idx, _ in g:
                consumed_code_idxs.add(idx)

            codes = [ln for _, ln in g]
            row_y = statistics.median([y0(ln) for ln in codes])
            min_x = min(x0(ln) for ln in codes)

            row_label = best_row_label_left_of_row(
                lines,
                row_y=row_y,
                min_x_code=min_x,
                page_w=page_w,
                med_sz=med_sz,
            )
            row_label = clean_field_name(row_label)

            right_texts = [right_neighbor_text(lines, ln, page_w=page_w, med_sz=med_sz) for ln in codes]
            has_right_option_text = any(bool(rt) for rt in right_texts)

            colhs = []
            for ln in codes:
                colh = best_col_header(lines, ln, page_w=page_w, med_sz=med_sz)
                colhs.append(clean_field_name(colh))

            nonempty_colhs = [c for c in colhs if c]
            long_headerish = any(len(c) >= 18 or (len(c.split()) >= 3) for c in nonempty_colhs)
            optionish_count = sum(1 for c in nonempty_colhs if header_is_optionish(c))
            repeated_sig = False
            sig = row_group_headers.get(gi)
            if sig is not None and sig_freq.get(sig, 0) >= 3:
                repeated_sig = True

            # Decide enumerated vs multi-field columns.
            enumerated_row = False
            if len(g) >= 3:
                enumerated_row = True
            elif has_right_option_text:
                enumerated_row = True
            elif repeated_sig and optionish_count >= 2:
                enumerated_row = True
            elif (not long_headerish) and optionish_count >= max(2, len(nonempty_colhs)):
                # Two-code grids (Yes/No, Positive/Negative, etc.) with short headers are usually a single field.
                enumerated_row = True

            if enumerated_row:
                field = row_label
                if not field:
                    field = best_question_label_above(
                        lines,
                        y_top=min(y0(ln) for ln in codes),
                        x_ref=min_x,
                        page_w=page_w,
                        page_h=page_h,
                        med_sz=med_sz,
                        current_form=current_form,
                    )
                    field = clean_field_name(field)

                if field and not looks_like_choice_list(field) and not looks_like_tech_annotation(field, lines[0], med_sz):
                    key = (current_form, field)
                    if key not in emitted:
                        emitted.add(key)
                        out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})
                continue

            # Multi-field columns: emit per column, but allow header-only when row_label is absent.
            for (_, code_ln), colh in zip(g, colhs):
                colh = clean_field_name(colh)
                if not colh and not row_label:
                    continue

                # Avoid duplicating when header collapses to the same as row label.
                if row_label and colh and row_label.lower() == colh.lower():
                    colh = ""

                if row_label and colh:
                    field = clean_field_name(f"{row_label} - {colh}")
                elif row_label:
                    field = row_label
                else:
                    # Only header visible: allow if it doesn't look like repeated option anchors.
                    if sig is not None and sig_freq.get(sig, 0) >= 3 and header_is_optionish(colh):
                        continue
                    field = colh

                if not field:
                    continue
                if looks_like_choice_list(field) or looks_like_tech_annotation(field, lines[0], med_sz):
                    continue

                key = (current_form, field)
                if key in emitted:
                    continue
                emitted.add(key)
                out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})

        # ---- single-code rows: option-lists vs standalone fields ----
        single_code_items = [(idx, ln) for idx, ln in code_items if idx not in consumed_code_idxs]

        opt_like_items = []
        for idx, ln in single_code_items:
            rt = right_neighbor_text(lines, ln, page_w=page_w, med_sz=med_sz)
            if rt:
                opt_like_items.append((idx, ln))

        x_tol = max(14.0, 0.05 * page_w)
        max_y_gap = max(26.0, 3.7 * med_sz)
        opt_clusters = split_vertical_clusters(opt_like_items, x_tol=x_tol, max_y_gap=max_y_gap)

        for cl in opt_clusters:
            if len(cl) < 2:
                continue
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

            if field and not looks_like_choice_list(field) and not looks_like_tech_annotation(field, lines[0], med_sz):
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

            if not label or looks_like_choice_list(label) or looks_like_tech_annotation(label, lines[0], med_sz):
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

            if not label:
                continue
            if looks_like_choice_list(label) or looks_like_tech_annotation(label, lines[0], med_sz):
                continue

            key = (current_form, label)
            if key in emitted:
                continue
            emitted.add(key)
            out.append({"form_name": current_form, "field_name": label, "page": page_idx0 + 1})

    return out
```
