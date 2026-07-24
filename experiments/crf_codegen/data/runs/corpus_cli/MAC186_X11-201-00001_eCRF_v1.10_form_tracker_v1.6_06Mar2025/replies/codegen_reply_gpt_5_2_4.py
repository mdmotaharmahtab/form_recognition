import re
import statistics
from typing import Any, Dict, List, Optional, Tuple


_RE_SPACES = re.compile(r"\s+")
_RE_BRACKET_NUM = re.compile(r"\[\s*\d+\s*\]")
_RE_CODE_ONLY_BRACKET = re.compile(r"^\[\s*\d+\s*\]$")
_RE_HAS_WORDCHAR = re.compile(r"\w", re.UNICODE)
_RE_PURE_NUM = re.compile(r"^\d+(\.\d+)?$")
_RE_SPLIT_COMMAS = re.compile(r"\s*,\s*")


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()  # (page_idx, form_name, field_name)
    current_form = ""

    for page_idx, raw_lines in pages:
        if not raw_lines:
            continue

        lines = list(raw_lines)
        lines.sort(
            key=lambda ln: (
                float(getattr(ln, "y0", 0.0) or 0.0),
                float(getattr(ln, "x0", 0.0) or 0.0),
            )
        )

        xs = [float(getattr(ln, "x0", 0.0) or 0.0) for ln in lines]
        min_x = min(xs) if xs else 0.0
        max_x = max(xs) if xs else 0.0
        x_span = max(1.0, max_x - min_x)

        sizes = [float(getattr(ln, "size", 0.0) or 0.0) for ln in lines]
        max_size = max(sizes) if sizes else 0.0
        med_size = statistics.median(sizes) if sizes else 0.0
        y_tol = _row_y_tol(med_size)

        rows = _cluster_rows(lines, y_tol=y_tol)

        # Detect page title (apply to this page; only persist if fields extracted)
        proposed_title = ""
        title = _detect_prominent_title(lines, max_size=max_size)
        if title:
            proposed_title = title
        else:
            header_form = _detect_header_form_name(lines, min_x=min_x)
            if header_form:
                proposed_title = header_form

        # Skip codebook/spec listing pages (structural), e.g., "Variable details" listings
        if _is_variable_definition_listing(rows, min_x=min_x, x_span=x_span):
            continue

        fields: List[str] = []

        # Layout dispatch (extend; keep prior behaviors)
        if _is_variable_table(rows):
            fields = _extract_variable_table_fields(rows)
        else:
            hdr_i = _detect_row_label_table_header(rows, min_x=min_x, x_span=x_span, max_size=max_size)
            if hdr_i is not None:
                fields = _extract_row_label_table_fields(rows, hdr_i, min_x=min_x, x_span=x_span)
            else:
                if _is_questionnaire_list(rows, min_x=min_x, x_span=x_span):
                    fields = _extract_questionnaire_list_fields(rows, min_x=min_x, x_span=x_span)
                elif _is_schedule_repeat_table(rows, min_x=min_x, x_span=x_span):
                    fields = _extract_schedule_repeat_table_fields(rows, min_x=min_x, x_span=x_span)
                else:
                    header_fields = _extract_header_band_fields(
                        rows, min_x=min_x, x_span=x_span, max_size=max_size, med_size=med_size
                    )
                    body_fields = _extract_body_label_fields(
                        rows, min_x=min_x, x_span=x_span, max_size=max_size, med_size=med_size
                    )
                    fields = header_fields + body_fields

        # Use proposed title for this page (even if not persisted yet)
        page_form = proposed_title or current_form or ""

        any_added = False
        for f in fields:
            field_name = _clean_field_text(f)
            if not field_name:
                continue
            key = (page_idx, page_form, field_name)
            if key in seen:
                continue
            seen.add(key)
            out.append({"form_name": page_form, "field_name": field_name, "page": int(page_idx) + 1})
            any_added = True

        # Persist title only if this page actually produced fields
        if any_added and proposed_title:
            current_form = proposed_title

    return out


# ----------------------------
# Row clustering / geometry
# ----------------------------

def _row_y_tol(med_size: float) -> float:
    if med_size <= 0:
        return 2.5
    return max(1.6, min(4.4, 0.42 * med_size))


def _cluster_rows(lines: List[Any], y_tol: float) -> List[List[Any]]:
    rows: List[List[Any]] = []
    cur: List[Any] = []
    cur_y: Optional[float] = None

    for ln in lines:
        y = float(getattr(ln, "y0", 0.0) or 0.0)
        if cur_y is None:
            cur = [ln]
            cur_y = y
            continue
        if abs(y - cur_y) <= y_tol:
            cur.append(ln)
        else:
            cur.sort(key=lambda z: float(getattr(z, "x0", 0.0) or 0.0))
            rows.append(cur)
            cur = [ln]
            cur_y = y

    if cur:
        cur.sort(key=lambda z: float(getattr(z, "x0", 0.0) or 0.0))
        rows.append(cur)
    return rows


# ----------------------------
# Text helpers / filters
# ----------------------------

def _norm(s: str) -> str:
    return _RE_SPACES.sub(" ", (s or "").strip())


def _text(ln: Any) -> str:
    return _norm(getattr(ln, "text", "") or "")


def _strip_bracket_codes(s: str) -> str:
    return _norm(_RE_BRACKET_NUM.sub("", s or ""))


def _has_letters_or_words(s: str) -> bool:
    s = s or ""
    return bool(_RE_HAS_WORDCHAR.search(s))


def _is_code_only_bracket(s: str) -> bool:
    return bool(_RE_CODE_ONLY_BRACKET.match(_norm(s)))


def _is_pure_number(s: str) -> bool:
    return bool(_RE_PURE_NUM.match(_norm(s)))


def _looks_like_machine_tracker(s: str) -> bool:
    s = _norm(s)
    if not s:
        return True
    if len(s) >= 26 and " " not in s and any(c.isalpha() for c in s) and any(c.isdigit() for c in s):
        return True
    if len(s) >= 20 and ("_" in s or s.count("_") >= 2 or s.count("/") >= 2 or s.count("-") >= 4):
        if " " not in s:
            return True
    return False


def _looks_like_code_token(s: str) -> bool:
    """
    Structural code token: no spaces, contains both letters & digits, moderately long.
    Avoid excluding short technical abbreviations like "SpO2".
    """
    s = _norm(s)
    if not s or " " in s:
        return False
    if len(s) < 7:
        return False
    has_a = any(c.isalpha() for c in s)
    has_d = any(c.isdigit() for c in s)
    if not (has_a and has_d):
        return False
    alnum = sum(c.isalnum() for c in s)
    if alnum / max(1, len(s)) < 0.85:
        return False
    return True


def _looks_like_export_code(s: str) -> bool:
    """
    Export code / variable name token used on codebook pages.
    Accepts all-caps tokens that may lack digits.
    """
    s = _norm(s)
    if not s or " " in s:
        return False
    if len(s) < 3 or len(s) > 20:
        return False
    ok = sum(c.isalnum() or c in "_" for c in s)
    if ok / max(1, len(s)) < 0.9:
        return False
    upp = sum(c.isupper() for c in s)
    letters = sum(c.isalpha() for c in s)
    if letters >= 2 and upp / max(1, letters) >= 0.75:
        return True
    return False


def _is_parenthetical_annotation(s: str) -> bool:
    s = _norm(s)
    return len(s) <= 26 and len(s) >= 3 and s.startswith("(") and s.endswith(")") and _has_letters_or_words(s[1:-1])


def _looks_like_compact_choice_group(s: str) -> bool:
    s = _strip_bracket_codes(_norm(s))
    if not s or len(s) > 12:
        return False
    if any(ch.isdigit() for ch in s):
        return False
    if any(ch in "/,;:()[]{}" for ch in s):
        return False
    parts = [p for p in s.split(" ") if p]
    if len(parts) != 2:
        return False
    if not all(p.isalpha() for p in parts):
        return False
    if not all(2 <= len(p) <= 3 for p in parts):
        return False
    if not all(p[:1].isupper() and p[1:].islower() for p in parts):
        return False
    return True


def _looks_like_dose_anchor(s: str) -> bool:
    """
    Option/anchor lines in medication tables: comma-separated medication + multiple doses.
    Filter by pattern rather than literal strings.
    """
    s = _norm(s)
    if not s or len(s) < 10 or len(s) > 80:
        return False
    if s.count(",") < 1:
        return False
    if sum(c.isdigit() for c in s) < 2:
        return False
    # Avoid removing legitimate labels like "Visit 2 Date" (no commas anyway)
    parts = [p for p in _RE_SPLIT_COMMAS.split(s) if p]
    if len(parts) < 2:
        return False
    # Typically contains unit-like slash or 'mg' token
    low = s.lower()
    if "mg" in low or "/d" in low or "/" in low:
        return True
    return False


def _clean_field_text(s: str) -> str:
    s = _norm(s)
    if not s:
        return ""
    if _looks_like_machine_tracker(s):
        return ""
    if _is_code_only_bracket(s):
        return ""
    if _is_parenthetical_annotation(s):
        return ""
    if _looks_like_code_token(s):
        return ""
    if _looks_like_dose_anchor(s):
        return ""

    s2 = _strip_bracket_codes(s)
    if not s2:
        return ""
    if not _has_letters_or_words(s2):
        return ""
    if _looks_like_compact_choice_group(s2):
        return ""
    return s2


# ----------------------------
# Form name detection
# ----------------------------

def _detect_prominent_title(lines: List[Any], max_size: float) -> str:
    if max_size <= 0:
        return ""
    cand = []
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0) or 0.0)
        x = float(getattr(ln, "x0", 0.0) or 0.0)
        sz = float(getattr(ln, "size", 0.0) or 0.0)
        txt = _text(ln)
        if y < 50 or y > 135:
            continue
        if sz < 0.86 * max_size:
            continue
        if not _has_letters_or_words(txt) or _looks_like_machine_tracker(txt):
            continue
        if x > 0.62 * (max(float(getattr(ln, "x1", x) or x), x) + 1.0) and len(txt) < 6:
            continue
        if len(txt) < 4:
            continue
        cand.append((sz, -y, -len(txt), txt))
    if not cand:
        return ""
    cand.sort(reverse=True)
    return cand[0][3]


def _detect_header_form_name(lines: List[Any], min_x: float) -> str:
    cand = []
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0) or 0.0)
        x = float(getattr(ln, "x0", 0.0) or 0.0)
        sz = float(getattr(ln, "size", 0.0) or 0.0)
        bold = bool(getattr(ln, "bold", False))
        txt = _text(ln)
        if not bold or not txt:
            continue
        if y < 36 or y > 70:
            continue
        if x > min_x + 16:
            continue
        if sz < 5.0 or sz > 13.5:
            continue
        if _looks_like_machine_tracker(txt) or _is_code_only_bracket(txt) or _looks_like_code_token(txt):
            continue
        if not _has_letters_or_words(txt):
            continue
        if len(txt) < 4:
            continue
        cand.append((len(txt), -sz, txt))
    if not cand:
        return ""
    cand.sort(reverse=True)
    return cand[0][2]


# ----------------------------
# Variable-definition/spec listing pages (NOT data-entry forms)
# ----------------------------

def _is_variable_definition_listing(rows: List[List[Any]], min_x: float, x_span: float) -> bool:
    """
    Detect codebook/spec pages listing variables with Export Name/Type/Max length/Categories.
    Structural detection: bracketed IDs at left + export-code column + type/length columns.
    """
    if not rows:
        return False

    hit_rows = 0
    bracket_rows = 0
    header_like = 0

    left_bracket_max = min_x + 0.20 * x_span
    name_col_min = min_x + 0.10 * x_span
    name_col_max = min_x + 0.44 * x_span
    code_col_min = min_x + 0.30 * x_span
    code_col_max = min_x + 0.60 * x_span
    type_col_min = min_x + 0.54 * x_span
    len_col_min = min_x + 0.64 * x_span
    len_col_max = min_x + 0.90 * x_span

    for row in rows:
        if not row:
            continue
        y = float(getattr(row[0], "y0", 0.0) or 0.0)
        if y < 38 or y > 290:
            continue

        # header row evidence: many bold labels across page width
        bold_cells = []
        bold_xs = []
        for ln in row:
            if not bool(getattr(ln, "bold", False)):
                continue
            t = _text(ln)
            if not t:
                continue
            t2 = _strip_bracket_codes(t)
            if not t2 or not _has_letters_or_words(t2):
                continue
            if _looks_like_machine_tracker(t2) or _looks_like_code_token(t2):
                continue
            bold_cells.append(t2)
            bold_xs.append(float(getattr(ln, "x0", 0.0) or 0.0))
        if len(bold_cells) >= 4:
            span = (max(bold_xs) - min(bold_xs)) if bold_xs else 0.0
            if span >= 0.55 * x_span and 50 <= y <= 95:
                header_like += 1

        br_found = False
        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            if x > left_bracket_max:
                continue
            t = _text(ln)
            if _is_code_only_bracket(t):
                br_found = True
                break
        if not br_found:
            continue

        bracket_rows += 1
        has_name = False
        has_code = False
        has_type = False
        has_len = False

        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            t = _text(ln)
            if not t:
                continue
            t2 = _strip_bracket_codes(t)
            if not t2:
                continue

            if name_col_min <= x <= name_col_max:
                if _has_letters_or_words(t2) and not _looks_like_machine_tracker(t2) and not _looks_like_code_token(t2):
                    if len(t2) >= 4:
                        has_name = True

            if code_col_min <= x <= code_col_max:
                if _looks_like_export_code(t2):
                    has_code = True

            if x >= type_col_min:
                # type descriptor: usually wordy, often with parentheses
                if _has_letters_or_words(t2) and 6 <= len(t2) <= 80 and not _looks_like_machine_tracker(t2):
                    if ("(" in t2 and ")" in t2) or (t2.count(" ") >= 1 and len(t2) >= 10):
                        has_type = True

            if len_col_min <= x <= len_col_max:
                if _is_pure_number(t2) and len(t2) <= 5:
                    has_len = True

        if has_code and has_name and (has_type or has_len):
            hit_rows += 1

    # Strong signal: one or more header-like rows, then many bracket rows with code/type structure
    if header_like >= 1 and bracket_rows >= 6 and hit_rows >= max(5, int(0.60 * bracket_rows)):
        return True
    # Fallback if header text not bold in some renderings
    if bracket_rows >= 10 and hit_rows >= max(8, int(0.65 * bracket_rows)):
        return True
    return False


# ----------------------------
# Variable-table ("[n]" rows) extraction (existing)
# ----------------------------

def _is_variable_table(rows: List[List[Any]]) -> bool:
    bracket_rows = 0
    bracket_rows_with_name = 0
    for row in rows:
        bracket_cells = [ln for ln in row if _is_code_only_bracket(getattr(ln, "text", "") or "")]
        if not bracket_cells:
            continue
        leftmost = min(bracket_cells, key=lambda z: float(getattr(z, "x0", 0.0) or 0.0))
        bx = float(getattr(leftmost, "x0", 0.0) or 0.0)
        by = float(getattr(leftmost, "y0", 0.0) or 0.0)
        if by < 60:
            continue
        bracket_rows += 1

        name_cells = []
        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            txt = _text(ln)
            if x <= bx + 18:
                continue
            if x > bx + 300:
                continue
            if not txt or _is_code_only_bracket(txt):
                continue
            if _looks_like_machine_tracker(txt) or _looks_like_code_token(txt):
                continue
            if not _has_letters_or_words(txt):
                continue
            name_cells.append(ln)
        if name_cells:
            bracket_rows_with_name += 1

    return bracket_rows >= 3 and bracket_rows_with_name >= max(2, int(0.6 * bracket_rows))


def _extract_variable_table_fields(rows: List[List[Any]]) -> List[str]:
    fields: List[str] = []
    starts = []
    for i, row in enumerate(rows):
        for ln in row:
            if _is_code_only_bracket(getattr(ln, "text", "") or ""):
                y = float(getattr(ln, "y0", 0.0) or 0.0)
                if y >= 60:
                    starts.append((i, ln))
                    break

    for idx, (row_i, bracket_ln) in enumerate(starts):
        row = rows[row_i]
        bx = float(getattr(bracket_ln, "x0", 0.0) or 0.0)

        name_ln = None
        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            txt = _text(ln)
            if x <= bx + 18 or x > bx + 300:
                continue
            if not txt or _is_code_only_bracket(txt):
                continue
            if _looks_like_machine_tracker(txt) or _looks_like_code_token(txt):
                continue
            if not _has_letters_or_words(txt):
                continue
            if name_ln is None or x < float(getattr(name_ln, "x0", 0.0) or 0.0):
                name_ln = ln

        if name_ln is None:
            continue

        name_x = float(getattr(name_ln, "x0", 0.0) or 0.0)
        end_row_i = starts[idx + 1][0] if idx + 1 < len(starts) else len(rows)

        parts = [_text(name_ln)]
        for rj in range(row_i + 1, end_row_i):
            for ln in rows[rj]:
                x = float(getattr(ln, "x0", 0.0) or 0.0)
                if abs(x - name_x) > 10:
                    continue
                txt = _text(ln)
                if not txt:
                    continue
                if x > name_x + 60:
                    continue
                if _is_code_only_bracket(txt) or _looks_like_machine_tracker(txt) or _looks_like_code_token(txt):
                    continue
                if not _has_letters_or_words(txt):
                    continue
                parts.append(txt)

        joined = _norm(" ".join(parts))
        if joined:
            fields.append(joined)

    return fields


# ----------------------------
# Questionnaire/list pages
# ----------------------------

def _is_questionnaire_list(rows: List[List[Any]], min_x: float, x_span: float) -> bool:
    left_num_rows = 0
    text_rows = 0
    anchor_digit_hits = 0

    for row in rows:
        if not row:
            continue
        y = float(getattr(row[0], "y0", 0.0) or 0.0)
        if y < 45:
            continue

        has_left_num = False
        has_text = False
        has_anchor_digits = False

        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            t = _text(ln)
            if not t:
                continue
            if x <= min_x + 0.085 * x_span and _is_pure_number(t):
                has_left_num = True
            if (min_x + 0.070 * x_span) <= x <= (min_x + 0.80 * x_span):
                t2 = _strip_bracket_codes(t)
                if len(t2) >= 10 and _has_letters_or_words(t2) and not _looks_like_machine_tracker(t2) and not _looks_like_code_token(t2):
                    has_text = True
            if x >= (min_x + 0.38 * x_span) and _is_pure_number(t) and len(t) <= 1:
                has_anchor_digits = True

        if has_left_num:
            left_num_rows += 1
        if has_text:
            text_rows += 1
        if has_anchor_digits:
            anchor_digit_hits += 1

    return (left_num_rows >= 6 and text_rows >= 6) or (left_num_rows >= 6 and text_rows >= 6 and anchor_digit_hits >= 6)


def _extract_questionnaire_list_fields(rows: List[List[Any]], min_x: float, x_span: float) -> List[str]:
    fields: List[str] = []

    anchor_bins: List[Dict[str, Any]] = []
    for row in rows:
        for ln in row:
            t = _text(ln)
            if not t or not _is_pure_number(t) or len(t) != 1:
                continue
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            if x < (min_x + 0.36 * x_span):
                continue
            placed = False
            for b in anchor_bins:
                if abs(x - b["x"]) <= 7.5:
                    b["x"] = 0.8 * b["x"] + 0.2 * x
                    b["n"] += 1
                    placed = True
                    break
            if not placed:
                anchor_bins.append({"x": x, "n": 1})
    anchor_xs = [b["x"] for b in anchor_bins if b["n"] >= 6]

    def is_anchor_col(x: float) -> bool:
        return any(abs(x - ax) <= 8.0 for ax in anchor_xs)

    for row in rows:
        if not row:
            continue
        y = float(getattr(row[0], "y0", 0.0) or 0.0)
        if y < 45:
            continue

        best = ""
        best_score = -1.0

        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            t = _text(ln)
            if not t:
                continue
            if is_anchor_col(x) and _is_pure_number(t):
                continue
            if x <= min_x + 0.09 * x_span and _is_pure_number(t):
                continue

            t2 = _strip_bracket_codes(t)
            if not t2 or not _has_letters_or_words(t2):
                continue
            if _looks_like_machine_tracker(t2) or _looks_like_code_token(t2):
                continue

            in_text_col = (min_x + 0.070 * x_span) <= x <= (min_x + 0.84 * x_span)
            score = (2.0 if in_text_col else 0.0) + min(90.0, float(len(t2)))
            if "." in t2:
                score += 1.0
            if t2.count(" ") >= 2:
                score += 1.0
            if score > best_score:
                best_score = score
                best = t2

        if best:
            fields.append(best)

    return fields


# ----------------------------
# Repeating schedule tables
# ----------------------------

def _is_schedule_repeat_table(rows: List[List[Any]], min_x: float, x_span: float) -> bool:
    hits = 0
    for row in rows:
        if not row:
            continue
        y = float(getattr(row[0], "y0", 0.0) or 0.0)
        if y < 45:
            continue

        has_left_index = False
        has_right_label = False

        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            t = _text(ln)
            if not t:
                continue
            if x <= min_x + 0.10 * x_span and _is_pure_number(t) and len(t) <= 3:
                has_left_index = True
            if x >= min_x + 0.70 * x_span:
                t2 = _strip_bracket_codes(t)
                if len(t2) >= 4 and _has_letters_or_words(t2) and not _looks_like_machine_tracker(t2) and not _looks_like_code_token(t2):
                    has_right_label = True

        if has_left_index and has_right_label:
            hits += 1

    return hits >= 8


def _extract_schedule_repeat_table_fields(rows: List[List[Any]], min_x: float, x_span: float) -> List[str]:
    fields: List[str] = []

    right_min = min_x + 0.62 * x_span
    mid_min = min_x + 0.24 * x_span

    for row in rows:
        if not row:
            continue
        y = float(getattr(row[0], "y0", 0.0) or 0.0)
        if y < 45:
            continue

        has_left_index = any(
            float(getattr(ln, "x0", 0.0) or 0.0) <= min_x + 0.10 * x_span
            and _is_pure_number(_text(ln))
            and len(_text(ln)) <= 3
            for ln in row
        )
        if not has_left_index:
            continue

        best = ""
        best_score = -1.0

        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            t = _text(ln)
            if not t:
                continue
            if _is_pure_number(t):
                continue

            t2 = _strip_bracket_codes(t)
            if not t2 or not _has_letters_or_words(t2):
                continue
            if _looks_like_machine_tracker(t2) or _looks_like_code_token(t2):
                continue

            in_right = x >= right_min
            in_mid = (mid_min <= x < right_min)

            if not in_right and not (in_mid and (t2.count(" ") >= 1 or len(t2) >= 12 or t2.endswith(":"))):
                continue

            score = (3.0 if in_right else 1.0) + min(90.0, float(len(t2))) + 2.0 * min(6, float(t2.count(" ")))
            if "(" in t2 and ")" in t2:
                score += 1.0
            if score > best_score:
                best_score = score
                best = t2

        if best:
            fields.append(best)

    return fields


# ----------------------------
# Row-label table extraction (labs / long parameter lists)
# ----------------------------

def _detect_row_label_table_header(
    rows: List[List[Any]], min_x: float, x_span: float, max_size: float
) -> Optional[int]:
    for i, row in enumerate(rows):
        if not row:
            continue
        y = float(getattr(row[0], "y0", 0.0) or 0.0)
        if y < 50:
            continue
        bolds = []
        xs = []
        for ln in row:
            if not bool(getattr(ln, "bold", False)):
                continue
            t = _text(ln)
            if not t:
                continue
            t2 = _strip_bracket_codes(t)
            if not t2 or not _has_letters_or_words(t2):
                continue
            if _looks_like_machine_tracker(t2) or _looks_like_code_token(t2):
                continue
            sz = float(getattr(ln, "size", 0.0) or 0.0)
            if max_size > 0 and sz >= 0.94 * max_size and y < 130:
                continue
            bolds.append(ln)
            xs.append(float(getattr(ln, "x0", 0.0) or 0.0))
        if len(bolds) < 3:
            continue
        span = (max(xs) - min(xs)) if xs else 0.0
        if span < 0.40 * x_span and len(bolds) < 5:
            continue

        left_label_rows = 0
        for r in rows[i + 1 : min(len(rows), i + 60)]:
            if not r:
                continue
            ry = float(getattr(r[0], "y0", 0.0) or 0.0)
            if ry - y > 260:
                break
            found = False
            for ln in r:
                x = float(getattr(ln, "x0", 0.0) or 0.0)
                if x > min_x + 0.45 * x_span:
                    continue
                t = _text(ln)
                if not t or _is_pure_number(t):
                    continue
                t2 = _strip_bracket_codes(t)
                if len(t2) < 4:
                    continue
                if not _has_letters_or_words(t2):
                    continue
                if _looks_like_machine_tracker(t2) or _looks_like_code_token(t2):
                    continue
                found = True
                break
            if found:
                left_label_rows += 1
        if left_label_rows >= 8:
            return i

    return None


def _extract_row_label_table_fields(rows: List[List[Any]], hdr_i: int, min_x: float, x_span: float) -> List[str]:
    fields: List[str] = []

    cand = []
    for row in rows[hdr_i + 1 :]:
        if not row:
            continue
        y = float(getattr(row[0], "y0", 0.0) or 0.0)
        hdr_y = float(getattr(rows[hdr_i][0], "y0", 0.0) or 0.0)
        if y - hdr_y > 420:
            break
        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            if x > min_x + 0.55 * x_span:
                continue
            t = _text(ln)
            if not t or _is_pure_number(t):
                continue
            t2 = _strip_bracket_codes(t)
            if not t2 or not _has_letters_or_words(t2):
                continue
            if _looks_like_machine_tracker(t2) or _looks_like_code_token(t2):
                continue
            cand.append((x, t2))

    bins: List[Dict[str, Any]] = []
    for x, t in cand:
        placed = False
        for b in bins:
            if abs(x - b["x"]) <= 12.0:
                b["x"] = 0.8 * b["x"] + 0.2 * x
                b["items"].append(t)
                placed = True
                break
        if not placed:
            bins.append({"x": x, "items": [t]})

    bins.sort(key=lambda b: b["x"])
    if not bins:
        return fields

    label_bins = bins[:2]

    def choose_label_in_row(row: List[Any]) -> str:
        picks: List[Tuple[float, str]] = []
        for ln in row:
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            t = _text(ln)
            if not t:
                continue
            t2 = _strip_bracket_codes(t)
            if not t2 or not _has_letters_or_words(t2):
                continue
            if _looks_like_machine_tracker(t2):
                continue
            for b in label_bins:
                if abs(x - b["x"]) <= 14.0:
                    score = float(len(t2)) + 4.0 * min(6, t2.count(" "))
                    if _looks_like_code_token(t2):
                        score -= 18.0
                    picks.append((score, t2))
                    break
        if not picks:
            return ""
        picks.sort(reverse=True)
        return picks[0][1]

    last_x: Optional[float] = None
    last_y: Optional[float] = None
    acc: List[str] = []

    for r in rows[hdr_i + 1 :]:
        if not r:
            continue
        y = float(getattr(r[0], "y0", 0.0) or 0.0)
        lbl = choose_label_in_row(r)
        if not lbl:
            if acc:
                fields.append(_norm(" ".join(acc)))
                acc = []
                last_x = None
                last_y = None
            continue

        lbl_x = None
        for ln in r:
            t = _strip_bracket_codes(_text(ln))
            if t == lbl:
                lbl_x = float(getattr(ln, "x0", 0.0) or 0.0)
                break

        if acc and last_x is not None and last_y is not None and lbl_x is not None:
            close = abs(lbl_x - last_x) <= 10.0 and (y - last_y) <= 14.5
            has_left_index = any(
                float(getattr(ln, "x0", 0.0) or 0.0) <= min_x + 0.10 * x_span
                and _is_pure_number(_text(ln))
                and len(_text(ln)) <= 3
                for ln in r
            )
            if close and not has_left_index:
                acc.append(lbl)
                last_x = lbl_x
                last_y = y
                continue

            fields.append(_norm(" ".join(acc)))
            acc = [lbl]
            last_x = lbl_x
            last_y = y
        else:
            acc = [lbl]
            last_x = lbl_x
            last_y = y

    if acc:
        fields.append(_norm(" ".join(acc)))

    return fields


# ----------------------------
# Header-band (multi-column) extraction
# ----------------------------

def _split_multi_coded_segments(s: str) -> Optional[List[str]]:
    s0 = s or ""
    matches = list(_RE_BRACKET_NUM.finditer(s0))
    if len(matches) <= 1:
        return None
    segs: List[str] = []
    start = 0
    for m in matches:
        end = m.end()
        seg = _norm(s0[start:end])
        if seg:
            segs.append(seg)
        start = end
    tail = _norm(s0[start:])
    if tail and _has_letters_or_words(_strip_bracket_codes(tail)):
        segs.append(tail)
    return [seg for seg in segs if seg]


def _extract_header_band_fields(
    rows: List[List[Any]], min_x: float, x_span: float, max_size: float, med_size: float
) -> List[str]:
    fields: List[str] = []
    if not rows:
        return fields

    candidate_row_idxs = []
    for i, row in enumerate(rows):
        if not row:
            continue
        y = float(getattr(row[0], "y0", 0.0) or 0.0)
        if y < 50:
            continue

        # Accept bold header-like rows; allow slightly looser at top to recover missing early labels
        bolds = [ln for ln in row if bool(getattr(ln, "bold", False))]
        if len(bolds) < 2:
            continue

        xs = [float(getattr(ln, "x0", 0.0) or 0.0) for ln in bolds]
        span = (max(xs) - min(xs)) if xs else 0.0

        if len(bolds) >= 3 and span < 0.40 * x_span and len(bolds) < 6:
            continue
        if len(bolds) == 2 and span < 0.52 * x_span:
            continue

        if max_size > 0:
            sizes = [float(getattr(ln, "size", 0.0) or 0.0) for ln in bolds]
            if sizes and statistics.median(sizes) >= 0.92 * max_size and y < 140:
                continue

        candidate_row_idxs.append(i)

    if not candidate_row_idxs:
        return fields

    used = set()
    for start_i in candidate_row_idxs:
        if start_i in used:
            continue

        block: List[Any] = []
        i = start_i
        last_y = float(getattr(rows[i][0], "y0", 0.0) or 0.0)

        while i < len(rows):
            row = rows[i]
            if not row:
                break
            y = float(getattr(row[0], "y0", 0.0) or 0.0)
            if i != start_i and (y - last_y) > 18.0:
                break

            bolds = [ln for ln in row if bool(getattr(ln, "bold", False))]
            if not bolds:
                break

            leftish_bolds = [
                ln for ln in bolds
                if float(getattr(ln, "x0", 0.0) or 0.0) <= min_x + 0.22 * x_span
            ]
            if i != start_i and len(bolds) <= 2 and leftish_bolds:
                break

            block.extend(bolds)
            used.add(i)
            last_y = y
            i += 1

        if not block:
            continue

        bin_lines = []
        for ln in block:
            txt = _text(ln)
            if not txt:
                continue
            segs = _split_multi_coded_segments(txt)
            if segs:
                for seg in segs:
                    seg2 = _strip_bracket_codes(seg)
                    if seg2 and not _looks_like_code_token(seg2) and not _looks_like_machine_tracker(seg2):
                        fields.append(seg2)
            else:
                bin_lines.append(ln)

        bins: List[Dict[str, Any]] = []
        for ln in bin_lines:
            txt = _text(ln)
            if not txt:
                continue
            x = float(getattr(ln, "x0", 0.0) or 0.0)
            y = float(getattr(ln, "y0", 0.0) or 0.0)

            placed = False
            for b in bins:
                if abs(x - b["x"]) <= 10.0:
                    b["items"].append((y, x, txt))
                    b["x"] = 0.82 * b["x"] + 0.18 * x
                    placed = True
                    break
            if not placed:
                bins.append({"x": x, "items": [(y, x, txt)]})

        bins.sort(key=lambda b: b["x"])
        for b in bins:
            items = sorted(b["items"])
            parts = []
            for _, __, t in items:
                if _is_code_only_bracket(t):
                    continue
                t2 = _strip_bracket_codes(t)
                if not t2:
                    continue
                if _looks_like_machine_tracker(t2) or _looks_like_code_token(t2):
                    continue
                parts.append(t2)
            joined = _norm(" ".join(parts))
            if joined:
                fields.append(joined)

    return fields


# ----------------------------
# Body label extraction - extended
# ----------------------------

def _extract_body_label_fields(
    rows: List[List[Any]], min_x: float, x_span: float, max_size: float, med_size: float
) -> List[str]:
    fields: List[str] = []
    if not rows:
        return fields

    def ok_label_text(t2: str) -> bool:
        if not t2:
            return False
        if not _has_letters_or_words(t2):
            return False
        if _looks_like_machine_tracker(t2) or _looks_like_code_token(t2):
            return False
        if len(t2) <= 2:
            return False
        return True

    # Collect candidates more inclusively to infer label columns robustly.
    cand_xs: List[float] = []
    cand_lns: List[Any] = []
    cand_meta: List[Tuple[float, float, bool, str]] = []  # (x, y, bold, t2)

    for row in rows:
        for ln in row:
            y = float(getattr(ln, "y0", 0.0) or 0.0)
            if y < 65:
                continue

            x = float(getattr(ln, "x0", 0.0) or 0.0)
            if x > min_x + 0.90 * x_span:
                continue

            txt0 = _text(ln)
            if not txt0 or _is_code_only_bracket(txt0) or _is_pure_number(txt0):
                continue

            t2 = _strip_bracket_codes(txt0)
            if not ok_label_text(t2):
                continue

            sz = float(getattr(ln, "size", 0.0) or 0.0)
            if max_size > 0 and sz >= 0.93 * max_size and y < 150:
                continue

            bold = bool(getattr(ln, "bold", False))
            # Evidence for column inference (looser): bold, colon, multiword, or modest length.
            ev = bold or t2.endswith(":") or (t2.count(" ") >= 1) or (len(t2) >= 7)
            if not ev:
                continue

            cand_xs.append(x)
            cand_lns.append(ln)
            cand_meta.append((x, y, bold, t2))

    if not cand_xs:
        return fields

    # Bin x positions to detect recurring label columns.
    bins: List[Dict[str, Any]] = []
    for x in cand_xs:
        placed = False
        for b in bins:
            if abs(x - b["x"]) <= 12.0:
                b["x"] = 0.8 * b["x"] + 0.2 * x
                b["n"] += 1
                placed = True
                break
        if not placed:
            bins.append({"x": x, "n": 1})
    bins.sort(key=lambda b: b["x"])
    total = sum(b["n"] for b in bins) or 1

    # Keep leftmost and additional frequent bins (support multi-column forms).
    keep_xs: List[float] = []
    if bins:
        keep_xs.append(bins[0]["x"])

    # Add up to 4 most frequent bins (excluding the first if already present).
    freq_bins = sorted(bins, key=lambda b: b["n"], reverse=True)
    for b in freq_bins[:6]:
        if b["n"] < max(3, int(0.06 * total)):
            continue
        if b["x"] < min_x + 0.08 * x_span:
            continue
        if b["x"] > min_x + 0.86 * x_span:
            continue
        if all(abs(b["x"] - kx) > 10.0 for kx in keep_xs):
            keep_xs.append(b["x"])
        if len(keep_xs) >= 4:
            break

    keep_xs.sort()

    def in_label_column(x: float) -> bool:
        return any(abs(x - kx) <= 14.0 for kx in keep_xs)

    base_left = keep_xs[0] if keep_xs else (bins[0]["x"] if bins else min_x)

    # Detect option-like vertical columns (e.g., checkbox options, category lists) to suppress.
    option_cols: List[float] = []
    opt_bins: List[Dict[str, Any]] = []
    for x, y, bold, t2 in cand_meta:
        if bold:
            continue
        if in_label_column(x):
            continue
        # Focus on typical option regions: indented from left label or far-right lists
        if not (x >= base_left + 10.0):
            continue
        if len(t2) > 34:
            continue
        if t2.endswith(":"):
            continue
        # Option-ish texts are usually short and not sentence-like.
        if t2.count(" ") > 5:
            continue

        placed = False
        for b in opt_bins:
            if abs(x - b["x"]) <= 9.0:
                b["x"] = 0.82 * b["x"] + 0.18 * x
                b["n"] += 1
                placed = True
                break
        if not placed:
            opt_bins.append({"x": x, "n": 1})

    for b in opt_bins:
        if b["n"] >= 6:
            option_cols.append(b["x"])

    def in_option_col(x: float) -> bool:
        return any(abs(x - ox) <= 10.0 for ox in option_cols)

    # Detect "table header rows" dominated by short tokens (often answer anchors like Yes/No).
    def is_headerish_row(row: List[Any]) -> bool:
        if not row:
            return False
        toks = 0
        shortish = 0
        bolds = 0
        for ln in row:
            t = _strip_bracket_codes(_text(ln))
            if not t or _is_pure_number(t) or _is_code_only_bracket(t):
                continue
            if _looks_like_machine_tracker(t) or _looks_like_code_token(t):
                continue
            toks += 1
            if len(t) <= 10 and t.count(" ") <= 1 and not t.endswith(":"):
                shortish += 1
            if bool(getattr(ln, "bold", False)):
                bolds += 1
        if toks >= 4 and shortish >= max(3, int(0.70 * toks)) and bolds <= 2:
            return True
        return False

    # Option-list filter: vertical choice lists under a parent label (extended beyond narrow indent).
    def is_option_like(row_i: int, ln: Any) -> bool:
        x = float(getattr(ln, "x0", 0.0) or 0.0)
        y = float(getattr(ln, "y0", 0.0) or 0.0)
        if bool(getattr(ln, "bold", False)):
            return False

        # Indent window OR clearly separate option column
        in_indent = (base_left + 4.0 <= x <= base_left + 70.0)
        in_far_col = in_option_col(x) and x >= base_left + 90.0
        if not (in_indent or in_far_col):
            return False

        txt = _strip_bracket_codes(_text(ln))
        if not ok_label_text(txt):
            return False
        if txt.endswith(":"):
            return False

        # Need a nearby parent label above in the left label column(s).
        parent_found = False
        for up in range(row_i - 1, max(-1, row_i - 14), -1):
            for up_ln in rows[up]:
                up_y = float(getattr(up_ln, "y0", 0.0) or 0.0)
                if y - up_y > 70.0:
                    break
                up_x = float(getattr(up_ln, "x0", 0.0) or 0.0)
                if abs(up_x - base_left) <= 22.0:
                    up_txt = _strip_bracket_codes(_text(up_ln))
                    if ok_label_text(up_txt) and (up_txt.count(" ") >= 1 or len(up_txt) >= 10 or up_txt.endswith(":")):
                        parent_found = True
                        break
            if parent_found:
                break
        if not parent_found:
            return False

        # Confirm vertical list at same x.
        sibs = 0
        for dn in range(row_i + 1, min(len(rows), row_i + 26)):
            for dn_ln in rows[dn]:
                dn_x = float(getattr(dn_ln, "x0", 0.0) or 0.0)
                dn_y = float(getattr(dn_ln, "y0", 0.0) or 0.0)
                if dn_y - y > 190.0:
                    break
                if abs(dn_x - x) <= 8.0:
                    dn_txt = _strip_bracket_codes(_text(dn_ln))
                    if ok_label_text(dn_txt) and not _is_code_only_bracket(dn_txt):
                        if not dn_txt.endswith(":"):
                            sibs += 1
            if sibs >= 2:
                return True
        return False

    for i, row in enumerate(rows):
        if not row:
            continue
        if is_headerish_row(row):
            continue

        for ln in row:
            y = float(getattr(ln, "y0", 0.0) or 0.0)
            if y < 65:
                continue

            x = float(getattr(ln, "x0", 0.0) or 0.0)
            if not in_label_column(x):
                continue

            txt0 = _text(ln)
            if not txt0 or _is_code_only_bracket(txt0) or _is_pure_number(txt0):
                continue

            t2 = _strip_bracket_codes(txt0)
            if not ok_label_text(t2):
                continue

            # Suppress option list items even if they align to a label column due to rendering quirks.
            if is_option_like(i, ln):
                continue

            # Extra suppression: very short non-bold tokens at shallow indent are typically options/anchors.
            if not bool(getattr(ln, "bold", False)) and (base_left + 4.0 <= x <= base_left + 70.0):
                if len(t2) <= 6 and t2.count(" ") == 0 and not t2.endswith(":"):
                    continue

            # Avoid extracting section headings that look like a title line (larger than body).
            sz = float(getattr(ln, "size", 0.0) or 0.0)
            if med_size > 0 and bool(getattr(ln, "bold", False)) and sz >= 1.25 * med_size and y < 140:
                if "-" in t2 and len(t2) >= 14 and not t2.endswith(":"):
                    continue

            # Join wrapped continuation lines below with same x.
            parts = [t2]
            last_y = y
            j = i + 1
            base_sz = sz if sz > 0 else (med_size if med_size > 0 else 7.0)

            while j < len(rows):
                next_row = rows[j]
                if not next_row:
                    break
                cont_y = float(getattr(next_row[0], "y0", 0.0) or 0.0)
                if cont_y - last_y > max(12.0, 2.45 * base_sz):
                    break

                cont_txt = None
                for nn in next_row:
                    nx = float(getattr(nn, "x0", 0.0) or 0.0)
                    if abs(nx - x) > 10.0:
                        continue
                    nt = _text(nn)
                    if not nt or _is_code_only_bracket(nt) or _is_pure_number(nt):
                        continue
                    nt2 = _strip_bracket_codes(nt)
                    if not ok_label_text(nt2):
                        continue
                    if is_option_like(j, nn):
                        continue
                    cont_txt = nt2
                    break

                if cont_txt is None:
                    break

                parts.append(cont_txt)
                last_y = cont_y
                j += 1

            joined = _norm(" ".join(parts))
            if joined:
                fields.append(joined)

    return fields
