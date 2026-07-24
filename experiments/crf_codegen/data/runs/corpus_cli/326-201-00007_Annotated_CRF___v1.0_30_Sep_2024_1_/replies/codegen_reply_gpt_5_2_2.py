```python
import re
from typing import Any, Dict, List, Optional, Tuple


_WS_RE = re.compile(r"\s+")
_ACT_HDR_RE = re.compile(r"#\s*\d+\b")
_OPT_RE = re.compile(r"^\s*[Oo]\s+")
_CODE_RE = re.compile(r"^\s*\[.*\]\s*$")
_SAS_HINT_RE = re.compile(r"\bSAS:\[", re.IGNORECASE)


def _norm_space(s: str) -> str:
    return _WS_RE.sub(" ", s).strip()


def _has_letter(s: str) -> bool:
    for ch in s:
        if ch.isalpha():
            return True
    return False


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


def _clean_entry_label(t: str) -> str:
    s = t
    s = re.sub(r"_+", " ", s)
    s = _norm_space(s)

    toks = []
    for tok in s.split(" "):
        if tok and all(ch in "-:./" for ch in tok):
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
    if float(ln.x0) < 0.18 * max_x or float(ln.x0) > 0.80 * max_x:
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


def _right_side_evidence_count(
    anchor_ln,
    block_lines,
    activity_x: float,
    max_x: float,
    y_window: float,
) -> Tuple[int, int, int]:
    """
    Returns (evidence_cnt, option_cnt, underscore_cnt) to the right of anchor.
    """
    y0 = float(anchor_ln.y0)
    y1 = y0 + y_window
    x_min = max(float(anchor_ln.x1) + 2.0, float(activity_x) + 0.18 * max_x)

    evidence_cnt = 0
    option_cnt = 0
    underscore_cnt = 0

    for ln in block_lines:
        yy = float(ln.y0)
        if yy <= y0 or yy > y1:
            continue
        if _is_blue_colon_label(ln, -1e9, 1e9):
            continue
        if float(ln.x0) < x_min:
            continue
        t = (ln.text or "").strip()
        if not t or _is_code_line_text(t):
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
        # Count other short/normal answer lines as weak evidence.
        if _has_letter(t) or any(ch.isdigit() for ch in t):
            evidence_cnt += 1

    return evidence_cnt, option_cnt, underscore_cnt


def _is_answer_header_like(lbl_ln, block_lines, activity_x: float, max_x: float) -> bool:
    # Structural: blue bold label ending with ':', with a multi-line right-hand answer region.
    if not lbl_ln.non_black or not lbl_ln.bold:
        return False
    t = (lbl_ln.text or "").strip()
    if not t.endswith(":"):
        return False
    if float(lbl_ln.x0) < 0.16 * max_x:
        return False

    evidence_cnt, option_cnt, underscore_cnt = _right_side_evidence_count(
        lbl_ln, block_lines, activity_x=activity_x, max_x=max_x, y_window=120.0
    )

    # Treat as an "answer header" when the region looks like a grouped answer area (options/list),
    # not a single-value subfield (e.g., Comment/Initials).
    if option_cnt >= 1:
        return True
    if evidence_cnt >= 3:
        return True
    if underscore_cnt >= 2:
        return True
    return False


def _has_right_side_entry(lbl_ln, block_lines, activity_x: float, max_x: float) -> bool:
    # Subfield labels should only be emitted if there is an actual entry slot to the right.
    evidence_cnt, option_cnt, underscore_cnt = _right_side_evidence_count(
        lbl_ln, block_lines, activity_x=activity_x, max_x=max_x, y_window=60.0
    )
    return (underscore_cnt >= 1) or (option_cnt >= 1) or (evidence_cnt >= 2)


def _first_question_span(block_lines, activity_x: float, x_tol: float, header_cut: float, footer_cut: float) -> str:
    best: List[str] = []
    started = False
    last_y: Optional[float] = None

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

        # Keep question label in left/main column.
        near_x = abs(float(ln.x0) - activity_x) <= x_tol
        is_black = (not ln.non_black)
        not_activity_hdr = (":" not in t) or (not _ACT_HDR_RE.search(t))
        looks_like_question_line = is_black and near_x and not_activity_hdr

        if not started:
            # Start on bold black line when possible; fall back to normal black if it's clearly in the same column.
            if looks_like_question_line and (ln.bold or len(t) >= 8):
                started = True
                best.append(t)
                last_y = y0
        else:
            if last_y is None:
                break
            dy = y0 - last_y
            # Allow wraps that aren't bold and may be slightly indented.
            cont_near_x = abs(float(ln.x0) - activity_x) <= (x_tol * 1.6)
            if is_black and cont_near_x and dy <= 34.0 and not _is_blue_colon_label(ln, header_cut, footer_cut):
                # Stop if we drift into obvious answer-column territory.
                if float(ln.x0) > activity_x + 0.30 * x_tol and float(ln.x0) > 0.55 * (activity_x + max(activity_x, 1.0)):
                    break
                best.append(t)
                last_y = y0
            else:
                break

    return _norm_space(" ".join(best))


def _extract_underscore_fields_from_region(
    region_lines,
    x_min: float,
    x_max: float,
    max_dx: float = 18.0,
    max_dy: float = 28.0,
) -> List[str]:
    # Find underscore-bearing entry lines and merge wrapped segments.
    cand = []
    for ln in region_lines:
        t = (ln.text or "").strip()
        if not t:
            continue
        if _is_code_line_text(t) or _OPT_RE.match(t):
            continue
        if "_" not in t:
            continue
        x0 = float(ln.x0)
        if x0 < x_min or x0 > x_max:
            continue
        cand.append(ln)

    cand.sort(key=lambda l: (float(l.y0), float(l.x0)))

    out: List[str] = []
    i = 0
    while i < len(cand):
        ln = cand[i]
        parts = [(ln.text or "").strip()]
        base_x = float(ln.x0)
        base_y = float(ln.y0)
        j = i + 1

        while j < len(cand):
            ln2 = cand[j]
            t2 = (ln2.text or "").strip()
            if not t2:
                j += 1
                continue
            dx = abs(float(ln2.x0) - base_x)
            dy = float(ln2.y0) - base_y
            if dx <= max_dx and dy <= max_dy:
                parts.append(t2)
                base_y = float(ln2.y0)
                j += 1
                continue
            break

        merged = _norm_space(" ".join(parts))
        cleaned = _clean_entry_label(merged)
        if cleaned and _has_letter(cleaned) and len(cleaned) >= 4:
            out.append(cleaned)

        i = j

    # De-dup preserving order.
    seen = set()
    dedup: List[str] = []
    for s in out:
        if s in seen:
            continue
        seen.add(s)
        dedup.append(s)
    return dedup


def _extract_answer_entry_labels(block_lines, ans_hdr_ln, activity_x: float, header_cut: float, footer_cut: float, max_x: float) -> List[str]:
    start_y = float(ans_hdr_ln.y0) + 0.5
    stop_y = footer_cut
    for ln in block_lines:
        if float(ln.y0) <= start_y:
            continue
        if _is_blue_colon_label(ln, header_cut, footer_cut):
            stop_y = float(ln.y0) - 0.1
            break

    region = [ln for ln in block_lines if (float(ln.y0) > start_y and float(ln.y0) <= stop_y)]
    # Right-of-label / right column: be permissive (some templates start answers closer than option bullets).
    x_min = max(float(ans_hdr_ln.x1) + 2.0, float(activity_x) + 0.16 * max_x)
    x_max = 1e9
    return _extract_underscore_fields_from_region(region, x_min=x_min, x_max=x_max, max_dx=22.0, max_dy=30.0)


def _page_form_title(lines, max_x: float, header_cut: float) -> str:
    # High-confidence guess for form title from header band (top of page).
    best_t = ""
    best_score = -1e9

    for ln in lines:
        y0 = float(ln.y0)
        if y0 >= header_cut:
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
        if _ACT_HDR_RE.search(t):
            continue
        if not (ln.bold and (not ln.non_black)):
            continue
        if not _has_letter(t):
            continue

        tt = t.lower()
        if "page" in tt and any(ch.isdigit() for ch in t):
            continue

        x0 = float(ln.x0)
        x1 = float(ln.x1)
        if x1 <= x0:
            continue
        span = x1 - x0
        if span < 0.18 * max_x:
            continue
        cx = (x0 + x1) / 2.0
        center_bonus = 1.0 - min(1.0, abs(cx - 0.5 * max_x) / (0.5 * max_x + 1e-6))

        # Prefer wide, centered, and closer to the bottom of header band.
        score = (span / (max_x + 1e-6)) * 2.2 + center_bonus * 0.9 + (y0 / (header_cut + 1e-6)) * 0.7
        if score > best_score:
            best_score = score
            best_t = t

    return _norm_space(best_t)


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    current_form = ""
    current_activity_x: Optional[float] = None

    for page_idx0, lines in pages:
        if not lines:
            continue

        max_x, max_y = _page_extents(lines)
        if max_x <= 0 or max_y <= 0:
            continue

        header_cut = 0.18 * max_y + 5.0
        footer_cut = max_y - 35.0

        page_form_guess = _page_form_title(lines, max_x=max_x, header_cut=header_cut)

        body_lines = []
        for ln in lines:
            t = (ln.text or "").strip()
            if not t:
                continue
            y0 = float(ln.y0)
            if y0 < header_cut or y0 > footer_cut:
                continue
            if _is_footer_furniture_line(ln, max_y=max_y):
                continue
            body_lines.append(ln)

        if not body_lines:
            continue

        # Activity headers define blocks.
        hdrs = [ln for ln in body_lines if _is_activity_header_line(ln, max_x, header_cut, footer_cut)]
        hdrs.sort(key=lambda l: (float(l.y0), float(l.x0)))

        first_hdr_form = ""
        if hdrs:
            first_hdr_form = _parse_form_name_from_activity_header(((hdrs[0].text or "").strip()))

        blocks = []
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

        # If a page-level title is confidently detected, allow it to reset the persistent form on pages
        # that lack activity headers (common continuation layouts).
        if page_form_guess and (not hdrs):
            current_form = page_form_guess

        local_seen = set()

        for hdr_ln, y0, y1 in blocks:
            block_lines = [ln for ln in body_lines if (float(ln.y0) >= y0 and float(ln.y0) <= y1)]
            if not block_lines:
                continue
            block_lines.sort(key=lambda l: (float(l.y0), float(l.x0)))

            # Default form selection for this block.
            block_form = current_form
            if hdr_ln is None:
                # Pre-header region on a page should inherit the first header's form when available (fixes page-1 preamble).
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

            x_tol = max(18.0, 0.045 * max_x)

            # Identify blue colon labels and classify answer header vs subfields structurally.
            blue_labels = [ln for ln in block_lines if _is_blue_colon_label(ln, header_cut, footer_cut)]
            blue_labels.sort(key=lambda l: (float(l.y0), float(l.x0)))

            ans_hdr = None
            for ln in blue_labels:
                if _is_answer_header_like(ln, block_lines, activity_x=activity_x, max_x=max_x):
                    ans_hdr = ln
                    break

            subfield_labels: List[str] = []
            for ln in blue_labels:
                if ans_hdr is not None and ln is ans_hdr:
                    continue
                # Only emit subfields if there's a right-side entry (prevents template headers from becoming fields).
                if not _has_right_side_entry(ln, block_lines, activity_x=activity_x, max_x=max_x):
                    continue
                lab = (ln.text or "").strip()
                if lab and not _is_code_line_text(lab):
                    subfield_labels.append(lab)

            entry_labels: List[str] = []
            if ans_hdr is not None:
                entry_labels = _extract_answer_entry_labels(
                    block_lines,
                    ans_hdr,
                    activity_x=activity_x,
                    header_cut=header_cut,
                    footer_cut=footer_cut,
                    max_x=max_x,
                )

            # Extract question label (choice field label) and keep it when there is answer evidence.
            q_label = _first_question_span(block_lines, activity_x, x_tol, header_cut, footer_cut)
            has_choice_evidence = False
            if ans_hdr is not None:
                ev_cnt, opt_cnt, us_cnt = _right_side_evidence_count(
                    ans_hdr, block_lines, activity_x=activity_x, max_x=max_x, y_window=160.0
                )
                has_choice_evidence = (opt_cnt >= 1) or (ev_cnt >= 2) or (us_cnt >= 1)
            else:
                # Fallback: look for options/underscore lines anywhere to the right of the activity column within the block.
                y_start = float(block_lines[0].y0)
                y_stop = float(block_lines[-1].y0)
                x_min = float(activity_x) + 0.22 * max_x
                ev = 0
                for ln in block_lines:
                    if float(ln.y0) < y_start or float(ln.y0) > y_stop:
                        continue
                    if float(ln.x0) < x_min:
                        continue
                    t = (ln.text or "").strip()
                    if not t or _is_code_line_text(t):
                        continue
                    if _OPT_RE.match(t) or "_" in t or _CODE_RE.match(t):
                        ev += 1
                        if ev >= 2:
                            break
                has_choice_evidence = ev >= 2

            # Inline underscore-fields anywhere in the block (captures Date/Version rows and table entry fields).
            inline_underscore_fields = _extract_underscore_fields_from_region(
                block_lines,
                x_min=0.0,
                x_max=1e9,
                max_dx=22.0,
                max_dy=30.0,
            )

            field_names: List[str] = []
            field_names.extend(subfield_labels)

            # Include the question label only when the block shows answer/entry evidence.
            if q_label and has_choice_evidence:
                field_names.append(q_label)

            # Add answer-area entry labels (e.g., "Yes (Specify) ____", "Time ____").
            field_names.extend(entry_labels)

            # Add inline underscore fields (but avoid duplicating those already captured from answer area/subfields).
            field_names.extend(inline_underscore_fields)

            # Emit.
            for fn in field_names:
                fn = _norm_space(fn)
                if not fn or not _has_letter(fn) or _is_code_line_text(fn):
                    continue

                # Avoid admitting blue-label headers that are structurally answer headers (even if misdetected earlier).
                # This is structural (right-side list evidence), not a literal string blocklist.
                if fn.endswith(":") and any(
                    (_norm_space((ln.text or "").strip()) == fn)
                    and _is_blue_colon_label(ln, header_cut, footer_cut)
                    and _is_answer_header_like(ln, block_lines, activity_x=activity_x, max_x=max_x)
                    for ln in blue_labels
                ):
                    continue

                key = (block_form or "", fn, int(page_idx0))
                if key in local_seen:
                    continue
                local_seen.add(key)

                results.append(
                    {
                        "form_name": block_form or "",
                        "field_name": fn,
                        "page": int(page_idx0) + 1,
                    }
                )

    return results
```
