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


def _is_non_field_text(text: str) -> bool:
    t = _norm(text)
    if not t:
        return True

    tl = t.lower()
    if tl.startswith("role restriction:"):
        return True
    if tl.startswith("data collector:"):
        return True

    # Mapping / machine metadata lines sometimes appear in the left column.
    if "cc mapping" in tl:
        return True
    if re.search(r"\bodm oid\b", t, re.IGNORECASE):
        return True

    # Known non-field annotation line in this family.
    if re.match(r"^comment\s*:\s*reading\b", t, re.IGNORECASE):
        return True

    # Known table/header-like non-field label in this family.
    if re.match(r"^drug name\s*-\s*study drug admin\b", t, re.IGNORECASE):
        return True

    return False


def _is_option_line(line) -> bool:
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
    return (
        (22 <= ln.y0 <= 52)
        and (35 <= ln.x0 <= 260)
        and (11.0 <= float(ln.size) <= 13.5)
        and bool(getattr(ln, "non_black", False))
        and bool(_norm(ln.text))
        and not _FURNITURE_RE.match(_norm(ln.text))
    )


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


def _is_crf_field_page(lines) -> bool:
    meta_cnt = 0
    for ln in lines:
        if _looks_like_meta(ln):
            meta_cnt += 1
            if meta_cnt >= 4:
                break
    if meta_cnt < 4:
        return False

    for ln in lines:
        if _is_footer_or_header(ln) or _is_title_like(ln):
            continue
        if not (6.7 <= float(ln.size) <= 9.5):
            continue
        if ln.x0 > 205:
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
        if _FURNITURE_RE.match(t):
            continue
        if _is_non_field_text(t):
            continue
        if re.fullmatch(r"[\W_]+", t):
            continue
        if re.fullmatch(r"\d+", t):
            continue
        return True
    return False


def _is_label_line(ln) -> bool:
    if _is_footer_or_header(ln) or _is_title_like(ln):
        return False
    if ln.x0 > 205:
        return False
    if not (6.7 <= float(ln.size) <= 9.5):
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


def _has_coded_decode_headers(lines) -> bool:
    coded = False
    decode = False
    for ln in lines:
        if _is_footer_or_header(ln):
            continue
        t = _norm(ln.text)
        if not t:
            continue
        if not (54 <= ln.y0 <= 76):
            continue
        if not (9.6 <= float(ln.size) <= 11.6):
            continue
        if not bool(getattr(ln, "non_black", False)):
            continue
        if t == "Coded" and (35 <= ln.x0 <= 120):
            coded = True
        elif t == "Decode" and (240 <= ln.x0 <= 360):
            decode = True
        if coded and decode:
            return True
    return False


def _is_code_decode_page(lines, title: Optional[str]) -> bool:
    if not title:
        return False
    return _has_coded_decode_headers(lines)


def _split_title_to_form_field(title: str) -> Tuple[Optional[str], Optional[str]]:
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


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1

        title = _extract_form_title(lines)
        is_code_decode = _is_code_decode_page(lines, title)

        if title and not is_code_decode:
            current_form = title

        if _is_crf_field_page(lines):
            page_seen = set()
            i = 0
            n = len(lines)

            while i < n:
                ln = lines[i]
                if not _is_label_line(ln):
                    i += 1
                    continue

                base_x = ln.x0
                y_prev = ln.y0
                text = _norm(ln.text)

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
                    if nxt.x0 > 225:
                        break

                    if _is_bracket_code(nxt_t) and nxt.x0 <= 225:
                        break

                    if _META_TOKENS_RE.match(nxt_t) or _FURNITURE_RE.match(nxt_t) or _is_non_field_text(nxt_t):
                        break
                    if re.fullmatch(r"\d+", nxt_t):
                        break

                    if not (6.7 <= float(nxt.size) <= 9.5):
                        break

                    if abs(nxt.x0 - base_x) > 12.0:
                        break

                    dy = nxt.y0 - y_prev
                    if dy < 0:
                        break
                    if dy > 17.0:
                        break

                    text = _join_text(text, nxt_t)
                    y_prev = nxt.y0
                    j += 1

                field_name = _norm(text)
                if field_name and not _FURNITURE_RE.match(field_name) and not _is_non_field_text(field_name):
                    key = (current_form, field_name)
                    if key not in page_seen:
                        page_seen.add(key)
                        out.append({"form_name": current_form or "", "field_name": field_name, "page": page_num})

                i = j if j > i else i + 1

            continue

        if is_code_decode and title:
            form, field = _split_title_to_form_field(title)
            if not field:
                continue

            form_name = form or (current_form or "")
            field_name = field

            if field_name in ("Coded", "Decode"):
                continue
            if _FURNITURE_RE.match(field_name):
                continue
            if _is_non_field_text(field_name):
                continue
            if re.fullmatch(r"\d+", field_name):
                continue

            out.append({"form_name": form_name, "field_name": field_name, "page": page_num})

    return out
