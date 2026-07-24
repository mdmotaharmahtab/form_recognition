```python
import re
import statistics
from typing import List, Tuple, Dict, Optional


_RX_PROTOCOL = re.compile(r"^\d{2,6}-\d{2,6}-\d{4,8}$")
_RX_URL = re.compile(r"(?i)\bhttps?://\S+\b")

# Widgets: radio options, bracketed fill boxes, underscore fill lines
_RX_WIDGET_RADIO = re.compile(r"^\s*[Oo]\s+\S")
_RX_WIDGET_BOX = re.compile(r"[\[_][\s\|\._/-]*[_\|]{2,}[\s\|\._/-]*[\]_]")
_RX_WIDGET_EMPTY_BRACKET = re.compile(r"\[\s{3,}\]")
_RX_WIDGET_EMPTY_BRACKET2 = re.compile(r"\[\s*[\.\-]{2,}\s*\]")
_RX_WIDGET_EMPTY_BRACKET3 = re.compile(r"\[\s*[_\-\.\s]{0,2}\s*\]")  # minimal box; guarded by other checks
_RX_UNDERSCORE_LINE = re.compile(r"^_{10,}$")

# Machine-ish codes embedded in otherwise human labels, e.g. "Severity [AESEV]"
_RX_TRAILING_BRACKET_CODE = re.compile(r"\s*\[[A-Za-z0-9_]{2,}\]\s*$")


def _norm_space(s: str) -> str:
    return " ".join(s.split())


def _count_letters(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


def _count_alnum(text: str) -> int:
    return sum(1 for ch in text if ch.isalnum())


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
        # very small boxes exist; require at least some whitespace/marks width
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
    xs = []
    for ln in lines:
        t = getattr(ln, "text", "")
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
        if float(getattr(ln, "y0", 0.0)) > 790:
            continue
        # exclude far-right technical column; allow some drift
        if float(getattr(ln, "x0", 0.0)) > 410:
            continue
        xs.append(float(getattr(ln, "x0", 0.0)))

    if not xs:
        return 190.0

    xs.sort()
    n = len(xs)
    low = xs[: max(3, int(n * 0.25))]
    med_low = statistics.median(low) if low else xs[0]
    mn = xs[0]

    # typical: labels near mn/med_low; widgets/options start well right of that
    # keep slack, but allow layouts where label column is slightly indented/wider.
    left_xmax = max(150.0, min(330.0, med_low + 230.0, mn + 270.0))
    return left_xmax


def _collect_widgets(lines):
    widgets = []
    for ln in lines:
        t = getattr(ln, "text", "")
        if not t:
            continue
        s = t.strip()
        if not s:
            continue
        if _looks_like_widget(s):
            widgets.append(ln)
    widgets.sort(key=lambda z: (float(getattr(z, "y0", 0.0)), float(getattr(z, "x0", 0.0))))
    return widgets


def _looks_like_approval_page(lines) -> bool:
    # Large bold title near top is a strong structural signature.
    for ln in lines:
        t = getattr(ln, "text", "")
        if not t:
            continue
        s = t.strip()
        if not _is_title_candidate_text(s):
            continue
        if float(getattr(ln, "y0", 0.0)) < 250 and bool(getattr(ln, "bold", False)) and float(getattr(ln, "size", 0.0)) >= 18:
            if float(getattr(ln, "x0", 0.0)) < 520 and _count_letters(s) >= 4:
                return True
    return False


def _join_title_band(lines, anchor_ln, y_slack: float = 20.0, x_slack: float = 70.0) -> str:
    base_x = float(getattr(anchor_ln, "x0", 0.0))
    base_y = float(getattr(anchor_ln, "y0", 0.0))
    base_sz = float(getattr(anchor_ln, "size", 0.0))

    band = []
    for ln in lines:
        t = getattr(ln, "text", "")
        if not t:
            continue
        s = t.strip()
        if not _is_title_candidate_text(s):
            continue
        if abs(float(getattr(ln, "size", 0.0)) - base_sz) > 2.4:
            continue
        if abs(float(getattr(ln, "y0", 0.0)) - base_y) > y_slack:
            continue
        if abs(float(getattr(ln, "x0", 0.0)) - base_x) > x_slack:
            continue
        band.append(ln)

    band.sort(key=lambda z: (float(getattr(z, "y0", 0.0)), float(getattr(z, "x0", 0.0))))
    parts = [getattr(ln, "text", "").strip() for ln in band if getattr(ln, "text", "").strip()]
    return _norm_space(" ".join(parts))


def _find_form_title(lines, has_fields: bool, is_approval: bool) -> Optional[str]:
    # Only consider updating form_name on pages that structurally have fields.
    if not has_fields and not is_approval:
        return None

    # Approval: large bold centered-ish title near top.
    if is_approval:
        top = [ln for ln in lines if getattr(ln, "text", "") and float(getattr(ln, "y0", 0.0)) < 220]
        if not top:
            return None

        def score(ln) -> float:
            t = getattr(ln, "text", "").strip()
            if not _is_title_candidate_text(t):
                return -1e9
            s = float(getattr(ln, "size", 0.0))
            if bool(getattr(ln, "bold", False)):
                s += 3.0
            x = float(getattr(ln, "x0", 0.0))
            if x < 90:
                s -= 6.0
            if ":" in t:
                s -= 2.5
            # prefer more centered titles
            s -= 0.0012 * abs(x - 280.0)
            return s

        best = max(top, key=score)
        if score(best) < 16.0:
            return None

        title = _join_title_band(top, best, y_slack=24.0, x_slack=160.0)
        title = _strip_machine_code_suffix(title)
        if not title or not _is_title_candidate_text(title):
            return None
        if _count_letters(title) < 4:
            return None
        if len(title) > 120:
            return None
        return title

    # Annotated-like (and metadata) pages: colored/section headers often live upper left and are non-black.
    cand = []
    for ln in lines:
        t = getattr(ln, "text", "")
        if not t:
            continue
        s = t.strip()
        if not _is_title_candidate_text(s):
            continue

        y0 = float(getattr(ln, "y0", 0.0))
        x0 = float(getattr(ln, "x0", 0.0))
        sz = float(getattr(ln, "size", 0.0))
        bold = bool(getattr(ln, "bold", False))
        non_black = bool(getattr(ln, "non_black", False))

        if y0 < 30 or y0 > 360:
            continue

        # Prefer visible section headers: non-black and larger than label body.
        if non_black and sz >= 9.5 and _count_letters(s) >= 3:
            cand.append(ln)
            continue

        # Black bold headings (titles can be centered; allow wider x
