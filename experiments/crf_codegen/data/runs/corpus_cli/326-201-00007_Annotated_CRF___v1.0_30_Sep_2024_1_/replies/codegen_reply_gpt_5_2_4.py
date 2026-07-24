```python
import re
from typing import Any, Dict, List, Optional, Tuple


_WS_RE = re.compile(r"\s+")
_ACT_HDR_RE = re.compile(r"#\s*\d+\b")
_OPT_RE = re.compile(r"^\s*[Oo]\s+")
_CODE_RE = re.compile(r"^\s*\[.*\]\s*$")
_SAS_HINT_RE = re.compile(r"\bSAS:\[", re.IGNORECASE)

_PAREN_LIMIT_HINT_RE = re.compile(
    r"^\(\s*\d+\s*char(?:s)?\.?\s*max\.?\s*\)\s*\.?\s*$", re.IGNORECASE
)


def _norm_space(s: str) -> str:
    return _WS_RE.sub(" ", s).strip()


def _has_letter(s: str) -> bool:
    for ch in s:
        if ch.isalpha():
            return True
    return False


def _word_count(s: str) -> int:
    return len([w for w in _norm_space(s).split(" ") if w])


def _is_code_line_text(t: str) -> bool:
    if not t:
        return False
    if _SAS_HINT_RE.search(t):
        return True
    if _CODE_RE.match(t) and ("SAS" in t or "Name=" in t or "Length=" in t or "DataType=" in t):
        return True
    if t.lstrip().startswith("[") and ("SAS" in t or "Name=" in t or "DataType=" in t):
        return True
    return False


def _is_parenthetical_limit_hint(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    if _PAREN_LIMIT_HINT_RE.match(t):
        return True
    return False


def _clean_field_label(t: str) -> str:
    s = (t or "").strip()
    if not s:
        return ""
    s = re.sub(r"_+", " ", s)
    s = _norm_space(s)

    # Drop tokens that are only punctuation-ish.
    toks = []
    for tok in s.split(" "):
        if tok and all(ch in "-:./;," for ch in tok):
            continue
        toks.append(tok)
    s = " ".join(toks).strip()

    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    s = s.strip(" ,;")
    return s


def _page_extents(lines) -> Tuple[float, float]:
    max_x = 0.0
    max_y = 0.0
    for ln in lines:
        if ln.x1 > max_x:
            max_x = float(ln.x1)
        if ln.y1 > max_y:
            max_y = float(ln.y1)
        if ln.y0 > max_y:
            max_y = float(ln.y0)
    return max_x, max_y


def _parse_form_name_from_activity_header(t: str) -> str:
    if ":" not in t:
        return ""
    left = t.split(":", 1)[0].strip()
    return left


def _is_footer_furniture_line(ln, max_y: float) -> bool:
    t = (ln.text or "").strip()
    if not t:
        return False
    # Very low band.
    if float(ln.y0) <= max_y - 65.0:
        return False
    has_digit = any(ch.isdigit() for ch in t)
    if not has_digit:
        return False
    tt = t.lower()
    if "page" in tt or ("date" in tt and has_digit) or ("printed" in tt and has_digit):
        return True
    return False


def _is_activity_header_line(ln, max_x: float, header_cut: float, footer_cut: float) -> bool:
    t = (ln.text or "").strip()
    if not t or ln.non_black or (not ln.bold):
        return False
    if float(ln.y0) < header_cut or float(ln.y0) > footer_cut:
        return False
    if float(ln.x0) < 0.14 * max_x or float(ln.x0) > 0.84 * max_x:
        return False
    if ":" not in t:
        return False
    if not _ACT_HDR_RE.search(t):
        return False
    return True


def _is_blue_colon_label(ln, header_cut: float, footer_cut: float) -> bool:
    t = (ln.text or "").strip()
    if not t:
        return False
    y0 = float(ln.y0)
    if y0 < header_cut or y0 > footer_cut:
        return False
    return bool(ln.non_black and ln.bold and t.endswith(":"))


def _looks_like_section_title_ln(ln, max_x: float, header_cut: float, footer_cut: float) -> bool:
    t = (ln.text or "").strip()
    if not t or _is_code_line_text(t) or "_" in t:
        return False
    y0 = float(ln.y0)
    if y0 < header_cut or y0 > footer_cut:
        return False
    if ln.non_black:
        return False
    if not ln.bold:
        return False
    if t.endswith(":"):
        return False
    if _ACT_HDR_RE.search(t) and ":" in t:
        return False
    if _word_count(t) <= 0:
        return False
    if _word_count(t) > 8 or len(t) > 55:
        return False

    x0 = float(ln.x0)
    x1 = float(ln.x1)
    span = max(0.0, x1 - x0)
    cx = (x0 + x1) / 2.0 if x1 > x0 else x0
    centerish = abs(cx - 0.5 * max_x) <= 0.16 * max_x
    wideish = span >= 0.34 * max_x
    return centerish or wideish


def _page_form_title(lines, max_x: float, header_band_y: float) -> str:
    best_t = ""
    best_score = -1e9

    for ln in lines:
        y0 = float(ln.y0)
        if y0 >= header_band_y:
            continue
        t = (ln.text or "").strip()
        if not t:
            continue
        if _is_code_line_text(t):
            continue
        if "_" in t:
            continue
        if t.endswith(":"):
            continue
        if _ACT_HDR_RE.search(t) and ":" in t:
            continue
        if not _has_letter(t):
            continue

        # Accept bold black, but also allow non-bold black if it looks like a centered title.
        if ln.non_black:
            continue

        x0 = float(ln.x0)
        x1 = float(ln.x1)
        if x1 <= x0:
            continue
        span = x1 - x0
        if span < 0.22 * max_x:
            continue

        cx = (x0 + x1) / 2.0
        center_bonus = 1.0 - min(1.0, abs(cx - 0.5 * max_x) / (0.5 * max_x + 1e-6))
        bold_bonus = 1.0 if ln.bold else 0.35

        # Prefer wide, centered, and closer to bottom of header band.
        score = (span / (max_x + 1e-6)) * 2.2 + center_bonus * 1.1 + (y0 / (header_band_y + 1e-6)) * 0.8
        score *= bold_bonus
        if score > best_score:
            best_score = score
            best_t = t

    return _norm_space(best_t)


def _group_rows(lines, y_tol: float) -> List[List[Any]]:
    items = sorted(lines, key=lambda l: (float(l.y0), float(l.x0)))
    rows: List[List[Any]] = []
    cur: List[Any] = []
    cur_y: Optional[float] = None

    for ln in items:
        y = float(ln.y0)
        if cur_y is None:
            cur = [ln]
            cur_y = y
            continue
        if abs(y - cur_y) <= y_tol:
            cur.append(ln)
        else:
            rows.append(sorted(cur, key=lambda l: float(l.x0)))
            cur = [ln]
            cur_y = y
    if cur:
        rows.append(sorted(cur, key=lambda l: float(l.x0)))
    return rows


def _merge_adjacent_text_tokens(row: List[Any], max_gap: float = 10.0) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ln in row:
        t = (ln.text or "").strip()
        if not t:
            continue
        if _is_code_line_text(t):
            # Keep as a token (as evidence), but do not merge into labels.
            out.append(
                {
                    "text": t,
                    "x0": float(ln.x0),
                    "x1": float(ln.x1),
                    "y0": float(ln.y0),
                    "y1": float(ln.y1),
                    "bold": bool(ln.bold),
                    "non_black": bool(ln.non_black),
                    "is_code": True,
                }
            )
            continue

        tok = {
            "text": t,
            "x0": float(ln.x0),
            "x1": float(ln.x1),
            "y0": float(ln.y0),
            "y1": float(ln.y1),
            "bold": bool(ln.bold),
            "non_black": bool(ln.non_black),
            "is_code": False,
        }

        if not out:
            out.append(tok)
            continue

        prev = out[-1]
        # Only merge non-code, same-ish style, both black-ish, and close.
        if (
            (not prev["is_code"])
            and (not tok["is_code"])
            and (prev["non_black"] == tok["non_black"])
            and (prev["bold"] == tok["bold"])
        ):
            gap = tok["x0"] - prev["x1"]
            if 0.0 <= gap <= max_gap:
                prev["text"] = _norm_space(prev["text"] + " " + tok["text"])
                prev["x1"] = max(prev["x1"], tok["x1"])
                prev["y1"] = max(prev["y1"], tok["y1"])
                continue

        out.append(tok)

    return out


def _is_underscore_token_text(t: str) -> bool:
    s = (t or "").strip()
    if not s:
        return False
    return "_" in s


def _is_placeholderish_token_text(t: str) -> bool:
    s = (t or "").strip()
    if not s:
        return False
    # Underscore groups are primary; keep hook for odd OCR that drops underscores.
    if "_" in s:
        return True
    # Rare: sequences like "...." / "__:__" already caught. Do not treat "##.0" as placeholder by itself.
    return False


def _row_has_entry_evidence(tokens: List[Dict[str, Any]], x_after: float) -> bool:
    for tok in tokens:
        if tok["is_code"]:
            continue
        if tok["x0"] < x_after:
            continue
        tt = tok["text"]
        if not tt:
            continue
        if _OPT_RE.match(tt):
            return True
        if _is_placeholderish_token_text(tt):
            return True
        # Light evidence: short numeric mask blocks in parens tend to appear near entry fields.
        if tt.strip().startswith("(") and tt.strip().endswith(")") and any(ch.isdigit() for ch in tt) and _has_letter(tt):
            return True
    return False


def _right_region_evidence(
    anchor_ln,
    block_lines,
    max_x: float,
    y_window: float,
) -> Tuple[int, int, int, int]:
    """
    Returns (evidence_cnt, option_cnt, underscore_cnt, code_cnt) in a region below anchor.
    """
    y0 = float(anchor_ln.y0)
    y1 = y0 + y_window

    # Relaxed x gate: answers often start slightly to the right, not necessarily beyond x1.
    x_min = float(anchor_ln.x0) + 0.06 * max_x

    evidence_cnt = 0
    option_cnt = 0
    underscore_cnt = 0
    code_cnt = 0

    for ln in block_lines:
        yy = float(ln.y0)
        if yy <= y0 or yy > y1:
            continue
        if float(ln.x0) < x_min:
            continue
        t = (ln.text or "").strip()
        if not t:
            continue
        if _is_code_line_text(t):
            code_cnt += 1
            evidence_cnt += 1
            continue
        if ln.non_black and ln.bold and t.endswith(":"):
            continue
        if _OPT_RE.match(t):
            option_cnt += 1
            evidence_cnt += 1
            continue
        if "_" in t:
            underscore_cnt += 1
            evidence_cnt += 1
            continue
        if _CODE_RE.match(t):
            evidence_cnt += 1
            continue
        if _has_letter(t) or any(ch.isdigit() for ch in t):
            evidence_cnt += 1

    return evidence_cnt, option_cnt, underscore_cnt, code_cnt


def _is_answer_header_like(lbl_ln, block_lines, max_x: float) -> bool:
    # Blue bold label ending with ':', followed by answer-like evidence to the right/below.
    if not lbl_ln.non_black or not lbl_ln.bold:
        return False
    t = (lbl_ln.text or "").strip()
    if not t.endswith(":"):
        return False

    ev, opt, us, code = _right_region_evidence(lbl_ln, block_lines, max_x=max_x, y_window=150.0)
    if opt >= 1:
        return True
    if us >= 2:
        return True
    if ev >= 4:
        return True
    # If there's explicit coding evidence attached, it's almost certainly a header for an answer region.
    if code >= 1 and ev >= 2:
        return True
    return False


def _has_right_side_entry(lbl_ln, block_lines, max_x: float) -> bool:
    ev, opt, us, code = _right_region_evidence(lbl_ln, block_lines, max_x=max_x, y_window=70.0)
    return (us >= 1) or (opt >= 1) or (code >= 1) or (ev >= 2)


def _first_question_span(
    block_lines,
    activity_x: float,
    x_tol: float,
    header_cut: float,
    footer_cut: float,
) -> Tuple[str, Optional[float], Optional[float]]:
    best: List[str] = []
    started = False
    last_y: Optional[float] = None
    start_y: Optional[float] = None

    for ln in block_lines:
        y0 = float(ln.y0)
        if y0 < header_cut or y0 > footer_cut:
            continue

        if _is_blue_colon_label(ln, header_cut, footer_cut):
            if started:
                break
            continue

        t = (ln.text or "").strip()
        if not t or _is_code_line_text(t):
            continue
        if _is_parenthetical_limit_hint(t):
            if started:
                break
            continue

        # Avoid picking up obvious section titles as a "question".
        if _looks_like_section_title_ln(ln, max_x=1e9, header_cut=-1e9, footer_cut=1e9):
            if started:
                break
            continue

        near_x = abs(float(ln.x0) - activity_x) <= x_tol
        is_black = (not ln.non_black)

        # Instruction-ish short sentences are commonly not the field label (e.g., "Update ... .").
        if started and is_black and (not ln.bold) and t.endswith(".") and ("?" not in t) and _word_count(t) <= 10:
            break

        not_activity_hdr = (":" not in t) or (not _ACT_HDR_RE.search(t))
        looks_like_question_line = is_black and near_x and not_activity_hdr

        if not started:
            if looks_like_question_line and (ln.bold or len(t) >= 10):
                started = True
                best.append(t)
                last_y = y0
                start_y = y0
        else:
            if last_y is None:
                break
            dy = y0 - last_y
            cont_near_x = abs(float(ln.x0) - activity_x) <= (x_tol * 1.6)
            if is_black and cont_near_x and dy <= 34.0 and not _is_blue_colon_label(ln, header_cut, footer_cut):
                if _is_parenthetical_limit_hint(t):
                    break
                best.append(t)
                last_y = y0
            else:
                break

    return _norm_space(" ".join(best)), start_y, last_y


def _question_has_entry_evidence(
    block_lines,
    q_end_y: float,
    activity_x: float,
    max_x: float,
    header_cut: float,
    footer_cut: float,
) -> bool:
    if q_end_y is None:
        return False
    y_stop = min(footer_cut, q_end_y + 190.0)
    x_min = float(activity_x) + 0.08 * max_x
    ev = 0
    for ln in block_lines:
        y0 = float(ln.y0)
        if y0 <= q_end_y or y0 > y_stop:
            continue
        if float(ln.x0) < x_min:
            continue
        t = (ln.text or "").strip()
        if not t:
            continue
        if _is_code_line_text(t):
            return True
        if _OPT_RE.match(t) or "_" in t or _CODE_RE.match(t):
            return True
        # Weak evidence: some numeric masks in parentheses appear next to entry slots.
        if t.startswith("(") and t.endswith(")") and any(ch.isdigit() for ch in t):
            ev += 1
            if ev >= 2:
                return True
    return False


def _extract_row_entry_fields(
    rows: List[List[Any]],
    max_x: float,
    header_cut: float,
    footer_cut: float,
) -> List[Tuple[str, float, float, bool, bool]]:
    """
    Returns list of (field_label, x0_norm, y0_norm, bold, non_black) inferred from multi-field rows.
    """
    out: List[Tuple[str, float, float, bool, bool]] = []

    for row in rows:
        if not row:
            continue
        y0 = float(row[0].y0)
        if y0 < header_cut or y0 > footer_cut:
            continue

        toks = _merge_adjacent_text_tokens(row, max_gap=max(8.0, 0.012 * max_x))
        if not toks:
            continue

        # Identify anchors: lettery tokens that are followed soon by placeholder-ish tokens.
        anchors: List[int] = []
        for i, tok in enumerate(toks):
            if tok["is_code"]:
                continue
            tt = tok["text"]
            if not tt or _is_parenthetical_limit_hint(tt):
                continue
            if tok["non_black"] and tok["bold"] and tt.endswith(":"):
                # Blue labels handled elsewhere.
                continue
            if not _has_letter(tt):
                continue
            if _OPT_RE.match(tt):
                continue

            # Consider it an anchor if there's placeholder evidence to its right in the same row.
            x1 = tok["x1"]
            found_slot = False
            for j in range(i + 1, min(len(toks), i + 6)):
                tj = toks[j]
                if tj["is_code"]:
                    continue
                if tj["x0"] <= x1:
                    continue
                # Stop if we jump too far; next fields will be later anchors.
                if tj["x0"] - tok["x0"] > 0.55 * max_x:
                    break
                if _is_placeholderish_token_text(tj["text"]):
                    found_slot = True
                    break
            if found_slot:
                anchors.append(i)

            # Also allow colon-terminated black labels like "Barcode:" as anchors if they have evidence right of them.
            if (not found_slot) and tt.endswith(":") and (not tok["non_black"]):
                if _row_has_entry_evidence(toks, x_after=tok["x1"] + 1.0):
                    anchors.append(i)

        # De-dup anchors and ensure they are ordered.
        anchors = sorted(set(anchors))
        if not anchors:
            continue

        for k, idx in enumerate(anchors):
            end = anchors[k + 1] if (k + 1) < len(anchors) else len(toks)

            base = toks[idx]
            parts: List[str] = [base["text"]]

            # Include non-placeholder tail hints up to next anchor, skipping underscore-only tokens and code.
            for tok in toks[idx + 1 : end]:
                if tok["is_code"]:
                    continue
                tt = tok["text"]
                if not tt:
                    continue
                if _is_placeholderish_token_text(tt):
                    continue
                if _OPT_RE.match(tt):
                    continue
                if _is_parenthetical_limit_hint(tt):
                    continue
                # Avoid swallowing another obvious label without having recognized it as an anchor.
                if _has_letter(tt) and tt.endswith(":") and tok["non_black"] and tok["bold"]:
                    break
                parts.append(tt)

            label = _clean_field_label(_norm_space(" ".join(parts)))
            if not label or not _has_letter(label):
                continue
            # Drop absurdly short section headings accidentally caught.
            if _word_count(label) <= 2 and len(label) <= 18 and (not base["non_black"]) and base["bold"]:
                continue

            out.append(
                (
                    label,
                    min(0.999, max(0.0, base["x0"] / (max_x + 1e-6))),
                    min(0.999, max(0.0, base["y0"] / 1.0)),  # normalize later with max_y where needed
                    bool(base["bold"]),
                    bool(base["non_black"]),
                )
            )

    return out


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    # First pass: collect candidates with metadata for global furniture filtering.
    candidates: List[Dict[str, Any]] = []
    occ_by_label: Dict[str, List[Tuple[int, float, float]]] = {}  # label -> [(page, x0n, y0n)]

    pages_total = 0
    per_page_dims: Dict[int, Tuple[float, float]] = {}

    current_form = ""
    current_activity_x: Optional[float] = None

    for page_idx0, lines in pages:
        pages_total += 1
        if not lines:
            continue

        max_x, max_y = _page_extents(lines)
        per_page_dims[int(page_idx0)] = (max_x, max_y)
        if max_x <= 0 or max_y <= 0:
            continue

        # Relax header cut to avoid losing top-of-body fields; rely on structural title detection instead.
        header_cut = 0.12 * max_y + 3.0
        footer_cut = max_y - 32.0
        header_band_y = 0.20 * max_y + 6.0

        page_form_guess = _page_form_title(lines, max_x=max_x, header_band_y=header_band_y)

        body_lines = []
        for ln in lines:
            t = (ln.text or "").strip()
            if not t:
                continue
            y0 = float(ln.y0)
            if y0 > footer_cut:
                continue
            if _is_footer_furniture_line(ln, max_y=max_y):
                continue
            # Keep header-band lines too; downstream logic will ignore titles/headers structurally.
            body_lines.append(ln)

        if not body_lines:
            continue

        hdrs = [ln for ln in body_lines if _is_activity_header_line(ln, max_x, header_cut, footer_cut)]
        hdrs.sort(key=lambda l: (float(l.y0), float(l.x0)))

        first_hdr_form = ""
        if hdrs:
            first_hdr_form = _parse_form_name_from_activity_header(((hdrs[0].text or "").strip()))

        blocks: List[Tuple[Optional[Any], float, float]] = []
        if hdrs:
            first_y = float(hdrs[0].y0)
            if first_y - header_cut > 6.0:
                blocks.append((None, header_cut, first_y - 0.1))
            for i, h in enumerate(hdrs):
                y0 = float(h.y0) - 0.1
                y1 = footer_cut
                if i + 1 < len(hdrs):
                    y1 = float(hdrs[i + 1].y0) - 0.2
                blocks.append((h, y0, y1))
        else:
            blocks.append((None, header_cut, footer_cut))

        # Update persistent form: prefer explicit page title if confidently detected.
        if page_form_guess:
            # If page has no activity headers, the title is usually the governing form.
            if not hdrs:
                current_form = page_form_guess
            else:
                # With headers present, keep current_form unless title is clearly different and non-empty.
                if page_form_guess and page_form_guess != current_form:
                    current_form = current_form or page_form_guess

        local_seen = set()

        for hdr_ln, y0, y1 in blocks:
            block_lines = [ln for ln in body_lines if (float(ln.y0) >= y0 and float(ln.y0) <= y1)]
            if not block_lines:
                continue
            block_lines.sort(key=lambda l: (float(l.y0), float(l.x0)))

            block_form = current_form
            if hdr_ln is None:
                if first_hdr_form:
                    block_form = first_hdr_form
                    current_form = first_hdr_form
                elif page_form_guess:
                    block_form = page_form_guess
                    current_form = page_form_guess
            else:
                t = (hdr_ln.text or "").strip()
                fm = _parse_form_name_from_activity_header(t)
                if fm:
                    block_form = fm
                    current_form = fm

            activity_x = current_activity_x if current_activity_x is not None else (0.30 * max_x)
            if hdr_ln is not None:
                activity_x = float(hdr_ln.x0)
                current_activity_x = activity_x
            elif current_activity_x is not None:
                activity_x = current_activity_x

            x_tol = max(18.0, 0.050 * max_x)
            y_tol = max(2.4, 0.006 * max_y)

            # Section titles inside the block can define a tighter "form" than the outer activity header.
            section_titles = [ln for ln in block_lines if _looks_like_section_title_ln(ln, max_x=max_x, header_cut=header_cut, footer_cut=footer_cut)]
            section_titles.sort(key=lambda l: (float(l.y0), float(l.x0)))

            # Build section ranges.
            section_ranges: List[Tuple[float, float, str]] = []
            for i, st in enumerate(section_titles):
                st_y = float(st.y0)
                nxt_y = y1
                if i + 1 < len(section_titles):
                    nxt_y = float(section_titles[i + 1].y0) - 0.2
                txt = _norm_space((st.text or "").strip())
                if txt and _has_letter(txt):
                    section_ranges.append((st_y, nxt_y, txt))

            def active_form_for_y(yy: float) -> str:
                for sy0, sy1, stxt in section_ranges:
                    if yy >= sy0 and yy <= sy1:
                        # Use section title as the form_name when it looks like a real section.
                        return stxt
                return block_form or ""

            # Blue colon labels: classify answer header vs subfields.
            blue_labels = [ln for ln in block_lines if _is_blue_colon_label(ln, header_cut, footer_cut)]
            blue_labels.sort(key=lambda l: (float(l.y0), float(l.x0)))

            ans_hdr = None
            for ln in blue_labels:
                if _is_answer_header_like(ln, block_lines, max_x=max_x):
                    ans_hdr = ln
                    break

            # Emit blue labels that look like true fields (must have entry evidence).
            for ln in blue_labels:
                if ans_hdr is not None and ln is ans_hdr:
                    continue
                if not _has_right_side_entry(ln, block_lines, max_x=max_x):
                    continue
                lab = (ln.text or "").strip()
                if not lab or _is_code_line_text(lab) or _is_parenthetical_limit_hint(lab):
                    continue
                fn = _norm_space(lab)
                if not fn or not _has_letter(fn):
                    continue

                yy = float(ln.y0)
                fm = active_form_for_y(yy)
                key = (fm, fn, int(page_idx0))
                if key in local_seen:
                    continue
                local_seen.add(key)

                x0n = float(ln.x0) / (max_x + 1e-6)
                y0n = float(ln.y0) / (max_y + 1e-6)
                candidates.append(
                    {
                        "form_name": fm,
                        "field_name": fn,
                        "page": int(page_idx0) + 1,
                        "src_kind": "blue_label",
                        "x0n": x0n,
                        "y0n": y0n,
                        "bold": bool(ln.bold),
                        "non_black": bool(ln.non_black),
                    }
                )
                occ_by_label.setdefault(fn, []).append((int(page_idx0), x0n, y0n))

            # Row-based extraction for composite entry rows (Date/Time/Version/etc).
            rows = _group_rows(block_lines, y_tol=y_tol)
            row_fields = _extract_row_entry_fields(rows, max_x=max_x, header_cut=header_cut, footer_cut=footer_cut)
            for label, x0n_raw, y0n_raw, _b, _nb in row_fields:
                # Fix y normalization (the helper stores raw y0 in y0n slot).
                y0 = y0n_raw
                yy = float(y0)
                y0n = yy / (max_y + 1e-6)

                # Skip labels that are clearly answer headers or titles.
                if label.endswith(":"):
                    # If a colon label made it here, require that it not be blue (already handled).
                    pass
                if _is_parenthetical_limit_hint(label):
                    continue
                if not _has_letter(label):
                    continue

                fm = active_form_for_y(yy)
                key = (fm, label, int(page_idx0))
                if key in local_seen:
                    continue
                local_seen.add(key)

                candidates.append(
                    {
                        "form_name": fm,
                        "field_name": label,
                        "page": int(page_idx0) + 1,
                        "src_kind": "row_entry",
                        "x0n": min(0.999, max(0.0, x0n_raw)),
                        "y0n": min(0.999, max(0.0, y0n)),
                        "bold": False,
                        "non_black": False,
                    }
                )
                occ_by_label.setdefault(label, []).append((int(page_idx0), min(0.999, max(0.0, x0n_raw)), min(0.999, max(0.0, y0n))))

            # Question label (left/main column). Keep only if the block shows entry evidence nearby.
            q_label, q_start_y, q_end_y = _first_question_span(block_lines, activity_x, x_tol, header_cut, footer_cut)
            if q_label and q_end_y is not None:
                # Clean and ensure it isn't accidentally a section title.
                q_label2 = _clean_field_label(q_label)
                if q_label2 and _has_letter(q_label2) and (not _is_parenthetical_limit_hint(q_label2)):
                    if _question_has_entry_evidence(block_lines, q_end_y, activity_x=activity_x, max_x=max_x, header_cut=header_cut, footer_cut=footer_cut):
                        # Reject short bold centered headings: these should become form_name, not field_name.
                        # (If it is actually a field label, it should have evidence and usually isn't centered-wide.)
                        fm = active_form_for_y(float(q_start_y or q_end_y))
                        key = (fm, q_label2, int(page_idx0))
                        if key not in local_seen:
                            local_seen.add(key)
                            x0n = float(activity_x) / (max_x + 1e-6)
                            y0n = float(q_start_y or q_end_y) / (max_y + 1e-6)
                            candidates.append(
                                {
                                    "form_name": fm,
                                    "field_name": q_label2,
                                    "page": int(page_idx0) + 1,
                                    "src_kind": "question",
                                    "x0n": min(0.999, max(0.0, x0n)),
                                    "y0n": min(0.999, max(0.0, y0n)),
                                    "bold": False,
                                    "non_black": False,
                                }
                            )
                            occ_by_label.setdefault(q_label2, []).append((int(page_idx0), min(0.999, max(0.0, x0n)), min(0.999, max(0.0, y0n))))

    # Second pass: global furniture filtering by recurrence + position clustering.
    # Drop labels that recur on >=70% of pages in a tight, template-like position band.
    def _mean(vals: List[float]) -> float:
        return sum(vals) / max(1, len(vals))

    def _std(vals: List[float]) -> float:
        if len(vals) <= 1:
            return 0.0
        m = _mean(vals)
        return (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5

    pages_total_nonzero = max(1, pages_total)
    drop_labels = set()
    for lbl, occ in occ_by_label.items():
        page_set = {p for (p, _, _) in occ}
        frac = len(page_set) / pages_total_nonzero
        if frac < 0.70:
            continue

        xs = [x for (_, x, _) in occ]
        ys = [y for (_, _, y) in occ]
        x_sd = _std(xs)
        y_sd = _std(ys)
        y_med = sorted(ys)[len(ys) // 2] if ys else 0.5

        # Template furniture tends to be in a stable spot and near top/bottom.
        # (This generalizes beyond literal strings like "Comment:" / "Staff Initials:".)
        if x_sd <= 0.035 and y_sd <= 0.055 and (y_med <= 0.28 or y_med >= 0.72):
            drop_labels.add(lbl)

    # Third pass: finalize, with de-dup and additional structural cleanup.
    results: List[Dict[str, Any]] = []
    seen = set()

    for c in candidates:
        fn = _norm_space(c["field_name"])
        fm = _norm_space(c["form_name"])
        pg = int(c["page"])

        if not fn or not _has_letter(fn) or _is_code_line_text(fn):
            continue
        if _is_parenthetical_limit_hint(fn):
            continue

        # Never output answer headers (if they slipped through).
        if fn.endswith(":") and c.get("src_kind") == "blue_label":
            # If it's highly likely to be template furniture, drop.
            if fn in drop_labels:
                continue

        # Drop section titles accidentally emitted as fields.
        if _word_count(fn) <= 3 and len(fn) <= 20:
            # If it appears bold black and centered-ish on many pages, it's likely a section header/furniture.
            if fn in drop_labels:
                continue

        key = (fm, fn, pg)
        if key in seen:
            continue
        seen.add(key)

        results.append({"form_name": fm, "field_name": fn, "page": pg})

    return results
```
