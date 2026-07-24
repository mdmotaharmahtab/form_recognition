import re
import statistics
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any


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


def _norm_ws(s: str) -> str:
    return " ".join(s.strip().split())


def _is_bracket(s: str) -> bool:
    s = s.strip()
    return bool(_BRACKET_ANY_RE.match(s))


def _is_machine_code(s: str) -> bool:
    s = s.strip()
    if ":" in s:
        return False
    return bool(_MACHINE_CODE_RE.match(s))


def _is_type_line(s: str) -> bool:
    s = s.strip()
    return _is_bracket(s) and bool(_TYPE_MARK_RE.search(s))


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
            while j < n and (j - i) <= 10:
                lj = lines[j]
                tj = (lj.text or "").strip()
                if lj.y0 - y1 > 30:
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


def _build_spans(body_lines: List[L], body_size: float) -> List[Span]:
    lines = [l for l in body_lines if l.text]
    lines.sort(key=lambda x: (x.y0, x.x0))
    spans: List[Span] = []
    cur: Optional[Span] = None

    def can_merge(prev: Span, l: L) -> bool:
        if abs(l.size - prev.size) > 1.6:
            return False
        if prev.bold != l.bold:
            return False
        if abs(l.x0 - prev.x0) > 22 and abs(((l.x0 + l.x1) / 2.0) - prev.cx) > 28:
            return False
        y_gap = l.y0 - prev.y1
        if y_gap < -2:
            return False
        if y_gap > 2.2 * max(6.0, prev.size):
            return False
        return True

    for l in lines:
        if l.y0 < 140 and l.x0 < 160 and body_size > 0 and l.size >= body_size * 1.75:
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
    cands = [
        l
        for l in body_lines
        if l.text
        and l.x0 < 140
        and l.y0 < 140
        and l.size >= max(12.0, body_size * 1.35 if body_size else 12.0)
    ]
    if not cands:
        cands = [
            l
            for l in body_lines
            if l.text
            and l.x0 < 140
            and l.y0 < 200
            and l.bold
            and l.size >= max(12.5, body_size * 1.35 if body_size else 12.5)
        ]
    if not cands:
        cands = [
            l
            for l in body_lines
            if l.text
            and l.y0 < 200
            and l.size >= max(11.5, body_size * 1.25 if body_size else 11.5)
            and (l.bold or l.non_black)
        ]

    if not cands:
        return None

    cands.sort(key=lambda l: (-l.size, l.y0, l.x0))
    base = cands[0]
    parts = [base.text]

    for l in cands[1:]:
        if l.y0 > base.y1 + 3.0 * max(6.0, base.size):
            continue
        if abs(l.size - base.size) <= 1.2 and abs(l.x0 - base.x0) <= 30:
            if l.y0 - base.y1 <= 2.4 * max(6.0, base.size):
                parts.append(l.text)

    title = _norm_ws(" ".join(parts))
    return title or None


def _x_close(a: L, b: L) -> bool:
    # "Same column" heuristic for bracket metadata lines.
    if abs(a.x0 - b.x0) <= 70:
        return True
    if abs(a.x1 - b.x1) <= 70:
        return True
    if not (a.x1 + 10 < b.x0 or b.x1 + 10 < a.x0):
        return True
    return False


def _is_read_only(code_line: L, merged_lines: List[L]) -> bool:
    # Only treat READ-ONLY metadata as applying to this code if it's nearby in the same x-column.
    for j in range(code_line.idx + 1, min(len(merged_lines), code_line.idx + 30)):
        lj = merged_lines[j]
        if lj.y0 - code_line.y0 > 200:
            break
        if not _is_bracket(lj.text):
            continue
        if _READONLY_MARK_RE.search(lj.text or "") and _x_close(code_line, lj):
            return True
        if _is_machine_code(lj.text) and _x_close(code_line, lj) and (lj.y0 > code_line.y0 + 2):
            # Next field in same column reached before a read-only marker.
            break
    return False


def _best_row_label(code_line: L, spans: List[Span], body_size: float) -> Optional[Span]:
    best = None
    best_score = None

    for s in spans:
        if not s.text:
            continue
        if s.x0 > 270:
            continue

        if s.y1 < code_line.y0:
            dy = code_line.y0 - s.y1
        elif s.y0 > code_line.y1:
            dy = s.y0 - code_line.y1
        else:
            dy = 0.0

        if dy > 280:
            continue

        score = dy
        if s.bold:
            score -= 14.0
        if (not s.bold) and s.line_count >= 3 and len(s.text) >= 90:
            score += 65.0
        if (not s.bold) and len(s.text) >= 160:
            score += 35.0
        if body_size > 0 and s.size >= body_size * 1.75:
            score += 80.0

        if best_score is None or score < best_score:
            best_score = score
            best = s

    return best


def _best_col_header(code_line: L, spans: List[Span], body_size: float) -> Optional[Span]:
    best = None
    best_score = None

    for s in spans:
        if not s.text:
            continue
        if s.y1 >= code_line.y0:
            continue
        if code_line.y0 - s.y1 > 260:
            continue

        x_close = abs(s.cx - ((code_line.x0 + code_line.x1) / 2.0))
        if x_close > 120:
            continue

        if body_size > 0 and (s.size < body_size + 0.6) and (not s.bold):
            continue
        if s.x0 < 170 and code_line.x0 > 250:
            continue

        score = (code_line.y0 - s.y1) + 0.08 * x_close
        if s.bold:
            score -= 6.0
        if len(s.text) > 60:
            score += 20.0

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
        body_lines = [l for l in merged if l.text and (not _is_bracket(l.text))]
        body_sizes = [l.size for l in body_lines if l.size and l.size > 0]
        body_size = _median(body_sizes, default=0.0)

        title = _page_title(body_lines, body_size)
        if title:
            current_form = title

        spans = _build_spans(body_lines, body_size)
        code_lines = [l for l in merged if l.text and _is_machine_code(l.text)]

        for c in code_lines:
            if _is_read_only(c, merged):
                continue

            row = _best_row_label(c, spans, body_size)
            hdr = _best_col_header(c, spans, body_size)

            field = ""
            if row and hdr and hdr.text and row.text and (hdr.text not in row.text):
                field = _norm_ws(row.text + " " + hdr.text)
            elif row:
                field = row.text
            elif hdr:
                field = hdr.text
            else:
                continue

            field = _norm_ws(field)
            if not field:
                continue
            if re.fullmatch(r"[\d\W_]+", field or ""):
                continue

            key = (page_idx0 + 1, current_form, field)
            if key in seen:
                continue
            seen.add(key)

            out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})

    return out
