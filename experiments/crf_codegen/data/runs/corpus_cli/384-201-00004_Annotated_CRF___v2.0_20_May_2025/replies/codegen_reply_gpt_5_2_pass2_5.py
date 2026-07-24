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

        docusign_kind = _classify_docusign_page(lines)

        title = _find_form_title(lines, max_x1, max_y1)
        if title and _looks_like_form_title(title):
            current_form = title

        # DocuSign disclosure pages are narrative/legal text (no data-entry fields).
        if docusign_kind == "disclosure":
            continue

        # DocuSign certificate/audit pages are event logs / tracking (not data-entry fields).
        # Do not extract "Name, Role" rows from these pages (e.g., "Carbon Copy Events, ...").
        if docusign_kind == "certificate":
            continue

        # Layout family 1: cover-style approval form
        labels = _extract_left_labels_if_layout_matches(lines, max_x1, max_y1)
        if labels:
            form_name = (title if _looks_like_form_title(title) else "") or current_form or ""
            seen = set()
            for lab in labels:
                key = (form_name, lab)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"form_name": form_name, "field_name": lab, "page": page_idx0 + 1})
            continue

        # Layout family 2: signature blocks (e.g., "Lora Adriano, Study Manager or designee")
        # Runs on non-DocuSign pages too; it is conservative to avoid pulling values.
        sig_labels = _extract_signature_name_role_labels(lines, max_y1)
        if sig_labels:
            form_name = (title if _looks_like_form_title(title) else "") or current_form or ""
            seen = set()
            for lab in sig_labels:
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


def _looks_like_form_title(s: str) -> bool:
    s2 = _norm(s).lower()
    if not _meaningful_text(s2):
        return False
    keys = (
        "form",
        "approval",
        "acrf",
        "ecrf",
        "crf",
        "case report",
    )
    return any(k in s2 for k in keys)


def _page_has_phrase(lines: List[Any], phrase: str) -> bool:
    p = phrase.lower()
    for ln in lines:
        t = _norm(_txt(ln)).lower()
        if not t:
            continue
        if p in t:
            return True
    return False


def _classify_docusign_page(lines: List[Any]) -> str:
    """
    Returns:
      - "certificate": DocuSign Certificate of Completion / tracking audit pages
      - "disclosure": narrative Electronic Record and Signature Disclosure pages
      - "": not DocuSign-related (for our purposes)
    """
    # Certificate/audit pages: explicit markers and event-log section headers.
    want = {"signer events", "signature", "timestamp"}
    found = set()
    for ln in lines:
        if not _bold(ln):
            continue
        if not (8.5 <= _size(ln) <= 13.5):
            continue
        t = _norm(_txt(ln)).lower()
        if t in want:
            found.add(t)

    if _page_has_phrase(lines, "certificate of completion"):
        return "certificate"
    if _page_has_phrase(lines, "record tracking"):
        return "certificate"
    if ("signer events" in found) and (len(found) >= 2):
        return "certificate"

    # Many DocuSign tracking pages don't include "certificate of completion" text,
    # but do include event section headers.
    for ph in (
        "carbon copy events",
        "in person signer events",
        "recipient delivery events",
        "editor delivery events",
        "agent delivery events",
        "envelope id",
    ):
        if _page_has_phrase(lines, ph):
            return "certificate"

    # Disclosure pages: big heading + long paragraphs (no fields).
    if _page_has_phrase(lines, "electronic record and signature disclosure"):
        # If it wasn't classified as certificate above, treat as narrative disclosure.
        return "disclosure"
    if _page_has_phrase(lines, "electronic record and signature disclosure created on"):
        return "disclosure"

    return ""


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

    near.sort(
        key=lambda ln: (
            abs(((_x0(ln) + _x1(ln)) / 2.0) - (max_x1 / 2.0)),
            _y0(ln),
        )
    )

    base = near[0]
    base_txt = _norm(_txt(base))

    join = [base]
    for ln in cands:
        if ln is base:
            continue
        if abs(_size(ln) - _size(base)) > 0.6:
            continue
        if abs(_x0(ln) - _x0(base)) > 80.0 and abs(
            ((_x0(ln) + _x1(ln)) / 2.0) - ((_x0(base) + _x1(base)) / 2.0)
        ) > 80.0:
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


def _extract_signature_name_role_labels(lines: List[Any], max_y1: float) -> List[str]:
    """
    Extract signature-block labels of the form:
      - "First Last, Role ..."
    Supports:
      - single line "Name, Role"
      - two-line blocks: Name then Role (same x0, small y-gap)
    Avoids obvious values (emails, IDs, timestamps) and avoids generic furniture.
    """
    if not lines or max_y1 <= 0:
        return []

    top_cut = 110.0
    bot_cut = max_y1 - 40.0

    cands = []
    for ln in lines:
        y = _y0(ln)
        if y < top_cut or y > bot_cut:
            continue
        sz = _size(ln)
        if not (7.2 <= sz <= 13.6):
            continue

        t = _norm(_txt(ln))
        if not _meaningful_text(t):
            continue

        tl = t.lower()
        if any(k in tl for k in ("envelope id", "signature id", "ip address", "record tracking", "certificate of completion")):
            continue
        if any(k in tl for k in ("carbon copy events", "in person signer events", "recipient delivery events", "editor delivery events", "agent delivery events")):
            continue
        if "@" in t:
            continue
        if re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", t):
            continue
        if re.search(r"\b\d{1,2}:\d{2}(:\d{2})?\b", t):
            continue
        if re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", tl):
            continue
        if any(ch.isdigit() for ch in t):
            # For signature labels, digits are almost always values, not labels.
            continue

        cands.append(ln)

    if not cands:
        return []

    cands.sort(key=lambda ln: (_y0(ln), _x0(ln)))

    # Pass 1: already "Name, Role" on one line.
    out = []
    used_idx = set()
    for i, ln in enumerate(cands):
        t = _norm(_txt(ln))
        if "," not in t:
            continue
        left, right = [p.strip() for p in t.split(",", 1)]
        if not (_looks_like_person_name(left) and _looks_like_role_text(right)):
            continue
        lab = _norm(f"{left}, {right}")
        if _is_good_signature_label(lab):
            out.append(lab)
            used_idx.add(i)

    # Pass 2: name line followed by role line.
    for i, ln in enumerate(cands):
        if i in used_idx:
            continue
        name = _norm(_txt(ln))
        if not _looks_like_person_name(name):
            continue

        x = _x0(ln)
        y = _y0(ln)

        role = ""
        best_j = None
        for j in range(i + 1, min(i + 7, len(cands))):
            nxt = cands[j]
            if abs(_x0(nxt) - x) > 28.0:
                continue
            dy = _y0(nxt) - y
            if dy <= 0:
                continue
            if dy > 42.0:
                break
            cand_role = _norm(_txt(nxt))
            if not _looks_like_role_text(cand_role):
                continue
            role = cand_role.rstrip(":").strip()
            best_j = j
            break

        if role:
            lab = _norm(f"{name}, {role}")
            if _is_good_signature_label(lab):
                out.append(lab)
                if best_j is not None:
                    used_idx.add(best_j)

    # De-dupe, preserve order.
    seen = set()
    uniq = []
    for s in out:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


def _looks_like_person_name(s: str) -> bool:
    s = _norm(s)
    if not _meaningful_text(s):
        return False
    if ":" in s or "," in s:
        return False
    if any(ch.isdigit() for ch in s):
        return False
    if "@" in s:
        return False
    if len(s) > 50:
        return False

    sl = s.lower()
    bad_exact = {
        "signer events", "signature", "timestamp",
        "electronic record and signature disclosure",
        "in person signer events", "editor delivery events", "agent delivery events", "recipient delivery events",
        "record tracking", "certificate of completion",
        "carbon copy events",
    }
    if sl in bad_exact:
        return False
    if "carbon copy" in sl or sl.endswith(" events"):
        return False

    parts = [p for p in re.split(r"\s+", s) if p]
    if len(parts) < 2 or len(parts) > 5:
        return False

    def ok_token(tok: str) -> bool:
        if len(tok) < 2:
            return False
        if tok.lower() in {"of", "and", "the"}:
            return False
        # allow initials and hyphenated names
        if not re.fullmatch(r"[A-Za-z][A-Za-z\.\-']*", tok):
            return False
        return True

    if not all(ok_token(p) for p in parts):
        return False

    # Require at least two tokens that look like capitalized names.
    cap = sum(1 for p in parts if p[0].isupper())
    return cap >= 2


def _looks_like_role_text(s: str) -> bool:
    s = _norm(s)
    if not _meaningful_text(s):
        return False
    if any(ch.isdigit() for ch in s):
        return False
    if "@" in s:
        return False
    if len(s) > 80:
        return False
    sl = s.lower()

    # Must include a role keyword; keeps us from grabbing company names, etc.
    keys = (
        "manager",
        "designee",
        "investigator",
        "director",
        "coordinator",
        "monitor",
        "supervisor",
        "lead",
        "senior",
    )
    if not any(k in sl for k in keys):
        return False

    # Avoid obvious non-role furniture.
    if any(k in sl for k in ("security level", "signature adoption", "using ip address", "with signing", "not offered")):
        return False
    if any(k in sl for k in ("carbon copy", "delivery events", "signer events")):
        return False

    return True


def _is_good_signature_label(s: str) -> bool:
    s = _norm(s)
    if not _meaningful_text(s):
        return False
    if len(s) < 8 or len(s) > 90:
        return False
    if any(ch.isdigit() for ch in s):
        return False
    if "@" in s:
        return False
    # Must look like "Name, Role"
    if "," not in s:
        return False
    left, right = [p.strip() for p in s.split(",", 1)]
    return _looks_like_person_name(left) and _looks_like_role_text(right)
```
