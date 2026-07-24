```python
import re
from typing import List, Dict, Tuple, Optional, Iterable


# --- Regexes ---
_RE_BRACKET_TOKEN = re.compile(r"\[[A-Za-z0-9][A-Za-z0-9_\-]{1,}\]")
_RE_FIELD_CODE_EXACT = re.compile(r"^\[[A-Za-z0-9][A-Za-z0-9_\-]{1,}\]$")

_RE_TYPELIKE = re.compile(r"^\[(TYPE|VISIBILITY|FORMAT|DEFAULT|NOTE|DERIVATION)\b[:\]]", re.I)
_RE_ROW = re.compile(r"^\s*Row\s+\d+\s*$", re.I)

_RE_NUMBERED = re.compile(r"^\s*[\\/]*\s*\d+\s*[\.\)]")
_RE_MOSTLY_PUNCT = re.compile(r"^[\W_]+$")


def _clean_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    # OCR artifact: leading slashes before numbered items (e.g. "\1.") -> "1."
    s = re.sub(r"^\s*[\\/]+\s*(\d+\s*[\.\)])", r"\1", s)
    return s.strip()


def _g(ln, name: str, default):
    return getattr(ln, name, default)


def _page_right(lines) -> float:
    mr = 0.0
    for ln in lines:
        x1 = float(_g(ln, "x1", 0.0) or 0.0)
        if x1 > mr:
            mr = x1
    return mr if mr > 0 else 600.0


def _is_typelike_line(t: str) -> bool:
    t = t.strip()
    return bool(_RE_TYPELIKE.match(t))


def _is_numbered_start_text(t: str) -> bool:
    t = _clean_text(t)
    return bool(_RE_NUMBERED.match(t))


def _extract_code_tokens_from_text(t: str) -> List[str]:
    """
    Raw token extraction only (no geometry checks).
    Excludes typelike tokens and colon-payload blobs.
    """
    t = (t or "").strip()
    if not t:
        return []
    tokens = _RE_BRACKET_TOKEN.findall(t)
    out = []
    for tok in tokens:
        if _RE_TYPELIKE.match(tok):
            continue
        inner = tok[1:-1]
        if ":" in inner:
            continue
        out.append(tok)
    return out


def _is_field_code_line(t: str) -> bool:
    t = t.strip()
    if not _RE_FIELD_CODE_EXACT.match(t):
        return False
    if _RE_TYPELIKE.match(t):
        return False
    inner = t[1:-1]
    if ":" in inner:
        return False
    return True


def _is_row_header(line) -> bool:
    t = _clean_text(_g(line, "text", "") or "")
    return bool(_g(line, "bold", False) and _RE_ROW.match(t))


def _column_thresholds(page_right: float) -> Tuple[float, float]:
    return (page_right * 0.52, page_right * 0.62)


def _x_band_tol(page_right: float) -> float:
    return max(120.0, min(190.0, page_right * 0.17))


def _looks_like_short_option(line, page_right: float) -> bool:
    """
    Right-column anchors/options (Yes/No/Met/Not Met etc.) tend to be extremely short.
    Keep this conservative to avoid filtering short real labels like "If Yes, describe".
    """
    t = _clean_text(_g(line, "text", "") or "")
    if not t:
        return False

    if t.endswith(":") or t.endswith("?"):
        return False

    x0 = float(_g(line, "x0", 0.0) or 0.0)
    size = float(_g(line, "size", 0.0) or 0.0)
    bold = bool(_g(line, "bold", False))
    non_black = bool(_g(line, "non_black", False))

    wc = len([w for w in t.split(" ") if w])

    # strong signal: very short + far-right + colored + small
    if x0 >= page_right * 0.58 and non_black and size <= 11.0 and (len(t) <= 8 or wc <= 2):
        return True

    # weaker signal: extremely short + far-right + small (even if black)
    if x0 >= page_right * 0.68 and size <= 10.5 and not bold and (len(t) <= 6 or wc <= 1):
        return True

    return False


def _is_definitionish_text(t: str) -> bool:
    """
    Filter glossary/definition lines like "Term: explanation ...".
    Structural: colon not at end, short head, longer tail.
    """
    t = _clean_text(t)
    if not t or t.endswith(":") or t.endswith("?"):
        return False
    if ":" not in t:
        return False
    head, tail = t.split(":", 1)
    head = _clean_text(head)
    tail = _clean_text(tail)
    if not head or not tail:
        return False

    # short head (term), longer tail (explanation)
    head_wc = len(head.split())
    tail_wc = len(tail.split())
    if len(head) <= 48 and head_wc <= 6 and tail_wc >= 4 and len(tail) >= 20:
        return True
    return False


def _is_codey_only_text(t: str) -> bool:
    t = _clean_text(t)
    if not t:
        return True
    if _is_field_code_line(t) or _is_typelike_line(t):
        return True
    toks = _extract_code_tokens_from_text(t)
    if toks and _clean_text(_RE_BRACKET_TOKEN.sub(" ", t)) == "":
        return True
    return False


def _is_label_candidate(line, page_right: float) -> bool:
    t = _clean_text(_g(line, "text", "") or "")
    if not t:
        return False
    if _is_typelike_line(t):
        return False
    if _RE_ROW.match(t):
        return False
    if _RE_MOSTLY_PUNCT.match(t):
        return False
    if _is_definitionish_text(t):
        return False
    if _looks_like_short_option(line, page_right):
        return False
    if _is_field_code_line(t):
        return False
    if t.startswith("[") and t.endswith("]") and len(_extract_code_tokens_from_text(t)) > 0:
        remainder = _clean_text(_RE_BRACKET_TOKEN.sub(" ", t))
        if not remainder:
            return False
    return True


def _join_wrap(lines_text: List[str]) -> str:
    out = ""
    for s in lines_text:
        s = _clean_text(s)
        if not s:
            continue
        if not out:
            out = s
            continue
        if out.endswith(("-", "‐", "‑", "–")):
            out = out + s
        else:
            out = out + " " + s
    return out.strip()


def _labelish_score(line) -> int:
    t = _clean_text(_g(line, "text", "") or "")
    if not t:
        return 0
    s = 0
    if bool(_g(line, "bold", False)):
        s += 3
    if t.endswith("?"):
        s += 3
    if t.endswith(":"):
        s += 2
    if _RE_NUMBERED.match(t):
        s += 4
    if len(t) <= 95:
        s += 1
    if _is_definitionish_text(t):
        s -= 3
    return s


def _find_form_title(lines, page_right: float) -> Optional[str]:
    candidates = []
    for ln in lines:
        t = _clean_text(_g(ln, "text", "") or "")
        if not t:
            continue
        if _is_typelike_line(t) or _is_field_code_line(t):
            continue
        if _RE_ROW.match(t):
            continue
        if _is_definitionish_text(t):
            continue

        y0 = float(_g(ln, "y0", 0.0) or 0.0)
        x0 = float(_g(ln, "x0", 0.0) or 0.0)
        size = float(_g(ln, "size", 0.0) or 0.0)
        bold = bool(_g(ln, "bold", False))
        non_black = bool(_g(ln, "non_black", False))

        if y0 > 160:
            continue
        if x0 > page_right * 0.52:
            continue

        if size >= 11.0:
            pass
        elif size >= 10.0 and bold and y0 <= 95:
            pass
        else:
            continue

        if not non_black and not bold:
            continue

        candidates.append((size, -y0, int(bold), int(non_black), -x0, t))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][-1] or None


def _build_row_spans(lines, page_right: float) -> List[Tuple[int, int]]:
    row_idxs = [i for i, ln in enumerate(lines) if _is_row_header(ln)]
    spans = []
    for k, i in enumerate(row_idxs):
        j = row_idxs[k + 1] if k + 1 < len(row_idxs) else len(lines)
        spans.append((i, j))
    return spans


def _row_span_for_index(row_spans: List[Tuple[int, int]], idx: int) -> Optional[Tuple[int, int]]:
    if not row_spans:
        return None
    lo, hi = 0, len(row_spans) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        a, b = row_spans[mid]
        if a <= idx < b:
            return (a, b)
        if idx < a:
            hi = mid - 1
        else:
            lo = mid + 1
    for a, b in reversed(row_spans):
        if a < idx:
            return (a, b)
    return None


def _extract_inline_label_before_code(raw_text: str) -> Optional[str]:
    raw_text = raw_text or ""
    tokens = _extract_code_tokens_from_text(raw_text)
    if not tokens:
        return None

    m = _RE_BRACKET_TOKEN.search(raw_text)
    if not m:
        return None
    prefix = _clean_text(raw_text[: m.start()])
    if not prefix:
        return None
    if _RE_MOSTLY_PUNCT.match(prefix):
        return None
    if _is_definitionish_text(prefix):
        return None
    return prefix


def _extract_inline_label_after_code(raw_text: str) -> Optional[str]:
    """
    Handle lines where the bracket code comes first, e.g.
    "[ABC_01] Has there been a time ...?"
    """
    raw_text = raw_text or ""
    tokens = _extract_code_tokens_from_text(raw_text)
    if not tokens:
        return None

    i = 0
    n = len(raw_text)
    while i < n and raw_text[i].isspace():
        i += 1

    j = i
    matched_any = False
    while True:
        m = _RE_BRACKET_TOKEN.match(raw_text, j)
        if not m:
            break
        matched_any = True
        j = m.end()
        while j < n and raw_text[j] in " \t-–—:|/\\·•)":
            j += 1

    if not matched_any or j <= i:
        return None

    suffix = _clean_text(raw_text[j:])
    if not suffix:
        return None
    if _RE_MOSTLY_PUNCT.match(suffix):
        return None
    if _is_definitionish_text(suffix):
        return None
    if _is_typelike_line(suffix) or _is_field_code_line(suffix) or _is_codey_only_text(suffix):
        return None
    return suffix


def _extract_code_tokens_from_line(line, page_right: float) -> List[str]:
    """
    Geometry-aware: only treat bracket tokens as field markers when the line
    looks like a form marker line (right column / small / colored / codey),
    or when token(s) are clearly attached to a label (prefix or suffix).
    """
    raw = _g(line, "text", "") or ""
    t = _clean_text(raw)
    if not t or _is_typelike_line(t):
        return []

    tokens = _extract_code_tokens_from_text(raw)
    if not tokens:
        return []

    # Always accept pure code lines.
    if _is_field_code_line(t):
        return [t]

    remainder = _clean_text(_RE_BRACKET_TOKEN.sub(" ", raw))
    remainder_len = len(remainder)

    x0 = float(_g(line, "x0", 0.0) or 0.0)
    size = float(_g(line, "size", 0.0) or 0.0)
    bold = bool(_g(line, "bold", False))
    non_black = bool(_g(line, "non_black", False))

    left_col_max, _ = _column_thresholds(page_right)

    endish = bool(re.search(r"\]\s*[\)\.\:\?]*\s*$", raw))
    starts_with_code = bool(re.match(r"^\s*\[[A-Za-z0-9][A-Za-z0-9_\-]{1,}\]", raw))
    labelish_remainder = bool(
        remainder.endswith("?")
        or remainder.endswith(":")
        or bold
        or _is_numbered_start_text(remainder)
    )

    # If it's mostly codes, accept.
    if remainder_len == 0:
        return tokens

    # If it's a long paragraph in left column, reject unless it strongly looks like a field label.
    if (
        x0 <= left_col_max + 10.0
        and not bold
        and not non_black
        and size >= 10.5
        and remainder_len >= 120
        and not labelish_remainder
        and not endish
        and not starts_with_code
    ):
        return []

    # Accept if this looks like a right-column marker/field line.
    if (x0 >= page_right * 0.54 and size <= 11.5) or (non_black and size <= 12.0):
        return tokens

    # Accept if the code is at the start and the remaining text looks like a label.
    if starts_with_code and not _is_definitionish_text(remainder):
        if labelish_remainder or remainder_len <= 120:
            return tokens

    # Accept if tokens are appended to a label (token near line end), including long questions.
    if endish and not _is_definitionish_text(remainder):
        if labelish_remainder or remainder_len <= 170:
            return tokens

    # Accept if the line is already a reasonable label-carrying line.
    if not _is_definitionish_text(remainder):
        if remainder_len <= 140 and (labelish_remainder or remainder_len <= 75):
            return tokens

    return []


def _collect_numbered_block(lines, start_idx: int, span_end: int, page_right: float) -> str:
    base_x = float(_g(lines[start_idx], "x0", 0.0) or 0.0)
    base_size = float(_g(lines[start_idx], "size", 0.0) or 0.0)
    tol = max(55.0, _x_band_tol(page_right) * 0.50)

    parts: List[str] = []
    for j in range(start_idx, min(span_end, len(lines))):
        ln = lines[j]
        if _is_row_header(ln):
            break

        t = _clean_text(_g(ln, "text", "") or "")
        if not t:
            continue

        # stop at next numbered item
        if j > start_idx and _is_numbered_start_text(t):
            break

        if _is_codey_only_text(t):
            continue
        if _looks_like_short_option(ln, page_right):
            continue
        if _is_definitionish_text(t):
            continue

        x0 = float(_g(ln, "x0", 0.0) or 0.0)
        sz = float(_g(ln, "size", 0.0) or 0.0)

        # Keep within a band; allow bullets within item.
        if abs(x0 - base_x) > tol and x0 > base_x + tol:
            if not t.lstrip().startswith(("-", "–", "•")):
                break

        # Soft font drift handling.
        if abs(sz - base_size) > 3.0:
            if not t.lstrip().startswith(("-", "–", "•")):
                pass

        parts.append(_g(ln, "text", "") or "")

    return _join_wrap(parts)


def _extract_label_near_code(
    lines,
    code_idx: int,
    page_right: float,
    row_spans: List[Tuple[int, int]],
) -> Optional[str]:
    code_ln = lines[code_idx]
    code_y = float(_g(code_ln, "y0", 0.0) or 0.0)
    code_x = float(_g(code_ln, "x0", 0.0) or 0.0)
    code_size = float(_g(code_ln, "size", 0.0) or 0.0)

    left_col_max, _right_col_min = _column_thresholds(page_right)
    tolx = _x_band_tol(page_right)

    span = _row_span_for_index(row_spans, code_idx)
    span_start, span_end = (span if span else (0, len(lines)))

    inline_prefix = _extract_inline_label_before_code(_g(code_ln, "text", "") or "")
    inline_suffix = _extract_inline_label_after_code(_g(code_ln, "text", "") or "")
    inline_label = inline_prefix or inline_suffix

    def column_accept(ln) -> bool:
        x0 = float(_g(ln, "x0", 0.0) or 0.0)
        if code_x <= left_col_max:
            return abs(x0 - code_x) <= tolx
        if x0 <= left_col_max + 14.0:
            return True
        return abs(x0 - code_x) <= tolx

    # Prefer same-row neighbor candidates (captures right-column labels aligned with right-column fields).
    neigh_best = None
    neigh_best_score = -10
    neigh_best_cost = 1e18
    ytol = max(11.0, min(22.0, 1.8 * code_size + 2.0))

    for j in range(max(span_start, code_idx - 12), min(span_end, code_idx + 13)):
        if j == code_idx:
            continue
        ln = lines[j]
        if not _is_label_candidate(ln, page_right):
            continue
        if not column_accept(ln):
            continue

        y0 = float(_g(ln, "y0", 0.0) or 0.0)
        if abs(y0 - code_y) > ytol:
            continue

        x0 = float(_g(ln, "x0", 0.0) or 0.0)
        dx = abs(code_x - x0)

        # prefer candidates to the left of the code when possible
        left_pen = 0.0 if x0 <= code_x + 2.0 else 55.0

        sc = _labelish_score(ln)
        cost = (abs(y0 - code_y) * 9.0) + dx + left_pen
        if sc > neigh_best_score or (sc == neigh_best_score and cost < neigh_best_cost):
            neigh_best = j
            neigh_best_score = sc
            neigh_best_cost = cost

    # Seed anchor preference with inline label on the code line (if it's plausible).
    preferred_anchor = neigh_best
    preferred_score = neigh_best_score
    if inline_label and not _is_typelike_line(inline_label):
        if not _RE_MOSTLY_PUNCT.match(inline_label) and not _is_definitionish_text(inline_label):
            preferred_anchor = code_idx
            preferred_score = max(preferred_score, 4 + (4 if _is_numbered_start_text(inline_label) else 0))

    # Find best anchor above (primary), but stay distance-aware to avoid grabbing nearby definitions.
    max_back = max(220.0, min(380.0, page_right * 0.58))
    best_anchor = preferred_anchor
    best_score = preferred_score if best_anchor is not None else -10
    best_cost = 1e18

    for j in range(code_idx - 1, span_start - 1, -1):
        ln = lines[j]
        y0 = float(_g(ln, "y0", 0.0) or 0.0)
        dist = code_y - y0
        if dist > max_back:
            break
        if _is_row_header(ln):
            break
        if not _is_label_candidate(ln, page_right):
            continue
        if not column_accept(ln):
            continue
        sc = _labelish_score(ln)
        cost = (dist * 8.0) - (sc * 25.0)
        if sc > best_score or (sc == best_score and cost < best_cost):
            best_anchor = j
            best_score = sc
            best_cost = cost

    # If still none, search forward below (rare layouts).
    if best_anchor is None:
        max_fwd = max(170.0, min(320.0, page_right * 0.52))
        for j in range(code_idx + 1, min(span_end, len(lines))):
            ln = lines[j]
            y0 = float(_g(ln, "y0", 0.0) or 0.0)
            if y0 - code_y > max_fwd:
                break
            t = _clean_text(_g(ln, "text", "") or "")
            if _is_field_code_line(t) or _is_typelike_line(t):
                break
            if not _is_label_candidate(ln, page_right):
                continue
            if not column_accept(ln):
                continue
            best_anchor = j
            break

    if best_anchor is None:
        return None

    anchor_ln = lines[best_anchor]
    base_x = float(_g(anchor_ln, "x0", 0.0) or 0.0)
    base_size = float(_g(anchor_ln, "size", 0.0) or 0.0)

    anchor_text = _clean_text(_g(anchor_ln, "text", "") or "")
    if inline_label and best_anchor == code_idx:
        anchor_text = inline_label

    # Numbered criteria blocks: collect full wrapped item text until next numbered start.
    if _is_numbered_start_text(anchor_text):
        label = _collect_numbered_block(lines, best_anchor, span_end, page_right)
        return label or None

    def x_ok(ln) -> bool:
        x0 = float(_g(ln, "x0", 0.0) or 0.0)
        t = _clean_text(_g(ln, "text", "") or "")
        bullet = t.lstrip().startswith(("-", "–", "•"))
        slack = max(65.0, tolx * 0.55)
        tight = max(50.0, tolx * 0.40)
        if bullet:
            return (x0 >= base_x - 6.0) and (x0 <= base_x + slack)
        return abs(x0 - base_x) <= tight

    def size_ok(ln) -> bool:
        sz = float(_g(ln, "size", 0.0) or 0.0)
        return abs(sz - base_size) <= 3.2

    # Extend upward (tight wrap).
    start = best_anchor
    prev_y = float(_g(lines[start], "y0", 0.0) or 0.0)
    for j in range(best_anchor - 1, span_start - 1, -1):
        ln = lines[j]
        if _is_row_header(ln):
            break
        if not _is_label_candidate(ln, page_right):
            continue
        if not column_accept(ln):
            break
        if not x_ok(ln) or not size_ok(ln):
            break
        y0 = float(_g(ln, "y0", 0.0) or 0.0)
        if prev_y - y0 > 22.0:
            break
        start = j
        prev_y = y0

    # Collect downward.
    stop_excl = span_end if (best_anchor == code_idx and inline_label) else (code_idx if start <= code_idx else span_end)

    parts: List[str] = []
    prev_included_y: Optional[float] = None

    gap_limit = 28.0
    if anchor_text.endswith("?") or len(anchor_text) >= 70:
        gap_limit = 46.0

    for j in range(start, min(stop_excl, span_end)):
        ln = lines[j]
        if _is_row_header(ln):
            break
        if not _is_label_candidate(ln, page_right):
            continue
        if not column_accept(ln):
            continue
        if not x_ok(ln) or not size_ok(ln):
            continue

        t = _clean_text(_g(ln, "text", "") or "")
        if not t or _is_codey_only_text(t):
            continue
        if _is_definitionish_text(t):
            continue

        y0 = float(_g(ln, "y0", 0.0) or 0.0)
        if prev_included_y is not None:
            if y0 - prev_included_y > gap_limit:
                if parts:
                    break

        # If we started before the code and are about to absorb the code line itself,
        # prefer the inline label to avoid trailing bracket tokens.
        if j == code_idx and inline_label:
            t = inline_label

        parts.append(t)
        prev_included_y = y0

    label = _join_wrap(parts)
    return label or None


def extract(pages: Iterable[Tuple[int, object]]):
    out: List[Dict[str, object]] = []
    seen_fields = set()

    current_form = ""

    for page_idx0, lines in pages:
        pr = _page_right(lines)
        title = _find_form_title(lines, pr)
        if title:
            current_form = title

        row_spans = _build_row_spans(lines, pr)

        for i, ln in enumerate(lines):
            codes = _extract_code_tokens_from_line(ln, pr)
            if not codes:
                continue

            label = _extract_label_near_code(lines, i, pr, row_spans)
            if not label:
                continue

            form_name = (current_form or "").strip()
            field_name = (label or "").strip()
            if not field_name:
                continue
            if _is_field_code_line(field_name) or _is_typelike_line(field_name):
                continue
            if _is_definitionish_text(field_name):
                continue
            if _looks_like_short_option(ln, pr) and len(field_name) <= 10:
                continue

            page_num = page_idx0 + 1
            key = (page_num, form_name, field_name)
            if key in seen_fields:
                continue
            seen_fields.add(key)

            out.append(
                {
                    "form_name": form_name,
                    "field_name": field_name,
                    "page": page_num,
                }
            )

    return out
```
