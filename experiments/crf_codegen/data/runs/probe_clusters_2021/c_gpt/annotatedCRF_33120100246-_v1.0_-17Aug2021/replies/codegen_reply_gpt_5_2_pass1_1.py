```python
# Observed layout: most data-entry fields are announced by a red bracketed item code
# line (e.g. "[XXXX]") followed by red technical lines like "[TYPE: ...]". The human
# label/question is printed in black shortly above (often wraps across lines). Form/section
# title is a prominent top-band line (typically larger and colored), carried forward.

import re
from typing import List, Tuple, Dict, Any, Optional


_WS_RE = re.compile(r"\s+")
_BRACKET_FULL_RE = re.compile(r"^\[(.*)\]$")
_CODE_RE = re.compile(r"^[A-Za-z0-9_]{2,}$")
_ROW_ONLY_RE = re.compile(r"^\s*Row\s*\d+\s*$", re.IGNORECASE)


def _norm_text(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip())


def _is_bracketish(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("[") and ("]" in t)


def _is_row_only(line_text: str) -> bool:
    return bool(_ROW_ONLY_RE.match(line_text or ""))


def _merge_bracket_fragments(lines):
    """
    Merge colored bracket fragments split across lines at same x (e.g. "[SCANNE" + "R]").
    Also merges multi-line bracket payloads (e.g. long "[TYPE: ...]" that wraps) into one.
    """
    merged = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        t = (ln.text or "").strip()
        if ln.non_black and t.startswith("[") and not t.endswith("]"):
            parts = [t]
            x0 = ln.x0
            y0 = ln.y0
            j = i + 1
            while j < n:
                ln2 = lines[j]
                t2 = (ln2.text or "").strip()
                if not ln2.non_black:
                    break
                if abs(ln2.x0 - x0) > 6:
                    break
                if (ln2.y0 - y0) > 30:
                    break
                parts.append(t2)
                y0 = ln2.y0
                if t2.endswith("]"):
                    j += 1
                    break
                j += 1
            if len(parts) > 1:
                new_text = _norm_text(" ".join(parts)).replace("[ ", "[").replace(" ]", "]")
                # lightweight proxy object using original line for geometry
                class _L:
                    __slots__ = ("text", "x0", "y0", "x1", "y1", "size", "bold", "non_black")

                nl = _L()
                nl.text = new_text
                nl.x0, nl.y0, nl.x1, nl.y1 = ln.x0, ln.y0, ln.x1, ln.y1
                nl.size, nl.bold, nl.non_black = ln.size, ln.bold, ln.non_black
                merged.append(nl)
                i = j
                continue
        merged.append(ln)
        i += 1
    return merged


def _field_code_from_bracket_line(text: str) -> Optional[str]:
    t = (text or "").strip()
    m = _BRACKET_FULL_RE.match(t)
    if not m:
        return None
    inner = (m.group(1) or "").strip()
    inner_u = inner.upper()

    # Exclude technical annotations (structure landmarks only)
    if ":" in inner:
        return None
    if "TYPE" in inner_u or "VISIBILITY" in inner_u:
        return None
    if "READ-ONLY" in inner_u or "READ ONLY" in inner_u:
        return None

    if not _CODE_RE.match(inner):
        return None
    return inner


def _pick_form_title(lines, has_fields: bool, current_form: str) -> Optional[str]:
    # Prefer a prominent top-band title (often colored + larger).
    top = [ln for ln in lines if ln.y0 <= 130 and not _is_bracketish(ln.text)]
    if not top:
        return None

    max_size_top = max((ln.size for ln in top), default=0.0)
    if max_size_top < 11.0:
        return None

    cands = []
    for ln in top:
        if ln.x0 > 280:
            continue
        if ln.size < (max_size_top - 0.8):
            continue
        if len((ln.text or "").strip()) < 2:
            continue
        # Prefer colored titles; allow black if very large/bold.
        if ln.non_black or ln.bold or ln.size >= (max_size_top - 0.2):
            cands.append(ln)

    if not cands:
        return None

    # Do not update title on pages without fields unless no title is known yet.
    if not has_fields and current_form:
        return None

    cands.sort(key=lambda l: (l.y0, l.x0))
    return _norm_text(cands[0].text)


def _nearest_row_context(black_lines, y0: float, max_dy: float = 90.0) -> Optional[str]:
    best = None
    best_dy = 1e9
    for ln in black_lines:
        if not ln.bold:
            continue
        if ln.x0 > 160:
            continue
        t = (ln.text or "").strip()
        if not _is_row_only(t):
            continue
        dy = y0 - ln.y0
        if 0 < dy <= max_dy and dy < best_dy:
            best = _norm_text(t)
            best_dy = dy
    return best


def _extract_label_for_code(code_line, black_lines) -> Optional[str]:
    y = code_line.y0
    x = code_line.x0

    # Candidate black lines above within a generous window.
    cands = []
    for ln in black_lines:
        if ln.y0 >= y:
            continue
        dy = y - ln.y0
        if dy > 150:
            continue
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t):
            continue
        # De-emphasize right-side option/legend columns
        if ln.x0 > 420 and abs(ln.x0 - x) > 90:
            continue
        cands.append(ln)

    if not cands:
        return None

    def score(ln):
        dy = y - ln.y0
        dx = abs(ln.x0 - x)
        pen = 0.0
        if x < 140:
            if ln.x0 > 260:
                pen += 250.0
        else:
            # still allow left labels (e.g., question at x~50 with code at x~350),
            # but slightly prefer x-aligned headers when available
            if ln.x0 < 200 and dx > 120:
                pen += 35.0
        if _is_row_only((ln.text or "").strip()):
            pen += 120.0
        # prefer bold line when close (often the actual question)
        if ln.bold and dy <= 70:
            pen -= 18.0
        return dy + 0.30 * dx + pen

    base = min(cands, key=score)
    base_x = base.x0

    # Build a wrapped label block around the base line by proximity/indent.
    # Collect nearby black lines (above and below) with similar indent.
    block = [base]
    # Expand upward
    cands_sorted = sorted([ln for ln in black_lines if ln.y0 < y], key=lambda l: (l.y0, l.x0))
    # find index of base in y-sorted list by identity fallback to nearest y/x match
    idx = None
    for k in range(len(cands_sorted) - 1, -1, -1):
        ln = cands_sorted[k]
        if ln is base:
            idx = k
            break
        if abs(ln.y0 - base.y0) < 0.2 and abs(ln.x0 - base.x0) < 0.2 and (ln.text or "") == (base.text or ""):
            idx = k
            break
    if idx is None:
        idx = 0

    # upwards: tight line spacing and similar indent
    last = base
    k = idx - 1
    while k >= 0:
        ln = cands_sorted[k]
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t):
            k -= 1
            continue
        if _is_row_only(t):
            k -= 1
            continue
        if (last.y0 - ln.y0) > 14.5:
            break
        if abs(ln.x0 - base_x) > 28:
            break
        block.insert(0, ln)
        last = ln
        k -= 1

    # downwards: include continuation lines between base and code
    last = base
    k = idx + 1
    while k < len(cands_sorted):
        ln = cands_sorted[k]
        if ln.y0 >= y:
            break
        t = (ln.text or "").strip()
        if not t or _is_bracketish(t):
            k += 1
            continue
        if _is_row_only(t):
            break
        if (ln.y0 - last.y0) > 14.5:
            break
        if abs(ln.x0 - base_x) > 28:
            break
        block.append(ln)
        last = ln
        k += 1

    label = _norm_text(" ".join((ln.text or "").strip() for ln in block))
    return label or None


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        lines2 = _merge_bracket_fragments(lines)

        # Identify field-code lines (colored bracket codes, excluding TYPE/VISIBILITY/etc.)
        code_lines = []
        for ln in lines2:
            if not ln.non_black:
                continue
            t = (ln.text or "").strip()
            if not (t.startswith("[") and t.endswith("]")):
                continue
            code = _field_code_from_bracket_line(t)
            if code:
                code_lines.append(ln)

        has_fields = bool(code_lines)
        title = _pick_form_title(lines2, has_fields=has_fields, current_form=current_form)
        if title:
            current_form = title

        if not has_fields:
            continue

        black_lines = [ln for ln in lines2 if (not ln.non_black) and (ln.text or "").strip()]

        for cl in code_lines:
            label = _extract_label_for_code(cl, black_lines)
            if not label:
                continue

            # Add row context for dense/repeatable tables so repeated rows don't collapse semantically.
            row_ctx = None
            if cl.y0 >= 260 and cl.x0 >= 150:
                row_ctx = _nearest_row_context(black_lines, cl.y0, max_dy=110.0)
            if row_ctx and row_ctx.lower() not in label.lower():
                field_name = _norm_text(f"{row_ctx} - {label}")
            else:
                field_name = label

            if not field_name:
                continue

            out.append(
                {
                    "form_name": current_form or "",
                    "field_name": field_name,
                    "page": int(page_idx0) + 1,
                }
            )

    return out
```
