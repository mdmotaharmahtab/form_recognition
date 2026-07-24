```python
# Observed layouts: (1) TOC-like pages with blue section lists and no field codes; (2) annotated CRF forms with a left/top title
# (colored, larger font) and per-field red bracket codes plus [TYPE: ...] metadata; (3) grid/table forms where one question feeds
# multiple column fields (e.g., timeframe columns). Strategy: carry forward the most prominent top-left title as form_name, anchor
# extraction on red bracket code lines, and recover the nearest human label text by geometry, joining wrapped label lines and
# disambiguating multi-column groups with nearby column headers when needed.

import re
import statistics
from typing import List, Tuple, Dict, Any, Optional


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    # ---------- helpers ----------
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip())

    def is_bracket_line(t: str) -> bool:
        t = (t or "").lstrip()
        return t.startswith("[")

    _META_BRACKET_RE = re.compile(r"^\[(TYPE|VISIBIL|READ-ONLY|REQUIRED|DEFAULT|CALC)\b", re.I)

    def is_meta_bracket(t: str) -> bool:
        t = (t or "").lstrip()
        return bool(_META_BRACKET_RE.match(t))

    # Field code lines are red/colored bracket tokens that are not [TYPE:], [VISIBILITY:], etc.
    # Allow truncated tokens like "[SCANNE" (missing closing bracket due to line wrapping).
    _CODE_BRACKET_RE = re.compile(r"^\[[^\[\]]{2,}$")  # "[SCANNE" style
    _CODE_BRACKET_CLOSED_RE = re.compile(r"^\[[A-Za-z0-9][A-Za-z0-9_/-]{1,}\]$")  # "[LBGLYC]" style

    def is_code_line(ln: Any) -> bool:
        t = (ln.text or "").strip()
        if not t:
            return False
        if not is_bracket_line(t):
            return False
        if is_meta_bracket(t):
            return False
        # Typically codes are colored (non_black True). Be tolerant: accept even if black.
        tt = t.strip()
        if _CODE_BRACKET_CLOSED_RE.match(tt):
            return True
        if _CODE_BRACKET_RE.match(tt):
            return True
        # Some code tokens may contain trailing punctuation or be partially clipped; keep if bracketed and short.
        if len(tt) <= 20 and ":" not in tt:
            return True
        return False

    def looks_like_junk_label(t: str) -> bool:
        t = norm(t)
        if not t:
            return True
        if is_bracket_line(t):
            return True
        if re.fullmatch(r"[\d\W]+", t):
            return True
        # Template row markers (document-specific chrome that is not a question/label itself)
        if re.fullmatch(r"Row\s*\d+\b.*", t, flags=re.I):
            return True
        return False

    def is_labelish(ln: Any) -> bool:
        t = ln.text or ""
        if looks_like_junk_label(t):
            return False
        # Exclude very small meta-like fragments (e.g., lone "on", "c") unless they are part of a wrapped question;
        # wrapping logic handles that via adjacency rather than allowing them as anchors.
        return True

    def cx(ln: Any) -> float:
        return (float(ln.x0) + float(ln.x1)) / 2.0

    def pick_form_title(lines: List[Any]) -> Optional[str]:
        if not lines:
            return None
        sizes = [float(ln.size) for ln in lines if (ln.text or "").strip()]
        if not sizes:
            return None
        med = statistics.median(sizes)
        mx = max(sizes)
        # Favor prominent titles: larger than body and near the top-left.
        min_big = med + (mx - med) * 0.45
        cands = []
        for ln in lines:
            t = norm(ln.text)
            if not t or is_bracket_line(t):
                continue
            if float(ln.y0) > 140:
                continue
            if float(ln.x0) > 170:
                continue
            if float(ln.size) < min_big and float(ln.size) < (med + 2.0):
                continue
            # Mild preference for colored headings (common in samples)
            style_bonus = 0.0
            if getattr(ln, "non_black", False):
                style_bonus -= 8.0
            if getattr(ln, "bold", False):
                style_bonus -= 3.0
            score = (float(ln.y0) * 1.0) + (float(ln.x0) * 0.15) - (float(ln.size) * 2.0) + style_bonus
            cands.append((score, t))
        if not cands:
            return None
        cands.sort(key=lambda x: x[0])
        return cands[0][1]

    def collect_wrapped(lines: List[Any], anchor_idx: int, y_min: float, y_max: float) -> str:
        """Collect a wrapped label around anchor_idx within [y_min, y_max], keeping same column."""
        if anchor_idx < 0 or anchor_idx >= len(lines):
            return ""
        a = lines[anchor_idx]
        ax0 = float(a.x0)
        asz = float(a.size)
        abold = bool(getattr(a, "bold", False))

        # Similar column tolerance scales with font size a bit; keep it loose.
        x_tol = max(18.0, asz * 2.2)
        y_gap = max(11.0, asz * 1.7)

        def compatible(i: int) -> bool:
            ln = lines[i]
            if not is_labelish(ln):
                return False
            t = norm(ln.text)
            if not t:
                return False
            if float(ln.y0) < y_min - 1e-3 or float(ln.y0) > y_max + 1e-3:
                return False
            if abs(float(ln.x0) - ax0) > x_tol:
                return False
            # Size should be similar (wrapped lines usually same size); allow modest drift.
            if abs(float(ln.size) - asz) > max(1.6, asz * 0.28):
                return False
            # Boldness should generally match, but allow mismatch if very close (some wrapped lines lose bold).
            if bool(getattr(ln, "bold", False)) != abold and abs(float(ln.y0) - float(a.y0)) > y_gap:
                return False
            return True

        idxs = [anchor_idx]

        # extend upwards
        i = anchor_idx - 1
        last_y = float(a.y0)
        while i >= 0:
            ln = lines[i]
            if float(ln.y0) < y_min - 1e-3:
                break
            if not compatible(i):
                # stop if we hit a code/meta band near the anchor
                if is_bracket_line(norm(ln.text)):
                    break
                i -= 1
                continue
            if last_y - float(ln.y0) > y_gap * 1.6:
                break
            idxs.append(i)
            last_y = float(ln.y0)
            i -= 1

        # extend downwards
        i = anchor_idx + 1
        last_y = float(a.y0)
        while i < len(lines):
            ln = lines[i]
            if float(ln.y0) > y_max + 1e-3:
                break
            if not compatible(i):
                if is_bracket_line(norm(ln.text)):
                    break
                i += 1
                continue
            if float(ln.y0) - last_y > y_gap * 1.6:
                break
            idxs.append(i)
            last_y = float(ln.y0)
            i += 1

        idxs = sorted(set(idxs))
        parts = [norm(lines[i].text) for i in idxs if norm(lines[i].text)]

        # join with hyphenation handling
        out = ""
        for p in parts:
            if not out:
                out = p
            else:
                if out.endswith("-"):
                    out = out[:-1] + p
                else:
                    out = out + " " + p
        return norm(out)

    def best_label_for_code(lines: List[Any], code_ln: Any, prefer_above: bool = True) -> str:
        cy = float(code_ln.y0)
        cx0 = float(code_ln.x0)
        cxc = cx(code_ln)

        # Search window: labels tend to be within ~120pt vertically.
        y_lo = cy - 140.0
        y_hi = cy + 90.0

        best = None
        for i, ln in enumerate(lines):
            if not is_labelish(ln):
                continue
            ty = float(ln.y0)
            if ty < y_lo or ty > y_hi:
                continue
            # avoid picking far-right option text as label for left codes
            if cx0 < 200.0 and float(ln.x0) > 260.0:
                continue

            # Score: prefer near in y, prefer above for typical single-field blocks.
            dy = ty - cy
            if prefer_above:
                if dy <= 0:
                    vy = abs(dy)
                else:
                    vy = abs(dy) * 2.2
            else:
                vy = abs(dy)

            # Prefer same column x
            vx = abs(cx(ln) - cxc) * 0.35 + abs(float(ln.x0) - cx0) * 0.15

            bonus = 0.0
            if getattr(ln, "bold", False):
                bonus -= 8.0
            if "?" in (ln.text or ""):
                bonus -= 6.0
            # Downweight long instruction paragraphs a bit
            if len(norm(ln.text)) > 130:
                bonus += 18.0
            score = vy + vx + bonus
            if best is None or score < best[0]:
                best = (score, i)

        if best is None:
            return ""

        _, idx = best
        # For single-field blocks, wrapping should stay above the code; allow a small amount below if needed.
        y_max = cy - 6.0 if prefer_above else cy + 40.0
        y_min = max(0.0, cy - 200.0)
        label = collect_wrapped(lines, idx, y_min=y_min, y_max=y_max)
        if not label:
            label = norm(lines[idx].text)
        return label

    def best_col_header(lines: List[Any], code_ln: Any) -> str:
        cy = float(code_ln.y0)
        cxc = cx(code_ln)
        cx0 = float(code_ln.x0)

        best = None
        for i, ln in enumerate(lines):
            if not is_labelish(ln):
                continue
            ty = float(ln.y0)
            if not (0.0 <= cy - ty <= 190.0):
                continue
            # column headers tend to be near the top of a table band; require some x alignment
            if abs(cx(ln) - cxc) > 55.0 and abs(float(ln.x0) - cx0) > 55.0:
                continue
            # Don't use left-side row labels as column header for right columns
            if cx0 > 250.0 and float(ln.x0) < 200.0:
                continue
            # Prefer slightly larger (often 9.2) and closer in y
            score = (cy - ty) + abs(cx(ln) - cxc) * 0.25 - float(ln.size) * 1.2
            if best is None or score < best[0]:
                best = (score, i)
        if best is None:
            return ""
        _, idx = best
        # Column headers are usually single-line; still allow wrapping lightly
        return collect_wrapped(lines, idx, y_min=float(lines[idx].y0) - 2.0, y_max=float(lines[idx].y0) + 18.0) or norm(
            lines[idx].text
        )

    def best_row_label_near_group(lines: List[Any], group_y: float) -> str:
        # Look around the group y; rows often have their question label slightly below the code row.
        y_lo = group_y - 95.0
        y_hi = group_y + 85.0
        best = None
        for i, ln in enumerate(lines):
            if not is_labelish(ln):
                continue
            if float(ln.x0) > 260.0:
                continue
            ty = float(ln.y0)
            if ty < y_lo or ty > y_hi:
                continue
            t = norm(ln.text)
            if not t:
                continue
            # Score: prefer bold/questions and proximity; slight preference to below the code row
            dy = ty - group_y
            vy = abs(dy) * (0.9 if dy >= 0 else 1.1)
            bonus = 0.0
            if getattr(ln, "bold", False):
                bonus -= 10.0
            if "?" in t:
                bonus -= 8.0
            if re.match(r"^\d+[\.\)]\s+", t):
                bonus -= 6.0
            if len(t) > 140:
                bonus += 14.0
            score = vy + abs(float(ln.x0) - 48.0) * 0.08 + bonus
            if best is None or score < best[0]:
                best = (score, i)
        if best is None:
            return ""
        _, idx = best
        return collect_wrapped(lines, idx, y_min=max(0.0, group_y - 140.0), y_max=group_y + 120.0)

    def group_codes_by_y(code_items: List[Tuple[int, Any]]) -> List[List[Tuple[int, Any]]]:
        if not code_items:
            return []
        code_items = sorted(code_items, key=lambda it: float(it[1].y0))
        groups = []
        cur = [code_items[0]]
        last_y = float(code_items[0][1].y0)
        for it in code_items[1:]:
            y = float(it[1].y0)
            if abs(y - last_y) <= 8.5:
                cur.append(it)
            else:
                groups.append(cur)
                cur = [it]
            last_y = y
        groups.append(cur)
        return groups

    # ---------- main ----------
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        title = pick_form_title(lines)
        if title:
            current_form = title

        code_items = [(i, ln) for i, ln in enumerate(lines) if is_code_line(ln)]
        if not code_items:
            continue  # likely TOC/chrome page (no annotated fields)

        # Precompute groupings for multi-column rows
        groups = group_codes_by_y(code_items)

        emitted = set()  # (form, field) per page to avoid accidental duplicates

        for g in groups:
            if len(g) == 1:
                _, code_ln = g[0]
                label = best_label_for_code(lines, code_ln, prefer_above=True)
                if not label:
                    label = best_label_for_code(lines, code_ln, prefer_above=False)
                label = norm(label)
                if not label or looks_like_junk_label(label):
                    continue
                key = (current_form, label)
                if key in emitted:
                    continue
                emitted.add(key)
                out.append({"form_name": current_form, "field_name": label, "page": page_idx0 + 1})
                continue

            # Multi-code row: use a row label plus per-code column header to disambiguate if needed
            group_y = statistics.median([float(ln.y0) for _, ln in g])
            row_label = norm(best_row_label_near_group(lines, group_y))

            # If we can't find a row label, fall back to per-code label recovery.
            col_headers = []
            for _, code_ln in g:
                col_headers.append(norm(best_col_header(lines, code_ln)))

            # Determine if per-code labels would collide; if so, compose with column header.
            per_code_labels = []
            for _, code_ln in g:
                per_code_labels.append(norm(best_label_for_code(lines, code_ln, prefer_above=True)) or "")

            collision = False
            seen = set()
            for lab in per_code_labels:
                if not lab:
                    continue
                if lab in seen:
                    collision = True
                    break
                seen.add(lab)

            for idx_in_g, (_, code_ln) in enumerate(g):
                colh = col_headers[idx_in_g]
                base_label = per_code_labels[idx_in_g] or norm(best_label_for_code(lines, code_ln, prefer_above=False))
                base_label = norm(base_label)

                field = ""
                # Prefer a real row label if present and meaningful
                if row_label and not looks_like_junk_label(row_label):
                    if colh and not looks_like_junk_label(colh):
                        # Compose only when needed: multi-column grids often require header disambiguation.
                        field = f"{row_label} - {colh}"
                    else:
                        field = row_label
                else:
                    # If no row label, try to use base label; if it collides across columns, append col header.
                    if base_label and not looks_like_junk_label(base_label):
                        if collision and colh and not looks_like_junk_label(colh):
                            field = f"{base_label} - {colh}"
                        else:
                            field = base_label
                    elif colh and not looks_like_junk_label(colh):
                        field = colh

                field = norm(field)
                if not field or looks_like_junk_label(field):
                    continue
                key = (current_form, field)
                if key in emitted:
                    continue
                emitted.add(key)
                out.append({"form_name": current_form, "field_name": field, "page": page_idx0 + 1})

    return out
```
