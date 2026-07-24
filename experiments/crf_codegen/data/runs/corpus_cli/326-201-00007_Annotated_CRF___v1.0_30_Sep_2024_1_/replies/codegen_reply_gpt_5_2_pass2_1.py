```python
# Observed layout: "Annotated CRF" pages with a fixed header, then repeated activity blocks.
# Each activity block has a bold activity title in the middle column, followed by bold question/label text,
# plus colored bold side labels like "Staff Initials:" and "Comment:" (data-entry fields).
# Strategy: detect this page family by geometry, track schedule and current activity title across pages,
# extract bold black wrapped labels/questions and colored bold ":" labels; skip options and machine-code annotations.

import re
import unicodedata
from typing import List, Tuple, Dict, Any


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    # Persistent context across pages
    schedule_name = ""
    current_activity = ""

    # Regexes to exclude technical annotations / machine codes
    re_bracket_code = re.compile(r"^\[[^\]]+\]\s*$")
    re_sas = re.compile(r"\bSAS:\[|Name=|Length=|DataType=", re.IGNORECASE)

    def norm_text(s: str) -> str:
        return " ".join((s or "").split())

    def has_letter(s: str) -> bool:
        for ch in s:
            if unicodedata.category(ch).startswith("L"):
                return True
        return False

    def looks_like_footer(line) -> bool:
        # In samples footer is at y~750; keep a wide cutoff.
        return (line.y0 is not None and line.y0 > 705)

    def is_machine_code(t: str) -> bool:
        tt = t.strip()
        if not tt:
            return True
        if re_bracket_code.match(tt):
            return True
        if re_sas.search(tt):
            return True
        # Very code-like: mostly uppercase/digits/_/[]:=, no letters from general scripts
        letters = sum(1 for ch in tt if unicodedata.category(ch).startswith("L"))
        if letters == 0:
            return False
        code_chars = sum(1 for ch in tt if (ch.isupper() or ch.isdigit() or ch in "_[]:=.,-/()#"))
        if len(tt) >= 10 and code_chars / max(1, len(tt)) > 0.85:
            return True
        return False

    def is_option_line(t: str) -> bool:
        tt = t.strip()
        if not tt:
            return False
        # Typical option bullets: "O Yes", "O 1 - ...", "O X - ..."
        if tt.startswith(("O ", "o ")):
            return True
        if re.match(r"^[Oo]\s*[0-9A-Za-z]{1,3}\s*[-–—:]\s+\S", tt):
            return True
        return False

    def is_placeholderish(t: str) -> bool:
        tt = t.strip()
        if not tt:
            return True
        # Underscore input boxes and pure format hints shouldn't be treated as labels/questions
        if all(ch in "_-:./() " for ch in tt):
            return True
        if re.match(r"^(dd|mm|yyyy|mmm|hh)\b", tt, re.IGNORECASE):
            return True
        if re.match(r"^[A-Za-z]{1,4}\s*[:\-]\s*$", tt):
            return True
        return False

    def page_matches_family(lines: List[Any]) -> bool:
        # Geometry-based: big bold colored title near top + several colored header lines.
        big_title = False
        blue_hdrs = 0
        for ln in lines:
            if ln.y0 is None or ln.x0 is None:
                continue
            if ln.y0 < 75 and ln.bold and ln.non_black and ln.size >= 17.5:
                big_title = True
            if 100 <= ln.y0 <= 135 and ln.bold and ln.non_black and 9.0 <= ln.size <= 11.5:
                blue_hdrs += 1
        return big_title and blue_hdrs >= 2

    def build_y_index(lines: List[Any]):
        # Bucket by rounded y to allow fast "same row" queries.
        idx = {}
        for ln in lines:
            if ln.y0 is None:
                continue
            yb = int(round(ln.y0 / 2.0) * 2)
            idx.setdefault(yb, []).append(ln)
        return idx

    def any_near_y(y_index, y0: float, cond, tol: float = 2.8) -> bool:
        yb = int(round(y0 / 2.0) * 2)
        for yk in (yb - 2, yb, yb + 2, yb - 4, yb + 4):
            for ln in y_index.get(yk, []):
                if abs((ln.y0 or 0.0) - y0) <= tol and cond(ln):
                    return True
        return False

    def pick_schedule_name(lines: List[Any]) -> str:
        # Value line sits around x~167, y~90-110, size~11, not bold.
        best = ""
        best_score = -1
        for ln in lines:
            if ln.y0 is None or ln.x0 is None:
                continue
            if looks_like_footer(ln):
                continue
            if 80 <= ln.y0 <= 112 and 135 <= ln.x0 <= 275 and 10.0 <= ln.size <= 12.2 and (not ln.bold):
                t = norm_text(ln.text)
                if not t or is_machine_code(t):
                    continue
                # Prefer longer, more contentful lines.
                score = len(t) + (5 if "," in t else 0)
                if score > best_score:
                    best_score = score
                    best = t
        return best

    def is_activity_header_line(ln, y_index) -> bool:
        if ln.y0 is None or ln.x0 is None:
            return False
        if looks_like_footer(ln):
            return False
        if not (ln.bold and (not ln.non_black) and 9.0 <= ln.size <= 11.5 and 140 <= ln.x0 <= 275):
            return False
        # Same row should have left timepoint-ish cell and right line-number-ish cell.
        has_left = any_near_y(
            y_index,
            ln.y0,
            lambda l: (l.x0 is not None and l.x0 < 95 and 8.5 <= l.size <= 11.5 and (l.text or "").strip() != ""),
        )
        has_right = any_near_y(
            y_index,
            ln.y0,
            lambda l: (
                l.x0 is not None
                and l.x0 > 455
                and 8.5 <= l.size <= 11.5
                and re.search(r"\d", (l.text or ""))
            ),
        )
        return has_left and has_right

    def is_colored_field_label(ln) -> bool:
        if ln.y0 is None or ln.x0 is None:
            return False
        if looks_like_footer(ln):
            return False
        t = norm_text(ln.text)
        if not t:
            return False
        # Colored bold labels ending with ":" at left side are entry fields.
        if ln.non_black and ln.bold and t.endswith(":") and ln.x0 < 155 and 8.5 <= ln.size <= 11.5:
            # Avoid column headers (typically no colon) and other furniture
            if 90 <= ln.y0 <= 140 and ln.x0 < 120:
                # Still allow if it has colon (sample shows "Staff Initials:" below 140)
                pass
            return True
        return False

    def is_question_line(ln, y_index) -> bool:
        if ln.y0 is None or ln.x0 is None:
            return False
        if looks_like_footer(ln):
            return False
        if not (ln.bold and (not ln.non_black) and 9.0 <= ln.size <= 11.5 and 140 <= ln.x0 <= 520):
            return False
        if is_activity_header_line(ln, y_index):
            return False
        t = norm_text(ln.text)
        if not t:
            return False
        if is_machine_code(t) or is_option_line(t) or is_placeholderish(t):
            return False
        # Exclude pure numerics / very short fragments without letters.
        if len(t) < 3:
            return False
        if not has_letter(t):
            return False
        # Exclude obvious header title if it appears (large handled earlier), but be safe:
        if ln.y0 < 85:
            return False
        return True

    def merge_wrapped(lines: List[Any], start_i: int, y_index) -> Tuple[str, int]:
        # Merge consecutive question lines that wrap.
        first = lines[start_i]
        base_x = first.x0 or 0.0
        parts = [norm_text(first.text)]
        j = start_i + 1
        last_y = first.y0 or 0.0
        while j < len(lines):
            ln = lines[j]
            if ln.y0 is None or ln.x0 is None:
                j += 1
                continue
            # Stop on colored field label lines or activity headers
            if is_colored_field_label(ln) or is_activity_header_line(ln, y_index):
                break
            if not is_question_line(ln, y_index):
                # Allow small interleaving noise only if it's clearly not part of question (usually it is separate).
                break
            dy = (ln.y0 or 0.0) - last_y
            if dy > 14.5:
                break
            if abs((ln.x0 or 0.0) - base_x) > 14.0:
                break
            parts.append(norm_text(ln.text))
            last_y = ln.y0 or last_y
            j += 1
        return norm_text(" ".join(parts)), j

    for page_idx0, lines in pages:
        if not lines:
            continue

        if not page_matches_family(lines):
            continue

        y_index = build_y_index(lines)

        # Update schedule name if present
        sn = pick_schedule_name(lines)
        if sn:
            schedule_name = sn

        # Per-page dedup
        emitted = set()

        i = 0
        while i < len(lines):
            ln = lines[i]
            if ln.y0 is None or ln.x0 is None:
                i += 1
                continue
            if looks_like_footer(ln):
                i += 1
                continue

            if is_activity_header_line(ln, y_index):
                t = norm_text(ln.text)
                if t and not is_machine_code(t):
                    current_activity = t
                i += 1
                continue

            # Colored ":" labels are fields (e.g., Staff Initials:, Comment:)
            if is_colored_field_label(ln):
                form = current_activity or schedule_name or ""
                field = norm_text(ln.text)
                key = (form, field, page_idx0)
                if key not in emitted:
                    out.append({"form_name": form, "field_name": field, "page": page_idx0 + 1})
                    emitted.add(key)
                i += 1
                continue

            # Extract bold wrapped question/label lines (one record per question)
            if is_question_line(ln, y_index):
                merged, next_i = merge_wrapped(lines, i, y_index)
                if merged and not is_machine_code(merged) and not is_option_line(merged):
                    form = current_activity or schedule_name or ""
                    key = (form, merged, page_idx0)
                    if key not in emitted:
                        out.append({"form_name": form, "field_name": merged, "page": page_idx0 + 1})
                        emitted.add(key)
                i = next_i
                continue

            i += 1

    return out
```
