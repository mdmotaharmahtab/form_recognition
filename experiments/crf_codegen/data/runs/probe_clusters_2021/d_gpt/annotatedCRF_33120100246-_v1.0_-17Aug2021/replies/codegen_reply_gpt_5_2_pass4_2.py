```python
import re
import unicodedata
from bisect import bisect_left
from collections import defaultdict

_WS_RE = re.compile(r"\s+")
_BRACKET_CODE_RE = re.compile(r"^\[[A-Za-z0-9]{2,}\]$")
_ROW_MARK_RE = re.compile(r"^[^\W\d_]{1,10}\s*\d{1,3}$", re.UNICODE)
_MOSTLY_PUNCT_NUM_RE = re.compile(r"^[\W\d_]+$", re.UNICODE)
_NUMERIC_ITEM_RE = re.compile(r"^\s*\d{1,3}\s*[\.\)]\s+\S")
_NUMERIC_ONLY_RE = re.compile(r"^\s*\d{1,4}\s*$")


def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00ad", "")  # soft hyphen
    s = s.replace("\u200b", "").replace("\ufeff", "")
    s = _WS_RE.sub(" ", s).strip()
    return s


def _has_letters(s: str) -> bool:
    for ch in s:
        if unicodedata.category(ch).startswith("L"):
            return True
    return False


def _looks_like_page_furniture(s: str) -> bool:
    s2 = (s or "").strip()
    if not s2:
        return True
    if _NUMERIC_ONLY_RE.match(s2):
        return True
    if len(s2) <= 2 and (s2.isdigit() or _MOSTLY_PUNCT_NUM_RE.match(s2)):
        return True
    return False


def _is_machine_annotation_text(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return False
    if t.startswith("["):
        return True
    tl = t.lower()
    if "type:" in tl or "visibility" in tl or "read-only" in tl or "readonly" in tl:
        return True
    if "enumeration" in tl or "values:" in tl:
        return True
    if "partialdate" in tl or "partialtime" in tl:
        return True
    return False


def _is_code_anchor_text(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return False
    if _BRACKET_CODE_RE.match(t) and (":" not in t) and (" " not in t) and ("\t" not in t):
        return True
    return False


def _is_type_anchor_text(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return False
    if not t.startswith("["):
        return False
    up = t.upper()
    if "TYPE:" in up:
        return True
    if "PARTIALDATE" in up or "PARTIALTIME" in up:
        return True
    if "READ-ONLY" in up or "READONLY" in up:
        return True
    if "VISIBILITY" in up:
        return True
    return False


def _median(nums):
    if not nums:
        return 0.0
    nums = sorted(nums)
    n = len(nums)
    mid = n // 2
    if n % 2:
        return float(nums[mid])
    return 0.5 * (nums[mid - 1] + nums[mid])


def _estimate_page_width(lines) -> float:
    mx = 0.0
    for ln in lines:
        x1 = getattr(ln, "x1", 0.0) or 0.0
        if x1 > mx:
            mx = x1
    return mx or 612.0


def _get_color_str(ln):
    for attr in ("color", "fill", "stroke", "fontcolor", "textcolor"):
        v = getattr(ln, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _is_non_black(ln) -> bool:
    c = _get_color_str(ln).lower()
    if not c:
        return False
    if c in ("black", "#000", "#000000", "0", "0.0", "rgb(0,0,0)"):
        return False
    return True


def _estimate_left_margin(lines, texts) -> float:
    xs = []
    for ln, t in zip(lines, texts):
        if not t:
            continue
        if _is_machine_annotation_text(t):
            continue
        if _looks_like_page_furniture(t):
            continue
        xs.append(float(getattr(ln, "x0", 0.0) or 0.0))
    if not xs:
        return 0.0
    xs.sort()
    return xs[max(0, min(len(xs) - 1, len(xs) // 10))]  # ~10th percentile


def _estimate_body_size(lines, texts, page_w: float) -> float:
    sizes = []
    for ln, t in zip(lines, texts):
        if not t or _is_machine_annotation_text(t):
            continue
        # ignore big titles in the top band
        if getattr(ln, "y0", 9999.0) < 130 and float(getattr(ln, "size", 0.0) or 0.0) >= 12:
            continue
        # ignore far-right short option/value cells
        if float(getattr(ln, "x0", 0.0) or 0.0) > page_w * 0.75 and len(t) <= 6:
            continue
        sizes.append(float(getattr(ln, "size", 0.0) or 0.0))
    return _median(sizes) or 8.0


def _pick_form_title(lines, texts, page_w: float, body_size: float, page_has_markers: bool) -> str:
    # Only trust weaker headers on marker pages; avoid letting TOC/legend pages overwrite form context.
    cands = []
    for ln, t in zip(lines, texts):
        if not t or _is_machine_annotation_text(t) or _looks_like_page_furniture(t):
            continue
        y0 = float(getattr(ln, "y0", 9999.0) or 9999.0)
        x0 = float(getattr(ln, "x0", 0.0) or 0.0)
        sz = float(getattr(ln, "size", 0.0) or 0.0)
        bold = bool(getattr(ln, "bold", False))
        if y0 > 140:
            continue
        if x0 > page_w * 0.70:
            continue
        if not _has_letters(t):
            continue
        if _ROW_MARK_RE.match(t):
            continue

        non_black = _is_non_black(ln)

        # Strength gating:
        strong = (sz >= max(body_size + 3.0, 12.0)) or (non_black and sz >= max(body_size + 2.0, 11.0))
        medium_top = (y0 < 90 and sz >= body_size + 2.0 and (bold or non_black))
        if not page_has_markers:
            if not strong:
                continue
        else:
            if not (strong or medium_top):
                # prevent mid-body prompts from becoming "form titles"
                continue
            if (not strong) and y0 >= 95:
                continue

        score = 0.0
        score += sz * 4.0
        score += 2.0 if bold else 0.0
        score += 2.5 if non_black else 0.0
        score += 2.0 if y0 < 90 else 0.0
        score += 1.0 if y0 < 120 else 0.0
        score -= 0.045 * y0
        score -= 0.002 * x0
        if len(t) > 70:
            score -= 1.5
        if len(t) > 110:
            score -= 3.0
        cands.append((score, y0, x0, t))

    if not cands:
        return ""
    cands.sort(reverse=True)
    return cands[0][3]


def _build_optionish_indices(lines, texts, left_margin: float, body_size: float, page_w: float):
    optionish = set()

    # Identify dense option rows (multiple short items on the same y band).
    y_buckets = defaultdict(list)
    for i, (ln, t) in enumerate(zip(lines, texts)):
        if not t or _is_machine_annotation_text(t) or _looks_like_page_furniture(t):
            continue
        x0 = float(getattr(ln, "x0", 0.0) or 0.0)
        y0 = float(getattr(ln, "y0", 0.0) or 0.0)
        sz = float(getattr(ln, "size", 0.0) or 0.0)
        bold = bool(getattr(ln, "bold", False))
        if bold:
            continue
        if sz > body_size + 1.2:
            continue
        if x0 <= left_margin + max(95.0, page_w * 0.14):
            continue
        if len(t) > 22:
            continue
        if t.endswith("?") or ":" in t:
            continue
        yk = int(round(y0 / 3.0))
        y_buckets[yk].append(i)

    for yk, idxs in y_buckets.items():
        if len(idxs) >= 3:
            for i in idxs:
                optionish.add(i)

    # Mark individual likely choice texts (right-ish, short, non-bold).
    for i, (ln, t) in enumerate(zip(lines, texts)):
        if not t or _is_machine_annotation_text(t) or _looks_like_page_furniture(t):
            continue
        x0 = float(getattr(ln, "x0", 0.0) or 0.0)
        sz = float(getattr(ln, "size", 0.0) or 0.0)
        bold = bool(getattr(ln, "bold", False))
        if bold:
            continue
        if sz > body_size + 1.2:
            continue
        if x0 > left_margin + max(140.0, page_w * 0.20) and len(t) <= 20 and not t.endswith("?") and ":" not in t:
            optionish.add(i)
        # Numeric rating anchors often look like options.
        if _NUMERIC_ITEM_RE.match(t) and sz <= body_size + 1.2 and not bold:
            optionish.add(i)

    # Mark clusters of numeric anchors in a column (rating scales).
    col_bins = defaultdict(list)
    for i, (ln, t) in enumerate(zip(lines, texts)):
        if not t or _is_machine_annotation_text(t) or _looks_like_page_furniture(t):
            continue
        if not _NUMERIC_ITEM_RE.match(t):
            continue
        x0 = float(getattr(ln, "x0", 0.0) or 0.0)
        y0 = float(getattr(ln, "y0", 0.0) or 0.0)
        xb = int(round(x0 / 35.0))
        col_bins[xb].append((y0, i))
    for xb, items in col_bins.items():
        if len(items) >= 3:
            for _, i in items:
                optionish.add(i)

    return optionish


def _join_wrapped_label(lines, texts, optionish, start_idx: int, page_w: float) -> str:
    base = lines[start_idx]
    base_x = float(getattr(base, "x0", 0.0) or 0.0)
    base_size = float(getattr(base, "size", 0.0) or 0.0)
    base_bold = bool(getattr(base, "bold", False))

    first = texts[start_idx]
    if not first:
        return ""

    parts = [first]
    last_y = float(getattr(base, "y0", 0.0) or 0.0)

    def ok_cont(j, ln, t):
        if not t:
            return False
        if _is_machine_annotation_text(t):
            return False
        if _looks_like_page_furniture(t):
            return False
        if j in optionish:
            return False
        # keep in same label column
        x0 = float(getattr(ln, "x0", 0.0) or 0.0)
        if abs(x0 - base_x) > 24:
            return False
        # similar font size
        sz = float(getattr(ln, "size", 0.0) or 0.0)
        if abs(sz - base_size) > 2.0:
            return False
        # avoid far-right short option/value cells
        if x0 > page_w * 0.62 and len(t) <= 6:
            return False
        # don't merge two distinct questions/prompts into one field
        if parts and parts[-1].endswith("?") and t.endswith("?"):
            return False
        if parts and parts[-1].endswith("?") and t and t[0].isupper() and ("?" in t):
            return False
        # avoid swallowing long explanatory paragraphs as part of a label
        if (not base_bold) and len(t) >= 90:
            return False
        return True

    for j in range(start_idx + 1, len(lines)):
        ln = lines[j]
        t = texts[j]
        if not t:
            continue
        y0 = float(getattr(ln, "y0", 0.0) or 0.0)
        dy = y0 - last_y
        if dy < 0:
            continue
        if dy > 14:
            break
        if not ok_cont(j, ln, t):
            continue
        parts.append(t)
        last_y = y0

    # Hyphenation join
    out_parts = []
    for p in parts:
        if not out_parts:
            out_parts.append(p)
            continue
        prev = out_parts[-1]
        if prev.endswith("-") and p and p[0].islower():
            out_parts[-1] = prev[:-1] + p
        else:
            out_parts.append(p)
    return _norm_text(" ".join(out_parts))


def _find_same_row_left(lines, texts, optionish, ay: float, ax: float, left_margin: float):
    best = None
    best_score = -1e9
    for i, (ln, t) in enumerate(zip(lines, texts)):
        if not t or _is_machine_annotation_text(t) or _looks_like_page_furniture(t):
            continue
        if not _has_letters(t):
            continue
        y0 = float(getattr(ln, "y0", 0.0) or 0.0)
        if abs(y0 - ay) > 10:
            continue
        x0 = float(getattr(ln, "x0", 0.0) or 0.0)
        if x0 >= ax - 4:
            continue
        bold = bool(getattr(ln, "bold", False))
        dx = ax - x0
        score = 0.0
        score += 4.0 if bold else 0.0
        score += 2.0 if x0 <= left_margin + 70 else 0.0
        score -= dx / 40.0
        score -= 3.0 if i in optionish else 0.0
        if score > best_score:
            best_score = score
            best = i
    return best


def _find_above_best(lines, texts, optionish, ay: float, ax: float, left_margin: float, page_w: float):
    # Scan upward in y window for a label-like line.
    best = None
    best_score = -1e9
    lo_y = ay - 190.0
    hi_y = ay + 6.0
    for i, (ln, t) in enumerate(zip(lines, texts)):
        if not t or _is_machine_annotation_text(t) or _looks_like_page_furniture(t):
            continue
        y0 = float(getattr(ln, "y0", 0.0) or 0.0)
        if y0 < lo_y or y0 > hi_y:
            continue
        if y0 > ay + 1.0:
            continue
        if not _has_letters(t):
            continue
        if _ROW_MARK_RE.match(t):
            continue

        x0 = float(getattr(ln, "x0", 0.0) or 0.0)
        bold = bool(getattr(ln, "bold", False))

        # Avoid far-right tiny values/options.
        if x0 > page_w * 0.78 and len(t) <= 8 and not bold:
            continue

        dy = ay - y0
        dx = abs(x0 - (left_margin if ax > page_w * 0.55 else ax))

        score = 0.0
        score += 3.5 if bold else 0.0
        score += 1.8 if x0 <= left_margin + 60 else 0.0
        score -= dy / 12.0
        score -= dx / 65.0
        score -= 4.0 if i in optionish else 0.0
        if len(t) >= 140 and not bold:
            score -= 5.0
        if score > best_score:
            best_score = score
            best = i
    return best


def _find_stem_above(lines, texts, optionish, start_y: float, left_margin: float, page_w: float):
    # When an anchor is near an option, try to recover the stem prompt above (left column).
    best = None
    best_score = -1e9
    lo_y = start_y - 170.0
    hi_y = start_y - 6.0
    for i, (ln, t) in enumerate(zip(lines, texts)):
        if not t or _is_machine_annotation_text(t) or _looks_like_page_furniture(t):
            continue
        if not _has_letters(t):
            continue
        if i in optionish:
            continue
        y0 = float(getattr(ln, "y0", 0.0) or 0.0)
        if y0 < lo_y or y0 > hi_y:
            continue
        x0 = float(getattr(ln, "x0", 0.0) or 0.0)
        bold = bool(getattr(ln, "bold", False))
        if x0 > left_margin + max(90.0, page_w * 0.18):
            continue
        if _ROW_MARK_RE.match(t):
            continue
        if len(t) >= 160 and not bold:
            continue

        dy = start_y - y0
        score = 0.0
        score += 4.0 if bold else 0.0
        score += 2.0 if t.endswith("?") else 0.0
        score += 1.0 if len(t) >= 10 else 0.0
        score -= dy / 10.0
        if score > best_score:
            best_score = score
            best = i
    return best


def extract(pages):
    out = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        texts = [_norm_text(getattr(ln, "text", "") or "") for ln in lines]

        page_w = _estimate_page_width(lines)
        left_margin = _estimate_left_margin(lines, texts)
        body_size = _estimate_body_size(lines, texts, page_w)

        page_has_markers = any(t and _is_machine_annotation_text(t) for t in texts)

        title = _pick_form_title(lines, texts, page_w, body_size, page_has_markers)
        if page_has_markers and title:
            current_form = title

        # If no markers at all, keep behavior conservative (avoid creating false fields).
        if not page_has_markers:
            continue

        optionish = _build_optionish_indices(lines, texts, left_margin, body_size, page_w)

        # Collect anchors: codes and TYPE markers (codes preferred; type secondary).
        anchors = []
        for i, (ln, t) in enumerate(zip(lines, texts)):
            if not t:
                continue
            if _is_code_anchor_text(t):
                anchors.append((float(getattr(ln, "y0", 0.0) or 0.0), float(getattr(ln, "x0", 0.0) or 0.0), i, "code"))
            elif _is_type_anchor_text(t):
                anchors.append((float(getattr(ln, "y0", 0.0) or 0.0), float(getattr(ln, "x0", 0.0) or 0.0), i, "type"))

        if not anchors:
            continue

        anchors.sort()

        seen_fields = set()

        for ay, ax, aidx, akind in anchors:
            # Prefer same-row left label; fallback to above.
            li = _find_same_row_left(lines, texts, optionish, ay, ax, left_margin)
            if li is None:
                li = _find_above_best(lines, texts, optionish, ay, ax, left_margin, page_w)
            if li is None:
                continue

            # If we landed on an option-like line, try to find the stem prompt above.
            if li in optionish:
                stem = _find_stem_above(lines, texts, optionish, ay, left_margin, page_w)
                if stem is not None:
                    li = stem
                else:
                    continue

            field = _join_wrapped_label(lines, texts, optionish, li, page_w)
            if not field or len(field) < 2:
                continue
            if not _has_letters(field):
                continue
            if _is_machine_annotation_text(field):
                continue
            if _looks_like_page_furniture(field):
                continue
            if _ROW_MARK_RE.match(field):
                continue

            # Reject paragraph-like explanatory text (structural: long + not bold + not left column).
            ln0 = lines[li]
            x0 = float(getattr(ln0, "x0", 0.0) or 0.0)
            bold = bool(getattr(ln0, "bold", False))
            if len(field) > 160 and not bold:
                continue
            if len(field) > 110 and not bold and x0 > left_margin + max(70.0, page_w * 0.12):
                continue

            # Avoid treating the page header/title as a field label when far away from the anchor.
            y0 = float(getattr(ln0, "y0", 0.0) or 0.0)
            sz = float(getattr(ln0, "size", 0.0) or 0.0)
            if current_form and field == current_form and y0 < 140 and sz >= body_size + 4.0 and (ay - y0) > 140:
                continue

            key = (current_form or "", field, int(page_idx0) + 1)
            if key in seen_fields:
                continue
            seen_fields.add(key)

            out.append(
                {
                    "form_name": current_form or "",
                    "field_name": field,
                    "page": int(page_idx0) + 1,
                }
            )

    return out
```
