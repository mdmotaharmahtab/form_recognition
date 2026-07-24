```python
# Observed layout: repeated header band (top) and footer band (bottom) with a single main column of "activity blocks".
# Each block typically starts with a bold black "Section: Item #n" activity header, followed by a bold black question label,
# then blue bold subfield labels (e.g., "Staff Initials:", "Comment:", "Barcode:") and an "Answer(s):" band with options/entry slots.
# Strategy: segment pages into blocks using the activity headers; carry forward the last seen section (form_name) across continuation pages;
# extract question labels when answers are choice-only, otherwise extract entry-slot labels from the answer area; always extract blue subfield labels.

import re
from typing import List, Tuple, Dict, Any, Optional


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
    # Also treat bracketed technical lines as code even if truncated.
    if t.lstrip().startswith("[") and ("SAS" in t or "Name=" in t or "DataType=" in t):
        return True
    return False


def _clean_entry_label(t: str) -> str:
    # Remove underscore-based blanks; keep human text, units, and parenthetical formats.
    s = t
    s = re.sub(r"_+", " ", s)
    s = _norm_space(s)

    # Drop tokens that are only placeholder separators left after underscore removal.
    toks = []
    for tok in s.split(" "):
        if tok and all(ch in "-:./" for ch in tok):
            continue
        toks.append(tok)
    s = " ".join(toks).strip()

    # Clean duplicated punctuation spacing.
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


def _option_x_min(lines, max_x: float) -> float:
    xs = []
    for ln in lines:
        t = ln.text or ""
        if _OPT_RE.match(t):
            xs.append(float(ln.x0))
    if xs:
        xs.sort()
        return xs[len(xs) // 2] - 2.0
    return 0.42 * max_x


def _is_activity_header_line(ln, max_x: float, header_cut: float, footer_cut: float) -> bool:
    t = (ln.text or "").strip()
    if not t or ln.non_black or (not ln.bold):
        return False
    if ln.y0 < header_cut or ln.y0 > footer_cut:
        return False
    # Mid-column; avoid left timepoint and right line number.
    if ln.x0 < 0.18 * max_x or ln.x0 > 0.75 * max_x:
        return False
    # Must look like "Section: Item #n" (colon + occurrence marker).
    if ":" not in t:
        return False
    if not _ACT_HDR_RE.search(t):
        return False
    return True


def _parse_form_name_from_activity_header(t: str) -> str:
    if ":" not in t:
        return ""
    left = t.split(":", 1)[0].strip()
    # Keep exactly printed (no reformat) but avoid empty.
    return left


def _is_blue_colon_label(ln, header_cut: float, footer_cut: float) -> bool:
    t = (ln.text or "").strip()
    if not t or ln.y0 < header_cut or ln.y0 > footer_cut:
        return False
    return bool(ln.non_black and ln.bold and t.endswith(":"))


def _is_answer_header_like(lbl_ln, block_lines, option_x: float, max_x: float) -> bool:
    # Structural: blue bold label with ':' in the activity column, followed soon by >=2 right-column answer lines.
    if not lbl_ln.non_black or not lbl_ln.bold:
        return False
    t = (lbl_ln.text or "").strip()
    if not t.endswith(":"):
        return False
    if lbl_ln.x0 < 0.20 * max_x:
        return False

    y0 = float(lbl_ln.y0)
    y1 = y0 + 95.0
    cnt = 0
    for ln in block_lines:
        if ln.y0 <= y0 or ln.y0 > y1:
            continue
        if ln.x0 + 1.0 >= option_x:
            tt = (ln.text or "").strip()
            if not tt:
                continue
            # Count options/codes/entry lines as evidence of an answer region.
            cnt += 1
            if cnt >= 2:
                return True
    return False


def _first_question_span(block_lines, activity_x: float, x_tol: float, header_cut: float, footer_cut: float) -> str:
    # Find the first contiguous run of bold black lines near the activity column,
    # stopping on the next blue label line.
    best = []
    started = False
    last_y = None
    for ln in block_lines:
        if ln.y0 < header_cut or ln.y0 > footer_cut:
            continue
        if _is_blue_colon_label(ln, header_cut, footer_cut):
            if started:
                break
            continue

        t = (ln.text or "").strip()
        if not t:
            continue
        if _is_code_line_text(t):
            continue

        near_activity = abs(float(ln.x0) - activity_x) <= x_tol
        is_q_line = (ln.bold and (not ln.non_black) and near_activity and (":" not in t or not _ACT_HDR_RE.search(t)))

        if not started:
            if is_q_line:
                started = True
                best.append(t)
                last_y = float(ln.y0)
        else:
            # Continue if still question-like and vertically close; otherwise stop when we hit other content.
            if is_q_line and last_y is not None and (float(ln.y0) - last_y) <= 26.0:
                best.append(t)
                last_y = float(ln.y0)
            else:
                break

    return _norm_space(" ".join(best))


def _extract_answer_entry_labels(block_lines, ans_hdr_ln, option_x: float, header_cut: float, footer_cut: float) -> List[str]:
    # Collect answer-area lines after the answer header until the next blue colon label.
    start_y = float(ans_hdr_ln.y0) + 0.5
    stop_y = footer_cut
    for ln in block_lines:
        if ln.y0 <= start_y:
            continue
        if _is_blue_colon_label(ln, header_cut, footer_cut):
            stop_y = float(ln.y0) - 0.1
            break

    ans_lines = []
    for ln in block_lines:
        if ln.y0 <= start_y or ln.y0 > stop_y:
            continue
        if float(ln.x0) + 1.0 < option_x:
            continue
        t = (ln.text or "").strip()
        if not t:
            continue
        ans_lines.append(ln)

    # Merge entry slots starting with underscore-bearing lines that are not options/codes.
    out = []
    i = 0
    while i < len(ans_lines):
        ln = ans_lines[i]
        t = (ln.text or "").strip()

        if _is_code_line_text(t) or _OPT_RE.match(t):
            i += 1
            continue
        if "_" not in t:
            i += 1
            continue

        parts = [t]
        base_x = float(ln.x0)
        base_y = float(ln.y0)
        j = i + 1
        while j < len(ans_lines):
            ln2 = ans_lines[j]
            t2 = (ln2.text or "").strip()
            if not t2:
                j += 1
                continue
            if _is_code_line_text(t2) or _OPT_RE.match(t2):
                break
            # Continue wrapped lines close in geometry (even if no underscores).
            if abs(float(ln2.x0) - base_x) <= 18.0 and (float(ln2.y0) - base_y) <= 26.0:
                parts.append(t2)
                base_y = float(ln2.y0)
                j += 1
                continue
            break

        merged = _norm_space(" ".join(parts))
        cleaned = _clean_entry_label(merged)
        if cleaned and _has_letter(cleaned) and (len(cleaned) >= 4):
            out.append(cleaned)

        i = j

    # De-dup preserving order.
    seen = set()
    dedup = []
    for s in out:
        key = s
        if key in seen:
            continue
        seen.add(key)
        dedup.append(s)
    return dedup


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    current_form = ""
    current_activity_x = None  # type: Optional[float]

    for page_idx0, lines in pages:
        if not lines:
            continue

        max_x, max_y = _page_extents(lines)
        if max_x <= 0 or max_y <= 0:
            continue

        header_cut = 0.18 * max_y + 5.0
        footer_cut = max_y - 35.0

        body_lines = []
        for ln in lines:
            t = (ln.text or "").strip()
            if not t:
                continue
            if ln.y0 < header_cut or ln.y0 > footer_cut:
                continue
            # Skip obvious footer furniture even if it drifts above footer_cut.
            if ln.y0 > max_y - 55.0 and (("Page" in t and any(ch.isdigit() for ch in t)) or ("Date" in t and any(ch.isdigit() for ch in t))):
                continue
            body_lines.append(ln)

        if not body_lines:
            continue

        option_x = _option_x_min(body_lines, max_x)

        # Activity headers define blocks.
        hdrs = [ln for ln in body_lines if _is_activity_header_line(ln, max_x, header_cut, footer_cut)]
        hdrs.sort(key=lambda l: (float(l.y0), float(l.x0)))

        # Create blocks: include continuation area before first header (header=None).
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

        local_seen = set()

        for hdr_ln, y0, y1 in blocks:
            block_lines = [ln for ln in body_lines if (float(ln.y0) >= y0 and float(ln.y0) <= y1)]
            if not block_lines:
                continue
            block_lines.sort(key=lambda l: (float(l.y0), float(l.x0)))

            block_form = current_form
            activity_x = current_activity_x if current_activity_x is not None else (0.30 * max_x)

            if hdr_ln is not None:
                t = (hdr_ln.text or "").strip()
                fm = _parse_form_name_from_activity_header(t)
                if fm:
                    block_form = fm
                    current_form = fm
                activity_x = float(hdr_ln.x0)
                current_activity_x = activity_x

            x_tol = max(18.0, 0.04 * max_x)

            # Blue colon labels (subfields), excluding the answer header.
            subfield_labels = []
            for ln in block_lines:
                if not _is_blue_colon_label(ln, header_cut, footer_cut):
                    continue
                if _is_answer_header_like(ln, block_lines, option_x, max_x):
                    continue
                lab = (ln.text or "").strip()
                if lab and not _is_code_line_text(lab):
                    subfield_labels.append(lab)

            # Find answer header if present.
            ans_hdr = None
            for ln in block_lines:
                if _is_blue_colon_label(ln, header_cut, footer_cut) and _is_answer_header_like(ln, block_lines, option_x, max_x):
                    ans_hdr = ln
                    break

            entry_labels = []
            if ans_hdr is not None:
                entry_labels = _extract_answer_entry_labels(block_lines, ans_hdr, option_x, header_cut, footer_cut)

            # Main question label (only used when there are no entry slots).
            q_label = ""
            if not entry_labels:
                q_label = _first_question_span(block_lines, activity_x, x_tol, header_cut, footer_cut)

            field_names = []
            field_names.extend(subfield_labels)
            if entry_labels:
                field_names.extend(entry_labels)
            elif q_label:
                field_names.append(q_label)

            for fn in field_names:
                fn = _norm_space(fn)
                if not fn or not _has_letter(fn) or _is_code_line_text(fn):
                    continue
                key = (block_form, fn, page_idx0)
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
