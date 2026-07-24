```python
import re
from collections import defaultdict

# --- Regexes / constants ---
RE_CODE = re.compile(r'^\[[A-Z0-9_]+\]$')
RE_TYPE = re.compile(r'^\[TYPE\s*:\s*', re.I)
RE_VIS = re.compile(r'^\[VISIBILITY\s*:', re.I)
RE_READONLY = re.compile(r'^\[Read-only field\]$', re.I)
RE_BRACKET_ANY = re.compile(r'^\[.*\]$')
RE_TOC_ITEM = re.compile(r'^\s*\d+(\.\d+)+\.\s+.+')
RE_PAGE_FURN = re.compile(r'^(Pack Version|Annotated CRF|CHANGE HISTORY|SCHEDULE OF ASSESSMENT|PAGES)\b', re.I)
RE_ROW = re.compile(r'^\s*Row\s+\d+\s*$', re.I)

# Common "not a field label" tokens that appear in option lists / UI chrome
RE_OPTION_TOKEN = re.compile(
    r'^(Yes|No|N/?A|NA|Unknown|Not Done|Positive|Negative|Scan|Other|None|Male|Female)$',
    re.I
)

# Lines that are clearly not labels (machine artifacts / broken bracket fragments)
RE_GARBLED_BRACKET = re.compile(r'^\[(?:SCANNE|SCANN|VISIBILIT|VISIBILI|TYPE|READ|RO)\b', re.I)
RE_MANY_BRACKETS = re.compile(r'(?:\[.*?\]){2,}')  # multiple bracket groups in one line


def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '').strip())


def _clean_label_text(t: str) -> str:
    """
    Remove bracketed annotations and obvious OCR/annotation debris from a candidate label.
    Keep it conservative to avoid harming good labels.
    """
    t = _norm(t)
    if not t:
        return t

    # Remove bracketed chunks like "[SCAN]" "[VISIBILITY: ...]" "[TYPE: ...]" "[ABC_123]"
    # but only when they look like annotations (start with [ and end with ]).
    t = re.sub(r'\[(?:TYPE\s*:.*?|VISIBILITY\s*:.*?|Read-only field|[A-Z0-9_]{2,}|SCAN(?:NER|NE|N)?\s*R?|SCANN?E?R?)\]', '', t, flags=re.I)

    # Remove any remaining standalone bracket groups (often annotation fragments)
    # but avoid deleting meaningful bracketed clarifications by only removing if short.
    def _strip_short_brackets(m):
        inner = m.group(0)[1:-1].strip()
        return '' if len(inner) <= 24 else m.group(0)

    t = re.sub(r'\[[^\]]+\]', _strip_short_brackets, t)

    # Remove dangling punctuation from deletions
    t = re.sub(r'\s+([)\],.;:?])', r'\1', t)
    t = re.sub(r'([(\[,])\s+', r'\1', t)
    t = _norm(t)

    # If label begins with punctuation after cleaning, trim
    t = t.lstrip(' ,;:)]}').strip()
    t = _norm(t)
    return t


def _is_probably_option(line):
    # Options are often grey and 9.2pt, short tokens like Yes/No/NA.
    t = _norm(getattr(line, "text", ""))
    if not t:
        return True
    if len(t) <= 4 and re.fullmatch(r'[A-Za-z]{1,4}', t):
        return True
    if RE_OPTION_TOKEN.fullmatch(t):
        return True
    # very short single-word tokens at right side are likely options
    if len(t) <= 12 and ' ' not in t and getattr(line, "x0", 0) > 350 and getattr(line, "size", 0) >= 8.5:
        return True
    return False


def _is_machine_or_annotation(line):
    t = _norm(getattr(line, "text", ""))
    if not t:
        return True
    if RE_TYPE.match(t) or RE_VIS.match(t) or RE_READONLY.match(t):
        return True
    if RE_CODE.match(t):
        return True
    # other bracketed annotations are not labels
    if RE_BRACKET_ANY.match(t):
        return True
    return False


def _is_header_candidate(line):
    t = _norm(getattr(line, "text", ""))
    if not t:
        return False
    if RE_PAGE_FURN.match(t):
        return False
    # Form titles are typically blue and larger (e.g., 14.4) near top.
    if getattr(line, "non_black", False) and getattr(line, "size", 0) >= 12.0 and getattr(line, "y0", 9999) < 120:
        return True
    return False


def _extract_form_title(lines):
    # Choose the most prominent colored header near top.
    cands = [ln for ln in lines if _is_header_candidate(ln)]
    if not cands:
        return None
    # Prefer largest font, then highest on page.
    cands.sort(key=lambda l: (-getattr(l, "size", 0), getattr(l, "y0", 0), getattr(l, "x0", 0)))
    title = _norm(cands[0].text)
    # Avoid TOC items like "3.1. Visit Date" (blue but smaller ~13.1 and many per page)
    if RE_TOC_ITEM.match(title) and getattr(cands[0], "size", 0) <= 13.5:
        return None
    return title


def _build_reading_order(lines):
    # Mostly single column; still, sort by y then x with row clustering.
    if not lines:
        return []
    lines = sorted(lines, key=lambda l: (getattr(l, "y0", 0), getattr(l, "x0", 0)))
    tol = 2.0
    rows = []
    cur = [lines[0]]
    yref = getattr(lines[0], "y0", 0)
    for ln in lines[1:]:
        y = getattr(ln, "y0", 0)
        if abs(y - yref) <= tol:
            cur.append(ln)
        else:
            cur.sort(key=lambda l: getattr(l, "x0", 0))
            rows.extend(cur)
            cur = [ln]
            yref = y
    cur.sort(key=lambda l: getattr(l, "x0", 0))
    rows.extend(cur)
    return rows


def _line_is_garbled(line):
    t = _norm(getattr(line, "text", ""))
    if not t:
        return True
    # Strong signals of OCR/annotation garbage seen on p265
    if RE_GARBLED_BRACKET.match(t):
        return True
    if RE_MANY_BRACKETS.search(t):
        # multiple bracket groups in one line is almost always annotation soup
        return True
    # Too many non-letters relative to length
    letters = sum(ch.isalpha() for ch in t)
    if len(t) >= 20 and letters / max(1, len(t)) < 0.35:
        return True
    return False


def _is_label_like_text(t: str) -> bool:
    t = _norm(t)
    if not t:
        return False
    if RE_TOC_ITEM.match(t):
        return False
    if RE_PAGE_FURN.match(t):
        return False
    if RE_ROW.match(t):
        return False
    if RE_OPTION_TOKEN.fullmatch(t):
        return False
    if RE_TYPE.match(t) or RE_VIS.match(t) or RE_READONLY.match(t):
        return False
    if RE_CODE.match(t):
        return False
    if RE_BRACKET_ANY.match(t):
        return False
    # Avoid pure punctuation/numbers
    if re.fullmatch(r'[\d\W]+', t):
        return False
    # Avoid pure dates
    if re.fullmatch(r'\d{1,2}[A-Za-z]{3}\d{4}', t):
        return False
    return True


def _collect_label_before_type(ordered, idx_type):
    """
    Given ordered lines and index of a [TYPE:] line, find the field label text
    immediately preceding the code/[TYPE] block.
    """
    labels = []
    y_type = getattr(ordered[idx_type], "y0", 0)
    max_dy = 110.0  # slightly more tolerant to catch labels like "Protocol Version for Consent"
    i = idx_type - 1
    while i >= 0:
        ln = ordered[i]
        if _line_is_garbled(ln):
            i -= 1
            continue
        t = _norm(ln.text)
        if not t:
            i -= 1
            continue
        if (y_type - getattr(ln, "y0", 0)) > max_dy:
            break
        if _is_header_candidate(ln):
            break
        if _is_machine_or_annotation(ln):
            i -= 1
            continue
        if RE_ROW.match(t):
            i -= 1
            continue
        if _is_probably_option(ln):
            i -= 1
            continue

        # likely label line: black, small font, left-ish
        if getattr(ln, "x0", 0) <= 160 or getattr(ln, "size", 0) <= 9.5:
            labels.append((getattr(ln, "y0", 0), getattr(ln, "x0", 0), t))
            i -= 1
            continue

        i -= 1

    if not labels:
        return None

    labels.sort(key=lambda z: (z[0], z[1]))
    bottom_y = max(y for y, _, _ in labels)
    kept = [(y, x, t) for (y, x, t) in labels if bottom_y - y <= 34.0]
    kept.sort(key=lambda z: (z[0], z[1]))
    text = _norm(' '.join(t for _, _, t in kept))
    text = _clean_label_text(text)

    if not _is_label_like_text(text):
        return None
    if len(text) > 240:
        return None
    return text


def _collect_label_left_of_type(ordered, idx_type):
    """
    Handle table-like layouts where the field label is in a left column and
    the [CODE]/[TYPE:] block is in a right column on the same row band.
    """
    type_ln = ordered[idx_type]
    y_type = getattr(type_ln, "y0", 0)
    x_type = getattr(type_ln, "x0", 0)

    band = 30.0
    cands = []
    for ln in ordered:
        if _line_is_garbled(ln):
            continue
        t = _norm(ln.text)
        if not t:
            continue
        y = getattr(ln, "y0", 0)
        x = getattr(ln, "x0", 0)
        if abs(y - y_type) > band:
            continue
        if x >= x_type - 40:
            continue
        if _is_header_candidate(ln):
            continue
        if _is_machine_or_annotation(ln):
            continue
        if RE_ROW.match(t):
            continue
        if _is_probably_option(ln):
            continue
        if len(t) > 180:
            continue
        t2 = _clean_label_text(t)
        if not _is_label_like_text(t2):
            continue
        cands.append((abs(y - y_type), x, -getattr(ln, "size", 0), t2))

    if not cands:
        return None

    # closest in y, then further-left (smaller x), then larger font
    cands.sort()
    return _norm(cands[0][-1])


def _collect_label_from_same_row_band(ordered, idx_type):
    """
    NEW: Some pages place the label on the same horizontal band as [TYPE:]
    but not strictly left-of-type (e.g., label may be slightly above-left or mid-left).
    We search within a band and prefer the nearest label-like text to the left/top-left.
    """
    type_ln = ordered[idx_type]
    y_type = getattr(type_ln, "y0", 0)
    x_type = getattr(type_ln, "x0", 0)

    band_y = 40.0
    max_left = x_type - 10
    cands = []
    for ln in ordered:
        if _line_is_garbled(ln):
            continue
        t = _clean_label_text(_norm(ln.text))
        if not _is_label_like_text(t):
            continue
        x = getattr(ln, "x0", 0)
        y = getattr(ln, "y0", 0)
        if x > max_left:
            continue
        if abs(y - y_type) > band_y:
            continue
        # Prefer close in y and reasonably close in x (but left)
        dx = max(0.0, x_type - x)
        dy = abs(y - y_type)
        score = dy * 1.2 + dx * 0.02
        # Avoid grabbing long instruction paragraphs
        if len(t) > 200:
            continue
        cands.append((score, dy, dx, -getattr(ln, "size", 0), t))

    if not cands:
        return None
    cands.sort()
    return _norm(cands[0][-1])


def _collect_question_block_above(ordered, idx_type):
    """
    NEW: For yes/no questions where the label is a full sentence above and the [TYPE:]
    is in a right-side column, we collect 1-3 lines above within a tighter x-range.
    This helps capture:
      - "Consent Obtained?"
      - "Was Informed Consent signed prior to any study procedures being performed?"
      - "Are there any clinically significant abnormal hematology results to be entered?"
    """
    type_ln = ordered[idx_type]
    y_type = getattr(type_ln, "y0", 0)
    x_type = getattr(type_ln, "x0", 0)

    max_dy = 85.0
    min_x = 20.0
    max_x = x_type - 20.0

    # gather candidate lines above, close in x band (left column)
    cands = []
    for ln in ordered:
        if _line_is_garbled(ln):
            continue
        y = getattr(ln, "y0", 0)
        x = getattr(ln, "x0", 0)
        if y >= y_type:
            continue
        if (y_type - y) > max_dy:
            continue
        if not (min_x <= x <= max_x):
            continue
        if _is_header_candidate(ln) or _is_machine_or_annotation(ln) or _is_probably_option(ln):
            continue
        t = _clean_label_text(_norm(ln.text))
        if not _is_label_like_text(t):
            continue
        # Prefer question-like / sentence-like labels
        q_bonus = 0.0
        if t.endswith('?'):
            q_bonus = -10.0
        elif len(t) >= 35:
            q_bonus = -3.0
        score = (y_type - y) + q_bonus + (x * 0.01)
        cands.append((score, y, x, t))

    if not cands:
        return None

    # Take the best line, then optionally prepend a directly-adjacent line above if it looks like a wrapped sentence.
    cands.sort()
    best = cands[0]
    best_y, best_x, best_t = best[1], best[2], best[3]

    # Find a line just above best that continues the sentence (wrap)
    wrap = None
    for ln in ordered:
        if _line_is_garbled(ln):
            continue
        y = getattr(ln, "y0", 0)
        x = getattr(ln, "x0", 0)
        if y >= best_y:
            continue
        if (best_y - y) > 18.0:
            continue
        if abs(x - best_x) > 40.0:
            continue
        if _is_header_candidate(ln) or _is_machine_or_annotation(ln) or _is_probably_option(ln):
            continue
        t = _clean_label_text(_norm(ln.text))
        if not _is_label_like_text(t):
            continue
        # If best doesn't start with lowercase, still allow wrap if previous ends without punctuation.
        if not re.search(r'[.?!:]$', t):
            wrap = t
            break

    if wrap:
        combined = _norm(wrap + " " + best_t)
        combined = _clean_label_text(combined)
        if _is_label_like_text(combined) and len(combined) <= 260:
            return combined

    return _norm(best_t)


def extract(pages):
    out = []
    seen = set()  # (form_name_norm, field_name_norm)
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        title = _extract_form_title(lines)
        if title:
            current_form = title

        ordered = _build_reading_order(lines)

        for i, ln in enumerate(ordered):
            t = _norm(getattr(ln, "text", ""))
            if not t:
                continue
            if not RE_TYPE.match(t):
                continue

            # Strategy 1: label immediately above the code/[TYPE] block.
            label = _collect_label_before_type(ordered, i)

            # Strategy 2: table/two-column layouts where label is left of [TYPE:].
            if not label:
                label = _collect_label_left_of_type(ordered, i)

            # Strategy 3: same-row-band nearest label (more flexible than strict left-of-type).
            if not label:
                label = _collect_label_from_same_row_band(ordered, i)

            # Strategy 4: question/sentence block above (yes/no questions, long prompts).
            if not label:
                label = _collect_question_block_above(ordered, i)

            if not label:
                continue

            # Final cleanup + validation
            label = _clean_label_text(label)
            if not _is_label_like_text(label):
                continue

            # Extra guard against the p265 garbage that slipped through previously
            if RE_GARBLED_BRACKET.match(label) or RE_MANY_BRACKETS.search(label):
                continue
            if len(label) < 2 or len(label) > 260:
                continue

            form_name = _norm(current_form)
            field_name = _norm(label)

            key = (form_name.lower(), field_name.lower())
            if key in seen:
                continue
            seen.add(key)

            out.append({
                "form_name": form_name,
                "field_name": field_name,
                "page": page_idx0 + 1
            })

    return out
```