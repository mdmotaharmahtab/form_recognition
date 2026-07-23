import re
from collections import defaultdict

def extract(pages):
    # ---------- helpers ----------
    def norm(s):
        s = re.sub(r"\s+", " ", (s or "").strip())
        return s

    def is_page_footer(line):
        t = line.text.strip()
        if not t:
            return True
        if re.search(r"\bAnnotated\s+CRF\b", t, re.I):
            return True
        if re.search(r"\bhttps?://", t, re.I):
            return True
        if re.search(r"\b\d+\s+of\s+\d+\b", t):
            return True
        if re.search(r"\bP\s*a\s*g\s*e\b", t, re.I):
            return True
        return False

    def is_machine_code_line(line):
        t = line.text.strip()
        if not t:
            return True
        # bracketed technical tags
        if t.startswith("[") and t.endswith("]"):
            return True
        if t.startswith("Odm OID") or "Odm OID" in t:
            return True
        if re.match(r"^(Format|Data Type|Origin|Aliases|Description|Mandatory\?|Disallow|Default Item Value|Conditional Item|Visible If Value|Conditionally Visible|Role Restriction|Domain|Repeating)\b", t):
            return True
        # short all-caps variable-like codes (e.g., PEDTC, INC001)
        if getattr(line, "bold", False) and getattr(line, "size", 0) <= 6.2 and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", t):
            return True
        # protocol number header
        if re.fullmatch(r"\d{3}-\d{3}-\d{5}", t):
            return True
        return False

    def is_option_line(line):
        t = line.text.strip()
        if not t:
            return True
        # radio/checkbox options often start with "O " (letter O) in this PDF text
        if re.match(r"^[Oo]\s+\S", t):
            return True
        # underscore entry widgets / date templates
        if re.search(r"\[_\|?_\]", t) or re.search(r"_{5,}", t):
            return True
        # coded/decode tables: numeric/short code in first column
        if re.fullmatch(r"(NA|N/A|MET|NOTMET|UNS|\d+)", t):
            return True
        return False

    def is_cover_label(line):
        # cover page: bold ~16pt labels at x~78
        return getattr(line, "bold", False) and 14.5 <= getattr(line, "size", 0) <= 17.5 and 60 <= getattr(line, "x0", 0) <= 120

    def looks_like_form_title(line):
        # main CRF pages: title in white text around y~35, size ~12
        if getattr(line, "y0", 9999) > 80:
            return False
        if getattr(line, "size", 0) >= 11.0 and getattr(line, "non_black", False):
            # often white on colored bar
            return True
        return False

    def is_code_list_page(lines):
        # detect "Coded" and "Decode" headers (code list pages have no data-entry fields)
        has_coded = any(norm(ln.text).lower() == "coded" for ln in lines if getattr(ln, "y0", 9999) < 120)
        has_decode = any(norm(ln.text).lower() == "decode" for ln in lines if getattr(ln, "y0", 9999) < 120)
        return has_coded and has_decode

    def get_form_from_metadata(lines):
        # schedule/listing pages: right column contains "Form: <name>"
        form = None
        for ln in lines:
            t = ln.text.strip()
            if getattr(ln, "x0", 0) >= 380 and re.match(r"^Form:\s*", t):
                form = norm(re.sub(r"^Form:\s*", "", t))
        return form

    def get_form_from_titlebar(lines):
        candidates = [ln for ln in lines if looks_like_form_title(ln)]
        if not candidates:
            return None
        candidates.sort(key=lambda l: (getattr(l, "y0", 0), getattr(l, "x0", 0)))
        title = norm(candidates[0].text)
        if re.match(r"^(Origin|Aliases)\b", title):
            for ln in candidates[1:]:
                title2 = norm(ln.text)
                if title2 and not re.match(r"^(Origin|Aliases)\b", title2):
                    return title2
            return None
        return title or None

    def looks_like_schedule_page(lines):
        # Cluster 2: schedule/listing pages with columns like:
        # Day X | timepoint | activity/form name, plus right-side metadata "Form:"
        has_form_meta = any(getattr(ln, "x0", 0) >= 380 and ln.text.strip().startswith("Form:") for ln in lines)
        # left columns: repeated "Day <n>" at x~44, size ~9
        day_hits = sum(
            1 for ln in lines
            if 35 <= getattr(ln, "x0", 0) <= 70
            and 8.5 <= getattr(ln, "size", 0) <= 9.5
            and re.match(r"^Day\s+\d+\b", ln.text.strip())
        )
        # activity column around x~200, size ~9
        activity_hits = sum(
            1 for ln in lines
            if 180 <= getattr(ln, "x0", 0) <= 320
            and 8.5 <= getattr(ln, "size", 0) <= 9.5
            and len(norm(ln.text)) >= 3
        )
        return (has_form_meta and day_hits >= 2 and activity_hits >= 2)

    def is_schedule_noise(text):
        t = norm(text)
        if not t:
            return True
        if re.match(r"^Day\s+\d+\b", t):
            return True
        # timepoint like 12:30:00 (1), -01:00:00 (7), *00:00:00 (7)
        if re.fullmatch(r"[*-]?\d{2}:\d{2}:\d{2}\s*\(\d+\)", t):
            return True
        # right-side metadata / rules
        if re.match(r"^(Conditionally Visible|Conditional Item|Visible If Value|Timepoint|Study Event|Form:)\b", t):
            return True
        return False

    def extract_fields_from_schedule_page(lines, page1based):
        # These pages list forms/activities; treat each activity name as a "field_name"
        # under a synthetic form_name so downstream can decide how to use it.
        out = []
        # activity names appear around x~208, size ~9, black
        candidates = []
        for ln in lines:
            if is_page_footer(ln):
                continue
            if getattr(ln, "non_black", False):
                continue
            if not (8.5 <= getattr(ln, "size", 0) <= 9.5):
                continue
            if not (180 <= getattr(ln, "x0", 0) <= 330):
                continue
            t = norm(ln.text)
            if is_schedule_noise(t):
                continue
            # exclude obvious headers if present
            if t.lower() in {"day", "timepoint", "time point", "activity", "procedure", "form"}:
                continue
            candidates.append((getattr(ln, "y0", 0), t))

        # de-dup within page preserving order
        seen_local = set()
        for _, t in sorted(candidates, key=lambda x: x[0]):
            if t in seen_local:
                continue
            seen_local.add(t)
            out.append({"form_name": "Schedule of Assessments", "field_name": t, "page": page1based})
        return out

    def extract_fields_from_main_page(lines, current_form, page1based):
        out = []
        label_lines = []
        for ln in lines:
            if is_page_footer(ln):
                continue
            if getattr(ln, "y0", 9999) < 80 and looks_like_form_title(ln):
                continue
            if getattr(ln, "x0", 0) <= 30:
                continue
            if getattr(ln, "x0", 0) > 220:
                continue
            if getattr(ln, "non_black", False):
                continue
            if not (6.8 <= getattr(ln, "size", 0) <= 8.2):
                continue
            if is_machine_code_line(ln):
                continue
            if is_option_line(ln):
                continue
            t = norm(ln.text)
            if not t:
                continue
            if re.fullmatch(r"[\d\.\)\(]+", t):
                continue
            if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", t):
                continue
            label_lines.append(ln)

        label_lines.sort(key=lambda l: (getattr(l, "y0", 0), getattr(l, "x0", 0)))
        merged = []
        for ln in label_lines:
            t = norm(ln.text)
            if not merged:
                merged.append([ln, t])
                continue
            prev_ln, prev_txt = merged[-1]
            if abs(getattr(ln, "x0", 0) - getattr(prev_ln, "x0", 0)) <= 8 and 0 < (getattr(ln, "y0", 0) - getattr(prev_ln, "y0", 0)) <= 12:
                merged[-1][0] = ln
                merged[-1][1] = norm(prev_txt + " " + t)
            else:
                merged.append([ln, t])

        for ln, t in merged:
            if len(t) < 3:
                continue
            out.append({"form_name": current_form or "", "field_name": t, "page": page1based})
        return out

    def extract_fields_from_cover(lines, page1based):
        out = []
        for ln in lines:
            if is_page_footer(ln):
                continue
            if is_cover_label(ln):
                t = norm(ln.text)
                if t and not re.search(r"\bSponsor Name:\b", t):
                    out.append({"form_name": "aCRF Approval Form", "field_name": t, "page": page1based})
        return out

    # ---------- main loop ----------
    results = []
    seen = set()  # (form_name, field_name)
    current_form = ""

    for page_index, lines in pages:
        page1based = page_index + 1
        if not lines:
            continue

        # Update form context
        title_form = get_form_from_titlebar(lines)
        meta_form = get_form_from_metadata(lines)
        if title_form:
            current_form = title_form
        elif meta_form:
            current_form = meta_form

        # Skip code list pages (cluster 1 samples): genuinely field-free
        if is_code_list_page(lines):
            continue

        # Cover/approval pages
        has_big_title = any(getattr(ln, "bold", False) and getattr(ln, "size", 0) >= 18 and "CRF" in ln.text for ln in lines)
        if has_big_title:
            page_fields = extract_fields_from_cover(lines, page1based)
        elif looks_like_schedule_page(lines):
            # Cluster 2: schedule/listing pages (contain form/activity names; treat as fields)
            page_fields = extract_fields_from_schedule_page(lines, page1based)
        else:
            page_fields = extract_fields_from_main_page(lines, current_form, page1based)

        for rec in page_fields:
            key = (rec["form_name"], rec["field_name"])
            if key in seen:
                continue
            fn = rec["field_name"]
            if not fn or re.fullmatch(r"[\W_]+", fn):
                continue
            if re.match(r"^\[?SAS Field Name\b", fn) or re.match(r"^\[?[A-Z0-9_]{3,}\]?$", fn):
                continue
            seen.add(key)
            results.append(rec)

    return results