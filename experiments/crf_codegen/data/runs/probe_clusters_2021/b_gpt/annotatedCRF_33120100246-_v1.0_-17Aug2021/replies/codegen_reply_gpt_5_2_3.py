```python
import re
import unicodedata
import statistics
from typing import List, Tuple, Dict, Any, Optional


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
        for ch in s or "":
            if unicodedata.category(ch).startswith("L"):
                return True
        return False

    def is_bold(ln: Any) -> bool:
        v = _get(ln, "bold", None)
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        font = (_get(ln, "font", "") or "") + " " + (_get(ln, "fontname", "") or "")
        font = font.lower()
        if "bold" in font:
            return True
        w = _get(ln, "weight", None)
        if isinstance(w, (int, float)):
            return w >= 600
        return False

    def color_str(ln: Any) -> str:
        c = _get(ln, "color", None)
        if c is None:
            c = _get(ln, "fill", None)
        if c is None:
            c = _get(ln, "stroke", None)
        if isinstance(c, str):
            return c.strip().lower()
        return ""

    def is_non_black(ln: Any) -> bool:
        nb = _get(ln, "non_black", None)
        if isinstance(nb, bool):
            return nb
        c = color_str(ln)
        if not c:
            return False
        if c in {"black", "#000000", "0,0,0"}:
            return False
        return True

    def is_blueish(ln: Any) -> bool:
        c = color_str(ln)
        if not c:
            return False
        if c.startswith("#") and len(c) >= 7:
            hx = c[1:7]
            try:
                r = int(hx[0:2], 16)
                g = int(hx[2:4], 16)
                b = int(hx[4:6], 16)
                return b >= 170 and b >= r + 35 and b >= g + 35
            except Exception:
                return False
        return "blue" in c

    _ROW_RE = re.compile(r"^\s*Row\s*\d+\b", re.IGNORECASE)
    _READONLY_RE = re.compile(r"\bREAD[-\s]?ONLY\b", re.IGNORECASE)
    _VISIBILITY_RE = re.compile(r"\bVISIBILITY\b", re.IGNORECASE)
    _TYPE_RE = re.compile(r"^\s*\[\s*TYPE\b", re.IGNORECASE)

    # wider + allow hyphen (still excludes dots/spaces/colons)
    _CODE_BRACKET_RE = re.compile(r"\[[-A-Za-z0-9_]{2,40}\]")

    def is_row_line(t: str) -> bool:
        return bool(_ROW_RE.match(t or ""))

    def _is_simple_code_token(tok: str) -> bool:
        if not tok or tok[0] != "[" or tok[-1] != "]":
            return False
        inner = tok[1:-1]
        if not inner:
            return False
        if ":" in inner or " " in inner or "\t" in inner:
            return False
        return bool(re.fullmatch(r"[-A-Za-z0-9_]{2,40}", inner))

    def is_marker_only_line(t: str) -> bool:
        tt = (t or "").strip()
        if not tt.startswith("["):
            return False
        up = tt.upper()
        if up.startswith("[TYPE") or up.startswith("[VISIBILITY") or up.startswith("[READ-ONLY"):
            return False
        if not tt.endswith("]"):
            return False
        return _is_simple_code_token(tt)

    def find_inline_codes(t: str) -> List[str]:
        if not t:
            return []
        codes = []
        for m in _CODE_BRACKET_RE.finditer(t):
            tok = m.group(0)
            if _is_simple_code_token(tok):
                inner = tok[1:-1]
                up = inner.upper()
                if up.startswith("TYPE") or up.startswith("VISIBILITY") or up.startswith("READ-ONLY"):
                    continue
                codes.append(inner)
        return codes

    def is_annotation_line_text(t: str) -> bool:
        tt = (t or "").strip()
        if not tt:
            return True
        up = tt.upper()

        if up.startswith("[TYPE"):
            return True
        if up.startswith("[VISIBILITY"):
            return True
        if up.startswith("[READ-ONLY"):
            return True

        if is_marker_only_line(tt):
            return False

        if up in {"ENUMERATION", "ON", "OFF"}:
            return True
        if up.startswith("(VALUES:") or up.startswith("VALUES:"):
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

        shortish = 0
        for tok in toks:
            core = tok.strip().strip(".")
            if not core:
                return False
            if len(core) <= 4:
                shortish += 1
            if not re.fullmatch(r"[A-Za-z0-9/+-]+", core):
                return False

        if shortish / max(1, len(toks)) < 0.85:
            return False

        if not any(any(ch.isalpha() for ch in tok) for tok in toks):
            if not all(re.fullmatch(r"[0-9]+", tok) for tok in toks):
                return False

        return True

    def strip_machine_codes(label: str) -> str:
        s = label or ""
        s = re.sub(r"\s*\[[-A-Za-z0-9_]{2,40}\]\s*", " ", s)
        return norm_ws(s)

    def dedupe_label(label: str) -> str:
        t = norm_ws(label)

        # "X X" exact duplication
        m = re.fullmatch(r"(.{2,120})\s+\1", t, flags=re.IGNORECASE)
        if m:
            t = norm_ws(m.group(1))

        # "X: X ..." prefix duplication
        m = re.match(r"^(.{2,80}?)\s*:\s*(.+)$", t)
        if m:
            p = norm_ws(m.group(1))
            rest = norm_ws(m.group(2))
            if p and rest.lower().startswith(p.lower() + " "):
                t = rest

        # repeated first token sequence at start ("Visit Date Visit Date ...")
        toks = t.split()
        if len(toks) >= 4:
            for k in range(2, min(7, len(toks) // 2 + 1)):
                a = " ".join(toks[:k]).lower()
                b = " ".join(toks[k : 2 * k]).lower()
                if a == b:
                    t = norm_ws(" ".join(toks[k:]))
                    break

        return norm_ws(t)

    def page_stats(lines: List[Any]) -> Dict[str, float]:
        non_empty = [ln for ln in lines if ltext(ln)]
        if not non_empty:
            return {"left": 0.0, "right": 0.0, "width": 1.0, "height": 1.0, "body": 8.0, "big": 12.0}

        non_ann = [ln for ln in non_empty if not is_annotation_line_text(ltext(ln))]
        ref = non_ann if non_ann else non_empty

        left = min(float(_get(ln, "x0", 0.0) or 0.0) for ln in ref)
        right = max(float(_get(ln, "x1", left + 1.0) or (left + 1.0)) for ln in ref)
        width = max(1.0, right - left)
        height = max(1.0, max(float(_get(ln, "y1", 0.0) or 0.0) for ln in non_empty))

        body_sizes = sorted(
            float(_get(ln, "size", 0.0) or 0.0)
            for ln in non_ann
            if 5.5 <= float(_get(ln, "size", 0.0) or 0.0) <= 13.5 and not is_row_line(ltext(ln))
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

    def iter_markers(lines: List[Any]) -> List[Dict[str, Any]]:
        markers: List[Dict[str, Any]] = []
        i = 0
        while i < len(lines):
            ln = lines[i]
            t = ltext(ln)
            up = t.upper()

            # marker-only line, possibly split across up to 3 lines
            if t.startswith("[") and not (up.startswith("[TYPE") or up.startswith("[VISIBILITY") or up.startswith("[READ-ONLY")):
                merged = t
                if not merged.endswith("]"):
                    for k in (1, 2, 3):
                        if i + k >= len(lines):
                            break
                        t2 = ltext(lines[i + k])
                        if not t2:
                            continue
                        merged2 = (merged + t2).replace(" ", "")
                        if "]" in merged2:
                            merged2 = merged2[: merged2.index("]") + 1]
                        if is_marker_only_line(merged2):
                            merged = merged2
                            break

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
                    i += 1
                    continue

            # inline marker(s)
            codes = find_inline_codes(t)
            if codes:
                markers.append(
                    {
                        "idx": i,
                        "inline": True,
                        "code": codes[0],
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
            return False

        if not has_letter(t):
            has_digit = any(ch.isdigit() for ch in t)
            has_other = any((not ch.isdigit()) and (not ch.isspace()) for ch in t)
            if not (has_digit and has_other and len(t) >= 4):
                return False

        return True

    def choose_anchor(lines: List[Any], marker: Dict[str, Any], stats: Dict[str, float]) -> Optional[int]:
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
        body = stats["body"]
        big = stats["big"]

        left_band = max(170.0, 0.30 * width)
        y_window = max(130.0, 10.0 * body)
        dx_window = max(105.0, 0.25 * width)

        def candidate_ok(ln: Any) -> bool:
            t = ltext(ln)
            if not t:
                return False
            if is_annotation_line_text(t) or is_row_line(t):
                return False
            if is_marker_only_line(t):
                return False
            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            sz = float(_get(ln, "size", 0.0) or 0.0)
            # only skip true titles/headings, not large field labels
            if y0 < min(210.0, 0.30 * stats["height"]) and sz >= big:
                if (is_bold(ln) or is_non_black(ln)) and not t.endswith("?"):
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

            if looks_like_options_text(t) and x0 > left + 0.32 * width:
                continue

            length = len(t)
            bold = is_bold(ln)
            nb = is_non_black(ln)

            leftish = x0 <= left + left_band
            if leftish:
                score = 0.0
                score -= 0.80 * dy
                score -= 0.012 * dx
                score += 0.32 * min(length, 180)
                if t.endswith(":"):
                    score += 10.0
                if t.endswith("?"):
                    score += 5.0
                if bold:
                    score += 1.8
                if nb:
                    score -= 0.6  # colored small link-like text tends to be furniture
                if length <= 4 and x0 > left + 0.25 * width:
                    score -= 12.0
                if score > best_score_left:
                    best_score_left = score
                    best_j_left = j

            if dx <= dx_window:
                score = 0.0
                score -= 0.55 * dy
                score += 0.22 * min(length, 140)
                score += 2.0 if x0 <= left + 0.55 * width else 0.0
                if t.endswith(":"):
                    score += 6.0
                if t.endswith("?"):
                    score += 3.0
                if bold:
                    score += 1.2
                if nb and is_blueish(ln) and length <= 30:
                    score -= 3.0
                if looks_like_options_text(t) and x0 > left + 0.35 * width:
                    score -= 18.0
                if score > best_score_near:
                    best_score_near = score
                    best_j_near = j

        if best_j_left is not None:
            return best_j_left
        return best_j_near

    def expand_wrapped_label(lines: List[Any], anchor_j: int, stats: Dict[str, float]) -> str:
        anchor = lines[anchor_j]
        ax = float(_get(anchor, "x0", 0.0) or 0.0)
        ay0 = float(_get(anchor, "y0", 0.0) or 0.0)
        ay1 = float(_get(anchor, "y1", ay0) or ay0)
        asz = float(_get(anchor, "size", stats["body"]) or stats["body"])
        abold = is_bold(anchor)
        ablue = is_blueish(anchor)
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
            if y0 < min(210.0, 0.30 * stats["height"]) and sz >= big:
                if (is_bold(ln) or is_non_black(ln)) and not t.endswith("?"):
                    return False
            if looks_like_options_text(t) and float(_get(ln, "x0", 0.0) or 0.0) > left + 0.32 * width:
                return False
            return True

        def style_compatible(ln: Any) -> bool:
            sz = float(_get(ln, "size", 0.0) or 0.0)
            if sz and abs(sz - asz) > 1.6:
                return False
            # prevent merging headers with row labels
            if is_bold(ln) != abold and abs((sz or asz) - asz) <= 1.0:
                return False
            if is_blueish(ln) != ablue and is_non_black(ln):
                return False
            return True

        def x_compatible(ln: Any) -> bool:
            x0 = float(_get(ln, "x0", 0.0) or 0.0)
            return (x0 >= ax - 22.0) and (x0 <= ax + 95.0)

        included = {anchor_j}

        prev_y0 = ay0
        for j in range(anchor_j - 1, -1, -1):
            ln = lines[j]
            if not ok_line(ln) or not x_compatible(ln) or not style_compatible(ln):
                continue
            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            y1 = float(_get(ln, "y1", y0) or y0)
            gap = prev_y0 - y1
            sz = float(_get(ln, "size", asz) or asz)
            if gap > max(20.0, 2.4 * max(sz, asz)):
                break
            if ay0 - y0 > max(120.0, 10.0 * stats["body"]):
                break
            included.add(j)
            prev_y0 = y0

        prev_y1 = ay1
        for j in range(anchor_j + 1, len(lines)):
            ln = lines[j]
            if not ok_line(ln) or not x_compatible(ln) or not style_compatible(ln):
                continue
            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            gap = y0 - prev_y1
            sz = float(_get(ln, "size", asz) or asz)
            if gap > max(20.0, 2.4 * max(sz, asz)):
                break
            if y0 - ay0 > max(120.0, 10.0 * stats["body"]):
                break
            included.add(j)
            prev_y1 = float(_get(ln, "y1", y0) or y0)

        idxs = sorted(included, key=lambda k: (float(_get(lines[k], "y0", 0.0) or 0.0), float(_get(lines[k], "x0", 0.0) or 0.0)))
        text = norm_ws(" ".join(norm_ws(ltext(lines[k])) for k in idxs))
        return text

    def detect_titles(lines: List[Any], stats: Dict[str, float], markers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not page_has_any_marker(lines):
            return []

        left = stats["left"]
        width = stats["width"]
        height = stats["height"]
        body = stats["body"]

        def is_titleish_line(ln: Any) -> bool:
            t = ltext(ln)
            if not t:
                return False
            if is_annotation_line_text(t) or is_row_line(t) or is_marker_only_line(t):
                return False
            if looks_like_options_text(t):
                return False
            if not has_letter(t):
                return False
            if t.endswith("?"):
                return False

            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            if y0 > min(0.60 * height, 460.0):
                return False

            sz = float(_get(ln, "size", 0.0) or 0.0)
            b = is_bold(ln)
            nb = is_non_black(ln)
            blue = is_blueish(ln)

            if not (sz >= body + 0.8 or b or blue or nb):
                return False

            x0 = float(_get(ln, "x0", 0.0) or 0.0)
            x1 = float(_get(ln, "x1", x0) or x0)
            if x0 > left + 0.68 * width and (x1 - x0) < 0.22 * width and len(t) <= 20:
                return False
            return True

        cands = []
        for i, ln in enumerate(lines):
            if is_titleish_line(ln):
                cands.append((i, ln))

        if not cands:
            return []

        cands.sort(key=lambda p: (float(_get(p[1], "y0", 0.0) or 0.0), float(_get(p[1], "x0", 0.0) or 0.0)))

        blocks: List[Dict[str, Any]] = []
        used = set()

        for i, ln in cands:
            if i in used:
                continue
            t0 = norm_ws(ltext(ln))
            y0 = float(_get(ln, "y0", 0.0) or 0.0)
            y1 = float(_get(ln, "y1", y0) or y0)
            x0 = float(_get(ln, "x0", 0.0) or 0.0)
            x1 = float(_get(ln, "x1", x0) or x0)
            sz0 = float(_get(ln, "size", 0.0) or 0.0)
            b0 = is_bold(ln)
            blue0 = is_blueish(ln)
            cx0 = (x0 + x1) / 2.0

            parts = [t0]
            used.add(i)
            prev_y1 = y1

            for j, ln2 in cands:
                if j in used:
                    continue
                t2 = norm_ws(ltext(ln2))
                if not t2:
                    continue
                y02 = float(_get(ln2, "y0", 0.0) or 0.0)
                if y02 <= y0:
                    continue
                y12 = float(_get(ln2, "y1", y02) or y02)
                gap = y02 - prev_y1
                if gap > max(20.0, 1.9 * max(sz0, float(_get(ln2, "size", sz0) or sz0))):
                    continue

                sz2 = float(_get(ln2, "size", 0.0) or 0.0)
                if sz0 and sz2 and abs(sz2 - sz0) > 1.7:
                    continue
                if is_bold(ln2) != b0 and sz0 and sz2 and abs(sz2 - sz0) <= 1.0:
                    continue
                if is_blueish(ln2) != blue0 and is_non_black(ln2):
                    continue

                x02 = float(_get(ln2, "x0", 0.0) or 0.0)
                x12 = float(_get(ln2, "x1", x02) or x02)
                cx2 = (x02 + x12) / 2.0
                if not (abs(x02 - x0) <= 55.0 or abs(cx2 - cx0) <= 75.0):
                    continue

                parts.append(t2)
                used.add(j)
                prev_y1 = y12
                x0 = min(x0, x02)
                x1 = max(x1, x12)

            name = norm_ws(" ".join(parts))
            name = strip_machine_codes(name)
            name = dedupe_label(name)
            if not name or not has_letter(name):
                continue

            max_sz = max(float(_get(lines[k], "size", 0.0) or 0.0) for k in range(len(lines)) if k in used) if used else 0.0
            # compute score for this block from its first line
            first_ln = ln
            sz = float(_get(first_ln, "size", 0.0) or 0.0)
            score = 0.0
            score += 2.5 if is_blueish(first_ln) else 0.0
            score += 1.4 if is_bold(first_ln) else 0.0
            score += 0.7 if is_non_black(first_ln) else 0.0
            score += 0.005 * min((x1 - x0), width)
            score += 0.8 * (sz / max(1e-6, body))
            score -= 0.01 * y0

            blocks.append({"name": name, "y0": y0, "y1": prev_y1, "x0": x0, "x1": x1, "score": score, "size": sz})

        # keep blocks that are sufficiently title-like
        kept = []
        for b in blocks:
            # require either topish or styled strongly
            if b["y0"] <= min(260.0, 0.40 * height) or b["size"] >= body + 1.3:
                kept.append(b)
            elif b["score"] >= 2.2:
                kept.append(b)

        kept.sort(key=lambda d: (d["y0"], -d["score"]))
        # de-overlap: keep distinct vertical titles
        final = []
        for b in kept:
            if final and abs(b["y0"] - final[-1]["y0"]) < 14.0 and abs(b["y1"] - final[-1]["y1"]) < 18.0:
                if b["score"] > final[-1]["score"]:
                    final[-1] = b
                continue
            final.append(b)

        return final

    def assign_form_name(titles: List[Dict[str, Any]], anchor_y0: float, fallback: str) -> str:
        if not titles:
            return fallback
        best = None
        best_dy = 1e18
        for t in titles:
            if t["y0"] <= anchor_y0 + 1e-6:
                dy = anchor_y0 - t["y0"]
                if dy < best_dy:
                    best_dy = dy
                    best = t
        if best is None:
            # if nothing above, use earliest title on page
            return titles[0]["name"] or fallback
        return best["name"] or fallback

    results: List[Dict[str, Any]] = []
    current_form_name = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        markers = iter_markers(lines)
        if not markers:
            continue

        stats = page_stats(lines)
        titles = detect_titles(lines, stats, markers)

        # update persistent context using the most topward title if present
        if titles:
            current_form_name = titles[0]["name"] or current_form_name

        seen_on_page = set()

        for marker in markers:
            if is_read_only_near(lines, marker, stats):
                continue

            anchor_j = choose_anchor(lines, marker, stats)
            if anchor_j is None:
                continue

            anchor_ln = lines[anchor_j]
            anchor_y0 = float(_get(anchor_ln, "y0", 0.0) or 0.0)

            label_raw = expand_wrapped_label(lines, anchor_j, stats)
            label = strip_machine_codes(label_raw)
            label = norm_ws(label).strip(" -\u2013\u2014")
            label = dedupe_label(label)

            if not is_label_like(label):
                continue

            if looks_like_options_text(label):
                if is_probable_response_column_line(anchor_ln, stats):
                    continue

            form_name = assign_form_name(titles, anchor_y0, current_form_name)

            key = (form_name, label)
            if key in seen_on_page:
                continue
            seen_on_page.add(key)

            results.append({"form_name": form_name, "field_name": label, "page": page_idx0 + 1})

    return results
```
