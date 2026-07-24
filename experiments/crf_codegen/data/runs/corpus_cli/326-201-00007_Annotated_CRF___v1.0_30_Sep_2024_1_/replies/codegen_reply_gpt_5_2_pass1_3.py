```python
import re
import unicodedata
from typing import List, Dict, Tuple, Optional


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []

    # -------- helpers --------
    _re_ws = re.compile(r"\s+")
    _re_only_punct = re.compile(r"[_\s\-:./]+$")
    _re_line_num = re.compile(r"\d+(?:\.\d+)?(?:\s*\(hidden\))?$", flags=re.IGNORECASE)

    _re_date_token = re.compile(r"\bdd\s*-\s*[A-Za-z]{3}\s*-\s*yyyy\b", flags=re.IGNORECASE)
    _re_time_token = re.compile(r"\bHH\s*:\s*mm\b", flags=re.IGNORECASE)

    _re_activates = re.compile(r"\(\s*activates\s+line\b.*?\)", flags=re.IGNORECASE)
    _re_hidden = re.compile(r"\(\s*hidden\s*\)", flags=re.IGNORECASE)

    # common data-entry mask tokens (inside parentheses or bare)
    _re_mask_inside_parens = re.compile(
        r"\(\s*(?:"
        r"dd\s*-\s*[A-Za-z]{3}\s*-\s*yyyy"
        r"|HH\s*:\s*mm"
        r"|#+"
        r"|##(?:\.\d+)?"
        r"|#*(?:0+)"
        r"|[0-9]{1,5}\s*char\.\s*max\."
        r")\s*\)",
        flags=re.IGNORECASE,
    )
    _re_char_max_parens = re.compile(r"\(\s*[0-9]{1,5}\s*char\.\s*max\.\s*\)", flags=re.IGNORECASE)
    _re_mask_bare = re.compile(
        r"^(?:dd\s*-\s*[A-Za-z]{3}\s*-\s*yyyy|HH\s*:\s*mm|#+|##(?:\.\d+)?|0+)$",
        flags=re.IGNORECASE,
    )

    _re_option_start = re.compile(r"^(?:O|0)\s+\S", flags=re.IGNORECASE)

    _exclude_fields = {
        "answer(s):",
        "answers:",
        "answer:",
        "answer(s)",
        "answers",
        "answer",
    }

    def norm_space(s: str) -> str:
        return _re_ws.sub(" ", (s or "").strip())

    def low_norm(s: str) -> str:
        return norm_space(s).lower()

    def has_letter(s: str) -> bool:
        for ch in s:
            if ch.isalpha():
                return True
            if unicodedata.category(ch).startswith("L"):
                return True
        return False

    def is_machine_annot(t: str) -> bool:
        t = (t or "").strip()
        return bool(t.startswith("[") and "]" in t and "SAS:" in t)

    def is_line_number_text(t: str) -> bool:
        t = norm_space(t)
        return bool(_re_line_num.fullmatch(t))

    def is_header_like(lines: list) -> bool:
        # detect this family by geometry: big colored title near top + colored column headers around y~110-130
        big_colored = 0
        mid_colored = 0
        for ln in lines[:40]:
            if ln.y0 < 70 and ln.size >= 18 and getattr(ln, "bold", False) and getattr(ln, "non_black", False):
                big_colored += 1
            if 95 <= ln.y0 <= 140 and 8.5 <= ln.size <= 11.5 and getattr(ln, "bold", False) and getattr(ln, "non_black", False):
                if ln.x0 < 80 or (140 <= ln.x0 <= 220) or ln.x0 > 450:
                    mid_colored += 1
        return big_colored >= 1 and mid_colored >= 2

    def y_key(y: float) -> int:
        # bucket y into ~3pt bins to build rows
        return int(round(y / 3.0))

    def group_rows(lines: list) -> List[Tuple[float, list]]:
        rows = {}
        for ln in lines:
            k = y_key(ln.y0)
            rows.setdefault(k, []).append(ln)
        row_list = []
        for k, lst in rows.items():
            lst_sorted = sorted(lst, key=lambda z: z.x0)
            y_avg = sum(z.y0 for z in lst_sorted) / max(1, len(lst_sorted))
            row_list.append((y_avg, lst_sorted))
        row_list.sort(key=lambda t: t[0])
        return row_list

    def pick_schedule_name(rows: List[Tuple[float, list]]) -> Optional[str]:
        # heuristic: a bold label ending in ":" at far left, with a value at x~168 on same row
        for y, r in rows:
            if not (55 <= y <= 115):
                continue
            left = None
            val = None
            for ln in r:
                tx = norm_space(ln.text)
                if ln.x0 < 90 and getattr(ln, "bold", False) and (10.0 <= ln.size <= 12.5) and tx.endswith(":"):
                    left = ln
                elif 130 <= ln.x0 <= 280 and (10.0 <= ln.size <= 12.5) and (not getattr(ln, "bold", False)):
                    if tx and not is_machine_annot(tx):
                        val = tx
            if left is not None and val:
                return val
        return None

    def find_activity_rows(rows: List[Tuple[float, list]]) -> List[Tuple[float, str]]:
        acts: List[Tuple[float, str]] = []
        for y, r in rows:
            if y < 105:
                continue
            ln_num_x = None
            for ln in r:
                if ln.x0 > 410 and is_line_number_text(ln.text):
                    ln_num_x = ln.x0
                    break
            if ln_num_x is None:
                continue

            best = None
            best_len = -1
            for ln in r:
                tx = norm_space(ln.text)
                if not tx or is_machine_annot(tx):
                    continue
                if getattr(ln, "non_black", False):
                    continue
                if not getattr(ln, "bold", False):
                    continue
                if not (7.5 <= ln.size <= 12.5):
                    continue
                if not (90 <= ln.x0 <= 360):
                    continue
                if ln.x0 >= ln_num_x - 40:
                    continue
                if _re_date_token.fullmatch(tx) or _re_time_token.fullmatch(tx):
                    continue
                if _re_only_punct.fullmatch(tx):
                    continue

                if len(tx) > best_len:
                    best = tx
                    best_len = len(tx)
            if best:
                acts.append((y, best))
        return acts

    def is_left_label(ln) -> bool:
        tx = norm_space(ln.text)
        if not tx or is_machine_annot(tx):
            return False
        if low_norm(tx) in _exclude_fields:
            return False
        if not tx.endswith(":"):
            return False
        if ln.x0 > 190:
            return False
        if not (7.0 <= ln.size <= 12.8):
            return False
        # labels are typically bold and/or colored; allow black bold too (some pages)
        if not (getattr(ln, "bold", False) or getattr(ln, "non_black", False)):
            return False
        if _re_only_punct.fullmatch(tx):
            return False
        return True

    def is_answer_header(ln) -> bool:
        tx = norm_space(ln.text)
        if not tx or is_machine_annot(tx):
            return False
        if not tx.endswith(":"):
            return False
        tlo = low_norm(tx)
        if tlo in _exclude_fields or tlo.startswith("answer"):
            # geometry-based but allow black (some pages render it black)
            if getattr(ln, "bold", False) and (7.5 <= ln.size <= 12.8) and (95 <= ln.x0 <= 380) and ln.y0 >= 95:
                return True
        # original colored/bold header style
        if getattr(ln, "non_black", False) and getattr(ln, "bold", False) and (8.0 <= ln.size <= 12.2):
            if 105 <= ln.x0 <= 380 and ln.y0 >= 95:
                if tlo in _exclude_fields or tlo.startswith("answer"):
                    return True
        return False

    def looks_like_entry_mask(s: str) -> bool:
        s = norm_space(s)
        if not s:
            return False
        if "_" in s:
            return True
        if _re_mask_inside_parens.search(s):
            return True
        if _re_date_token.search(s) or _re_time_token.search(s):
            return True
        if _re_mask_bare.fullmatch(s):
            return True
        return False

    def is_inline_mask_label(s: str) -> bool:
        s = norm_space(s)
        if not s or is_machine_annot(s):
            return False
        if _re_only_punct.fullmatch(s):
            return False
        if _re_mask_inside_parens.search(s) or _re_char_max_parens.search(s) or _re_date_token.search(s) or _re_time_token.search(s):
            # require letters outside the parens so we don't emit bare "(dd-MMM-yyyy)"
            tmp = re.sub(r"\([^)]*\)", " ", s)
            return has_letter(tmp)
        return False

    def is_option_line_text(s: str) -> bool:
        s = norm_space(s)
        if not s:
            return False
        if _re_option_start.match(s):
            if s.lower().startswith("open "):
                return False
            return True
        if s[:1] in ("○", "◯", "●", "•") and len(s) >= 2 and s[1].isspace():
            return True
        return False

    def clean_entry_text(raw: str) -> str:
        s = norm_space(raw)
        if not s:
            return s
        s = _re_hidden.sub("", s)
        s = _re_activates.sub("", s)
        s = norm_space(s)
        return s

    def clean_underscores_preserve_masks(raw: str) -> Tuple[str, bool]:
        """
        Returns (cleaned, constraint_only).
        - cleaned may include a parenthesized mask like '(dd-MMM-yyyy)' or '(##0)'.
        - constraint_only True if the line was essentially just underscores + a mask (no label).
        """
        s = clean_entry_text(raw)
        if not s:
            return "", False

        if "_" in s:
            first_us = s.find("_")
            prefix = s[:first_us].strip()

            tail = s[first_us:]
            paren = ""
            if "(" in tail and ")" in tail:
                paren = tail[tail.find("("):].strip()

            mid = tail
            if "(" in tail:
                mid = tail[:tail.find("(")]
            mid = mid.replace("_", " ")
            mid = norm_space(mid)

            mid_kept = ""
            if mid and has_letter(mid):
                mid_kept = mid

            parts = []
            if prefix:
                parts.append(prefix)
            if mid_kept:
                parts.append(mid_kept)
            if paren:
                parts.append(paren)

            cleaned = norm_space(" ".join(parts))
            constraint_only = (not prefix) and (not mid_kept) and bool(paren)
            return cleaned, constraint_only

        return s, False

    def is_parenthetical_instruction(s: str) -> bool:
        s = norm_space(s)
        if not s:
            return False
        if s.startswith("(") and s.endswith(")"):
            if looks_like_entry_mask(s) or is_inline_mask_label(s):
                return False
            return True
        return False

    def is_instructiony_sentence(s: str) -> bool:
        s = norm_space(s)
        if not s:
            return False
        slo = s.lower()
        if slo.startswith("please ensure"):
            return True
        return False

    def is_question_like_text(s: str) -> bool:
        s = norm_space(s)
        if not s or is_machine_annot(s):
            return False
        if s.endswith(":"):
            return False
        if low_norm(s) in _exclude_fields or low_norm(s).startswith("answer"):
            return False
        if _re_only_punct.fullmatch(s):
            return False
        if is_option_line_text(s):
            return False
        if _re_mask_bare.fullmatch(s):
            return False
        if is_parenthetical_instruction(s):
            return False
        if is_instructiony_sentence(s):
            return False

        if len(s) >= 18:
            return True
        if s.endswith("?"):
            return True
        if _re_mask_inside_parens.search(s) and has_letter(s):
            return True
        # allow shorter labels (e.g., "Prandial state")
        if has_letter(s) and len(s) >= 10 and s.count(" ") >= 1:
            return True
        return False

    def is_question_line(ln) -> bool:
        tx = norm_space(ln.text)
        if not is_question_like_text(tx):
            return False
        if not (6.8 <= ln.size <= 12.8):
            return False
        if not (55 <= ln.x0 <= 420):
            return False
        if _re_date_token.fullmatch(tx) or _re_time_token.fullmatch(tx):
            return False
        return True

    def add_field(page_1based: int, form: str, field: str, seen: set):
        form = norm_space(form)
        field = norm_space(field)
        if not field:
            return
        if low_norm(field) in _exclude_fields or low_norm(field).startswith("answer"):
            return

        if field.startswith("(") and field.endswith(")"):
            if _re_char_max_parens.fullmatch(field):
                return
            if _re_mask_inside_parens.fullmatch(field):
                return

        key = (form, field)
        if key in seen:
            return
        seen.add(key)
        out.append({"form_name": form, "field_name": field, "page": page_1based})

    def build_row_texts(lines_subset: list, x_min: float) -> List[Tuple[float, str]]:
        row_map = {}
        for ln in lines_subset:
            if is_machine_annot(ln.text):
                continue
            if ln.x0 < x_min:
                continue
            tx = norm_space(ln.text)
            if not tx:
                continue
            if is_line_number_text(tx):
                continue
            k = y_key(ln.y0)
            row_map.setdefault(k, []).append(ln)

        row_list: List[Tuple[float, str]] = []
        for k, lst in row_map.items():
            lst_sorted = sorted(lst, key=lambda z: z.x0)
            y_avg = sum(z.y0 for z in lst_sorted) / max(1, len(lst_sorted))
            txt = norm_space(" ".join(norm_space(z.text) for z in lst_sorted if norm_space(z.text)))
            if txt:
                row_list.append((y_avg, txt))
        row_list.sort(key=lambda t: t[0])
        return row_list

    # -------- main loop --------
    current_form = ""
    current_schedule = ""

    for page_idx0, lines in pages:
        if not lines:
            continue
        if not is_header_like(lines):
            continue

        rows = group_rows(lines)
        sched = pick_schedule_name(rows)
        if sched:
            current_schedule = sched

        activities = find_activity_rows(rows)
        block_starts = [y for y, _ in activities]
        block_starts.sort()
        page_seen = set()

        if not block_starts:
            block_starts = [120.0]

        act_by_y = {y: name for y, name in activities}

        # include slightly above prior cutoff to catch fields near the top of blocks (e.g., Date)
        body_lines = [ln for ln in lines if ln.y0 >= 88]
        body_lines.sort(key=lambda z: (z.y0, z.x0))

        block_ranges = []
        for i, y0 in enumerate(block_starts):
            y1 = 1e9 if i + 1 == len(block_starts) else block_starts[i + 1]
            block_ranges.append((y0, y1))

        for y0, y1 in block_ranges:
            if y0 in act_by_y:
                current_form = act_by_y[y0]

            block_lines = [ln for ln in body_lines if y0 - 1.5 <= ln.y0 < y1 - 1.5]
            if not block_lines:
                continue

            form_name = current_form or current_schedule or ""

            # find answer header and left-label boundaries
            answer_y = None
            left_label_ys = []
            for ln in block_lines:
                if answer_y is None and is_answer_header(ln):
                    answer_y = ln.y0
                if is_left_label(ln):
                    left_label_ys.append((ln.y0, norm_space(ln.text)))

            # answer section ends at the first left-label AFTER answer header (if any)
            ans_end = None
            if answer_y is not None and left_label_ys:
                for ly, _txt in sorted(left_label_ys, key=lambda t: t[0]):
                    if ly > answer_y + 1.0:
                        ans_end = ly
                        break
            if ans_end is None:
                ans_end = y1

            # --- extract question/prompt label(s) ---
            prompt_end_y = answer_y if answer_y is not None else (ans_end if ans_end is not None else y1)
            q_lines = []
            for ln in block_lines:
                if ln.y0 <= y0 + 0.5:
                    continue
                if ln.y0 >= (prompt_end_y - 0.5):
                    break
                if is_question_line(ln):
                    q_lines.append(ln)

            if q_lines:
                q_lines.sort(key=lambda z: (z.y0, z.x0))
                joined = []
                buf = []
                last_y = None
                for ln in q_lines:
                    tx = norm_space(ln.text)
                    if not tx:
                        continue
                    if low_norm(tx) in _exclude_fields or low_norm(tx).startswith("answer"):
                        continue
                    if is_parenthetical_instruction(tx) or is_instructiony_sentence(tx):
                        continue

                    if last_y is None or abs(ln.y0 - last_y) <= 18.5:
                        buf.append(tx)
                    else:
                        if buf:
                            joined.append(norm_space(" ".join(buf)))
                        buf = [tx]
                    last_y = ln.y0
                if buf:
                    joined.append(norm_space(" ".join(buf)))

                for q in joined:
                    if current_form and norm_space(q) == norm_space(current_form):
                        continue
                    if low_norm(q) in _exclude_fields or low_norm(q).startswith("answer"):
                        continue
                    if is_parenthetical_instruction(q) or is_instructiony_sentence(q):
                        continue
                    add_field(page_idx0 + 1, form_name, q, page_seen)

            # --- extract left labels (Comment:, Staff Initials:, Date:, Barcode:, etc.) ---
            for ln in block_lines:
                if is_left_label(ln):
                    add_field(page_idx0 + 1, form_name, norm_space(ln.text), page_seen)

            # --- extract inline mask labels that can appear anywhere in the block (e.g., Date (dd-MMM-yyyy)) ---
            # This catches fields that are labels with masks, even without underscores.
            for y, tx in build_row_texts(block_lines, x_min=60):
                if low_norm(tx) in _exclude_fields or low_norm(tx).startswith("answer"):
                    continue
                if is_option_line_text(tx):
                    continue
                if is_parenthetical_instruction(tx) or is_instructiony_sentence(tx):
                    continue
                if is_inline_mask_label(tx):
                    add_field(page_idx0 + 1, form_name, tx, page_seen)

            # --- extract answer entry fields ---
            scan_y0 = (answer_y + 0.5) if answer_y is not None else (y0 + 0.5)
            scan_y1 = (ans_end - 0.5) if ans_end is not None else (y1 - 0.5)

            scan_lines = [ln for ln in block_lines if scan_y0 <= ln.y0 < scan_y1]
            scan_lines.sort(key=lambda z: (z.y0, z.x0))

            row_list = build_row_texts(scan_lines, x_min=80)

            last_option_y = None
            pending_label = ""
            pending_label_y = None
            seen_any_option = False

            for y, tx in row_list:
                if not tx or is_machine_annot(tx):
                    continue
                if low_norm(tx) in _exclude_fields or low_norm(tx).startswith("answer"):
                    continue
                if is_parenthetical_instruction(tx) or is_instructiony_sentence(tx):
                    continue

                # option handling
                if is_option_line_text(tx):
                    last_option_y = y
                    pending_label = ""
                    pending_label_y = None
                    seen_any_option = True
                    continue
                if last_option_y is not None and abs(y - last_option_y) <= 18.5:
                    # wrapped option continuation: ignore unless it's clearly an entry mask / inline mask label
                    if not looks_like_entry_mask(tx) and not is_inline_mask_label(tx):
                        continue

                entryish = looks_like_entry_mask(tx) or is_inline_mask_label(tx)

                # label accumulation (multi-line labels before the entry line)
                if (not entryish) and has_letter(tx) and (not tx.endswith(":")) and (not _re_only_punct.fullmatch(tx)):
                    if not pending_label:
                        pending_label = tx
                        pending_label_y = y
                    else:
                        if pending_label_y is not None and abs(y - pending_label_y) <= 20.0:
                            pending_label = norm_space(pending_label + " " + tx)
                            pending_label_y = y
                        else:
                            pending_label = tx
                            pending_label_y = y
                    continue

                if not entryish:
                    continue

                # Inline mask labels like "Diastolic mmHg (####)" should be emitted as-is (not as constraints)
                if is_inline_mask_label(tx) and "_" not in tx:
                    field_name = norm_space(clean_entry_text(tx))
                    add_field(page_idx0 + 1, form_name, field_name, page_seen)
                    pending_label = ""
                    pending_label_y = None
                    continue

                cleaned, constraint_only = clean_underscores_preserve_masks(tx)
                cleaned = norm_space(cleaned)

                if not cleaned:
                    continue

                field_name = cleaned

                if constraint_only:
                    # Only emit if we can attach it to a preceding label
                    if pending_label and pending_label_y is not None and abs(y - pending_label_y) <= 28.0:
                        field_name = norm_space(pending_label + " " + cleaned)
                    else:
                        continue
                else:
                    if pending_label and pending_label_y is not None and abs(y - pending_label_y) <= 28.0:
                        if field_name.startswith("(") and field_name.endswith(")"):
                            field_name = norm_space(pending_label + " " + field_name)
                        elif _re_mask_inside_parens.fullmatch(field_name) or _re_char_max_parens.fullmatch(field_name):
                            field_name = norm_space(pending_label + " " + field_name)
                        elif _re_mask_bare.fullmatch(field_name):
                            field_name = norm_space(pending_label + " (" + field_name + ")")

                add_field(page_idx0 + 1, form_name, field_name, page_seen)

                pending_label = ""
                pending_label_y = None

            # If we saw options but captured no question line, try to recover a short label near the top of the block
            if seen_any_option:
                # heuristic: pick the best short label in the prompt region just above the answer area
                if answer_y is not None:
                    cand_lines = [
                        ln for ln in block_lines
                        if (y0 + 0.5) < ln.y0 < (answer_y - 0.5) and (70 <= ln.x0 <= 380) and (7.0 <= ln.size <= 12.8)
                    ]
                else:
                    cand_lines = [
                        ln for ln in block_lines
                        if (y0 + 0.5) < ln.y0 < (y0 + 70.0) and (70 <= ln.x0 <= 380) and (7.0 <= ln.size <= 12.8)
                    ]
                best_lbl = ""
                best_y = None
                for ln in cand_lines:
                    tx = norm_space(ln.text)
                    if not tx or is_machine_annot(tx):
                        continue
                    if low_norm(tx) in _exclude_fields or low_norm(tx).startswith("answer"):
                        continue
                    if tx.endswith(":"):
                        continue
                    if is_option_line_text(tx):
                        continue
                    if is_parenthetical_instruction(tx) or is_instructiony_sentence(tx):
                        continue
                    if not has_letter(tx):
                        continue
                    # allow short ones here
                    if len(tx) < 6:
                        continue
                    if len(tx) > len(best_lbl):
                        best_lbl = tx
                        best_y = ln.y0
                if best_lbl:
                    add_field(page_idx0 + 1, form_name, best_lbl, page_seen)

        if not activities and (not current_form) and current_schedule:
            current_form = current_schedule

    return out
```
