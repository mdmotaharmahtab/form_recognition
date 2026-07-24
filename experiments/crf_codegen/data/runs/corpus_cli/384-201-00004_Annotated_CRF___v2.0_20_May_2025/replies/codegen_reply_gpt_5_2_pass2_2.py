```python
import re
from typing import List, Tuple, Dict, Any


def extract(pages: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    current_form = ""

    for page_idx0, lines in pages:
        if not lines:
            continue

        max_x1 = max((_x1(ln) for ln in lines), default=0.0)
        max_y1 = max((_y1(ln) for ln in lines), default=0.0)

        title = _find_form_title(lines, max_x1, max_y1)
        if title:
            current_form = title

        # Layout family 1: cover-style approval form (existing)
        labels = _extract_left_labels_if_layout_matches(lines, max_x1, max_y1)
        if labels:
            form_name = title or current_form or ""
            seen = set()
            for lab in labels:
                key = (form_name, lab)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"form_name": form_name, "field_name": lab, "page": page_idx0 + 1})
            continue

        # Layout family 2: DocuSign signer-events table (new)
        signer_labels = _extract_signer_event_people(lines, max_x1, max_y1)
        if signer_labels:
            form_name = current_form or title or ""
            seen = set()
            for lab in signer_labels:
                key = (form_name, lab)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"form_name": form_name, "field_name": lab, "page": page_idx0 + 1})
            continue

        # Otherwise: no fields for this layout family (ignore)

    return out


# ---------------- helpers ----------------

def _txt(ln: Any) -> str:
    return getattr(ln, "text", "") or ""


def _x0(ln: Any) -> float:
    return float(getattr(ln, "x0", 0.0) or 0.0)


def _x1(ln: Any) -> float:
    return float(getattr(ln, "x1", 0.0) or 0.0)


def _y0(ln: Any) -> float:
    return float(getattr(ln, "y0", 0.0) or 0.0)


def _y1(ln: Any) -> float:
    return float(getattr(ln, "y1", 0.0) or 0.0)


def _size(ln: Any) -> float:
    return float(getattr(ln, "size", 0.0) or 0.0)


def _bold(ln: Any) -> bool:
    return bool(getattr(ln, "bold", False))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _only_punct_or_rules(s: str) -> bool:
    s2 = re.sub(r"\s+", "", s or "")
    if not s2:
        return True
    if re.fullmatch(r"[_\-–—\.]{6,}", s2):
        return True
    if re.fullmatch(r"[\*\.\-–—]+", s2):
        return True
    return False


def _meaningful_text(s: str) -> bool:
    s = _norm(s)
    if not s or _only_punct_or_rules(s):
        return False
    alnum = sum(1 for ch in s if ch.isalnum())
    digits = sum(1 for ch in s if ch.isdigit())
    if alnum < 3:
        return False
    if digits == alnum and alnum >= 3:
        return False
    return True


def _looks_like_email(s: str) -> bool:
    s = _norm(s).lower()
    return "@" in s and "." in s and " " not in s


def _looks_like_ipish(s: str) -> bool:
    s = _norm(s)
    return bool(re.search(r"\b\d{1,3}(\.\d{1,3}){2,3}\b", s))


def _find_form_title(lines, max_x1: float, max_y1: float) -> str:
    top_cut = 110.0
    bot_cut = max_y1 - 90.0

    cands = []
    for ln in lines:
        if not _bold(ln):
            continue
        if _y0(ln) < top_cut or _y0(ln) > bot_cut:
            continue
        if _size(ln) < 16.0:
            continue
        txt = _norm(_txt(ln))
        if not _meaningful_text(txt):
            continue
        if _x0(ln) < 45.0:
            continue
        cands.append(ln)

    if not cands:
        return ""

    max_size = max(_size(ln) for ln in cands)
    near = [ln for ln in cands if _size(ln) >= max_size - 0.6]

    near.sort(key=lambda ln: (abs(((_x0(ln) + _x1(ln)) / 2.0) - (max_x1 / 2.0)), _y0(ln)))

    base = near[0]
    base_txt = _norm(_txt(base))

    join = [base]
    for ln in cands:
        if ln is base:
            continue
        if abs(_size(ln) - _size(base)) > 0.6:
            continue
        if abs(_x0(ln) - _x0(base)) > 80.0 and abs(((_x0(ln) + _x1(ln)) / 2.0) - ((_x0(base) + _x1(base)) / 2.0)) > 80.0:
            continue
        if 0.0 < (_y0(ln) - _y0(base)) <= (_size(base) * 1.6 + 6.0):
            overlap = min(_x1(base), _x1(ln)) - max(_x0(base), _x0(ln))
            if overlap >= 40.0:
                join.append(ln)

    join.sort(key=lambda ln: _y0(ln))
    txt = _norm(" ".join(_norm(_txt(ln)) for ln in join))
    if _meaningful_text(txt):
        return txt
    return base_txt if _meaningful_text(base_txt) else ""


def _extract_left_labels_if_layout_matches(lines, max_x1: float, max_y1: float) -> List[str]:
    top_cut = 140.0
    bot_cut = max_y1 - 110.0

    left = []
    right = []

    for ln in lines:
        y = _y0(ln)
        if y < top_cut or y > bot_cut:
            continue
        txt = _norm(_txt(ln))
        if not txt:
            continue

        if _bold(ln) and _size(ln) >= 14.6 and _x0(ln) <= 150.0 and _meaningful_text(txt):
            if (_x1(ln) - _x0(ln)) <= 350.0:
                left.append(ln)

        if (not _bold(ln)) and 10.0 <= _size(ln) <= 13.2 and 160.0 <= _x0(ln) <= 320.0 and _meaningful_text(txt):
            right.append(ln)

    if len(left) < 3:
        return []

    y_bins = {}
    for ln in right:
        key = int(round(_y0(ln) / 3.0))
        y_bins.setdefault(key, []).append(ln)

    aligned = 0
    for ln in left:
        key = int(round(_y0(ln) / 3.0))
        found = False
        for k in (key - 1, key, key + 1):
            for rln in y_bins.get(k, []):
                if abs(_y0(rln) - _y0(ln)) <= 4.0:
                    found = True
                    break
            if found:
                break
        if found:
            aligned += 1
    if aligned < 2:
        return []

    left.sort(key=lambda ln: (_y0(ln), _x0(ln)))

    merged = []
    i = 0
    while i < len(left):
        a = left[i]
        parts = [_norm(_txt(a))]
        j = i + 1
        while j < len(left):
            b = left[j]
            if abs(_x0(b) - _x0(a)) <= 14.0 and abs(_size(b) - _size(a)) <= 0.8 and _bold(b) == _bold(a):
                gap = _y0(b) - _y0(left[j - 1])
                if 0.0 < gap <= (_size(a) * 1.25 + 6.0):
                    parts.append(_norm(_txt(b)))
                    j += 1
                    continue
            break

        lab = _norm(" ".join(p for p in parts if p))
        if _meaningful_text(lab) and not _only_punct_or_rules(lab):
            merged.append(lab)

        i = j

    return merged


def _extract_signer_event_people(lines, max_x1: float, max_y1: float) -> List[str]:
    # Detect "Signer Events | Signature | Timestamp" tables and extract signer identity labels
    # as "Name, Role" when role text is present nearby.
    top_cut = 15.0
    bot_cut = max((_y1(ln) for ln in lines), default=0.0) - 30.0

    def norm_low(s: str) -> str:
        return _norm(s).lower()

    # Find signer-events header rows
    headers = []
    for ln in lines:
        if _y0(ln) < top_cut or _y0(ln) > bot_cut:
            continue
        if not _bold(ln):
            continue
        if not (9.5 <= _size(ln) <= 11.8):
            continue
        t = norm_low(_txt(ln))
        if t in ("signer events", "signature", "timestamp"):
            headers.append(ln)

    if not headers:
        return []

    # Cluster header y's; require at least two distinct labels near same y band
    by_band: Dict[int, List[str]] = {}
    for ln in headers:
        band = int(round(_y0(ln) / 6.0))
        by_band.setdefault(band, []).append(norm_low(_txt(ln)))

    header_band = None
    for band, labs in sorted(by_band.items(), key=lambda kv: len(set(kv[1])), reverse=True):
        if len(set(labs)) >= 2 and ("signer events" in set(labs)):
            header_band = band
            break
    if header_band is None:
        return []

    header_y = min(_y0(ln) for ln in headers if int(round(_y0(ln) / 6.0)) == header_band)

    # Determine end of this table: next bold section header that looks like another "* Events"
    end_y = bot_cut
    for ln in lines:
        if _y0(ln) <= header_y + 18.0:
            continue
        if _x0(ln) > 120.0:
            continue
        if not _bold(ln):
            continue
        if _size(ln) < 9.5:
            continue
        t = norm_low(_txt(ln))
        if "events" in t and t != "signer events" and len(t) <= 40:
            end_y = min(end_y, _y0(ln))
        # also stop at big new sections even without "events"
        if t in ("record tracking", "certificate of completion") and _size(ln) >= 9.5:
            end_y = min(end_y, _y0(ln))

    # Build index of right-column event lines (Sent:/Viewed:/Signed:)
    event_prefixes = ("sent:", "viewed:", "signed:", "completed:", "declined:", "delivered:", "voided:")
    right_events = []
    for ln in lines:
        y = _y0(ln)
        if y <= header_y + 8.0 or y >= end_y:
            continue
        if _x0(ln) < 300.0:
            continue
        if _bold(ln):
            continue
        if not (7.0 <= _size(ln) <= 9.4):
            continue
        t = norm_low(_txt(ln))
        if any(t.startswith(p) for p in event_prefixes):
            right_events.append(ln)

    if not right_events:
        return []

    y_bins: Dict[int, List[Any]] = {}
    for ln in right_events:
        y_bins.setdefault(int(round(_y0(ln) / 3.0)), []).append(ln)

    def has_right_event(y: float) -> bool:
        key = int(round(y / 3.0))
        for k in (key - 1, key, key + 1):
            for rln in y_bins.get(k, []):
                if abs(_y0(rln) - y) <= 4.0:
                    return True
        return False

    # Candidate name lines in left column
    left_lines = [ln for ln in lines if (header_y + 8.0) <= _y0(ln) < end_y]
    left_lines.sort(key=lambda ln: (_y0(ln), _x0(ln)))

    def is_name_like(s: str) -> bool:
        s2 = _norm(s)
        if not _meaningful_text(s2):
            return False
        if ":" in s2:
            return False
        if _looks_like_email(s2) or _looks_like_ipish(s2):
            return False
        low = s2.lower()
        if any(k in low for k in ("docusign", "envelope", "certificate", "disclosure", "security level")):
            return False
        if any(k in low for k in ("clinical research", "inc", "llc", "company", "university", "hospital", "center")):
            return False
        if len(s2) > 60:
            return False
        if " " not in s2:
            return False
        # avoid common non-name tokens
        if low in ("(required)", "not offered via docusign"):
            return False
        return True

    def is_role_like(s: str) -> bool:
        s2 = _norm(s)
        if not _meaningful_text(s2):
            return False
        if ":" in s2:
            return False
        if _looks_like_email(s2) or _looks_like_ipish(s2):
            return False
        low = s2.lower()
        if any(k in low for k in ("docusign", "envelope", "certificate", "disclosure", "security level")):
            return False
        if any(k in low for k in ("clinical research", "inc", "llc", "company")):
            return False
        keys = (
            "designee",
            "manager",
            "director",
            "coordinator",
            "officer",
            "monitor",
            "investigator",
            "data",
            "study",
            "lead",
            "senior",
            "sr.",
            "project",
            "qa",
            "quality",
        )
        return any(k in low for k in keys)

    extracted: List[str] = []
    used_name_y_bins = set()

    for idx, ln in enumerate(left_lines):
        if _x0(ln) > 90.0:
            continue
        if _bold(ln):
            continue
        if not (7.0 <= _size(ln) <= 9.4):
            continue

        name = _norm(_txt(ln))
        if not is_name_like(name):
            continue
        if not has_right_event(_y0(ln)):
            continue

        yk = int(round(_y0(ln) / 4.0))
        if yk in used_name_y_bins:
            continue

        role = ""
        # Look shortly below for role-like line(s) at same left margin
        for j in range(idx + 1, min(idx + 10, len(left_lines))):
            ln2 = left_lines[j]
            if _y0(ln2) - _y0(ln) > 60.0:
                break
            if abs(_x0(ln2) - _x0(ln)) > 10.0:
                continue
            if _bold(ln2):
                continue
            if not (7.0 <= _size(ln2) <= 9.4):
                continue
            t2 = _norm(_txt(ln2))
            if not t2 or t2 == name:
                continue
            if is_role_like(t2):
                role = t2
                break

        label = name if not role else _norm(f"{name}, {role}")
        extracted.append(label)
        used_name_y_bins.add(yk)

    # De-dup while preserving order
    seen = set()
    out_labs = []
    for lab in extracted:
        if lab in seen:
            continue
        seen.add(lab)
        out_labs.append(lab)

    return out_labs
```
