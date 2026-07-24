# Observed layouts: (1) "Study Events" schedule table pages with a colored header row and many
# blue, non-bold entries in a mid-page column (Forms list), sometimes wrapped across lines.
# (2) Small-font right-margin technical annotation blocks (Description/Mandatory/etc), not fields.
# Strategy: detect the schedule-table layout by geometry/style; extract only the Forms-column
# blue entries as field labels, joining wrapped continuations; ignore annotation-only pages.

import re
import unicodedata
from collections import defaultdict

def extract(pages):
    out = []
    current_form_name = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        if _is_right_margin_annotation_only(lines):
            continue

        if not _is_schedule_table_layout(lines):
            continue

        title = _pick_section_title(lines)
        if title:
            current_form_name = title
        form_name = current_form_name or title or ""

        fields = _extract_forms_column_fields(lines)
        for fld in fields:
            if not fld:
                continue
            out.append({"form_name": form_name, "field_name": fld, "page": page_idx0 + 1})

    return out


# ----------------- helpers -----------------

def _norm_text(s):
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _has_letter(s):
    for ch in s:
        if unicodedata.category(ch).startswith("L"):
            return True
    return False

def _is_mostly_digits_punct(s):
    s = _norm_text(s)
    if not s:
        return False
    good = 0
    for ch in s:
        if ch.isdigit() or ch in " )](}{/\\-–—.,:+*":
            good += 1
    return good / max(1, len(s)) >= 0.85

def _pick_section_title(lines):
    # Left/top colored title (often white text) above the table header row.
    candidates = []
    for ln in lines:
        if ln.y0 > 70:
            break
        if not ln.text:
            continue
        if 10.0 <= float(ln.size) <= 16.0 and ln.non_black and ln.x0 <= 160:
            t = _norm_text(ln.text)
            if t:
                candidates.append((-(float(ln.size)), float(ln.y0), float(ln.x0), t))
    if not candidates:
        return ""
    candidates.sort()
    return candidates[0][3]

def _is_schedule_table_layout(lines):
    # Geometry/style signature: many bold, colored header labels around y~55-75,
    # plus many non-bold colored entries in a mid-page column.
    hdr = 0
    body = 0
    for ln in lines:
        y = float(ln.y0)
        x = float(ln.x0)
        sz = float(ln.size)
        if 45 <= y <= 85 and ln.non_black and ln.bold and 9.0 <= sz <= 13.0 and 20 <= x <= 560:
            if _norm_text(ln.text):
                hdr += 1
        if 80 <= y <= 770 and ln.non_black and (not ln.bold) and 7.0 <= sz <= 11.0 and 120 <= x <= 360:
            if _norm_text(ln.text):
                body += 1
    return hdr >= 3 and body >= 10

def _is_right_margin_annotation_only(lines):
    # Detect pages dominated by tiny black text at right margin near the top.
    tiny_right = 0
    other_content = 0
    for ln in lines:
        t = _norm_text(ln.text or "")
        if not t:
            continue
        y = float(ln.y0)
        x = float(ln.x0)
        sz = float(ln.size)
        if y <= 130 and x >= 420 and sz <= 6.6 and (not ln.non_black):
            tiny_right += 1
        # Count anything that looks like main-body content (excluding standard footer/header).
        if 90 <= y <= 770 and sz >= 7.5 and x <= 420 and t:
            other_content += 1
    return tiny_right >= 3 and other_content == 0

def _extract_forms_column_fields(lines):
    # 1) Gather candidate colored entries likely in the "Forms" column.
    cands = []
    for ln in lines:
        t = _norm_text(ln.text or "")
        if not t:
            continue
        if ln.bold:
            continue
        if not ln.non_black:
            continue
        y = float(ln.y0)
        x = float(ln.x0)
        sz = float(ln.size)
        if not (80 <= y <= 770 and 7.0 <= sz <= 11.0 and 120 <= x <= 360):
            continue
        # Avoid very short stray items unless they look like meaningful tokens.
        cands.append(ln)

    if len(cands) < 6:
        return []

    # 2) Find dominant x-position bin (Forms column).
    bins = defaultdict(int)
    for ln in cands:
        b = int(round(float(ln.x0) / 10.0)) * 10
        bins[b] += 1
    x_bin, x_cnt = max(bins.items(), key=lambda kv: kv[1])
    if x_cnt < 4:
        return []

    x_center = float(x_bin)

    # 3) Keep lines near that column.
    col = [ln for ln in cands if abs(float(ln.x0) - x_center) <= 35]
    col.sort(key=lambda ln: (float(ln.y0), float(ln.x0)))

    # 4) Join wrapped continuations.
    fields = []
    cur = ""
    prev_ln = None

    def flush():
        nonlocal cur
        t = _norm_text(cur)
        cur = ""
        if not t:
            return
        # Heuristic: require at least one letter OR be a mixed token (e.g., AE/CM).
        if not _has_letter(t):
            if not re.search(r"[^\W_]{2,}", t, flags=re.UNICODE) and _is_mostly_digits_punct(t):
                return
        fields.append(t)

    for ln in col:
        t = _norm_text(ln.text or "")
        if not t:
            continue

        if prev_ln is None:
            cur = t
            prev_ln = ln
            continue

        y_gap = float(ln.y0) - float(prev_ln.y0)
        x_gap = abs(float(ln.x0) - float(prev_ln.x0))

        prev_txt = _norm_text(prev_ln.text or "")
        prev_open = prev_txt.count("(") > prev_txt.count(")")

        is_close = (0 < y_gap <= 13.5 and x_gap <= 12.0)
        cont_hint = (
            prev_txt.endswith(("-", "–", "—", "/", "(", ":", ",")) or
            prev_open or
            (not _has_letter(t) and len(t) <= 10) or
            (t and t[0] in ")]}/\\,.:") or
            (t and t[0].isdigit() and (prev_txt.endswith(("-", "–", "—", "(")) or prev_open))
        )

        if is_close and cont_hint:
            # join with or without space depending on punctuation
            if cur.endswith(("-", "–", "—", "/", "(")) or prev_txt.endswith(("-", "–", "—", "/", "(")):
                cur = (cur + t).strip()
            else:
                cur = (cur + " " + t).strip()
        else:
            flush()
            cur = t

        prev_ln = ln

    flush()
    return fields
