```python
import re
import unicodedata
import statistics
from typing import List, Tuple, Dict, Any, Optional


_ROW_RE = re.compile(r"^\s*Row\s*\d+\b", re.IGNORECASE)
_CODE_BRACKET_RE = re.compile(r"\[[A-Za-z0-9_]{2,24}\]")
_READONLY_RE = re.compile(r"\bREAD[-\s]?ONLY\b", re.IGNORECASE)
_VISIBILITY_RE = re.compile(r"\bVISIBILITY\b", re.IGNORECASE)
_TYPE_RE = re.compile(r"^\s*\[\s*TYPE\b", re.IGNORECASE)


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def ltext(ln: Any) -> str:
        return (_get(ln, "text", "") or "").strip()

    def norm_ws(s: str) -> str:
        return " ".join((s or "").strip().split())

    def has_letter(s: str) -> bool:
        for ch in s:
            if unicodedata.category(ch).startswith("L"):
                return True
        return False

    def is_row_line(t: str) -> bool:
        return bool(_ROW_RE.match(t or ""))

    def _is_simple_code_token(tok: str) -> bool:
        # tok is like "[ABC123]" (no spaces/colon)
        if not tok or tok[0] != "[" or tok[-1] != "]":
            return False
        inner = tok[1:-1]
        if not inner:
            return False
        # exclude technical annotations and bracketed prose
        if ":" in inner or " " in inner or "\t" in inner:
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9_]{2,24}", inner))

    def is_marker_only_line(t: str) -> bool:
        tt = (t or "").strip()
        if not tt.startswith("["):
            return False
        if tt.upper().startswith("[TYPE") or tt.upper().startswith("[VISIBILITY") or tt.upper().startswith("[READ-ONLY"):
            return False
        if not tt.endswith("]"):
            return False
        return _is_simple_code_token(tt)

    def find_inline_codes(t: str) -> List[str]:
        # Find bracketed machine codes embedded in text (e.g. "Visit Date [VISDAT]")
        if not t:
            return []
        codes = []
        for m in _CODE_BRACKET_RE.finditer(t):
            tok = m.group(0)
            if _is_simple_code_token(tok):
                codes.append(tok[1:-1])
        return codes

    def is_annotation_line_text(t: str) -> bool:
        tt = (t or "").strip()
        if not tt:
            return True
        up = tt.upper()

        # Explicit technical blocks
        if up.startswith("[TYPE"):
            return True
        if up.startswith("[VISIBILITY"):
            return True
        if up.startswith("[READ-ONLY"):
            return True

        # Marker-only IDs are NOT annotation (we use them as field anchors)
        if is_marker_only_line(tt):
            return False

        # Continuation fragments of technical blocks
        if up in {"ENUMERATION", "ON", "OFF"}:
            return True
        if up.startswith("(VALUES:"):
            return True
        if up.startswith("VALUES:"):
            return True

        return False

    def looks_like_options_text(t: str) -> bool:
        tt = norm_ws(t)
        if not tt:
            return False
        if tt.endswith(":"):
            return False
        if re.search(r"[\[\]():;,]", tt):
            return False

        toks = [x for x in re.split(r"\s+", tt) if x]
        if len(toks) < 2 or len(toks) > 7:
            return False

        # Option tokens are typically very short words/numbers
        shortish = 0
        for tok in toks:
            core = tok.strip().strip(".")
            if not core:
                return False
            if len(core) <= 4:
                shortish += 1
            # tokens should be simple (letters/digits or common separators)
            if not re.fullmatch(r"[A-Za-z0-9/+-]+", core):
                return False

        if shortish / max(1, len(toks)) < 0.85:
            return False

        # Must have at least one letter OR be a small numeric rating row (e.g. "0 1 2 3 4")
        if not any(any(ch.isalpha() for ch in tok) for tok in toks):
            if not all(re.fullmatch(r"[0-9]+", tok) for tok in toks):
                return False

        return True

    def strip_machine_codes(label: str) -> str:
        # Remove bracketed machine codes anywhere, but keep ordinary bracketed prose (rare here).
        s = label or ""
        # remove simple codes like [VISDAT]
        s = re.sub(r"\s*\[[A-Za-z0-9_]{2,24}\]\s*", " ", s)
        s = norm_ws(s)
        return s

    def page_stats(lines: List[Any]) -> Dict[str, float]:
        non_empty = [ln for ln in lines if ltext(ln)]
        if not non_empty:
            return {"left": 0.0, "right": 0.0, "width": 1.0, "height": 1.0, "body": 8.0, "big": 12.0}

        non_ann = [ln for ln in non_empty if not is_annotation_line_text(ltext(ln))]
        ref = non_ann if non_ann else non_empty

        left = min(float(_get(ln, "x0", 0.0) or 0.0) for ln in ref)
        right = max(float(_get(ln, "x1", left + 1.0) or (left + 1.0)) for ln in ref)
        width = max(1.0, right - left)
        height = max(1.0, max(float(_get(ln, "y1", 0.0) or 0.0) for ln in ref))

        body_sizes = sorted(
            float(_get(ln, "size", 0.0) or 0.0)
            for ln in non_ann
            if 5.5 <= float(_get(ln, "size", 0.0) or 0.0) <= 12.5 and not is_row_line(ltext(ln))
        )
        if body_sizes:
            body = float(statistics.median(body_sizes))
        else:
            sizes = [float(_get(ln, "size", 8.0) or 8.0) for ln in ref]
            body = float(statistics.median(sizes)) if sizes else 8.0

        big = max(body * 1.35, body + 2.5)
        return {"left": left, "right": right, "width": width, "height": height, "body": body, "big": big}

    def is_probable_response_column_line(ln: Any, stats: Dict[str, float]) -> bool:
        x0 = float(_get(ln, "x0", 0.0) or 0.0)
        return x0 > stats["left"] + 0.35 * stats["width"]

    def page_has_any_marker(lines: List[Any]) -> bool:
        for ln in lines:
            t = ltext(ln)
            if is_marker_only_line(t):
                return True
            if find_inline_codes(t):
                return True
        return False

    def detect_form_title(lines: List[Any], stats: Dict[str, float]) -> str:
        if not page_has_any_marker(lines):
            return ""

        left = stats["left"]
        width = stats["width"]
        height = stats["height"]
        body = stats["body"]
        big = stats["big"]

        top_limit = min(220.0, 0.30 * height + 1e-6)

        cands = []
        for i, ln in enumerate(lines):
            t = ltext(ln)
            if not t:
                continue
            if is_annotation_line_text(t) or is_row_line(t):
                continue
            if is_marker_only_line(t):
                continue
            if looks_like_options_text(t) and is_probable_response_column_line(ln, stats):
                continue

            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            sz = float(_get(ln, "size", 0.0) or 0.0)
            if y0 > top_limit:
                continue

            # title tends to be larger than body; keep some slack for "blue header" titles
            if sz < max(body + 2.0, big * 0.92):
                continue

            # Avoid picking narrow table headers in the right half
            x0 = float(_get(ln, "x0", 0.0) or 0.0)
            if x0 > left + 0.60 * width and len(t) <= 18:
                continue

            if not has_letter(t):
                continue

            cands.append((i, ln))

        if not cands:
            return ""

        # Prefer largest size; then higher on page; then nearer left (but allow centered)
        cands.sort(key=lambda p: (-float(_get(p[1], "size", 0.0) or 0.0), float(_get(p[1], "y0", 0.0) or 0.0), float(_get(p[1], "x0", 0.0) or 0.0)))
        best_i, best = cands[0]

        bx0 = float(_get(best, "x0", 0.0) or 0.0)
        by0 = float(_get(best, "y0", 0.0) or 0.0)
        by1 = float(_get(best, "y1", by0) or by0)
        bsz = float(_get(best, "size", 0.0) or 0.0)
        bcx = (float(_get(best, "x0", 0.0) or 0.0) + float(_get(best, "x1", 0.0) or 0.0)) / 2.0

        parts = [norm_ws(ltext(best))]
        y_end = by1

        # Join wrapped title lines: similar size, close vertical gap, similar left OR center
        for i, ln in cands[1:]:
            if i == best_i:
                continue
            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            if y0 <= by0:
                continue
            if y0 - y_end > max(18.0, 1.9 * bsz):
                continue

            sz = float(_get(ln, "size", 0.0) or 0.0)
            if abs(sz - bsz) > 1.3:
                continue

            x0 = float(_get(ln, "x0", 0.0) or 0.0)
            cx = (float(_get(ln, "x0", 0.0) or 0.0) + float(_get(ln, "x1", 0.0) or 0.0)) / 2.0
            if not (abs(x0 - bx0) <= 40.0 or abs(cx - bcx) <= 55.0):
                continue

            tt = norm_ws(ltext(ln))
            if tt and not is_annotation_line_text(tt) and not is_marker_only_line(tt):
                parts.append(tt)
                y_end = float(_get(ln, "y1", y0) or y0)

        return norm_ws(" ".join(parts))

    def iter_markers(lines: List[Any]) -> List[Dict[str, Any]]:
        markers: List[Dict[str, Any]] = []
        i = 0
        while i < len(lines):
            ln = lines[i]
            t = ltext(ln)

            # Marker-only line (potentially split across lines)
            if t.startswith("[") and not t.upper().startswith("[TYPE") and not t.upper().startswith("[VISIBILITY") and not t.upper().startswith("[READ-ONLY"):
                t1 = t
                # Merge split marker lines like "[SCANNE" + "R]"
                if (not t1.endswith("]")) and (i + 1 < len(lines)):
                    ln2 = lines[i + 1]
                    t2 = ltext(ln2)
                    if t2 and ("]" in t2):
                        merged = (t1 + t2).replace(" ", "")
                        # normalize to something like "[CODE]"
                        if merged.startswith("[") and "]" in merged:
                            merged = merged[: merged.index("]") + 1]
                        if is_marker_only_line(merged):
                            markers.append(
                                {
                                    "idx": i,
                                    "inline": False,
                                    "code": merged[1:-1],
                                    "x0": float(_get(ln, "x0", 0.0) or 0.0),
                                    "x1": float(_get(ln, "x1", 0.0) or 0.0),
                                    "y0": float(_get(ln, "y0", 0.0) or 0.0),
                                    "y1": float(_get(ln, "y1", 0.0) or 0.0),
                                }
                            )
                            i += 2
                            continue

                if is_marker_only_line(t1):
                    markers.append(
                        {
                            "idx": i,
                            "inline": False,
                            "code": t1[1:-1],
                            "x0": float(_get(ln, "x0", 0.0) or 0.0),
                            "x1": float(_get(ln, "x1", 0.0) or 0.0),
                            "y0": float(_get(ln, "y0", 0.0) or 0.0),
                            "y1": float(_get(ln, "y1", 0.0) or 0.0),
                        }
                    )
                    i += 1
                    continue

            # Inline marker(s) inside a normal text line
            codes = find_inline_codes(t)
            if codes:
                markers.append(
                    {
                        "idx": i,
                        "inline": True,
                        "code": codes[0],  # one marker event is enough to treat line as a field anchor
                        "x0": float(_get(ln, "x0", 0.0) or 0.0),
                        "x1": float(_get(ln, "x1", 0.0) or 0.0),
                        "y0": float(_get(ln, "y0", 0.0) or 0.0),
                        "y1": float(_get(ln, "y1", 0.0) or 0.0),
                    }
                )

            i += 1

        return markers

    def is_read_only_near(lines: List[Any], marker: Dict[str, Any], stats: Dict[str, float]) -> bool:
        mx = (marker["x0"] + marker["x1"]) / 2.0
        my = marker["y0"]
        y_win = max(55.0, 7.0 * stats["body"])
        x_win = max(220.0, 0.40 * stats["width"])

        for ln in lines:
            t = ltext(ln)
            if not t:
                continue
            up = t.upper()
            if "[READ-ONLY" in up or _READONLY_RE.search(t):
                x0 = float(_get(ln, "x0", 0.0) or 0.0)
                x1 = float(_get(ln, "x1", 0.0) or 0.0)
                cx = (x0 + x1) / 2.0
                y0 = float(_get(ln, "y0", 0.0) or 0.0)
                if abs(y0 - my) <= y_win and abs(cx - mx) <= x_win:
                    return True
        return False

    def is_label_like(label: str) -> bool:
        t = norm_ws(label)
        if not t:
            return False
        if t.startswith("["):
            return False
        if len(t) < 2:
            return False
        if is_row_line(t):
            return False
        if _TYPE_RE.match(t) or _VISIBILITY_RE.search(t) or _READONLY_RE.search(t):
            return False
        if looks_like_options_text(t):
            # options-only text is not a field label
            return False

        # Avoid returning pure numeric / symbol fragments
        if not has_letter(t):
            has_digit = any(ch.isdigit() for ch in t)
            has_other = any((not ch.isdigit()) and (not ch.isspace()) for ch in t)
            if not (has_digit and has_other and len(t) >= 4):
                return False

        return True

    def choose_anchor(lines: List[Any], marker: Dict[str, Any], stats: Dict[str, float]) -> Optional[int]:
        # Inline marker: the label is on the same line (after stripping codes)
        if marker.get("inline", False):
            j = int(marker["idx"])
            if 0 <= j < len(lines):
                t = strip_machine_codes(ltext(lines[j]))
                if t and not is_annotation_line_text(t) and not is_row_line(t):
                    return j

        my = float(marker["y0"])
        mx = (float(marker["x0"]) + float(marker["x1"])) / 2.0
        left = stats["left"]
        width = stats["width"]
        big = stats["big"]
        body = stats["body"]

        left_band = max(170.0, 0.30 * width)
        y_window = max(120.0, 9.0 * body)
        dx_window = max(95.0, 0.22 * width)

        def candidate_ok(ln: Any) -> bool:
            t = ltext(ln)
            if not t:
                return False
            if is_annotation_line_text(t) or is_row_line(t):
                return False
            if is_marker_only_line(t):
                return False
            # skip obvious titles/headings
            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            sz = float(_get(ln, "size", 0.0) or 0.0)
            if sz >= big and y0 < min(200.0, 0.30 * stats["height"]):
                return False
            return True

        best_j_left = None
        best_score_left = -1e18

        best_j_near = None
        best_score_near = -1e18

        for j, ln in enumerate(lines):
            if not candidate_ok(ln):
                continue

            t = ltext(ln)
            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            if abs(y0 - my) > y_window:
                continue

            x0 = float(_get(ln, "x0", 0.0) or 0.0)
            x1 = float(_get(ln, "x1", x0) or x0)
            cx = (x0 + x1) / 2.0
            dx = abs(cx - mx)
            dy = abs(y0 - my)

            # Option-like text is only plausible as a label if it sits in the left question column
            if looks_like_options_text(t) and x0 > left + 0.32 * width:
                continue

            length = len(t)
            non_black = bool(_get(ln, "non_black", False))

            # Scoring for left-question anchors (preferred)
            leftish = x0 <= left + left_band
            if leftish:
                score = 0.0
                score -= 0.80 * dy
                score -= 0.01 * dx
                score += 0.30 * min(length, 160)
                if t.endswith(":"):
                    score += 10.0
                if not non_black:
                    score += 2.5
                # penalize tiny right-side tokens even if they slipped in
                if length <= 4 and x0 > left + 0.25 * width:
                    score -= 12.0
                if score > best_score_left:
                    best_score_left = score
                    best_j_left = j

            # Fallback scoring near marker column (for above-field labels in grids/tables)
            if dx <= dx_window:
                score = 0.0
                score -= 0.55 * dy
                score += 0.22 * min(length, 120)
                # prefer being not too far right unless necessary
                score += 2.0 if x0 <= left + 0.55 * width else 0.0
                if not non_black:
                    score += 1.5
                # penalize option-like content in response area
                if looks_like_options_text(t) and x0 > left + 0.35 * width:
                    score -= 18.0
                if score > best_score_near:
                    best_score_near = score
                    best_j_near = j

        # Prefer left anchor whenever we have one
        if best_j_left is not None:
            return best_j_left
        return best_j_near

    def expand_wrapped_label(lines: List[Any], anchor_j: int, stats: Dict[str, float]) -> str:
        anchor = lines[anchor_j]
        ax = float(_get(anchor, "x0", 0.0) or 0.0)
        ay0 = float(_get(anchor, "y0", 0.0) or 0.0)
        ay1 = float(_get(anchor, "y1", ay0) or ay0)
        asz = float(_get(anchor, "size", stats["body"]) or stats["body"])
        big = stats["big"]
        left = stats["left"]
        width = stats["width"]

        def ok_line(ln: Any) -> bool:
            t = ltext(ln)
            if not t:
                return False
            if is_annotation_line_text(t) or is_row_line(t):
                return False
            if is_marker_only_line(t):
                return False
            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            sz = float(_get(ln, "size", 0.0) or 0.0)
            if sz >= big and y0 < min(200.0, 0.30 * stats["height"]):
                return False
            # Option-like fragments in response column are not part of the label block
            if looks_like_options_text(t) and float(_get(ln, "x0", 0.0) or 0.0) > left + 0.32 * width:
                return False
            return True

        def x_compatible(ln: Any) -> bool:
            # allow indent drift for wraps; widen tolerance to catch long multi-line questions
            x0 = float(_get(ln, "x0", 0.0) or 0.0)
            return (x0 >= ax - 22.0) and (x0 <= ax + 95.0)

        included = {anchor_j}

        # Upward
        prev_y0 = ay0
        for j in range(anchor_j - 1, -1, -1):
            ln = lines[j]
            if not ok_line(ln) or not x_compatible(ln):
                continue
            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            y1 = float(_get(ln, "y1", y0) or y0)
            gap = prev_y0 - y1
            if gap > max(20.0, 2.4 * max(float(_get(ln, "size", asz) or asz), asz)):
                break
            if ay0 - y0 > max(120.0, 10.0 * stats["body"]):
                break
            included.add(j)
            prev_y0 = y0

        # Downward
        prev_y1 = ay1
        for j in range(anchor_j + 1, len(lines)):
            ln = lines[j]
            if not ok_line(ln) or not x_compatible(ln):
                continue
            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            gap = y0 - prev_y1
            if gap > max(20.0, 2.4 * max(float(_get(ln, "size", asz) or asz), asz)):
                break
            if y0 - ay0 > max(120.0, 10.0 * stats["body"]):
                break
            included.add(j)
            prev_y1 = float(_get(ln, "y1", y0) or y0)

        # Reading order for the block
        idxs = sorted(included, key=lambda k: (float(_get(lines[k], "y0", 0.0) or 0.0), float(_get(lines[k], "x0", 0.0) or 0.0)))
        text = norm_ws(" ".join(norm_ws(ltext(lines[k])) for k in idxs))
        return text

    results: List[Dict[str, Any]] = []
    current_form_name = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        markers = iter_markers(lines)
        if not markers:
            continue

        stats = page_stats(lines)

        # Update form title context if this is a field-bearing page
        title = detect_form_title(lines, stats)
        if title:
            current_form_name = title

        seen_on_page = set()

        for marker in markers:
            # Skip read-only/display-only fields (structural exclusion via nearby technical annotation)
            if is_read_only_near(lines, marker, stats):
                continue

            anchor_j = choose_anchor(lines, marker, stats)
            if anchor_j is None:
                continue

            label_raw = expand_wrapped_label(lines, anchor_j, stats)
            label = strip_machine_codes(label_raw)

            # Clean common trailing artifacts after code removal
            label = norm_ws(label).strip(" -\u2013\u2014")
            if not is_label_like(label):
                continue

            # Extra guard: if label still looks like a response options row and sits in response column, drop it
            if looks_like_options_text(label):
                ln = lines[anchor_j]
                if is_probable_response_column_line(ln, stats):
                    continue

            key = (current_form_name, label)
            if key in seen_on_page:
                continue
            seen_on_page.add(key)

            results.append(
                {
                    "form_name": current_form_name,
                    "field_name": label,
                    "page": page_idx0 + 1,
                }
            )

    return results
```
