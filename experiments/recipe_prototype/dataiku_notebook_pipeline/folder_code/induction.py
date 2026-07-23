"""Stage 1 shared scoring/gates + the LEGACY recipe-induction path.

PRODUCTION-INTENT parts of this module: load_rep_pages, score, gate_problems,
gate_warnings (codegen.py imports them). The recipe/engine-catalog prompt and
induce_recipe below are the LEGACY comparison path - production induction is
codegen.py, where the LLM writes the extraction program itself.

The ONLY prior knowledge is: "this is a CRF". The LLM never gets a list of known
vendor formats. It sees the stage-0 representative pages (structured text dumps
with geometry + font info, optionally page images) and must emit a recipe JSON
that parameterises one of the generic layout engines in replay.py.

Loop (all bounded, all artifacts saved):
  1. build induction prompt from representative pages
  2. LLM -> recipe JSON
  3. validate: replay the recipe over the representative pages only, compute
     quality metrics, and check them against acceptance gates
  4. if gates fail: send the metrics + a sample of the (bad) output back to the
     LLM for ONE revision round (2 attempts total by default)
  5. if still failing: mark document as needs-manual-template (fail loudly)

LLM transport is pluggable:
  - Dataiku LLM Mesh (production; see notebook)
  - local HTTP/CLI shims for testing
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter

from replay import ENGINES, ReplayResult, replay

PROMPT_TEMPLATE = """You are configuring a deterministic PDF extraction engine for a clinical Case Report Form (CRF) document. You will see a small sample of REPRESENTATIVE PAGES (one or two per page-layout cluster) from a document that is {n_pages} pages long. The whole document is repetitive: what you see is representative of everything.

Each page is given as structured text lines with geometry:
    x=<left> y=<top> sz=<font-size> <color> <B if bold> | <text>

# Your task

Produce a JSON "recipe" that tells the engine how to extract, for EVERY field on EVERY page of the document:
  - form_name   : the name of the CRF form/section the field belongs to
  - field_name  : the human-readable field label/question
  - field_oid   : the machine identifier (OID / SAS name / export name / variable
                  code) if the document prints one; null if the document is not
                  annotated with machine codes

# Engines you can parameterise (pick exactly one)

1. "adjacent_annotation" - machine codes are printed on their own annotation lines
   (often bracketed, often colored) directly next to/under the field label, in the
   same column. Params: column_x_max, oid_regex (capture group 1 = code),
   alt_regex/alt_is_primary (a second code on nearby lines), oid_color_non_black,
   annotation_group_dy, label_max_dy, label_noise (regexes for lines that are
   never labels).
2. "anchored_blocks" - each field starts at a repeated anchor row (e.g. a bold
   'Prefix: Activity #1' line with a number in a far-right column); everything
   until the next anchor belongs to that field. Params: activity_regex (group 1 =
   form, group 2 = field), activity_x [min,max], line_number_x_min, oid_regex.
3. "numbered_join" - two page types per form: content pages print each label with
   a join number, definition pages map the same numbers to codes in a column
   under a header. Params: definition_page_all (regexes that all appear on
   definition pages), oid_header (text of the column header the codes sit under),
   row_number_x_max (join keys on definition pages must start left of this),
   data_number_regex (group 1 = join key; same regex applies on BOTH page types),
   data_number_x_min, data_label_x_max, label_noise,
   number_embedded_in_label (true when the join key is printed on/next to the
   label line itself, e.g. 'Consent Date  [2]', rather than in a separate far
   column; the engine then searches the regex inside lines right of
   data_number_x_min and takes the remaining text on that row as the label),
   definition_form_from_carry (true when definition pages do NOT print the form
   name; they are then attributed to the most recent content-page form).
   form_name.strategy must be "regex" for this engine (carry_forward supported).
4. "column_table" - definition tables with an explicit header row; label and code
   are cells of configurable columns. Params: definition_page_regex, row_key_regex,
   name_header, oid_header, type_header.
5. "line_pattern" - fallback: a code regex over lines, label = nearest previous
   line matching label_regex within label_window_lines. Params: code_regex,
   code_search (true = search inside line), label_regex, label_window_lines,
   label_noise.

# form_name strategies

- {{"strategy":"regex","regex":"^Form:\\\\s*(.+)$"}} - a header line matches a regex (group 1 = name)
- {{"strategy":"colored_font","min_size":14,"carry_forward":true,"noise":[...]}} - the form title is the big colored heading; carry_forward repeats the last seen title on continuation pages
- {{"strategy":"font","min_size":14,"carry_forward":true,"noise":[...]}} - same but title is not colored
- for engine anchored_blocks the form name comes from activity_regex group 1 automatically

# Output format (JSON only, no prose)

{{
  "format_id": "<short slug you invent>",
  "reasoning": "<2-4 sentences: what layout you saw and why you chose the engine>",
  "detect": {{"all": ["<2-3 regexes that identify this layout>"]}},
  "skip_page_if": ["<optional regexes: pages to skip entirely (title/TOC/approval)>"],
  "form_name": {{...}},
  "fields": {{"engine": "<one of the 5>", ...params...}}
}}

# Rules

- Regexes are Python re syntax inside JSON strings (escape backslashes).
- Codes are machine identifiers like AESTDAT / QVAL_GENDOTH - short, uppercase,
  underscores/digits allowed. Human text, dates and option values are NOT codes.
- Prefer the most specific engine that fits; use line_pattern only if nothing fits.
- If the document prints NO machine codes at all, still extract form_name +
  field_name (choose the engine that best yields labels; oid_regex may then match
  nothing) and say so in "reasoning".
- Numbers like x/y/size in the dumps are points; use them to set column bounds.

# Representative pages

{pages}
"""

REVISION_TEMPLATE = """Your previous recipe was executed on the SAME representative pages. It did not pass the quality gates.

Previous recipe:
{recipe}

Execution metrics:
{metrics}

Sample of extracted records (form_name | field_name | field_oid):
{sample}

Problems to fix (in priority order):
{problems}

Emit a corrected recipe now. Same output format: JSON only, no prose. You may switch engine entirely.
"""


def _family_letter(i: int) -> str:
    """0 -> A, 1 -> B, ... 26 -> AA (documents can exceed 26 families)."""
    letters = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        letters = chr(ord("A") + r) + letters
    return letters


def load_rep_pages(outdir: str, max_chars_per_page: int = 6000,
                   only_pages: list[int] | None = None) -> tuple[str, list[int]]:
    """Concatenate the stage-0 representative page dumps for the prompt,
    labeled by LAYOUT FAMILY (stage-0 cluster).

    Family labels exist so the model can mirror the document's real structure
    in its program (one handler per family) and can see that several sample
    pages are THE SAME layout: without the grouping, a model shown four pages
    of one family and two of another tends to write one global rule set whose
    thresholds fit some families and silently drop others. The letters are
    positional (assigned in sample order), carry no meaning, and are computed
    from this document's own clustering - nothing corpus-specific.

    The per-page cap of 6000 chars keeps dense pages whole: at the previous
    3600, ~30% of representative pages lost their bottom third (exactly where
    per-page answer blocks live), so the model was coding blind against
    regions the audit then judged it on.

    only_pages (1-based, optional): show these rep pages instead of the
    budgeted representative_pages_1based list - the multi-pass specialist
    path, where each pass sees its own clusters' representatives (stage 0
    dumps a rep for every content cluster since the multi-pass change).
    Family letters are then assigned within the shown subset."""
    with open(os.path.join(outdir, "clusters.json"), encoding="utf-8") as f:
        meta = json.load(f)
    reps = sorted(only_pages) if only_pages is not None else meta["representative_pages_1based"]
    clusters = meta["clusters"]

    def cluster_of(p: int) -> int | None:
        return next((ci for ci, c in enumerate(clusters)
                     if p - 1 in (c.get("representatives") or [])), None)

    fam_of_cluster: dict[int, str] = {}   # cluster index -> letter, sample order
    fam_pages: dict[str, list[int]] = {}  # letter -> shown pages
    fam_size: dict[str, int] = {}
    header: dict[int, str] = {}
    n_fams = 0
    for p in reps:
        ci = cluster_of(p)
        fam = fam_of_cluster.get(ci) if ci is not None else None
        if fam is None:  # first page of this cluster (or metadata-less rep)
            fam = _family_letter(n_fams)
            n_fams += 1
            if ci is not None:
                fam_of_cluster[ci] = fam
        size = clusters[ci]["n_pages"] if ci is not None else 1
        fam_pages.setdefault(fam, []).append(p)
        fam_size[fam] = size
        header[p] = f"--- page {p} of {meta['pages']} | layout family {fam} (~{size} pages) ---"

    intro = ["The document's pages cluster into structural LAYOUT FAMILIES "
             "(computed from this document itself). The sample below shows:"]
    for fam in sorted(fam_pages, key=lambda f: fam_pages[f][0]):
        pages_s = ", ".join(str(p) for p in fam_pages[fam])
        intro.append(f"  family {fam} (~{fam_size[fam]} pages of the document)"
                     f" - sample pages {pages_s}")
    intro.append(
        "Pages of one family share the same structural layout, but instances "
        "may drift in absolute font sizes, positions and wording - what all "
        "of a family's sample pages have in COMMON is what defines it. A few "
        "small families may have no sample here.")

    blocks = []
    for p in reps:
        path = os.path.join(outdir, f"rep_p{p}.txt")
        with open(path, encoding="utf-8") as f:
            body = f.read()
        if len(body) > max_chars_per_page:
            body = body[:max_chars_per_page] + "\n<...page truncated...>\n"
        blocks.append(f"{header[p]}\n{body}")
    return "\n".join(intro) + "\n\n" + "\n".join(blocks), [p - 1 for p in reps]


def load_title_context_pages(outdir: str, max_chars_per_page: int = 4000) -> str:
    """Load stage-0's independent title-context pack.

    These are NOT layout representatives and must not alter family ownership,
    coverage accounting or specialist masking. They are pages where repeated
    top-of-page context differs across the document, supplied only so the model
    can learn which printed string groups fields and how that title is carried.
    Older metadata has no channel and returns an explicit absence note.
    """
    with open(os.path.join(outdir, "clusters.json"), encoding="utf-8") as f:
        meta = json.load(f)
    pages = meta.get("title_context_pages_1based") or []
    if not pages:
        return (
            "No additional title-context pages were selected. Do not invent a "
            "title: infer it only from printed grouping context visible in the "
            "layout-family samples, and carry it forward when appropriate.")
    blocks = [
        "These pages are TITLE/FORM CONTEXT ONLY, selected independently from "
        "the layout families because representative field pages can all be "
        "continuations. Repeated invariant text may be page chrome OR a document-"
        "wide title; changing text that persists over a run of pages may be a form/"
        "section title. Treat both as candidates, then use structural prominence "
        "and whether the text actually groups multiple fields to identify the title. "
        "Learn its position/style and carry it forward. Do not treat per-field "
        "subsection labels or technical annotations as titles."
    ]
    for p in pages:
        path = os.path.join(outdir, f"title_p{p}.txt")
        if not os.path.isfile(path):  # tolerate partial/legacy artifacts
            continue
        with open(path, encoding="utf-8") as f:
            body = f.read()
        if len(body) > max_chars_per_page:
            body = body[:max_chars_per_page] + "\n<...page truncated...>\n"
        blocks.append(f"--- title-context page {p} of {meta['pages']} "
                      "(not a layout-family representative) ---\n" + body)
    return "\n\n".join(blocks)


def parse_recipe(raw: str) -> dict:
    """First complete JSON object in an LLM reply. Balanced parse (raw_decode) -
    a greedy `\\{.*\\}` regex would span from the first to the LAST brace and be
    corrupted by prose containing braces around the payload."""
    dec = json.JSONDecoder()
    idx = raw.find("{")
    while idx != -1:
        try:
            out, _ = dec.raw_decode(raw, idx)
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass
        idx = raw.find("{", idx + 1)
    raise ValueError("no JSON object in LLM reply")


# --------------------------------------------------------------------------- #
# quality gates - two tiers, both computed on the FULL-document run:
#   gate_problems  = contract blockers (program is effectively not working)
#   gate_warnings  = quality signals; they drive revision rounds but must never
#                    permanently reject a document (a legitimately form-dense or
#                    label-sparse CRF may violate them while being correct - the
#                    grounded audit round judges real quality per page)
# --------------------------------------------------------------------------- #
CODE_SHAPE = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")


def score(result: ReplayResult, engine: str) -> dict:
    recs = result.records
    n = len(recs)
    m = {
        "engine": engine,
        "records": n,
        "pages_total": result.pages_total,
        "pages_with_fields": result.pages_with_fields,
        "definition_pages_seen": result.definition_pages_seen,
        "forms_nonempty_pct": round(100 * sum(1 for r in recs if r.form_name.strip()) / n) if n else 0,
        # contract-level shape check only: has letters (any script/case), sane length,
        # not a single machine-code token. Floor is 2 chars: many CJK labels are two
        # characters (e.g. two-ideograph words); 1 char is still junk in any script.
        # The code-shape exclusion additionally requires a digit or underscore:
        # a bare ALL-CAPS word ("AGE", "SEVERITY") is a legitimate caps-styled
        # label in many books, and this is a warning metric - a false "junk"
        # verdict on caps-label documents costs pointless revision rounds.
        "labels_look_human_pct": round(100 * sum(
            1 for r in recs
            if re.search(r"[^\W\d_]", r.field_name) and 2 <= len(r.field_name) <= 200
            and not (CODE_SHAPE.match(r.field_name.strip())
                     and re.search(r"[\d_]", r.field_name))) / n) if n else 0,
        # oid metrics are LEGACY (recipe/engine path extracted OIDs; codegen scope
        # is form+field only, where these are always 0) - kept for the comparison path
        "oids_present_pct": round(100 * sum(1 for r in recs if r.field_oid) / n) if n else 0,
        "oids_look_like_codes_pct": round(100 * sum(
            1 for r in recs if r.field_oid and CODE_SHAPE.match(r.field_oid.strip())) /
            max(1, sum(1 for r in recs if r.field_oid))),
        "distinct_forms": len({r.form_name.strip().lower() for r in recs if r.form_name.strip()}),
    }
    # density per page is a property of the document, never gated; the
    # fields-per-form RATIO is gated in gate_problems (only at the definitional
    # extreme: an average "form" of <2 fields is not a grouping at all)
    m["fields_per_form"] = round(n / max(1, m["distinct_forms"]), 1)
    m["forms_per_100_pages"] = round(100 * m["distinct_forms"] / max(1, result.pages_total), 1)
    # A real form title normally persists across multiple fields on the same
    # field-bearing page. Measure that directly instead of inferring persistence
    # only from a document-wide form/record ratio. Pages with one record provide
    # no evidence either way and are excluded from the denominator.
    page_forms: dict[int, Counter] = {}
    for r in recs:
        form = r.form_name.strip().casefold()
        if r.page and form:
            page_forms.setdefault(r.page, Counter())[form] += 1
    persistence_evidence = 0
    persistent_records = 0
    for counts in page_forms.values():
        page_records = sum(counts.values())
        if page_records < 2:
            continue
        persistence_evidence += page_records
        persistent_records += sum(c for c in counts.values() if c >= 2)
    m["form_same_page_evidence_records"] = persistence_evidence
    m["form_same_page_persistence_pct"] = round(
        100 * persistent_records / persistence_evidence
    ) if persistence_evidence else None
    # furniture candidates: a field_name extracted on >=70% of ALL pages of a
    # sizeable document is almost always page template chrome (watermark, footer,
    # stamp) rather than a field. Derived from THIS document's own repetition -
    # no vocabulary, no corpus statistics. The 70% floor is deliberately above
    # what repeated real fields reach (diary/grid questions recur on many pages,
    # but not on front matter, TOCs and other forms' pages).
    if result.pages_total >= 30 and n:
        pages_by_name: dict[str, set] = {}
        display: dict[str, str] = {}
        for r in recs:
            if r.page:
                key = r.field_name.strip().casefold()
                pages_by_name.setdefault(key, set()).add(r.page)
                display.setdefault(key, r.field_name.strip())
        floor = 0.7 * result.pages_total
        m["furniture_candidates"] = sorted(
            display[k] for k, pgs in pages_by_name.items() if len(pgs) >= floor)[:5]
    else:
        m["furniture_candidates"] = []
    return m


def gate_problems(m: dict) -> list[str]:
    """Contract blockers only: the program crashed upstream, its output is so
    small it is effectively not extracting, or the output violates a DEFINITIONAL
    property of the contract. Nothing here encodes corpus statistics.

    The <5-records floor applies only to documents of >=20 pages: on a big book
    it means the program is broken, but a 1-2 page CRF can legitimately carry
    3 fields total, and a hard gate would flag every version of a correct
    program as needs_manual_template. Tiny-document low volume is a warning
    (gate_warnings) so the audit still scrutinizes it.

    The degenerate-grouping gate is likewise definitional, not statistical: a
    form/section title GROUPS fields - that is what makes it a title. When the
    average "form" holds fewer than 2 fields across a sizeable output, form_name
    is per-field text (each field's own label, code, or technical annotation),
    which no real document's form structure can produce. The >=20-records floor
    keeps genuinely tiny documents (where one-field sections are plausible) in
    the warning tier instead."""
    problems = []
    if m["records"] == 0:
        problems.append("The program extracted ZERO records from the document.")
        return problems
    if m["records"] < 5 and m["pages_total"] >= 20:
        problems.append(f"Only {m['records']} records from a {m['pages_total']}-page document - the program is effectively not extracting.")
    if m["records"] >= 20 and m.get("distinct_forms", 0) * 2 > m["records"]:
        problems.append(
            f"Degenerate form grouping: {m['distinct_forms']} distinct form_names for "
            f"{m['records']} records. A form/section title groups MANY fields by "
            "definition, so these form_name values are per-field text (each field's "
            "own label, a machine code, or a per-field technical annotation), not the "
            "printed title. Extract the title that heads the form/section - shared by "
            "the fields it groups and carried across the form's continuation pages - "
            "never text attached to a single field.")
    if m["records"] and not m["pages_with_fields"]:
        # contract: every record carries page (int, 1-based). Without valid pages
        # the output cannot be page-audited or coverage-checked at all.
        problems.append("Records carry no valid 1-based `page` numbers - the `page` "
                        "field of every returned record must be the page the field "
                        "appears on.")
    return problems


def gate_warnings(m: dict) -> list[str]:
    """Quality signals fed back to the revision loop. A document may legitimately
    violate these (unlabeled forms, very short labels, dense form books), so after
    the revision budget is exhausted the best warning-only attempt is still
    accepted - final quality judgment belongs to the grounded audit."""
    warnings = []
    if 0 < m["records"] < 5 and m["pages_total"] < 20:
        warnings.append(f"Only {m['records']} records from this {m['pages_total']}-page "
                        "document - plausible for a document this small, but make sure "
                        "no fields were missed.")
    if m["forms_nonempty_pct"] < 70:
        warnings.append(f"form_name empty for {100 - m['forms_nonempty_pct']}% of records - if the document does print form/section names, fix the form_name strategy (consider carrying the last seen title forward).")
    if m["labels_look_human_pct"] < 60:
        warnings.append(f"Only {m['labels_look_human_pct']}% of field_name values look like human labels (they look like codes/dates/junk) - fix label selection.")
    if m["oids_present_pct"] > 0 and m["oids_look_like_codes_pct"] < 80:
        warnings.append(f"Extracted field_oid values often don't look like machine codes ({m['oids_look_like_codes_pct']}% ok) - tighten oid_regex.")
    if m["engine"] == "numbered_join" and m["definition_pages_seen"] > 0 and m["oids_present_pct"] < 10:
        warnings.append(
            f"{m['definition_pages_seen']} definition pages were detected but codes were joined to only "
            f"{m['oids_present_pct']}% of labels. "
            "The join is broken: check data_number_regex (group 1 must capture the SAME key on both page types), "
            "row_number_x_max, oid_header, and consider number_embedded_in_label:true (key printed on the label line) "
            "or definition_form_from_carry:true (definition pages don't print the form name; attribute them to the "
            "most recent content-page form).")
    # fine-grained-forms advice band: avg <4 fields per "form" is suspicious on
    # any document (short 2-3 field forms exist; whole books averaging under 4
    # deserve a look), but only avg <2 violates the grouping definition - that
    # case is a HARD gate in gate_problems, so it is excluded here to avoid
    # double messaging. Tiny outputs (<20 records) always stay in this advice
    # tier: one-field sections are plausible on small documents.
    if m["distinct_forms"] > max(10, m["records"] // 4) and not (
            m["records"] >= 20 and m["distinct_forms"] * 2 > m["records"]):
        warnings.append(
            f"{m['distinct_forms']} distinct form_names for {m['records']} records - check whether form detection "
            "is picking up field labels or body text as form names; if so, make the form_name pattern stricter "
            "(font size / color / position) or carry the last seen title forward. If the document genuinely has "
            "this many forms, keep it as is.")
    persistence = m.get("form_same_page_persistence_pct")
    evidence = m.get("form_same_page_evidence_records", 0)
    if evidence >= 20 and persistence is not None and persistence < 50:
        warnings.append(
            f"Only {persistence}% of the {evidence} records on multi-field pages "
            "reuse a form_name used by another field on that page. A form/section "
            "title normally persists across the fields it groups; per-field labels "
            "or annotations do not. Detect the shared printed heading structurally "
            "and carry it across continuation pages. If this document genuinely "
            "prints many one-field forms, keep the extraction unchanged.")
    if m.get("furniture_candidates"):
        shown = "; ".join(repr(s) for s in m["furniture_candidates"])
        warnings.append(
            f"These field_name values were extracted on >=70% of ALL pages: {shown}. "
            "Text recurring on nearly every page is usually page template furniture "
            "(watermark/footer/stamp), not a field - verify against the page dumps and "
            "stop extracting it unless it is genuinely a per-page data-entry field.")
    return warnings


def validate_recipe(pdf_path: str, raw_reply: str) -> dict:
    """Parse a reply, replay it over the FULL document (fast - no LLM), and gate.
    Full-document validation matters: representative pages alone can miss a broken
    join (e.g. definition pages present but codes never attached)."""
    try:
        recipe = parse_recipe(raw_reply)
        result = replay(pdf_path, recipe)
        metrics = score(result, recipe.get("fields", {}).get("engine", "?"))
        # legacy path keeps the old strict behavior: warnings block acceptance too
        problems = gate_problems(metrics) + gate_warnings(metrics)
        sample = "\n".join(f"{r.form_name} | {r.field_name} | {r.field_oid}"
                           for r in result.records[:25]) or "(none)"
    except Exception as e:
        recipe, result = None, None
        metrics, problems, sample = {"error": str(e)}, [f"Recipe failed to execute: {e}"], "(none)"
    return {"recipe": recipe, "result": result, "metrics": metrics,
            "problems": problems, "sample": sample}


def build_revision_prompt(raw_reply: str, verdict: dict) -> str:
    return REVISION_TEMPLATE.format(
        recipe=json.dumps(verdict["recipe"], indent=1) if verdict["recipe"] else raw_reply[:2000],
        metrics=json.dumps(verdict["metrics"], indent=1),
        sample=verdict["sample"],
        problems="\n".join(f"- {p}" for p in verdict["problems"]),
    )


def induce_recipe(pdf_path: str, outdir: str, call_llm, max_attempts: int = 3) -> dict:
    """call_llm: fn(prompt:str) -> str. Returns dict with recipe/metrics/attempts."""
    import fitz
    pages_text, _ = load_rep_pages(outdir)
    n_pages = fitz.open(pdf_path).page_count
    prompt = PROMPT_TEMPLATE.format(n_pages=n_pages, pages=pages_text)

    trail = []
    for attempt in range(1, max_attempts + 1):
        raw = call_llm(prompt)
        verdict = validate_recipe(pdf_path, raw)
        trail.append({"attempt": attempt, "raw_reply": raw, "recipe": verdict["recipe"],
                      "metrics": verdict["metrics"], "problems": verdict["problems"]})
        if not verdict["problems"]:
            return {"status": "ok", "recipe": verdict["recipe"], "attempts": trail}
        prompt = build_revision_prompt(raw, verdict)
    return {"status": "needs_manual_template", "recipe": None, "attempts": trail}
