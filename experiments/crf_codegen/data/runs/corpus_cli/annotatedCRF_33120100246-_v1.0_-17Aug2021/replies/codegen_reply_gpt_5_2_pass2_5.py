```python
import re
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class L:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    bold: bool
    non_black: bool
    idx: int  # index in merged list

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0


@dataclass
class Span:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    bold: bool
    line_count: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0


_BRACKET_ANY_RE = re.compile(r"^\[.*\]$")
_MACHINE_CODE_RE = re.compile(r"^\[[A-Za-z0-9_\-]{2,}\]$")
_TYPE_MARK_RE = re.compile(r"\bTYPE\b", re.IGNORECASE)
_READONLY_MARK_RE = re.compile(r"READ[- ]?ONLY", re.IGNORECASE)

_ROW_PREFIX_RE = re.compile(r"^\s*Row\s*\d+\b\s*", re.IGNORECASE)
_ROW_MARK_ANY_RE = re.compile(r"\bRow\s*\d+\b", re.IGNORECASE)
_PURE_ROW_ANCHOR_RE = re.compile(r"^\s*Row\s*\d+\s*$", re.IGNORECASE)

_MOSTLY_NONLETTER_RE = re.compile(r"^[^A-Za-z]*$")
_BARE_ANCHOR_RE = re.compile(r"^\s*\d{1,2}\s*[\)\.:-]\s*$")


def _norm_ws(s: str) -> str:
    return " ".join((s or "").strip().split())


def _is_bracket(s: str) -> bool:
    s = (s or "").strip()
    return bool(_BRACKET_ANY_RE.match(s))


def _is_machine_code(s: str) -> bool:
    s = (s or "").strip()
    if ":" in s:
        return False
    return bool(_MACHINE_CODE_RE.match(s))


def _is_type_line(s: str) -> bool:
    s = (s or "").strip()
    if not _is_bracket(s):
        return False
    return bool(_TYPE_MARK_RE.search(s))


def _merge_bracket_fragments(lines) -> List[L]:
    merged: List[L] = []
    i = 0
    n = len(lines)
    while i < n:
        li = lines[i]
        t = (getattr(li, "text", "") or "").strip()
        if t.startswith("[") and "]" not in t:
            acc = t
            x0, y0, x1, y1 = (
                float(getattr(li, "x0", 0.0)),
                float(getattr(li, "y0", 0.0)),
                float(getattr(li, "x1", 0.0)),
                float(getattr(li, "y1", 0.0)),
            )
            size = float(getattr(li, "size", 0.0) or 0.0)
            bold = bool(getattr(li, "bold", False))
            non_black = bool(getattr(li, "non_black", False))
            j = i + 1
            while j < n and (j - i) <= 12:
                lj = lines[j]
                tj = (getattr(lj, "text", "") or "").strip()
                if float(getattr(lj, "y0", 0.0)) - y1 > 40:
                    break
                if tj == "":
                    j += 1
                    continue
                acc += tj
                x0 = min(x0, float(getattr(lj, "x0", 0.0)))
                y0 = min(y0, float(getattr(lj, "y0", 0.0)))
                x1 = max(x1, float(getattr(lj, "x1", 0.0)))
                y1 = max(y1, float(getattr(lj, "y1", 0.0)))
                size = max(size, float(getattr(lj, "size", 0.0) or 0.0))
                bold = bold or bool(getattr(lj, "bold", False))
                non_black = non_black or bool(getattr(lj, "non_black", False))
                if "]" in tj:
                    break
                j += 1

            merged.append(
                L(
                    text=_norm_ws(acc),
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    size=size,
                    bold=bold,
                    non_black=non_black,
                    idx=len(merged),
                )
            )
            i = j + 1
        else:
            merged.append(
                L(
                    text=_norm_ws(t),
                    x0=float(getattr(li, "x0", 0.0)),
                    y0=float(getattr(li, "y0", 0.0)),
                    x1=float(getattr(li, "x1", 0.0)),
                    y1=float(getattr(li, "y1", 0.0)),
                    size=float(getattr(li, "size", 0.0) or 0.0),
                    bold=bool(getattr(li, "bold", False)),
                    non_black=bool(getattr(li, "non_black", False)),
                    idx=len(merged),
                )
            )
            i += 1
    return merged


def _median(vals: List[float], default: float = 0.0) -> float:
    vals = [float(v) for v in vals if v is not None]
    if not vals:
        return default
    return float(statistics.median(vals))


def _estimate_page_width(lines: List[L]) -> float:
    xs = [l.x1 for l in lines if l and (l.x1 is not None)]
    if not xs:
        return 612.0
    w = float(max(xs))
    if w < 300:
        w = 612.0
    return w


def _page_title(body_lines: List[L], body_size: float) -> Optional[str]:
    cands = [
        l
        for l in body_lines
        if l.text
        and l.x0 < 190
        and l.y0 < 150
        and l.size >= max(12.0, (body_size * 1.30) if body_size else 12.0)
        and (l.bold or l.non_black)
    ]
    if not cands:
        cands = [
            l
            for l in body_lines
            if l.text
            and l.x0 < 190
            and l.y0 < 175
            and l.size >= max(12.0, (body_size * 1.30) if body_size else 12.0)
            and l.bold
        ]
    if not cands:
        return None

    cands.sort(key=lambda l: (-l.size, l.y0, l.x0))
    base = cands[0]
    parts = [base.text]
    for l in cands[1:]:
        if l.y0 > base.y1 + 3.2 * max(6.0, base.size):
            continue
        if abs(l.size - base.size) <= 1.25 and abs(l.x0 - base.x0) <= 60:
            if l.y0 - base.y1 <= 2.8 * max(6.0, base.size):
                parts.append(l.text)

    title = _norm_ws(" ".join(parts))
    if not title:
        return None
    title = _ROW_PREFIX_RE.sub("", title).strip()
    if not title:
        return None
    return title


def _x_close(a: L, b: L, page_w: float) -> bool:
    slack = max(60.0, 0.09 * page_w)
    if abs(a.x0 - b.x0) <= slack:
        return True
    if abs(a.x1 - b.x1) <= slack:
        return True
    if not (a.x1 + 10 < b.x0 or b.x1 + 10 < a.x0):
        return True
    return False


def _is_read_only(code_line: L, merged_lines: List[L], page_w: float) -> bool:
    for j in range(code_line.idx + 1, min(len(merged_lines), code_line.idx + 34)):
        lj = merged_lines[j]
        if lj.y0 - code_line.y0 > 220:
            break
        if not _is_bracket(lj.text):
            continue
        if _READONLY_MARK_RE.search(lj.text or "") and _x_close(code_line, lj, page_w):
            return True
        if _is_machine_code(lj.text) and _x_close(code_line, lj, page_w) and (lj.y0 > code_line.y0 + 2):
            break
    return False


def _word_count(s: str) -> int:
    s = _norm_ws(s)
    return 0 if not s else len(s.split())


def _build_spans(body_lines: List[L], page_w: float) -> List[Span]:
    lines = [l for l in body_lines if l.text]
    lines.sort(key=lambda x: (x.y0, x.x0))
    spans: List[Span] = []
    cur: Optional[Span] = None

    def can_merge(prev: Span, l: L) -> bool:
        if abs(l.size - prev.size) > 1.7:
            return False
        if prev.bold != l.bold:
            return False

        if (l.x0 - prev.x1) > max(34.0, 0.06 * page_w):
            return False

        if abs(l.x0 - prev.x0) > 28 and abs(l.cx - prev.cx) > 40:
            return False

        y_gap = l.y0 - prev.y1
        if y_gap < -2:
            return False
        if y_gap > 2.4 * max(6.0, prev.size):
            return False
        return True

    for l in lines:
        if cur is None:
            cur = Span(
                text=l.text,
                x0=l.x0,
                y0=l.y0,
                x1=l.x1,
                y1=l.y1,
                size=l.size,
                bold=l.bold,
                line_count=1,
            )
            continue

        if can_merge(cur, l):
            cur.text = _norm_ws(cur.text + " " + l.text)
            cur.x0 = min(cur.x0, l.x0)
            cur.y0 = min(cur.y0, l.y0)
            cur.x1 = max(cur.x1, l.x1)
            cur.y1 = max(cur.y1, l.y1)
            cur.size = max(cur.size, l.size)
            cur.line_count += 1
        else:
            spans.append(cur)
            cur = Span(
                text=l.text,
                x0=l.x0,
                y0=l.y0,
                x1=l.x1,
                y1=l.y1,
                size=l.size,
                bold=l.bold,
                line_count=1,
            )

    if cur is not None:
        spans.append(cur)
    return spans


def _collect_right_side_option_texts(body_lines: List[L], page_w: float, body_size: float) -> List[str]:
    # Identify short tokens in right-side columns; include repeated ones and "row groups" of multiple options.
    cands: List[Tuple[float, str]] = []
    counts: Dict[str, int] = {}

    for l in body_lines:
        t = _norm_ws(l.text)
        if not t:
            continue
        if l.x0 < 0.52 * page_w:
            continue
        if l.y0 < 105:
            continue
        wc = _word_count(t)
        if wc > 3:
            continue
        if len(t) > 24:
            continue
        if body_size > 0 and not (body_size - 2.5 <= l.size <= body_size + 3.8):
            continue
        if l.bold:
            continue
        if _MOSTLY_NONLETTER_RE.match(t):
            continue
        if _PURE_ROW_ANCHOR_RE.match(t):
            continue

        cands.append((l.y0, t))
        counts[t] = counts.get(t, 0) + 1

    # Group by y0 to catch one-off option headers in a row.
    cands.sort(key=lambda x: x[0])
    y_tol = max(5.5, 0.75 * (body_size if body_size else 9.0))
    row: List[str] = []
    last_y: Optional[float] = None
    row_bonus: Dict[str, int] = {}

    def flush_row(r: List[str]) -> None:
        uniq = []
        seen = set()
        for s in r:
            if s not in seen:
                uniq.append(s)
                seen.add(s)
        if len(uniq) >= 3:
            for s in uniq:
                row_bonus[s] = row_bonus.get(s, 0) + 1

    for y, t in cands:
        if last_y is None or abs(y - last_y) <= y_tol:
            row.append(t)
        else:
            flush_row(row)
            row = [t]
        last_y = y
    flush_row(row)

    out: List[str] = []
    for t, c in counts.items():
        if c >= 2 or row_bonus.get(t, 0) >= 1:
            out.append(t)

    out.sort(key=lambda x: (-len(x), x))
    return out


def _strip_trailing_option(text: str, option_texts: List[str]) -> str:
    t = _norm_ws(text)
    if not t:
        return t
    tl = " " + t.lower() + " "
    for opt in option_texts:
        opt_l = _norm_ws(opt).lower()
        if len(opt_l) < 2:
            continue
        if tl.endswith(" " + opt_l + " "):
            t = _norm_ws(t[: -len(opt)].rstrip())
            break
    t = t.strip().strip('"\'')

    t = re.sub(r"[\s\]\)\}]+$", "", t).strip()
    t = re.sub(r"[\s\[\(\{]+$", "", t).strip()
    return _norm_ws(t)


def _looks_like_option_row(text: str, option_texts: List[str]) -> bool:
    t = _norm_ws(text)
    if not t or not option_texts:
        return False
    tl = " " + t.lower() + " "
    hits = 0
    distinct = 0
    for opt in option_texts:
        opt_l = " " + _norm_ws(opt).lower() + " "
        if len(opt_l.strip()) < 2:
            continue
        if opt_l in tl:
            hits += 1
            distinct += 1
        if distinct >= 2:
            break
    if distinct >= 2:
        return True
    # Also treat "concatenations" of many short tokens (typical for header/option furniture).
    if _word_count(t) <= 8:
        # If most words are short and capitalized (or "Not"), it's likely options/furniture.
        words = t.split()
        shortish = sum(1 for w in words if len(w) <= 6)
        if len(words) >= 4 and shortish >= len(words) - 1:
            return True
    return False


def _is_bad_label_text(t: str) -> bool:
    t = _norm_ws(t)
    if not t:
        return True
    if _is_bracket(t) or _is_machine_code(t):
        return True
    if len(t) < 2:
        return True
    if _BARE_ANCHOR_RE.match(t):
        return True
    if _PURE_ROW_ANCHOR_RE.match(t):
        return True
    if re.fullmatch(r"[\d\W_]+", t):
        return True
    return False


def _clip_at_row_marker(t: str) -> str:
    t = _norm_ws(t)
    if not t:
        return t
    m = _ROW_MARK_ANY_RE.search(t)
    if not m:
        return t
    pre = _norm_ws(t[: m.start()])
    if _word_count(pre) >= 2:
        return pre
    # If it starts with Row N, just remove markers.
    return _norm_ws(_ROW_MARK_ANY_RE.sub(" ", t))


def _clean_label(t: str, option_texts: List[str], form_name: str) -> str:
    t = _norm_ws(t)
    if not t:
        return ""
    t = _ROW_PREFIX_RE.sub("", t).strip()
    t = t.strip().strip('"\'')

    t = _clip_at_row_marker(t)
    t = _strip_trailing_option(t, option_texts)
    t = _norm_ws(t)

    # Avoid echoing the form title as a field label.
    if form_name:
        if _norm_ws(form_name).lower() == t.lower() and _word_count(t) <= 8:
            return ""

    return t


def _overlap_1d(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _pick_wrapped_block(
    seed: L,
    candidates: List[L],
    x0_slack: float,
    y_gap_max: float,
    keep_pred,
) -> List[L]:
    if not seed:
        return []
    lines = [l for l in candidates if keep_pred(l)]
    if not lines:
        return [seed]

    lines.sort(key=lambda l: (l.y0, l.x0))
    try:
        seed_i = next(i for i, l in enumerate(lines) if l is seed)
    except StopIteration:
        lines.append(seed)
        lines.sort(key=lambda l: (l.y0, l.x0))
        seed_i = next(i for i, l in enumerate(lines) if l is seed)

    block = [seed]

    cur = seed
    for i in range(seed_i - 1, -1, -1):
        l = lines[i]
        if cur.y0 - l.y1 > y_gap_max:
            break
        if _PURE_ROW_ANCHOR_RE.match(l.text or ""):
            continue
        if abs(l.x0 - seed.x0) > x0_slack and abs(l.cx - seed.cx) > x0_slack:
            continue
        if abs(l.x0 - cur.x0) > x0_slack and abs(l.cx - cur.cx) > x0_slack:
            continue
        block.append(l)
        cur = l
        if len(block) >= 5:
            break

    block = list(reversed(block))

    cur = seed
    for i in range(seed_i + 1, len(lines)):
        l = lines[i]
        if l.y0 - cur.y1 > y_gap_max:
            break
        if _PURE_ROW_ANCHOR_RE.match(l.text or ""):
            continue
        if abs(l.x0 - seed.x0) > x0_slack and abs(l.cx - seed.cx) > x0_slack:
            continue
        if abs(l.x0 - cur.x0) > x0_slack and abs(l.cx - cur.cx) > x0_slack:
            continue
        block.append(l)
        cur = l
        if len(block) >= 6:
            break

    block.sort(key=lambda l: (l.y0, l.x0))
    return block


def _block_text(block: List[L]) -> str:
    if not block:
        return ""
    parts = [_norm_ws(l.text) for l in block if _norm_ws(l.text)]
    return _norm_ws(" ".join(parts))


def _looks_like_instruction_label(txt: str) -> bool:
    t = _norm_ws(txt)
    if not t:
        return True
    wc = _word_count(t)
    if wc >= 34 and "?" not in t:
        return True
    if len(t) >= 220 and "?" not in t:
        return True
    return False


def _label_candidates_for_code(
    c: L,
    body_lines: List[L],
    option_texts: List[str],
    page_w: float,
    body_size: float,
    form_name: str,
) -> List[Tuple[float, str]]:
    c_cy = c.cy
    c_cx = c.cx

    base = max(7.0, body_size if body_size else c.size if c.size else 9.0)
    y_band = max(14.0, 2.2 * base)
    y_above_max = max(120.0, 13.0 * base)
    y_below_max = max(130.0, 15.0 * base)
    x_slack = max(10.0, 0.018 * page_w)

    lines = [
        l
        for l in body_lines
        if l.text
        and (not _is_bad_label_text(l.text))
        and (not _PURE_ROW_ANCHOR_RE.match(l.text))
    ]

    left_inline = [
        l
        for l in lines
        if abs(l.cy - c_cy) <= y_band
        and l.x1 <= c.x0 + x_slack
        and (c.x0 - l.x1) <= max(380.0, 0.75 * page_w)
        and l.y0 >= c.y0 - 3.2 * base
        and l.y1 <= c.y1 + 3.6 * base
    ]

    right_inline = [
        l
        for l in lines
        if abs(l.cy - c_cy) <= y_band
        and l.x0 >= c.x1 - x_slack
        and (l.x0 - c.x1) <= max(220.0, 0.45 * page_w)
        and l.y0 >= c.y0 - 3.2 * base
        and l.y1 <= c.y1 + 3.6 * base
    ]

    above = [
        l
        for l in lines
        if l.y1 <= c.y0 + 0.5
        and (c.y0 - l.y1) <= y_above_max
        and (
            _overlap_1d(l.x0, l.x1, c.x0 - x_slack, c.x1 + x_slack) >= 6.0
            or abs(l.cx - c_cx) <= max(90.0, 0.16 * page_w)
        )
    ]

    below = [
        l
        for l in lines
        if l.y0 >= c.y1 - 0.5
        and (l.y0 - c.y1) <= y_below_max
        and (
            _overlap_1d(l.x0, l.x1, c.x0 - x_slack, c.x1 + x_slack) >= 6.0
            or abs(l.cx - c_cx) <= max(130.0, 0.22 * page_w)
            or (c.x0 >= 0.45 * page_w and l.x0 <= 0.58 * page_w)  # lab-grid style: code column vs label column
        )
    ]

    cands: List[Tuple[float, str]] = []

    def add_block(seed: L, pool: List[L], kind: str) -> None:
        if seed is None:
            return
        gap_max = max(10.0, 2.7 * base)
        x0_slack = max(28.0, 0.05 * page_w)

        if kind == "left":

            def keep_pred(l: L) -> bool:
                return abs(l.cx - seed.cx) <= max(110.0, 0.18 * page_w) and l.x1 <= c.x0 + x_slack

        elif kind == "right":

            def keep_pred(l: L) -> bool:
                return abs(l.cx - seed.cx) <= max(110.0, 0.18 * page_w) and l.x0 >= c.x1 - x_slack

        elif kind == "below":

            def keep_pred(l: L) -> bool:
                return abs(l.cx - seed.cx) <= max(150.0, 0.25 * page_w)

        else:

            def keep_pred(l: L) -> bool:
                return abs(l.cx - seed.cx) <= max(120.0, 0.20 * page_w)

        block = _pick_wrapped_block(seed, pool, x0_slack=x0_slack, y_gap_max=gap_max, keep_pred=keep_pred)
        txt = _clean_label(_block_text(block), option_texts, form_name)
        if not txt:
            return
        if _is_bad_label_text(txt):
            return
        if _looks_like_option_row(txt, option_texts):
            return
        if _looks_like_instruction_label(txt):
            return

        # Reject pure option tokens (structure-driven).
        if txt in option_texts and _word_count(txt) <= 3:
            return

        # Extra guard: right-side short tokens are very often option/value text.
        if kind == "right" and _word_count(txt) <= 2 and (seed.x0 >= 0.55 * page_w) and ("?" not in txt):
            return

        dy = 0.0
        if block:
            by0 = min(l.y0 for l in block)
            by1 = max(l.y1 for l in block)
            if by1 < c.y0:
                dy = c.y0 - by1
            elif by0 > c.y1:
                dy = by0 - c.y1
            else:
                dy = 0.0

        if kind == "left":
            dx = max(0.0, c.x0 - max(l.x1 for l in block))
            score = dy + 0.09 * dx
            if "?" in txt:
                score -= 8.0
            if _word_count(txt) >= 3:
                score -= 4.0
        elif kind == "right":
            dx = max(0.0, min(l.x0 for l in block) - c.x1)
            score = dy + 0.11 * dx
            if _word_count(txt) <= 2:
                score += 18.0
        elif kind == "below":
            dx = abs((min(l.cx for l in block) + max(l.cx for l in block)) / 2.0 - c_cx)
            score = dy + 0.10 * dx + 6.0  # slight penalty; use below when needed
            if _word_count(txt) >= 3:
                score -= 2.0
        else:  # above
            dx = abs((min(l.cx for l in block) + max(l.cx for l in block)) / 2.0 - c_cx)
            score = dy + 0.10 * dx
            if txt in option_texts and _word_count(txt) <= 2:
                score += 40.0

        max_sz = max((l.size for l in block), default=0.0)
        if body_size > 0 and max_sz >= body_size * 1.75 and (len(txt) <= 20 or _word_count(txt) <= 3):
            score += 28.0

        cands.append((score, txt))

    if left_inline:
        left_inline.sort(key=lambda l: (abs(l.cy - c_cy), max(0.0, c.x0 - l.x1), -l.x1))
        add_block(left_inline[0], left_inline, "left")
        if len(left_inline) > 1:
            add_block(left_inline[1], left_inline, "left")

    if above:
        above.sort(key=lambda l: ((c.y0 - l.y1), abs(l.cx - c_cx), -l.size, l.x0))
        add_block(above[0], above, "above")
        if len(above) > 1:
            add_block(above[1], above, "above")

    if below:
        below.sort(key=lambda l: ((l.y0 - c.y1), abs(l.cx - c_cx), l.x0))
        add_block(below[0], below, "below")
        if len(below) > 1:
            add_block(below[1], below, "below")

    if right_inline:
        right_inline.sort(key=lambda l: (abs(l.cy - c_cy), max(0.0, l.x0 - c.x1), l.x0))
        add_block(right_inline[0], right_inline, "right")

    best_by_text: Dict[str, float] = {}
    for s, t in cands:
        if t not in best_by_text or s < best_by_text[t]:
            best_by_text[t] = s

    out = sorted(((s, t) for t, s in best_by_text.items()), key=lambda x: x[0])

    final: List[Tuple[float, str]] = []
    for s, t in out:
        if not t:
            continue
        if _MOSTLY_NONLETTER_RE.match(t):
            continue
        if _looks_like_option_row(t, option_texts):
            continue
        if form_name and t.lower() == _norm_ws(form_name).lower():
            continue
        final.append((s, t))

    return final


def _best_col_header(code_line: L, spans: List[Span], body_size: float, page_w: float, option_texts: List[str]) -> Optional[Span]:
    best: Optional[Span] = None
    best_score: Optional[float] = None
    code_cx = code_line.cx

    for s in spans:
        t = _norm_ws(s.text)
        if _is_bad_label_text(t):
            continue
        if _looks_like_option_row(t, option_texts):
            continue
        if s.y1 >= code_line.y0:
            continue
        if code_line.y0 - s.y1 > 320:
            continue

        x_close = abs(s.cx - code_cx)
        if x_close > max(150.0, 0.24 * page_w):
            continue

        if body_size > 0 and (s.size < body_size - 0.2) and (not s.bold):
            continue

        score = (code_line.y0 - s.y1) + 0.10 * x_close
        if s.bold:
            score -= 7.0
        if len(t) > 60:
            score += 22.0

        if best_score is None or score < best_score:
            best_score = score
            best = s

    return best


def _grid_row_fields(body_lines: List[L], page_w: float, body_size: float, option_texts: List[str], form_name: str) -> List[str]:
    # Table/grid layout: left-side row labels + multiple short right-side options on same y.
    # Used for lab grids and assessment tables; avoids emitting the option header row itself.
    if not body_lines:
        return []
    opts_set = {o.lower(): o for o in option_texts}

    # Collect right-side short tokens by y rows.
    right_tokens: List[Tuple[float, L, str]] = []
    for l in body_lines:
        t = _norm_ws(l.text)
        if not t or _is_bad_label_text(t):
            continue
        if l.x0 < 0.54 * page_w:
            continue
        if l.y0 < 90:
            continue
        if _word_count(t) > 3 or len(t) > 24:
            continue
        if l.bold:
            continue
        if body_size > 0 and not (body_size - 2.7 <= l.size <= body_size + 4.2):
            continue
        if _MOSTLY_NONLETTER_RE.match(t):
            continue
        right_tokens.append((l.y0, l, t))

    if not right_tokens:
        return []

    right_tokens.sort(key=lambda x: x[0])
    y_tol = max(6.0, 0.85 * (body_size if body_size else 9.0))

    rows: List[List[Tuple[L, str]]] = []
    cur: List[Tuple[L, str]] = []
    last_y: Optional[float] = None
    for y, l, t in right_tokens:
        if last_y is None or abs(y - last_y) <= y_tol:
            cur.append((l, t))
        else:
            if cur:
                rows.append(cur)
            cur = [(l, t)]
        last_y = y
    if cur:
        rows.append(cur)

    fields: List[str] = []
    for row in rows:
        # Need multiple "option-like" tokens in the row to consider it a data-entry control row.
        uniq = []
        seen = set()
        for _, t in row:
            tl = t.lower()
            if tl not in seen:
                uniq.append(t)
                seen.add(tl)

        if len(uniq) < 2:
            continue

        # If option_texts are known, require at least 2 hits; else require 3 tokens total.
        opt_hits = 0
        if option_texts:
            for t in uniq:
                if (" " + t.lower() + " ") in (" " + " ".join(o.lower() for o in option_texts) + " "):
                    opt_hits += 1
        if option_texts and opt_hits < 2 and len(uniq) < 3:
            continue
        if (not option_texts) and len(uniq) < 3:
            continue

        row_y = sum(l.cy for l, _ in row) / max(1, len(row))

        # Find left-side label near same y.
        left_cands = [
            l
            for l in body_lines
            if l.text
            and (not _is_bad_label_text(l.text))
            and (not _PURE_ROW_ANCHOR_RE.match(l.text))
            and l.x0 <= 0.58 * page_w
            and abs(l.cy - row_y) <= max(12.0, 1.9 * (body_size if body_size else max(8.0, l.size)))
        ]
        if not left_cands:
            continue

        left_cands.sort(key=lambda l: (abs(l.cy - row_y), l.x0, -l.x1))
        lbl = _clean_label(left_cands[0].text, option_texts, form_name)
        if not lbl or _is_bad_label_text(lbl):
            continue
        if _looks_like_option_row(lbl, option_texts):
            continue
        if _looks_like_instruction_label(lbl):
            continue
        if lbl in option_texts and _word_count(lbl) <= 3:
            continue

        fields.append(lbl)

    # Dedup while preserving order.
    out: List[str] = []
    seen = set()
    for f in fields:
        k = f.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(f)
    return out


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    current_form = ""

    for page_idx0, raw_lines in pages:
        merged = _merge_bracket_fragments(raw_lines)
        if not merged:
            continue

        page_w = _estimate_page_width(merged)

        body_lines = [l for l in merged if l.text and (not _is_bracket(l.text))]
        body_sizes = [l.size for l in body_lines if l.size and l.size > 0]
        body_size = _median(body_sizes, default=0.0)

        title = _page_title(body_lines, body_size)
        if title:
            current_form = title

        option_texts = _collect_right_side_option_texts(body_lines, page_w, body_size)
        spans = _build_spans(body_lines, page_w)

        # Grid/table extraction (improves coverage for lab/assessment grids; avoids option headers).
        if current_form:
            for fld in _grid_row_fields(body_lines, page_w, body_size, option_texts, current_form):
                key = (page_idx0 + 1, current_form, fld)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"form_name": current_form, "field_name": fld, "page": page_idx0 + 1})

        code_lines = [l for l in merged if l.text and _is_machine_code(l.text)]
        type_lines = [l for l in merged if l.text and _is_type_line(l.text)]

        if not code_lines and not type_lines:
            continue

        hdr_counts: Dict[str, int] = {}
        best_hdr_for_code: Dict[int, str] = {}
        if code_lines:
            for c in code_lines:
                if _is_read_only(c, merged, page_w):
                    continue
                h = _best_col_header(c, spans, body_size, page_w, option_texts)
                if h and h.text:
                    ht = _clean_label(h.text, option_texts, current_form)
                    if ht and (ht not in option_texts) and (not _MOSTLY_NONLETTER_RE.match(ht)) and (not _looks_like_option_row(ht, option_texts)):
                        hdr_counts[ht] = hdr_counts.get(ht, 0) + 1
                        best_hdr_for_code[c.idx] = ht

        def emit_field(field: str) -> None:
            nonlocal out, seen, current_form, page_idx0
            field = _clean_label(field, option_texts, current_form)
            if not field:
                return
            if _is_bad_label_text(field):
                return
            if _MOSTLY_NONLETTER_RE.match(field):
                return
            if _looks_like_option_row(field, option_texts):
                return
            if _looks_like_instruction_label(field):
                return
            if field in option_texts and _word_count(field) <= 3:
                return
            if not current_form:
                return
            key = (page_idx0 + 1, current_form, field)
            if key in seen:
                return
            seen.add(key)
            out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})

        # Primary: machine-code anchored extraction.
        for c in code_lines:
            if _is_read_only(c, merged, page_w):
                continue

            cands = _label_candidates_for_code(
                c=c,
                body_lines=body_lines,
                option_texts=option_texts,
                page_w=page_w,
                body_size=body_size,
                form_name=current_form,
            )
            if not cands:
                continue

            field = ""
            for _, t in cands:
                if not t:
                    continue
                if t in option_texts and _word_count(t) <= 3:
                    continue
                if _looks_like_option_row(t, option_texts):
                    continue
                if _looks_like_instruction_label(t):
                    continue
                field = t
                break

            if not field:
                continue

            wc = _word_count(field)
            ht = best_hdr_for_code.get(c.idx, "")
            if ht and wc <= 2:
                if current_form and ht.lower() == _norm_ws(current_form).lower():
                    ht = ""
                if ht and hdr_counts.get(ht, 0) <= 1 and ht not in field and field not in ht:
                    if ht not in option_texts and (not _looks_like_option_row(ht, option_texts)):
                        field = _norm_ws(field + " " + ht)

            emit_field(field)

        # Secondary: TYPE-anchored extraction when codes are absent/misaligned.
        # Uses the TYPE line position as the anchor to discover nearby labels (often fixes "Reason not done", "Scan", etc.).
        for tline in type_lines:
            # Create a pseudo-anchor at the TYPE line position; skip if it appears to be read-only meta.
            if _READONLY_MARK_RE.search(tline.text or ""):
                continue

            pseudo = L(
                text=tline.text,
                x0=tline.x0,
                y0=tline.y0,
                x1=tline.x1,
                y1=tline.y1,
                size=tline.size,
                bold=tline.bold,
                non_black=tline.non_black,
                idx=tline.idx,
            )

            cands = _label_candidates_for_code(
                c=pseudo,
                body_lines=body_lines,
                option_texts=option_texts,
                page_w=page_w,
                body_size=body_size,
                form_name=current_form,
            )
            if not cands:
                continue

            field = ""
            for _, s in cands:
                if not s:
                    continue
                if s in option_texts and _word_count(s) <= 3:
                    continue
                if _looks_like_option_row(s, option_texts):
                    continue
                if _looks_like_instruction_label(s):
                    continue
                field = s
                break

            if field:
                emit_field(field)

    return out
```
