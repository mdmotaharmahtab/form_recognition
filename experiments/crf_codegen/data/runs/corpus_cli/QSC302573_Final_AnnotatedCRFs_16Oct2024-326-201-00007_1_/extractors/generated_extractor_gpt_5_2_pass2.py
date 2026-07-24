# Layout observed: "Annotated CRF" pages with a fixed header, a blue table-header row,
# and repeated activity blocks. Each block has an activity/title line (bold black) with
# a line-number at far right, followed by one or more bold-black question/label lines.
# Strategy: detect this layout by header geometry, track current schedule/activity as
# form_name, and extract bold-black question labels plus left-column blue field labels
# (e.g., Staff Initials / Comment), while excluding options and machine annotations.

import re
from typing import List, Tuple, Dict, Any, Optional

# ---- heuristics helpers ----

_WS_RE = re.compile(r"\s+")
_LINE_NO_RE = re.compile(r"^\s*\d+(?:\.\d+)?")
_MACHINE_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")

def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())

def _is_machine_annotation(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _MACHINE_RE.match(t):
        return True
    # Common annotated-CRF machine/meta lines
    if "SAS:[" in t or "DataType=" in t or "Length=" in t:
        return True
    if t.startswith("[") and "]" in t[:25]:
        return True
    return False

def _is_option_text(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    # Typical option bullets in this CRF: "O Yes", "O 1 - ...", etc.
    if re.match(r"^[Oo]\s+\S", t):
        return True
    # Also treat checkbox/circle unicode bullets as options if present
    if t[:1] in ("○", "◯", "●", "▪", "□", "■"):
        return True
    return False

def _group_rows(lines, y_tol: float = 1.2):
    # lines are sorted by y then x; group by visual rows using y0
    rows = []
    cur = []
    cur_y = None
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if cur_y is None or abs(y - cur_y) <= y_tol:
            cur.append(ln)
            if cur_y is None:
                cur_y = y
            else:
                # running average for stability
                cur_y = (cur_y * (len(cur) - 1) + y) / len(cur)
        else:
            rows.append((cur_y, cur))
            cur = [ln]
            cur_y = y
    if cur:
        rows.append((cur_y, cur))
    return rows

def _looks_like_layout(lines) -> bool:
    # Large colored title near top + blue bold table header row with 3 columns.
    if not lines:
        return False

    has_big_colored_title = False
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if y > 70:
            break
        if getattr(ln, "non_black", False) and getattr(ln, "bold", False) and float(getattr(ln, "size", 0.0)) >= 18.0:
            x = float(getattr(ln, "x0", 0.0))
            if 120 <= x <= 360:
                has_big_colored_title = True
                break
    if not has_big_colored_title:
        return False

    # Find a blue-bold row around y ~ 90-140 with 3 distinct x regions.
    rows = _group_rows([ln for ln in lines if 80 <= float(getattr(ln, "y0", 0.0)) <= 150], y_tol=1.2)
    for _, row in rows:
        xs = []
        for ln in row:
            if getattr(ln, "non_black", False) and getattr(ln, "bold", False) and 9.0 <= float(getattr(ln, "size", 0.0)) <= 11.5:
                xs.append(float(getattr(ln, "x0", 0.0)))
        if not xs:
            continue
        if (min(xs) < 70) and any(120 < x < 260 for x in xs) and (max(xs) > 450):
            return True
    return False

def _extract_schedule_name(lines) -> str:
    # Value line typically: size ~11, not bold, x ~160-400, y ~80-115
    best = ""
    best_score = -1
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if not (70 <= y <= 125):
            continue
        if getattr(ln, "bold", False):
            continue
        if float(getattr(ln, "size", 0.0)) < 10.5 or float(getattr(ln, "size", 0.0)) > 11.8:
            continue
        x = float(getattr(ln, "x0", 0.0))
        if not (130 <= x <= 430):
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t:
            continue
        # Prefer longer, more "contentful" strings
        score = len(t) + sum(ch.isalnum() for ch in t)
        if score > best_score:
            best_score = score
            best = t
    return best

def _row_has_line_number(row) -> bool:
    for ln in row:
        x = float(getattr(ln, "x0", 0.0))
        if x < 450:
            continue
        t = (getattr(ln, "text", "") or "").strip()
        y = float(getattr(ln, "y0", 0.0))
        if y > 740:
            continue
        if _LINE_NO_RE.match(t):
            return True
    return False

def _extract_activity_from_row(row) -> str:
    if not _row_has_line_number(row):
        return ""
    best = ""
    best_len = 0
    for ln in row:
        if getattr(ln, "non_black", False):
            continue
        if not getattr(ln, "bold", False):
            continue
        sz = float(getattr(ln, "size", 0.0))
        if not (9.0 <= sz <= 11.5):
            continue
        x = float(getattr(ln, "x0", 0.0))
        if not (140 <= x <= 360):
            continue
        t = _norm(getattr(ln, "text", ""))
        if not t or _is_machine_annotation(t) or _is_option_text(t):
            continue
        # Avoid capturing left-side headers accidentally
        if t.endswith(":"):
            continue
        if len(t) > best_len:
            best = t
            best_len = len(t)
    return best

def _is_left_blue_field_label(ln) -> bool:
    # Left column blue bold labels like "Staff Initials:" and "Comment:"
    if not getattr(ln, "bold", False):
        return False
    if not getattr(ln, "non_black", False):
        return False
    sz = float(getattr(ln, "size", 0.0))
    if not (9.0 <= sz <= 11.5):
        return False
    x = float(getattr(ln, "x0", 0.0))
    y = float(getattr(ln, "y0", 0.0))
    if not (15 <= x <= 125):
        return False
    if not (140 <= y <= 735):
        return False
    t = _norm(getattr(ln, "text", ""))
    if not t or not t.endswith(":"):
        return False
    # Exclude table headers (usually higher on page), and any non-field container labels
    # Keep generic: suppress only obvious non-fields seen in this layout family.
    if re.match(r"^(Timepoint|Activity|Line\s*#)\s*$", t, flags=re.IGNORECASE):
        return False
    return True

def _is_question_label_candidate(ln, row_is_activity: bool) -> bool:
    if row_is_activity:
        return False  # activity/title row itself
    if getattr(ln, "non_black", False):
        return False
    if not getattr(ln, "bold", False):
        return False
    sz = float(getattr(ln, "size", 0.0))
    if not (9.0 <= sz <= 11.5):
        return False
    x = float(getattr(ln, "x0", 0.0))
    y = float(getattr(ln, "y0", 0.0))
    if not (140 <= x <= 380):
        return False
    if not (110 <= y <= 735):
        return False

    t = _norm(getattr(ln, "text", ""))
    if not t:
        return False
    if _is_machine_annotation(t):
        return False
    if _is_option_text(t):
        return False
    # Exclude container header "Answer(s):" which is colored in samples, but be safe anyway
    if t.rstrip(":").strip().lower() in ("answer(s)", "answers"):
        return False
    # Parenthetical guidance lines: treat as non-field annotation
    if t.startswith("(") and t.endswith(")") and len(t) >= 3:
        return False
    # Avoid capturing obvious page furniture
    if "Page " in t and re.search(r"\bof\b", t):
        return False
    return True

def _should_merge_wrap(prev_x: float, prev_y: float, cur_x: float, cur_y: float) -> bool:
    if abs(cur_x - prev_x) > 10:
        return False
    dy = cur_y - prev_y
    return 0 < dy <= 16

# ---- main extraction ----

def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()

    current_schedule = ""
    current_activity = ""

    for page_idx0, lines in pages:
        if not _looks_like_layout(lines):
            continue

        schedule = _extract_schedule_name(lines)
        if schedule and schedule != current_schedule:
            current_schedule = schedule
            current_activity = ""

        rows = _group_rows(lines, y_tol=1.2)

        pending_text: Optional[str] = None
        pending_form: str = ""
        pending_x: float = 0.0
        pending_y: float = 0.0

        def flush_pending():
            nonlocal pending_text, pending_form, pending_x, pending_y
            if pending_text:
                key = (page_idx0, pending_form, pending_text)
                if key not in seen:
                    seen.add(key)
                    out.append(
                        {"form_name": pending_form, "field_name": pending_text, "page": page_idx0 + 1}
                    )
            pending_text = None
            pending_form = ""
            pending_x = 0.0
            pending_y = 0.0

        for row_y, row in rows:
            if row_y is not None and float(row_y) > 740:
                continue

            row_is_activity = _row_has_line_number(row)
            new_activity = _extract_activity_from_row(row) if row_is_activity else ""
            if new_activity:
                # New section boundary: flush any pending wrapped question
                flush_pending()
                current_activity = new_activity

            form_name = current_activity or current_schedule or ""

            # Extract left blue labels (fields)
            for ln in row:
                if _is_left_blue_field_label(ln):
                    t = _norm(getattr(ln, "text", ""))
                    # Suppress "Answer(s):" even if mis-positioned (rare)
                    if t.rstrip(":").strip().lower() in ("answer(s)", "answers"):
                        continue
                    key = (page_idx0, form_name, t)
                    if key not in seen:
                        seen.add(key)
                        out.append({"form_name": form_name, "field_name": t, "page": page_idx0 + 1})

            # Extract bold-black question labels (may wrap across rows)
            # Process in x order within row to keep deterministic merge behavior
            row_sorted = sorted(row, key=lambda ln: float(getattr(ln, "x0", 0.0)))
            for ln in row_sorted:
                if not _is_question_label_candidate(ln, row_is_activity=row_is_activity):
                    continue
                t = _norm(getattr(ln, "text", ""))
                x = float(getattr(ln, "x0", 0.0))
                y = float(getattr(ln, "y0", 0.0))

                if pending_text and pending_form == form_name and _should_merge_wrap(pending_x, pending_y, x, y):
                    pending_text = _norm(pending_text + " " + t)
                    pending_x = (pending_x + x) / 2.0
                    pending_y = y
                else:
                    flush_pending()
                    pending_text = t
                    pending_form = form_name
                    pending_x = x
                    pending_y = y

        flush_pending()

    return out
