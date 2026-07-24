```python
import re
import statistics
from typing import List, Tuple, Dict, Any, Optional


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    _WS_RE = re.compile(r"\s+")
    _META_BRACKET_RE = re.compile(r"^\[(TYPE|VISIBIL|READ-ONLY|REQUIRED|DEFAULT|CALC)\b", re.I)

    # Bracketed codes (checkbox/radio tokens rendered as [X], [Y/N], [___], etc.)
    _CODE_BRACKET_CLOSED_RE = re.compile(r"^\[\s*[A-Za-z0-9][A-Za-z0-9_/\-]{1,}\s*\]$")
    _CODE_BRACKET_OPEN_RE = re.compile(r"^\[\s*[^\[\]]{2,}$")  # truncated like "[SCANNE"

    _NUM_PREFIX_RE = re.compile(r"^\s*\d+\s*[\.\)]\s+")
    _CHOICE_ANCHOR_RE = re.compile(r"\(\s*\d+\s*\)")
    _CHOICE_ANCHOR2_RE = re.compile(r"\b\d+\s*\)")
    _CHOICE_SINGLE_ANCHOR_START_RE = re.compile(r"^\s*(\(\s*\d+\s*\)|\d+\s*\))\s+\S")

    # Generic technical annotation cues (not page-specific literals)
    _TECH_WORD_RE = re.compile(
        r"\b(values?\s*:|enumerat(?:ion|e|ed)?|read-?only|required|visibility|calculated|calc|default)\b",
        re.I,
    )

    _OPTION_TOKENS = {
        "yes",
        "no",
        "y",
        "n",
        "true",
        "false",
        "unknown",
        "na",
        "n/a",
        "none",
        "normal",
        "abnormal",
        "positive",
        "negative",
        "present",
        "absent",
        "done",
        "undone",
    }

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

    def tokenize(s: str) -> List[str]:
        s = norm(s).lower()
        if not s:
            return []
        s = re.sub(r"[^\w/]+", " ", s)
        return [w for w in s.split() if w]

    def option_token_stats(s: str) -> Tuple[int, int]:
        toks = tokenize(s)
        if not toks:
            return (0, 0)
        hits = sum(1 for w in toks if w in _OPTION_TOKENS)
        return (hits, len(toks))

    def looks_like_choice_list(ss: str) -> bool:
        s = norm(ss)
        if not s:
            return True

        hits, n = option_token_stats(s)
        if hits >= 3 and (hits / max(1, n)) >= 0.25:
            return True

        # Dense rating/value anchors like "(1) ... (2) ..." or "1) 2) 3)"
        if len(_CHOICE_ANCHOR_RE.findall(s)) >= 2:
            return True
        if len(_CHOICE_ANCHOR2_RE.findall(s)) >= 3 and len(s) >= 24:
            return True
        if _CHOICE_SINGLE_ANCHOR_START_RE.match(s):
            return True

        # Repeated short option runs anywhere, not only "short lines"
        if re.search(r"\b(yes|no|true|false|normal|abnormal|positive|negative)\b", s, re.I):
            if len(re.findall(r"\b(yes|no|true|false|normal|abnormal|positive|negative)\b", s, re.I)) >= 4:
                return True

        # Box/underline style placeholders often used as answer areas/options
        if re.search(r"_{3,}", s):
            return True

        # "Values:" / "Enumeration" style blocks are not labels
        if re.search(r"\bvalues?\s*:", s, flags=re.I):
            return True
        if re.search(r"\benumerat(?:ion|e|ed)?\b", s, flags=re.I) and re.search(r"\bvalues?\b", s, flags=re.I):
            return True

        return False

    def looks_like_bracket_artifact(ss: str) -> bool:
        s = norm(ss)
        if not s:
            return True
        has_l = "[" in s
        has_r = "]" in s
        if has_l != has_r:
            if s.endswith("]") or s.endswith(")]") or s.endswith("].") or s.endswith(")]."):
                return True
        return False

    def looks_like_tech_annotation(ss: str) -> bool:
        s = norm(ss)
        if not s:
            return False
        if is_meta_bracket(s):
            return True
        if _TECH_WORD_RE.search(s):
            return True
        return False

    def looks_like_sentence_instruction(ss: str, ln: Any, med_sz: float) -> bool:
        s = norm(ss)
        if not s:
            return False

        # Questions are usually labels
        if "?" in s:
            return False

        # Numeric leading bullets/steps are usually instructions, not field labels
        if _NUM_PREFIX_RE.match(s):
            return True

        # Long multi-sentence prose is usually instruction/furniture
        periods = s.count(".")
        if periods >= 2 and not bool(getattr(ln, "bold", False)) and size(ln) <= med_sz * 1.12:
            return True

        # Sentence-like endings with small/normal font
        if s.endswith(".") and not bool(getattr(ln, "bold", False)) and size(ln) <= med_sz * 1.12:
            words = [w for w in re.split(r"\s+", s) if w]
            if len(words) >= 6:
                return True
            if len(s) >= 55:
                return True

        # Colon in the middle is more often an annotation than a label; allow trailing ":" (e.g., "Other, specify:")
        if ":" in s and not s.rstrip().endswith(":"):
            if len(s) >= 28 and not bool(getattr(ln, "bold", False)) and size(ln) <= med_sz * 1.12:
                return True

        return False

    def clean_field_name(s: str) -> str:
        ss = norm(s)
        ss = re.sub(r"\s*[:\-–]\s*$", "", ss).strip()
        ss = norm(ss)

        # Trim dangling unmatched close brackets at end
        if ("]" in ss) and ("[" not in ss):
            ss = re.sub(r"[\]\)]+$", "", ss).strip()
            ss = norm(ss)

        # Trim leading punctuation fragments
        ss = re.sub(r"^[,;]\s*", "", ss).strip()
        ss = norm(ss)

        # Reject short "code-ish" prefixes like "Y: site", "A: ..." (generic heuristic)
        if re.match(r"^[A-Z]{1,2}\s*:\s*\w", ss) and len(ss) <= 16:
            return ""

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
        if len(s) <= 28 and ":" not in s:
            return True
        # token-ish bracket lines, OCR spaces allowed
        if s.startswith("[") and ":" not in s:
            inner = re.sub(r"[\[\]\s]+", "", s)
            if re.fullmatch(r"[A-Za-z0-9_/\-]{2,}", inner or ""):
                return True
        return False

    def collect_wrapped_flexible(
        lines: List[Any],
        anchor_idx: int,
        y_min: float,
        y_max: float,
        page_w: float,
        med_sz: float,
        header_footer_texts: Optional[set] = None,
    ) -> str:
        if anchor_idx < 0 or anchor_idx >= len(lines):
            return ""
        a = lines[anchor_idx]
        ax = x0(a)
        asz = size(a)
        abold = bool(getattr(a, "bold", False))
        atext = norm(t(a))

        x_back = max(18.0, 0.04 * page_w)
        x_fwd = max(70.0, 0.14 * page_w)
        if _NUM_PREFIX_RE.match(atext) or ("?" in atext):
            x_fwd = max(x_fwd, 0.22 * page_w)

        y_gap = max(10.0, asz * 1.55, med_sz * 1.35)

        def accept_line(i: int) -> bool:
            ln = lines[i]
            s = norm(t(ln))
            if not s:
                return False
            if header_footer_texts is not None and s.lower() in header_footer_texts:
                return False
            if is_bracket_line(s) or looks_like_bracket_artifact(s):
                return False
            if looks_like_choice_list(s) or looks_like_tech_annotation(s):
                return False
            if looks_like_sentence_instruction(s, ln, med_sz):
                return False

            yy = y0(ln)
            if yy < y_min - 1e-3 or yy > y_max + 1e-3:
                return False

            dx = x0(ln) - ax
            if dx < -x_back:
                return False
            if dx > x_fwd:
                # allow deeper indent only when it still looks like continuation (not a new column)
                if dx > max(x_fwd, 0.30 * page_w):
                    return False

            if abs(size(ln) - asz) > max(2.0, asz * 0.34):
                return False

            if bool(getattr(ln, "bold", False)) != abold and abs(y0(ln) - y0(a)) > y_gap:
                return False

            return True

        idxs = [anchor_idx]

        # upward
        i = anchor_idx - 1
        last_y = y0(a)
        while i >= 0:
            ln = lines[i]
            if y0(ln) < y_min - 1e-3:
                break
            if not accept_line(i):
                if is_bracket_line(norm(t(ln))):
                    break
                i -= 1
                continue
            if last_y - y0(ln) > y_gap * 1.7:
                break
            idxs.append(i)
            last_y = y0(ln)
            i -= 1

        # downward
        i = anchor_idx + 1
        last_y = y0(a)
        while i < len(lines):
            ln = lines[i]
            if y0(ln) > y_max + 1e-3:
                break
            if not accept_line(i):
                if is_bracket_line(norm(t(ln))):
                    break
                i += 1
                continue
            if y0(ln) - last_y > y_gap * 1.7:
                break
            idxs.append(i)
            last_y = y0(ln)
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

    def right_neighbor_text(
        lines: List[Any],
        code_ln: Any,
        page_w: float,
        med_sz: float,
        header_footer_texts: set,
    ) -> str:
        cy = y0(code_ln)
        cx_end = x1(code_ln)
        cs = max(1.0, size(code_ln))
        y_tol = max(3.5, cs * 0.65, med_sz * 0.55)
        min_gap = max(3.0, cs * 0.15)
        max_gap = max(70.0, 0.16 * page_w)

        best = None
        for ln in lines:
            s = norm(t(ln))
            if not s:
                continue
            if s.lower() in header_footer_texts:
                continue
            yy = y0(ln)
            if abs(yy - cy) > y_tol:
                continue
            if x0(ln) < cx_end + min_gap:
                continue
            if x0(ln) > cx_end + max_gap:
                continue
            if is_bracket_line(s) or looks_like_bracket_artifact(s):
                continue
            if looks_like_choice_list(s) or looks_like_tech_annotation(s):
                continue
            if looks_like_sentence_instruction(s, ln, med_sz):
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
        header_footer_texts: set,
    ) -> Tuple[str, float, float]:
        cy = y0(code_ln)
        cxc = cx(code_ln)
        cs = max(1.0, size(code_ln))

        y_hi = cy - max(6.0, cs * 0.35)
        y_lo = cy - max(185.0, 9.5 * med_sz)

        best = None
        for i, ln in enumerate(lines):
            s = norm(t(ln))
            if not s:
                continue
            if s.lower() in header_footer_texts:
                continue
            yy = y0(ln)
            if yy < y_lo or yy > y_hi:
                continue
            if is_bracket_line(s) or looks_like_bracket_artifact(s):
                continue
            if looks_like_choice_list(s) or looks_like_tech_annotation(s):
                continue
            if looks_like_sentence_instruction(s, ln, med_sz):
                continue
            dx = abs(cx(ln) - cxc)
            if dx > max(70.0, 0.13 * page_w):
                continue

            para_pen = 0.0
            if len(s) > 70:
                para_pen += 30.0
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
            y_max=y0(lines[idx]) + 24.0,
            page_w=page_w,
            med_sz=med_sz,
            header_footer_texts=header_footer_texts,
        )
        txt = clean_field_name(wrapped or norm(t(lines[idx])))
        return (txt, y0(lines[idx]), size(lines[idx]))

    def header_is_optionish(h: str) -> bool:
        hh = clean_field_name(h)
        if not hh:
            return False
        if looks_like_choice_list(hh) or looks_like_tech_annotation(hh):
            return True
        toks = tokenize(hh)
        if not toks:
            return False
        # single-word option headers (Yes/No/True/False/etc.)
        if len(toks) == 1 and toks[0] in _OPTION_TOKENS:
            return True
        # pure numeric/range-like headers are usually anchors
        if re.fullmatch(r"[\(\)\d\-\s/]+", hh):
            return True
        return False

    def best_row_label_left_of_row(
        lines: List[Any],
        row_y: float,
        min_x_code: float,
        page_w: float,
        med_sz: float,
        header_footer_texts: set,
    ) -> str:
        y_tol = max(10.0, 1.45 * med_sz)
        start_slack = max(10.0, 0.014 * page_w)

        best = None
        for i, ln in enumerate(lines):
            s = norm(t(ln))
            if not s:
                continue
            if s.lower() in header_footer_texts:
                continue
            yy = y0(ln)
            if abs(yy - row_y) > y_tol:
                continue
            if x0(ln) > (min_x_code - start_slack):
                continue
            if is_bracket_line(s) or looks_like_bracket_artifact(s):
                continue
            if looks_like_choice_list(s) or looks_like_tech_annotation(s):
                continue
            if looks_like_sentence_instruction(s, ln, med_sz):
                continue

            bonus = 0.0
            if bool(getattr(ln, "bold", False)):
                bonus -= 10.0
            if "?" in s:
                bonus -= 9.0
            if _NUM_PREFIX_RE.match(s):
                bonus -= 7.0

            big_pen = 0.0
            if size(ln) > med_sz * 1.35:
                big_pen += 16.0

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
            y_min=max(0.0, row_y - 3.6 * max(1.0, med_sz)),
            y_max=row_y + 3.6 * max(1.0, med_sz),
            page_w=page_w,
            med_sz=med_sz,
            header_footer_texts=header_footer_texts,
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
        header_footer_texts: set,
    ) -> str:
        max_up = max(280.0, 0.28 * page_h, 12.5 * med_sz)
        y_lo = max(0.0, y_top - max_up)
        y_hi = y_top - max(6.0, 0.35 * med_sz)

        best = None
        for i, ln in enumerate(lines):
            s = norm(t(ln))
            if not s:
                continue
            if s.lower() in header_footer_texts:
                continue
            yy = y0(ln)
            if yy < y_lo or yy > y_hi:
                continue

            if current_form and norm(current_form).lower() == s.lower():
                continue
            if x0(ln) > 0.82 * page_w:
                continue

            if is_bracket_line(s) or looks_like_bracket_artifact(s):
                continue
            if looks_like_choice_list(s) or looks_like_tech_annotation(s):
                continue

            # Avoid picking long prose instruction fragments as "question label"
            instr_pen = 0.0
            if looks_like_sentence_instruction(s, ln, med_sz):
                instr_pen += 55.0
            if len(s) > 160 and "?" not in s:
                instr_pen += 20.0

            dy = y_top - yy
            dx = abs(x0(ln) - min(x_ref, 0.55 * page_w))

            bonus = 0.0
            if bool(getattr(ln, "bold", False)):
                bonus -= 15.0
            if "?" in s:
                bonus -= 13.0
            if _NUM_PREFIX_RE.match(s):
                bonus -= 9.0
            if size(ln) > med_sz * 1.05:
                bonus -= 6.0

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
            header_footer_texts=header_footer_texts,
        )
        return clean_field_name(s or norm(t(lines[idx])))

    def pick_form_title(lines: List[Any], page_w: float, med_sz: float, header_footer_texts: set) -> Optional[str]:
        if not lines:
            return None
        sizes = [size(ln) for ln in lines if norm(t(ln))]
        if not sizes:
            return None
        mx = max(sizes)
        med = statistics.median(sizes)
        min_big = med + (mx - med) * 0.45

        page_h = max(10.0, max(y1(ln) for ln in lines))
        top_y = max(110.0, 0.18 * page_h)
        left_x = max(140.0, 0.28 * page_w)

        cands = []
        for ln in lines:
            s = norm(t(ln))
            if not s:
                continue
            if s.lower() in header_footer_texts:
                continue
            if is_bracket_line(s) or looks_like_bracket_artifact(s):
                continue
            if y0(ln) > top_y:
                continue
            if x0(ln) > left_x:
                continue
            if size(ln) < min_big and size(ln) < (med + 2.0):
                continue
            if looks_like_choice_list(s) or looks_like_tech_annotation(s):
                continue
            if looks_like_sentence_instruction(s, ln, med_sz):
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

    def split_vertical_clusters(items: List[Tuple[int, Any]], x_tol: float, max_y_gap: float) -> List[List[Tuple[int, Any]]]:
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

    # ---- Prepass: discover repeated header/footer "template markers" from the document itself (not hardcoded) ----
    header_footer_freq: Dict[str, int] = {}
    per_page_geom: Dict[int, Tuple[float, float, float]] = {}  # page_idx0 -> (page_w, page_h, med_sz)
    for page_idx0, lines in pages:
        if not lines:
            continue
        page_w = max(10.0, max(x1(ln) for ln in lines))
        page_h = max(10.0, max(y1(ln) for ln in lines))
        font_sizes = [size(ln) for ln in lines if norm(t(ln))]
        med_sz = statistics.median(font_sizes) if font_sizes else 9.0
        per_page_geom[page_idx0] = (page_w, page_h, med_sz)

        top_band = 0.085 * page_h
        bot_band = 0.915 * page_h

        for ln in lines:
            s = norm(t(ln))
            if not s:
                continue
            if is_bracket_line(s) or looks_like_bracket_artifact(s):
                continue
            yy = y0(ln)
            if yy <= top_band or yy >= bot_band:
                # bias toward smaller header/footer text
                if size(ln) <= med_sz * 1.08 or bool(getattr(ln, "non_black", False)):
                    header_footer_freq[s.lower()] = header_footer_freq.get(s.lower(), 0) + 1

    repeated_header_footer = {k for (k, v) in header_footer_freq.items() if v >= 3 and len(k) >= 4}

    # ---- Main extraction ----
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        page_w, page_h, med_sz = per_page_geom.get(page_idx0, (0.0, 0.0, 9.0))
        if page_w <= 0.0:
            page_w = max(10.0, max(x1(ln) for ln in lines))
        if page_h <= 0.0:
            page_h = max(10.0, max(y1(ln) for ln in lines))

        title = pick_form_title(lines, page_w=page_w, med_sz=med_sz, header_footer_texts=repeated_header_footer)
        if title:
            current_form = title

        code_items = [(i, ln) for i, ln in enumerate(lines) if is_code_line(ln)]
        if not code_items:
            continue

        emitted = set()  # (form, field) per page
        consumed_code_idxs = set()

        y_tol_row = max(8.5, 1.15 * med_sz)
        row_groups = group_codes_by_y(code_items, y_tol=y_tol_row)

        # Identify repeated option-grid signatures (structural: recurring optionish headers)
        sig_freq: Dict[Tuple[str, ...], int] = {}
        row_group_headers: Dict[int, Tuple[str, ...]] = {}
        for gi, g in enumerate(row_groups):
            if len(g) < 2:
                continue
            hdrs = []
            for _, code_ln in g:
                h, _, _ = best_col_header_info(lines, code_ln, page_w=page_w, med_sz=med_sz, header_footer_texts=repeated_header_footer)
                h = clean_field_name(h)
                hdrs.append((h or "").lower())
            sig = tuple(hdrs)
            nonempty = [h for h in sig if h]
            if len(nonempty) >= 2 and all(header_is_optionish(h) for h in nonempty):
                sig_freq[sig] = sig_freq.get(sig, 0) + 1
                row_group_headers[gi] = sig

        # ---- multi-code rows ----
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
                header_footer_texts=repeated_header_footer,
            )
            row_label = clean_field_name(row_label)

            right_texts = [right_neighbor_text(lines, ln, page_w=page_w, med_sz=med_sz, header_footer_texts=repeated_header_footer) for ln in codes]
            has_right_option_text = any(bool(rt) for rt in right_texts)

            colhs = []
            for ln in codes:
                ch, _, _ = best_col_header_info(lines, ln, page_w=page_w, med_sz=med_sz, header_footer_texts=repeated_header_footer)
                colhs.append(clean_field_name(ch))

            nonempty_colhs = [c for c in colhs if c]
            long_headerish = any(len(c) >= 22 or (len(c.split()) >= 4) for c in nonempty_colhs)
            optionish_count = sum(1 for c in nonempty_colhs if header_is_optionish(c))
            sig = row_group_headers.get(gi)
            repeated_sig = bool(sig is not None and sig_freq.get(sig, 0) >= 3)

            enumerated_row = False
            if len(g) >= 3:
                enumerated_row = True
            elif has_right_option_text:
                enumerated_row = True
            elif repeated_sig and optionish_count >= 2:
                enumerated_row = True
            elif (not long_headerish) and optionish_count >= max(2, len(nonempty_colhs)):
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
                        header_footer_texts=repeated_header_footer,
                    )
                    field = clean_field_name(field)

                if field and not looks_like_choice_list(field) and not looks_like_tech_annotation(field) and not header_is_optionish(field):
                    key = (current_form, field)
                    if key not in emitted:
                        emitted.add(key)
                        out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})
                continue

            # multi-field columns
            for (_, _code_ln), colh in zip(g, colhs):
                colh = clean_field_name(colh)
                if not colh and not row_label:
                    continue

                if row_label and colh and row_label.lower() == colh.lower():
                    colh = ""

                if row_label and colh:
                    field = clean_field_name(f"{row_label} - {colh}")
                elif row_label:
                    field = row_label
                else:
                    if header_is_optionish(colh):
                        continue
                    field = colh

                if not field:
                    continue
                if looks_like_choice_list(field) or looks_like_tech_annotation(field) or header_is_optionish(field):
                    continue

                key = (current_form, field)
                if key in emitted:
                    continue
                emitted.add(key)
                out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})

        # ---- single-code rows ----
        single_code_items = [(idx, ln) for idx, ln in code_items if idx not in consumed_code_idxs]

        # A) option-style clusters (codes with text directly to right)
        opt_like_items = []
        for idx, ln in single_code_items:
            rt = right_neighbor_text(lines, ln, page_w=page_w, med_sz=med_sz, header_footer_texts=repeated_header_footer)
            if rt:
                opt_like_items.append((idx, ln))

        x_tol = max(16.0, 0.055 * page_w)
        max_y_gap = max(28.0, 4.1 * med_sz)
        opt_clusters = split_vertical_clusters(opt_like_items, x_tol=x_tol, max_y_gap=max_y_gap)

        for cl in opt_clusters:
            if len(cl) < 2:
                continue

            hits = 0
            for _, ln in cl:
                if right_neighbor_text(lines, ln, page_w=page_w, med_sz=med_sz, header_footer_texts=repeated_header_footer):
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
                header_footer_texts=repeated_header_footer,
            )
            field = clean_field_name(field)

            if field and not looks_like_choice_list(field) and not looks_like_tech_annotation(field) and not header_is_optionish(field):
                key = (current_form, field)
                if key not in emitted:
                    emitted.add(key)
                    out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})

            for idx, _ in cl:
                consumed_code_idxs.add(idx)

        # B) rating/anchor columns: vertical clusters of codes without right-neighbor labels
        remaining_single = [(idx, ln) for idx, ln in single_code_items if idx not in consumed_code_idxs]
        if remaining_single:
            col_clusters = split_vertical_clusters(
                remaining_single,
                x_tol=max(18.0, 0.06 * page_w),
                max_y_gap=max(34.0, 4.8 * med_sz),
            )
            for cl in col_clusters:
                if len(cl) < 3:
                    continue

                rn_hits = 0
                for _, ln in cl:
                    if right_neighbor_text(lines, ln, page_w=page_w, med_sz=med_sz, header_footer_texts=repeated_header_footer):
                        rn_hits += 1
                if rn_hits / max(1, len(cl)) >= 0.45:
                    continue

                cl_sorted = sorted(cl, key=lambda it: y0(it[1]))
                _top_idx, top_ln = cl_sorted[0]

                hdr, _, _ = best_col_header_info(lines, top_ln, page_w=page_w, med_sz=med_sz, header_footer_texts=repeated_header_footer)
                hdr = clean_field_name(hdr)

                if (not hdr) or looks_like_choice_list(hdr) or looks_like_tech_annotation(hdr) or header_is_optionish(hdr):
                    hdr2 = best_question_label_above(
                        lines,
                        y_top=y0(top_ln),
                        x_ref=x0(top_ln),
                        page_w=page_w,
                        page_h=page_h,
                        med_sz=med_sz,
                        current_form=current_form,
                        header_footer_texts=repeated_header_footer,
                    )
                    hdr2 = clean_field_name(hdr2)
                    if hdr2 and not looks_like_choice_list(hdr2) and not looks_like_tech_annotation(hdr2) and not header_is_optionish(hdr2):
                        hdr = hdr2

                if hdr and not looks_like_choice_list(hdr) and not looks_like_tech_annotation(hdr) and not header_is_optionish(hdr):
                    key = (current_form, hdr)
                    if key not in emitted:
                        emitted.add(key)
                        out.append({"form_name": current_form, "field_name": hdr, "page": page_idx0 + 1})
                    for idx, _ in cl:
                        consumed_code_idxs.add(idx)

        # ---- remaining single codes: standalone fields ----
        for idx, code_ln in single_code_items:
            if idx in consumed_code_idxs:
                continue

            # Prefer right-neighbor label for standalone checkbox
            label = right_neighbor_text(lines, code_ln, page_w=page_w, med_sz=med_sz, header_footer_texts=repeated_header_footer)
            label = clean_field_name(label)

            if not label:
                label = best_question_label_above(
                    lines,
                    y_top=y0(code_ln),
                    x_ref=x0(code_ln),
                    page_w=page_w,
                    page_h=page_h,
                    med_sz=med_sz,
                    current_form=current_form,
                    header_footer_texts=repeated_header_footer,
                )
                label = clean_field_name(label)

            if not label:
                continue
            if looks_like_choice_list(label) or looks_like_tech_annotation(label) or header_is_optionish(label):
                continue

            key = (current_form, label)
            if key in emitted:
                continue
            emitted.add(key)
            out.append({"form_name": current_form, "field_name": label, "page": page_idx0 + 1})

    return out
```
