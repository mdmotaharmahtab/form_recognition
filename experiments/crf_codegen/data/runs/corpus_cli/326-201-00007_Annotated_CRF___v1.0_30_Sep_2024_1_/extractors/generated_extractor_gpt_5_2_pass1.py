# Observed layout: "Annotated CRF" pages with a fixed header and a repeating schedule-table body.
# Each data-entry block is keyed by an Activity row (bold black text near x~168 with a Line# at far right).
# Within each block, extract the main bold question label (wrapped across lines), plus left-column blue labels
# (e.g., Staff Initials / Comment), and fill-in fields inside the Answer(s) section (underscore blanks), while
# skipping answer options ("O ...") and machine annotations ("[XXXX] SAS:...").

import re
import unicodedata
from typing import List, Dict, Tuple, Optional


def extract(pages: List[Tuple[int, list]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []

    # -------- helpers --------
    def norm_space(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip())

    def has_letter(s: str) -> bool:
        for ch in s:
            if ch.isalpha():
                return True
            cat = unicodedata.category(ch)
            if cat.startswith("L"):
                return True
        return False

    def is_machine_annot(t: str) -> bool:
        t = (t or "").strip()
        return bool(t.startswith("[") and "]" in t and "SAS:" in t)

    def is_line_number_text(t: str) -> bool:
        t = norm_space(t)
        # typical: "142.0", "8.0 (hidden)"
        return bool(re.fullmatch(r"\d+(?:\.\d+)?(?:\s*\(hidden\))?", t, flags=re.IGNORECASE))

    def is_header_like(lines: list) -> bool:
        # detect this family by geometry: big colored title near top + colored column headers around y~110-130
        big_colored = 0
        mid_colored = 0
        for ln in lines[:40]:
            if ln.y0 < 70 and ln.size >= 18 and ln.bold and ln.non_black:
                big_colored += 1
            if 95 <= ln.y0 <= 140 and 8.5 <= ln.size <= 11.5 and ln.bold and ln.non_black:
                # "Timepoint/Activity/Line #" row (language may vary but style is stable)
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
                if ln.x0 < 90 and ln.bold and (10.0 <= ln.size <= 12.5) and tx.endswith(":"):
                    left = ln
                elif 135 <= ln.x0 <= 260 and (10.0 <= ln.size <= 12.5) and not ln.bold:
                    if tx and not is_machine_annot(tx):
                        val = tx
            if left is not None and val:
                return val
        return None

    def find_activity_rows(rows: List[Tuple[float, list]]) -> List[Tuple[float, str]]:
        acts: List[Tuple[float, str]] = []
        for y, r in rows:
            if y < 120:
                continue
            ln_num_x = None
            for ln in r:
                if ln.x0 > 460 and is_line_number_text(ln.text):
                    ln_num_x = ln.x0
                    break
            if ln_num_x is None:
                continue
            # activity title candidate: bold black around x~168
            best = None
            best_len = -1
            for ln in r:
                tx = norm_space(ln.text)
                if not tx or is_machine_annot(tx):
                    continue
                if ln.non_black:
                    continue
                if not ln.bold:
                    continue
                if not (9.0 <= ln.size <= 11.5):
                    continue
                if not (130 <= ln.x0 <= 300):
                    continue
                if ln.x0 >= ln_num_x - 40:
                    continue
                # avoid date/time placeholder-like furniture
                if re.fullmatch(r"(?:dd\s*-\s*\w+\s*-\s*yyyy|HH:mm)", tx, flags=re.IGNORECASE):
                    continue
                if re.fullmatch(r"[_\s\-:./]+", tx):
                    continue
                if len(tx) > best_len:
                    best = tx
                    best_len = len(tx)
            if best:
                acts.append((y, best))
        return acts

    def is_blue_left_label(ln) -> bool:
        tx = norm_space(ln.text)
        if not tx:
            return False
        if not ln.non_black:
            return False
        if not ln.bold:
            return False
        if not (8.5 <= ln.size <= 11.5):
            return False
        if ln.x0 > 120:
            return False
        # avoid column headers at y~116 (still blue/bold)
        if 95 <= ln.y0 <= 145:
            return False
        return tx.endswith(":")

    def is_answer_header(ln) -> bool:
        tx = norm_space(ln.text)
        if not tx:
            return False
        if not (ln.non_black and ln.bold and (8.5 <= ln.size <= 11.5)):
            return False
        if not (130 <= ln.x0 <= 300):
            return False
        # typically "Answer(s):" (language may vary); rely on style + trailing ":"
        if not tx.endswith(":"):
            return False
        # avoid "Activity" header at y~116
        if 95 <= ln.y0 <= 145:
            return False
        return True

    def is_question_bold_line(ln) -> bool:
        tx = norm_space(ln.text)
        if not tx or is_machine_annot(tx):
            return False
        if ln.non_black:
            return False
        if not ln.bold:
            return False
        if not (9.0 <= ln.size <= 11.5):
            return False
        if not (130 <= ln.x0 <= 300):
            return False
        # ignore obvious field furniture
        if re.fullmatch(r"[_\s\-:./]+", tx):
            return False
        if re.fullmatch(r"(?:dd\s*-\s*\w+\s*-\s*yyyy|HH:mm)", tx, flags=re.IGNORECASE):
            return False
        return True

    def clean_answer_field(raw: str) -> str:
        s = norm_space(raw)
        if not s:
            return s

        # remove machine-like trailing "(hidden)" or "(Activates Line ...)" when present
        s = re.sub(r"\(\s*hidden\s*\)", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\(\s*activates\s+line\b.*?\)", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\bactivates\s+line\b.*$", "", s, flags=re.IGNORECASE).strip()
        s = norm_space(s)

        if "_" not in s:
            return s

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
        # drop mid if it's just punctuation/separators
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

        return norm_space(" ".join(parts))

    def add_field(page_1based: int, form: str, field: str, seen: set):
        form = norm_space(form)
        field = norm_space(field)
        if not field:
            return
        key = (form, field)
        if key in seen:
            return
        seen.add(key)
        out.append({"form_name": form, "field_name": field, "page": page_1based})

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
        # Build block boundaries based on activity rows found on this page
        block_starts = [y for y, _ in activities]
        block_starts.sort()
        page_seen = set()

        # if no activity rows, treat whole body as one block continuing current_form
        if not block_starts:
            block_starts = [120.0]

        # map activity y->name for quick update
        act_by_y = {y: name for y, name in activities}

        # Pre-collect all lines in body in y order
        body_lines = [ln for ln in lines if ln.y0 >= 120]
        body_lines.sort(key=lambda z: (z.y0, z.x0))

        # Prepare block ranges
        block_ranges = []
        for i, y0 in enumerate(block_starts):
            y1 = 1e9 if i + 1 == len(block_starts) else block_starts[i + 1]
            block_ranges.append((y0, y1))

        # For each block range, extract
        for y0, y1 in block_ranges:
            # update form if this is an activity-start row
            if y0 in act_by_y:
                current_form = act_by_y[y0]

            block_lines = [ln for ln in body_lines if y0 - 1.5 <= ln.y0 < y1 - 1.5]

            form_name = current_form or current_schedule or ""
            if not block_lines:
                continue

            # locate Answer(s) header y (if any) and Comment label y (if any)
            answer_y = None
            comment_y = None
            for ln in block_lines:
                if answer_y is None and is_answer_header(ln):
                    answer_y = ln.y0
                if is_blue_left_label(ln) and norm_space(ln.text).endswith(":"):
                    # treat as potential comment boundary too (we don't key on wording)
                    # comment label typically appears after answers, but can appear even if no answers.
                    if comment_y is None and ln.x0 < 80:
                        # pick the last such label in the block as boundary later
                        pass
            # use last blue-left label in block as boundary end for answers (usually Comment)
            for ln in block_lines:
                if is_blue_left_label(ln):
                    comment_y = ln.y0 if (comment_y is None or ln.y0 > comment_y) else comment_y

            # extract main question label (bold black lines between activity row and Answer(s) header)
            q_candidates = []
            for ln in block_lines:
                if answer_y is not None and ln.y0 >= answer_y - 0.5:
                    break
                if ln.y0 <= y0 + 0.5:
                    continue
                if is_question_bold_line(ln):
                    # exclude the activity title itself if it repeats inside the block
                    if norm_space(ln.text) == norm_space(form_name):
                        continue
                    q_candidates.append(ln)

            # join contiguous question lines by y proximity
            if q_candidates:
                q_candidates.sort(key=lambda z: (z.y0, z.x0))
                joined = []
                buf = []
                last_y = None
                for ln in q_candidates:
                    if last_y is None or abs(ln.y0 - last_y) <= 18.5:
                        buf.append(norm_space(ln.text))
                    else:
                        if buf:
                            joined.append(norm_space(" ".join(buf)))
                        buf = [norm_space(ln.text)]
                    last_y = ln.y0
                if buf:
                    joined.append(norm_space(" ".join(buf)))

                # emit each joined question group (usually one per block)
                for q in joined:
                    add_field(page_idx0 + 1, form_name, q, page_seen)

            # extract blue left labels (Staff Initials / Comment etc.)
            for ln in block_lines:
                if is_blue_left_label(ln):
                    add_field(page_idx0 + 1, form_name, norm_space(ln.text), page_seen)

            # extract fill-in fields inside Answer(s)
            if answer_y is not None:
                ans_end = comment_y if comment_y is not None and comment_y > answer_y else y1
                ans_lines = [ln for ln in block_lines if (answer_y + 0.5) <= ln.y0 < (ans_end - 0.5)]
                ans_lines.sort(key=lambda z: (z.y0, z.x0))

                last_option_y = None
                last_added_raw = None
                last_added_y = None

                for ln in ans_lines:
                    tx = norm_space(ln.text)
                    if not tx or is_machine_annot(tx):
                        continue
                    # skip obvious options
                    if tx.startswith("O "):
                        last_option_y = ln.y0
                        continue
                    # skip continuation of option text (wrapped option line)
                    if last_option_y is not None and abs(ln.y0 - last_option_y) <= 18.5:
                        # only keep if it clearly looks like an entry field (underscores)
                        if "_" not in tx:
                            continue

                    # only consider right-column answer content region
                    if ln.x0 < 200:
                        continue

                    # merge with previous if it's clearly a continuation (e.g., "(Activates Line" + "145)")
                    if last_added_raw is not None and last_added_y is not None:
                        if abs(ln.y0 - last_added_y) <= 14.5 and abs(ln.x0 - 238.7) <= 25:
                            prev = last_added_raw
                            if prev.count("(") > prev.count(")") and "_" not in tx and not tx.startswith("O "):
                                last_added_raw = norm_space(prev + " " + tx)
                                last_added_y = ln.y0
                                continue

                    # keep only lines that look like fill-in entry fields (underscore blanks)
                    if "_" not in tx:
                        continue

                    cleaned = clean_answer_field(tx)
                    if cleaned and not is_machine_annot(cleaned):
                        add_field(page_idx0 + 1, form_name, cleaned, page_seen)
                        last_added_raw = tx
                        last_added_y = ln.y0

        # if we never found an activity on this page but do have schedule, keep schedule as fallback form context
        if activities:
            # ensure current_form updated to the last activity on the page (already done via blocks)
            pass
        elif not current_form and current_schedule:
            current_form = current_schedule

    return out
