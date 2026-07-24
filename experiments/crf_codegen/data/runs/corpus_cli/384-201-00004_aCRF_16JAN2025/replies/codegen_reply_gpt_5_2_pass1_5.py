```python
import re
from typing import List, Tuple, Dict, Optional


_META_TOKENS_RE = re.compile(
    r"^(?:Format:|Data Type:|Origin:|Description:|Mandatory\?:|Disallow\b|Range\b|Units:|Aliases:|Odm OID\b|"
    r"SAS Dataset Name:|SAS Field Name\b|SDS Var Name:|Requires\b|Conditionally Visible\b|Conditional Item:|"
    r"Visible If\b|Edit Checks:|Device Parameter:|Name:|Value\b)"
)

_FURNITURE_RE = re.compile(r"^(?:Annotated CRF|\d+\s+of\s+\d+|https?://\S+)$", re.IGNORECASE)

_LABEL_SIZE_MIN = 6.7
_LABEL_SIZE_MAX = 11.2

_DEFAULT_LABEL_X_MAX = 235.0
_EXPANDED_LABEL_X_MAX = 320.0


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _join_text(a: str, b: str) -> str:
    a = (a or "").rstrip()
    b = (b or "").lstrip()
    if not a:
        return b
    if not b:
        return a
    if a.endswith("-") and b and b[0].isalnum():
        return a[:-1] + b
    if a.endswith(";") and b and b[0].isalnum():
        return a[:-1] + " " + b
    return a + " " + b


def _is_bracket_code(text: str) -> bool:
    t = _norm(text)
    return bool(t.startswith("[") and t.endswith("]") and len(t) >= 3)


def _is_non_field_text(text: str) -> bool:
    t = _norm(text)
    if not t:
        return True

    tl = t.lower()
    if tl.startswith("role restriction:"):
        return True
    if tl.startswith("data collector:"):
        return True

    if "cc mapping" in tl:
        return True
    if re.search(r"\bodm oid\b", t, re.IGNORECASE):
        return True

    if re.match(r"^comment\s*:\s*reading\b", t, re.IGNORECASE):
        return True

    # Common non-field headers in code/decode tables.
    if tl in {"coded", "decode"}:
        return True

    # Very short all-caps section tokens (often module/form abbreviations).
    if re.fullmatch(r"[A-Z]{1,3}", t):
        return True

    # Physical exam body-system headings (not data-entry fields in this family).
    if "/" in t and re.search(r"[a-z]", t) and len(t) <= 44 and not re.search(r"[?:]", t):
        if re.fullmatch(r"[A-Za-z][A-Za-z ]+/[A-Za-z][A-Za-z ]+", t):
            return True

    # Standalone instrument/page headings that are not fields.
    if re.fullmatch(r"Electrocardiogram\s+\d+", t, re.IGNORECASE):
        return True

    return False


def _is_option_line(line) -> bool:
    t = _norm(line.text)
    if not t:
        return False
    if line.x0 >= 160:
        if t.startswith(("O ", "o ", "○ ", "◯ ", "● ", "• ", "▪ ")):
            return True
        if t.startswith(("[ ]", "[x]", "[X]", "( )", "(x)", "(X)")):
            return True
    return False


def _is_footer_or_header(line) -> bool:
    t = _norm(line.text)
    if not t:
        return True
    if line.y0 < 22 and float(line.size) <= 10:
        return True
    if line.y0 > 790 and float(line.size) <= 10:
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


def _is_title_like(ln) -> bool:
    if not ((22 <= ln.y0 <= 52) and (35 <= ln.x0 <= 320) and (11.0 <= float(ln.size) <= 13.8)):
        return False
    t = _norm(ln.text)
    if not t or _FURNITURE_RE.match(t):
        return False
    if not re.search(r"[A-Za-z]", t):
        return False
    if re.fullmatch(r"[A-Z0-9\-/ ]{2,}", t) and len(t) <= 8:
        return False
    return True


def _extract_form_title(lines) -> Optional[str]:
    cands = []
    for ln in lines:
        if _is_title_like(ln):
            t = _norm(ln.text)
            cands.append((ln.x0, -len(t), t))
    if not cands:
        return None
    cands.sort()
    return cands[0][2]


def _has_coded_decode_headers(lines) -> bool:
    coded = False
    decode = False
    for ln in lines:
        if _is_footer_or_header(ln):
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if not (50 <= ln.y0 <= 88):
            continue
        if not (9.0 <= float(ln.size) <= 12.2):
            continue
        if t == "Coded" and (30 <= ln.x0 <= 160):
            coded = True
        elif t == "Decode" and (220 <= ln.x0 <= 390):
            decode = True
        if coded and decode:
            return True
    return False


def _split_title_to_form_field(title: str):
    t = _norm(title)
    if not t:
        return (None, None)

    m = re.match(r"^([A-Z][A-Z0-9]{1,10})\s+(.+)$", t)
    if m:
        form = m.group(1).strip()
        field = _norm(m.group(2))
        if field and not _FURNITURE_RE.match(field) and not _is_non_field_text(field):
            return (form, field)

    return (None, t)


def _is_wrap_continuation(prev_text: str, base_x: float, nxt_x: float, nxt_text: str) -> bool:
    t = _norm(nxt_text)
    if not t:
        return False

    dx = nxt_x - base_x
    if abs(dx) <= 14.0:
        return True

    if not prev_text:
        return False
    prev_end = _norm(prev_text)[-1:]
    if prev_end in {"?", ":", "."}:
        return False

    first = t[0]
    starts_like_cont = first.islower() or first in {")", "]", ",", ";", "-", "—"}
    if not starts_like_cont and t.lower().split(" ", 1)[0] in {
        "and",
        "or",
        "to",
        "of",
        "the",
        "a",
        "an",
        "in",
        "on",
        "for",
        "with",
        "by",
        "from",
        "at",
        "as",
    }:
        starts_like_cont = True

    # Allow hanging indents and moderate column shifts.
    if starts_like_cont and -28.0 <= dx <= 140.0:
        return True

    return False


def _median(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return float((s[mid - 1] + s[mid]) / 2.0)


def _is_labelish(ln, label_x_max: float) -> bool:
    if _is_footer_or_header(ln) or _is_title_like(ln):
        return False
    if ln.x0 > label_x_max:
        return False
    if not (_LABEL_SIZE_MIN <= float(ln.size) <= _LABEL_SIZE_MAX):
        return False

    t = _norm(ln.text)
    if not t:
        return False
    if _is_option_line(ln):
        return False
    if _is_bracket_code(t):
        return False
    if t.startswith("[") or t.startswith("]"):
        return False
    if _META_TOKENS_RE.match(t):
        return False
    if _FURNITURE_RE.match(t):
        return False
    if _is_non_field_text(t):
        return False
    if re.fullmatch(r"[\W_]+", t):
        return False
    if re.fullmatch(r"\d+", t):
        return False
    return True


def _estimate_label_x_max(lines) -> float:
    # Expand on pages that clearly place labels in a wider column.
    wide_cnt = 0
    for ln in lines:
        if _is_footer_or_header(ln) or _is_title_like(ln):
            continue
        if not (_LABEL_SIZE_MIN <= float(ln.size) <= _LABEL_SIZE_MAX):
            continue
        if not (_DEFAULT_LABEL_X_MAX < ln.x0 <= _EXPANDED_LABEL_X_MAX):
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if _is_option_line(ln) or _is_bracket_code(t):
            continue
        if _META_TOKENS_RE.match(t) or _FURNITURE_RE.match(t) or _is_non_field_text(t):
            continue
        if re.fullmatch(r"\d+", t) or re.fullmatch(r"[\W_]+", t):
            continue
        wide_cnt += 1
        if wide_cnt >= 2:
            return _EXPANDED_LABEL_X_MAX
    return _DEFAULT_LABEL_X_MAX


def _is_field_page(lines, label_x_max: float) -> bool:
    meta_cnt = 0
    for ln in lines:
        if _looks_like_meta(ln):
            meta_cnt += 1

    label_cnt = 0
    for ln in lines:
        if _is_labelish(ln, label_x_max):
            label_cnt += 1
            if label_cnt >= 6:
                break

    # Keep original behavior, but add a fallback for families with fewer meta tokens.
    if meta_cnt >= 4 and label_cnt >= 1:
        return True
    if meta_cnt >= 2 and label_cnt >= 3:
        return True
    if label_cnt >= 5:
        return True
    return False


def _extract_table_values(lines) -> List[str]:
    # Collect a few decode-like values from code/decode tables (used for title cleanup).
    vals = []
    for ln in lines:
        if _is_footer_or_header(ln) or _is_title_like(ln):
            continue
        if not (70 <= ln.y0 <= 760):
            continue
        if not (8.4 <= float(ln.size) <= 10.6):
            continue
        if not (35 <= ln.x0 <= 420):
            continue
        t = _norm(ln.text)
        if not t or _FURNITURE_RE.match(t):
            continue
        if t in {"Coded", "Decode"}:
            continue
        vals.append(t)
        if len(vals) >= 12:
            break
    return vals


def _clean_code_decode_title(title: str, table_vals: List[str]) -> str:
    t = _norm(title)
    if not t:
        return t

    # If title looks like "... - <value>", drop the trailing value when it matches table content.
    if " - " in t:
        parts = [p.strip() for p in t.split(" - ") if p.strip()]
        if len(parts) >= 3:
            last = parts[-1]
            prefix = " - ".join(parts[:-1]).strip()
            if prefix and 2 <= len(last) <= 28 and not re.search(r"\b(date|time|start|end|ongoing)\b", last, re.I):
                last_l = last.lower()
                for v in table_vals:
                    vl = v.lower()
                    if last_l == vl or last_l in vl or vl in last_l:
                        return prefix
    return t


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1

        title = _extract_form_title(lines)
        has_cd = _has_coded_decode_headers(lines)
        is_code_decode = bool(has_cd and title)

        # Update current form only on real form pages (not code/decode definition pages).
        if title and not has_cd:
            current_form = title

        # Code/decode definition pages: emit the field described by the title.
        if is_code_decode and title:
            form, field = _split_title_to_form_field(title)
            if not field:
                continue

            table_vals = _extract_table_values(lines)
            field_name = _clean_code_decode_title(field, table_vals)
            field_name = _norm(field_name)

            if not field_name:
                continue
            if field_name in ("Coded", "Decode"):
                continue
            if _FURNITURE_RE.match(field_name):
                continue
            if re.fullmatch(r"\d+", field_name):
                continue
            if _is_bracket_code(field_name):
                continue

            # Keep non-field filter conservative here: many legitimate fields are short/abbrev.
            if field_name.lower().startswith("role restriction:") or field_name.lower().startswith("data collector:"):
                continue

            form_name = form or (current_form or "")
            out.append({"form_name": form_name, "field_name": field_name, "page": page_num})
            continue

        label_x_max = _estimate_label_x_max(lines)
        if not _is_field_page(lines, label_x_max):
            continue

        # Find a strong "inner" header near the top of the label column (often the true form title
        # for sub-forms like "AE Details"). Use it for form attribution and suppress it as a field.
        label_sizes = [float(ln.size) for ln in lines if _is_labelish(ln, label_x_max)]
        med_size = _median(label_sizes)

        inner_title = None
        inner_title_y = None
        inner_title_size = None

        inner_cands = []
        for ln in lines:
            if not _is_labelish(ln, label_x_max):
                continue
            if ln.y0 > 155:
                continue
            t = _norm(ln.text)
            if not t:
                continue
            if t.endswith("?") or ":" in t:
                continue
            if re.fullmatch(r"\d+", t):
                continue
            if len(t) > 52:
                continue
            if float(ln.size) >= med_size + 0.75:
                inner_cands.append((ln.y0, -float(ln.size), len(t), t, ln))

        if inner_cands:
            inner_cands.sort()
            inner_title_y, neg_sz, _, inner_title, ln0 = inner_cands[0]
            inner_title_size = -neg_sz

        page_form = inner_title or (current_form or "")

        page_seen = set()
        extracted_fields = 0

        i = 0
        n = len(lines)
        while i < n:
            ln = lines[i]
            if not _is_labelish(ln, label_x_max):
                i += 1
                continue

            base_x = ln.x0
            y_prev = ln.y0
            text = _norm(ln.text)

            # Suppress the chosen inner title if it appears as a label line.
            if inner_title and text == inner_title and inner_title_y is not None:
                if abs(float(ln.y0) - float(inner_title_y)) <= 2.5 and abs(float(ln.size) - float(inner_title_size or 0)) <= 0.6:
                    i += 1
                    continue

            j = i + 1
            while j < n:
                nxt = lines[j]
                if _is_footer_or_header(nxt):
                    j += 1
                    continue
                if _is_title_like(nxt):
                    break

                nxt_t = _norm(nxt.text)
                if not nxt_t:
                    break

                if _is_option_line(nxt):
                    break
                if nxt.x0 > label_x_max:
                    break
                if _is_bracket_code(nxt_t):
                    break
                if _META_TOKENS_RE.match(nxt_t) or _FURNITURE_RE.match(nxt_t) or _is_non_field_text(nxt_t):
                    break
                if re.fullmatch(r"\d+", nxt_t):
                    break
                if not (_LABEL_SIZE_MIN <= float(nxt.size) <= _LABEL_SIZE_MAX):
                    break

                dy = nxt.y0 - y_prev
                if dy < -0.1:
                    break
                if dy > 19.0:
                    break

                if not _is_wrap_continuation(text, base_x, nxt.x0, nxt_t):
                    break

                text = _join_text(text, nxt_t)
                y_prev = nxt.y0
                j += 1

            field_name = _norm(text)
            if field_name and not _FURNITURE_RE.match(field_name) and not _is_non_field_text(field_name):
                # Suppress repeated inner header-like lines even if not matched above.
                if inner_title and field_name == inner_title and ln.y0 <= 170 and not re.search(r"[?:]", field_name):
                    pass
                else:
                    key = (page_form, field_name)
                    if key not in page_seen:
                        page_seen.add(key)
                        out.append({"form_name": page_form, "field_name": field_name, "page": page_num})
                        extracted_fields += 1

            i = j if j > i else i + 1

        # If the inner title is strong and the page actually yielded fields, persist it across pages.
        if inner_title and extracted_fields >= 2:
            current_form = inner_title

    return out
```
