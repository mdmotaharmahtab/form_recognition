import re
import statistics
from typing import List, Tuple, Dict, Optional


_RX_PROTOCOL = re.compile(r"^\d{2,6}-\d{2,6}-\d{4,8}$")
_RX_URL = re.compile(r"(?i)\bhttps?://\S+\b")

# Widgets: radio options, bracketed fill boxes, underscore fill lines
_RX_WIDGET_RADIO = re.compile(r"^\s*[Oo]\s+\S")
_RX_WIDGET_BOX = re.compile(r"[\[_][\s\|\._-]*[_\|]{2,}[\s\|\._-]*[\]_]")
_RX_UNDERSCORE_LINE = re.compile(r"^_{10,}$")

# Machine-ish codes embedded in otherwise human labels, e.g. "Severity [AESEV]"
_RX_TRAILING_BRACKET_CODE = re.compile(r"\s*\[[A-Za-z0-9_]{2,}\]\s*$")


def _norm_space(s: str) -> str:
    return " ".join(s.split())


def _count_letters(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


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
    if t.count("_") >= 10 and (len(t) >= 12):
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
    return t


def _page_left_xmax(lines) -> float:
    # Identify the left label column boundary from the leftmost text cluster.
    xs = []
    for ln in lines:
        if not getattr(ln, "text", ""):
            continue
        t = ln.text.strip()
        if not t:
            continue
        if _is_junk_headerish(t) or _is_protocol_number(t):
            continue
        # exclude far-right technical column and footer-ish lines
        if ln.y0 > 790:
            continue
        xs.append(float(ln.x0))

    if not xs:
        return 170.0

    xs.sort()
    n = len(xs)
    q20 = xs[max(0, min(n - 1, int(n * 0.20)))]
    mn = xs[0]

    # Slack to tolerate small shifts; cap to avoid bleeding into widget/options column.
    return min(240.0, max(125.0, mn + 140.0, q20 + 115.0))


def _collect_widgets(lines):
    widgets = []
    for ln in lines:
        if not getattr(ln, "text", ""):
            continue
        t = ln.text.strip()
        if not t:
            continue
        if _looks_like_widget(t):
            widgets.append(ln)
    widgets.sort(key=lambda z: (z.y0, z.x0))
    return widgets


def _looks_like_approval_page(lines) -> bool:
    # Large bold title near top is a strong structural signature.
    for ln in lines:
        if not getattr(ln, "text", ""):
            continue
        t = ln.text.strip()
        if not t or _is_protocol_number(t) or _is_junk_headerish(t):
            continue
        if ln.y0 < 250 and ln.bold and float(ln.size) >= 18 and ln.x0 < 520 and _count_letters(t) >= 4:
            return True
    return False


def _join_title_band(lines, anchor_ln, y_slack: float = 20.0, x_slack: float = 70.0) -> str:
    base_x = float(anchor_ln.x0)
    base_y = float(anchor_ln.y0)
    base_sz = float(anchor_ln.size)

    band = []
    for ln in lines:
        if not getattr(ln, "text", ""):
            continue
        t = ln.text.strip()
        if not t or _is_protocol_number(t) or _is_junk_headerish(t):
            continue
        if abs(float(ln.size) - base_sz) > 2.2:
            continue
        if abs(float(ln.y0) - base_y) > y_slack:
            continue
        if abs(float(ln.x0) - base_x) > x_slack:
            continue
        band.append(ln)

    band.sort(key=lambda z: (z.y0, z.x0))
    parts = [ln.text.strip() for ln in band if ln.text and ln.text.strip()]
    return _norm_space(" ".join(parts))


def _find_form_title(lines, widgets_present: bool, is_approval: bool) -> Optional[str]:
    # Important: only consider updating form_name on pages that structurally have fields.
    if not widgets_present and not is_approval:
        return None

    # Approval: large bold centered-ish title near top.
    if is_approval:
        top = [ln for ln in lines if getattr(ln, "text", "") and ln.y0 < 200]
        if not top:
            return None

        def score(ln) -> float:
            t = ln.text.strip()
            if not t or _is_protocol_number(t) or _is_junk_headerish(t):
                return -1e9
            s = float(ln.size)
            if ln.bold:
                s += 3.0
            # prefer more centered titles; avoid far-left label column
            x = float(ln.x0)
            if x < 90:
                s -= 6.0
            # devalue lines that look like per-field labels (colon-heavy)
            if ":" in t:
                s -= 2.5
            if _looks_like_code_bracket(t):
                s -= 6.0
            return s

        best = max(top, key=score)
        if score(best) < 16.0:
            return None

        title = _join_title_band(top, best, y_slack=22.0, x_slack=120.0)
        title = _strip_machine_code_suffix(title)
        if not title or _is_protocol_number(title) or _is_junk_headerish(title):
            return None
        # titles should be mostly words, not single-field phrases
        if _count_letters(title) < 4:
            return None
        return title

    # Annotated-like pages: colored/section headers often live mid-upper left and are non-black.
    cand = []
    for ln in lines:
        if not getattr(ln, "text", ""):
            continue
        t = ln.text.strip()
        if not t or _is_protocol_number(t) or _is_junk_headerish(t):
            continue
        if ln.y0 < 40 or ln.y0 > 360:
            continue
        if ln.x0 > 320:
            continue
        if _looks_like_code_bracket(t):
            continue
        # Prefer visible section headers: non-black and larger than label body.
        if ln.non_black and float(ln.size) >= 9.5 and _count_letters(t) >= 3:
            cand.append(ln)
        # Fallback: some forms use black bold headings.
        elif ln.bold and float(ln.size) >= 12.0 and ln.x0 > 90 and _count_letters(t) >= 4:
            cand.append(ln)

    if not cand:
        return None

    def score2(ln) -> float:
        t = ln.text.strip()
        s = float(ln.size)
        if ln.bold:
            s += 1.5
        if ln.non_black:
            s += 2.0
        # avoid header rows with ":" that are likely per-field (or technical) snippets
        if ":" in t:
            s -= 1.5
        # prefer higher on page, but not the protocol line zone
        s -= 0.004 * float(ln.y0)
        return s

    best = max(cand, key=score2)
    title = _join_title_band(lines, best, y_slack=16.0, x_slack=180.0)
    title = _strip_machine_code_suffix(title)
    if not title or _is_protocol_number(title) or _is_junk_headerish(title):
        return None
    if _count_letters(title) < 3:
        return None
    return title


def _extract_approval_fields(lines, form_name: str, page_1based: int) -> List[Dict[str, object]]:
    out = []
    seen = set()

    def add(label: str):
        lbl = _strip_machine_code_suffix(_norm_space(label))
        if not lbl or _count_letters(lbl) < 2 or _is_protocol_number(lbl) or _is_junk_headerish(lbl):
            return
        key = (form_name, lbl)
        if key in seen:
            return
        seen.add(key)
        out.append({"form_name": form_name, "field_name": lbl, "page": page_1based})

    # Bold left labels (e.g., Sponsor Name, Protocol Number, etc.)
    for ln in lines:
        t = getattr(ln, "text", "")
        if not t:
            continue
        txt = t.strip()
        if not txt:
            continue
        if ln.y0 < 95 or ln.y0 > 760:
            continue
        if ln.x0 > 220:
            continue
        if ln.bold and float(ln.size) >= 12.2 and _count_letters(txt) >= 2 and not _is_protocol_number(txt):
            # Avoid accidentally promoting a full sentence-like string into a "label"
            add(txt.rstrip(":").strip())

    # Signature/approval underscore widgets: take nearest descriptive lines around them (below OR above).
    underscore_widgets = []
    for ln in lines:
        t = getattr(ln, "text", "")
        if not t:
            continue
        s = t.strip()
        if not s:
            continue
        if _looks_like_widget(s) and s.count("_") >= 16:
            underscore_widgets.append(ln)

    underscore_widgets.sort(key=lambda z: (z.y0, z.x0))

    for ul in underscore_widgets:
        # collect nearby non-widget text lines in a vertical window around the line,
        # near the same x-region (covers both "label under line" and "name/role above line").
        near = []
        for ln in lines:
            t = getattr(ln, "text", "")
            if not t:
                continue
            s = t.strip()
            if not s:
                continue
            if _looks_like_widget(s):
                continue
            if _is_protocol_number(s) or _is_junk_headerish(s):
                continue
            if ln.y0 < 80 or ln.y0 > 780:
                continue

            dy = float(ln.y0) - float(ul.y0)
            if dy < -28 or dy > 48:
                continue

            # allow some horizontal slack; approval blocks often align on same left edge
            if abs(float(ln.x0) - float(ul.x0)) <= 40 or (float(ln.x0) >= float(ul.x0) - 10 and float(ln.x0) <= float(ul.x0) + 260):
                # devalue tiny footnotes
                if float(ln.size) < 7.0:
                    continue
                near.append((abs(dy), float(ln.y0), float(ln.x0), s))

        near.sort()
        if not near:
            continue

        # join up to two closest lines (often split across wrapped role text)
        parts = []
        for _, _, _, s in near[:2]:
            parts.append(s)
        label = _norm_space(" ".join(parts))
        # don't accidentally add generic filler text; require letters
        if _count_letters(label) >= 2:
            add(label)

    return out


def _group_wrapped_label_lines(label_lines, widget_lines, join_y_mult: float = 1.65):
    groups = []
    if not label_lines:
        return groups

    wy = sorted(float(w.y0) for w in widget_lines)

    def widget_between(y0: float, y1: float) -> bool:
        for y in wy:
            if y <= y0:
                continue
            if y >= y1:
                break
            return True
        return False

    cur = [label_lines[0]]
    for ln in label_lines[1:]:
        prev = cur[-1]
        ygap = float(ln.y0) - float(prev.y0)
        same_x = abs(float(ln.x0) - float(prev.x0)) <= 16
        size_ok = abs(float(ln.size) - float(prev.size)) <= 1.3
        join_gap = join_y_mult * max(6.0, float(prev.size))

        if same_x and size_ok and 0 < ygap <= join_gap and not widget_between(float(prev.y0) + 0.1, float(ln.y0) - 0.1):
            cur.append(ln)
        else:
            groups.append(cur)
            cur = [ln]
    groups.append(cur)
    return groups


def _join_group_text(group) -> str:
    parts = [ln.text.strip() for ln in group if getattr(ln, "text", "") and ln.text.strip()]
    if not parts:
        return ""
    out = parts[0]
    for nxt in parts[1:]:
        if out.endswith("-") and nxt and not nxt.startswith(" "):
            out = out[:-1] + nxt
        else:
            out = out + " " + nxt
    return _norm_space(out)


def _extract_annotated_like_fields(lines, form_name: str, page_1based: int) -> List[Dict[str, object]]:
    widgets = _collect_widgets(lines)
    if not widgets:
        return []

    left_xmax = _page_left_xmax(lines)

    # Candidate left labels: left column, black, mid-size, not bracket-only codes.
    left_lines = []
    for ln in lines:
        if not getattr(ln, "text", ""):
            continue
        t = ln.text.strip()
        if not t:
            continue
        if float(ln.x0) > left_xmax:
            continue
        if ln.non_black:
            continue
        if ln.y0 < 45 or ln.y0 > 770:
            continue
        if _looks_like_code_bracket(t):
            continue
        if _is_protocol_number(t) or _is_junk_headerish(t):
            continue
        # exclude pure widget-ish underscore lines from label side
        if _looks_like_widget(t) and t.count("_") >= 10:
            continue
        # avoid tiny technical annotation text
        if float(ln.size) < 6.2 or float(ln.size) > 10.0:
            continue
        left_lines.append(ln)

    if not left_lines:
        return []

    sizes = [float(ln.size) for ln in left_lines]
    try:
        med = statistics.median(sizes)
    except Exception:
        med = 7.5

    # Tighten around typical label size while allowing some drift (e.g., date/time rows).
    label_lines = [ln for ln in left_lines if abs(float(ln.size) - med) <= 1.6]
    if not label_lines:
        label_lines = left_lines

    label_lines.sort(key=lambda z: (z.y0, z.x0))
    widgets.sort(key=lambda z: (z.y0, z.x0))

    groups = _group_wrapped_label_lines(label_lines, widgets)

    out = []
    seen = set()

    for g in groups:
        gy0 = float(g[0].y0)
        gy_last = float(g[-1].y0)
        gx_max = max(float(ln.x0) + 1.0 for ln in g)

        txt = _join_group_text(g)
        if not txt or _count_letters(txt) < 2:
            continue

        txt = _strip_machine_code_suffix(txt)
        if not txt or _count_letters(txt) < 2:
            continue

        # Must have a widget to the right of the label group (relative geometry, not absolute).
        has_near_widget = False
        for w in widgets:
            wx = float(w.x0)
            if wx < gx_max + 25.0:
                continue
            wy = float(w.y0)
            if wy < gy0 - 8:
                continue
            if wy > gy_last + 85:
                # widgets are sorted by y; if far below, stop
                if wy - gy0 > 120:
                    break
                continue
            has_near_widget = True
            break

        if not has_near_widget:
            continue

        key = (form_name, txt)
        if key in seen:
            continue
        seen.add(key)
        out.append({"form_name": form_name, "field_name": txt, "page": page_1based})

    return out


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    current_form = ""

    for page_idx0, lines in pages:
        page_1based = page_idx0 + 1

        is_approval = _looks_like_approval_page(lines)
        widgets = _collect_widgets(lines)
        widgets_present = bool(widgets) or is_approval  # approval pages may have signature underscore widgets

        # Only update the current form on pages that structurally have fields.
        title = _find_form_title(lines, widgets_present=widgets_present, is_approval=is_approval)
        if title:
            current_form = title

        form_name = current_form or ""

        if is_approval:
            records.extend(_extract_approval_fields(lines, form_name, page_1based))
            continue

        # For all other layouts, only attempt field extraction when widgets are present.
        if widgets_present:
            records.extend(_extract_annotated_like_fields(lines, form_name, page_1based))

    return records
