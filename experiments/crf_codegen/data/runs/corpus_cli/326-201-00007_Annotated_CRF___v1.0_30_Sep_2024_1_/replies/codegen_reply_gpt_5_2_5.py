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

# Parenthetical masks like "(dd-MMM-yyyy)", "(HH:mm)", "(##.0)", "(####)" etc.
_MASK_PAREN_RE = re.compile(r"\(\s*[0-9#:\.\-\/\s]*[dmyhsaapDMyHSAAP#0:\.\-\/\s]+\s*\)", re.IGNORECASE)

# Placeholder-ish runs: underscores and common OCR variants.
_US_RUN_RE = re.compile(r"(?:_{2,}|(?:\s_){2,}|(?:\s*[_·•]\s*){6,})")
# Mask runs like "####", "##0", "##.0" etc outside parentheses.
_HASH_MASK_RE = re.compile(r"(?:#){2,}[0#\.]*")

_NONLABEL_CODE_TOKENS = ("Name=", "Length=", "DataType=")


def _norm_space(s: str) -> str:
    return _WS_RE.sub(" ", s or "").strip()


def _has_letter(s: str) -> bool:
    s = s or ""
    return any(ch.isalpha() for ch in s)


def _word_count(s: str) -> int:
    return len([w for w in _norm_space(s).split(" ") if w])


def _is_code_line_text(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return False
    if _SAS_HINT_RE.search(t):
        return True
    if _CODE_RE.match(t) and ("SAS" in t or any(k in t for k in _NONLABEL_CODE_TOKENS)):
        return True
    if t.lstrip().startswith("[") and ("SAS" in t or any(k in t for k in _NONLABEL_CODE_TOKENS) or "DataType=" in t):
        return True
    return False


def _is_parenthetical_limit_hint(t: str) -> bool:
    t = (t or "").strip()
    return bool(t and _PAREN_LIMIT_HINT_RE.match(t))


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
    t = (t or "").strip()
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
    if not t:
        return False
    if _is_code_line_text(t) or "_" in t:
        return False
    y0 = float(ln.y0)
    if y0 < header_cut or y0 > footer_cut:
        return False
    if ln.non_black:
        return False
    if not ln.bold:
        return False
    if t.endswith(":") or t.endswith(".") or "?" in t:
        return False
    if _ACT_HDR_RE.search(t) and ":" in t:
        return False
    wc = _word_count(t)
    if wc <= 0:
        return False
    # Titles are usually short.
    if wc > 10 or len(t) > 60:
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
        if _is_code_line_text(t) or "_" in t:
            continue
        if t.endswith(":") or t.endswith(".") or "?" in t:
            continue
        if _ACT_HDR_RE.search(t) and ":" in t:
            continue
        if not _has_letter(t):
            continue
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

        is_code = _is_code_line_text(t)
        tok = {
            "text": t,
            "x0": float(ln.x0),
            "x1": float(ln.x1),
            "y0": float(ln.y0),
            "y1": float(ln.y1),
            "bold": bool(ln.bold),
            "non_black": bool(ln.non_black),
            "is_code": bool(is_code),
        }

        if not out:
            out.append(tok)
            continue

        prev = out[-1]
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


def _strip_mask_parens(s: str) -> str:
    s = s or ""
    s = _MASK_PAREN_RE.sub("", s)
    return s


def _strip_limit_parens(s: str) -> str:
    s = s or ""
    # Remove limit hints embedded anywhere: "(200 char. max.)", "(100 chars max.)"
    s = re.sub(r"\(\s*\d+\s*char(?:s)?\.?\s*max\.?\s*\)", "", s, flags=re.IGNORECASE)
    return s


def _strip_placeholders_inline(s: str) -> str:
    s = s or ""
    s = _strip_mask_parens(s)
    s = _strip_limit_parens(s)
    s = _US_RUN_RE.sub(" ", s)
    s = _HASH_MASK_RE.sub(" ", s)
    # Collapse sequences like " _  _ " that OCR splits
    s = re.sub(r"(?:\s+_\s+){1,}", " ", s)
    return s


def _clean_field_label(t: str) -> str:
    s = (t or "").strip()
    if not s:
        return ""
    s = _strip_placeholders_inline(s)
    s = re.sub(r"_+", " ", s)
    s = _norm_space(s)

    toks: List[str] = []
    for tok in s.split(" "):
        if not tok:
            continue
        if all(ch in "-:./;," for ch in tok):
            # Keep common in-between separators if they occur alone.
            if tok in ("/", "-"):
                toks.append(tok)
            else:
                continue
        else:
            toks.append(tok)

    s = _norm_space(" ".join(toks))
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    s = s.strip(" ,;")

    # Normalize " / " to "/" for compactness.
    s = s.replace(" / ", " / ")
    return s


def _text_has_inline_placeholder(s: str) -> bool:
    s = (s or "").strip()
    if not s or not _has_letter(s):
        return False
    if "_" in s:
        return True
    if _HASH_MASK_RE.search(s):
        return True
    if _MASK_PAREN_RE.search(s):
        return True
    if _US_RUN_RE.search(s):
        return True
    return False


def _right_region_evidence(
    anchor_ln,
    block_lines,
    max_x: float,
    y_window: float,
    x_min_override: Optional[float] = None,
) -> Tuple[int, int, int, int]:
    """
    Returns (evidence_cnt, option_cnt, underscore_cnt, code_cnt) in a region below/right of anchor.
    """
    y0 = float(anchor_ln.y0)
    y1 = y0 + y_window

    # Default: to the right of anchor, but do not over-gate; answer regions often start near x0.
    x_min = float(anchor_ln.x0) if x_min_override is None else float(x_min_override)

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

        # Skip other blue headers while scoring evidence.
        if ln.non_black and ln.bold and t.endswith(":"):
            continue

        if _OPT_RE.match(t):
            option_cnt += 1
            evidence_cnt += 1
            continue

        if "_" in t or _US_RUN_RE.search(t):
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
    # Blue bold label ending with ':', followed by answer-like evidence nearby.
    if not lbl_ln.non_black or not lbl_ln.bold:
        return False
    t = (lbl_ln.text or "").strip()
    if not t.endswith(":"):
        return False

    # Evidence in a broader nearby region (below), allowing x close to x0.
    ev, opt, us, code = _right_region_evidence(lbl_ln, block_lines, max_x=max_x, y_window=180.0, x_min_override=float(lbl_ln.x0) - 0.01 * max_x)
    if opt >= 1:
        return True
    if us >= 2:
        return True
    if code >= 1 and ev >= 2:
        return True
    # Many non-empty items in the region is usually an answer bucket header.
    if ev >= 5:
        return True
    return False


def _has_right_side_entry(lbl_ln, block_lines, max_x: float) -> bool:
    # Entry evidence near the label, not necessarily strictly to the right (wraps/columns vary).
    ev, opt, us, code = _right_region_evidence(lbl_ln, block_lines, max_x=max_x, y_window=85.0, x_min_override=float(lbl_ln.x0) - 0.01 * max_x)
    return (us >= 1) or (opt >= 1) or (code >= 1) or (ev >= 2)


def _question_entry_evidence_anywhere(
    block_lines,
    q_end_y: float,
    activity_x: float,
    max_x: float,
    header_cut: float,
    footer_cut: float,
) -> bool:
    if q_end_y is None:
        return False

    y_stop = min(footer_cut, q_end_y + 220.0)
    x_min = float(activity_x) + 0.02 * max_x
    ev = 0

    for ln in block_lines:
        y0 = float(ln.y0)
        if y0 <= q_end_y or y0 > y_stop:
            continue

        # Evidence usually appears in the answer column(s) to the right.
        if float(ln.x0) < x_min:
            continue

        t = (ln.text or "").strip()
        if not t:
            continue

        if _is_code_line_text(t):
            return True
        if _OPT_RE.match(t):
            return True
        if "_" in t or _US_RUN_RE.search(t):
            return True
        if _CODE_RE.match(t):
            return True
        if _text_has_inline_placeholder(t):
            return True

        # Weak evidence: repeated numeric-ish tokens close by.
        if any(ch.isdigit() for ch in t):
            ev += 1
            if ev >= 2:
                return True

    return False


def _multiline_left_label(
    block_lines: List[Any],
    start_i: int,
    activity_x: float,
    max_x: float,
    header_cut: float,
    footer_cut: float,
) -> Tuple[str, int, float, float]:
    """
    Collect a multi-line left-column label starting at start_i.
    Returns (label_text, next_index, start_y, end_y)
    """
    first = block_lines[start_i]
    start_y = float(first.y0)
    parts: List[str] = []
    last_y = start_y
    i = start_i

    # Wrap/indent allowance.
    x_left = float(activity_x) - max(18.0, 0.05 * max_x)
    x_right = float(activity_x) + 0.24 * max_x

    while i < len(block_lines):
        ln = block_lines[i]
        y0 = float(ln.y0)
        if y0 < header_cut or y0 > footer_cut:
            break

        # Stop if we hit a new blue label line.
        if _is_blue_colon_label(ln, header_cut, footer_cut):
            break

        t = (ln.text or "").strip()
        if not t:
            i += 1
            continue
        if _is_code_line_text(t):
            break
        if _is_parenthetical_limit_hint(t):
            # Limit-only hint line is not a label continuation.
            break

        # Don't swallow headings as labels.
        if _looks_like_section_title_ln(ln, max_x=max_x, header_cut=header_cut, footer_cut=footer_cut):
            if parts:
                break
            return "", start_i + 1, start_y, start_y

        # Geometric continuation gate.
        dy = y0 - last_y
        if parts and dy > 46.0:
            break

        x0 = float(ln.x0)
        if x0 < x_left:
            if parts:
                break
            else:
                return "", start_i + 1, start_y, start_y
        if x0 > x_right:
            if parts:
                break
            else:
                return "", start_i + 1, start_y, start_y

        # If we already started and the next line looks like a short instruction sentence, stop.
        if parts and (not ln.bold) and (not ln.non_black) and t.endswith(".") and ("?" not in t) and _word_count(t) <= 10:
            break

        parts.append(t)
        last_y = y0
        i += 1

        # Stop once we hit a clear question mark end and next line is far away (handled by dy gate).
        # (No extra logic needed.)

    lbl = _clean_field_label(_norm_space(" ".join(parts)))
    if not lbl or not _has_letter(lbl):
        return "", i, start_y, last_y
    return lbl, i, start_y, last_y


def _extract_row_entry_fields(
    rows: List[List[Any]],
    max_x: float,
    header_cut: float,
    footer_cut: float,
) -> List[Tuple[str, float, float]]:
    """
    Row-based anchors for composite entry rows (Date/Time/Version/etc).
    Returns list of (field_label, x0_norm, y0_raw)
    """
    out: List[Tuple[str, float, float]] = []

    for row in rows:
        if not row:
            continue
        y0 = float(row[0].y0)
        if y0 < header_cut or y0 > footer_cut:
            continue

        toks = _merge_adjacent_text_tokens(row, max_gap=max(8.0, 0.012 * max_x))
        if not toks:
            continue

        anchors: List[int] = []
        for i, tok in enumerate(toks):
            if tok["is_code"]:
                continue
            tt = tok["text"]
            if not tt or _is_parenthetical_limit_hint(tt):
                continue
            if tok["non_black"] and tok["bold"] and tt.endswith(":"):
                continue
            if not _has_letter(tt):
                continue
            if _OPT_RE.match(tt):
                continue

            # Inline placeholder in the same token: accept as a direct field label.
            if _text_has_inline_placeholder(tt):
                anchors.append(i)
                continue

            # Otherwise: look for placeholder evidence to the right in same row.
            x1 = tok["x1"]
            found_slot = False
            for j in range(i + 1, min(len(toks), i + 7)):
                tj = toks[j]
                if tj["is_code"]:
                    continue
                if tj["x0"] <= x1:
                    continue
                if tj["x0"] - tok["x0"] > 0.58 * max_x:
                    break
                if _text_has_inline_placeholder(tj["text"]):
                    found_slot = True
                    break
                if "_" in tj["text"] or _US_RUN_RE.search(tj["text"]):
                    found_slot = True
                    break
            if found_slot:
                anchors.append(i)

            # Also allow black colon labels as anchors if they have evidence to the right in the row.
            if (not found_slot) and tt.endswith(":") and (not tok["non_black"]):
                # Any underscore/mask token to the right
                for j in range(i + 1, min(len(toks), i + 7)):
                    tj = toks[j]
                    if tj["is_code"]:
                        continue
                    if tj["x0"] <= tok["x1"]:
                        continue
                    if _text_has_inline_placeholder(tj["text"]) or _OPT_RE.match(tj["text"]) or "_" in tj["text"]:
                        anchors.append(i)
                        break

        anchors = sorted(set(anchors))
        if not anchors:
            continue

        for k, idx in enumerate(anchors):
            end = anchors[k + 1] if (k + 1) < len(anchors) else len(toks)
            base = toks[idx]

            # Build a label: keep adjacent non-placeholder descriptor tokens that are close, but do not eat the answer slots.
            parts: List[str] = [base["text"]]
            for tok in toks[idx + 1 : end]:
                if tok["is_code"]:
                    continue
                tt = tok["text"]
                if not tt:
                    continue
                if _OPT_RE.match(tt):
                    continue
                if _is_parenthetical_limit_hint(tt):
                    continue
                if _text_has_inline_placeholder(tt) or "_" in tt or _US_RUN_RE.search(tt):
                    continue
                # Avoid swallowing a blue label.
                if tok["non_black"] and tok["bold"] and tt.endswith(":"):
                    break
                parts.append(tt)

            label = _clean_field_label(_norm_space(" ".join(parts)))
            if not label or not _has_letter(label):
                continue
            if _looks_like_section_title_ln(
                type("Tmp", (), {"text": label, "x0": base["x0"], "x1": base["x1"], "y0": base["y0"], "y1": base["y1"], "bold": base["bold"], "non_black": base["non_black"]}),
                max_x=max_x,
                header_cut=header_cut,
                footer_cut=footer_cut,
            ):
                continue

            out.append(
                (
                    label,
                    min(0.999, max(0.0, base["x0"] / (max_x + 1e-6))),
                    float(base["y0"]),
                )
            )

    return out


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    # label -> [(page0, x0n, y0n, entryish)]
    occ_by_label: Dict[str, List[Tuple[int, float, float, bool]]] = {}

    pages_total = 0
    current_form = ""
    current_activity_x: Optional[float] = None

    for page_idx0, lines in pages:
        pages_total += 1
        if not lines:
            continue

        max_x, max_y = _page_extents(lines)
        if max_x <= 0 or max_y <= 0:
            continue

        header_cut = 0.12 * max_y + 3.0
        footer_cut = max_y - 32.0
        header_band_y = 0.20 * max_y + 6.0

        page_form_guess = _page_form_title(lines, max_x=max_x, header_band_y=header_band_y)

        body_lines: List[Any] = []
        for ln in lines:
            t = (ln.text or "").strip()
            if not t:
                continue
            y0 = float(ln.y0)
            if y0 > footer_cut:
                continue
            if _is_footer_furniture_line(ln, max_y=max_y):
                continue
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

        # Maintain current form using printed page title when appropriate.
        if page_form_guess and not hdrs:
            current_form = page_form_guess or current_form

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

            y_tol = max(2.4, 0.006 * max_y)

            # Section titles define form_name within the block.
            section_titles = [
                ln
                for ln in block_lines
                if _looks_like_section_title_ln(ln, max_x=max_x, header_cut=header_cut, footer_cut=footer_cut)
            ]
            section_titles.sort(key=lambda l: (float(l.y0), float(l.x0)))

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
                        return stxt
                return block_form or ""

            # Blue colon labels: keep as fields broadly, but never treat answer headers as fields.
            blue_labels = [ln for ln in block_lines if _is_blue_colon_label(ln, header_cut, footer_cut)]
            blue_labels.sort(key=lambda l: (float(l.y0), float(l.x0)))

            for ln in blue_labels:
                if _is_answer_header_like(ln, block_lines, max_x=max_x):
                    continue

                lab = (ln.text or "").strip()
                if not lab or _is_code_line_text(lab) or _is_parenthetical_limit_hint(lab):
                    continue

                fn = _clean_field_label(lab)
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
                entryish = _has_right_side_entry(ln, block_lines, max_x=max_x)

                candidates.append(
                    {
                        "form_name": fm,
                        "field_name": fn,
                        "page": int(page_idx0) + 1,
                        "src_kind": "blue_label",
                        "x0n": x0n,
                        "y0n": y0n,
                        "entryish": bool(entryish),
                    }
                )
                occ_by_label.setdefault(fn, []).append((int(page_idx0), x0n, y0n, bool(entryish)))

            # Row-based extraction for composite entry rows and inline placeholder labels.
            rows = _group_rows(block_lines, y_tol=y_tol)

            # 1) Anchor-based row entry fields.
            row_fields = _extract_row_entry_fields(rows, max_x=max_x, header_cut=header_cut, footer_cut=footer_cut)
            for label, x0n_raw, y0_raw in row_fields:
                if not label or not _has_letter(label) or _is_parenthetical_limit_hint(label):
                    continue

                yy = float(y0_raw)
                fm = active_form_for_y(yy)

                key = (fm, label, int(page_idx0))
                if key in local_seen:
                    continue
                local_seen.add(key)

                y0n = yy / (max_y + 1e-6)
                candidates.append(
                    {
                        "form_name": fm,
                        "field_name": label,
                        "page": int(page_idx0) + 1,
                        "src_kind": "row_entry",
                        "x0n": min(0.999, max(0.0, x0n_raw)),
                        "y0n": min(0.999, max(0.0, y0n)),
                        "entryish": True,
                    }
                )
                occ_by_label.setdefault(label, []).append((int(page_idx0), min(0.999, max(0.0, x0n_raw)), min(0.999, max(0.0, y0n)), True))

            # 2) Inline placeholder labels anywhere in rows (e.g., "Date __-___-____ (dd-MMM-yyyy)").
            for row in rows:
                toks = _merge_adjacent_text_tokens(row, max_gap=max(8.0, 0.012 * max_x))
                for tok in toks:
                    if tok["is_code"]:
                        continue
                    raw = tok["text"]
                    if not raw or not _text_has_inline_placeholder(raw):
                        continue
                    # Avoid treating answer option clusters as field labels.
                    if _OPT_RE.match(raw):
                        continue
                    # Don't treat obvious section titles as fields even if OCR adds underscores.
                    if tok["bold"] and (not tok["non_black"]) and ("?" not in raw) and (not raw.endswith(":")):
                        # Still allow, but only if it's not centered-wide.
                        # (Use a conservative title test on the original line-like token.)
                        pass

                    label = _clean_field_label(raw)
                    if not label or not _has_letter(label):
                        continue
                    if _is_parenthetical_limit_hint(label):
                        continue

                    # Reject tiny labels that are likely artifacts.
                    if _word_count(label) <= 1 and len(label) <= 3:
                        continue

                    yy = float(tok["y0"])
                    fm = active_form_for_y(yy)
                    key = (fm, label, int(page_idx0))
                    if key in local_seen:
                        continue
                    local_seen.add(key)

                    x0n = float(tok["x0"]) / (max_x + 1e-6)
                    y0n = yy / (max_y + 1e-6)
                    candidates.append(
                        {
                            "form_name": fm,
                            "field_name": label,
                            "page": int(page_idx0) + 1,
                            "src_kind": "inline_placeholder",
                            "x0n": min(0.999, max(0.0, x0n)),
                            "y0n": min(0.999, max(0.0, y0n)),
                            "entryish": True,
                        }
                    )
                    occ_by_label.setdefault(label, []).append((int(page_idx0), min(0.999, max(0.0, x0n)), min(0.999, max(0.0, y0n)), True))

            # Left-column (question/instruction) labels with entry evidence.
            i = 0
            x_tol = max(18.0, 0.05 * max_x)
            while i < len(block_lines):
                ln = block_lines[i]
                ycur = float(ln.y0)
                if ycur < header_cut or ycur > footer_cut:
                    i += 1
                    continue

                # Skip blue labels and activity headers.
                if _is_blue_colon_label(ln, header_cut, footer_cut) or _is_activity_header_line(ln, max_x, header_cut, footer_cut):
                    i += 1
                    continue

                t = (ln.text or "").strip()
                if not t or _is_code_line_text(t) or _is_parenthetical_limit_hint(t):
                    i += 1
                    continue

                # Avoid section titles.
                if _looks_like_section_title_ln(ln, max_x=max_x, header_cut=header_cut, footer_cut=footer_cut):
                    i += 1
                    continue

                # Start gate: left-ish and black-ish.
                is_black = not ln.non_black
                near_x = abs(float(ln.x0) - float(activity_x)) <= x_tol
                if not (is_black and near_x and (_has_letter(t))):
                    i += 1
                    continue

                # Build a multiline label from here.
                lbl, next_i, start_y, end_y = _multiline_left_label(
                    block_lines, i, activity_x=float(activity_x), max_x=max_x, header_cut=header_cut, footer_cut=footer_cut
                )
                if not lbl:
                    i = max(i + 1, next_i)
                    continue

                # Do not accept labels that are actually section titles after normalization.
                if "?" not in lbl and not lbl.endswith(":"):
                    # Use a soft gate: very short bold lines are likely headings.
                    if ln.bold and _word_count(lbl) <= 4 and len(lbl) <= 28:
                        # Only accept if there is strong entry evidence.
                        if not _question_entry_evidence_anywhere(block_lines, end_y, activity_x=float(activity_x), max_x=max_x, header_cut=header_cut, footer_cut=footer_cut):
                            i = next_i
                            continue

                # Require entry evidence nearby (prevents pulling pure instruction text).
                if not _question_entry_evidence_anywhere(block_lines, end_y, activity_x=float(activity_x), max_x=max_x, header_cut=header_cut, footer_cut=footer_cut):
                    i = next_i
                    continue

                yy = float(start_y)
                fm = active_form_for_y(yy)

                key = (fm, lbl, int(page_idx0))
                if key not in local_seen:
                    local_seen.add(key)

                    x0n = float(activity_x) / (max_x + 1e-6)
                    y0n = yy / (max_y + 1e-6)
                    candidates.append(
                        {
                            "form_name": fm,
                            "field_name": lbl,
                            "page": int(page_idx0) + 1,
                            "src_kind": "left_label",
                            "x0n": min(0.999, max(0.0, x0n)),
                            "y0n": min(0.999, max(0.0, y0n)),
                            "entryish": True,
                        }
                    )
                    occ_by_label.setdefault(lbl, []).append((int(page_idx0), min(0.999, max(0.0, x0n)), min(0.999, max(0.0, y0n)), True))

                i = next_i

    # Global furniture filtering by recurrence + tight position clustering, but only for non-entryish items.
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
        page_set = {p for (p, _, _, _) in occ}
        frac = len(page_set) / pages_total_nonzero
        if frac < 0.70:
            continue

        xs = [x for (_, x, _, _) in occ]
        ys = [y for (_, _, y, _) in occ]
        entryish_frac = sum(1 for (_, _, _, e) in occ if e) / max(1, len(occ))

        x_sd = _std(xs)
        y_sd = _std(ys)
        y_med = sorted(ys)[len(ys) // 2] if ys else 0.5

        # Template furniture tends to be stable and near top/bottom, and usually not tied to entry evidence.
        if entryish_frac <= 0.20 and x_sd <= 0.035 and y_sd <= 0.055 and (y_med <= 0.26 or y_med >= 0.76):
            drop_labels.add(lbl)

    # Finalize with de-dup and cleanup.
    results: List[Dict[str, Any]] = []
    seen = set()

    for c in candidates:
        fn = _clean_field_label(_norm_space(c.get("field_name", "")))
        fm = _norm_space(c.get("form_name", ""))
        pg = int(c.get("page", 0) or 0)

        if not fn or not _has_letter(fn):
            continue
        if _is_code_line_text(fn):
            continue
        if _is_parenthetical_limit_hint(fn):
            continue
        if fn in drop_labels:
            continue

        # Never output headings as fields.
        if c.get("src_kind") in ("left_label", "row_entry", "inline_placeholder"):
            # Drop if it still looks like a section title (rare but can happen with OCR quirks).
            tmp = type(
                "Tmp",
                (),
                {
                    "text": fn,
                    "x0": 0.5,  # unused by this simplified check; we guard via punctuation and length
                    "x1": 0.9,
                    "y0": 0.5,
                    "y1": 0.5,
                    "bold": False,
                    "non_black": False,
                },
            )
            # Only apply the hard punctuation/title guard.
            if ("?" not in fn) and (not fn.endswith(":")) and (not fn.endswith(".")) and _word_count(fn) <= 3 and len(fn) <= 20:
                # Very short labels are OK; keep (e.g., "Date", "Time", "Comment").
                pass

        # If a blue label ends with ":" but has no entry evidence, treat it cautiously.
        if c.get("src_kind") == "blue_label" and fn.endswith(":") and (not c.get("entryish", False)):
            # Keep (covers fields like Staff Initials / Comment that may have non-text entry lines),
            # but rely on global furniture drop to remove true template furniture.
            pass

        key = (fm, fn, pg)
        if key in seen:
            continue
        seen.add(key)

        results.append({"form_name": fm, "field_name": fn, "page": pg})

    return results
```
