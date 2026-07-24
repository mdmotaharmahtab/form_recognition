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
_COL_HDR_RE = re.compile(r"^(Timepoint|Activity|Line\s*#|Line#)$", re.IGNORECASE)

# Box / placeholder artifacts that appear near labels.
_BOX = r"(?:_\s*){2,}"
_TIME_BOX_RE = re.compile(rf"^\s*{_BOX}\s*:\s*{_BOX}\s*", re.IGNORECASE)
_DATE_BOX_RE = re.compile(rf"^\s*{_BOX}\s*/\s*{_BOX}\s*/\s*(?:_\s*){{3,}}\s*", re.IGNORECASE)
_LEADING_BOXISH_RE = re.compile(rf"^\s*{_BOX}\s*(?:[.:/]\s*{_BOX}\s*)+", re.IGNORECASE)
_TRAILING_BOXISH_RE = re.compile(rf"\s*(?:[.:/]\s*{_BOX}\s*)+(\s*[A-Za-z]{{1,3}})?\s*$", re.IGNORECASE)

# Inline templates that show up mid-line due to OCR/column merges.
_INLINE_TIMEBOX_RE = re.compile(rf"\s*{_BOX}\s*:\s*{_BOX}\s*", re.IGNORECASE)
_INLINE_DATEBOX_RE = re.compile(rf"\s*{_BOX}\s*/\s*{_BOX}\s*/\s*(?:_\s*){{3,}}\s*", re.IGNORECASE)
_INLINE_PLACEHOLDERS_RE = re.compile(r"(?:_\s*){3,}", re.IGNORECASE)

# Numeric format parens like "(##.0)" or "(####)".
_PARENS_NUM_FMT_RE = re.compile(r"\(\s*#+(?:\.\d+)?\s*\)", re.IGNORECASE)

# Tokens from time templates that contaminate nearby labels.
_HHMM_TOKEN_RE = re.compile(r"^\s*HH\s*:\s*mm\s*$", re.IGNORECASE)
_HHMM_ANYWHERE_RE = re.compile(r"\bHH\s*:\s*mm\b", re.IGNORECASE)
_HH_COLON_ANYWHERE_RE = re.compile(r"\bHH\s*:\s*([;:,\)\]]|$)", re.IGNORECASE)

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

# Form-name machine prefix patterns.
_FORM_CODE_PREFIX_RE = re.compile(r"^\s*[A-Z]{1,5}_[A-Z0-9]{4,}\s*,\s*\d+\s*-\s*", re.IGNORECASE)
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
    if re.match(r"^\s*[A-Z]{1,5}_[A-Z0-9]{4,}\b", t):
        return True
    return False


def _looks_like_furniture(line) -> bool:
    t = (getattr(line, "text", "") or "").strip()
    if not t:
        return True
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

    has_title = any(
        (
            getattr(ln, "non_black", False)
            and getattr(ln, "bold", False)
            and getattr(ln, "size", 0) >= 18
            and getattr(ln, "y0", 9999) < 80
        )
        for ln in lines
    )

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
    t = _FORM_CODE_PREFIX_RE.sub("", t)
    t = re.sub(r"\bFinal\s+v\d+(\.\d+)*\b", "", t, flags=re.IGNORECASE).strip()
    t = _norm(t)
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


def _is_staff_initials_text(t: str) -> bool:
    tl = _norm(t).lower()
    return bool(tl == "staff initials:" or (tl.startswith("staff initials") and tl.endswith(":")))


def _is_comment_text(t: str) -> bool:
    tl = _norm(t).lower()
    return bool(tl == "comment:" or (tl.startswith("comment") and tl.endswith(":")))


def _is_staff_initials_marker(ln) -> bool:
    t = _norm(getattr(ln, "text", ""))
    if not t or not _is_staff_initials_text(t):
        return False
    y = getattr(ln, "y0", 9999)
    if not (165 <= y <= 705):
        return False
    x = getattr(ln, "x0", 9999)
    if x > 340:
        return False
    sz = getattr(ln, "size", 0.0)
    if not (7.5 <= sz <= 14.5):
        return False
    return True


def _is_comment_marker(ln) -> bool:
    t = _norm(getattr(ln, "text", ""))
    if not t or not _is_comment_text(t):
        return False
    y = getattr(ln, "y0", 9999)
    if not (165 <= y <= 705):
        return False
    x = getattr(ln, "x0", 9999)
    if x > 360:
        return False
    sz = getattr(ln, "size", 0.0)
    if not (7.5 <= sz <= 14.5):
        return False
    return True


def _is_group_visit_context(t: str) -> bool:
    if _GROUP_VISIT_RE.search(t):
        return True
    if ("group" in t.lower() and "visit" in t.lower() and _VERSIONISH_RE.search(t)):
        if t.lower().startswith("group") or "group," in t.lower():
            return True
    return False


def _is_section_header_not_field(t: str) -> bool:
    tl = t.lower().strip()
    if tl.startswith("vital signs") and ("(" in tl and ")" in tl):
        return True
    if tl.startswith("vital signs") and ("supine" in tl or "standing" in tl) and "(" in tl:
        return True
    if tl.startswith("vital signs difference:") and ("calculation" in tl or "bp and hr" in tl):
        return True
    if tl in ("slot:", "answer:", "ans:", "response:", "resp:"):
        return True
    if tl.startswith("targeted physical examination findings:"):
        return True
    return False


def _option_has_payload_field(t: str) -> bool:
    tl = (t or "").lower()
    if "specify" in tl:
        return True
    if "activates line" in tl:
        return True
    if "char" in tl and "max" in tl:
        return True
    if _INLINE_PLACEHOLDERS_RE.search(t or ""):
        return True
    return False


def _is_option_only_line(t: str) -> bool:
    if not _GENERIC_CHOICE_LINE_RE.match(t):
        return False
    if _option_has_payload_field(t):
        return False
    tl = t.lower()
    if "?" in t or tl.startswith("if ") or " if " in tl or tl.startswith("does ") or tl.startswith("is ") or tl.startswith("are "):
        return False
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
    if any(k in tl for k in _MEAS_KEYS):
        return True
    if tl.strip() in ("systolic", "diastolic", "pulse", "temperature"):
        return True
    # Difference page data-entry fields.
    if " drop" in tl and ("systolic" in tl or "diastolic" in tl) and ("mmhg" in tl):
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

    if _DATE_TEMPLATE_ONLY_RE.match(t) or _TIME_TEMPLATE_ONLY_RE.match(t):
        return False

    # Choice lines: keep only those with an actual payload field (Specify/blank/etc).
    if _GENERIC_CHOICE_LINE_RE.match(t):
        return _option_has_payload_field(t)

    if t.endswith("?") or t.endswith(":"):
        if t.lower().strip() in ("slot:", "answer:", "ans:", "response:", "resp:"):
            return False
        return True
    if _looks_like_measurement_label(t):
        return True

    tl = t.lower()

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

    if any(k in tl for k in (" version", " part", " status of the subject", " category", " indication", "full name")):
        return True

    if re.search(r"\(\s*(full name|indication|allocated sequentially)\s*[^)]*\)\s*$", t, flags=re.IGNORECASE):
        return True

    # Short but meaningful noun-ish labels in this family.
    if tl.strip() in ("year of birth",):
        return True

    return False


def _strip_hhmm_artifacts(t: str) -> str:
    if not t:
        return ""
    t = _HHMM_ANYWHERE_RE.sub(" ", t)
    t = _HH_COLON_ANYWHERE_RE.sub(" ", t)
    return _norm(t)


def _strip_entry_templates(t: str) -> str:
    t0 = _norm(t)
    if not t0:
        return ""

    t1 = t0
    # Remove inline date/time boxes anywhere (not just leading).
    t1 = _INLINE_DATEBOX_RE.sub(" ", t1)
    t1 = _INLINE_TIMEBOX_RE.sub(" ", t1)

    # Leading date/time boxes.
    t1 = _DATE_BOX_RE.sub("", t1)
    t1 = _TIME_BOX_RE.sub("", t1)
    t1 = _LEADING_BOXISH_RE.sub("", t1)

    # Remove raw "HH:mm" template tokens that get merged into labels.
    t1 = _strip_hhmm_artifacts(t1)

    # Trailing box templates and numeric format parens like "(##.0)" or "(####)".
    t1 = _PARENS_NUM_FMT_RE.sub("", t1)
    t1 = _TRAILING_BOXISH_RE.sub("", t1)

    # Remove common format-parens that are template hints.
    t1 = _PARENS_DATEFMT_RE.sub("", t1)
    t1 = _PARENS_TIMEFMT_RE.sub("", t1)

    # Remove long underscore placeholders (keeps the label text around them).
    t1 = _INLINE_PLACEHOLDERS_RE.sub(" ", t1)

    # Normalize punctuation spacing after deletions.
    t1 = re.sub(r"\s+([,;:.])", r"\1", t1)
    t1 = re.sub(r"\(\s*\)", "", t1)

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

    # Drop "On Study ... x:" row/column labels.
    if _ON_STUDY_X_RE.match(t_orig):
        return ""

    # Strip leading checkbox/choice prefix when it got merged into the label.
    t = _strip_choice_prefix(t)

    # If we still have a leading checkbox marker, drop it cautiously.
    t = re.sub(r"^\s*(?:\d+\)\s*)?(?:O|0|\u25cb)\s+", "", t).strip()

    # Remove box/template artifacts around the label.
    t = _strip_entry_templates(t)

    if not t:
        return ""

    # Drop obvious non-label placeholder-only tokens.
    if _HHMM_TOKEN_RE.match(t):
        return ""
    if re.fullmatch(r"[_\s:./-]+", t):
        return ""
    if re.fullmatch(r"[\d\.\-]+", t):
        return ""

    if t.lower().strip() == "slot:":
        return ""

    # Fix merged "heading + time template + real question" cases by keeping the actual question.
    m_if_yes = re.search(r"\bIf\s+yes\b", t, flags=re.IGNORECASE)
    if m_if_yes and m_if_yes.start() > 0:
        prefix = t[: m_if_yes.start()].lower()
        if (":" in prefix) or ("#" in prefix) or ("findings" in prefix):
            t = t[m_if_yes.start() :].lstrip(" ,;:-")

    # For "Confirm ...:" style fields, keep the header only (avoid OCR-merged checklist tails).
    tl = t.lower()
    if tl.startswith("confirm ") and ":" in t:
        t = t.split(":", 1)[0].strip() + ":"

    # Clean up stray punctuation left by artifact stripping.
    t = re.sub(r"\s+([,;:.?])", r"\1", t)
    t = re.sub(r"([(\[])\s+", r"\1", t)
    t = re.sub(r"\s+([)\]])", r"\1", t)
    t = t.strip(" ;")
    t = _norm(t)

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
        if not (7.5 <= sz <= 14.5):
            continue
        x = getattr(ln, "x0", 0.0)

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

        # Keep Staff Initials / Comment even when left-aligned; otherwise keep main body region.
        if not (_is_staff_initials_text(t) or _is_comment_text(t)):
            if not (70 <= x <= 520):
                continue

        # Exclude right-column line number tokens.
        if x > 430 and _is_line_number_token(getattr(ln, "text", "")):
            continue

        # Exclude pure option lines, but keep options that contain an actual payload (Specify/blank/etc).
        if _is_option_only_line(t) and ("?" not in t and ":" not in t):
            continue

        if _DATE_TEMPLATE_ONLY_RE.match(t) or _TIME_TEMPLATE_ONLY_RE.match(t):
            continue

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
        same_blockish = dy <= 14.5 and dx <= 140.0

        if same_blockish and (not cur_done) and (not _looks_like_measurement_label(t)):
            # Weak lowercase-starting lines (e.g., "where ...") are continuations.
            if t and t[:1].islower():
                cur_parts.append(t)
                last_y, last_x = y, x
                continue
            # Merge if the next line isn't a strong new field label.
            t_probe = _strip_entry_templates(_strip_choice_prefix(t))
            if not _looks_like_field_labelish(t_probe):
                cur_parts.append(t)
                last_y, last_x = y, x
                continue

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

    if form_here and _norm(form_here) == f:
        return True
    if schedule and _norm(schedule) == f:
        return True
    if f in activity_names:
        return True

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

        # Staff Initials / Comment: collect by content/position, but attach to local form context.
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
                    if len(field) > 260 and ("?" not in field and ":" not in field):
                        continue

                    rec = (page_index0 + 1, form_here, field)
                    if rec in seen:
                        continue
                    seen.add(rec)
                    out.append({"form_name": form_here, "field_name": field, "page": page_index0 + 1})

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
