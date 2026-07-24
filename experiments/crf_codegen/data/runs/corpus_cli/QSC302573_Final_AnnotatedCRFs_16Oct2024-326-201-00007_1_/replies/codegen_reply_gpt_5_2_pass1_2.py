```python
import re
from typing import List, Tuple, Dict, Any


_WS_RE = re.compile(r"\s+")
_MACHINE_RE = re.compile(r"^\s*\[[A-Za-z0-9_]+\]\s*")
_PAGE_FURN_RE = re.compile(r"^\s*(Page\s+\d+\s+of\s+\d+|Date\s+Created\s*:)", re.IGNORECASE)

_GROUP_VISIT_RE = re.compile(r"\bGroup\s*,\s*Visit\s*:", re.IGNORECASE)
_VERSIONISH_RE = re.compile(r"\bv\d+(\.\d+)*\b", re.IGNORECASE)

# Checkbox/choice prefixes that often get OCR'd into label lines.
_CHOICE_PREFIX_RE = re.compile(
    r"^\s*(?:\d+\)\s*)?(?:O|0|\u25cb)\s+(?:Yes|No|N/?A|NA)\b(?:\s*\([^)]*\))?(?:\s*\(Activates[^\)]*\))?\s*",
    re.IGNORECASE,
)
_GENERIC_CHOICE_LINE_RE = re.compile(
    r"^\s*(?:\d+\)\s*)?(?:O|0|\u25cb)\s+\S+",
    re.IGNORECASE,
)

# Lines that look like list items beneath a header (not a field label).
_BULLETISH_RE = re.compile(r"^\s*[-–•]\s+")

# Vital-sign / numeric-entry style label hints.
_UNIT_RE = re.compile(
    r"\b(mmHg|beats\s*/\s*min|breaths\s*/\s*(?:min|mi)|Degrees\s+Celsius|C\s*\(##|\(##\.0\)|\(##0\)|\(#*\)\b)\b",
    re.IGNORECASE,
)
_NUM_FMT_RE = re.compile(r"\(\s*#+(?:\.\d+)?\s*\)", re.IGNORECASE)

# Column header tokens to ignore.
_COL_HDR_RE = re.compile(r"^(Timepoint|Activity|Line\s*#|Line#)$", re.IGNORECASE)


def _norm(s: str) -> str:
    s = s.replace("\u00ad", "").replace("\u200b", "")
    s = _WS_RE.sub(" ", s).strip()
    return s


def _is_machine_annotation(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if "SAS:[" in s or "SAS:" in s:
        return True
    return bool(_MACHINE_RE.match(s))


def _looks_like_furniture(line) -> bool:
    t = (line.text or "").strip()
    if not t:
        return True
    # Bottom-of-page furniture
    if getattr(line, "y0", 0) > 730:
        return True
    if _PAGE_FURN_RE.match(t):
        return True
    return False


def _is_colored_headerish(line) -> bool:
    # Blue header/labels: non_black + bold + size ~10-12
    return bool(getattr(line, "non_black", False) and getattr(line, "bold", False) and 8.0 <= getattr(line, "size", 0) <= 13.5)


def _is_layout_page(lines) -> bool:
    if not lines:
        return False

    # Large colored title near the top.
    has_title = any((getattr(ln, "non_black", False) and getattr(ln, "bold", False) and getattr(ln, "size", 0) >= 18 and getattr(ln, "y0", 9999) < 80) for ln in lines)

    # Column header trio around y~110-140
    left = mid = right = 0
    for ln in lines:
        if not _is_colored_headerish(ln):
            continue
        y = getattr(ln, "y0", 9999)
        if not (90 <= y <= 150):
            continue
        x = getattr(ln, "x0", 9999)
        if x < 90:
            left += 1
        elif 110 <= x <= 280:
            mid += 1
        elif x > 420:
            right += 1

    return has_title and (left + mid + right) >= 2 and (mid >= 1)


def _row_key(y: float, tol: float = 2.0) -> int:
    return int((y + tol / 2.0) // tol)


def _build_rows(lines):
    rows = {}
    for i, ln in enumerate(lines):
        k = _row_key(getattr(ln, "y0", 0.0))
        rows.setdefault(k, []).append((i, ln))
    for k in list(rows.keys()):
        rows[k].sort(key=lambda p: getattr(p[1], "x0", 0.0))
    return rows


def _is_line_number_token(s: str) -> bool:
    s = s.strip()
    return bool(re.match(r"^\d+(\.\d+)?(\s*\(.*\))?\s*$", s))


def _extract_schedule_context(lines) -> str:
    best = ""
    best_y = 1e9
    for ln in lines:
        if getattr(ln, "non_black", False):
            continue
        if not (9.0 <= getattr(ln, "size", 0) <= 13.5):
            continue
        x = getattr(ln, "x0", 0)
        y = getattr(ln, "y0", 9999)
        if not (140 <= x <= 240):
            continue
        if not (75 <= y <= 120):
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        if _GROUP_VISIT_RE.search(t):
            continue
        if y < best_y:
            best, best_y = t, y
    return best


def _build_activity_entries(lines) -> List[Tuple[float, str]]:
    """
    Returns list of (y0, activity_text) for the mid "Activity" column rows.
    """
    rows = _build_rows(lines)
    out = []
    for _, row in rows.items():
        left_ln = None
        mid_ln = None
        right_ln = None

        for _, ln in row:
            if _looks_like_furniture(ln):
                continue
            x = getattr(ln, "x0", 0)
            y = getattr(ln, "y0", 0)
            sz = getattr(ln, "size", 0)
            if getattr(ln, "non_black", False):
                continue
            if not (8.0 <= sz <= 13.5):
                continue

            if x < 90:
                left_ln = ln
            elif 135 <= x <= 300 and getattr(ln, "bold", False):
                mid_ln = ln
            elif x > 420:
                if _is_line_number_token(getattr(ln, "text", "")):
                    right_ln = ln

        if left_ln and mid_ln and right_ln:
            t = _norm(getattr(mid_ln, "text", ""))
            if not t:
                continue
            if _is_machine_annotation(t):
                continue
            if _GROUP_VISIT_RE.search(t):
                continue
            out.append((getattr(mid_ln, "y0", 0.0), t))

    out.sort(key=lambda p: p[0])
    return out


def _form_for_y(activity_entries: List[Tuple[float, str]], y: float) -> str:
    best = ""
    best_y = -1e9
    for ay, t in activity_entries:
        if ay < y and ay > best_y:
            best_y = ay
            best = t
    return best


def _is_answer_marker(ln) -> bool:
    if not _is_colored_headerish(ln):
        return False
    x = getattr(ln, "x0", 9999)
    y = getattr(ln, "y0", 9999)
    if y < 120:
        return False
    if not (100 <= x <= 320):
        return False
    t = _norm(getattr(ln, "text", ""))
    if not t.endswith(":"):
        return False
    tl = t.lower()
    # Keep broad but anchored to "answer" when present.
    if "answer" in tl or tl.startswith("ans"):
        return True
    # Fallback: the mid-column colored ":" marker is almost always the answer marker in this family.
    if 140 <= x <= 260 and len(t) <= 20:
        return True
    return False


def _is_staff_initials_marker(ln) -> bool:
    if not _is_colored_headerish(ln):
        return False
    t = _norm(getattr(ln, "text", ""))
    if not t.endswith(":"):
        return False
    tl = t.lower()
    if "initial" not in tl:
        return False
    if getattr(ln, "x0", 9999) > 200:
        return False
    return True


def _is_comment_marker(ln) -> bool:
    if not _is_colored_headerish(ln):
        return False
    t = _norm(getattr(ln, "text", ""))
    if not t.endswith(":"):
        return False
    tl = t.lower()
    if not tl.startswith("comment"):
        return False
    return True


def _is_group_visit_context(t: str) -> bool:
    if _GROUP_VISIT_RE.search(t):
        return True
    # Some pages have only a "Group, Visit: ... Final v1.0" context line.
    if ("group" in t.lower() and "visit" in t.lower() and _VERSIONISH_RE.search(t)):
        # Avoid false positives on genuine questions mentioning "visit"
        if t.lower().startswith("group") or "group," in t.lower():
            return True
    return False


def _is_section_header_not_field(t: str) -> bool:
    tl = t.lower()
    # These are section headers that should not be extracted as fields.
    if tl.startswith("vital signs") and "(" in tl and ")" in tl:
        return True
    if tl.startswith("vital signs") and ("supine" in tl or "standing" in tl) and "(" in tl:
        return True
    return False


def _is_option_only_line(t: str) -> bool:
    # Pure choice/option line (checkbox + option text), not a label.
    if not _GENERIC_CHOICE_LINE_RE.match(t):
        return False
    # If it clearly contains a question/label verb, don't treat as option-only (we'll strip prefix instead).
    tl = t.lower()
    if "?" in t or tl.startswith("if ") or " if " in tl or "does the" in tl or tl.startswith("does ") or tl.startswith("is ") or tl.startswith("are "):
        return False
    # Typical non-label option fragments.
    if "comment required" in tl or "activates line" in tl:
        return True
    # Starts with checkbox and a short option word, likely option-only.
    return True


def _strip_choice_prefix(t: str) -> str:
    t2 = _CHOICE_PREFIX_RE.sub("", t)
    return t2 if t2 != t else t


def _looks_like_measurement_label(t: str) -> bool:
    if not re.search(r"[A-Za-z]", t):
        return False
    if t.count("_") >= 2 or "##" in t or _NUM_FMT_RE.search(t):
        if _UNIT_RE.search(t):
            return True
        tl = t.lower()
        # Keywords that strongly indicate numeric-entry fields in this layout family.
        if any(k in tl for k in ["systolic", "diastolic", "heart rate", "respiratory rate", "oral temperature", "drop"]):
            return True
    return False


def _looks_like_field_labelish(t: str) -> bool:
    if not t:
        return False
    if _COL_HDR_RE.match(t):
        return False
    if _is_machine_annotation(t):
        return False
    if _is_group_visit_context(t):
        return False
    if _BULLETISH_RE.match(t):
        return False
    if _is_section_header_not_field(t):
        return False
    if _is_option_only_line(t):
        return False

    # Strong signals.
    if t.endswith("?") or t.endswith(":"):
        return True
    if _looks_like_measurement_label(t):
        return True

    tl = t.lower()
    if tl.startswith("confirm "):
        return True
    if tl.startswith("clinical assessment"):
        return True
    if " category" in tl:
        return True
    if tl.startswith("vital signs difference"):
        return True

    return False


def _clean_field_text(t: str) -> str:
    t = _norm(t)
    if not t:
        return ""
    if _is_group_visit_context(t):
        return ""

    # Strip leading checkbox/choice prefix when it got merged into the label.
    t = _strip_choice_prefix(t)

    # If we still have a leading checkbox marker, drop it cautiously.
    t = re.sub(r"^\s*(?:\d+\)\s*)?(?:O|0|\u25cb)\s+", "", t).strip()

    # For "Confirm ...:" style fields, keep the header only (avoid checklist bullets being merged).
    tl = t.lower()
    if tl.startswith("confirm ") and ":" in t:
        t = t.split(":", 1)[0].strip() + ":"

    # Remove leading/trailing stray punctuation.
    t = t.strip(" ;")
    t = _norm(t)

    # Guard against trivial/numeric-only.
    if re.fullmatch(r"[\d\.\-]+", t or ""):
        return ""
    if len(t) < 2:
        return ""

    return t


def _group_wrapped_labels(cands: List[Tuple[float, float, str]]) -> List[Tuple[float, str]]:
    """
    cands: (y, x, text) sorted by y,x
    returns: list of (anchor_y, merged_text)
    """
    merged: List[Tuple[float, str]] = []
    cur_parts: List[str] = []
    cur_y = None
    last_y = None
    last_x = None

    def _cur_text() -> str:
        return _norm(" ".join(cur_parts))

    def _flush():
        nonlocal cur_parts, cur_y, last_y, last_x
        if cur_parts:
            merged.append((cur_y if cur_y is not None else (last_y or 0.0), _cur_text()))
        cur_parts = []
        cur_y = None
        last_y = None
        last_x = None

    for y, x, t in cands:
        t = _norm(t)
        if not t:
            continue

        if not cur_parts:
            cur_parts = [t]
            cur_y = y
            last_y = y
            last_x = x
            continue

        cur_txt = _cur_text()
        cur_done = cur_txt.endswith("?") or cur_txt.endswith(":") or _looks_like_measurement_label(cur_txt)

        # Decide if this line is a wrap continuation.
        dy = (y - (last_y or y))
        dx = abs(x - (last_x or x))
        same_blockish = dy <= 14.5 and dx <= 90.0

        # Don't wrap-merge measurement lines (they're usually separate fields).
        if same_blockish and (not cur_done) and (not _looks_like_measurement_label(t)) and (not _looks_like_field_labelish(t)):
            # This is a weak line; avoid merging it.
            _flush()
            cur_parts = [t]
            cur_y = y
            last_y = y
            last_x = x
            continue

        if same_blockish and (not cur_done) and (not _looks_like_measurement_label(t)):
            # Likely wrapped question/instruction label.
            cur_parts.append(t)
            last_y = y
            last_x = x
            continue

        # Otherwise start a new field candidate.
        _flush()
        cur_parts = [t]
        cur_y = y
        last_y = y
        last_x = x

    _flush()
    return merged


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()

    current_schedule = ""
    current_form = ""

    for page_index0, lines in pages:
        if not _is_layout_page(lines):
            continue

        # Update schedule context if present.
        sched = _extract_schedule_context(lines)
        if sched:
            current_schedule = sched

        activity_entries = _build_activity_entries(lines)

        # Answer markers define stacked blocks in this family.
        answer_markers = [(i, getattr(ln, "y0", 0.0)) for i, ln in enumerate(lines) if _is_answer_marker(ln)]
        answer_markers.sort(key=lambda p: p[1])

        # Always extract Staff Initials / Comment markers (they're real data-entry fields).
        for ln in lines:
            if _looks_like_furniture(ln):
                continue
            y = getattr(ln, "y0", 0.0)
            t = _norm(getattr(ln, "text", ""))
            if not t:
                continue

            if _is_staff_initials_marker(ln) or _is_comment_marker(ln):
                form_here = _form_for_y(activity_entries, y + 0.01) or current_form or current_schedule or ""
                field = _clean_field_text(t)
                if not field:
                    continue
                rec = (page_index0 + 1, form_here, field)
                if rec in seen:
                    continue
                seen.add(rec)
                out.append({"form_name": form_here, "field_name": field, "page": page_index0 + 1})

        # If no answer markers, fall back to a conservative scan for obvious question/colon fields.
        if not answer_markers:
            for ln in lines:
                if _looks_like_furniture(ln):
                    continue
                if getattr(ln, "non_black", False):
                    continue
                if not (8.0 <= getattr(ln, "size", 0) <= 13.5):
                    continue
                x = getattr(ln, "x0", 0.0)
                if not (110 <= x <= 520):
                    continue
                t = _norm(getattr(ln, "text", ""))
                if not _looks_like_field_labelish(t):
                    continue
                field = _clean_field_text(t)
                if not field:
                    continue
                y = getattr(ln, "y0", 0.0)
                form_here = _form_for_y(activity_entries, y + 0.01) or current_form or current_schedule or ""
                rec = (page_index0 + 1, form_here, field)
                if rec in seen:
                    continue
                seen.add(rec)
                out.append({"form_name": form_here, "field_name": field, "page": page_index0 + 1})
            continue

        # Process each answer-marker block: extract all label-like lines above the marker within the block.
        marker_ys = [y for _, y in answer_markers]

        for mi, (idx, y_m) in enumerate(answer_markers):
            y_prev = marker_ys[mi - 1] if mi > 0 else None
            y_next = marker_ys[mi + 1] if mi + 1 < len(marker_ys) else None

            y_top = 0.0 if y_prev is None else (y_prev + y_m) / 2.0
            y_bot = 760.0 if y_next is None else (y_m + y_next) / 2.0

            # Collect black label candidates above the answer marker, within this block.
            cands: List[Tuple[float, float, str]] = []
            for ln in lines:
                y = getattr(ln, "y0", 0.0)
                if y < y_top or y > (y_m - 2.0):
                    continue
                if _looks_like_furniture(ln):
                    continue
                if getattr(ln, "non_black", False):
                    continue
                sz = getattr(ln, "size", 0.0)
                if not (8.0 <= sz <= 13.5):
                    continue
                x = getattr(ln, "x0", 0.0)
                if not (95 <= x <= 520):
                    continue
                # Exclude right-column line number tokens.
                if x > 430 and _is_line_number_token(getattr(ln, "text", "")):
                    continue

                t = _norm(getattr(ln, "text", ""))
                if not t:
                    continue
                if _COL_HDR_RE.match(t):
                    continue
                if _is_machine_annotation(t):
                    continue
                if _is_group_visit_context(t):
                    continue
                if _BULLETISH_RE.match(t):
                    continue
                if _is_section_header_not_field(t):
                    continue

                # Exclude pure option lines, but keep in case it's merged (we'll strip later) if it clearly contains label punctuation.
                if _is_option_only_line(t) and ("?" not in t and ":" not in t):
                    continue

                # Keep only label-ish lines or lines that help wrap labels.
                # (We allow non-terminal wrap fragments here; grouping later merges them.)
                cands.append((y, x, t))

            cands.sort(key=lambda p: (p[0], p[1]))
            merged = _group_wrapped_labels(cands)

            for y_anchor, raw_field in merged:
                if not raw_field:
                    continue
                if not _looks_like_field_labelish(raw_field):
                    continue
                field = _clean_field_text(raw_field)
                if not field:
                    continue

                # If a "Confirm ...:" header got OCR-merged with trailing checklist text, enforce header-only.
                if field.lower().startswith("confirm ") and ":" in field and len(field) > 70:
                    field = field.split(":", 1)[0].strip() + ":"

                form_here = _form_for_y(activity_entries, y_anchor + 0.01) or current_form or current_schedule or ""
                rec = (page_index0 + 1, form_here, field)
                if rec in seen:
                    continue
                seen.add(rec)
                out.append({"form_name": form_here, "field_name": field, "page": page_index0 + 1})

            # Carry forward a plausible form context for later blocks/pages.
            form_for_block = _form_for_y(activity_entries, min(y_bot, y_m) + 0.01)
            if form_for_block:
                current_form = form_for_block

        # If page has activity entries, keep the last one as carry-forward.
        if activity_entries:
            current_form = activity_entries[-1][1] or current_form

    return out
```
