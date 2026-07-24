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

_ROW_ANCHOR_RE = re.compile(r"^\s*Row\s*\d+\s*(?:[:.\-]|$)", re.IGNORECASE)
_MOSTLY_NONLETTER_RE = re.compile(r"^[^A-Za-z]*$")


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


def _merge_bracket_fragments(lines) -> List[L]:
    merged: List[L] = []
    i = 0
    n = len(lines)
    while i < n:
        li = lines[i]
        t = (li.text or "").strip()
        if t.startswith("[") and "]" not in t:
            acc = t
            x0, y0, x1, y1 = li.x0, li.y0, li.x1, li.y1
            size = li.size
            bold = bool(li.bold)
            non_black = bool(li.non_black)
            j = i + 1
            while j < n and (j - i) <= 12:
                lj = lines[j]
                tj = (lj.text or "").strip()
                if lj.y0 - y1 > 40:
                    break
                if tj == "":
                    j += 1
                    continue
                acc += tj
                x0 = min(x0, lj.x0)
                y0 = min(y0, lj.y0)
                x1 = max(x1, lj.x1)
                y1 = max(y1, lj.y1)
                size = max(size, lj.size)
                bold = bold or bool(lj.bold)
                non_black = non_black or bool(lj.non_black)
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
                    x0=li.x0,
                    y0=li.y0,
                    x1=li.x1,
                    y1=li.y1,
                    size=li.size,
                    bold=bool(li.bold),
                    non_black=bool(li.non_black),
                    idx=len(merged),
                )
            )
            i += 1
    return merged


def _median(vals: List[float], default: float = 0.0) -> float:
    vals = [v for v in vals if v is not None]
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


def _build_spans(body_lines: List[L], body_size: float, page_w: float) -> List[Span]:
    lines = [l for l in body_lines if l.text]
    lines.sort(key=lambda x: (x.y0, x.x0))
    spans: List[Span] = []
    cur: Optional[Span] = None

    def can_merge(prev: Span, l: L) -> bool:
        if abs(l.size - prev.size) > 1.6:
            return False
        if prev.bold != l.bold:
            return False

        # Avoid fusing across distant columns on the same visual row.
        if (l.x0 - prev.x1) > max(30.0, 0.05 * page_w):
            return False

        # Keep same-column / wrapped-line merges.
        if abs(l.x0 - prev.x0) > 26 and abs(((l.x0 + l.x1) / 2.0) - prev.cx) > 34:
            return False

        y_gap = l.y0 - prev.y1
        if y_gap < -2:
            return False
        if y_gap > 2.2 * max(6.0, prev.size):
            return False
        return True

    for l in lines:
        # Drop very large top-left headers from span pool (to reduce title/section text as labels).
        if (
            l.y0 < 140
            and l.x0 < 170
            and body_size > 0
            and l.size >= body_size * 1.75
            and (l.bold or l.non_black)
        ):
            if cur is not None:
                spans.append(cur)
                cur = None
            continue

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


def _page_title(body_lines: List[L], body_size: float) -> Optional[str]:
    # Prefer top-left prominent lines (often bold or non-black).
    cands = [
        l
        for l in body_lines
        if l.text
        and l.x0 < 180
        and l.y0 < 140
        and l.size >= max(12.0, (body_size * 1.35) if body_size else 12.0)
        and (l.bold or l.non_black)
    ]
    if not cands:
        cands = [
            l
            for l in body_lines
            if l.text
            and l.x0 < 180
            and l.y0 < 170
            and l.size >= max(12.5, (body_size * 1.35) if body_size else 12.5)
            and l.bold
        ]
    if not cands:
        return None

    cands.sort(key=lambda l: (-l.size, l.y0, l.x0))
    base = cands[0]
    parts = [base.text]

    for l in cands[1:]:
        if l.y0 > base.y1 + 3.0 * max(6.0, base.size):
            continue
        if abs(l.size - base.size) <= 1.2 and abs(l.x0 - base.x0) <= 40:
            if l.y0 - base.y1 <= 2.6 * max(6.0, base.size):
                parts.append(l.text)

    title = _norm_ws(" ".join(parts))
    if not title:
        return None
    if _ROW_ANCHOR_RE.match(title):
        return None
    return title


def _x_close(a: L, b: L, page_w: float) -> bool:
    # "Same column" heuristic for bracket metadata lines.
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


def _collect_right_side_option_texts(spans: List[Span], page_w: float, body_size: float) -> List[str]:
    # Identify repeated short labels in the right-hand area (often answer options like Yes/No/Applicable).
    opts: Dict[str, int] = {}
    for s in spans:
        t = _norm_ws(s.text)
        if not t:
            continue
        if s.x0 < 0.58 * page_w:
            continue
        if s.y0 < 120:
            continue
        wc = _word_count(t)
        if wc > 3:
            continue
        if len(t) > 20:
            continue
        if body_size > 0 and not (body_size - 2.2 <= s.size <= body_size + 3.2):
            continue
        if s.bold:
            continue
        if _is_bracket(t) or _is_machine_code(t):
            continue
        if _ROW_ANCHOR_RE.match(t):
            continue
        if _MOSTLY_NONLETTER_RE.match(t):
            continue
        opts[t] = opts.get(t, 0) + 1

    # Keep things that appear at least twice (structure), plus a few common singletons
    # that are extremely short and in far-right (still structure-driven).
    out: List[str] = []
    for t, c in opts.items():
        if c >= 2:
            out.append(t)
        elif len(t) <= 10 and page_w > 0:
            out.append(t)

    out.sort(key=lambda x: (-len(x), x))
    return out


def _strip_trailing_option(text: str, option_texts: List[str]) -> str:
    t = _norm_ws(text)
    if not t:
        return t

    # Strip trailing right-side option tokens (learned from page structure).
    for opt in option_texts:
        if len(opt) < 2:
            continue
        if t.endswith(" " + opt):
            t = _norm_ws(t[: -len(opt)].rstrip())
            break

    # Strip trailing bracket-like/punct tails sometimes glued from nearby legends.
    t = re.sub(r"[\s\]\)\}]+$", "", t).strip()
    t = re.sub(r"[\s\[\(\{]+$", "", t).strip()
    t = _norm_ws(t)
    return t


def _is_bad_label_text(t: str) -> bool:
    t = _norm_ws(t)
    if not t:
        return True
    if _is_bracket(t) or _is_machine_code(t):
        return True
    if _ROW_ANCHOR_RE.match(t):
        return True
    if len(t) < 2:
        return True
    if re.fullmatch(r"[\d\W_]+", t):
        return True
    # Reject labels that start with a bare anchor number (common in rating anchors).
    if re.match(r"^\s*\d{1,2}\s*[\)\.:-]\s*$", t):
        return True
    return False


def _best_row_label(code_line: L, spans: List[Span], body_size: float, page_w: float) -> Optional[Span]:
    best: Optional[Span] = None
    best_score: Optional[float] = None

    for s in spans:
        t = _norm_ws(s.text)
        if _is_bad_label_text(t):
            continue

        # Prefer spans that are in the label area left of the field/code.
        # Use page-relative bounds to avoid hardcoded columns.
        if s.x0 > min(code_line.x0 + 25.0, 0.78 * page_w):
            continue

        # Vertical distance / overlap.
        if s.y1 < code_line.y0:
            dy = code_line.y0 - s.y1
        elif s.y0 > code_line.y1:
            dy = s.y0 - code_line.y1
        else:
            dy = 0.0

        if dy > 320:
            continue

        # Base score: prefer closer vertically.
        score = dy

        # Prefer text that ends before the code box (less likely to include filled values/options).
        if s.x1 <= code_line.x0 + 6.0:
            score -= 18.0
        else:
            # Penalize overlap into the entry area.
            overlap = max(0.0, min(s.x1, code_line.x1) - max(s.x0, code_line.x0))
            score += 0.12 * overlap

        # Prefer bold slightly (often section row labels), but not big headers.
        if s.bold:
            score -= 10.0

        # Penalize long paragraph-ish blocks.
        if (not s.bold) and s.line_count >= 3 and len(t) >= 90:
            score += 70.0
        if (not s.bold) and len(t) >= 160:
            score += 45.0

        # Avoid using oversized titles as row labels.
        if body_size > 0 and s.size >= body_size * 1.75:
            score += 90.0

        if best_score is None or score < best_score:
            best_score = score
            best = s

    return best


def _best_col_header(code_line: L, spans: List[Span], body_size: float, page_w: float) -> Optional[Span]:
    best: Optional[Span] = None
    best_score: Optional[float] = None
    code_cx = (code_line.x0 + code_line.x1) / 2.0

    for s in spans:
        t = _norm_ws(s.text)
        if _is_bad_label_text(t):
            continue

        # Must be above.
        if s.y1 >= code_line.y0:
            continue
        if code_line.y0 - s.y1 > 300:
            continue

        # Must be in the same general column as the code.
        x_close = abs(s.cx - code_cx)
        if x_close > max(140.0, 0.22 * page_w):
            continue

        # Avoid tiny plain body text far from being a header.
        if body_size > 0 and (s.size < body_size - 0.2) and (not s.bold):
            continue

        # If code is in far right, ignore far-left headers.
        if s.x0 < 0.18 * page_w and code_line.x0 > 0.45 * page_w:
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


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    current_form = ""

    for page_idx0, raw_lines in pages:
        merged = _merge_bracket_fragments(raw_lines)
        page_w = _estimate_page_width(merged)

        body_lines = [l for l in merged if l.text and (not _is_bracket(l.text))]
        body_sizes = [l.size for l in body_lines if l.size and l.size > 0]
        body_size = _median(body_sizes, default=0.0)

        title = _page_title(body_lines, body_size)
        if title:
            current_form = title

        spans = _build_spans(body_lines, body_size, page_w)
        option_texts = _collect_right_side_option_texts(spans, page_w, body_size)

        code_lines = [l for l in merged if l.text and _is_machine_code(l.text)]

        for c in code_lines:
            if _is_read_only(c, merged, page_w):
                continue

            row = _best_row_label(c, spans, body_size, page_w)
            hdr = _best_col_header(c, spans, body_size, page_w)

            field = ""
            if row and hdr and hdr.text and row.text:
                rt = _norm_ws(row.text)
                ht = _norm_ws(hdr.text)
                if ht and rt and (ht not in rt) and (rt not in ht):
                    field = _norm_ws(rt + " " + ht)
                else:
                    field = rt or ht
            elif row:
                field = _norm_ws(row.text)
            elif hdr:
                field = _norm_ws(hdr.text)
            else:
                continue

            field = _strip_trailing_option(field, option_texts)
            field = _norm_ws(field)

            if _is_bad_label_text(field):
                continue

            # Avoid admitting single short tokens from right-side option column.
            if page_w > 0 and row is None and hdr is not None:
                if hdr.x0 > 0.62 * page_w and _word_count(field) <= 2 and len(field) <= 16:
                    continue

            # Avoid labels that are mostly non-letters (anchors, punctuation).
            if _MOSTLY_NONLETTER_RE.match(field):
                continue

            key = (page_idx0 + 1, current_form, field)
            if key in seen:
                continue
            seen.add(key)

            out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})

    return out
