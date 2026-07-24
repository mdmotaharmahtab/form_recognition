# Observed layout: most pages are "Annotated CRF" exports with a colored top title bar
# and per-field blocks where the human label sits in the left column while bracketed
# machine tags and technical metadata sit below/at the right in smaller fonts.
# Strategy: detect and carry forward the form title from the top bar; on field pages,
# extract only left-column black label text (joining wrapped lines) while filtering
# bracketed codes, options, metadata, headers/footers, and reference/menu pages.

import re
from collections import Counter
from statistics import median

_WS_RE = re.compile(r"\s+")
_UNDERSCORE_RE = re.compile(r"_{10,}")
_BRACKET_CODE_RE = re.compile(r"^\s*\[[^\]]*\]\s*$")


def _norm(s: str) -> str:
    s = s.strip()
    if not s:
        return ""
    return _WS_RE.sub(" ", s)


def _is_underscore_line(t: str) -> bool:
    t = t.strip()
    if not t:
        return False
    if _UNDERSCORE_RE.search(t):
        return True
    # long runs of underline-like characters
    core = re.sub(r"\s+", "", t)
    if len(core) >= 20 and all(ch in "_-—–" for ch in core):
        return True
    return False


def _is_bracket_code_line(t: str) -> bool:
    # machine tags typically render as a full bracketed line
    return bool(_BRACKET_CODE_RE.match(t.strip()))


def _letters_count(t: str) -> int:
    # unicode-aware "letter" estimate
    return sum(1 for ch in t if ch.isalpha())


def _looks_like_input_marker(t: str) -> bool:
    tt = t.strip()
    if not tt:
        return False
    # radio options usually begin with "O " (circle glyph rendered as capital O)
    if len(tt) >= 2 and tt[0] == "O" and tt[1].isspace():
        return True
    # bracketed blanks / boxes
    if "[" in tt and "]" in tt and ("_" in tt or "|" in tt):
        return True
    # digit-box patterns e.g. [_|_|_] . [_|_]
    if ("_|" in tt) or ("|_" in tt):
        return True
    return False


def _rounded_mode(vals, step=0.1):
    if not vals:
        return None
    r = [round(v / step) * step for v in vals]
    c = Counter(r)
    best = c.most_common(1)[0][0]
    return best


def _page_ymax(lines) -> float:
    if not lines:
        return 0.0
    return max(getattr(l, "y1", getattr(l, "y0", 0.0)) for l in lines)


def _detect_form_title(lines) -> str:
    """
    Prefer top-bar title (often white, non_black, ~12pt) at left.
    Fallback: large black bold centered-ish title (approval page).
    """
    if not lines:
        return ""

    # Top bar title: left side, near y~35, typically non_black (white) and largest in that band.
    top_band = [l for l in lines if l.y0 <= 80 and l.x0 <= 260 and _norm(l.text)]
    if top_band:
        max_sz = max(l.size for l in top_band)
        cand = [
            l
            for l in top_band
            if l.size >= max_sz - 1.2
            and l.x0 <= 200
            and l.y0 <= 60
            and (l.non_black or l.size >= 11.0)
        ]
        if cand:
            cand.sort(key=lambda l: (l.y0, l.x0))
            # join wrapped title lines if any
            parts = []
            last_y = None
            for l in cand:
                t = _norm(l.text)
                if not t:
                    continue
                if last_y is None or (l.y0 - last_y) <= 18:
                    parts.append(t)
                    last_y = l.y0
            title = _norm(" ".join(parts))
            if title:
                return title

    # Approval title: very large black bold around upper-middle
    big = [l for l in lines if l.y0 <= 250 and l.x0 <= 350 and l.bold and l.size >= 16 and _norm(l.text)]
    if big:
        max_sz = max(l.size for l in big)
        cand2 = [l for l in big if l.size >= max_sz - 2.0]
        cand2.sort(key=lambda l: (l.y0, l.x0))
        title = _norm(" ".join(_norm(l.text) for l in cand2))
        return title

    return ""


def _looks_like_menu_page(lines) -> bool:
    """
    Structural "menu/schedule" pages: many small black rows in two left x-clusters
    and almost no bracketed machine tags / input markers.
    """
    if not lines:
        return False

    left_brackets = sum(1 for l in lines if l.x0 <= 220 and _is_bracket_code_line(l.text))
    if left_brackets >= 2:
        return False

    marker_ct = sum(1 for l in lines if _looks_like_input_marker(l.text))
    if marker_ct >= 2:
        return False

    mids = [l for l in lines if 55 <= l.y0 <= (_page_ymax(lines) - 60) and l.x0 <= 240 and not l.non_black]
    if len(mids) < 20:
        return False

    xs = [l.x0 for l in mids if 7.5 <= l.size <= 10.5 and _norm(l.text)]
    if len(xs) < 16:
        return False

    # bin x positions into coarse bins, look for two strong clusters
    bins = Counter(int(x / 20) for x in xs)
    top = bins.most_common(5)
    strong = [b for b, n in top if n >= 8]
    if len(strong) < 2:
        return False
    strong.sort()
    # require separation between two strongest clusters
    if (strong[-1] - strong[0]) * 20 >= 70:
        return True
    return False


def _extract_fields_approval_page(lines) -> list:
    """
    Approval form page: left labels are bold ~16pt at x~80 with values to the right.
    Extract only the bold left labels (exclude big title).
    """
    if not lines:
        return []

    # find large title size to exclude it
    title_sz = None
    for l in lines:
        if l.bold and l.size >= 18 and l.x0 <= 300 and l.y0 <= 250:
            title_sz = l.size
            break

    cand = []
    for l in lines:
        t = _norm(l.text)
        if not t:
            continue
        if _is_underscore_line(t):
            continue
        if l.x0 > 170:
            continue
        if l.y0 < 180 or l.y0 > (_page_ymax(lines) - 80):
            continue
        if not l.bold:
            continue
        if title_sz is not None and abs(l.size - title_sz) <= 2.5:
            continue
        cand.append(l)

    if not cand:
        return []

    sz_mode = _rounded_mode([l.size for l in cand], step=0.5) or median([l.size for l in cand])
    out = []
    for l in cand:
        if abs(l.size - sz_mode) <= max(2.0, 0.2 * sz_mode):
            out.append(_norm(l.text))

    # dedupe in reading order
    seen = set()
    fields = []
    for t in out:
        if t and t not in seen:
            seen.add(t)
            fields.append(t)
    return fields


def _extract_fields_signature_page(lines) -> list:
    """
    Signature page: long underscore lines indicate signature lines; take the first
    human-readable line that follows each underscore at similar x as the label.
    """
    if not lines:
        return []

    # collect underscore baselines
    unders = [l for l in lines if _is_underscore_line(l.text) and l.y0 <= (_page_ymax(lines) - 120)]
    unders.sort(key=lambda l: (l.y0, l.x0))
    fields = []
    for u in unders:
        ux = u.x0
        uy = u.y0
        # find next line within a short window at similar x
        nxt = None
        for l in lines:
            if l.y0 <= uy:
                continue
            if l.y0 - uy > 40:
                break
            if abs(l.x0 - ux) <= 8 and _norm(l.text) and not _is_underscore_line(l.text):
                nxt = l
                break
        if nxt:
            t = _norm(nxt.text)
            if t:
                fields.append(t)

    # dedupe
    seen = set()
    out = []
    for t in fields:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _estimate_label_size(lines) -> float:
    """
    Estimate the typical human label font size for this page from left-column black lines.
    """
    candidates = []
    for l in lines:
        if l.x0 > 200:
            continue
        if l.y0 < 60 or l.y0 > (_page_ymax(lines) - 70):
            continue
        if l.non_black:
            continue
        t = _norm(l.text)
        if not t or _is_bracket_code_line(t) or _is_underscore_line(t):
            continue
        if _letters_count(t) == 0 and not re.search(r"\d+\.", t):
            continue
        # avoid very small technical crumbs
        if l.size < 6.0:
            continue
        candidates.append(l.size)

    if not candidates:
        return 7.5

    mode = _rounded_mode(candidates, step=0.1)
    if mode is not None:
        return float(mode)
    return float(median(candidates))


def _is_field_page_annotated(lines) -> bool:
    if not lines:
        return False
    left_brackets = sum(1 for l in lines if l.x0 <= 220 and _is_bracket_code_line(l.text))
    if left_brackets >= 2:
        return True
    # fallback: looks like it has input glyphs and left labels
    marker_ct = sum(1 for l in lines if _looks_like_input_marker(l.text))
    if marker_ct >= 3:
        return True
    return False


def _extract_fields_annotated(lines) -> list:
    if not lines:
        return []

    y_max = _page_ymax(lines)
    footer_cut = y_max - 55 if y_max else 760

    label_sz = _estimate_label_size(lines)
    sz_tol = max(1.3, 0.22 * label_sz)

    # collect candidate label lines
    cand = []
    for l in lines:
        if l.x0 > 200:
            continue
        if l.y0 < 60 or l.y0 > footer_cut:
            continue
        if l.non_black:
            continue

        t = _norm(l.text)
        if not t:
            continue
        if _is_underscore_line(t):
            continue
        if _is_bracket_code_line(t):
            continue
        # avoid accidental capture of bracket-leading machine lines that aren't fully bracketed
        if t.startswith("["):
            continue
        # filter by size
        if abs(l.size - label_sz) > sz_tol:
            continue
        # require some "human" content: letters or numbered question format
        if _letters_count(t) == 0 and not re.search(r"\d+\.", t):
            continue

        cand.append(l)

    if not cand:
        return []

    cand.sort(key=lambda l: (l.y0, l.x0))

    # group wrapped lines into one field label
    fields = []
    block = []
    prev = None
    for l in cand:
        if prev is None:
            block = [l]
            prev = l
            continue

        same_col = abs(l.x0 - prev.x0) <= 10
        y_gap = l.y0 - prev.y0
        cont_gap = y_gap <= max(12.5, 1.75 * label_sz)

        if same_col and cont_gap and abs(l.size - prev.size) <= 0.8:
            block.append(l)
            prev = l
        else:
            # flush
            parts = [_norm(x.text) for x in block if _norm(x.text)]
            if parts:
                # handle hyphenation
                merged = parts[0]
                for p in parts[1:]:
                    if merged.endswith("-"):
                        merged = merged[:-1] + p
                    else:
                        merged = merged + " " + p
                merged = _norm(merged)
                if merged:
                    fields.append(merged)
            block = [l]
            prev = l

    # final flush
    if block:
        parts = [_norm(x.text) for x in block if _norm(x.text)]
        if parts:
            merged = parts[0]
            for p in parts[1:]:
                if merged.endswith("-"):
                    merged = merged[:-1] + p
                else:
                    merged = merged + " " + p
            merged = _norm(merged)
            if merged:
                fields.append(merged)

    # de-duplicate while preserving order
    seen = set()
    out = []
    for f in fields:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def extract(pages):
    results = []
    current_form = ""
    seen = set()  # (form_name, field_name, page1based)

    for page_idx0, lines in pages:
        page1 = page_idx0 + 1

        # update / carry form title
        title = _detect_form_title(lines)
        if title:
            current_form = title

        # classify page types and extract accordingly
        y_max = _page_ymax(lines)

        # approval pages: very large title near top
        has_big_title = any(l.bold and l.size >= 18 and l.x0 <= 350 and l.y0 <= 250 for l in lines)
        if has_big_title:
            fields = _extract_fields_approval_page(lines)
            for fn in fields:
                form_name = current_form or title or ""
                key = (form_name, fn, page1)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"form_name": form_name, "field_name": fn, "page": page1})
            continue

        # signature page: multiple long underscore lines
        underscore_ct = sum(1 for l in lines if _is_underscore_line(l.text) and l.y0 <= (y_max - 120 if y_max else 650))
        if underscore_ct >= 2 and not _is_field_page_annotated(lines):
            fields = _extract_fields_signature_page(lines)
            for fn in fields:
                form_name = current_form or ""
                key = (form_name, fn, page1)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"form_name": form_name, "field_name": fn, "page": page1})
            continue

        # menu/schedule pages: skip
        if _looks_like_menu_page(lines):
            continue

        # annotated field pages
        if _is_field_page_annotated(lines):
            fields = _extract_fields_annotated(lines)
            for fn in fields:
                form_name = current_form or ""
                key = (form_name, fn, page1)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"form_name": form_name, "field_name": fn, "page": page1})
            continue

        # other pages: conservative fallback (only if there are clear input markers)
        marker_ct = sum(1 for l in lines if _looks_like_input_marker(l.text))
        if marker_ct >= 3:
            fields = _extract_fields_annotated(lines)
            for fn in fields:
                form_name = current_form or ""
                key = (form_name, fn, page1)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"form_name": form_name, "field_name": fn, "page": page1})
            continue

        # otherwise: no extract
        continue

    return results
