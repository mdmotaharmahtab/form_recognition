"""LEGACY COMPARISON PATH - not the production flow.

Production induction is codegen.py (the LLM writes the extraction program itself;
no fixed engine catalog). This module remains for two reasons only:
  - FieldRec / ReplayResult are the shared record/result types
  - the engine catalog + reference_recipes serve as a measurable baseline the
    codegen output is compared against
Engine parameter DEFAULTS below (e.g. oid_header="Include", column headers
"Name"/"Export Name") come from the local sample corpus - they are baseline
fixtures, NOT priors to ship. Do not route production documents through here.

A recipe is a small JSON document emitted once per document by the induction LLM,
which only ever sees the stage-0 representative pages. The engines below execute
recipes at native speed - no LLM anywhere in the per-page path.

Any CRF layout is expressed as one of these engines plus parameters:

  adjacent_annotation - machine codes printed on their own annotation lines next to
                        (usually under) the human field label, in the same column
  anchored_blocks     - repeated anchor rows (e.g. bold 'Prefix: Activity #n' with a
                        number in a far column) delimit blocks; codes found per block
  numbered_join       - two page types joined by a printed number: content pages
                        (label + number) and definition pages (number + code column)
  column_table        - definition tables with a header row; label and code are
                        cells in configurable columns
  line_pattern        - generic fallback: regex roles over sequential text lines
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import fitz

from common import Line, build_page_lines


@dataclass
class FieldRec:
    form_name: str
    field_name: str
    field_oid: str | None
    oid_alt: str | None = None
    page: int = 0
    extra: str = ""


@dataclass
class ReplayResult:
    format_id: str
    records: list[FieldRec] = field(default_factory=list)
    pages_with_fields: int = 0
    pages_total: int = 0
    definition_pages_seen: int = 0  # numbered_join only: pages matching def markers
    covered_pages: set = field(default_factory=set)  # 0-based, PRE-dedup (dedup keeps first
    # occurrence only, which would make repeated-field pages look uncovered)

    def dedup(self) -> None:
        """Collapse duplicates WITHIN a page only. The key includes `page`:
        a field repeated across pages (visit forms, log lines) is a real
        occurrence on every page it appears on. A page-blind key would keep
        only the first occurrence, making every later page look unextracted -
        the grounded audit then files phantom 'missed' findings against pages
        whose records were silently dropped, and convergence on repetitive
        form books (the core document class) becomes impossible."""
        seen, out = set(), []
        for r in self.records:
            key = (r.form_name.strip().lower(), r.field_name.strip().lower(),
                   (r.field_oid or "").strip(), r.page)
            if key not in seen:
                seen.add(key)
                out.append(r)
        self.records = out


def _compile(rxs) -> list[re.Pattern]:
    return [re.compile(rx) for rx in (rxs or [])]


def _is_noise(text: str, noise: list[re.Pattern]) -> bool:
    return any(rx.search(text) for rx in noise)


# --------------------------------------------------------------------------- #
# form-name strategies
# --------------------------------------------------------------------------- #
def find_form_name(lines: list[Line], cfg: dict, carry: str | None) -> str | None:
    strat = cfg.get("strategy")
    if strat == "regex":
        rx = re.compile(cfg["regex"])
        for L in lines:
            m = rx.match(L.text)
            if m:
                return m.group(1).strip()
        return carry if cfg.get("carry_forward") else None
    elif strat in ("colored_font", "font"):
        noise = _compile(cfg.get("noise"))
        best = None
        for L in lines:
            if L.size < cfg.get("min_size", 14):
                continue
            if strat == "colored_font" and not L.non_black:
                continue
            if _is_noise(L.text, noise) or not re.search(r"[A-Za-z]", L.text):
                continue
            if cfg.get("pick") == "last_above_first_field":
                # NOTE (known limitation, legacy path): callers pass full-page
                # lines, so this returns the last matching line on the PAGE, not
                # the last one above the first field. Good enough as a baseline.
                best = L.text.strip()
            else:
                return L.text.strip()
        if best:
            return best
    return carry if cfg.get("carry_forward") else None


# --------------------------------------------------------------------------- #
# engine: adjacent_annotation (codes on annotation lines next to the label)
# --------------------------------------------------------------------------- #
def extract_adjacent_annotation(pages, recipe: dict, result: ReplayResult) -> None:
    fcfg = recipe["fields"]
    oid_rx = re.compile(fcfg["oid_regex"])
    alt_rx = re.compile(fcfg["alt_regex"]) if fcfg.get("alt_regex") else None
    noise = _compile(fcfg.get("label_noise"))
    x_max = fcfg.get("column_x_max", 320)
    need_color = fcfg.get("oid_color_non_black", False)
    join_dy = fcfg.get("annotation_group_dy", 16)
    label_max_dy = fcfg.get("label_max_dy", 160)

    carry = None
    for pno, lines in pages:
        col = [L for L in lines if L.x0 <= x_max]
        # group consecutive bracket-annotation lines
        groups, cur = [], []
        for L in col:
            is_annot = bool(re.match(r"^\[.+", L.text)) and (L.non_black or not need_color)
            if is_annot and (not cur or L.y0 - cur[-1].y0 <= join_dy * max(1, len(cur))):
                cur.append(L)
            else:
                if cur:
                    groups.append(cur)
                cur = [L] if is_annot else []
        if cur:
            groups.append(cur)

        form_cfg = recipe["form_name"]
        form = find_form_name(lines, form_cfg, carry)
        got_field = False
        for g in groups:
            oid = alt = None
            for L in g:
                m = oid_rx.match(L.text)
                if m and not oid:
                    oid = m.group(1)
                elif alt_rx:
                    m2 = alt_rx.match(L.text)
                    if m2 and not alt:
                        alt = m2.group(1)
            if fcfg.get("alt_is_primary") and alt:
                oid, alt = alt, oid
            if not oid:
                continue
            # label: nearest non-noise line above the group, same column
            top = g[0]
            cand = [L for L in col
                    if L.y1 <= top.y0 + 2 and top.y0 - L.y0 <= label_max_dy
                    and not re.match(r"^\[.+", L.text) and not _is_noise(L.text, noise)]
            if not cand:
                continue
            cand.sort(key=lambda L: L.y0)
            label_parts = [cand[-1].text]
            # pull preceding wrapped label lines
            k = len(cand) - 2
            while k >= 0 and cand[k + 1].y0 - cand[k].y0 <= join_dy and len(label_parts) < 4:
                label_parts.insert(0, cand[k].text)
                k -= 1
            label = re.sub(r"\s+", " ", " ".join(label_parts)).strip()
            result.records.append(FieldRec(form or "", label, oid, alt, pno + 1))
            got_field = True
        if got_field:
            result.pages_with_fields += 1
        if form:
            carry = form


# --------------------------------------------------------------------------- #
# engine: anchored_blocks (repeated anchor rows delimit per-field blocks)
# --------------------------------------------------------------------------- #
def extract_anchored_blocks(pages, recipe: dict, result: ReplayResult) -> None:
    fcfg = recipe["fields"]
    act_rx = re.compile(fcfg["activity_regex"])
    oid_rx = re.compile(fcfg["oid_regex"])
    ax_min, ax_max = fcfg.get("activity_x", [150, 200])
    line_no_x = fcfg.get("line_number_x_min", 460)

    for pno, lines in pages:
        blocks = []  # (y, form, field)
        for L in lines:
            if not (ax_min <= L.x0 <= ax_max and L.bold):
                continue
            same_row_num = any(abs(o.y0 - L.y0) < 4 and o.x0 >= line_no_x for o in lines)
            m = act_rx.match(L.text)
            if m and same_row_num:
                blocks.append((L.y0, m.group(1).strip(), m.group(2).strip()))
        if not blocks:
            continue
        result.pages_with_fields += 1
        bounds = [b[0] for b in blocks] + [10 ** 9]
        for i, (y, form, fieldname) in enumerate(blocks):
            oids, question = [], ""
            for L in lines:
                if not (y < L.y0 < bounds[i + 1]):
                    continue
                m = oid_rx.search(L.text)
                if m:
                    oids.append(m.group(1))
                elif not question and L.bold and ax_min <= L.x0 <= ax_max + 5:
                    question = L.text.strip()
            for oid in dict.fromkeys(oids) or [None]:
                result.records.append(FieldRec(form, fieldname, oid, None, pno + 1, extra=question))


# --------------------------------------------------------------------------- #
# engine: numbered_join (content pages joined to definition pages by a number)
# --------------------------------------------------------------------------- #
def extract_numbered_join(pages, recipe: dict, result: ReplayResult) -> None:
    fcfg = recipe["fields"]
    form_rx = re.compile(recipe["form_name"]["regex"])
    def_marker = _compile(fcfg["definition_page_all"])
    num_rx = re.compile(fcfg.get("data_number_regex", r"^(\d+)(\.\d+)?$"))
    noise = _compile(fcfg.get("label_noise"))

    data: dict[str, list[tuple[str, str, int]]] = {}   # form -> [(num, label, page)]
    codes: dict[str, dict[str, str]] = {}              # form -> num -> code

    carry = None
    for pno, lines in pages:
        texts = [L.text for L in lines]
        is_def = all(any(rx.search(t) for t in texts) for rx in def_marker)

        form = None
        if not (is_def and fcfg.get("definition_form_from_carry")):
            for L in lines:
                m = form_rx.match(L.text)
                if m:
                    form = m.group(1).strip()
                    break
        if not form and (recipe["form_name"].get("carry_forward") or fcfg.get("definition_form_from_carry")):
            form = carry
        if not form:
            continue

        if is_def:
            result.definition_pages_seen += 1
            _parse_definition_page(lines, fcfg, num_rx, codes.setdefault(form, {}))
        else:
            rows = _parse_content_page(lines, fcfg, num_rx, noise)
            if rows:
                data.setdefault(form, []).extend((n, lbl, pno + 1) for n, lbl in rows)
                result.pages_with_fields += 1
            carry = form  # only content pages define which form a def page belongs to

    for form, rows in data.items():
        cmap = codes.get(form, {})
        for num, label, pno in rows:
            result.records.append(FieldRec(form, label, cmap.get(num), None, pno))


def _parse_definition_page(lines: list[Line], fcfg: dict, num_rx: re.Pattern, out: dict[str, str]) -> None:
    """Rows are keyed by the join number in the left margin (same regex as content
    pages, group 1 = key); the code lives in the column under `oid_header`."""
    anchor = next((L for L in lines if L.text.strip().startswith(fcfg.get("oid_header", "Include"))), None)
    if anchor is None:
        return
    code_x = anchor.x0 - 6
    # right-bound the code column at the next column header on the same header row,
    # otherwise neighbouring cells (e.g. a 'Type' column) get glued onto the code
    right = [L.x0 for L in lines if abs(L.y0 - anchor.y0) < 5 and L.x0 > anchor.x0 + 10]
    code_x_hi = min(right) - 4 if right else 10 ** 9
    num_x_max = fcfg.get("row_number_x_max", 108)
    rows = []
    for L in lines:
        t = L.text.strip()
        # anchors: the recipe's join-key regex, a bare integer, or an integer glued
        # to the first cell fragment on the same extracted line ("10 CSS0203A_")
        m = num_rx.match(t) or re.match(r"^(\d+)$", t) or re.match(r"^(\d+)\s+\S+$", t)
        if m and L.x0 < num_x_max:
            rows.append((L, m.group(1)))
    rows.sort(key=lambda t: t[0].y0)
    header_y = anchor.y0
    gaps = [rows[i + 1][0].y0 - rows[i][0].y0 for i in range(len(rows) - 1)]
    gaps = sorted(g for g in gaps if g > 0)
    typ_gap = gaps[len(gaps) // 2] if gaps else 40.0
    for i, (R, key) in enumerate(rows):
        y_lo = R.y0 - 8
        # bound the last row too, or the page footer gets swept into its code
        y_hi = rows[i + 1][0].y0 - 8 if i + 1 < len(rows) else R.y0 + max(3 * typ_gap, 48)
        parts = [L.text.strip() for L in lines
                 if code_x <= L.x0 < code_x_hi and y_lo <= L.y0 < y_hi and L.y0 > header_y + 5
                 and not re.search(r"\s", L.text.strip())]  # code fragments never contain spaces
        code = "".join(parts).strip()   # codes wrap across lines in narrow columns
        if code:
            out[key] = code


def _parse_content_page(lines, fcfg, num_rx, noise) -> list[tuple[str, str]]:
    num_x_min = fcfg.get("data_number_x_min", 480)
    label_x_max = fcfg.get("data_label_x_max", 320)
    embedded = bool(fcfg.get("number_embedded_in_label"))
    out = []
    for N in lines:
        t = N.text.strip()
        m = num_rx.match(t) if not embedded else num_rx.search(t)
        if not m or N.x0 < num_x_min:
            continue
        if embedded:
            # the join key can sit inside/next to the label line itself
            label = num_rx.sub("", t).strip(" -:\u2013")
            if not re.search(r"[A-Za-z]", label) or _is_noise(label, noise):
                same_row = [L for L in lines
                            if L is not N and abs(L.y0 - N.y0) <= 6 and L.x0 < N.x0
                            and re.search(r"[A-Za-z]", L.text) and not _is_noise(L.text, noise)]
                label = same_row[-1].text.strip() if same_row else ""
            if label:
                out.append((m.group(1), label))
            continue
        cand = [L for L in lines
                if L.x0 <= label_x_max and -8 <= L.y0 - N.y0 <= 16
                and re.search(r"[A-Za-z]", L.text) and not _is_noise(L.text, noise)]
        if cand:
            label = max(cand, key=lambda L: L.y0).text.strip()
            out.append((m.group(1), label))
    return out


# --------------------------------------------------------------------------- #
# engine: column_table (definition tables with a header row)
# --------------------------------------------------------------------------- #
def extract_column_table(pages, recipe: dict, result: ReplayResult) -> None:
    fcfg = recipe["fields"]
    def_marker = re.compile(fcfg["definition_page_regex"])
    row_rx = re.compile(fcfg.get("row_key_regex", r"^\[(\d+)\]$"))
    carry = None

    for pno, lines in pages:
        form_cfg = recipe["form_name"]
        form = find_form_name(lines, form_cfg, None)
        if form:
            carry = form
        if not any(def_marker.match(L.text.strip()) for L in lines):
            continue
        headers = {L.text.strip(): L.x0 for L in lines if L.bold}
        x_name = headers.get(fcfg.get("name_header", "Name"))
        x_oid = headers.get(fcfg.get("oid_header", "Export Name"))
        x_type = headers.get(fcfg.get("type_header", "Type"))
        if x_name is None or x_oid is None:
            continue
        rows = [L for L in lines if row_rx.match(L.text.strip()) and L.x0 < x_name - 5]
        rows.sort(key=lambda L: L.y0)
        got = False
        for i, R in enumerate(rows):
            y_lo, y_hi = R.y0 - 3, (rows[i + 1].y0 - 3 if i + 1 < len(rows) else 10 ** 9)
            names = [L.text.strip() for L in lines if abs(L.x0 - x_name) < 8 and y_lo <= L.y0 < y_hi]
            oid_cands = [L.text.strip() for L in lines
                         if abs(L.x0 - x_oid) < 8 and y_lo <= L.y0 < y_hi
                         and (x_type is None or L.x0 < x_type - 5)]
            if not names or not oid_cands:
                continue
            label = re.sub(r"\s+", " ", " ".join(names)).strip()
            result.records.append(FieldRec(carry or "", label, oid_cands[0], None, pno + 1))
            got = True
        if got:
            result.pages_with_fields += 1


# --------------------------------------------------------------------------- #
# engine: line_pattern (generic fallback for layouts none of the above fit)
# --------------------------------------------------------------------------- #
def extract_line_pattern(pages, recipe: dict, result: ReplayResult) -> None:
    fcfg = recipe["fields"]
    code_rx = re.compile(fcfg["code_regex"])
    label_rx = re.compile(fcfg.get("label_regex", r"^(?=.*[A-Za-z]).{3,140}$"))
    window = fcfg.get("label_window_lines", 4)
    noise = _compile(fcfg.get("label_noise"))
    carry = None
    for pno, lines in pages:
        form = find_form_name(lines, recipe["form_name"], carry)
        if form:
            carry = form
        got = False
        for i, L in enumerate(lines):
            t = L.text.strip()
            m = code_rx.search(t) if fcfg.get("code_search") else code_rx.match(t)
            if not m:
                continue
            label = None
            for j in range(i - 1, max(-1, i - 1 - window), -1):
                cand = lines[j].text.strip()
                if code_rx.search(cand) or _is_noise(cand, noise):
                    continue
                if label_rx.match(cand):
                    label = cand
                    break
            if label:
                result.records.append(FieldRec(form or "", label, m.group(1), None, pno + 1))
                got = True
        if got:
            result.pages_with_fields += 1


ENGINES = {
    "adjacent_annotation": extract_adjacent_annotation,
    "anchored_blocks": extract_anchored_blocks,
    "numbered_join": extract_numbered_join,
    "column_table": extract_column_table,
    "line_pattern": extract_line_pattern,
}


def build_pages(doc, recipe: dict, page_indices=None):
    skip = _compile(recipe.get("skip_page_if"))
    pages = []
    indices = range(doc.page_count) if page_indices is None else page_indices
    for i in indices:
        if i >= doc.page_count:
            continue
        lines = build_page_lines(doc[i])
        if skip and any(_is_noise(L.text, skip) for L in lines[:6]):
            continue
        pages.append((i, lines))
    return pages


def replay(pdf_path: str, recipe: dict, page_indices=None) -> ReplayResult:
    """Execute a recipe. `page_indices` restricts the run (used by the induction
    validator, which replays only the representative pages)."""
    doc = fitz.open(pdf_path)
    pages = build_pages(doc, recipe, page_indices)
    result = ReplayResult(format_id=recipe.get("format_id", "unknown"), pages_total=doc.page_count)
    engine = recipe.get("fields", {}).get("engine")
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}; must be one of {sorted(ENGINES)}")
    ENGINES[engine](pages, recipe, result)
    result.dedup()
    doc.close()
    return result


def detect_format(pdf_path: str, recipes: list[dict], sample_pages: list[int]) -> tuple[dict | None, dict]:
    """Score each recipe's detect markers against the sampled (representative) pages."""
    doc = fitz.open(pdf_path)
    text = "\n".join(doc[p].get_text() for p in sample_pages if p < doc.page_count)
    doc.close()
    scores = {}
    best, best_score = None, 0.0
    for r in recipes:
        det = r.get("detect", {})
        hits = sum(1 for rx in det.get("all", []) if re.search(rx, text))
        need = len(det.get("all", []) or [1])
        score = hits / need
        scores[r["format_id"]] = round(score, 2)
        if score > best_score or (score == best_score and best is None):
            if hits == need:
                best, best_score = r, score
    return best, scores
