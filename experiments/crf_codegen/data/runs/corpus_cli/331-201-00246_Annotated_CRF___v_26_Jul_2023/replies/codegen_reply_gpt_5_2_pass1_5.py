```python
import re
import statistics
import unicodedata
from typing import List, Tuple, Dict, Optional, Callable


_CODE_RE = re.compile(r"^\[(?=[A-Za-z0-9]{2,}\]$)(?=.*[A-Za-z])[A-Za-z0-9]+\]$")
_PAGE_RE = re.compile(r"^Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)
_ENUM_OPT_RE = re.compile(r"^\d+\s*[\.\)]\s*")
_LEADING_ENUM_RE = re.compile(r"^(?:\\\s*)?\d{1,3}\s*[\.\)]\s*")
_ROW_N_RE = re.compile(r"^\s*Row\s+\d+\b", re.IGNORECASE)


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    seen = set()
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        page_w = max((getattr(ln, "x1", 0.0) for ln in lines), default=800.0) or 800.0
        sizes = [ln.size for ln in lines if getattr(ln, "size", 0) and (getattr(ln, "text", "") or "").strip()]
        med_size = statistics.median(sizes) if sizes else 9.0

        option_like_idx = _compute_option_like_lines(lines, page_w)
        option_stack_idx = _compute_option_stack_lines(lines, page_w, med_size)
        rating_header_rows = _detect_rating_header_rows(lines, page_w, med_size)
        table_header_idx = _detect_table_header_token_indices(lines, page_w, med_size)

        checklist = _detect_enumerated_checklist_mode(
            lines,
            page_w=page_w,
            med_size=med_size,
            option_stack_idx=option_stack_idx,
            table_header_idx=table_header_idx,
        )

        title, title_conf = _detect_form_title(lines, med_size, page_w, first_code_y=_first_code_y(lines))
        if title and title_conf >= 1.0:
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

        if not code_indices:
            labels = _extract_fields_when_no_codes(
                lines,
                page_w=page_w,
                med_size=med_size,
                option_stack_idx=option_stack_idx,
                col_headers=col_headers,
                table_header_idx=table_header_idx,
                checklist=checklist,
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

        dict_like_codes = _detect_dictionary_like_code_indices(lines, code_indices, page_w, option_stack_idx, table_header_idx)

        for ci in code_indices:
            if ci in dict_like_codes:
                continue

            if _is_readonly_marked(ci, lines):
                continue

            code_ln = lines[ci]
            label = _find_label_for_code(
                ci,
                lines=lines,
                option_like_idx=option_like_idx,
                option_stack_idx=option_stack_idx,
                table_header_idx=table_header_idx,
                page_w=page_w,
                med_size=med_size,
                checklist=checklist,
            )
            if not label:
                continue

            label = _clean_label(label)
            if not label:
                continue

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


def _first_code_y(lines: list) -> Optional[float]:
    ys = []
    for ln in lines:
        t = (getattr(ln, "text", "") or "").strip()
        if t and _CODE_RE.match(t):
            ys.append(getattr(ln, "y0", 0.0))
    return min(ys) if ys else None


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


def _looks_like_stray_bracket_artifact(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return True
    # Short tokens with unmatched closing bracket(s) are usually extraction artifacts.
    if len(t) <= 12 and ("]" in t) and ("[" not in t) and (t.endswith("]") or t.endswith(")]") or t.endswith("] )")):
        return True
    return False


def _is_technical_marker(ln) -> bool:
    t = (getattr(ln, "text", "") or "").strip()
    if not t:
        return True
    if _PAGE_RE.match(t):
        return True
    if _ROW_N_RE.match(t):
        return True
    if t.startswith("[") and ":" in t[:24]:
        return True
    if t.startswith("(") and ":" in t[:34]:
        return True
    if _looks_like_stray_bracket_artifact(t):
        return True
    return False


def _looks_like_instruction_text(t: str, *, allow_enum: bool = False) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    if t.endswith(":") or t.endswith("?"):
        return False

    if allow_enum and _LEADING_ENUM_RE.match(t):
        # Checklist item labels can be long narrative sentences.
        return False

    if len(t) >= 120 and (("." in t) or (";" in t) or ("," in t)):
        return True
    if len(t) >= 170:
        return True
    return False


def _detect_form_title(lines, med_size: float, page_w: float, first_code_y: Optional[float]) -> Tuple[str, float]:
    candidates = []
    for ln in lines:
        t = (getattr(ln, "text", "") or "").strip()
        if not t:
            continue
        if _looks_like_furniture(ln):
            continue
        if t.startswith("["):
            continue
        if _LEADING_ENUM_RE.match(t):
            continue
        if _looks_like_stray_bracket_artifact(t):
            continue

        # Keep titles near the top; avoid mid-page prompts
        if ln.y0 > 240:
            continue

        # Avoid using a field label sitting below the first code line as a title.
        if first_code_y is not None and ln.y0 > first_code_y + 28:
            continue

        if t.endswith(":") or t.endswith("?"):
            continue
        if _looks_like_instruction_text(t):
            continue

        if len(t) > 115:
            continue
        if not _has_letter(t):
            continue

        # Must stand out vs body: either color, or clearly larger font.
        standout = False
        if getattr(ln, "non_black", False) and ln.size >= max(12.5, med_size + 2.2):
            standout = True
        if ln.size >= max(15.0, med_size + 4.0):
            standout = True
        if not standout:
            continue

        # Left-ish or centered-ish
        if ln.x0 > max(250.0, 0.45 * page_w):
            continue

        candidates.append(ln)

    if not candidates:
        return ("", 0.0)

    def score_title(ln) -> float:
        t = (ln.text or "").strip()
        sc = 0.0
        sc += 3.0 * ln.size
        sc += 1.2 if getattr(ln, "non_black", False) else 0.0
        sc += 1.0 if " - " in t else 0.0
        sc -= 0.010 * max(0, len(t) - 34)
        sc -= 0.006 * ln.y0
        sc -= 0.002 * abs(ln.x0 - 0.22 * page_w)
        sc -= 2.0 if ("," in t or "." in t or ";" in t) else 0.0
        sc -= 1.5 if t.lower().startswith("row ") else 0.0
        return sc

    best = max(candidates, key=score_title)
    best_txt = (best.text or "").strip()

    # Confidence: require it to beat the "standout" threshold meaningfully.
    conf = 0.0
    conf += 1.0 if best.size >= (med_size + 4.0) else 0.0
    conf += 0.6 if getattr(best, "non_black", False) else 0.0
    conf += 0.3 if best.y0 <= 170 else 0.0
    if len(best_txt) >= 8:
        conf += 0.2
    return (best_txt, conf)


def _compute_option_like_lines(lines, page_w: float) -> set:
    buckets = {}
    for i, ln in enumerate(lines):
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln):
            continue
        if _looks_like_stray_bracket_artifact(t):
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
    cand = []
    for i, ln in enumerate(lines):
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue

        if ln.x0 < 0.20 * page_w:
            continue

        if len(t) < 2 or len(t) > 30:
            continue
        if t.endswith(":") or t.endswith("?"):
            continue
        if not _has_letter(t):
            continue
        if _looks_like_instruction_text(t):
            continue

        if ln.size > max(16.5, med_size + 6.2):
            continue

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
    rows: Dict[int, List[int]] = {}
    for i, ln in enumerate(lines):
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue
        if ln.y0 > 255:
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
        if ln.y0 > 230:
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue
        if i in option_like_idx or i in option_stack_idx:
            continue

        yb = int(round(ln.y0 / 3.5))
        if yb in rating_header_rows and len(t) <= 9 and ln.x0 >= 0.33 * page_w:
            continue

        if ln.size < (med_size + 0.6):
            continue
        if ln.size > (med_size + 6.3):
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
    for j in range(code_idx + 1, min(len(lines), code_idx + 22)):
        ln = lines[j]
        if ln.y0 - y0 > 110:
            break
        if not getattr(ln, "non_black", False):
            continue
        if abs(ln.x0 - code_ln.x0) > 120:
            continue
        t = (getattr(ln, "text", "") or "").strip().lower()
        if "read-only" in t or "read only" in t:
            return True
    return False


def _detect_enumerated_checklist_mode(
    lines: list,
    *,
    page_w: float,
    med_size: float,
    option_stack_idx: set,
    table_header_idx: set,
) -> Dict[str, object]:
    enum_idxs = []
    for i, ln in enumerate(lines):
        if i in option_stack_idx or i in table_header_idx:
            continue
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue
        if not _LEADING_ENUM_RE.match(t):
            continue
        if ln.x0 > 0.48 * page_w:
            continue
        if ln.size < (med_size - 1.8) or ln.size > (med_size + 6.5):
            continue
        enum_idxs.append(i)

    if len(enum_idxs) < 4:
        return {"mode": False}

    ys = [lines[i].y0 for i in enum_idxs]
    if (max(ys) - min(ys)) < 140:
        return {"mode": False}

    # Look for a repeated response/anchor column on the right half: short tokens, aligned x.
    right_cands = []
    for i, ln in enumerate(lines):
        if i in option_stack_idx or i in table_header_idx:
            continue
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue
        if ln.x0 < 0.45 * page_w:
            continue
        if len(t) > 18:
            continue
        if not _has_letter(t):
            continue
        if _looks_like_instruction_text(t):
            continue
        # Often contains "/" for two-choice headers/anchors, but keep it optional.
        right_cands.append(i)

    if len(right_cands) >= 6:
        buckets: Dict[int, List[int]] = {}
        for i in right_cands:
            xb = int(round(lines[i].x0 / 14.0))
            buckets.setdefault(xb, []).append(i)
        best_bucket = None
        best_n = 0
        for xb, idxs in buckets.items():
            if len(idxs) > best_n:
                best_n = len(idxs)
                best_bucket = xb
        if best_bucket is not None and best_n >= 6:
            xs = [lines[i].x0 for i in buckets[best_bucket]]
            if statistics.pstdev(xs) <= 20:
                return {"mode": True, "right_x": statistics.median(xs)}

    # Even without a clean right column, a dense enumerated list is likely a checklist form.
    return {"mode": True}


def _find_label_for_code(
    code_idx: int,
    lines: list,
    option_like_idx: set,
    option_stack_idx: set,
    table_header_idx: set,
    page_w: float,
    med_size: float,
    checklist: Dict[str, object],
) -> str:
    code_ln = lines[code_idx]
    code_y = code_ln.y0
    code_x = code_ln.x0
    allow_enum = bool(checklist.get("mode", False))

    def is_human_candidate(i: int, *, allow_option_stack: bool) -> bool:
        ln = lines[i]
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            return False
        if _looks_like_furniture(ln):
            return False
        if _is_technical_marker(ln):
            return False
        if i in table_header_idx:
            return False

        if not allow_option_stack and (i in option_like_idx or i in option_stack_idx):
            return False

        if _looks_like_instruction_text(t, allow_enum=allow_enum):
            return False

        if not _has_letter(t):
            return False

        if _looks_like_stray_bracket_artifact(t):
            return False

        # Exclude likely filled values (very short, numeric-ish) in right lanes
        if ln.x0 > 0.55 * page_w and len(t) <= 6:
            alnum = "".join(ch for ch in t if ch.isalnum())
            if alnum.isdigit() or len(alnum) <= 3:
                return False

        stripped = "".join(ch for ch in t if unicodedata.category(ch)[0] not in ("P", "Z"))
        if not stripped:
            return False

        return True

    def attempt(allow_option_stack: bool) -> str:
        inline = _find_inline_label_near_code(
            code_idx=code_idx,
            lines=lines,
            is_human_candidate=lambda i: is_human_candidate(i, allow_option_stack=allow_option_stack),
            option_like_idx=option_like_idx if not allow_option_stack else set(),
            option_stack_idx=option_stack_idx if not allow_option_stack else set(),
            table_header_idx=table_header_idx,
            page_w=page_w,
        )
        if inline is not None:
            label_lines = _collect_wrapped_label(
                inline,
                code_idx,
                lines,
                is_human_candidate=lambda i: is_human_candidate(i, allow_option_stack=allow_option_stack),
                option_like_idx=option_like_idx if not allow_option_stack else set(),
                med_size=med_size,
            )
            label = _join_wrapped([ln.text.strip() for ln in label_lines])
            label = _clean_label(label)
            if label and (_has_letter(label) or len(label) >= 6):
                return label

        win1 = 130 if code_x > 0.25 * page_w else 115
        anchor = _pick_anchor(
            code_idx,
            lines,
            is_human_candidate=lambda i: is_human_candidate(i, allow_option_stack=allow_option_stack),
            page_w=page_w,
            code_x=code_x,
            win_y=win1,
            relax_x=False,
        )

        if anchor is None and code_x <= 0.22 * page_w:
            anchor = _pick_anchor(
                code_idx,
                lines,
                is_human_candidate=lambda i: is_human_candidate(i, allow_option_stack=allow_option_stack),
                page_w=page_w,
                code_x=code_x,
                win_y=470,
                relax_x=False,
            )

        if anchor is None:
            anchor = _pick_anchor(
                code_idx,
                lines,
                is_human_candidate=lambda i: is_human_candidate(i, allow_option_stack=allow_option_stack),
                page_w=page_w,
                code_x=code_x,
                win_y=240,
                relax_x=True,
            )

        # For top-of-page code markers where the label starts noticeably below (seen in some lab/assay layouts)
        if anchor is None and code_y < 200 and code_x < 0.30 * page_w:
            anchor = _pick_anchor_below(
                code_idx,
                lines,
                is_human_candidate=lambda i: is_human_candidate(i, allow_option_stack=allow_option_stack),
                win_y=130,
                page_w=page_w,
            )

        if anchor is None:
            anchor = _pick_anchor_below(
                code_idx,
                lines,
                is_human_candidate=lambda i: is_human_candidate(i, allow_option_stack=allow_option_stack),
                win_y=44,
                page_w=page_w,
            )

        if anchor is None:
            return ""

        label_lines = _collect_wrapped_label(
            anchor,
            code_idx,
            lines,
            is_human_candidate=lambda i: is_human_candidate(i, allow_option_stack=allow_option_stack),
            option_like_idx=option_like_idx if not allow_option_stack else set(),
            med_size=med_size,
        )
        label = _join_wrapped([ln.text.strip() for ln in label_lines])
        label = _clean_label(label)

        if not label:
            return ""

        # Checklist: strip leading enumeration consistently.
        if allow_enum and _LEADING_ENUM_RE.match(label):
            label = _clean_label(_LEADING_ENUM_RE.sub("", label).strip())

        if not label:
            return ""

        # If we accidentally latched onto a response/anchor column token, discard.
        if (len(label) <= 18) and (code_x > 0.42 * page_w) and ("/" in label or label.lower().startswith("met")):
            return ""

        return label

    # Pass 1: strict (avoid option stacks)
    label = attempt(allow_option_stack=False)
    if label:
        return label

    # Pass 2: relaxed for checkbox lists and similar, but only when code is in the left/mid lane.
    if code_x <= 0.38 * page_w:
        label2 = attempt(allow_option_stack=True)
        if label2:
            return label2

    return ""


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
            if dx > 340:
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
        if dx > 320:
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
                if ln.x0 > 0.42 * page_w:
                    continue
            else:
                if ln.x0 > 0.52 * page_w:
                    continue

        t = (ln.text or "").strip()
        span_pen = 0.0
        if (ln.x1 - ln.x0) > 0.78 * page_w:
            span_pen = 42.0

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


def _pick_anchor_below(
    code_idx: int,
    lines: list,
    is_human_candidate: Callable[[int], bool],
    win_y: float,
    page_w: float,
) -> Optional[int]:
    code_y = lines[code_idx].y0
    code_x = lines[code_idx].x0
    best_i = None
    best_score = None
    for i in range(code_idx + 1, min(len(lines), code_idx + 55)):
        ln = lines[i]
        dy = ln.y0 - code_y
        if dy < 0:
            continue
        if dy > win_y:
            break
        if not is_human_candidate(i):
            continue

        if code_x <= 0.22 * page_w and ln.x0 > 0.48 * page_w:
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
    if " " in h and len(h) >= 6:
        return True
    if len(h) >= 10:
        return True
    return False


def _clean_label(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\u00a0", " ")
    s = s.strip()
    s = s.lstrip("\\").strip()
    s = re.sub(r"\s+", " ", s).strip()

    s = re.sub(r"^[\u2022\u00b7\-\*\u25aa\u25cf]+\s*", "", s).strip()
    s = _LEADING_ENUM_RE.sub("", s).strip()

    # Trim unmatched trailing brackets/parentheses (common extraction debris like "Scan)]")
    if ("[" not in s) and ("]" in s):
        while s.endswith("]") and s.count("[") < s.count("]"):
            s = s[:-1].rstrip()
    if s.endswith(")") and s.count("(") < s.count(")"):
        s = s[:-1].rstrip()

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
    if _looks_like_stray_bracket_artifact(s):
        return ""
    return s


def _extract_fields_when_no_codes(
    lines: list,
    page_w: float,
    med_size: float,
    option_stack_idx: set,
    col_headers: List[Tuple[float, str]],
    table_header_idx: set,
    checklist: Dict[str, object],
) -> List[str]:
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
        if _looks_like_stray_bracket_artifact(t):
            return False
        return True

    # 0) Pure dictionary/legend list pages: many short aligned items, no prompts, no structure.
    if _looks_like_pure_dictionary_list_page(lines, page_w, med_size):
        return []

    # A) Enumerated checklist pages (eligibility-type): extract enumerated items as fields.
    if checklist.get("mode", False):
        items = _extract_enumerated_checklist_items(lines, page_w=page_w, med_size=med_size, option_stack_idx=option_stack_idx, table_header_idx=table_header_idx)
        if items:
            return items

    # B) Matrix/table: left row labels + descriptive column headers.
    row_labels = _detect_left_row_labels(lines, page_w, med_size, option_stack_idx, table_header_idx)
    if len(row_labels) >= 2 and len(col_headers) >= 1:
        labels_out: List[str] = []
        descriptive_headers = []
        for _, hdr in col_headers:
            hdr2 = _clean_label(hdr)
            if not hdr2:
                continue
            if (" " in hdr2) or (len(hdr2) >= 12):
                descriptive_headers.append(hdr2)

        if descriptive_headers:
            for _, txt in row_labels:
                base = _clean_label(txt)
                if not base:
                    continue
                labels_out.append(base)
                for hdr in descriptive_headers:
                    if hdr.lower() not in base.lower():
                        labels_out.append(_clean_label(base + " " + hdr))
            return labels_out

    # 1) Prompt ending with ":" with a dense option list below (dropdown-style) -> single field.
    best_colon_prompt = None
    best_support = 0

    for i, ln in enumerate(lines):
        if not is_prompt_like_idx(i):
            continue
        t = ln.text.strip()
        if ln.y0 > 320:
            continue
        if ln.x0 > 0.60 * page_w:
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
            if ln2.x0 < 0.22 * page_w:
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
    standalone = _detect_standalone_field_labels(lines, page_w, med_size, option_stack_idx, table_header_idx)
    if standalone:
        return standalone

    # 3) Header row fields + enumerated options below (legend pages for picklists): avoid unless strong evidence.
    header_candidates = []
    for i, ln in enumerate(lines):
        if not is_prompt_like_idx(i):
            continue
        if i in table_header_idx:
            continue
        t = ln.text.strip()
        if ln.y0 > 200:
            continue
        if ln.x0 > 0.62 * page_w:
            continue
        if len(t) < 3 or len(t) > 60:
            continue
        if ln.size >= max(14.5, med_size + 4.0):
            continue
        if t.endswith("."):
            continue
        if _LEADING_ENUM_RE.match(t):
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


def _looks_like_pure_dictionary_list_page(lines: list, page_w: float, med_size: float) -> bool:
    # Many short single tokens in one aligned column; no codes; likely a legend page.
    cands = []
    for ln in lines:
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue
        if _looks_like_instruction_text(t):
            continue
        if t.endswith(":") or t.endswith("?"):
            continue
        if not _has_letter(t):
            continue
        if len(t) > 22:
            continue
        if ln.size < (med_size - 2.0) or ln.size > (med_size + 7.0):
            continue
        cands.append(ln)

    if len(cands) < 10:
        return False

    buckets: Dict[int, List[object]] = {}
    for ln in cands:
        xb = int(round(ln.x0 / 18.0))
        buckets.setdefault(xb, []).append(ln)

    best = max(buckets.values(), key=len)
    if len(best) < 10:
        return False

    xs = [ln.x0 for ln in best]
    if statistics.pstdev(xs) > 16:
        return False

    ys = [ln.y0 for ln in best]
    if (max(ys) - min(ys)) < 220:
        return False

    # Require the "list column" to be away from the far-left prompt lane (typical for legend pages).
    x_med = statistics.median(xs)
    if x_med < 0.40 * page_w:
        return False

    return True


def _extract_enumerated_checklist_items(
    lines: list,
    *,
    page_w: float,
    med_size: float,
    option_stack_idx: set,
    table_header_idx: set,
) -> List[str]:
    idxs = list(range(len(lines)))
    idxs.sort(key=lambda i: (getattr(lines[i], "y0", 0.0), getattr(lines[i], "x0", 0.0)))

    def is_item_start(i: int) -> bool:
        if i in option_stack_idx or i in table_header_idx:
            return False
        ln = lines[i]
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            return False
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            return False
        if not _LEADING_ENUM_RE.match(t):
            return False
        if ln.x0 > 0.52 * page_w:
            return False
        if not _has_letter(t):
            return False
        if ln.size < (med_size - 2.0) or ln.size > (med_size + 7.0):
            return False
        return True

    starts = [i for i in idxs if is_item_start(i)]
    if len(starts) < 3:
        return []

    # Build items by appending wrapped continuation lines until next enumerated start.
    start_set = set(starts)
    out = []
    for si in starts:
        ln0 = lines[si]
        base_x = ln0.x0
        base_sz = ln0.size
        parts = [(ln0.text or "").strip()]

        # Find following lines in y order that continue the same item.
        for j in idxs:
            if j == si:
                continue
            ln = lines[j]
            if ln.y0 <= ln0.y0:
                continue
            if (ln.y0 - ln0.y0) > 140:
                break
            if j in option_stack_idx or j in table_header_idx:
                continue
            t = (getattr(ln, "text", "") or "").strip()
            if not t or t.startswith("["):
                continue
            if _looks_like_furniture(ln) or _is_technical_marker(ln):
                continue
            if j in start_set:
                break
            if _looks_like_instruction_text(t, allow_enum=True):
                # Still allow wrapped narrative text; only reject if it's clearly a separate paragraph.
                pass
            if not _has_letter(t):
                continue
            if abs(ln.size - base_sz) > 3.2 and not (min(ln.size, base_sz) > 0 and max(ln.size, base_sz) / min(ln.size, base_sz) <= 1.28):
                continue
            # Continuation lines usually align with the start or are slightly indented.
            if ln.x0 < base_x - 12:
                continue
            if ln.x0 > base_x + 140:
                continue
            # Keep tight vertical continuity.
            if (ln.y0 - (getattr(lines[si], "y0", 0.0))) > 135:
                continue
            parts.append(t)
            ln0 = ln

        txt = _join_wrapped(parts)
        txt = _clean_label(txt)
        if not txt:
            continue
        # Remove leading enum marker again (after wrapping/joining).
        txt = _clean_label(_LEADING_ENUM_RE.sub("", txt).strip())
        if not txt:
            continue
        if len(txt) < 12:
            continue
        out.append(txt)

    # Dedup preserve order
    ded = []
    seen = set()
    for t in out:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        ded.append(t)
    return ded


def _detect_left_row_labels(lines: list, page_w: float, med_size: float, option_stack_idx: set, table_header_idx: set) -> List[Tuple[float, str]]:
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
        if _looks_like_stray_bracket_artifact(t):
            continue
        if ln.x0 > 0.40 * page_w:
            continue
        if ln.y0 < 110 or ln.y0 > 770:
            continue
        if len(t) < 2 or len(t) > 85:
            continue
        if t.endswith("."):
            continue
        if ln.size < (med_size - 1.8) or ln.size > (med_size + 5.5):
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
    idxs = list(range(len(lines)))
    idxs.sort(key=lambda i: (getattr(lines[i], "y0", 0.0), getattr(lines[i], "x0", 0.0)))

    # Precompute lane density to avoid pulling items from dense lists (lab panels, dictionaries, etc.).
    lane_counts: Dict[int, int] = {}
    lane_ymin: Dict[int, float] = {}
    lane_ymax: Dict[int, float] = {}
    for i, ln in enumerate(lines):
        t = (getattr(ln, "text", "") or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln) or _is_technical_marker(ln):
            continue
        if _looks_like_instruction_text(t):
            continue
        if not _has_letter(t):
            continue
        if len(t) < 2 or len(t) > 90:
            continue
        xb = int(round(ln.x0 / 18.0))
        lane_counts[xb] = lane_counts.get(xb, 0) + 1
        lane_ymin[xb] = min(lane_ymin.get(xb, ln.y0), ln.y0)
        lane_ymax[xb] = max(lane_ymax.get(xb, ln.y0), ln.y0)

    next_below = {}
    for pos, i in enumerate(idxs):
        ln = lines[i]
        if _looks_like_furniture(ln):
            continue
        if not (getattr(ln, "text", "") or "").strip():
            continue
        for pos2 in range(pos + 1, min(len(idxs), pos + 14)):
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
        if _looks_like_stray_bracket_artifact(t):
            continue

        if ln.x0 > 0.72 * page_w:
            continue

        # Avoid pure titles at top.
        if ln.y0 < 150 and (ln.size >= max(14.5, med_size + 4.4) or getattr(ln, "non_black", False)):
            continue

        if len(t) < 3 or len(t) > 70:
            continue
        if t.endswith("."):
            continue

        xb = int(round(ln.x0 / 18.0))
        # Dense single-lane lists are rarely standalone textboxes.
        if lane_counts.get(xb, 0) >= 8 and (lane_ymax.get(xb, 0.0) - lane_ymin.get(xb, 0.0)) > 220:
            continue

        j = next_below.get(i)
        if j is None:
            continue
        ln2 = lines[j]
        gap = ln2.y0 - ln.y0
        if gap < 26:
            continue

        if gap < 58 and abs(ln2.x0 - ln.x0) <= 48:
            continue

        # Extra: the "blank area" hypothesis is stronger if the label is fairly wide.
        if (ln.x1 - ln.x0) < 0.18 * page_w and not t.endswith(":"):
            continue

        # Avoid labels that are immediately followed by obvious option stacks.
        if any(
            (k in option_stack_idx)
            and (0 < (lines[k].y0 - ln.y0) < 220)
            and (abs(lines[k].x0 - ln.x0) < 140)
            for k in range(len(lines))
        ):
            continue

        out.append(t)

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
