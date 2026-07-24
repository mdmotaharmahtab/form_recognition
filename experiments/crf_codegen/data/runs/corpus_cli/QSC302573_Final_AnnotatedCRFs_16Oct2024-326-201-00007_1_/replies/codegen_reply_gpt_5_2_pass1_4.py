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
_GENERIC_CHOICE_LINE_RE = re.compile(r"^\s*(?:\d+\)\s*)?(?:O|0|\u25cb)\s+\S+", re.IGNORECASE)

_BULLETISH_RE = re.compile(r"^\s*[-–•]\s+")

# Column header tokens to ignore.
_COL_HDR_RE = re.compile(r"^(Timepoint|Activity|Line\s*#|Line#)$", re.IGNORECASE)

# Box / placeholder artifacts that appear near labels.
_BOX = r"(?:_\s*){2,}"
_TIME_BOX_RE = re.compile(rf"^\s*{_BOX}\s*:\s*{_BOX}\s*", re.IGNORECASE)
_DATE_BOX_RE = re.compile(rf"^\s*{_BOX}\s*/\s*{_BOX}\s*/\s*(?:_\s*){{3,}}\s*", re.IGNORECASE)
_LEADING_BOXISH_RE = re.compile(rf"^\s*{_BOX}\s*(?:[.:/]\s*{_BOX}\s*)+", re.IGNORECASE)
_TRAILING_BOXISH_RE = re.compile(rf"\s*(?:[.:/]\s*{_BOX}\s*)+(\s*[A-Za-z]{{1,3}})?\s*$", re.IGNORECASE)
_PARENS_NUM_FMT_RE = re.compile(r"\(\s*#+(?:\.\d+)?\s*\)", re.IGNORECASE)
_HHMM_TOKEN_RE = re.compile(r"^\s*HH\s*:\s*mm\s*$", re.IGNORECASE)

# Format-parens that often belong to entry templates, not labels.
_PARENS_DATEFMT_RE = re.compile(r"\(\s*dd\s*-\s*mmm\s*-\s*yyyy\s*\)", re.IGNORECASE)
_PARENS_TIMEFMT_RE = re.compile(r"\(\s*HH\s*:\s*mm\s*\)", re.IGNORECASE)

# Template-only "Date ____ (dd-MMM-yyyy)" / "Time __:__ (HH:mm)" lines (not fields).
_DATE_TEMPLATE_ONLY_RE = re.compile(
    r"^\s*Date\b.*(?:_\s*){2,}.*\(\s*dd\s*-\s*mmm\s*-\s*yyyy\s*\)\s*$",
    re.IGNORECASE,
)
_TIME_TEMPLATE_ONLY_RE = re.compile(
    r"^\s*Time\b.*(?:_\s*){2,}.*\(\s*HH\s*:\s*mm\s*\)\s*$",
    re.IGNORECASE,
)

# "On Study ... x:" row/column tokens that are not fields in this family.
_ON_STUDY_X_RE = re.compile(r"^\s*On\s+Study\b.*\bx\s*:\s*", re.IGNORECASE)

# Calculated/non-entry vitals "Drop ____ mmHg" templates on difference pages.
_DROP_TEMPLATE_RE = re.compile(
    r"\b(?:Systolic|Diastolic)\s+Drop\b.*(?:_\s*){2,}.*\bmmHg\b",
    re.IGNORECASE,
)

# Form-name machine prefix patterns.
_FORM_CODE_PREFIX_RE = re.compile(r"^\s*[A-Z]{1,5}_[A-Z0-9]{4,}\s*,\s*\d+\s*-\s*", re.IGNORECASE)

# Form-title-ish (activities) often end with "#N" and contain a colon; those are not fields.
_FORM_TITLEISH_RE = re.compile(r".+:\s+.+#\d+\s*$")


def _norm(s: str) -> str:
    s = (s or "").replace("\u00ad", "").replace("\u200b", "")
    s = _WS_RE.sub(" ", s).strip()
    return s


def _is_machine_annotation(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return False
    if "SAS:[" in t or "SAS:" in t:
        return True
    if _MACHINE_RE.match(t):
        return True
    # Common CRF-ish code lines that shouldn't become labels/forms.
    if re.match(r"^\s*[A-Z]{1,5}_[A-Z0-9]{4,}\b", t):
        return True
    return False


def _looks_like_furniture(line) -> bool:
    t = (getattr(line, "text", "") or "").strip()
    if not t:
        return True
    # Bottom-of-page furniture
    if getattr(line, "y0", 0) > 730:
        return True
    if _PAGE_FURN_RE.match(t):
        return True
    return False


def _is_colored_headerish(line) -> bool:
    return bool(
        getattr(line, "non_black", False)
        and getattr(line, "bold", False)
        and 8.0 <= getattr(line, "size", 0) <= 13.5
    )


def _is_layout_page(lines) -> bool:
    if not lines:
        return False

    # Large colored title near the top.
    has_title = any(
        (
            getattr(ln, "non_black", False)
            and getattr(ln, "bold", False)
            and getattr(ln, "size", 0) >= 18
            and getattr(ln, "y0", 9999) < 80
        )
        for ln in lines
    )

    # Column headers around y~90-160 (this family usually has them).
    hdr = 0
    for ln in lines:
        if not _is_colored_headerish(ln):
            continue
        y = getattr(ln, "y0", 9999)
        if not (85 <= y <= 170):
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        # Avoid counting stray colored labels like "Answer:" as column headers.
        if t.lower() in ("answer:", "ans:", "response:", "resp:", "slot:"):
            continue
        hdr += 1

    return has_title and hdr >= 2


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
    t = (s or "").strip()
    return bool(re.match(r"^\d+(\.\d+)?(\s*\(.*\))?\s*$", t))


def _clean_form_name(t: str) -> str:
    t = _norm(t)
    if not t:
        return ""
    if _is_machine_annotation(t):
        return ""
    if _GROUP_VISIT_RE.search(t):
        return ""
    # Strip common code prefix and trailing "Final vX.Y".
    t = _FORM_CODE_PREFIX_RE.sub("", t)
    t = re.sub(r"\bFinal\s+v\d+(\.\d+)*\b", "", t, flags=re.IGNORECASE).strip()
    t = _norm(t)
    # Too code-ish even after cleaning.
    if re.match(r"^\s*[A-Z]{1,5}_[A-Z0-9]{4,}\b", t):
        return ""
    return t


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
        t = _clean_form_name(getattr(ln, "text", ""))
        if not t:
            continue
        if y < best_y:
            best, best_y = t, y
    return best


def _build_activity_entries(lines) -> List[Tuple[float, str]]:
    rows = _build_rows(lines)
    out: List[Tuple[float, str]] = []
    for _, row in rows.items():
        left_ln = None
        mid_ln = None
        right_ln = None

        for _, ln in row:
            if _looks_like_furniture(ln):
                continue
            x = getattr(ln, "x0", 0)
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
            t = _clean_form_name(getattr(mid_ln, "text", ""))
            if not t:
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
    return tl in ("answer:", "ans:", "response:", "resp:")


def _is_staff_initials_marker(ln) -> bool:
    if not _is_colored_headerish(ln):
        return False
    # Suppress repeating template furniture by position.
    y = getattr(ln, "y0", 9999)
    if not (180 <= y <= 690):
        return False
    t = _norm(getattr(ln, "text", ""))
    if not t.endswith(":"):
        return False
    tl = t.lower()
    if "initial" not in tl:
        return False
    if getattr(ln, "x0", 9999) > 220:
        return False
    return True


def _is_comment_marker(ln) -> bool:
    if not _is_colored_headerish(ln):
        return False
    # Suppress repeating template furniture by position.
    y = getattr(ln, "y0", 9999)
    if not (180 <= y <= 690):
        return False
    t = _norm(getattr(ln, "text", ""))
    if not t.endswith(":"):
        return False
    return t.lower().startswith("comment")


def _is_group_visit_context(t: str) -> bool:
    if _GROUP_VISIT_RE.search(t):
        return True
    if ("group" in t.lower() and "visit" in t.lower() and _VERSIONISH_RE.search(t)):
        if t.lower().startswith("group") or "group," in t.lower():
            return True
    return False


def _is_section_header_not_field(t: str) -> bool:
    tl = t.lower().strip()
    # Vital signs section headers (not the individual Systolic/Diastolic/etc fields).
    if tl.startswith("vital signs") and ("(" in tl and ")" in tl):
        return True
    if tl.startswith("vital signs") and ("supine" in tl or "standing" in tl) and "(" in tl:
        return True
    # Calculated header in the Standing/Supine difference pages.
    if tl.startswith("vital signs difference:") and ("calculation" in tl or "bp and hr" in tl):
        return True
    # Common non-field colored/label-ish tokens.
    if tl in ("slot:", "answer:", "ans:", "response:", "resp:"):
        return True
    return False


def _is_option_only_line(t: str) -> bool:
    if not _GENERIC_CHOICE_LINE_RE.match(t):
        return False
    tl = t.lower()
    if "?" in t or tl.startswith("if ") or " if " in tl or tl.startswith("does ") or tl.startswith("is ") or tl.startswith("are "):
        return False
    if "comment required" in tl or "activates line" in tl:
        return True
    return True


def _strip_choice_prefix(t: str) -> str:
    t2 = _CHOICE_PREFIX_RE.sub("", t)
    return t2 if t2 != t else t


_MEAS_KEYS = (
    "systolic",
    "diastolic",
    "heart rate",
    "respiratory rate",
    "oral temperature",
    "degrees celsius",
)


def _looks_like_measurement_label(t: str) -> bool:
    tl = t.lower()
    if "drop" in tl:
        return False
    if any(k in tl for k in _MEAS_KEYS):
        return True
    # Short single-word vitals often appear without units.
    if tl.strip() in ("systolic", "diastolic", "pulse", "temperature"):
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

    # Drop template-only "Date/Time ____ (format)" lines.
    if _DATE_TEMPLATE_ONLY_RE.match(t) or _TIME_TEMPLATE_ONLY_RE.match(t):
        return False

    # Drop calculated drop templates.
    if _DROP_TEMPLATE_RE.search(t):
        return False

    # Strong signals.
    if t.endswith("?") or t.endswith(":"):
        if t.lower().strip() in ("slot:", "answer:", "ans:", "response:", "resp:"):
            return False
        return True
    if _looks_like_measurement_label(t):
        return True

    tl = t.lower()

    # Common label starters in this family.
    starters = (
        "date ",
        "time ",
        "record ",
        "for what ",
        "what is ",
        "confirm ",
        "clinical assessment",
        "physical examination",
        "targeted physical examination",
        "additional icf",
        "study icf",
        "sponsor specific",
        "has the participant",
        "was a copy",
        "is there",
        "if yes",
        "if 'yes'",
    )
    if tl.startswith(starters):
        return True

    # Mid-sentence anchors that often appear without punctuation.
    if any(k in tl for k in (" version", " part", " status of the subject", " category", " indication", "full name")):
        return True

    # Parenthetical label qualifiers like "(full name)" or "(Indication)".
    if re.search(r"\(\s*(full name|indication|allocated sequentially)\s*[^)]*\)\s*$", t, flags=re.IGNORECASE):
        return True

    return False


def _strip_entry_templates(t: str) -> str:
    t0 = _norm(t)
    if not t0:
        return ""
    # Leading date/time boxes.
    t1 = _DATE_BOX_RE.sub("", t0)
    t1 = _TIME_BOX_RE.sub("", t1)
    t1 = _LEADING_BOXISH_RE.sub("", t1)

    # Leading "HH:mm" token artifacts.
    t1 = re.sub(r"^\s*HH\s*:\s*mm\s*", "", t1, flags=re.IGNORECASE)

    # Trailing box templates and numeric format parens like "(##.0)".
    t1 = _PARENS_NUM_FMT_RE.sub("", t1)
    t1 = _TRAILING_BOXISH_RE.sub("", t1)

    # Remove common format-parens that are template hints.
    t1 = _PARENS_DATEFMT_RE.sub("", t1)
    t1 = _PARENS_TIMEFMT_RE.sub("", t1)

    # Trailing Celsius unit sometimes follows templates; keep unit only if attached to label.
    t1 = re.sub(r"\s*(?:_\s*){2,}\s*C\b", " C", t1, flags=re.IGNORECASE)

    return _norm(t1)


def _clean_field_text(t: str) -> str:
    t_orig = _norm(t)
    t = t_orig
    if not t:
        return ""
    if _is_group_visit_context(t) or _is_machine_annotation(t):
        return ""
    if _is_section_header_not_field(t):
        return ""

    # Drop template-only Date/Time lines.
    if _DATE_TEMPLATE_ONLY_RE.match(t_orig) or _TIME_TEMPLATE_ONLY_RE.match(t_orig):
        return ""

    # Drop calculated "Drop ____ mmHg" templates.
    if _DROP_TEMPLATE_RE.search(t_orig):
        return ""

    # Drop "On Study ... x:" row/column labels.
    if _ON_STUDY_X_RE.match(t_orig):
        return ""

    # Strip leading checkbox/choice prefix when it got merged into the label.
    t = _strip_choice_prefix(t)

    # If we still have a leading checkbox marker, drop it cautiously.
    t = re.sub(r"^\s*(?:\d+\)\s*)?(?:O|0|\u25cb)\s+", "", t).strip()

    # Remove box/template artifacts around the label.
    t = _strip_entry_templates(t)

    # Drop obvious non-label placeholder-only tokens.
    if not t:
        return ""
    if _HHMM_TOKEN_RE.match(t):
        return ""
    if re.fullmatch(r"[_\s:./-]+", t):
        return ""
    if re.fullmatch(r"[\d\.\-]+", t):
        return ""

    # Suppress recurring non-field token that was being extracted.
    if t.lower().strip() == "slot:":
        return ""

    # For "Confirm ...:" style fields, keep the header only (avoid OCR-merged checklist tails).
    tl = t.lower()
    if tl.startswith("confirm ") and ":" in t:
        t = t.split(":", 1)[0].strip() + ":"

    # Remove leading/trailing stray punctuation.
    t = t.strip(" ;")
    t = _norm(t)

    # Avoid extracting tiny fragments (e.g., the second wrapped line alone).
    if len(t) < 2:
        return ""

    return t


def _collect_black_cands(lines, y_top: float = 0.0, y_bot: float = 760.0) -> List[Tuple[float, float, str]]:
    cands: List[Tuple[float, float, str]] = []
    for ln in lines:
        y = getattr(ln, "y0", 0.0)
        if y < y_top or y > y_bot:
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

        # Exclude pure option lines, but keep if label punctuation is present (merged labels).
        if _is_option_only_line(t) and ("?" not in t and ":" not in t):
            continue

        # Exclude template-only Date/Time lines early.
        if _DATE_TEMPLATE_ONLY_RE.match(t) or _TIME_TEMPLATE_ONLY_RE.match(t):
            continue

        # Exclude calculated "Drop ____ mmHg" templates early.
        if _DROP_TEMPLATE_RE.search(t):
            continue

        # Exclude "On Study ... x:" row/column labels.
        if _ON_STUDY_X_RE.match(t):
            continue

        cands.append((y, x, t))

    cands.sort(key=lambda p: (p[0], p[1]))
    return cands


def _group_wrapped_labels(cands: List[Tuple[float, float, str]]) -> List[Tuple[float, str]]:
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
            cur_y, last_y, last_x = y, y, x
            continue

        cur_txt = _cur_text()
        cur_done = cur_txt.endswith("?") or cur_txt.endswith(":") or _looks_like_measurement_label(cur_txt)

        dy = y - (last_y or y)
        dx = abs(x - (last_x or x))
        same_blockish = dy <= 14.5 and dx <= 120.0

        if same_blockish and (not cur_done) and (not _looks_like_measurement_label(t)):
            # Treat weak lowercase-starting lines (e.g., "where ...") as continuations.
            if t and t[:1].islower():
                cur_parts.append(t)
                last_y, last_x = y, x
                continue
            # If the next line is not a strong new label, also merge it.
            if not _looks_like_field_labelish(_strip_entry_templates(_strip_choice_prefix(t))):
                cur_parts.append(t)
                last_y, last_x = y, x
                continue

        # If current isn't done and the next line is close, merge unless it's clearly a new field.
        if same_blockish and (not cur_done) and (not _looks_like_measurement_label(t)):
            cur_parts.append(t)
            last_y, last_x = y, x
            continue

        _flush()
        cur_parts = [t]
        cur_y, last_y, last_x = y, y, x

    _flush()
    return merged


def _is_spurious_form_title(field: str, form_here: str, schedule: str, activity_names: set) -> bool:
    f = _norm(field)
    if not f:
        return True

    # If a "field" equals a known form title, it's not a data-entry field.
    if form_here and _norm(form_here) == f:
        return True
    if schedule and _norm(schedule) == f:
        return True
    if f in activity_names:
        return True

    # Activity-title-like lines: "...: ... #N" (even if they contain a "?").
    if _FORM_TITLEISH_RE.match(f):
        return True

    return False


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()

    current_schedule = ""
    current_form = ""

    for page_index0, lines in pages:
        if not _is_layout_page(lines):
            continue

        sched = _extract_schedule_context(lines)
        if sched:
            current_schedule = sched

        activity_entries = _build_activity_entries(lines)
        activity_names = set(t for _, t in activity_entries if t)

        def _form_at(y: float) -> str:
            return _form_for_y(activity_entries, y + 0.01) or current_form or current_schedule or ""

        # Staff Initials / Comment markers can be real fields in this family, but
        # suppress repeating template furniture and spurious title-like captures.
        for ln in lines:
            if _looks_like_furniture(ln):
                continue
            y = getattr(ln, "y0", 0.0)
            t = _norm(getattr(ln, "text", ""))
            if not t:
                continue
            if _is_staff_initials_marker(ln) or _is_comment_marker(ln):
                field = _clean_field_text(t)
                if not field:
                    continue
                form_here = _form_at(y)
                if _is_spurious_form_title(field, form_here, current_schedule, activity_names):
                    continue
                rec = (page_index0 + 1, form_here, field)
                if rec in seen:
                    continue
                seen.add(rec)
                out.append({"form_name": form_here, "field_name": field, "page": page_index0 + 1})

        # Use answer markers as block anchors when present.
        answer_markers = [(i, getattr(ln, "y0", 0.0)) for i, ln in enumerate(lines) if _is_answer_marker(ln)]
        answer_markers.sort(key=lambda p: p[1])

        marker_ys = [y for _, y in answer_markers]
        if answer_markers:
            for mi, (_, y_m) in enumerate(answer_markers):
                y_prev = marker_ys[mi - 1] if mi > 0 else None
                y_next = marker_ys[mi + 1] if mi + 1 < len(marker_ys) else None
                y_top = 0.0 if y_prev is None else (y_prev + y_m) / 2.0
                y_bot = 760.0 if y_next is None else (y_m + y_next) / 2.0

                cands = _collect_black_cands(lines, y_top=y_top, y_bot=max(y_top, y_m - 2.0))
                merged = _group_wrapped_labels(cands)

                for y_anchor, raw in merged:
                    if not raw:
                        continue
                    field = _clean_field_text(raw)
                    if not field:
                        continue
                    form_here = _form_at(y_anchor)
                    if _is_spurious_form_title(field, form_here, current_schedule, activity_names):
                        continue
                    if not _looks_like_field_labelish(field):
                        continue
                    # Cap absurdly long instruction blobs.
                    if len(field) > 260 and ("?" not in field and ":" not in field):
                        continue

                    rec = (page_index0 + 1, form_here, field)
                    if rec in seen:
                        continue
                    seen.add(rec)
                    out.append({"form_name": form_here, "field_name": field, "page": page_index0 + 1})

                # Carry forward form context.
                form_for_block = _form_for_y(activity_entries, min(y_bot, y_m) + 0.01)
                if form_for_block:
                    current_form = form_for_block

        # Page-wide conservative pass to catch labels that don't sit cleanly above an answer marker.
        page_cands = _collect_black_cands(lines, y_top=0.0, y_bot=760.0)
        page_merged = _group_wrapped_labels(page_cands)
        for y_anchor, raw in page_merged:
            field = _clean_field_text(raw)
            if not field:
                continue
            form_here = _form_at(y_anchor)
            if _is_spurious_form_title(field, form_here, current_schedule, activity_names):
                continue
            if not _looks_like_field_labelish(field):
                continue
            if len(field) > 260 and ("?" not in field and ":" not in field):
                continue

            rec = (page_index0 + 1, form_here, field)
            if rec in seen:
                continue
            seen.add(rec)
            out.append({"form_name": form_here, "field_name": field, "page": page_index0 + 1})

        if activity_entries:
            current_form = activity_entries[-1][1] or current_form

    return out
```
