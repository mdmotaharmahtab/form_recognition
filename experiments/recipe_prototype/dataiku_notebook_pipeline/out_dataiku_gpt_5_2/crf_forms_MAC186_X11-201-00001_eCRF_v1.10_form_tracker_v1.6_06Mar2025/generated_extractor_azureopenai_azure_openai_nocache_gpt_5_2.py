import re
from collections import defaultdict

RE_BRACKET_CODE = re.compile(r"\[\s*\d+\s*\]")
RE_PURE_BRACKET = re.compile(r"^\[\s*\d+\s*\]$")
RE_MACHINE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
RE_NUM_ONLY = re.compile(r"^\d+([.,]\d+)?$")
RE_PUNCT_ONLY = re.compile(r"^[-–—•]+$")

# Common option tokens that should not be treated as fields
RE_OPTION_WORD = re.compile(
    r"^(yes|no|unknown|not done|none|n/?a|na|other|male|female|true|false|positive|negative)$",
    re.I,
)

# Phrases that are typically section headers / instructional text, not fields
RE_NONFIELD_PHRASE = re.compile(
    r"^(variable details|categories|name|export name|type|max length|"
    r"answer for .* only|answer for .*|instructions?|please (specify|enter)|"
    r"most lethal)$",
    re.I,
)

# Words that often appear as fragments when a real field is split across multiple bold chunks
RE_FRAGMENT_WORD = re.compile(
    r"^(attempt|date|time|enter code|code|enter|most lethal|potential lethality|actual lethality)$",
    re.I,
)

# Option-like subitems that often appear under Race/Ethnicity checklists and should not be fields
RE_RACE_OPTION = re.compile(
    r"^(american indian or alaska native|asian|black or african american|"
    r"native hawaiian or other pacific islander|white|"
    r"other(,)?( please specify)?|unknown|not reported|declined to answer)$",
    re.I,
)

# Field labels that are sometimes not bold (e.g., "Visit Date" page 4)
RE_KNOWN_PLAIN_LABEL = re.compile(
    r"^(visit date)$",
    re.I,
)


def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _strip_bracket_codes(s: str) -> str:
    return _norm_space(RE_BRACKET_CODE.sub("", s))


def _is_probably_option_text(s: str) -> bool:
    s = _norm_space(s)
    if not s:
        return True
    if RE_PURE_BRACKET.match(s):
        return True
    if RE_NUM_ONLY.match(s):
        return True
    if len(s) <= 3:
        return True
    if RE_PUNCT_ONLY.fullmatch(s):
        return True
    if RE_OPTION_WORD.fullmatch(s):
        return True
    return False


def _is_header_or_footer(line) -> bool:
    t = line.text.strip()
    if not t:
        return True
    # top file identifier line
    if line.y0 < 45 and len(t) > 20 and ("ecrf" in t.lower() or "form" in t.lower() or "_" in t):
        return True
    return False


def _cluster_rows(lines, y_tol=2.5):
    rows = []
    cur = []
    cur_y = None
    for ln in sorted(lines, key=lambda l: (l.y0, l.x0)):
        y = ln.y0
        if cur_y is None or abs(y - cur_y) <= y_tol:
            cur.append(ln)
            cur_y = y if cur_y is None else (cur_y + y) / 2.0
        else:
            rows.append(cur)
            cur = [ln]
            cur_y = y
    if cur:
        rows.append(cur)
    return rows


def _row_text_sorted(row, rtl=False):
    return sorted(row, key=lambda l: (-l.x0 if rtl else l.x0, l.y0))


def _detect_form_name(lines):
    # Prefer large title around y~70-110, size ~15+
    candidates = []
    for ln in lines:
        if _is_header_or_footer(ln):
            continue
        t = _norm_space(ln.text)
        if not t:
            continue
        if ln.size >= 15 and 55 <= ln.y0 <= 120:
            candidates.append((ln.y0, -ln.size, ln.x0, t))
    if candidates:
        candidates.sort()
        return candidates[0][3]

    # Fallback: small bold header at y~48
    small = []
    for ln in lines:
        t = _norm_space(ln.text)
        if not t:
            continue
        if ln.bold and 6.5 <= ln.size <= 9.5 and 40 <= ln.y0 <= 60 and ln.x0 <= 80:
            if t.lower().startswith("variable details"):
                continue
            small.append((ln.y0, ln.x0, t))
    if small:
        small.sort()
        return small[0][2]

    # Cover page: "Visit:" + next line
    visit = None
    for ln in lines:
        if ln.size >= 18 and "visit" in ln.text.lower():
            visit = ln
            break
    if visit:
        below = [ln for ln in lines if ln.size >= 18 and ln.y0 > visit.y0 + 5]
        if below:
            below.sort(key=lambda l: l.y0)
            return _norm_space(visit.text) + " " + _norm_space(below[0].text)

    return ""


def _is_variable_details_page(lines):
    for ln in lines:
        if ln.bold and 6.5 <= ln.size <= 8.5 and 45 <= ln.y0 <= 62:
            if ln.text.strip().lower().startswith("variable details"):
                return True
    return False


def _extract_fields_variable_details(lines):
    # Table: columns at approx x=80 (Name), x=235 (Export Name), etc.
    # Extract "Name" column entries for each row that begins with [n] at x~41.
    rows = _cluster_rows([ln for ln in lines if not _is_header_or_footer(ln)], y_tol=2.2)
    fields = []
    for row in rows:
        idx_cell = None
        for ln in row:
            if 30 <= ln.x0 <= 60 and RE_PURE_BRACKET.match(ln.text.strip()):
                idx_cell = ln
                break
        if not idx_cell:
            continue

        name_cells = [ln for ln in row if 70 <= ln.x0 <= 220]
        if not name_cells:
            continue

        name_cells_sorted = sorted(name_cells, key=lambda l: l.x0)
        name_text = _norm_space(" ".join([c.text for c in name_cells_sorted]))
        if not name_text:
            continue
        if name_text.lower() == "name":
            continue
        if RE_MACHINE_CODE.match(name_text):
            continue

        # Avoid capturing table section headers that sometimes appear in Name column
        if RE_NONFIELD_PHRASE.match(name_text):
            continue

        fields.append(name_text)
    return fields


def _looks_like_section_header(cleaned: str, joined_raw: str, row_sorted) -> bool:
    low = cleaned.lower()

    # Explicit non-field phrases
    if RE_NONFIELD_PHRASE.match(cleaned):
        return True

    # If it's identical to the form name / page title style (single big bold line)
    if len(RE_BRACKET_CODE.findall(joined_raw)) == 0 and any(ln.bold and ln.size >= 10.2 for ln in row_sorted):
        # short all-caps banners
        if len(cleaned.split()) <= 6 and cleaned.isupper():
            return True
        # single phrase like "Demographics", "Informed Consent"
        if len(cleaned.split()) <= 3 and cleaned[0:1].isalpha() and cleaned == cleaned.title():
            return True

    # Common CRF section titles
    if len(cleaned.split()) <= 4 and low in (
        "demographics",
        "informed consent",
        "medical history",
        "inclusion / exclusion criteria",
        "inclusion/exclusion criteria",
        "visit date",
    ):
        return True

    return False


def _merge_bold_fragments_into_fields(bold_parts):
    """
    bold_parts: list of (x0, text) in reading order for a row.
    Returns list of candidate field strings for that row.
    Strategy:
      - If bracket codes exist, split by them (legacy behavior).
      - Else, if multiple bold chunks exist, join them into one field (prevents fragments like 'Attempt', 'Date').
    """
    joined_raw = _norm_space(" ".join([t for _, t in bold_parts]))
    if not joined_raw:
        return []

    bracket_count = len(RE_BRACKET_CODE.findall(joined_raw))

    # If there are bracket codes, they often delimit multiple labels on one row.
    if bracket_count >= 1:
        tmp = re.sub(r"\s*\[\s*\d+\s*\]\s*", " | ", joined_raw)
        parts = [_strip_bracket_codes(p) for p in tmp.split("|")]
        parts = [_norm_space(p) for p in parts if _norm_space(p)]
        return parts

    # No bracket codes: treat the whole bold run as one label.
    return [_strip_bracket_codes(joined_raw)]


def _filter_plausible_fields(candidates, min_x, bracket_count_hint=0, row_context_text=""):
    out = []
    row_low = _norm_space(row_context_text).lower()

    for p in candidates:
        p = _norm_space(p)
        if not p:
            continue
        pl = p.lower()

        if RE_PURE_BRACKET.match(p):
            continue
        if RE_NUM_ONLY.match(p):
            continue
        if RE_MACHINE_CODE.match(p):
            continue
        if len(p) < 3:
            continue
        if RE_PUNCT_ONLY.fullmatch(p):
            continue

        # Option tokens
        if RE_OPTION_WORD.fullmatch(p):
            continue

        # Instructional / non-field phrases
        if RE_NONFIELD_PHRASE.match(p):
            continue

        # Race checklist options should not be fields (fixes "American Indian or Alaska Native")
        # Trigger if the row context suggests Race/Ethnicity area OR the token itself is a known race option.
        if RE_RACE_OPTION.fullmatch(p):
            if ("race" in row_low) or ("ethnicity" in row_low) or (min_x >= 120):
                continue

        # Avoid capturing fragments that are likely parts of a longer label
        if RE_FRAGMENT_WORD.match(p) and (min_x >= 120 or len(p.split()) <= 2):
            continue

        # If it starts with an option word and had bracket codes in the original row, it's likely an option
        if bracket_count_hint >= 1 and re.match(r"^(yes|no|unknown|not done|none)\b", pl):
            continue

        # If it looks like an option/value and is far to the right, skip
        if _is_probably_option_text(p) and min_x >= 180:
            continue

        out.append(p)
    return out


def _extract_fields_crf_page(lines):
    # Extract bold label lines (size ~6-11) excluding bracket-only and excluding option lists.
    content = [ln for ln in lines if not _is_header_or_footer(ln)]
    rows = _cluster_rows(content, y_tol=2.8)

    fields = []
    for row in rows:
        row_sorted = _row_text_sorted(row, rtl=False)

        bold_parts = []
        for ln in row_sorted:
            t = ln.text.strip()
            if not t:
                continue
            if RE_PURE_BRACKET.match(t):
                continue
            if RE_MACHINE_CODE.match(t) and ln.size <= 11:
                continue
            if ln.bold and 5.5 <= ln.size <= 11.5:
                bold_parts.append((ln.x0, t))

        if not bold_parts:
            continue

        joined_raw = _norm_space(" ".join([p[1] for p in bold_parts]))
        cleaned_joined = _strip_bracket_codes(joined_raw)
        if not cleaned_joined:
            continue

        # Skip section headers / page titles
        if _looks_like_section_header(cleaned_joined, joined_raw, row_sorted):
            continue

        # Skip table header rows listing multiple columns
        bracket_count = len(RE_BRACKET_CODE.findall(joined_raw))
        if bracket_count >= 3 and len(cleaned_joined.split()) <= 12:
            continue

        min_x = min([p[0] for p in bold_parts]) if bold_parts else 0

        # Build candidates:
        candidates = _merge_bold_fragments_into_fields(bold_parts)

        # If we got multiple candidates but they are mostly fragments, prefer the fully-joined label
        if len(candidates) >= 2:
            frag_like = sum(1 for c in candidates if RE_FRAGMENT_WORD.match(_norm_space(c)))
            if frag_like >= 2:
                candidates = [_strip_bracket_codes(joined_raw)]

        row_context_text = " ".join([_norm_space(ln.text) for ln in row_sorted if _norm_space(ln.text)])
        plausible = _filter_plausible_fields(
            candidates, min_x, bracket_count_hint=bracket_count, row_context_text=row_context_text
        )

        # If splitting produced nothing plausible, fall back to the joined label (but still filtered)
        if not plausible:
            plausible = _filter_plausible_fields(
                [cleaned_joined], min_x, bracket_count_hint=bracket_count, row_context_text=row_context_text
            )

        fields.extend(plausible)

    # De-dupe within page extraction
    seen = set()
    out = []
    for f in fields:
        f = _norm_space(f)
        if not f:
            continue
        key = f.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _extract_plain_labels_fallback(lines):
    """
    Fallback for pages where the primary label is not bold (e.g., "Visit Date" page).
    We only extract very conservative known labels to avoid false positives.
    """
    content = [ln for ln in lines if not _is_header_or_footer(ln)]
    rows = _cluster_rows(content, y_tol=2.8)

    found = []
    for row in rows:
        row_sorted = _row_text_sorted(row, rtl=False)
        row_text = _norm_space(" ".join([ln.text for ln in row_sorted]))
        if not row_text:
            continue

        # Skip obvious titles/headers
        if any(ln.size >= 14 for ln in row_sorted) and len(row_text.split()) <= 6:
            continue

        # Extract known plain labels if present as a standalone row or dominant left label
        if RE_KNOWN_PLAIN_LABEL.fullmatch(row_text):
            found.append(_norm_space(row_text))
            continue

        # Sometimes label appears left and value area right; accept if left-most chunk matches
        left_chunks = [ln for ln in row_sorted if ln.x0 <= 140 and _norm_space(ln.text)]
        left_text = _norm_space(" ".join([ln.text for ln in left_chunks]))
        if RE_KNOWN_PLAIN_LABEL.fullmatch(left_text):
            found.append(_norm_space(left_text))

    # de-dupe
    out = []
    seen = set()
    for f in found:
        k = f.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(f)
    return out


def extract(pages):
    results = []
    seen_global = set()  # (form_name_lower, field_name_lower)
    current_form = ""

    for page_idx0, lines in pages:
        page_num = page_idx0 + 1
        if not lines:
            continue

        form = _detect_form_name(lines)
        if form:
            current_form = form

        if _is_variable_details_page(lines):
            fields = _extract_fields_variable_details(lines)
            form_name = current_form or form or "Variable details"
        else:
            fields = _extract_fields_crf_page(lines)
            form_name = current_form or form

            # Conservative fallback for non-bold labels (fixes missing "Visit Date" on some pages)
            if not fields:
                fields = _extract_plain_labels_fallback(lines)

        form_name = _norm_space(form_name) if form_name else ""
        if not form_name:
            # last resort: keep stable grouping
            form_name = current_form or f"Page {page_num}"

        for field in fields:
            field = _norm_space(field)
            if not field:
                continue
            if RE_PURE_BRACKET.match(field):
                continue
            if RE_NUM_ONLY.match(field):
                continue
            if RE_PUNCT_ONLY.fullmatch(field):
                continue

            # Final guard against race options slipping through
            if RE_RACE_OPTION.fullmatch(field):
                continue

            key = (form_name.lower(), field.lower())
            if key in seen_global:
                continue
            seen_global.add(key)

            results.append(
                {
                    "page": page_num,
                    "form_name": form_name,
                    "field_name": field,
                }
            )

    return results
