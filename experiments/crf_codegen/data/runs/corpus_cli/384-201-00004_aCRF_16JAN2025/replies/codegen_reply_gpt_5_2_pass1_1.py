```python
# Observed layouts: (1) "Annotated CRF" pages with a white-on-dark form title near top (sz≈12, non_black),
# plus right-side technical metadata column (x>430, sz≈5.6), and left-column field labels (x≈46, sz≈7.5).
# Extraction strategy: detect these pages via title+metadata patterns, carry forward the current form title,
# then scan the left column for human-readable label blocks, joining wrapped lines and skipping codes/options/metadata.

import re
from typing import List, Tuple, Dict, Optional


_META_TOKENS_RE = re.compile(
    r"^(?:Format:|Data Type:|Origin:|Description:|Mandatory\?:|Disallow\b|Range\b|Units:|Aliases:|Odm OID\b|"
    r"SAS Dataset Name:|SAS Field Name\b|SDS Var Name:|Requires\b|Conditionally Visible\b|Conditional Item:|"
    r"Visible If\b|Edit Checks:|Device Parameter:|Name:|Value\b)"
)

_FURNITURE_RE = re.compile(r"^(?:Annotated CRF|\d+\s+of\s+\d+|https?://\S+)$", re.IGNORECASE)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _join_text(a: str, b: str) -> str:
    a = a.rstrip()
    b = b.lstrip()
    if not a:
        return b
    if not b:
        return a
    if a.endswith("-") and b and b[0].isalnum():
        return a[:-1] + b
    return a + " " + b


def _is_bracket_code(text: str) -> bool:
    t = _norm(text)
    return bool(t.startswith("[") and t.endswith("]") and len(t) >= 3)


def _is_option_line(line) -> bool:
    # Radio/checkbox options in this CRF cluster: "O Yes", "O No", etc., usually mid-column (x≈240+).
    t = _norm(line.text)
    if not t:
        return False
    if line.x0 >= 170 and (t.startswith("O ") or t.startswith("○ ") or t.startswith("◯ ")):
        return True
    return False


def _is_footer_or_header(line) -> bool:
    t = _norm(line.text)
    if not t:
        return True
    if line.y0 < 22 and line.size <= 10:
        return True
    if line.y0 > 790 and line.size <= 10:
        return True
    if _FURNITURE_RE.match(t):
        return True
    return False


def _looks_like_meta(line) -> bool:
    t = _norm(line.text)
    if not t:
        return False
    if line.x0 < 380:
        return False
    if not (4.8 <= float(line.size) <= 6.4):
        return False
    return bool(_META_TOKENS_RE.match(t))


def _extract_form_title(lines) -> Optional[str]:
    # White/non-black title at top: sz≈12, y≈35, x≈42.
    cands = []
    for ln in lines:
        if 22 <= ln.y0 <= 52 and 35 <= ln.x0 <= 260 and 11.0 <= float(ln.size) <= 13.5 and ln.non_black:
            t = _norm(ln.text)
            if t and not _FURNITURE_RE.match(t):
                # Prefer leftmost; break ties by longer title.
                cands.append((ln.x0, -len(t), t))
    if not cands:
        return None
    cands.sort()
    return cands[0][2]


def _is_crf_field_page(lines) -> bool:
    # Needs metadata column + at least one plausible left-column field label.
    meta_cnt = 0
    for ln in lines:
        if _looks_like_meta(ln):
            meta_cnt += 1
            if meta_cnt >= 4:
                break
    if meta_cnt < 4:
        return False

    for ln in lines:
        if _is_footer_or_header(ln):
            continue
        if ln.non_black:
            continue
        if not (6.9 <= float(ln.size) <= 8.3):
            continue
        if ln.x0 > 140:
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _is_bracket_code(t):
            continue
        if t.startswith("[") or t.startswith("]"):
            continue
        if _META_TOKENS_RE.match(t):
            continue
        # Exclude page furniture and obvious headings (rare in this cluster at sz 7.5, but keep conservative).
        if _FURNITURE_RE.match(t):
            continue
        return True
    return False


def _is_label_line(ln) -> bool:
    if _is_footer_or_header(ln):
        return False
    if ln.non_black:
        return False
    if ln.x0 > 140:
        return False
    if not (6.9 <= float(ln.size) <= 8.3):
        return False
    t = _norm(ln.text)
    if not t:
        return False
    if _is_bracket_code(t):
        return False
    if t.startswith("[") or t.startswith("]"):
        return False
    if _META_TOKENS_RE.match(t):
        return False
    return True


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1

        title = _extract_form_title(lines)
        if title:
            current_form = title

        if not _is_crf_field_page(lines):
            continue

        # Scan left column for label blocks, joining wrapped lines.
        page_seen = set()

        i = 0
        n = len(lines)
        while i < n:
            ln = lines[i]
            if not _is_label_line(ln):
                i += 1
                continue
            if _is_option_line(ln):
                i += 1
                continue

            # Start block
            base_x = ln.x0
            base_size = float(ln.size)
            y_prev = ln.y0
            text = _norm(ln.text)

            j = i + 1
            while j < n:
                nxt = lines[j]
                if _is_footer_or_header(nxt):
                    j += 1
                    continue

                # Stop if next is a bracket code on left (the CRF prints machine tags like [CMYN] under labels).
                nxt_t = _norm(nxt.text)
                if nxt.x0 <= 160 and _is_bracket_code(nxt_t):
                    break

                # Stop if we hit an option list line or jump far right.
                if _is_option_line(nxt) or nxt.x0 > 170:
                    break

                # Continuation must look like a label line with similar geometry and small y-gap.
                if nxt.non_black:
                    break
                if not (6.9 <= float(nxt.size) <= 8.3):
                    break

                # Similar left alignment (wrapped lines keep same left margin).
                if abs(nxt.x0 - base_x) > 6.5:
                    break

                dy = nxt.y0 - y_prev
                if dy < 0:
                    break
                if dy > 14.0:
                    break

                # Exclude accidental metadata-like lines.
                if _META_TOKENS_RE.match(nxt_t) or _is_bracket_code(nxt_t):
                    break

                # Continuation accepted
                text = _join_text(text, nxt_t)
                y_prev = nxt.y0
                j += 1

            field_name = _norm(text)

            # Final filtering: keep human-readable labels (allow short like "PR", but avoid stray punctuation).
            if field_name and not _FURNITURE_RE.match(field_name):
                key = (current_form, field_name)
                if key not in page_seen:
                    page_seen.add(key)
                    out.append({"form_name": current_form or "", "field_name": field_name, "page": page_num})

            i = j if j > i else i + 1

    return out
```
