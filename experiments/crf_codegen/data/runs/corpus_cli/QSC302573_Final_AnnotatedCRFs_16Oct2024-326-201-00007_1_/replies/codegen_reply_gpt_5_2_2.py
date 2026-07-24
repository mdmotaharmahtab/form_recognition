```python
import re
import unicodedata
from typing import Dict, List, Optional, Tuple


def extract(pages):
    out: List[Dict[str, object]] = []
    seen = set()

    current_form = ""

    for page_idx0, lines in pages:
        try:
            page_num = int(page_idx0) + 1
        except Exception:
            page_num = int(str(page_idx0)) + 1

        lines = [ln for ln in (lines or []) if (getattr(ln, "text", "") or "").strip()]

        page_box = _page_box(lines)
        header_cutoff_y = _header_cutoff_y(lines, page_box)

        current_form = _extract_form_name(lines, page_box, header_cutoff_y, current_form)

        ans_markers = [ln for ln in lines if _is_answer_marker(ln, page_box, header_cutoff_y)]
        ans_markers.sort(key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))

        label_x = _estimate_label_column_x(lines, ans_markers, page_box, header_cutoff_y)

        # --------
        # Pass 1: Answer(s) blocks (primary layout)
        # --------
        if ans_markers:
            for i, ans in enumerate(ans_markers):
                y_prev = header_cutoff_y if i == 0 else max(header_cutoff_y, float(getattr(ans_markers[i - 1], "y0", header_cutoff_y)))
                y_next = 1e9 if i + 1 >= len(ans_markers) else float(getattr(ans_markers[i + 1], "y0", 1e9))

                main_label = _extract_main_label(lines, label_x, y_prev, float(getattr(ans, "y0", 0.0)), page_box, ans_markers)
                if main_label:
                    _add(out, seen, current_form, main_label, page_num)

                # Conservative: only checkbox-style subfields inside the answer region.
                subs = _extract_checkbox_prompts_in_region(
                    lines=lines,
                    answer_marker=ans,
                    y0=float(getattr(ans, "y0", 0.0)),
                    y1=y_next,
                    label_x=label_x,
                    page_box=page_box,
                )
                for s in subs:
                    _add(out, seen, current_form, s, page_num)

                # Catch radio-option style fields within the block (label + O Yes/No ...), without extracting options.
                opt_label = _extract_option_group_label(
                    lines=lines,
                    y0=float(getattr(ans, "y0", 0.0)),
                    y1=y_next,
                    label_x=label_x,
                    page_box=page_box,
                    header_cutoff_y=header_cutoff_y,
                    ans_markers=ans_markers,
                )
                if opt_label:
                    _add(out, seen, current_form, opt_label, page_num)

        # --------
        # Pass 2: Underline/box-like fill areas (fallback for pages/fields without Answer(s))
        # --------
        for field in _extract_underline_fields(lines, page_box, header_cutoff_y, label_x, ans_markers):
            _add(out, seen, current_form, field, page_num)

        # --------
        # Pass 3: Option groups anywhere on the page (fallback)
        # --------
        for field in _extract_option_group_labels_pagewide(lines, page_box, header_cutoff_y, label_x, ans_markers):
            _add(out, seen, current_form, field, page_num)

        # --------
        # Pass 4: Checkbox prompts anywhere (very conservative; checkbox lines only)
        # --------
        for field in _extract_checkbox_prompts_pagewide(lines, page_box, header_cutoff_y, label_x):
            _add(out, seen, current_form, field, page_num)

    return out


# -------------------------
# Geometry helpers
# -------------------------

def _page_box(lines) -> Tuple[float, float, float, float]:
    xs0, xs1, ys0, ys1 = [], [], [], []
    for ln in lines or []:
        x0 = float(getattr(ln, "x0", 0.0))
        x1 = float(getattr(ln, "x1", x0))
        y0 = float(getattr(ln, "y0", 0.0))
        ys0.append(y0)
        ys1.append(y0)
        xs0.append(x0)
        xs1.append(x1)
    if not xs0:
        return (0.0, 1.0, 0.0, 1.0)
    min_x = min(xs0)
    max_x = max(xs1) if xs1 else (min_x + 1.0)
    min_y = min(ys0)
    max_y = max(ys1) if ys1 else (min_y + 1.0)
    if max_x - min_x < 1.0:
        max_x = min_x + 1.0
    if max_y - min_y < 1.0:
        max_y = min_y + 1.0
    return (min_x, max_x, min_y, max_y)


def _w(page_box) -> float:
    return max(1.0, page_box[1] - page_box[0])


def _h(page_box) -> float:
    return max(1.0, page_box[3] - page_box[2])


def _header_cutoff_y(lines, page_box, default_frac: float = 0.18) -> float:
    # Prefer using the first clearly body-like y if present; else use a fraction of page height.
    min_x, max_x, min_y, max_y = page_box
    body_candidates = [float(getattr(ln, "y0", 0.0)) for ln in lines if float(getattr(ln, "y0", 0.0)) >= (min_y + 0.12 * _h(page_box))]
    if body_candidates:
        return max(min_y + 0.10 * _h(page_box), min(body_candidates) - 2.0)
    return min_y + default_frac * _h(page_box)


# -------------------------
# Text normalization / heuristics
# -------------------------

def _norm_text(s: str) -> str:
    s = s or ""
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _norm_compact(s: str) -> str:
    s = _norm_text(s).lower()
    s = re.sub(r"\s+", "", s)
    return s


def _strip_trailing_colon(s: str) -> str:
    s = _norm_text(s)
    s = re.sub(r"\s*:\s*$", "", s)
    return s.strip()


def _letters_count(s: str) -> int:
    return sum(1 for c in (s or "") if unicodedata.category(c).startswith("L"))


def _looks_like_placeholder(txt: str) -> bool:
    t = txt or ""
    chars = [c for c in t if not c.isspace()]
    if not chars:
        return True

    underscores = sum(1 for c in chars if c == "_")
    letters = sum(1 for c in chars if unicodedata.category(c).startswith("L"))
    digits = sum(1 for c in chars if unicodedata.category(c).startswith("N"))

    ufrac = underscores / max(1, len(chars))
    lfrac = letters / max(1, len(chars))

    if ufrac >= 0.25 and lfrac <= 0.22:
        return True
    if letters == 0 and digits > 0 and digits / max(1, len(chars)) >= 0.55:
        return True
    return False


def _is_underline_only(s: str) -> bool:
    t = re.sub(r"\s+", "", s or "")
    if not t:
        return False
    return bool(re.fullmatch(r"[_\-–—.]+", t))


def _contains_fill_underline(s: str) -> bool:
    return bool(re.search(r"_{5,}", s or ""))


def _clean_checkbox_prompt(s: str) -> str:
    s = _norm_text(s)
    s = re.sub(r"^\s*\[\s*[xX]?\s*\]\s*", "", s)
    s = re.sub(r"_{5,}", " ", s)
    s = _norm_text(s)
    return _strip_trailing_colon(s)


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
    return bool(re.match(r"^\s*[Oo]\s+\S+", txt or ""))


def _is_checkbox_line(txt: str) -> bool:
    return bool(re.match(r"^\s*\[\s*[xX]?\s*\]\s*\S+", txt or ""))


def _looks_like_code_label(txt: str) -> bool:
    # Structural filter: heavy uppercase/digit tokens with few letters/spaces.
    t = _norm_text(txt)
    if not t:
        return True
    if len(t) <= 3:
        return True

    chars = [c for c in t if not c.isspace()]
    if not chars:
        return True

    letters = sum(1 for c in chars if unicodedata.category(c).startswith("L"))
    digits = sum(1 for c in chars if unicodedata.category(c).startswith("N"))
    uppers = sum(1 for c in chars if c.isupper())
    spaces = sum(1 for c in t if c.isspace())

    # If it's almost all uppercase/digits and has no natural word spacing, treat as code-ish.
    if letters > 0:
        ud_frac = (uppers + digits) / max(1, len(chars))
        if ud_frac >= 0.80 and spaces <= 1 and len(t) <= 25:
            return True

    # Very short token with digits.
    if digits >= 3 and spaces == 0 and len(t) <= 12:
        return True

    return False


def _looks_incomplete_parenthetical(t: str) -> bool:
    s = _norm_text(t)
    if "(" in s and ")" not in s:
        # Incomplete snippet often comes from option-side helper text.
        if len(s) <= 70:
            return True
    return False


# -------------------------
# Form name extraction
# -------------------------

def _extract_form_name(lines, page_box, header_cutoff_y, prev_form: str) -> str:
    # Look for "Schedule Category & Name" near the top; accept minor punctuation/spaces.
    min_x, max_x, min_y, max_y = page_box
    top_limit = min_y + 0.28 * _h(page_box)

    key_tokens = ("schedule", "category", "name")
    best = None

    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if y > top_limit:
            continue
        txt = _norm_text(getattr(ln, "text", ""))
        tlo = txt.lower()
        if all(tok in tlo for tok in key_tokens):
            best = ln
            break

    if not best:
        return prev_form

    y = float(getattr(best, "y0", 0.0))
    x1 = float(getattr(best, "x1", float(getattr(best, "x0", 0.0))))
    min_val_x = x1 - 2.0

    # Prefer same-row or immediate-below value to the right.
    cands = []
    for ln in lines:
        if _norm_text(getattr(ln, "text", "")) == "":
            continue
        y2 = float(getattr(ln, "y0", 0.0))
        x0_2 = float(getattr(ln, "x0", 0.0))
        if x0_2 < min_val_x:
            continue
        if abs(y2 - y) <= 2.5 or (y2 >= y - 0.5 and y2 <= y + 14.0):
            # Avoid picking the label itself.
            if ln is best:
                continue
            # Avoid obviously header noise.
            if y2 < header_cutoff_y - 10:
                continue
            cands.append(ln)

    if not cands:
        # Even if header_cutoff is off, accept near-top.
        for ln in lines:
            y2 = float(getattr(ln, "y0", 0.0))
            x0_2 = float(getattr(ln, "x0", 0.0))
            if x0_2 < min_val_x:
                continue
            if abs(y2 - y) <= 3.0 or (y2 >= y - 0.5 and y2 <= y + 14.0):
                if ln is best:
                    continue
                cands.append(ln)

    if not cands:
        return prev_form

    cands.sort(key=lambda l: (abs(float(getattr(l, "y0", 0.0)) - y), float(getattr(l, "x0", 0.0))))

    base = _norm_text(getattr(cands[0], "text", ""))
    if not base:
        return prev_form

    # Join wrapped lines directly below if aligned.
    wrap = [base]
    x0 = float(getattr(cands[0], "x0", 0.0))
    y0 = float(getattr(cands[0], "y0", 0.0))
    for ln in lines:
        if ln is cands[0]:
            continue
        y2 = float(getattr(ln, "y0", 0.0))
        x0_2 = float(getattr(ln, "x0", 0.0))
        if y2 > y0 and (y2 - y0) <= 18.0 and abs(x0_2 - x0) <= 10.0:
            t2 = _norm_text(getattr(ln, "text", ""))
            if t2:
                wrap.append(t2)
                y0 = y2

    joined = _norm_text(" ".join(wrap))
    return joined or prev_form


# -------------------------
# Answer(s) marker detection
# -------------------------

_ANSWER_RE = re.compile(r"^\s*answer\s*\(\s*s\s*\)\s*:?\s*$", re.IGNORECASE)


def _is_answer_marker(ln, page_box, header_cutoff_y: float) -> bool:
    txt = _norm_text(getattr(ln, "text", ""))
    if not txt:
        return False
    if not _ANSWER_RE.match(txt):
        return False

    y0 = float(getattr(ln, "y0", 0.0))
    if y0 < header_cutoff_y - 5.0:
        return False

    min_x, max_x, *_ = page_box
    x0 = float(getattr(ln, "x0", 0.0))

    # Marker is usually in the left/mid column (not extreme left).
    if x0 < (min_x + 0.10 * _w(page_box)):
        return False
    if x0 > (min_x + 0.60 * _w(page_box)):
        return False

    # Style is often bold and/or colored, but allow drift.
    bold = bool(getattr(ln, "bold", False))
    non_black = bool(getattr(ln, "non_black", False))
    if not (bold or non_black):
        # Still allow if it's exactly the marker and positioned correctly.
        return True
    return True


def _estimate_label_column_x(lines, ans_markers, page_box, header_cutoff_y: float) -> float:
    if ans_markers:
        xs = [float(getattr(ln, "x0", 0.0)) for ln in ans_markers]
        xs.sort()
        return xs[len(xs) // 2]

    # Fallback: median x0 of plausible label lines in the body (left-middle).
    min_x, max_x, *_ = page_box
    lo = min_x + 0.12 * _w(page_box)
    hi = min_x + 0.55 * _w(page_box)

    cands = []
    for ln in lines:
        y0 = float(getattr(ln, "y0", 0.0))
        if y0 < header_cutoff_y:
            continue
        x0 = float(getattr(ln, "x0", 0.0))
        if x0 < lo or x0 > hi:
            continue
        txt = _norm_text(getattr(ln, "text", ""))
        if not txt:
            continue
        if _is_sas_line(txt) or _is_option_line(txt) or _is_checkbox_line(txt):
            continue
        if _looks_like_placeholder(txt):
            continue
        if _letters_count(txt) < 4:
            continue
        cands.append(x0)

    if not cands:
        return min_x + 0.25 * _w(page_box)
    cands.sort()
    return cands[len(cands) // 2]


# -------------------------
# Furniture suppression (structural)
# -------------------------

def _is_probable_furniture_label(ln, page_box, header_cutoff_y: float, ans_markers) -> bool:
    # Structural template furniture is often blue + bold in extreme left margin, repeated around Answer(s) rows.
    y0 = float(getattr(ln, "y0", 0.0))
    if y0 < header_cutoff_y:
        return True  # treat header items as non-fields here

    non_black = bool(getattr(ln, "non_black", False))
    bold = bool(getattr(ln, "bold", False))
    if not (non_black and bold):
        return False

    min_x, max_x, *_ = page_box
    x0 = float(getattr(ln, "x0", 0.0))
    if x0 > (min_x + 0.18 * _w(page_box)):
        return False

    # If the page clearly uses Answer(s) layout, left-margin blue labels are usually column furniture.
    if ans_markers and len(ans_markers) >= 2:
        # If it's in the vertical span of the blocks, treat as furniture.
        ys = [float(getattr(a, "y0", 0.0)) for a in ans_markers]
        if ys:
            if (min(ys) - 30.0) <= y0 <= (max(ys) + 30.0):
                return True

    return False


# -------------------------
# Main label extraction above Answer(s)
# -------------------------

def _extract_main_label(lines, label_x: float, y0: float, ans_y: float, page_box, ans_markers) -> str:
    # Use the last mask line (underscore placeholders) in the left area as a divider when present.
    x_tol = max(28.0, 0.08 * _w(page_box))

    mask_y = None
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if y < y0 or y >= ans_y:
            continue
        x0_ln = float(getattr(ln, "x0", 0.0))
        txt = getattr(ln, "text", "") or ""
        if x0_ln <= (label_x - 20.0) and txt.count("_") >= 4:
            if mask_y is None or y > mask_y:
                mask_y = y

    # Candidates in label column between y0 and Answer(s)
    cands = []
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if y <= y0 or y >= ans_y:
            continue

        x0_ln = float(getattr(ln, "x0", 0.0))
        if abs(x0_ln - label_x) > x_tol:
            continue

        txt = _norm_text(getattr(ln, "text", ""))
        if not txt:
            continue

        # Exclude non-label structural lines
        if _ANSWER_RE.match(txt):
            continue
        if _is_sas_line(txt) or _is_option_line(txt) or _is_checkbox_line(txt):
            continue
        if _is_underline_only(txt):
            continue
        if _looks_like_placeholder(txt):
            continue

        # Exclude obvious code-ish tokens
        if _looks_like_code_label(txt):
            continue

        # Avoid template furniture (blue, left margin) being picked as "main label"
        if _is_probable_furniture_label(ln, page_box, y0, ans_markers):
            continue

        # Require some human text content
        if _letters_count(txt) < 4:
            continue
        if _looks_incomplete_parenthetical(txt):
            continue

        cands.append(ln)

    if not cands:
        return ""

    cands.sort(key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))

    # Choose the last candidate not clearly above the mask divider (helps avoid activity headers).
    chosen = None
    for ln in reversed(cands):
        y = float(getattr(ln, "y0", 0.0))
        if mask_y is None or y >= (mask_y - 3.0):
            chosen = ln
            break
    if chosen is None:
        chosen = cands[-1]

    # Join wrapped label lines above chosen (same column, tight vertical spacing).
    group = [chosen]
    chosen_idx = cands.index(chosen)
    last_y = float(getattr(chosen, "y0", 0.0))
    chosen_x = float(getattr(chosen, "x0", 0.0))

    for ln in reversed(cands[:chosen_idx]):
        y = float(getattr(ln, "y0", 0.0))
        if last_y - y > 22.0:
            break
        if abs(float(getattr(ln, "x0", 0.0)) - chosen_x) > 12.0:
            break
        txt = _norm_text(getattr(ln, "text", ""))
        if not txt:
            continue
        if _is_sas_line(txt) or _is_option_line(txt) or _is_checkbox_line(txt) or _looks_like_placeholder(txt):
            continue
        if _looks_like_code_label(txt):
            continue
        if _looks_incomplete_parenthetical(txt):
            continue
        group.append(ln)
        last_y = y

    group.sort(key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))
    parts = [_norm_text(getattr(ln, "text", "")) for ln in group]
    label = _norm_text(" ".join([p for p in parts if p]))
    label = _strip_trailing_colon(label)
    if not label:
        return ""
    if _looks_like_placeholder(label) or _looks_like_code_label(label) or _looks_incomplete_parenthetical(label):
        return ""
    return label


# -------------------------
# Checkbox prompts inside Answer(s) region
# -------------------------

def _extract_checkbox_prompts_in_region(lines, answer_marker, y0: float, y1: float, label_x: float, page_box) -> List[str]:
    # Only checkbox lines are treated as data-entry fields here.
    answer_min_x = label_x + max(34.0, 0.06 * _w(page_box))

    region = []
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if y < y0 - 0.5 or y > y1 + 0.5:
            continue
        if not _norm_text(getattr(ln, "text", "")):
            continue
        region.append(ln)

    region.sort(key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))

    prompts = []
    for ln in region:
        x0 = float(getattr(ln, "x0", 0.0))
        if x0 < answer_min_x:
            continue
        txt = _norm_text(getattr(ln, "text", ""))
        if not txt:
            continue
        if _is_sas_line(txt) or _is_option_line(txt):
            continue
        if not _is_checkbox_line(txt):
            continue

        cleaned = _clean_checkbox_prompt(txt)
        if not cleaned:
            continue
        if _looks_like_placeholder(cleaned) or _looks_like_code_label(cleaned) or _looks_incomplete_parenthetical(cleaned):
            continue
        prompts.append(cleaned)

    # De-dup preserve order
    seen_local = set()
    out = []
    for p in prompts:
        k = _norm_text(p).lower()
        if k and k not in seen_local:
            seen_local.add(k)
            out.append(p)
    return out


# -------------------------
# Underline-based field extraction (fallback)
# -------------------------

def _row_key(y: float, tol: float = 2.5) -> int:
    return int(round(y / tol))


def _group_rows(lines, tol: float = 2.5) -> Dict[int, List[object]]:
    rows: Dict[int, List[object]] = {}
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        k = _row_key(y, tol)
        rows.setdefault(k, []).append(ln)
    for k in rows:
        rows[k].sort(key=lambda l: float(getattr(l, "x0", 0.0)))
    return rows


def _is_underline_line(txt: str) -> bool:
    if not txt:
        return False
    t = txt.strip()
    if _is_underline_only(t):
        return True
    if _contains_fill_underline(t):
        return True
    # Sometimes dotted leaders act like blanks.
    if re.fullmatch(r"[.\s]{10,}", t):
        return True
    return False


def _extract_underline_fields(lines, page_box, header_cutoff_y: float, label_x: float, ans_markers) -> List[str]:
    min_x, max_x, min_y, max_y = page_box
    width = _w(page_box)

    rows = _group_rows([ln for ln in lines if float(getattr(ln, "y0", 0.0)) >= header_cutoff_y - 2.0])

    # Candidate underline lines in the body, typically in the answer area.
    underline_lines = []
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if y < header_cutoff_y - 2.0:
            continue
        txt = _norm_text(getattr(ln, "text", ""))
        if not txt:
            continue
        if not _is_underline_line(txt):
            continue
        x0 = float(getattr(ln, "x0", 0.0))
        # Avoid label-column masks by requiring it to be not too far left.
        if x0 < (min_x + 0.22 * width):
            continue
        underline_lines.append(ln)

    underline_lines.sort(key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))

    fields = []
    seen_ul = set()

    for ul in underline_lines:
        y = float(getattr(ul, "y0", 0.0))
        x0_ul = float(getattr(ul, "x0", 0.0))
        x1_ul = float(getattr(ul, "x1", x0_ul))
        k = _row_key(y)

        # prevent repeated detection for long underline runs split into multiple line objects
        ul_sig = (k, int(round(x0_ul / 4.0)), int(round(x1_ul / 4.0)))
        if ul_sig in seen_ul:
            continue
        seen_ul.add(ul_sig)

        row = rows.get(k, [])
        # Find a label on the same row to the left of the underline.
        label_ln = None
        best_x = None
        for ln in row:
            if ln is ul:
                continue
            txt = _norm_text(getattr(ln, "text", ""))
            if not txt:
                continue
            if _is_sas_line(txt) or _is_option_line(txt) or _is_checkbox_line(txt):
                continue
            if _is_underline_line(txt) or _looks_like_placeholder(txt):
                continue

            x0 = float(getattr(ln, "x0", 0.0))
            x1 = float(getattr(ln, "x1", x0))
            # Must be meaningfully left of the underline start
            if x1 > x0_ul - 6.0:
                continue

            # Suppress likely column-furniture labels
            if _is_probable_furniture_label(ln, page_box, header_cutoff_y, ans_markers):
                continue

            # Must contain human text
            if _letters_count(txt) < 4:
                continue
            if _looks_like_code_label(txt) or _looks_incomplete_parenthetical(txt):
                continue

            # Prefer the rightmost label on the left side
            if best_x is None or x1 > best_x:
                best_x = x1
                label_ln = ln

        # If not found, look slightly above for a label aligned to the left of underline.
        if label_ln is None:
            best = None
            best_score = None
            for ln in lines:
                y2 = float(getattr(ln, "y0", 0.0))
                if y2 >= y:
                    continue
                if y - y2 > 24.0:
                    continue
                txt = _norm_text(getattr(ln, "text", ""))
                if not txt:
                    continue
                if _is_sas_line(txt) or _is_option_line(txt) or _is_checkbox_line(txt):
                    continue
                if _is_underline_line(txt) or _looks_like_placeholder(txt):
                    continue
                x0 = float(getattr(ln, "x0", 0.0))
                x1 = float(getattr(ln, "x1", x0))
                if x1 > x0_ul - 6.0:
                    continue
                if _is_probable_furniture_label(ln, page_box, header_cutoff_y, ans_markers):
                    continue
                if _letters_count(txt) < 4:
                    continue
                if _looks_like_code_label(txt) or _looks_incomplete_parenthetical(txt):
                    continue

                # Score: closest in y, then closest in x to label column
                score = (y - y2, abs(x0 - label_x))
                if best_score is None or score < best_score:
                    best = ln
                    best_score = score
            label_ln = best

        if label_ln is None:
            continue

        # Join wrapped label lines immediately above (same x band).
        base = _strip_trailing_colon(_norm_text(getattr(label_ln, "text", "")))
        if not base:
            continue

        x0_base = float(getattr(label_ln, "x0", 0.0))
        y0_base = float(getattr(label_ln, "y0", 0.0))
        parts = [base]

        # walk upward to join
        for ln in sorted(lines, key=lambda l: float(getattr(l, "y0", 0.0)), reverse=True):
            if ln is label_ln:
                continue
            y2 = float(getattr(ln, "y0", 0.0))
            if y2 >= y0_base:
                continue
            if y0_base - y2 > 22.0:
                continue
            x0 = float(getattr(ln, "x0", 0.0))
            if abs(x0 - x0_base) > 12.0:
                continue
            txt2 = _norm_text(getattr(ln, "text", ""))
            if not txt2:
                continue
            if _is_sas_line(txt2) or _is_option_line(txt2) or _is_checkbox_line(txt2):
                continue
            if _is_underline_line(txt2) or _looks_like_placeholder(txt2):
                continue
            if _letters_count(txt2) < 4:
                continue
            if _looks_like_code_label(txt2) or _looks_incomplete_parenthetical(txt2):
                continue
            parts.append(_strip_trailing_colon(txt2))
            y0_base = y2

        parts = list(reversed(parts))
        label = _norm_text(" ".join([p for p in parts if p]))
        label = _strip_trailing_colon(label)

        if not label:
            continue
        if _looks_like_placeholder(label) or _looks_like_code_label(label) or _looks_incomplete_parenthetical(label):
            continue

        fields.append(label)

    # De-dup preserve order
    seen_local = set()
    out = []
    for f in fields:
        k = _norm_text(f).lower()
        if k and k not in seen_local:
            seen_local.add(k)
            out.append(f)
    return out


# -------------------------
# Option-group label extraction (fallback)
# -------------------------

def _extract_option_group_label(lines, y0: float, y1: float, label_x: float, page_box, header_cutoff_y: float, ans_markers) -> str:
    # Within a region, find a cluster of option lines and infer the label just above/left.
    min_x, max_x, *_ = page_box
    answer_min_x = label_x + max(34.0, 0.06 * _w(page_box))

    opts = []
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if y < y0 - 0.5 or y > y1 + 0.5:
            continue
        x0 = float(getattr(ln, "x0", 0.0))
        if x0 < answer_min_x:
            continue
        txt = _norm_text(getattr(ln, "text", ""))
        if not txt:
            continue
        if _is_option_line(txt):
            opts.append(ln)

    if len(opts) < 2:
        return ""

    opts.sort(key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))
    first = opts[0]
    base_y = float(getattr(first, "y0", 0.0))
    base_x = float(getattr(first, "x0", 0.0))

    # Find nearest label above within a small window, left column.
    best = None
    best_score = None
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if y >= base_y:
            continue
        if base_y - y > 28.0:
            continue
        if y < header_cutoff_y - 2.0:
            continue
        x0 = float(getattr(ln, "x0", 0.0))
        x1 = float(getattr(ln, "x1", x0))
        # Must be left of the option column
        if x1 > base_x - 10.0:
            continue

        txt = _norm_text(getattr(ln, "text", ""))
        if not txt:
            continue
        if _is_sas_line(txt) or _is_option_line(txt) or _is_checkbox_line(txt):
            continue
        if _looks_like_placeholder(txt) or _is_underline_line(txt):
            continue
        if _is_probable_furniture_label(ln, page_box, header_cutoff_y, ans_markers):
            continue
        if _letters_count(txt) < 4:
            continue
        if _looks_like_code_label(txt) or _looks_incomplete_parenthetical(txt):
            continue

        score = (base_y - y, abs(x0 - label_x))
        if best_score is None or score < best_score:
            best = ln
            best_score = score

    if not best:
        return ""

    label = _strip_trailing_colon(_norm_text(getattr(best, "text", "")))
    if not label:
        return ""
    if _looks_like_placeholder(label) or _looks_like_code_label(label) or _looks_incomplete_parenthetical(label):
        return ""

    return label


def _extract_option_group_labels_pagewide(lines, page_box, header_cutoff_y: float, label_x: float, ans_markers) -> List[str]:
    # Find option clusters pagewide and add only the inferred parent label (not the options).
    answer_min_x = label_x + max(34.0, 0.06 * _w(page_box))

    # Collect option lines in the body.
    opt_lines = []
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if y < header_cutoff_y - 2.0:
            continue
        x0 = float(getattr(ln, "x0", 0.0))
        if x0 < answer_min_x:
            continue
        txt = _norm_text(getattr(ln, "text", ""))
        if txt and _is_option_line(txt) and not _is_sas_line(txt):
            opt_lines.append(ln)

    opt_lines.sort(key=lambda l: (float(getattr(l, "y0", 0.0)), float(getattr(l, "x0", 0.0))))

    # Group into clusters by proximity.
    clusters = []
    cur = []
    last_y = None
    last_x = None

    for ln in opt_lines:
        y = float(getattr(ln, "y0", 0.0))
        x = float(getattr(ln, "x0", 0.0))
        if not cur:
            cur = [ln]
            last_y, last_x = y, x
            continue
        if (y - last_y) <= 16.0 and abs(x - last_x) <= 18.0:
            cur.append(ln)
            last_y, last_x = y, x
        else:
            if len(cur) >= 2:
                clusters.append(cur)
            cur = [ln]
            last_y, last_x = y, x

    if cur and len(cur) >= 2:
        clusters.append(cur)

    labels = []
    for cl in clusters:
        y0 = float(getattr(cl[0], "y0", 0.0))
        y1 = float(getattr(cl[-1], "y0", 0.0)) + 2.0
        # Use region-based extractor to avoid duplicating logic.
        lab = _extract_option_group_label(lines, y0 - 1.0, y1 + 1.0, label_x, page_box, header_cutoff_y, ans_markers)
        if lab:
            labels.append(lab)

    # De-dup preserve order
    seen_local = set()
    out = []
    for l in labels:
        k = _norm_text(l).lower()
        if k and k not in seen_local:
            seen_local.add(k)
            out.append(l)
    return out


# -------------------------
# Checkbox prompts (pagewide)
# -------------------------

def _extract_checkbox_prompts_pagewide(lines, page_box, header_cutoff_y: float, label_x: float) -> List[str]:
    answer_min_x = label_x + max(34.0, 0.06 * _w(page_box))
    prompts = []
    for ln in lines:
        y = float(getattr(ln, "y0", 0.0))
        if y < header_cutoff_y - 2.0:
            continue
        x0 = float(getattr(ln, "x0", 0.0))
        if x0 < answer_min_x:
            continue
        txt = _norm_text(getattr(ln, "text", ""))
        if not txt:
            continue
        if _is_sas_line(txt) or _is_option_line(txt):
            continue
        if not _is_checkbox_line(txt):
            continue
        cleaned = _clean_checkbox_prompt(txt)
        if not cleaned:
            continue
        if _looks_like_placeholder(cleaned) or _looks_like_code_label(cleaned) or _looks_incomplete_parenthetical(cleaned):
            continue
        prompts.append(cleaned)

    seen_local = set()
    out = []
    for p in prompts:
        k = _norm_text(p).lower()
        if k and k not in seen_local:
            seen_local.add(k)
            out.append(p)
    return out


# -------------------------
# Output record helper
# -------------------------

def _add(out, seen, form_name: str, field_name: str, page_num: int) -> None:
    fn = _norm_text(form_name)
    fld = _norm_text(field_name)

    if not fld:
        return
    if _looks_like_placeholder(fld):
        return
    if _looks_like_code_label(fld):
        return
    if _is_sas_line(fld):
        return
    if _is_option_line(fld):
        return
    if _ANSWER_RE.match(fld):
        return

    key = (fn, fld, int(page_num))
    if key in seen:
        return
    seen.add(key)
    out.append({"form_name": fn, "field_name": fld, "page": int(page_num)})
```
