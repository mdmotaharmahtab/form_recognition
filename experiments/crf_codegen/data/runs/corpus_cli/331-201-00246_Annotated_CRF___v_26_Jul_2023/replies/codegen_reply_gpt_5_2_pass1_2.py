import re
import statistics
import unicodedata
from typing import List, Tuple, Dict, Optional


_CODE_RE = re.compile(r"^\[(?=[A-Za-z0-9]{2,}\]$)(?=.*[A-Za-z])[A-Za-z0-9]+\]$")
_PAGE_RE = re.compile(r"^Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)
_ENUM_OPT_RE = re.compile(r"^\d+\s*[\.\)]\s*")


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    seen = set()

    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        # Page geometry proxies
        page_w = max((ln.x1 for ln in lines), default=800.0)
        sizes = [ln.size for ln in lines if getattr(ln, "size", 0) and ln.text]
        med_size = statistics.median(sizes) if sizes else 9.0

        # Mark "option bands" (rows with multiple short items, typically answer choices or headers)
        option_like_idx = _compute_option_like_lines(lines, page_w)

        # Update form title if a prominent top-left title is present
        title = _detect_form_title(lines, med_size)
        if title:
            current_form = title

        # Build column header text clusters near top band (used to disambiguate matrix/table columns)
        col_headers = _build_column_headers(lines, page_w, med_size)

        # Collect field code lines (bracket codes; may be non-black or black depending on rendering)
        code_indices = [i for i, ln in enumerate(lines) if _is_field_code_line(ln)]

        # New: handle layouts that carry fields but have no bracket code lines in extracted text
        if not code_indices:
            labels = _extract_fields_when_no_codes(lines, page_w, med_size)
            for label in labels:
                label = _clean_label(label)
                if not label:
                    continue
                rec = {"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1}
                key = (rec["page"], rec["form_name"], rec["field_name"])
                if key in seen:
                    continue
                seen.add(key)
                out.append(rec)
            continue

        for ci in code_indices:
            code_ln = lines[ci]

            # Skip read-only fields when explicitly marked nearby
            if _is_readonly_marked(ci, lines):
                continue

            label = _find_label_for_code(ci, lines, option_like_idx, page_w, med_size)
            if not label:
                continue

            label = _clean_label(label)
            if not label:
                continue

            # If the field is in a right-side column, append the closest column header (to avoid duplicates)
            if code_ln.x0 > 0.28 * page_w:
                hdr = _closest_col_header(col_headers, code_ln.x0)
                if hdr:
                    hdr = _clean_label(hdr)
                    if hdr and hdr.lower() not in label.lower():
                        label = _clean_label(label + " " + hdr)

            rec = {"form_name": current_form or "", "field_name": label, "page": page_idx0 + 1}
            key = (rec["page"], rec["form_name"], rec["field_name"])
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)

    return out


def _is_field_code_line(ln) -> bool:
    if not getattr(ln, "text", ""):
        return False
    t = ln.text.strip()
    if not _CODE_RE.match(t):
        return False
    return True


def _is_technical_marker(ln) -> bool:
    t = (ln.text or "").strip()
    if not t:
        return True
    if _PAGE_RE.match(t):
        return True
    if t.startswith("[") and ":" in t[:20]:
        return True
    if t.startswith("(") and ":" in t[:30]:
        return True
    return False


def _has_letter(s: str) -> bool:
    for ch in s:
        if unicodedata.category(ch).startswith("L"):
            return True
    return False


def _looks_like_furniture(ln) -> bool:
    t = (ln.text or "").strip()
    if not t:
        return True
    if _PAGE_RE.match(t):
        return True
    return False


def _detect_form_title(lines, med_size: float) -> str:
    # Prominent form titles are typically top-left, non-black (e.g., blue), and distinctly larger.
    candidates = []
    for ln in lines:
        if not ln.text:
            continue
        if ln.y0 > 230:
            continue
        if ln.x0 > 170:
            continue
        if ln.text.strip().startswith("["):
            continue
        if _looks_like_furniture(ln):
            continue
        if ln.size >= max(14.0, med_size + 4.0) and getattr(ln, "non_black", False):
            candidates.append(ln)

    if not candidates:
        return ""

    # Prefer largest font, then highest on page (smallest y)
    best = max(candidates, key=lambda l: (l.size, -l.y0))
    return (best.text or "").strip()


def _compute_option_like_lines(lines, page_w: float) -> set:
    # Group by approximate y; mark groups with multiple short tokens on same row in mid/right columns.
    buckets = {}
    for i, ln in enumerate(lines):
        t = (ln.text or "").strip()
        if not t or t.startswith("["):
            continue
        if _looks_like_furniture(ln):
            continue
        # Short, token-like strings
        if len(t) > 14:
            continue
        if ln.x0 < 0.35 * page_w:
            continue
        yb = int(round(ln.y0 / 3.0))
        buckets.setdefault(yb, []).append(i)

    opt = set()
    for _, idxs in buckets.items():
        if len(idxs) >= 2:
            for i in idxs:
                opt.add(i)
    return opt


def _build_column_headers(lines, page_w: float, med_size: float) -> List[Tuple[float, str]]:
    # Header band near top: moderate font (slightly larger than body), not bracketed, not huge titles.
    header_lines = []
    for ln in lines:
        t = (ln.text or "").strip()
        if not t or t.startswith("["):
            continue
        if ln.y0 > 175:
            continue
        if _looks_like_furniture(ln):
            continue
        if ln.size < (med_size + 0.8):
            continue
        if ln.size > (med_size + 5.5):
            continue
        header_lines.append(ln)

    # Cluster by x0 (column) within tolerance; then join within cluster by y.
    header_lines.sort(key=lambda l: (l.x0, l.y0))
    clusters: List[List] = []
    for ln in header_lines:
        placed = False
        for cl in clusters:
            if abs(cl[0].x0 - ln.x0) <= 35:
                cl.append(ln)
                placed = True
                break
        if not placed:
            clusters.append([ln])

    col_headers = []
    for cl in clusters:
        cl.sort(key=lambda l: l.y0)
        txt = _join_wrapped([c.text.strip() for c in cl if c.text and c.text.strip()])
        if txt and (len(txt) > 1) and (_has_letter(txt) or len(txt) >= 4):
            # Use cluster x as representative
            col_headers.append((statistics.median([c.x0 for c in cl]), txt))

    # Keep only distinct headers by text
    dedup = {}
    for x, txt in col_headers:
        k = txt.lower()
        if k not in dedup or abs(dedup[k][0] - x) > 15:
            dedup[k] = (x, txt)
    return sorted(dedup.values(), key=lambda xt: xt[0])


def _closest_col_header(col_headers: List[Tuple[float, str]], x: float) -> str:
    if not col_headers:
        return ""
    best = min(col_headers, key=lambda xt: abs(xt[0] - x))
    if abs(best[0] - x) > 140:
        return ""
    return best[1]


def _is_readonly_marked(code_idx: int, lines: list) -> bool:
    code_ln = lines[code_idx]
    # Look below for red "Read-only field" marker near same column
    y0 = code_ln.y0
    for j in range(code_idx + 1, min(len(lines), code_idx + 20)):
        ln = lines[j]
        if ln.y0 - y0 > 90:
            break
        if not getattr(ln, "non_black", False):
            continue
        if abs(ln.x0 - code_ln.x0) > 110:
            continue
        t = (ln.text or "").strip().lower()
        if "read-only" in t or "read only" in t:
            return True
    return False


def _find_label_for_code(code_idx: int, lines: list, option_like_idx: set, page_w: float, med_size: float) -> str:
    code_ln = lines[code_idx]
    code_y = code_ln.y0

    def is_human_candidate(i: int) -> bool:
        ln = lines[i]
        if not ln.text:
            return False
        t = ln.text.strip()
        if not t or t.startswith("["):
            return False
        if _looks_like_furniture(ln):
            return False
        if _is_technical_marker(ln):
            return False
        if i in option_like_idx:
            return False
        # Exclude far-right tiny tokens (typically options) unless it's a longer phrase
        if ln.x0 > 0.55 * page_w and len(t) <= 10:
            return False
        # Exclude pure punctuation / bullets
        stripped = "".join(ch for ch in t if unicodedata.category(ch)[0] not in ("P", "Z"))
        if not stripped:
            return False
        return True

    # Primary window
    win1 = 130 if code_ln.x0 > 0.25 * page_w else 110
    anchor = _pick_anchor(code_idx, lines, is_human_candidate, page_w, code_ln.x0, win1)

    # If no anchor and code is left-aligned, broaden search to handle long option lists between label and code.
    if anchor is None and code_ln.x0 <= 0.22 * page_w:
        anchor = _pick_anchor(code_idx, lines, is_human_candidate, page_w, code_ln.x0, 470)

    if anchor is None:
        # Fallback: nearest above human line anywhere reasonably close
        anchor = _pick_anchor(code_idx, lines, is_human_candidate, page_w, code_ln.x0, 220, relax_x=True)

    if anchor is None:
        return ""

    # Collect wrapped label lines around anchor (mostly above; sometimes label spans multiple lines)
    label_lines = _collect_wrapped_label(anchor, code_idx, lines, is_human_candidate, option_like_idx, med_size)
    label = _join_wrapped([ln.text.strip() for ln in label_lines])

    # If we accidentally picked a header-like label far above, try to refine by choosing the last candidate in the same x lane
    if label and (code_y - lines[anchor].y0) > 200 and code_ln.x0 <= 0.22 * page_w:
        # Try last left-lane candidate before the code, excluding option-like
        refined = None
        for i in range(code_idx - 1, -1, -1):
            ln = lines[i]
            if code_y - ln.y0 > 470:
                break
            if not is_human_candidate(i):
                continue
            if ln.x0 > 0.35 * page_w:
                continue
            refined = i
            break
        if refined is not None and refined != anchor:
            label_lines = _collect_wrapped_label(refined, code_idx, lines, is_human_candidate, option_like_idx, med_size)
            label = _join_wrapped([ln.text.strip() for ln in label_lines])

    # Basic sanity
    label = _clean_label(label)
    if not label:
        return ""
    if not _has_letter(label) and len(label) < 6:
        return ""
    return label


def _pick_anchor(
    code_idx: int,
    lines: list,
    is_human_candidate,
    page_w: float,
    code_x: float,
    win_y: float,
    relax_x: bool = False,
) -> Optional[int]:
    code_y = lines[code_idx].y0
    best_i = None
    best_score = None

    for i in range(code_idx - 1, -1, -1):
        ln = lines[i]
        dy = code_y - ln.y0
        if dy < 0:
            continue
        if dy > win_y:
            break
        if not is_human_candidate(i):
            continue

        # Prefer left-side labels for right-column codes; prefer same-lane for left codes.
        if not relax_x:
            if code_x <= 0.22 * page_w:
                if ln.x0 > 0.40 * page_w:
                    continue
            else:
                if ln.x0 > 0.45 * page_w:
                    continue

        # Score: closer vertically; slight preference for left margin labels when code is right-side
        x_pref = 0.0
        if code_x > 0.25 * page_w and ln.x0 < 0.30 * page_w:
            x_pref = -10.0
        score = dy + 0.03 * abs(ln.x0 - min(code_x, 0.30 * page_w)) + x_pref

        if best_score is None or score < best_score:
            best_score = score
            best_i = i

    return best_i


def _collect_wrapped_label(
    anchor_idx: int,
    code_idx: int,
    lines: list,
    is_human_candidate,
    option_like_idx: set,
    med_size: float,
) -> List:
    anchor = lines[anchor_idx]
    ax = anchor.x0
    asz = anchor.size

    def size_sim(a: float, b: float) -> bool:
        return abs(a - b) <= 2.2 or (min(a, b) > 0 and max(a, b) / min(a, b) <= 1.22)

    # Expand upward
    start = anchor_idx
    for i in range(anchor_idx - 1, -1, -1):
        ln = lines[i]
        if not is_human_candidate(i):
            continue
        if i in option_like_idx:
            continue
        if anchor.y0 - ln.y0 > 18:
            break
        if abs(ln.x0 - ax) > 28:
            break
        if not size_sim(ln.size, asz):
            break
        start = i

    # Expand downward but stop before code and before big vertical gaps
    end = anchor_idx
    for i in range(anchor_idx + 1, min(code_idx, len(lines))):
        ln = lines[i]
        if ln.text and ln.text.strip().startswith("["):
            break
        if i in option_like_idx:
            continue
        if not is_human_candidate(i):
            continue
        if ln.y0 - lines[end].y0 > 18:
            break
        if abs(ln.x0 - ax) > 28:
            break
        # Allow label wrap even if size differs slightly, but stay near body
        if ln.size > max(med_size + 6.5, asz + 5.0):
            break
        end = i

    return [lines[i] for i in range(start, end + 1)]


def _join_wrapped(parts: List[str]) -> str:
    parts = [p.strip() for p in parts if p and p.strip()]
    if not parts:
        return ""
    out = parts[0]
    for p in parts[1:]:
        if out.endswith("-") and p and p[0].isalpha():
            out = out[:-1] + p
        else:
            out = out + " " + p
    return out


def _clean_label(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # Remove leading bullets and similar markers
    s = re.sub(r"^[\u2022\u00b7\-\*\u25aa\u25cf]+\s*", "", s).strip()
    # Remove trailing colon commonly used in prompts
    if s.endswith(":") and _has_letter(s):
        s = s[:-1].rstrip()
    # Drop solitary punctuation
    if not s or re.fullmatch(r"[\W_]+", s, flags=re.UNICODE):
        return ""
    return s


def _extract_fields_when_no_codes(lines: list, page_w: float, med_size: float) -> List[str]:
    """
    Handle pages that include a prompt + option list or a header row naming fields,
    but have no bracketed code markers in extracted text.
    """
    def is_prompt_like(ln) -> bool:
        t = (ln.text or "").strip()
        if not t:
            return False
        if t.startswith("["):
            return False
        if _looks_like_furniture(ln):
            return False
        if _is_technical_marker(ln):
            return False
        if not _has_letter(t):
            return False
        return True

    # 1) Prompt ending with ":" with a dense option list below (common for dropdowns)
    best_colon_prompt = None
    best_support = 0
    for ln in lines:
        if not is_prompt_like(ln):
            continue
        t = ln.text.strip()
        if ln.y0 > 230:
            continue
        if ln.x0 > 0.45 * page_w:
            continue
        if not t.endswith(":"):
            continue

        # Count option-like lines below, typically in a right lane and clustered by x
        opts = []
        for ln2 in lines:
            if ln2.y0 <= ln.y0 + 14:
                continue
            if ln2.y0 - ln.y0 > 720:
                continue
            if not is_prompt_like(ln2):
                continue
            if ln2.x0 < 0.25 * page_w:
                continue
            txt2 = ln2.text.strip()
            if len(txt2) < 2:
                continue
            opts.append(ln2)

        if len(opts) < 6:
            continue

        # Require a stable right-lane column (avoid random paragraph text)
        xs = [o.x0 for o in opts]
        if statistics.pstdev(xs) > 65:
            continue

        support = len(opts)
        if support > best_support:
            best_support = support
            best_colon_prompt = ln

    if best_colon_prompt is not None:
        return [(best_colon_prompt.text or "").strip()]

    # 2) Header row with multiple short field names + enumerated option text below (e.g., behavior severity choices)
    header_candidates = []
    for ln in lines:
        if not is_prompt_like(ln):
            continue
        t = ln.text.strip()
        if ln.y0 > 165:
            continue
        if len(t) < 3 or len(t) > 60:
            continue
        # avoid capturing big section titles; those are handled as form titles
        if ln.size >= max(14.0, med_size + 4.0):
            continue
        header_candidates.append(ln)

    # group by y row
    rows: Dict[int, List] = {}
    for ln in header_candidates:
        yk = int(round(ln.y0 / 4.0))
        rows.setdefault(yk, []).append(ln)

    # pick the densest row with at least 2 headers
    best_row = None
    best_n = 0
    for yk, lns in rows.items():
        if len(lns) >= 2 and len(lns) > best_n:
            best_n = len(lns)
            best_row = (yk, lns)

    if best_row is None:
        return []

    row_y = 4.0 * best_row[0]
    has_enum = False
    for ln in lines:
        if ln.y0 <= row_y + 18:
            continue
        if ln.y0 - row_y > 520:
            break
        if not getattr(ln, "text", ""):
            continue
        t = ln.text.strip()
        if not t or _looks_like_furniture(ln):
            continue
        t2 = t.lstrip("\\").lstrip()
        if _ENUM_OPT_RE.match(t2):
            has_enum = True
            break

    if not has_enum:
        return []

    lns = sorted(best_row[1], key=lambda l: l.x0)
    return [(ln.text or "").strip() for ln in lns]
