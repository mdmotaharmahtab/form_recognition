```python
import re
import statistics
import unicodedata
from typing import List, Tuple, Dict, Optional, Iterable, Callable


_CODE_RE = re.compile(r"^\[(?=[A-Za-z0-9]{2,}\]$)(?=.*[A-Za-z])[A-Za-z0-9]+\]$")
_PAGE_RE = re.compile(r"^Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)
_ENUM_OPT_RE = re.compile(r"^\d+\s*[\.\)]\s*")
_LEADING_ENUM_RE = re.compile(r"^(?:\\\s*)?\d{1,3}\s*[\.\)]\s*")


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    seen = set()
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        page_w = max((getattr(ln, "x1", 0.0) for ln in lines), default=800.0) or 800.0
        sizes = [ln.size for ln in lines if getattr(ln, "size", 0) and getattr(ln, "text", "")]
        med_size = statistics.median(sizes) if sizes else 9.0

        option_like_idx = _compute_option_like_lines(lines, page_w)
        option_stack_idx = _compute_option_stack_lines(lines, page_w, med_size)
        rating_header_rows = _detect_rating_header_rows(lines, page_w, med_size)
        table_header_idx = _detect_table_header_token_indices(lines, page_w, med_size)

        title = _detect_form_title(lines, med_size, page_w)
        if title:
            current_form = title

        col_headers = _build_column_headers(
            lines,
            page_w=page_w,
            med_size=med_size,
            option_like_idx=option_like_idx,
            option_stack_idx=option_stack_idx,
            rating_header_rows=rating_header_rows,
        )

        code_indices = [i for i, ln in enumerate(lines) if _is_field_code_line(ln)]

        # Pages with fields but no bracket codes in extracted text
        if not code_indices:
            labels = _extract_fields_when_no_codes(
                lines,
                page_w=page_w,
                med_size=med_size,
                option_stack_idx=option_stack_idx,
                col_headers=col_headers,
                table_header_idx=table_header_idx,
            )
            for label in labels:
                label = _clean_label(label)
                if not label:
                    continue
                rec = {"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1}
                key = (rec["page"], rec["form_name"], rec["field_name"])
                if key in seen:
                    continue
                seen.add(key)
                out.append(rec)
            continue

        # Detect dictionary/legend-like code columns (option mappings), so we can avoid emitting those "labels"
        dict_like_codes = _detect_dictionary_like_code_indices(lines, code_indices, page_w, option_stack_idx, table_header_idx)

        for ci in code_indices:
            if ci in dict_like_codes:
                continue

            code_ln = lines[ci]
            if _is_readonly_marked(ci, lines):
                continue

            label = _find_label_for_code(
                ci,
                lines=lines,
                option_like_idx=option_like_idx,
                option_stack_idx=option_stack_idx,
                table_header_idx=table_header_idx,
                page_w=page_w,
                med_size=med_size,
            )
            if not label:
                continue

            label = _clean_label(label)
            if not label:
                continue

            # Append column header when it is truly descriptive and helps disambiguate table cells.
            if code_ln.x0 > 0.28 * page_w:
                hdr = _closest_col_header(col_headers, code_ln.x0)
                hdr = _clean_label(hdr)
                if hdr and _is_descriptive_header(hdr) and hdr.lower() not in label.lower():
                    label = _clean_label(label + " " + hdr)

            rec = {"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1}
            key = (rec["page"], rec["form_name"], rec["field_name"])
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)

    return out


def _is_field_code_line(ln) -> bool:
    t = (getattr(ln, "text", "") or "").strip()
    return bool(t) and bool(_CODE_RE.match(t))


def _has_letter(s: str) -> bool:
    for ch in s:
        if unicodedata.category(ch).startswith("L"):
            return True
    return False


def _looks_like_furniture(ln) -> bool:
    t = (getattr(ln, "text", "") or "").strip()
    if not t:
        return True
    if _PAGE_RE.match(t):
        return True
    return False


def _is_technical_marker(ln) -> bool:
    t = (getattr(ln, "text", "") or "").strip()
    if not t:
        return True
    if _PAGE_RE.match(t):
        return True
    if t.startswith("[") and ":" in t[:20]:
        return True
    if t.startswith("(") and ":" in t[:30]:
        return True
    return False


def _looks_like_instruction_text(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    if t.endswith(":") or t.endswith("?"):
        return False
    # Long narrative sentences are much more likely instructions than labels.
    if len(t) >= 120 and (("." in t) or (";" in t) or ("," in t)):
        return True
    # Very long lines without terminal punctuation are still likely narrative/instructions.
    if len(t) >= 170:
        return True
    return False


def _detect_form_title(lines, med_size: float, page_w: float) -> str:
    candidates = []
    for ln in lines:
        t = (getattr(ln, "text", "") or "").strip()
        if not t:
            continue
        if _looks_like_furniture(ln):
            continue
        if t.startswith("["):
            continue

        # Keep titles near the top; avoid mid-page prompts
        if ln.y0 > 240:
            continue

        # Left-ish
        if ln.x0 > max(220.0, 0.34 * page_w):
            continue

        # Must stand out vs body
        if ln.size < max(14.5, med_size + 4.4):
            continue

        if not getattr(ln, "non_black", False):
            continue

        # Avoid prompt-like / per-field strings
        if t.endswith(":") or t.endswith("?"):
            continue
        if _LEADING_ENUM_RE.match(t):
            continue
        if _looks_like_instruction_text(t):
            continue

        # Basic sanity
        if len(t) > 115:
            continue
        if not _has_letter(t):
            continue

        candidates.append(ln)

    if not candidates:
        return ""

    def score_title(ln) -> float:
        t = (ln.text or "").strip()
        sc = 0.0
        sc += 3.2 * ln.size
        sc += 1.0 if getattr(ln, "non_black", False) else 0.0
        sc += 2.0 if " - " in t else 0.0
        sc += 2.5 if re.search(r"\bpage\s*\d+\b", t, flags=re.IGNORECASE) else 0.0
        sc -= 0.012 * max(0, len(t) - 36)
        sc -= 0.005 * ln.y0
        sc -= 0.002 * ln.x0
        sc -= 2.0 if ("," in t or "." in t or ";" in t) else 0.0
        return sc

    best = max(candidates, key=score_title)
    return (best.text or "").strip()


def _compute_option_like_lines(lines, page_w: float) -> set:
    buckets = {}
    for i, ln in enumerate(lines):
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln):
            continue

        if len(t) > 14:
            continue
        if ln.x0 < 0.35 * page_w:
            continue

        yb = int(round(ln.y0 / 3.0))
        buckets.setdefault(yb, []).append(i)

    opt = set()
    for _, idxs in buckets.items():
        if len(idxs) >= 2:
            opt.update(idxs)
    return opt


def _compute_option_stack_lines(lines: list, page_w: float, med_size: float) -> set:
    """
    Detect vertical option lists (single column, many short items aligned at same x0).
    These are answer choices / legends, not data-entry fields.
    """
    cand = []
    for i, ln in enumerate(lines):
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue

        # Options are usually not in far-left prompt lane
        if ln.x0 < 0.20 * page_w:
            continue

        # Option-like: short-ish, not ending with ":" / "?" (prompts)
        if len(t) < 2 or len(t) > 30:
            continue
        if t.endswith(":") or t.endswith("?"):
            continue
        if not _has_letter(t):
            continue
        if _looks_like_instruction_text(t):
            continue

        # Similar to body size
        if ln.size > max(16.5, med_size + 6.2):
            continue

        # Usually narrow column items
        if (ln.x1 - ln.x0) > 0.34 * page_w:
            continue

        cand.append((i, ln))

    if len(cand) < 6:
        return set()

    buckets: Dict[int, List[int]] = {}
    for i, ln in cand:
        xb = int(round(ln.x0 / 10.0))
        buckets.setdefault(xb, []).append(i)

    option_idx = set()
    for xb, idxs in buckets.items():
        if len(idxs) < 6:
            continue

        xs = [lines[i].x0 for i in idxs]
        ys = [lines[i].y0 for i in idxs]
        if statistics.pstdev(xs) > 22:
            continue
        if (max(ys) - min(ys)) < 120:
            continue

        # Ensure it's really a list: mostly short phrases
        shortish = 0
        for i in idxs:
            t = (lines[i].text or "").strip()
            if len(t) <= 20:
                shortish += 1
        if shortish / max(1, len(idxs)) < 0.70:
            continue

        option_idx.update(idxs)

    return option_idx


def _detect_rating_header_rows(lines: list, page_w: float, med_size: float) -> set:
    """
    Detect dense header rows of short tokens in mid/right (e.g., rating anchors).
    """
    rows: Dict[int, List[int]] = {}
    for i, ln in enumerate(lines):
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue
        if ln.y0 > 220:
            continue
        if ln.x0 < 0.33 * page_w:
            continue
        if len(t) > 10:
            continue
        if ln.size < (med_size - 0.2) or ln.size > (med_size + 6.0):
            continue
        yb = int(round(ln.y0 / 3.5))
        rows.setdefault(yb, []).append(i)

    rating_rows = set()
    for yb, idxs in rows.items():
        if len(idxs) >= 4:
            rating_rows.add(yb)
    return rating_rows


def _detect_table_header_token_indices(lines: list, page_w: float, med_size: float) -> set:
    """
    Detect generic table header rows (e.g., 'Test', 'Result', 'Units') so we don't
    mistake them for data-entry field labels.
    """
    rows: Dict[int, List[int]] = {}
    for i, ln in enumerate(lines):
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue
        if ln.y0 > 245:
            continue
        if len(t) < 2 or len(t) > 28:
            continue
        if not _has_letter(t):
            continue
        if _looks_like_instruction_text(t):
            continue
        if ln.size < (med_size - 0.2) or ln.size > (med_size + 6.2):
            continue
        yb = int(round(ln.y0 / 3.8))
        rows.setdefault(yb, []).append(i)

    header_idx = set()
    for yb, idxs in rows.items():
        if len(idxs) < 2:
            continue
        xs = [lines[i].x0 for i in idxs]
        if (max(xs) - min(xs)) < 0.28 * page_w:
            continue
        if statistics.pstdev(xs) < 35:
            continue
        header_idx.update(idxs)
    return header_idx


def _build_column_headers(
    lines,
    page_w: float,
    med_size: float,
    option_like_idx: set,
    option_stack_idx: set,
    rating_header_rows: set,
) -> List[Tuple[float, str]]:
    header_lines = []
    for i, ln in enumerate(lines):
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if ln.y0 > 205:
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue
        if i in option_like_idx or i in option_stack_idx:
            continue

        yb = int(round(ln.y0 / 3.5))
        # Avoid dense rating-anchor rows, but keep longer descriptive headers.
        if yb in rating_header_rows and len(t) <= 9 and ln.x0 >= 0.33 * page_w:
            continue

        if ln.size < (med_size + 0.7):
            continue
        if ln.size > (med_size + 6.1):
            continue

        if len(t) <= 3:
            continue

        header_lines.append(ln)

    header_lines.sort(key=lambda l: (l.x0, l.y0))
    clusters: List[List] = []
    for ln in header_lines:
        placed = False
        for cl in clusters:
            if abs(cl[0].x0 - ln.x0) <= 35:
                cl.append(ln)
                placed = True
                break
        if not placed:
            clusters.append([ln])

    col_headers: List[Tuple[float, str]] = []
    for cl in clusters:
        cl.sort(key=lambda l: l.y0)
        txt = _join_wrapped([c.text.strip() for c in cl if c.text and c.text.strip()])
        txt = _clean_label(txt)
        if not txt:
            continue
        if len(txt) <= 3:
            continue
        if not _has_letter(txt) and len(txt) < 6:
            continue
        col_headers.append((statistics.median([c.x0 for c in cl]), txt))

    dedup = {}
    for x, txt in col_headers:
        k = txt.lower()
        if k not in dedup or abs(dedup[k][0] - x) > 15:
            dedup[k] = (x, txt)
    return sorted(dedup.values(), key=lambda xt: xt[0])


def _closest_col_header(col_headers: List[Tuple[float, str]], x: float) -> str:
    if not col_headers:
        return ""
    best = min(col_headers, key=lambda xt: abs(xt[0] - x))
    if abs(best[0] - x) > 150:
        return ""
    return best[1]


def _is_readonly_marked(code_idx: int, lines: list) -> bool:
    code_ln = lines[code_idx]
    y0 = code_ln.y0
    for j in range(code_idx + 1, min(len(lines), code_idx + 20)):
        ln = lines[j]
        if ln.y0 - y0 > 90:
            break
        if not getattr(ln, "non_black", False):
            continue
        if abs(ln.x0 - code_ln.x0) > 110:
            continue
        t = (getattr(ln, "text", "") or "").strip().lower()
        if "read-only" in t or "read only" in t:
            return True
    return False


def _find_label_for_code(
    code_idx: int,
    lines: list,
    option_like_idx: set,
    option_stack_idx: set,
    table_header_idx: set,
    page_w: float,
    med_size: float,
) -> str:
    code_ln = lines[code_idx]
    code_y = code_ln.y0

    def is_human_candidate(i: int) -> bool:
        ln = lines[i]
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            return False
        if _looks_like_furniture(ln):
            return False
        if _is_technical_marker(ln):
            return False
        if _looks_like_instruction_text(t):
            return False
        if i in option_like_idx or i in option_stack_idx:
            return False
        if i in table_header_idx:
            return False

        # Exclude likely filled values (very short, numeric-ish) in right lanes
        if ln.x0 > 0.55 * page_w and len(t) <= 6:
            alnum = "".join(ch for ch in t if ch.isalnum())
            if alnum.isdigit() or len(alnum) <= 3:
                return False

        # Exclude pure punctuation / bullets
        stripped = "".join(ch for ch in t if unicodedata.category(ch)[0] not in ("P", "Z"))
        if not stripped:
            return False
        return True

    inline = _find_inline_label_near_code(
        code_idx=code_idx,
        lines=lines,
        is_human_candidate=is_human_candidate,
        option_like_idx=option_like_idx,
        option_stack_idx=option_stack_idx,
        table_header_idx=table_header_idx,
        page_w=page_w,
    )
    if inline is not None:
        label_lines = _collect_wrapped_label(
            inline,
            code_idx,
            lines,
            is_human_candidate,
            option_like_idx,
            med_size,
        )
        label = _join_wrapped([ln.text.strip() for ln in label_lines])
        label = _clean_label(label)
        if label and (_has_letter(label) or len(label) >= 6):
            return label

    win1 = 130 if code_ln.x0 > 0.25 * page_w else 115
    anchor = _pick_anchor(code_idx, lines, is_human_candidate, page_w, code_ln.x0, win1)

    if anchor is None and code_ln.x0 <= 0.22 * page_w:
        anchor = _pick_anchor(code_idx, lines, is_human_candidate, page_w, code_ln.x0, 470)

    if anchor is None:
        anchor = _pick_anchor(code_idx, lines, is_human_candidate, page_w, code_ln.x0, 240, relax_x=True)

    if anchor is None:
        anchor = _pick_anchor_below(code_idx, lines, is_human_candidate, win_y=38, page_w=page_w)

    if anchor is None:
        return ""

    label_lines = _collect_wrapped_label(anchor, code_idx, lines, is_human_candidate, option_like_idx, med_size)
    label = _join_wrapped([ln.text.strip() for ln in label_lines])

    if label and (code_y - lines[anchor].y0) > 200 and code_ln.x0 <= 0.22 * page_w:
        refined = None
        for i in range(code_idx - 1, -1, -1):
            ln = lines[i]
            if code_y - ln.y0 > 470:
                break
            if not is_human_candidate(i):
                continue
            if ln.x0 > 0.35 * page_w:
                continue
            if i in option_stack_idx:
                continue
            refined = i
            break
        if refined is not None and refined != anchor:
            label_lines = _collect_wrapped_label(refined, code_idx, lines, is_human_candidate, option_like_idx, med_size)
            label = _join_wrapped([ln.text.strip() for ln in label_lines])

    label = _clean_label(label)
    if not label:
        return ""
    if not _has_letter(label) and len(label) < 6:
        return ""
    return label


def _find_inline_label_near_code(
    code_idx: int,
    lines: list,
    is_human_candidate: Callable[[int], bool],
    option_like_idx: set,
    option_stack_idx: set,
    table_header_idx: set,
    page_w: float,
) -> Optional[int]:
    code_ln = lines[code_idx]
    cy = code_ln.y0
    cx0 = code_ln.x0
    cx1 = code_ln.x1

    start = max(0, code_idx - 25)
    end = min(len(lines), code_idx + 25)

    same_row = []
    for i in range(start, end):
        if i == code_idx:
            continue
        ln = lines[i]
        if abs(ln.y0 - cy) > 6.5:
            continue
        if not is_human_candidate(i):
            continue
        if i in option_like_idx or i in option_stack_idx or i in table_header_idx:
            continue
        t = (ln.text or "").strip()
        if not t or t.startswith("["):
            continue
        same_row.append(i)

    if not same_row:
        return None

    if cx0 <= 0.28 * page_w:
        best = None
        best_dx = None
        for i in same_row:
            ln = lines[i]
            if ln.x0 <= cx1 + 4:
                continue
            dx = ln.x0 - cx1
            if dx > 320:
                continue
            if best_dx is None or dx < best_dx:
                best_dx = dx
                best = i
        if best is not None:
            return best

    best = None
    best_dx = None
    for i in same_row:
        ln = lines[i]
        if ln.x1 >= cx0 - 3:
            continue
        dx = cx0 - ln.x1
        if dx > 300:
            continue
        if (ln.x1 - ln.x0) > 0.80 * page_w:
            continue
        if best_dx is None or dx < best_dx:
            best_dx = dx
            best = i
    return best


def _pick_anchor(
    code_idx: int,
    lines: list,
    is_human_candidate: Callable[[int], bool],
    page_w: float,
    code_x: float,
    win_y: float,
    relax_x: bool = False,
) -> Optional[int]:
    code_y = lines[code_idx].y0
    best_i = None
    best_score = None

    for i in range(code_idx - 1, -1, -1):
        ln = lines[i]
        dy = code_y - ln.y0
        if dy < 0:
            continue
        if dy > win_y:
            break
        if not is_human_candidate(i):
            continue

        if not relax_x:
            if code_x <= 0.22 * page_w:
                if ln.x0 > 0.40 * page_w:
                    continue
            else:
                if ln.x0 > 0.50 * page_w:
                    continue

        t = (ln.text or "").strip()
        span_pen = 0.0
        if (ln.x1 - ln.x0) > 0.78 * page_w:
            span_pen = 42.0

        # Strongly discourage narrative lines
        narr_pen = 0.0
        if _looks_like_instruction_text(t):
            narr_pen = 55.0

        x_pref = 0.0
        if code_x > 0.25 * page_w and ln.x0 < 0.30 * page_w:
            x_pref = -10.0

        score = dy + 0.03 * abs(ln.x0 - min(code_x, 0.30 * page_w)) + x_pref + span_pen + narr_pen
        if best_score is None or score < best_score:
            best_score = score
            best_i = i

    return best_i


def _pick_anchor_below(code_idx: int, lines: list, is_human_candidate: Callable[[int], bool], win_y: float, page_w: float) -> Optional[int]:
    code_y = lines[code_idx].y0
    code_x = lines[code_idx].x0
    best_i = None
    best_score = None
    for i in range(code_idx + 1, min(len(lines), code_idx + 30)):
        ln = lines[i]
        dy = ln.y0 - code_y
        if dy < 0:
            continue
        if dy > win_y:
            break
        if not is_human_candidate(i):
            continue

        if code_x <= 0.22 * page_w and ln.x0 > 0.45 * page_w:
            continue

        score = dy + 0.02 * abs(ln.x0 - code_x)
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    return best_i


def _collect_wrapped_label(
    anchor_idx: int,
    code_idx: int,
    lines: list,
    is_human_candidate: Callable[[int], bool],
    option_like_idx: set,
    med_size: float,
) -> List:
    anchor = lines[anchor_idx]
    ax = anchor.x0
    asz = anchor.size

    def size_sim(a: float, b: float) -> bool:
        return abs(a - b) <= 2.2 or (min(a, b) > 0 and max(a, b) / min(a, b) <= 1.22)

    start = anchor_idx
    for i in range(anchor_idx - 1, -1, -1):
        ln = lines[i]
        if not is_human_candidate(i):
            continue
        if i in option_like_idx:
            continue
        if anchor.y0 - ln.y0 > 18:
            break
        if abs(ln.x0 - ax) > 28:
            break
        if not size_sim(ln.size, asz):
            break
        start = i

    end = anchor_idx
    for i in range(anchor_idx + 1, min(code_idx, len(lines))):
        ln = lines[i]
        if (getattr(ln, "text", "") or "").strip().startswith("["):
            break
        if i in option_like_idx:
            continue
        if not is_human_candidate(i):
            continue
        if ln.y0 - lines[end].y0 > 18:
            break
        if abs(ln.x0 - ax) > 28:
            break
        if ln.size > max(med_size + 6.5, asz + 5.0):
            break
        end = i

    return [lines[i] for i in range(start, end + 1)]


def _join_wrapped(parts: List[str]) -> str:
    parts = [p.strip() for p in parts if p and p.strip()]
    if not parts:
        return ""
    out = parts[0]
    for p in parts[1:]:
        if out.endswith("-") and p and p[0].isalpha():
            out = out[:-1] + p
        else:
            out = out + " " + p
    return out


def _is_descriptive_header(h: str) -> bool:
    h = (h or "").strip()
    if not h:
        return False
    # Multi-word is usually descriptive (e.g., 'Abnormal Findings', 'Clinically Significant').
    if " " in h and len(h) >= 6:
        return True
    # Longer single tokens can be helpful (e.g., 'Comments', 'Medication', 'Assessment').
    if len(h) >= 10:
        return True
    return False


def _clean_label(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()

    s = re.sub(r"^[\u2022\u00b7\-\*\u25aa\u25cf]+\s*", "", s).strip()
    s = _LEADING_ENUM_RE.sub("", s).strip()

    if s.endswith(":") and _has_letter(s):
        s = s[:-1].rstrip()

    if len(s) >= 35:
        m = re.search(r"\b([A-Za-z]{2,}/[A-Za-z]{2,})\s+([A-Za-z]{2,})\s*$", s)
        if m:
            opts = {p.lower() for p in m.group(1).split("/") if p}
            tail = m.group(2).lower()
            if tail in opts:
                s = s[: m.start(2)].rstrip()

    if not s or re.fullmatch(r"[\W_]+", s, flags=re.UNICODE):
        return ""
    return s


def _extract_fields_when_no_codes(
    lines: list,
    page_w: float,
    med_size: float,
    option_stack_idx: set,
    col_headers: List[Tuple[float, str]],
    table_header_idx: set,
) -> List[str]:
    """
    Handle pages where bracketed code markers are missing from extracted text.
    Extend prior logic by also handling matrix/table layouts (row labels + column headers),
    and standalone labels above blank entry areas.
    """

    def is_prompt_like_idx(i: int) -> bool:
        ln = lines[i]
        t = (getattr(ln, "text", "") or "").strip()
        if not t:
            return False
        if t.startswith("["):
            return False
        if _looks_like_furniture(ln):
            return False
        if _is_technical_marker(ln):
            return False
        if _looks_like_instruction_text(t):
            return False
        if i in option_stack_idx or i in table_header_idx:
            return False
        if not _has_letter(t):
            return False
        return True

    # A) Matrix/table: detect left row labels + descriptive column headers.
    row_labels = _detect_left_row_labels(lines, page_w, med_size, option_stack_idx, table_header_idx)
    if len(row_labels) >= 2 and len(col_headers) >= 1:
        labels_out: List[str] = []
        descriptive_headers = []
        for _, hdr in col_headers:
            hdr2 = _clean_label(hdr)
            if not hdr2:
                continue
            # Only append truly descriptive headers on no-code tables to avoid anchors like 'Normal'/'Test'
            if (" " in hdr2) or (len(hdr2) >= 12):
                descriptive_headers.append(hdr2)

        for _, txt in row_labels:
            base = _clean_label(txt)
            if not base:
                continue
            labels_out.append(base)
            for hdr in descriptive_headers:
                if hdr.lower() not in base.lower():
                    labels_out.append(_clean_label(base + " " + hdr))

        return labels_out

    # 1) Prompt ending with ":" with a dense option list below (dropdown-style)
    best_colon_prompt = None
    best_support = 0

    for i, ln in enumerate(lines):
        if not is_prompt_like_idx(i):
            continue
        t = ln.text.strip()
        if ln.y0 > 300:
            continue
        if ln.x0 > 0.52 * page_w:
            continue
        if not t.endswith(":"):
            continue

        opts = []
        for j, ln2 in enumerate(lines):
            if j in option_stack_idx:
                continue
            if ln2.y0 <= ln.y0 + 14:
                continue
            if ln2.y0 - ln.y0 > 820:
                continue
            if not is_prompt_like_idx(j):
                continue
            if ln2.x0 < 0.25 * page_w:
                continue
            txt2 = (ln2.text or "").strip()
            if len(txt2) < 2 or len(txt2) > 30:
                continue
            opts.append(ln2)

        if len(opts) < 5:
            continue

        xs = [o.x0 for o in opts]
        if statistics.pstdev(xs) > 70:
            continue

        support = len(opts)
        if support > best_support:
            best_support = support
            best_colon_prompt = ln

    if best_colon_prompt is not None:
        return [(best_colon_prompt.text or "").strip()]

    # 2) Standalone labels above blank entry areas (textboxes) with no code captured.
    #    Heuristic: left lane, short-ish, and followed by a larger-than-typical vertical gap.
    standalone = _detect_standalone_field_labels(lines, page_w, med_size, option_stack_idx, table_header_idx)
    if standalone:
        return standalone

    # 3) Prior "header row fields + enumerated options below" logic, but safer:
    #    Only use when we cannot find row labels, and headers are clearly field prompts (left-ish).
    header_candidates = []
    for i, ln in enumerate(lines):
        if not is_prompt_like_idx(i):
            continue
        if i in table_header_idx:
            continue
        t = ln.text.strip()
        if ln.y0 > 185:
            continue
        if ln.x0 > 0.55 * page_w:
            continue
        if len(t) < 3 or len(t) > 60:
            continue
        if ln.size >= max(14.5, med_size + 4.0):
            continue
        # Prefer field-like short nouns, not generic columns
        if t.endswith("."):
            continue
        header_candidates.append((i, ln))

    rows: Dict[int, List[Tuple[int, object]]] = {}
    for i, ln in header_candidates:
        yk = int(round(ln.y0 / 4.0))
        rows.setdefault(yk, []).append((i, ln))

    best_row = None
    best_n = 0
    for yk, lns in rows.items():
        if len(lns) >= 2 and len(lns) > best_n:
            best_n = len(lns)
            best_row = (yk, lns)

    if best_row is None:
        return []

    row_y = 4.0 * best_row[0]
    has_enum = False
    for ln in lines:
        if ln.y0 <= row_y + 18:
            continue
        if ln.y0 - row_y > 560:
            break
        t = (getattr(ln, "text", "") or "").strip()
        if not t or _looks_like_furniture(ln):
            continue
        t2 = t.lstrip("\\").lstrip()
        if _ENUM_OPT_RE.match(t2):
            has_enum = True
            break

    if not has_enum:
        return []

    lns = sorted(best_row[1], key=lambda il: il[1].x0)
    return [(ln.text or "").strip() for _, ln in lns]


def _detect_left_row_labels(lines: list, page_w: float, med_size: float, option_stack_idx: set, table_header_idx: set) -> List[Tuple[float, str]]:
    """
    Detect row labels in the left lane for matrix/table pages (no code markers present).
    Returns list of (y0, text) in reading order.
    """
    cands: List[Tuple[float, float, int, str]] = []
    for i, ln in enumerate(lines):
        if i in option_stack_idx or i in table_header_idx:
            continue
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue
        if _looks_like_instruction_text(t):
            continue
        if not _has_letter(t):
            continue
        if ln.x0 > 0.34 * page_w:
            continue
        if ln.y0 < 150 or ln.y0 > 760:
            continue
        if len(t) < 2 or len(t) > 80:
            continue
        if t.endswith("."):
            continue
        if ln.size < (med_size - 1.5) or ln.size > (med_size + 5.0):
            continue
        cands.append((ln.y0, ln.x0, i, t))

    if not cands:
        return []

    cands.sort(key=lambda x: (x[0], x[1]))
    out: List[Tuple[float, str]] = []
    used_y = set()
    for y0, x0, i, t in cands:
        yk = int(round(y0 / 6.0))
        if yk in used_y:
            continue
        used_y.add(yk)
        out.append((y0, t))

    if len(out) < 2:
        return []

    return out


def _detect_standalone_field_labels(lines: list, page_w: float, med_size: float, option_stack_idx: set, table_header_idx: set) -> List[str]:
    """
    Find labels that likely sit above a blank entry box (no codes captured).
    """
    # Sort by y then x to compute "next line below" gaps.
    idxs = list(range(len(lines)))
    idxs.sort(key=lambda i: (getattr(lines[i], "y0", 0.0), getattr(lines[i], "x0", 0.0)))

    # Map to next non-furniture/non-empty line below per index in the sorted order.
    next_below = {}
    for pos, i in enumerate(idxs):
        ln = lines[i]
        if _looks_like_furniture(ln):
            continue
        if not (getattr(ln, "text", "") or "").strip():
            continue
        for pos2 in range(pos + 1, min(len(idxs), pos + 12)):
            j = idxs[pos2]
            ln2 = lines[j]
            t2 = (getattr(ln2, "text", "") or "").strip()
            if not t2:
                continue
            if _looks_like_furniture(ln2):
                continue
            next_below[i] = j
            break

    out = []
    for i, ln in enumerate(lines):
        if i in option_stack_idx or i in table_header_idx:
            continue
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue
        if _looks_like_instruction_text(t):
            continue
        if not _has_letter(t):
            continue

        # Field-label lane
        if ln.x0 > 0.56 * page_w:
            continue

        # Avoid pure titles at top
        if ln.y0 < 155 and (ln.size >= max(14.5, med_size + 4.4) or getattr(ln, "non_black", False)):
            continue

        if len(t) < 3 or len(t) > 70:
            continue
        if t.endswith("."):
            continue

        j = next_below.get(i)
        if j is None:
            continue
        ln2 = lines[j]
        gap = ln2.y0 - ln.y0
        if gap < 26:
            continue

        # If the next line is in the same left lane and close, it's probably just another label.
        if gap < 55 and abs(ln2.x0 - ln.x0) <= 45:
            continue

        # Don’t treat labels that are immediately followed by option lists as standalone textboxes.
        if any((k in option_stack_idx) and (0 < (lines[k].y0 - ln.y0) < 220) and (abs(lines[k].x0 - ln.x0) < 140) for k in range(len(lines))):
            continue

        out.append(t)

    # Dedup while keeping order
    ded = []
    seen = set()
    for t in out:
        c = _clean_label(t)
        if not c:
            continue
        k = c.lower()
        if k in seen:
            continue
        seen.add(k)
        ded.append(c)
    return ded


def _detect_dictionary_like_code_indices(lines: list, code_indices: List[int], page_w: float, option_stack_idx: set, table_header_idx: set) -> set:
    """
    Detect code lines that are part of a vertical legend/dictionary mapping (option -> [CODE]),
    and should not be treated as data-entry fields.
    This is structural: repeated same-row pairs in the right half of the page.
    """
    # Group code indices by approximate x column
    buckets: Dict[int, List[int]] = {}
    for i in code_indices:
        ln = lines[i]
        xb = int(round(ln.x0 / 12.0))
        buckets.setdefault(xb, []).append(i)

    bad = set()
    for xb, idxs in buckets.items():
        if len(idxs) < 6:
            continue
        idxs_sorted = sorted(idxs, key=lambda i: lines[i].y0)
        x_med = statistics.median([lines[i].x0 for i in idxs_sorted])
        if x_med < 0.42 * page_w:
            continue
        y_span = lines[idxs_sorted[-1]].y0 - lines[idxs_sorted[0]].y0
        if y_span < 140:
            continue

        # Count how many have an immediate same-row token immediately to the left in the right/mid lane.
        paired = 0
        for ci in idxs_sorted:
            code_ln = lines[ci]
            cy = code_ln.y0
            cx0 = code_ln.x0
            best_li = None
            best_dx = None
            for j, ln in enumerate(lines):
                if j == ci or j in option_stack_idx or j in table_header_idx:
                    continue
                t = (getattr(ln, "text", "") or "").strip()
                if not t or t.startswith("["):
                    continue
                if _looks_like_furniture(ln) or _is_technical_marker(ln):
                    continue
                if _looks_like_instruction_text(t):
                    continue
                if abs(ln.y0 - cy) > 6.5:
                    continue
                if ln.x1 >= cx0 - 2:
                    continue
                dx = cx0 - ln.x1
                if dx > 120:
                    continue
                # option-like token: short, narrow, not a prompt
                if len(t) > 28 or t.endswith(":") or t.endswith("?"):
                    continue
                if (ln.x1 - ln.x0) > 0.28 * page_w:
                    continue
                if ln.x0 < 0.30 * page_w:
                    continue
                if best_dx is None or dx < best_dx:
                    best_dx = dx
                    best_li = j
            if best_li is not None:
                paired += 1

        if paired / max(1, len(idxs_sorted)) >= 0.70:
            bad.update(idxs_sorted)

    return bad
```
