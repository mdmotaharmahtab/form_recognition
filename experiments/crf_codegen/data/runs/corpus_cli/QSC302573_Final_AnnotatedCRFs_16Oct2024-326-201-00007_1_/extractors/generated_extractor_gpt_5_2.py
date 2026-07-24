# Observed layout: repeated CRF pages with a fixed header and a "Schedule Category & Name" line
# that identifies the current form/section; within the body each data-entry item is organized
# around an "Answer(s)" marker, with its question/label printed just above in a consistent column.
# Strategy: carry forward form_name from the schedule line; for each "Answer(s)" block, extract the
# nearest bold black label text above it (joining wrapped lines) and also capture nearby blue left
# labels (e.g., Staff Initials / Comment) plus checkbox-style subprompts in the answer region.

import re
import unicodedata
from typing import List, Dict, Tuple, Optional


def extract(pages):
    out: List[Dict[str, object]] = []
    seen = set()

    current_form = ""

    for page_idx0, lines in pages:
        page_num = int(page_idx0) + 1

        current_form = _extract_form_name(lines, current_form)

        # Find all "Answer(s)" markers on the page; these define field blocks.
        ans_markers = [ln for ln in lines if _is_answer_marker(ln)]
        ans_markers.sort(key=lambda l: (l.y0, l.x0))

        if not ans_markers:
            continue

        header_cutoff_y = _header_cutoff_y(lines)

        for i, ans in enumerate(ans_markers):
            y_prev = header_cutoff_y if i == 0 else max(header_cutoff_y, ans_markers[i - 1].y0)
            y_next = 1e9 if i + 1 >= len(ans_markers) else ans_markers[i + 1].y0

            label_x = ans.x0

            main_label = _extract_main_label(lines, label_x, y_prev, ans.y0)
            if main_label:
                _add(out, seen, current_form, main_label, page_num)

                staff_ln = _nearest_blue_left_label(lines, y_prev, ans.y0, choose="last")
                if staff_ln:
                    staff_name = _strip_trailing_colon(_norm_text(staff_ln.text))
                    if staff_name:
                        _add(out, seen, current_form, staff_name, page_num)

                comment_ln = _nearest_blue_left_label(lines, ans.y0, y_next, choose="first")
                comment_y = comment_ln.y0 if comment_ln else y_next
                if comment_ln:
                    comment_name = _strip_trailing_colon(_norm_text(comment_ln.text))
                    if comment_name:
                        _add(out, seen, current_form, comment_name, page_num)
            else:
                # No on-page label above this Answer(s): likely a continuation page; still use
                # comment marker to bound answer-region parsing if present.
                comment_ln = _nearest_blue_left_label(lines, ans.y0, y_next, choose="first")
                comment_y = comment_ln.y0 if comment_ln else y_next

            # Extract checkbox/prompts inside the answer region (useful for checklist-style items).
            # Bound by the next left-blue label (often "Comment:") when present.
            subs = _extract_answer_region_prompts(lines, label_x, ans.y0, comment_y)
            for s in subs:
                _add(out, seen, current_form, s, page_num)

    return out


# -------------------------
# Form name (section title)
# -------------------------

_SCHEDULE_LABEL_NORM = re.sub(r"\s+", "", "Schedule Category & Name:").lower()


def _extract_form_name(lines, prev_form: str) -> str:
    # Use the value printed to the right of "Schedule Category & Name:" in the header area.
    for idx, ln in enumerate(lines):
        if ln.y0 > 140:
            break
        tnorm = re.sub(r"\s+", "", (ln.text or "")).lower()
        if tnorm == _SCHEDULE_LABEL_NORM:
            y = ln.y0
            x_min = max(120.0, ln.x1 - 5.0)
            # Prefer same-row value at the right.
            cands = [
                l2
                for l2 in lines
                if abs(l2.y0 - y) <= 2.0
                and l2.x0 >= x_min
                and (l2.text or "").strip()
                and (not l2.bold)
            ]
            if not cands:
                # Fallback: nearest line just below, same x band.
                cands = [
                    l2
                    for l2 in lines
                    if (l2.y0 >= y - 0.5 and l2.y0 <= y + 10.0)
                    and l2.x0 >= x_min
                    and (l2.text or "").strip()
                    and (not l2.bold)
                ]
            if cands:
                cands.sort(key=lambda l: (abs(l.y0 - y), l.x0))
                base = _norm_text(cands[0].text)

                # Join wrapped continuation lines directly below if they align.
                wrap = [base]
                x0 = cands[0].x0
                y0 = cands[0].y0
                for l2 in lines:
                    if l2 is cands[0]:
                        continue
                    if l2.y0 > y0 and (l2.y0 - y0) <= 16.0 and abs(l2.x0 - x0) <= 8.0 and not l2.bold:
                        tx = _norm_text(l2.text)
                        if tx:
                            wrap.append(tx)
                            y0 = l2.y0
                return _norm_text(" ".join(wrap)) or prev_form

    return prev_form


def _header_cutoff_y(lines) -> float:
    # The header row with column titles sits around y~116; keep a tolerant cutoff.
    # Use the smallest y among body-like items if present; otherwise default.
    ys = [ln.y0 for ln in lines if ln.y0 >= 120]
    return min(ys) if ys else 120.0


# -------------------------
# Block detection
# -------------------------

_ANSWER_MARKER_NORM = re.sub(r"\s+", "", "Answer(s):").lower()


def _is_answer_marker(ln) -> bool:
    if not ln.bold:
        return False
    # In samples the marker is colored (blue), but use text-shape first.
    t = ln.text or ""
    tnorm = re.sub(r"\s+", "", t).lower()
    if tnorm != _ANSWER_MARKER_NORM:
        return False
    if ln.y0 < 120:
        return False
    # Expected in the label column region.
    if ln.x0 < 110 or ln.x0 > 260:
        return False
    return True


def _is_blue_left_label(ln) -> bool:
    if not ln.bold:
        return False
    if not ln.non_black:
        return False
    if ln.x0 > 110:
        return False
    if ln.y0 < 120:
        return False
    txt = (ln.text or "").strip()
    if not txt:
        return False
    # Prefer labels ending with ":" but allow minor drift.
    if txt.endswith(":"):
        return True
    # Some templates may omit the colon; accept short, label-like text.
    if len(txt) <= 30:
        return True
    return False


def _nearest_blue_left_label(lines, y0: float, y1: float, choose: str) -> Optional[object]:
    cands = [ln for ln in lines if ln.y0 >= y0 - 0.5 and ln.y0 <= y1 + 0.5 and _is_blue_left_label(ln)]
    if not cands:
        return None
    cands.sort(key=lambda l: (l.y0, l.x0))
    return cands[0] if choose == "first" else cands[-1]


# -------------------------
# Main field label extraction
# -------------------------

def _extract_main_label(lines, label_x: float, y0: float, ans_y: float) -> str:
    # Use the last "mask" line (underscore placeholders) in the left area as a structural divider:
    # the human label tends to appear at or below that y, while the activity header is above it.
    mask_y = None
    for ln in lines:
        if ln.y0 < y0 or ln.y0 >= ans_y:
            continue
        if ln.x0 <= (label_x - 20.0) and "_" in (ln.text or "") and (ln.text or "").count("_") >= 4:
            mask_y = ln.y0 if (mask_y is None or ln.y0 > mask_y) else mask_y

    # Candidate bold black lines in the label column between y0 and Answer(s)
    cands = []
    for ln in lines:
        if ln.y0 <= y0 or ln.y0 >= ans_y:
            continue
        if not ln.bold:
            continue
        if ln.non_black:
            continue
        if abs(ln.x0 - label_x) > 28.0:
            continue
        txt = _norm_text(ln.text)
        if not txt:
            continue
        if _is_sas_line(txt) or _is_option_line(txt) or _is_checkbox_line(txt):
            continue
        if txt.startswith("-") or txt.startswith("_"):
            continue
        cands.append(ln)

    if not cands:
        return ""

    cands.sort(key=lambda l: (l.y0, l.x0))

    # Choose the last candidate that is not clearly above the mask divider (to avoid activity headers).
    chosen = None
    for ln in reversed(cands):
        if mask_y is None or ln.y0 >= (mask_y - 2.0):
            chosen = ln
            break
    if chosen is None:
        return ""

    # Walk upward to join wrapped label lines (same column, tight vertical spacing).
    group = [chosen]
    last_y = chosen.y0
    for ln in reversed(cands[: cands.index(chosen)]):
        if last_y - ln.y0 > 20.0:
            break
        if abs(ln.x0 - chosen.x0) > 8.0:
            break
        # Keep only plausible continuation lines.
        txt = _norm_text(ln.text)
        if txt and (not txt.startswith("-")) and (not _looks_like_placeholder(txt)):
            group.append(ln)
            last_y = ln.y0

    group.sort(key=lambda l: (l.y0, l.x0))

    parts = []
    for ln in group:
        t = _norm_text(ln.text)
        if t:
            parts.append(t)

    label = _norm_text(" ".join(parts))
    return label


# -------------------------
# Answer-region prompt extraction (checklists)
# -------------------------

def _extract_answer_region_prompts(lines, label_x: float, y0: float, y1: float) -> List[str]:
    region = [ln for ln in lines if ln.y0 >= y0 - 0.5 and ln.y0 <= y1 + 0.5 and (ln.text or "").strip()]
    region.sort(key=lambda l: (l.y0, l.x0))

    # Focus on the answer column to the right of the label column.
    answer_min_x = label_x + 40.0

    prompts: List[str] = []
    i = 0
    while i < len(region):
        ln = region[i]
        if ln.x0 < answer_min_x:
            i += 1
            continue
        if ln.non_black:
            i += 1
            continue

        txt_raw = _norm_text(ln.text)
        if not txt_raw or _is_sas_line(txt_raw) or _is_option_line(txt_raw):
            i += 1
            continue

        checkbox = _is_checkbox_line(txt_raw)
        if _looks_like_placeholder(txt_raw) and not checkbox:
            i += 1
            continue

        # Lookahead for SAS annotation tied to this line (options/placeholder lines commonly have it).
        if not checkbox:
            if _has_nearby_sas(region, i, ln):
                i += 1
                continue

        # Start a prompt if checkbox, or if followed by an underscore-only line (free text field),
        # or if the line itself contains an underline fill area.
        start = False
        if checkbox:
            start = True
        else:
            if _contains_fill_underline(txt_raw):
                start = True
            elif _next_is_underline_only(region, i, ln):
                start = True

        if not start:
            i += 1
            continue

        # Build a wrapped prompt across subsequent lines with aligned x and tight y spacing.
        parts = [_clean_answer_prompt(txt_raw)]
        j = i + 1
        last = ln
        while j < len(region):
            ln2 = region[j]
            if ln2.x0 < answer_min_x or ln2.non_black:
                break
            dy = ln2.y0 - last.y0
            if dy < 0:
                j += 1
                continue
            if dy > 16.0:
                break
            if abs(ln2.x0 - last.x0) > 10.0:
                break

            t2 = _norm_text(ln2.text)
            if not t2 or _is_sas_line(t2) or _is_option_line(t2) or _is_checkbox_line(t2):
                break
            if _looks_like_placeholder(t2):
                break

            parts.append(_clean_answer_prompt(t2))
            last = ln2
            j += 1

        prompt = _norm_text(" ".join([p for p in parts if p]))
        prompt = _strip_trailing_colon(prompt)
        if prompt and not _looks_like_placeholder(prompt):
            prompts.append(prompt)

        i = max(i + 1, j)

    # De-dup within region while preserving order
    seen_local = set()
    out = []
    for p in prompts:
        key = _norm_text(p)
        if key and key not in seen_local:
            seen_local.add(key)
            out.append(p)
    return out


def _has_nearby_sas(region, idx: int, ln) -> bool:
    # If a SAS annotation line appears shortly after, aligned in the same answer column,
    # treat the current line as an option/placeholder rather than a separate field label.
    base_x = ln.x0
    base_y = ln.y0
    steps = 0
    j = idx + 1
    while j < len(region) and steps < 3:
        ln2 = region[j]
        if ln2.y0 - base_y > 26.0:
            break
        t2 = _norm_text(ln2.text)
        if t2:
            steps += 1
            if abs(ln2.x0 - base_x) <= 18.0 and _is_sas_line(t2):
                return True
        j += 1
    return False


def _next_is_underline_only(region, idx: int, ln) -> bool:
    base_x = ln.x0
    base_y = ln.y0
    j = idx + 1
    while j < len(region):
        ln2 = region[j]
        if ln2.y0 - base_y > 18.0:
            return False
        if abs(ln2.x0 - base_x) > 18.0:
            j += 1
            continue
        t2 = (ln2.text or "").strip()
        if not t2:
            j += 1
            continue
        return _is_underline_only(t2)
    return False


# -------------------------
# Text heuristics / cleaning
# -------------------------

_SAS_RE = re.compile(r"\bSAS\s*:\s*\[|\bSAS\s*:\s*\{|\bSAS\s*:\s*Name\b|\bSAS\s*:\s*\[Name=", re.IGNORECASE)
_SAS_BRACKET_RE = re.compile(r"^\s*\[[A-Z0-9_]+\]\s*SAS\s*:", re.IGNORECASE)


def _is_sas_line(txt: str) -> bool:
    if not txt:
        return False
    if _SAS_BRACKET_RE.match(txt):
        return True
    if _SAS_RE.search(txt):
        return True
    return False


def _is_option_line(txt: str) -> bool:
    # Radio option marker in this CRF template is leading "O ".
    return bool(re.match(r"^\s*[Oo]\s+", txt))


def _is_checkbox_line(txt: str) -> bool:
    # Checkbox-style marker like "[ ]" or "[X]".
    return bool(re.match(r"^\s*\[\s*[xX]?\s*\]\s*", txt))


def _norm_text(s: str) -> str:
    s = s or ""
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _strip_trailing_colon(s: str) -> str:
    s = _norm_text(s)
    s = re.sub(r"\s*:\s*$", "", s)
    return s.strip()


def _is_underline_only(s: str) -> bool:
    t = re.sub(r"\s+", "", s or "")
    if not t:
        return False
    return bool(re.fullmatch(r"[_\-–—.]+", t))


def _contains_fill_underline(s: str) -> bool:
    return bool(re.search(r"_{5,}", s or ""))


def _clean_answer_prompt(s: str) -> str:
    s = _norm_text(s)
    # Remove leading checkbox marker.
    s = re.sub(r"^\s*\[\s*[xX]?\s*\]\s*", "", s)
    # Drop long underline sequences.
    s = re.sub(r"_{5,}", " ", s)
    s = _norm_text(s)
    return s


def _looks_like_placeholder(txt: str) -> bool:
    # Structural filter: lines dominated by underscores/digits/punctuation are not human labels.
    t = txt or ""
    chars = [c for c in t if not c.isspace()]
    if not chars:
        return True

    underscores = sum(1 for c in chars if c == "_")
    letters = sum(1 for c in chars if unicodedata.category(c).startswith("L"))
    digits = sum(1 for c in chars if unicodedata.category(c).startswith("N"))

    ufrac = underscores / max(1, len(chars))
    lfrac = letters / max(1, len(chars))

    # Very underscore-heavy and low-letter -> placeholder/mask.
    if ufrac >= 0.25 and lfrac <= 0.22:
        return True

    # Pure numeric/punct lines (e.g., isolated codes) are not labels.
    if letters == 0 and digits > 0 and digits / max(1, len(chars)) >= 0.55:
        return True

    return False


def _add(out, seen, form_name: str, field_name: str, page_num: int) -> None:
    fn = _norm_text(form_name)
    fld = _norm_text(field_name)
    if not fld:
        return
    key = (fn, fld, int(page_num))
    if key in seen:
        return
    seen.add(key)
    out.append({"form_name": fn, "field_name": fld, "page": int(page_num)})
