```python
import re
import statistics
from typing import List, Dict, Optional, Tuple, Iterable


_RX_PROTOCOL = re.compile(r"^\d{2,6}-\d{2,6}-\d{4,8}$")
_RX_URL = re.compile(r"(?i)\bhttps?://\S+\b")

# Widgets: radio options, bracketed fill boxes, underscore fill lines
_RX_WIDGET_RADIO = re.compile(r"^\s*[Oo]\s+\S")
_RX_WIDGET_BOX = re.compile(r"[\[_][\s\|\._/-]*[_\|]{2,}[\s\|\._/-]*[\]_]")
_RX_WIDGET_EMPTY_BRACKET = re.compile(r"\[\s{3,}\]")
_RX_WIDGET_EMPTY_BRACKET2 = re.compile(r"\[\s*[\.\-]{2,}\s*\]")
_RX_WIDGET_EMPTY_BRACKET3 = re.compile(r"\[\s*[_\-\.\s]{0,2}\s*\]")
_RX_UNDERSCORE_LINE = re.compile(r"^_{10,}$")

# Machine-ish codes embedded in otherwise human labels, e.g. "Severity [AESEV]"
_RX_TRAILING_BRACKET_CODE = re.compile(r"\s*\[[A-Za-z0-9_]{2,}\]\s*$")
_RX_PARENS_CODE = re.compile(r"\s*\([A-Za-z0-9_]{2,}\)\s*$")


def _norm_space(s: str) -> str:
    return " ".join(s.split())


def _count_letters(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


def _count_alnum(text: str) -> int:
    return sum(1 for ch in text if ch.isalnum())


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _text(ln) -> str:
    return getattr(ln, "text", "") or ""


def _page_wh(lines) -> Tuple[float, float]:
    # Infer page width/height from geometry; fall back to letter-ish.
    max_x = 0.0
    max_y = 0.0
    for ln in lines:
        x0 = _safe_float(getattr(ln, "x0", 0.0))
        y0 = _safe_float(getattr(ln, "y0", 0.0))
        x1 = _safe_float(getattr(ln, "x1", x0))
        y1 = _safe_float(getattr(ln, "y1", y0))
        max_x = max(max_x, x0, x1)
        max_y = max(max_y, y0, y1)
    if max_x < 200:
        max_x = 612.0
    if max_y < 200:
        max_y = 792.0
    return max_x, max_y


def _median_font_size(lines) -> float:
    sizes = []
    for ln in lines:
        t = _text(ln).strip()
        if not t:
            continue
        sz = _safe_float(getattr(ln, "size", 0.0))
        if sz > 0.1:
            sizes.append(sz)
    if not sizes:
        return 10.0
    return float(statistics.median(sizes))


def _is_protocol_number(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 40:
        return False
    if _RX_PROTOCOL.match(t):
        return True
    if all(ch.isdigit() or ch == "-" for ch in t) and sum(ch.isdigit() for ch in t) >= 8 and "-" in t:
        return True
    return False


def _is_junk_headerish(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if _RX_URL.search(t):
        return True
    # page furniture often includes separated letters "P a g e"
    if len(t) <= 30 and sum(ch.isalpha() for ch in t) >= 3 and " " in t and t.replace(" ", "").isalpha():
        return True
    return False


def _looks_like_code_bracket(text: str) -> bool:
    t = text.strip()
    return len(t) >= 3 and t[0] == "[" and t[-1] == "]"


def _looks_like_widget(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if _RX_WIDGET_RADIO.match(t):
        return True
    if _RX_WIDGET_BOX.search(t):
        return True
    if _RX_UNDERSCORE_LINE.match(t):
        return True
    if t.count("_") >= 10 and len(t) >= 12:
        return True
    # bracketed empty fill boxes (no letters/digits inside)
    if t.startswith("[") and t.endswith("]") and _count_alnum(t[1:-1]) == 0:
        if _RX_WIDGET_EMPTY_BRACKET.search(t) or _RX_WIDGET_EMPTY_BRACKET2.search(t):
            return True
        inner = t[1:-1]
        if len(inner) >= 4 and sum(1 for ch in inner if ch in " _.-") >= 3 and _RX_WIDGET_EMPTY_BRACKET3.search(t):
            return True
    return False


def _strip_machine_code_suffix(label: str) -> str:
    t = _norm_space(label)
    # remove trailing bracket codes like [AESEV], repeatedly if stacked
    while True:
        t2 = _RX_TRAILING_BRACKET_CODE.sub("", t)
        if t2 == t:
            break
        t = _norm_space(t2)
    # also remove trailing paren codes like (AESEV)
    while True:
        t2 = _RX_PARENS_CODE.sub("", t)
        if t2 == t:
            break
        t = _norm_space(t2)
    return t


def _is_title_candidate_text(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if _is_protocol_number(t) or _is_junk_headerish(t):
        return False
    if _looks_like_widget(t):
        return False
    if _looks_like_code_bracket(t):
        return False
    # avoid signature/underline-heavy strings becoming titles
    if t.count("_") >= 6:
        return False
    return True


def _page_left_xmax(lines) -> float:
    # Identify the left label column boundary from the leftmost text cluster.
    w, h = _page_wh(lines)
    xs = []
    for ln in lines:
        t = _text(ln)
        if not t:
            continue
        s = t.strip()
        if not s:
            continue
        if _is_junk_headerish(s) or _is_protocol_number(s):
            continue
        if _looks_like_widget(s):
            continue
        # exclude footer-ish
        if _safe_float(getattr(ln, "y0", 0.0)) > 0.93 * h:
            continue
        # exclude far-right technical column; allow some drift
        if _safe_float(getattr(ln, "x0", 0.0)) > 0.70 * w:
            continue
        xs.append(_safe_float(getattr(ln, "x0", 0.0)))

    if not xs:
        return 0.33 * w

    xs.sort()
    n = len(xs)
    low = xs[: max(3, int(n * 0.25))]
    med_low = statistics.median(low) if low else xs[0]
    mn = xs[0]

    # Typical: labels near mn/med_low; widgets/options start well right of that.
    left_xmax = max(0.24 * w, min(0.55 * w, med_low + 0.38 * w, mn + 0.44 * w))
    return float(left_xmax)


def _collect_widgets(lines):
    widgets = []
    for ln in lines:
        s = _text(ln).strip()
        if not s:
            continue
        if _looks_like_widget(s):
            widgets.append(ln)
    widgets.sort(key=lambda z: (_safe_float(getattr(z, "y0", 0.0)), _safe_float(getattr(z, "x0", 0.0))))
    return widgets


def _looks_like_approval_page(lines) -> bool:
    # Large bold title near top is a strong structural signature.
    w, h = _page_wh(lines)
    top_band = 0.30 * h
    for ln in lines:
        s = _text(ln).strip()
        if not s:
            continue
        if not _is_title_candidate_text(s):
            continue
        if _safe_float(getattr(ln, "y0", 0.0)) < top_band and bool(getattr(ln, "bold", False)) and _safe_float(getattr(ln, "size", 0.0)) >= 18:
            if _safe_float(getattr(ln, "x0", 0.0)) < 0.85 * w and _count_letters(s) >= 4:
                return True
    return False


def _join_title_band(lines, anchor_ln, y_slack: float = 20.0, x_slack: float = 70.0) -> str:
    base_x = _safe_float(getattr(anchor_ln, "x0", 0.0))
    base_y = _safe_float(getattr(anchor_ln, "y0", 0.0))
    base_sz = _safe_float(getattr(anchor_ln, "size", 0.0))

    band = []
    for ln in lines:
        s = _text(ln).strip()
        if not s:
            continue
        if not _is_title_candidate_text(s):
            continue
        if abs(_safe_float(getattr(ln, "size", 0.0)) - base_sz) > 2.4:
            continue
        if abs(_safe_float(getattr(ln, "y0", 0.0)) - base_y) > y_slack:
            continue
        if abs(_safe_float(getattr(ln, "x0", 0.0)) - base_x) > x_slack:
            continue
        band.append(ln)

    band.sort(key=lambda z: (_safe_float(getattr(z, "y0", 0.0)), _safe_float(getattr(z, "x0", 0.0))))
    parts = [_text(ln).strip() for ln in band if _text(ln).strip()]
    return _norm_space(" ".join(parts))


def _find_form_title(lines, has_fields: bool, is_approval: bool) -> Optional[str]:
    # Only consider updating form_name on pages that structurally have fields.
    if not has_fields and not is_approval:
        return None

    w, h = _page_wh(lines)
    base_sz = _median_font_size(lines)

    # Approval: large bold centered-ish title near top.
    if is_approval:
        top = [ln for ln in lines if _text(ln).strip() and _safe_float(getattr(ln, "y0", 0.0)) < 0.28 * h]
        if not top:
            return None

        def score(ln) -> float:
            t = _text(ln).strip()
            if not _is_title_candidate_text(t):
                return -1e9
            s = _safe_float(getattr(ln, "size", 0.0))
            if bool(getattr(ln, "bold", False)):
                s += 3.0
            x = _safe_float(getattr(ln, "x0", 0.0))
            if x < 0.12 * w:
                s -= 6.0
            if ":" in t:
                s -= 2.5
            # prefer more centered titles
            s -= 0.0012 * abs(x - 0.46 * w)
            return s

        best = max(top, key=score)
        if score(best) < max(16.0, base_sz + 6.0):
            return None

        title = _join_title_band(top, best, y_slack=24.0, x_slack=0.26 * w)
        title = _strip_machine_code_suffix(title)
        if not title or not _is_title_candidate_text(title):
            return None
        if _count_letters(title) < 4:
            return None
        if len(title) > 120:
            return None
        return title

    # Non-approval pages: section headers often live upper left and are non-black/bold.
    cand = []
    for ln in lines:
        s = _text(ln).strip()
        if not s:
            continue
        if not _is_title_candidate_text(s):
            continue

        y0 = _safe_float(getattr(ln, "y0", 0.0))
        x0 = _safe_float(getattr(ln, "x0", 0.0))
        sz = _safe_float(getattr(ln, "size", 0.0))
        bold = bool(getattr(ln, "bold", False))
        non_black = bool(getattr(ln, "non_black", False))

        if y0 < 0.03 * h or y0 > 0.55 * h:
            continue

        # Prefer visible section headers.
        if non_black and sz >= base_sz + 0.5 and _count_letters(s) >= 3:
            cand.append(ln)
            continue
        if bold and sz >= base_sz + 1.2 and _count_letters(s) >= 3:
            cand.append(ln)
            continue
        if sz >= base_sz + 2.5 and _count_letters(s) >= 4:
            cand.append(ln)
            continue

    if not cand:
        return None

    left_xmax = _page_left_xmax(lines)

    def score2(ln) -> float:
        t = _text(ln).strip()
        if not _is_title_candidate_text(t):
            return -1e9
        sz = _safe_float(getattr(ln, "size", 0.0))
        s = sz
        if bool(getattr(ln, "bold", False)):
            s += 1.8
        if bool(getattr(ln, "non_black", False)):
            s += 1.2
        y0 = _safe_float(getattr(ln, "y0", 0.0))
        x0 = _safe_float(getattr(ln, "x0", 0.0))
        # higher on page is better
        s -= 0.010 * y0
        # too far right is unlikely to be the form/section title
        if x0 > left_xmax + 0.25 * w:
            s -= 3.0
        # colon lines are usually field labels
        if ":" in t:
            s -= 1.8
        if len(t) > 90:
            s -= 1.5
        return s

    best = max(cand, key=score2)
    if score2(best) < base_sz + 1.0:
        return None

    title = _join_title_band(lines, best, y_slack=26.0, x_slack=0.28 * w)
    title = _strip_machine_code_suffix(title)
    if not title or not _is_title_candidate_text(title):
        return None
    if _count_letters(title) < 4:
        return None
    if len(title) > 120:
        return None
    return title


def _is_option_line_text(text: str) -> bool:
    # A line that encodes a selectable option (should not become a field itself).
    t = text.strip()
    if not t:
        return False
    if _RX_WIDGET_RADIO.match(t):
        return True
    # checkbox-like at start with trailing word(s)
    if t.startswith("[") and "]" in t[:8]:
        after = t.split("]", 1)[1].strip()
        if after and _count_letters(after) >= 2:
            return True
    if t.startswith("(") and ")" in t[:8]:
        after = t.split(")", 1)[1].strip()
        if after and _count_letters(after) >= 2:
            return True
    return False


def _clean_field_label(text: str) -> Optional[str]:
    t = _norm_space(text.strip())
    if not t:
        return None
    t = _strip_machine_code_suffix(t)
    # strip leading widget glyphs and option markers if they slipped in
    t2 = re.sub(r"^\s*([Oo]|\(\s*\)|\[\s*\]|\[\s*[_\.\- ]+\s*\])\s+", "", t)
    t2 = _norm_space(t2)
    # strip trailing colon (common label formatting)
    if t2.endswith(":"):
        t2 = _norm_space(t2[:-1])
    if not t2:
        return None
    if _is_protocol_number(t2) or _is_junk_headerish(t2):
        return None
    if _looks_like_code_bracket(t2):
        return None
    if _count_letters(t2) < 2:
        return None
    if len(t2) > 180:
        return None
    # avoid pure punctuation
    if all(not ch.isalnum() for ch in t2):
        return None
    return t2


def _cluster_by_proximity(items, y_gap: float, x_gap: float) -> List[List]:
    if not items:
        return []
    items = sorted(items, key=lambda z: (_safe_float(getattr(z, "y0", 0.0)), _safe_float(getattr(z, "x0", 0.0))))
    groups: List[List] = []
    cur = [items[0]]
    for it in items[1:]:
        py = _safe_float(getattr(cur[-1], "y0", 0.0))
        px = _safe_float(getattr(cur[-1], "x0", 0.0))
        y = _safe_float(getattr(it, "y0", 0.0))
        x = _safe_float(getattr(it, "x0", 0.0))
        if abs(y - py) <= y_gap and abs(x - px) <= x_gap:
            cur.append(it)
        else:
            groups.append(cur)
            cur = [it]
    groups.append(cur)
    return groups


def _best_label_above(lines, anchor, max_up: float, x_center: float, x_span: float) -> Optional[str]:
    ay0 = _safe_float(getattr(anchor, "y0", 0.0))
    best_ln = None
    best_score = -1e9
    for ln in lines:
        s = _text(ln).strip()
        if not s:
            continue
        if _looks_like_widget(s):
            continue
        if _is_junk_headerish(s) or _is_protocol_number(s):
            continue
        y0 = _safe_float(getattr(ln, "y0", 0.0))
        if y0 >= ay0:
            continue
        dy = ay0 - y0
        if dy > max_up:
            continue
        x0 = _safe_float(getattr(ln, "x0", 0.0))
        x1 = _safe_float(getattr(ln, "x1", x0))
        cx = 0.5 * (x0 + x1)
        if abs(cx - x_center) > x_span:
            continue
        # score: closer is better, more letters is better, avoid option-like
        sc = 0.0
        sc -= 0.050 * dy
        sc += 0.030 * min(40, _count_letters(s))
        if ":" in s:
            sc += 0.3
        if _is_option_line_text(s):
            sc -= 2.0
        if bool(getattr(ln, "bold", False)):
            sc += 0.7
        if bool(getattr(ln, "non_black", False)):
            sc += 0.5
        if sc > best_score:
            best_score = sc
            best_ln = ln
    if not best_ln:
        return None
    return _clean_field_label(_text(best_ln))


def _best_label_left(lines, anchor, left_xmax: float, y_slack: float, x_slack: float) -> Optional[str]:
    ax0 = _safe_float(getattr(anchor, "x0", 0.0))
    ay0 = _safe_float(getattr(anchor, "y0", 0.0))
    candidates = []
    for ln in lines:
        s = _text(ln).strip()
        if not s:
            continue
        if _looks_like_widget(s):
            continue
        if _is_junk_headerish(s) or _is_protocol_number(s):
            continue
        x0 = _safe_float(getattr(ln, "x0", 0.0))
        x1 = _safe_float(getattr(ln, "x1", x0))
        y0 = _safe_float(getattr(ln, "y0", 0.0))
        # label should be left of the widget-ish anchor
        if x0 > min(ax0 + x_slack, left_xmax + 0.12 * abs(left_xmax)):
            continue
        if x1 > ax0 + 0.02 * max(1.0, ax0):
            # if it spills into the widget region, it's likely not a clean label
            continue
        if abs(y0 - ay0) > y_slack:
            continue
        # avoid capturing section titles
        if bool(getattr(ln, "bold", False)) and _safe_float(getattr(ln, "size", 0.0)) >= _safe_float(getattr(anchor, "size", 10.0)) + 4.0:
            continue
        candidates.append(ln)

    if not candidates:
        return None
    candidates.sort(key=lambda z: (_safe_float(getattr(z, "y0", 0.0)), _safe_float(getattr(z, "x0", 0.0))))

    # Join multiple label fragments on the same band (wrapped lines or split chunks).
    parts = []
    for ln in candidates:
        s = _text(ln).strip()
        if not s:
            continue
        parts.append(s)
    joined = _norm_space(" ".join(parts))
    return _clean_field_label(joined)


def _section_headers(lines) -> List:
    w, h = _page_wh(lines)
    base_sz = _median_font_size(lines)
    hs = []
    for ln in lines:
        s = _text(ln).strip()
        if not s:
            continue
        if not _is_title_candidate_text(s):
            continue
        y0 = _safe_float(getattr(ln, "y0", 0.0))
        if y0 < 0.04 * h or y0 > 0.92 * h:
            continue
        sz = _safe_float(getattr(ln, "size", 0.0))
        bold = bool(getattr(ln, "bold", False))
        non_black = bool(getattr(ln, "non_black", False))
        if non_black and sz >= base_sz + 0.2 and _count_letters(s) >= 3:
            hs.append(ln)
        elif bold and sz >= base_sz + 0.9 and _count_letters(s) >= 3:
            hs.append(ln)
        elif sz >= base_sz + 2.2 and _count_letters(s) >= 4:
            hs.append(ln)

    hs.sort(key=lambda z: (_safe_float(getattr(z, "y0", 0.0)), _safe_float(getattr(z, "x0", 0.0))))
    return hs


def _nearest_header_above(headers, y0: float, x0: float, x1: float, max_up: float) -> Optional[str]:
    # Choose nearest header above, roughly overlapping horizontally.
    best = None
    best_dy = 1e9
    for h in headers:
        hy = _safe_float(getattr(h, "y0", 0.0))
        if hy >= y0:
            continue
        dy = y0 - hy
        if dy > max_up:
            continue
        hx0 = _safe_float(getattr(h, "x0", 0.0))
        hx1 = _safe_float(getattr(h, "x1", hx0))
        # overlap / proximity in x
        overlap = min(x1, hx1) - max(x0, hx0)
        if overlap < -25:  # allow mild miss
            continue
        if dy < best_dy:
            best_dy = dy
            best = h
    if not best:
        return None
    return _clean_field_label(_text(best))


def _extract_radio_option_groups(lines, base_sz: float) -> List[Tuple[float, float, float, float, object]]:
    # Return bounding boxes of option groups + representative anchor (first option line).
    option_lines = [ln for ln in lines if _is_option_line_text(_text(ln))]
    if not option_lines:
        return []

    w, h = _page_wh(lines)
    y_gap = max(1.8 * base_sz, 0.012 * h)
    x_gap = 0.08 * w
    groups = _cluster_by_proximity(option_lines, y_gap=y_gap, x_gap=x_gap)

    out = []
    for g in groups:
        ys = [_safe_float(getattr(ln, "y0", 0.0)) for ln in g]
        xs0 = [_safe_float(getattr(ln, "x0", 0.0)) for ln in g]
        xs1 = [_safe_float(getattr(ln, "x1", _safe_float(getattr(ln, "x0", 0.0)))) for ln in g]
        y0 = min(ys) if ys else 0.0
        y1 = max(ys) if ys else y0
        x0 = min(xs0) if xs0 else 0.0
        x1 = max(xs1) if xs1 else x0
        g_sorted = sorted(g, key=lambda z: (_safe_float(getattr(z, "y0", 0.0)), _safe_float(getattr(z, "x0", 0.0))))
        out.append((x0, y0, x1, y1, g_sorted[0]))
    out.sort(key=lambda z: (z[1], z[0]))
    return out


def _is_footer_or_header_furniture(ln, w: float, h: float) -> bool:
    s = _text(ln).strip()
    if not s:
        return True
    y0 = _safe_float(getattr(ln, "y0", 0.0))
    x0 = _safe_float(getattr(ln, "x0", 0.0))
    if y0 < 0.03 * h or y0 > 0.965 * h:
        # tiny bands at top/bottom are often repeating furniture, but never whole-page skip
        if _is_junk_headerish(s) or _is_protocol_number(s):
            return True
        if len(s) <= 12 and (s.isdigit() or s.lower().startswith("page")):
            return True
    # far right narrow column with machine-ish bits is often technical
    if x0 > 0.82 * w and (_is_protocol_number(s) or _looks_like_code_bracket(s)):
        return True
    return False


def extract(pages) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    current_form_name: Optional[str] = None

    for page in pages or []:
        lines = list(getattr(page, "lines", None) or getattr(page, "spans", None) or getattr(page, "blocks", None) or [])
        # Also support page itself being an iterable of lines.
        if not lines and isinstance(page, Iterable):
            try:
                lines = list(page)
            except Exception:
                lines = []

        w, h = _page_wh(lines)
        base_sz = _median_font_size(lines)

        # Keep only meaningful lines for layout decisions (do not hard skip whole page).
        usable_lines = []
        for ln in lines:
            s = _text(ln).strip()
            if not s:
                continue
            if _is_footer_or_header_furniture(ln, w, h):
                continue
            usable_lines.append(ln)

        widgets = _collect_widgets(usable_lines)
        has_fields = bool(widgets)
        is_approval = _looks_like_approval_page(usable_lines)

        page_title = _find_form_title(usable_lines, has_fields=has_fields, is_approval=is_approval)
        if page_title:
            current_form_name = page_title

        # Precompute section headers; they can act as "form_name" within a page.
        headers = _section_headers(usable_lines)

        left_xmax = _page_left_xmax(usable_lines)
        y_slack = max(2.2 * base_sz, 0.014 * h)
        x_slack = max(1.8 * base_sz, 0.010 * w)

        seen = set()

        # 1) Handle option groups (radio/checkbox lists) -> one field per question.
        option_groups = _extract_radio_option_groups(usable_lines, base_sz=base_sz)
        for (gx0, gy0, gx1, gy1, anchor) in option_groups:
            x_center = 0.5 * (gx0 + gx1)
            label = _best_label_above(
                usable_lines,
                anchor=anchor,
                max_up=max(7.0 * base_sz, 0.10 * h),
                x_center=x_center,
                x_span=max(0.30 * w, 10.0 * base_sz),
            )
            if not label:
                # sometimes the question is to the left but above the group start
                label = _best_label_left(
                    usable_lines,
                    anchor=anchor,
                    left_xmax=left_xmax,
                    y_slack=max(4.0 * base_sz, 0.035 * h),
                    x_slack=max(6.0 * base_sz, 0.03 * w),
                )
            if not label:
                continue

            # Determine section/form name for this field.
            sec = _nearest_header_above(headers, y0=gy0, x0=gx0, x1=gx1, max_up=max(0.22 * h, 18.0 * base_sz))
            form_name = sec or current_form_name or ""
            key = (form_name, label)
            if key in seen:
                continue
            seen.add(key)
            records.append({"form_name": form_name, "field_name": label})

        # 2) Standalone widgets (underline lines, blank brackets, etc.) -> label left/above.
        # Skip widget lines that are option lines (handled above) to avoid emitting answer options.
        for wd in widgets:
            wtxt = _text(wd).strip()
            if not wtxt:
                continue
            if _is_option_line_text(wtxt):
                continue

            wx0 = _safe_float(getattr(wd, "x0", 0.0))
            wy0 = _safe_float(getattr(wd, "y0", 0.0))
            wx1 = _safe_float(getattr(wd, "x1", wx0))

            label = _best_label_left(usable_lines, anchor=wd, left_xmax=left_xmax, y_slack=y_slack, x_slack=x_slack)

            if not label:
                x_center = 0.5 * (wx0 + wx1)
                label = _best_label_above(
                    usable_lines,
                    anchor=wd,
                    max_up=max(6.0 * base_sz, 0.08 * h),
                    x_center=x_center,
                    x_span=max(0.22 * w, 8.0 * base_sz),
                )

            # If still none, try a nearby label that ends with ":" on the same row (common layout).
            if not label:
                best = None
                best_dx = 1e9
                for ln in usable_lines:
                    s = _text(ln).strip()
                    if not s or _looks_like_widget(s):
                        continue
                    if _is_junk_headerish(s) or _is_protocol_number(s):
                        continue
                    if not s.endswith(":"):
                        continue
                    y0 = _safe_float(getattr(ln, "y0", 0.0))
                    if abs(y0 - wy0) > max(2.8 * base_sz, 0.02 * h):
                        continue
                    x1 = _safe_float(getattr(ln, "x1", _safe_float(getattr(ln, "x0", 0.0))))
                    dx = abs(wx0 - x1)
                    if dx < best_dx:
                        best_dx = dx
                        best = ln
                if best is not None:
                    label = _clean_field_label(_text(best))

            if not label:
                continue

            # Determine section/form name for this field.
            sec = _nearest_header_above(headers, y0=wy0, x0=wx0, x1=wx1, max_up=max(0.22 * h, 18.0 * base_sz))
            form_name = sec or current_form_name or ""
            key = (form_name, label)
            if key in seen:
                continue
            seen.add(key)
            records.append({"form_name": form_name, "field_name": label})

        # 3) Some layouts have explicit "Label:" without a visible widget (value entered in a right column).
        # To avoid capturing filled values, only emit when there is strong structural evidence: a large blank gap to the right
        # and no alnum-dense trailing content (which would likely be a filled value).
        for ln in usable_lines:
            s = _text(ln).strip()
            if not s:
                continue
            if not s.endswith(":"):
                continue
            if _is_junk_headerish(s) or _is_protocol_number(s):
                continue
            if _looks_like_widget(s):
                continue

            x0 = _safe_float(getattr(ln, "x0", 0.0))
            x1 = _safe_float(getattr(ln, "x1", x0))
            y0 = _safe_float(getattr(ln, "y0", 0.0))
            # Require label-ish position (left side) and that it's not a section header.
            if x0 > left_xmax + 0.10 * w:
                continue
            if bool(getattr(ln, "bold", False)) and _safe_float(getattr(ln, "size", 0.0)) >= base_sz + 2.5:
                continue

            # Look for evidence of an entry area to the right on same row: a widget or large whitespace until page edge.
            has_right_widget = False
            for wd in widgets:
                wy0 = _safe_float(getattr(wd, "y0", 0.0))
                if abs(wy0 - y0) > max(2.4 * base_sz, 0.02 * h):
                    continue
                wx0 = _safe_float(getattr(wd, "x0", 0.0))
                if wx0 > x1 + max(1.8 * base_sz, 0.03 * w):
                    has_right_widget = True
                    break

            # Large gap heuristic (structural, not text blocklist): no other text immediately right.
            right_text_near = False
            for ln2 in usable_lines:
                if ln2 is ln:
                    continue
                y2 = _safe_float(getattr(ln2, "y0", 0.0))
                if abs(y2 - y0) > max(2.2 * base_sz, 0.02 * h):
                    continue
                x02 = _safe_float(getattr(ln2, "x0", 0.0))
                if x02 > x1 + max(2.2 * base_sz, 0.04 * w) and x02 < x1 + 0.25 * w:
                    # some text close to the right likely indicates filled value; avoid emitting
                    if _count_alnum(_text(ln2)) >= 3:
                        right_text_near = True
                        break

            if not has_right_widget and right_text_near:
                continue

            label = _clean_field_label(s)
            if not label:
                continue

            sec = _nearest_header_above(headers, y0=y0, x0=x0, x1=x1, max_up=max(0.22 * h, 18.0 * base_sz))
            form_name = sec or current_form_name or ""
            key = (form_name, label)
            if key in seen:
                continue
            seen.add(key)
            records.append({"form_name": form_name, "field_name": label})

    # Final cleanup: ensure human-readable, no empties.
    cleaned: List[Dict[str, str]] = []
    for r in records:
        fn = _norm_space((r.get("form_name") or "").strip())
        fld = _norm_space((r.get("field_name") or "").strip())
        fld = _strip_machine_code_suffix(fld)
        fn = _strip_machine_code_suffix(fn)
        if not fld or _count_letters(fld) < 2:
            continue
        if _looks_like_widget(fld) or _looks_like_code_bracket(fld):
            continue
        cleaned.append({"form_name": fn, "field_name": fld})
    return cleaned
```
