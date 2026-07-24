"""Format-agnostic induction via CODE GENERATION - no strategy catalog, no few-shots.

Scope: form_name + field_name only. Printed machine codes are NOT extracted;
OID resolution happens downstream by name mapping against the rule library.

The LLM sees ONLY:
  - the task (extract form_name / field_name for every field)
  - the input data schema (Line objects with geometry/font attributes)
  - the output contract (function signature + record dict shape)
  - generic quality constraints (the same ones the gates check)
  - the stage-0 representative pages of THIS document

It must write the extraction program itself. Nothing in the prompt encodes layout
knowledge from any particular CRF vendor or sample. Generated code runs in a
separate killable process (sandbox_runner.py) and is only accepted if it passes
full-document contract gates; gate warnings and per-cluster coverage go back to
the LLM for a bounded revision loop.
"""
from __future__ import annotations

import ast
import collections
import json
import os
import re
import subprocess
import sys
import tempfile

import fitz

from common import art, build_page_lines
from induction import (gate_problems, gate_warnings, load_rep_pages,
                       load_title_context_pages, score)
from replay import FieldRec, ReplayResult

HERE = os.path.dirname(os.path.abspath(__file__))

CODEGEN_PROMPT = """You are writing a deterministic extraction program for one specific clinical Case Report Form (CRF) PDF document. Below you will find a small sample of REPRESENTATIVE PAGES (one or two per page-layout cluster) from a document that is {n_pages} pages long. The document is highly repetitive: the sampled pages cover its layouts, but the unsampled pages contain different content in the same layouts.{scope_note}

Each sampled page is shown as structured text lines with geometry:
    x=<left> y=<top> sz=<font-size> <color-hex or 'black'> <B if bold> | <text>

# Your task

Write a Python function that will run UNCHANGED over all {n_pages} pages and extract every data-entry field of the CRF:
  - form_name : the CRF form/section the field belongs to
  - field_name: the human-readable field label/question

That is the complete output. Some CRFs also print machine codes or technical
annotations near fields - do NOT return those (they are resolved downstream by a
separate system). You may still USE such markings as structural landmarks if that
helps you locate fields reliably.

# Runtime contract

def extract(pages):
    # pages: list of (page_index_0based, lines) tuples for the ENTIRE document, in
    #        page order. lines is a list of Line objects sorted by y, then x.
    #        NOTE: y-then-x order is NOT reading order on multi-column pages; if the
    #        layout has side-by-side columns, use x coordinates to separate them.
    #        For right-to-left scripts the within-row order is right-to-left, and
    #        vertical text yields an arbitrary line order - reconstruct reading
    #        order from the coordinates when the script needs it.
    # Line attributes:
    #   .text  (str, stripped visible text of one visual line)
    #   .x0 .y0 .x1 .y1  (floats; PDF points; origin = top-left of the page)
    #   .size  (float; font size in points; the largest span on the line)
    #   .bold  (bool)
    #   .non_black  (bool; True if any text on the line is printed in color)
    # returns: list of dicts, one per extracted field occurrence:
    #   {{"form_name": str, "field_name": str, "page": int_1based}}

# Hard constraints

- Pure computation only. These modules are already available: re, math, collections,
  itertools, functools, string, unicodedata, bisect, statistics, json, typing,
  dataclasses, enum, datetime. You may not import anything else, access
  files/network, or print.
- Deterministic, fast, simple: loops, regexes, coordinate arithmetic. It must
  process all {n_pages} pages in seconds.
- Generalize from STRUCTURE, not content. The unsampled pages contain questions,
  values and section names you have never seen. Never key your logic on specific
  question wording from the samples; key it on geometry (x positions, font sizes,
  color, boldness), on repeated marker/header patterns, and on the SHAPE of text
  (regexes over character classes). The document may be in any language.
- Geometry generalizes only when it is RELATIVE and TOLERANT. A family's
  instances drift in absolute numbers across a big document (a label font shown
  at one size in the samples prints slightly smaller or larger elsewhere), so
  prefer comparisons against the page's own scale - size ranks (title vs label
  vs body), "distinctly larger/smaller than" - and give absolute windows real
  slack. Verify every threshold against ALL sample pages of the family it
  serves: a cutoff that excludes one of its own family's samples is wrong.
- Junk filtering must be structural too. Never enumerate literal text strings
  (blocklists of answer options, column headers, known non-fields): unsampled
  pages carry the same junk CLASSES with different wording, so a blocklist
  both misses them and deletes real fields that happen to share the words.
  Find the discriminator instead - answer options sit in an option column/row
  under their field, column headers sit in a table's header band, furniture
  repeats at a fixed position page after page. Literal matching is appropriate
  only for the document's own repeated TEMPLATE markers used as landmarks.
- Do not discard whole pages with statistical heuristics (text density, line
  counts). Skip a page only on structural evidence of its TYPE (it matches a
  recognized non-form template); when unsure, extract - a wrongly read page
  costs a few junk records, a wrongly skipped page loses every field on it.
- You may keep state across pages (the function receives the whole document) -
  e.g. a form name announced once may govern many following pages.

# Program architecture

The representative pages below are labeled by LAYOUT FAMILY to expose meaningful
structural variation, but a cluster label is evidence, not an implementation
requirement. When families have genuinely different field-bearing structures,
use small family handlers dispatched by tolerant structural signatures. When
families differ only in incidental styling or content volume, prefer one shared
handler. Do not force one handler per cluster. Check every chosen handler against
all relevant samples. Pages matching no signature must not be silently skipped -
route them through the closest compatible handler or a tolerant generic path.

# Quality bar (your program's output is machine-checked before acceptance)

- It must extract from every page that carries fields, not just the sampled ones.
- form_name should be non-empty for the large majority of records. Use form/section
  titles exactly as printed - do not invent, abbreviate, or reformat them. If the
  document genuinely prints no form/section names, use the best available section
  context; leave it empty only as a last resort.
- form_name is the title printed FOR HUMAN READERS that heads the form/section: a
  grouping shared by all of that form's fields, usually repeated or carried forward
  across the form's continuation pages. Never build form_name from text attached to
  one individual field - the field's own label, a machine code, or a per-field
  technical annotation. Structural self-check: if nearly every record ends up with
  its own unique form_name, the program is reading per-field text, not form titles.
- field_name values must be human-readable label text - not machine codes, bare
  numbers, dates, or page furniture (headers/footers/page numbers/watermarks/
  legends).
- A label/question may WRAP across several visual lines: join its continuation
  lines into ONE field_name. Sentence fragments are not separate fields.
- Answer OPTIONS are not fields: choice values (e.g. Yes / No / Unknown / list
  items - examples here are English, apply the concept in the document's language)
  belong to a field, they are not field_name records themselves. The same applies
  to rating-scale anchor rows that merely explain what each numeric value means.
- Rows of a printed reference or enumeration table (a list of items with no
  per-row entry cell to fill in) are page content, not data-entry fields. A table
  row IS a field when the row has its own cell to be filled per row - such a cell
  may be a drawn blank box that prints no text.
- No duplicate records for the same (form_name, field_name) pair beyond what the
  document itself repeats.

# Reply format

Answer in TWO parts, in this order, in one reply:

1. STRATEGY (plain language, NO code). Begin with a line "STRATEGY:" then 6-12
   short sentences describing the GENERAL extraction logic you will implement -
   rules meant to hold over the pages you were NOT shown, not a description of the
   sampled pages. Decide the approach in words first; that is the point of this
   step. Commit explicitly to:
     - how you locate the form/section title, AND what you do on pages where the
       title is absent, smaller, or positioned differently. A form runs across
       many pages, so most pages will NOT reprint the title: state how you carry
       the current title forward instead of skipping a page that lacks one.
     - how you tell a data-entry field from an answer option, a reference or
       enumeration table row, and page furniture - by geometry, style and
       position, never by specific wording.
     - how you ensure every content-bearing page that holds fields yields them
       (no whole-page skips keyed on a single cue such as one font size, one
       y-position, or one wording).

2. CODE. Then give the program as a SINGLE ```python fenced code block: open with
   a short comment (2-4 lines) noting the layout you observed, then define
   extract(pages) plus any helpers. Put NO prose outside this block. The code
   must implement the STRATEGY above.

# Representative pages of this document

{pages}

# Independent title/form context

{title_context}
"""

CODE_REVISION_TEMPLATE = """Your extraction program was executed over the FULL document. It did not pass the quality gates.{scope_note}

Your previous program:
{code}

Execution metrics:
{metrics}

Sample of extracted records (pN: form_name | field_name):
{sample}

Problems to fix (in priority order):
{problems}
{cluster_feedback}
Rewrite the program now, in the SAME two-part reply format: FIRST a short
"STRATEGY:" section in plain language (no code) stating how this revision handles
the form/section title - including pages where the title is absent, smaller, or
placed differently, via carrying the current title forward - how it separates
data-entry fields from options / table rows / furniture structurally, and how it
covers every content-bearing page; THEN the program as a SINGLE ```python fenced
code block defining extract(pages).
Where your program already works, EXTEND it rather than rewriting it - do not lose
coverage on pages that were extracting correctly. Different page layouts may need
different handling inside the same extract() function.
The original task contract applies unchanged: every data-entry field's form_name +
field_name; human-readable labels only - never machine codes, answer options or
rating anchors, filled values, or repeated page furniture; a label wrapped over
several lines is ONE field; form_name is the printed form/section TITLE shared by
that form's fields - never text attached to a single field (its own label, a code,
or a per-field technical annotation).
Generalize structurally, as before: geometry relative to the page's own scale
with real slack (absolute cutoffs fitted to the sample pages drop the same
layout printed slightly differently elsewhere); junk excluded by its structural
class (position/style/column), NEVER by blocklisting literal strings; no
whole-page skips on density heuristics.
"""

CLUSTER_FEEDBACK_TEMPLATE = """
# Per-layout coverage

Pages of this document are grouped into layout clusters (pages whose structural
layout profiles are similar).
Coverage of your program per cluster (clusters your program extracted nothing or
little from are the ones to investigate):

{table}

# Sample pages from poorly-covered parts of the document (you have NOT seen these before)

If these pages contain data-entry fields, add handling for their layout. If they
genuinely carry no fields (title/instructions/legend pages), ignore them - zero
coverage there is correct.

{failing_pages}
"""

COVERAGE_CONFIRM_TEMPLATE = """You previously wrote the extraction program below for a clinical CRF PDF (task: extract form_name + field_name for every data-entry field; form_name = the printed form/section title, field labels only - never machine codes, answer options, or page furniture). It passed the aggregate quality gates, but substantial parts of the document produced ZERO records. Below are sample pages from those parts (you have not seen these pages before).{scope_note}

Your current program:
{code}

For each sampled page decide: does this layout carry data-entry fields your program is missing, or is it genuinely field-free (title/TOC/instructions/definitions-only pages)?

{cluster_feedback}

Reply with EXACTLY one of:
- the single line: CONFIRM_NO_FIELDS
  (meaning: all shown layouts are genuinely field-free; the program is complete), or
- an EXTENSION, in the same two-part format as before: FIRST a short "STRATEGY:"
  section in plain language (no code) saying what field-bearing structure you now
  see on these pages, how you will locate their form/section title - including
  pages that do not reprint it, which you handle by carrying the current title
  forward rather than skipping the page - and how you separate their fields from
  options / table rows / furniture structurally; THEN the FULL updated program as
  a SINGLE ```python fenced code block defining extract(pages), keeping existing
  behavior for covered layouts and ADDING handling for the missed ones.
"""

_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)


def _parses(src: str) -> bool:
    try:
        ast.parse(src)
        return True
    except SyntaxError:
        return False


def extract_source(raw: str) -> str:
    """Extract the program from a model reply.

    Handles three shapes: (1) a fenced ```python block - the largest wins;
    (2) bare source (returned verbatim, including any leading module-level
    constants); (3) the STRATEGY-then-code reply format, where a plain-language
    section precedes UNFENCED code. Case (3) is detected by parseability: valid
    bare source is returned untouched, and only when the whole text does NOT
    parse do we drop leading lines until the remainder is valid Python (the
    prose stripped away). This never discards real top-level code the way a
    keyword-anchored heuristic would."""
    blocks = _FENCE.findall(raw)
    if blocks:
        return max(blocks, key=len).strip()
    text = raw.strip()
    if not text or _parses(text):
        return text
    lines = text.splitlines()
    for i in range(1, len(lines)):
        cand = "\n".join(lines[i:]).strip()
        if cand and _parses(cand):
            return cand
    return text


def run_extractor(source: str, pdf_path: str, timeout_s: int = 300) -> ReplayResult:
    """Run generated code over the whole document in a SEPARATE process.

    The child (sandbox_runner.py) restricts the namespace; the process boundary is
    what makes a runaway program killable and keeps every run's module state fresh
    (an in-process thread can be neither killed nor isolated - in a long-lived
    notebook kernel that leaks CPU and cross-document state)."""
    src_file = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                           encoding="utf-8", dir=HERE)
    try:
        src_file.write(source)
        src_file.close()
        proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "sandbox_runner.py"), src_file.name, pdf_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=HERE)
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise TimeoutError(f"generated extractor exceeded {timeout_s}s") from None
    finally:
        try:
            os.unlink(src_file.name)
        except OSError:
            pass

    if proc.returncode != 0:
        raise RuntimeError("extractor process died "
                           f"(exit {proc.returncode}): {err.decode('utf-8', 'replace')[:800]}")
    try:
        payload = json.loads(out.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        raise RuntimeError(f"extractor process produced no valid output: {out[:400]!r}")
    if "error" in payload:
        raise RuntimeError(f"generated extractor crashed:\n{payload['error']}")

    raw = payload["records"]
    n_pages = payload["n_pages"]
    result = ReplayResult(format_id="codegen", pages_total=n_pages)
    malformed = 0
    for item in raw:
        if item is None or not str(item.get("field_name", "")).strip():
            malformed += 1
            continue
        try:
            page = int(item.get("page") or 0)
        except (TypeError, ValueError):
            page = 0
        # out-of-range pages are invalid, not "extra coverage": they would
        # inflate pages_with_fields (poisoning version_score / the improves()
        # coverage guard) and crash the audit's doc[p - 1] page lookup
        if not 1 <= page <= n_pages:
            page = 0
        result.records.append(FieldRec(
            form_name=str(item.get("form_name") or "").strip(),
            field_name=str(item["field_name"]).strip(),
            field_oid=None,  # out of extraction scope; resolved downstream by name
            page=page,
        ))
    result.covered_pages = {r.page - 1 for r in result.records if r.page}
    result.pages_with_fields = len(result.covered_pages)
    result.dedup()
    if malformed > max(5, len(raw) // 10):
        raise ValueError(f"{malformed} of {len(raw)} returned records were malformed "
                         "(not a dict, or empty field_name)")
    return result


# Inserted into TAIL-SPECIALIST prompts only (plan_passes split the document's
# layout families across several programs; the MAIN pass gets no note - its
# prompt is identical to the single-pass one). Deliberately HARNESS-DESCRIPTIVE
# rather than behavior-restricting: an instruction like "extract only your
# layout families" makes literal-minded models write narrow rep-matching
# parsers, which collapsed v1 multi-pass coverage on fragmented books (5% vs
# 88% for the same model without the note). Ownership is enforced by masking,
# so the note states the safe asymmetry instead: over-extraction outside the
# assignment costs nothing, under-extraction inside it costs everything.
# Generic by construction: it describes the harness contract, not any layout.
SPECIALIST_NOTE = """

NOTE: This document carries more page-layout families than one prompt can
sample, so several independent extraction programs are run and the harness
assembles their outputs. Each program is credited only for the pages of its
assigned layout families; records it emits for any other page are silently
discarded, never penalized. Therefore write your program as if it owned the
ENTIRE document: read every page and extract every data-entry field you can
recognize, exactly per the contract above. Do not try to filter pages to your
assignment yourself - skipping pages risks losing fields you own, while
extracting beyond your assignment costs nothing."""


def build_codegen_prompt(pdf_path: str, outdir: str,
                         rep_pages: list[int] | None = None,
                         scope_note: str = "") -> str:
    """rep_pages (1-based, optional): show only these representative page dumps
    instead of the stage-0 budgeted list - the multi-pass specialist path.
    scope_note is inserted verbatim after the intro paragraph (empty for the
    single-pass path, keeping that prompt byte-identical to before)."""
    pages_text, _ = load_rep_pages(outdir, only_pages=rep_pages)
    title_context = load_title_context_pages(outdir)
    doc = fitz.open(pdf_path)
    n_pages = doc.page_count
    doc.close()
    return CODEGEN_PROMPT.format(n_pages=n_pages, pages=pages_text,
                                 title_context=title_context,
                                 scope_note=scope_note)


# --------------------------------------------------------------------------- #
# per-cluster / per-page localization of coverage holes
# --------------------------------------------------------------------------- #
def _load_cluster_meta(outdir: str) -> dict:
    with open(art(outdir, "clusters.json"), encoding="utf-8") as f:
        return json.load(f)


def cluster_stats(result, meta: dict) -> list[dict]:
    """Coverage of the extraction per layout cluster (0-based pages in meta).

    Page coverage uses the PRE-dedup covered_pages set: dedup keeps only the
    first occurrence of a repeated field, which would make repetition-heavy
    clusters look uncovered. The per-cluster `records` count, by contrast, is
    computed from result.records as they stand at call time - POST-dedup in
    the production flow (run_extractor dedups before returning) - so it counts
    distinct records per page, not raw emissions.

    `uncovered_content` counts the cluster's uncovered pages that actually
    carry content (>= 3 text lines, from stage-0's per-page line_counts): a
    blank or furniture-only page (0-2 lines: at most a header + footer) cannot
    hold a data-entry field, so it is never evidence of a coverage hole. When
    the meta predates line_counts, every uncovered page counts as content."""
    stats = []
    covered_pages = result.covered_pages or {r.page - 1 for r in result.records if r.page}
    rec_pages = collections.Counter(r.page - 1 for r in result.records if r.page)
    line_counts = meta.get("line_counts")

    def has_content(p: int) -> bool:
        return line_counts is None or not (0 <= p < len(line_counts)) or line_counts[p] >= 3

    for ci, c in enumerate(meta["clusters"]):
        pages = c["pages"]
        with_rec = [p for p in pages if p in covered_pages]
        holes = [p for p in pages if p not in covered_pages and has_content(p)]
        stats.append({
            "cluster": ci,
            "n_pages": len(pages),
            "pages_with_records": len(with_rec),
            "coverage_pct": round(100 * len(with_rec) / max(1, len(pages))),
            "records": sum(rec_pages[p] for p in pages),
            "uncovered_content": len(holes),
            "hole_pages": holes[:40],  # 0-based; capped, feedback only samples a few
        })
    return stats


# Doc-wide coverage floor. A MAIN-pass program that leaves more than this share
# of CONTENT-BEARING pages with zero records has over-gated (typically anchored
# a whole page on one fixed cue - a font size, a y-position, a wording - that
# many pages legitimately lack). The share is measured only over pages that
# provably carry content (>= 3 text lines), so blank/furniture pages never count
# against it, and the loop clears the floor entirely once the model confirms the
# uncovered layouts are field-free. Env-overridable for probes; NOT tuned per doc.
COVERAGE_FLOOR_UNCOVERED_PCT = int(os.environ.get("ECS_COVERAGE_FLOOR_PCT", "50"))

# Credibility bar for a blanket "the uncovered layouts are field-free" answer,
# which otherwise stands the floor down for the rest of the document. Deliberately
# ABOVE the floor: between the two values a claim can still excuse a coverage hole
# (some books really do carry many instruction/TOC/reference pages), but past this
# point the program is reading under a quarter of the document's content-bearing
# pages, so "all the rest holds no data-entry fields" is not a credible statement
# about a form book - it is the excuse a title-gated program would use to dodge the
# floor. Rejecting it only costs bounded extra revisions; the best version is still
# what gets exported.
FIELD_FREE_CLAIM_MAX_UNCOVERED_PCT = int(
    os.environ.get("ECS_FIELD_FREE_MAX_UNCOVERED_PCT", "75"))


def coverage_floor_metrics(stats: list[dict]) -> dict:
    """Doc-wide coverage over CONTENT-BEARING pages, from per-cluster stats.

    content pages = covered pages (they emitted records) + uncovered pages that
    carry content (`uncovered_content` holes). Blank/furniture pages are in
    neither term, so a document of mostly-empty template pages is not penalized.
    Returns 100% covered for an empty stat set (nothing to judge)."""
    covered = sum(s.get("pages_with_records", 0) for s in stats)
    holes = sum(s.get("uncovered_content", 0) for s in stats)
    content_total = covered + holes
    if content_total <= 0:
        return {"content_pages": 0, "content_covered_pct": 100,
                "uncovered_content_pct": 0}
    return {"content_pages": content_total,
            "content_covered_pct": round(100 * covered / content_total),
            "uncovered_content_pct": round(100 * holes / content_total)}


def weak_clusters(stats: list[dict], doc_pages: int | None = None,
                  min_pages: int = 4, coverage_lt: int = 30) -> list[dict]:
    """Clusters whose coverage holes warrant feedback. Two triggers, either fires:

    1. ABSOLUTE hole: >= max(3, 2% of the document) uncovered content-bearing
       pages. Percentage coverage alone hides big holes inside big clusters
       (a 300-page cluster at 90% still misses 30 real pages); an absolute
       count of pages that provably carry content cannot be hidden by the
       cluster's own size. The 2% scaling keeps the bar proportionate on
       thousand-page books; the floor of 3 keeps one-off stragglers (often
       genuinely field-free variants) from burning feedback rounds.
    2. RELATIVE (the original rule): a cluster of >= min_pages with under
       coverage_lt% of its pages covered - catches small fully-dark clusters
       that never accumulate 3 content holes.
    """
    if doc_pages is None:
        doc_pages = sum(s["n_pages"] for s in stats)
    hole_min = max(3, round(0.02 * doc_pages))
    out = [s for s in stats
           if s.get("uncovered_content", 0) >= hole_min
           or (s["n_pages"] >= min_pages and s["coverage_pct"] < coverage_lt)]
    return sorted(out, key=lambda s: (-s.get("uncovered_content", 0), -s["n_pages"]))


def _dump_lines_text(lines, max_chars: int = 3200) -> str:
    buf = []
    for L in lines:
        color = "#{:06x}".format(L.colors[-1]) if L.non_black else "black  "
        buf.append(f"x={L.x0:6.1f} y={L.y0:6.1f} sz={L.size:4.1f} {color} {'B' if L.bold else ' '} | {L.text}")
    s = "\n".join(buf)
    return s[:max_chars] + ("\n<...page truncated...>" if len(s) > max_chars else "")


def _spread(items: list, k: int) -> list:
    """Deterministically pick up to k items spread across the list."""
    if k <= 0:
        return []
    if len(items) <= k:
        return list(items)
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def build_cluster_feedback(pdf_path: str, weak: list[dict], meta: dict,
                           stats: list[dict], max_clusters: int = 3,
                           pages_per_cluster: int = 2) -> str:
    """Coverage table + dumps of previously-unshown pages from the weakest clusters.

    Page picks come from the cluster's HOLES (uncovered content-bearing pages,
    per cluster_stats) whenever any exist outside the already-shown reps: the
    point of the dump is to show the model a page it is failing on, and in a
    partially-covered cluster a positional pick could land on a page that
    already extracts fine, wasting the slot. Falls back to any unshown page
    (old behavior) for weak clusters with no recorded holes."""
    if not weak:
        return ""
    shown = {p - 1 for p in meta["representative_pages_1based"]}
    table = "\n".join(
        f"  cluster {s['cluster']:>3}: {s['n_pages']:>4} pages, "
        f"{s['pages_with_records']:>4} with records ({s['coverage_pct']}%), {s['records']} records"
        + (f", {s['uncovered_content']} uncovered content pages"
           if s.get("uncovered_content") else "")
        for s in stats if s["n_pages"] >= 2)

    doc = fitz.open(pdf_path)
    sections = []
    for s in weak[:max_clusters]:
        holes = [p for p in s.get("hole_pages", []) if p not in shown]
        candidates = holes or [p for p in meta["clusters"][s["cluster"]]["pages"] if p not in shown]
        if not candidates:
            continue
        picks = sorted({candidates[len(candidates) // 3], candidates[(2 * len(candidates)) // 3]})
        for p in picks[:pages_per_cluster]:
            sections.append(f"--- page {p + 1} (cluster {s['cluster']}, {s['n_pages']} pages like this, "
                            f"{s['coverage_pct']}% covered) ---\n"
                            + _dump_lines_text(build_page_lines(doc[p])))
    doc.close()
    if not sections:
        return ""
    return CLUSTER_FEEDBACK_TEMPLATE.format(table=table, failing_pages="\n\n".join(sections))


def build_uncovered_feedback(pdf_path: str, result, meta: dict,
                             uncovered_pct_min: int = 25, max_pages: int = 4) -> str:
    """Fallback coverage signal for DEGENERATE clusterings (e.g. every page its own
    cluster): the per-cluster rules only see clusters, so a document whose layout
    profiles fragment would never surface coverage holes. This samples uncovered
    pages directly, doc-wide, whenever a substantial share of CONTENT-BEARING
    pages produced nothing (blank/furniture-only pages are excluded from both
    the numerator and the sampled dumps - they cannot hold fields).

    uncovered_pct_min=25: aligned with the audit's proportional uncovered
    sampling, not with any document. The audit treats an uncovered share as a
    real doc-wide signal once it earns >=2 of the minimum 6 audit slots -
    round(6 * share) >= 2 first holds at 25%. From that point the audit will
    keep REPORTING under-coverage in issue counts, so the revision must also
    RECEIVE page dumps of the missed layouts or it revises blind against a
    signal it cannot localize. The previous 40% threshold left a dead zone
    (25-40% uncovered on a fragmented document: audited as a problem, never
    shown as pages) in which scores could not improve."""
    pool = meta.get("page_pool") or range(meta["pages"])  # scoped pass or full doc
    covered = result.covered_pages or {r.page - 1 for r in result.records if r.page}
    line_counts = meta.get("line_counts")

    def has_content(p: int) -> bool:
        return line_counts is None or not (0 <= p < len(line_counts)) or line_counts[p] >= 3

    content_total = sum(1 for p in pool if has_content(p)) or 1
    uncovered = [p for p in pool if p not in covered and has_content(p)]
    if 100 * len(uncovered) / content_total < uncovered_pct_min:
        return ""
    shown = {p - 1 for p in meta["representative_pages_1based"]}
    candidates = [p for p in uncovered if p not in shown] or uncovered
    doc = fitz.open(pdf_path)
    sections = [f"--- page {p + 1} (uncovered) ---\n" + _dump_lines_text(build_page_lines(doc[p]))
                for p in _spread(candidates, max_pages)]
    doc.close()
    table = (f"  {len(uncovered)} of {content_total} content-bearing pages "
             f"({round(100 * len(uncovered) / content_total)}%) produced no records "
             "(page layouts too fragmented for a per-cluster table)")
    return CLUSTER_FEEDBACK_TEMPLATE.format(table=table, failing_pages="\n\n".join(sections))


def soften_scoped_volume_gates(problems: list[str], warnings: list[str],
                               metrics: dict, scope: dict | None):
    """VOLUME gates (zero records / too-few-records) soften to warnings for
    TAIL-SPECIALIST passes only: their layout families can legitimately be
    (nearly) field-free, and the page-grounded audit - which still runs on the
    scope's pages - judges the claim. The MAIN pass (scope["main"]) keeps
    single-pass gates: it owns the budgeted clusters, i.e. nearly every page,
    so zero/low volume from it means a broken program, exactly as in a
    single-pass run. Everything else (page-number contract, degenerate form
    grouping, crashes) stays hard for every pass. Returns the filtered
    (problems, warnings)."""
    if scope is None or scope.get("main") or not problems:
        return problems, warnings
    hard = [p for p in problems
            if not (p.startswith("The program extracted ZERO records")
                    or re.match(r"Only \d+ records", p))]
    if len(hard) < len(problems):
        n = metrics.get("records") or 0
        soft = "ZERO records" if n == 0 else f"only {n} records"
        warnings = [f"This pass's layout scope produced {soft} - correct "
                    "only if these layouts genuinely carry few or no "
                    "data-entry fields; the page audit will verify that "
                    "claim."] + warnings
    return hard, warnings


def mask_result(result: ReplayResult, pages_0based: set) -> ReplayResult:
    """Restrict a full-document replay to a page scope (multi-pass specialists).

    Records outside the scope are dropped and coverage is recomputed;
    pages_total becomes the scope size so the volume/coverage gates judge the
    specialist against ITS pages, not the whole book. The generated program
    itself always ran over the full document - masking is pure bookkeeping."""
    pages = set(pages_0based)
    scoped = ReplayResult(format_id=result.format_id,
                          pages_total=len(pages) or result.pages_total)
    scoped.records = [r for r in result.records if r.page and (r.page - 1) in pages]
    scoped.covered_pages = set(result.covered_pages or ()) & pages
    scoped.pages_with_fields = len(scoped.covered_pages)
    scoped.definition_pages_seen = result.definition_pages_seen
    return scoped


def _scope_meta(meta: dict, scope: dict) -> dict:
    """View of the stage-0 meta restricted to one specialist's clusters/pages.
    line_counts stays FULL-length (indexed by absolute page number); `pages`
    becomes the scope size and `page_pool` lists the absolute 0-based scope
    pages, which the coverage-feedback builders iterate instead of
    range(pages).

    representative_pages_1based becomes the pages THIS PASS'S PROMPT actually
    showed (scope["rep_pages"] - the pass's own reps, carried by run_document)
    plus any budgeted reps inside the scope. Downstream consumers treat that
    list as 'pages the model has seen': feedback builders must not re-dump a
    shown page under a 'you have not seen this' header, and the audit's
    rep/non-rep split tests generalization against it."""
    keep = set(scope["clusters"])
    m = dict(meta)
    m["clusters"] = [c for i, c in enumerate(meta["clusters"]) if i in keep]
    m["pages"] = len(scope["pages"])
    m["page_pool"] = sorted(scope["pages"])
    shown = {p for p in meta["representative_pages_1based"] if p - 1 in scope["pages"]}
    shown |= set(scope.get("rep_pages") or ())
    m["representative_pages_1based"] = sorted(shown)
    return m


TEXT_FILTER_WARN = 10
TEXT_FILTER_HARD = 30


def count_text_filters(source: str) -> int:
    """How many literal text values the program compares records/lines against:
    string items of inline OR named list/set/tuple membership tests plus
    literal-word alternatives in regex calls (a|b|c|...). A handful is normal
    (template markers used as landmarks); dozens means the program is filtering
    by enumerated content - a blocklist fitted to the sampled pages that neither
    generalizes nor spares real fields sharing the words. Purely a code-shape
    property of the generated source: no corpus vocabulary or document text is
    consulted."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0

    def literal_collection_size(node) -> int:
        if not isinstance(node, (ast.List, ast.Set, ast.Tuple)):
            return 0
        return sum(1 for e in node.elts
                   if isinstance(e, ast.Constant) and isinstance(e.value, str)
                   and re.search(r"[^\W\d_]", e.value))

    named_collections: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            size = literal_collection_size(node.value)
            if size:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        named_collections[target.id] = size
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            size = literal_collection_size(node.value)
            if size:
                named_collections[node.target.id] = size

    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn))
                                                 for op in node.ops):
            for cmp_ in node.comparators:
                n += literal_collection_size(cmp_)
                if isinstance(cmp_, ast.Name):
                    n += named_collections.get(cmp_.id, 0)
        elif isinstance(node, ast.Call) and node.args:
            fn = node.func.attr if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else "")
            pattern = node.args[0]
            if fn not in {"compile", "match", "search", "fullmatch", "findall",
                          "finditer", "sub", "split"} \
                    or not isinstance(pattern, ast.Constant) \
                    or not isinstance(pattern.value, str) \
                    or pattern.value.count("|") < 3:
                continue
            parts = pattern.value.split("|")
            wordish = [p for p in parts
                       if re.fullmatch(r"[\w \.\-\(\)\^\$,:#/']{2,60}", p)
                       and re.search(r"[^\W\d_]", p)]
            if len(wordish) >= 0.7 * len(parts):
                n += len(wordish)
    return n


def validate_generated(pdf_path: str, raw_reply: str, outdir: str | None = None,
                       scope: dict | None = None) -> dict:
    """Run + gate a generated program. Returns:
      problems  - contract blockers (crash / effectively-no-output): must be fixed
      warnings  - quality signals (form pct, label shape, form explosion): feed the
                  revision loop but never permanently reject a document by themselves
      cluster_feedback - coverage holes localized to clusters (or raw pages when the
                  clustering is degenerate), for revision/confirmation prompts

    scope (multi-pass): {"pages": set of 0-based pages, "clusters": set of
    cluster indices, "main": bool}. The replay is masked to the scope before
    scoring, and coverage feedback is computed against the scoped clusters
    only. For TAIL-SPECIALIST scopes (main=False) the volume gates soften to
    warnings - see soften_scoped_volume_gates; the main pass keeps every
    single-pass gate."""
    source = extract_source(raw_reply)
    cluster_feedback, stats, weak = "", [], []
    try:
        result = run_extractor(source, pdf_path)
        if scope is not None:
            result = mask_result(result, scope["pages"])
        metrics = score(result, "codegen")
        problems = gate_problems(metrics)
        warnings = gate_warnings(metrics)
        problems, warnings = soften_scoped_volume_gates(problems, warnings,
                                                        metrics, scope)
        n_filters = count_text_filters(source)
        filter_feedback = (
            f"The program filters by {n_filters} hardcoded literal text strings "
            "(membership blocklists / long regex alternations of specific "
            "wordings). These fit only the pages they were copied from: unsampled "
            "pages carry the same junk classes with other wording, and real fields "
            "elsewhere can share the blocklisted words. Replace them with the "
            "structural discriminator (position, style, column membership); keep "
            "literal matching only for repeated template markers."
        )
        if n_filters >= TEXT_FILTER_HARD:
            problems.append("Extreme content-fitted blocklist. " + filter_feedback)
        elif n_filters >= TEXT_FILTER_WARN:
            warnings.append(
                filter_feedback)
        sample = "\n".join(f"p{r.page}: {r.form_name} | {r.field_name}"
                           for r in result.records[:25]) or "(none)"
    except Exception as e:  # noqa: BLE001 - every failure becomes revision feedback
        result = None
        metrics = {"error": str(e)}
        problems = [f"Program failed to run: {e}"]
        warnings = []
        sample = "(none)"
    # Feedback building is OUR harness, not the generated program: its failures
    # (corrupt clusters.json, unreadable PDF page) must not masquerade as
    # "Program failed to run" and misdirect the revision at working code.
    if result is not None and outdir:
        try:
            meta = _load_cluster_meta(outdir)
            if scope is not None:
                meta = _scope_meta(meta, scope)
            stats = cluster_stats(result, meta)
            weak = weak_clusters(stats, doc_pages=meta["pages"])
            metrics["pages_covered_pct"] = round(
                100 * len(result.covered_pages) / max(1, meta["pages"]))
            metrics.update(coverage_floor_metrics(stats))
            if weak:
                cluster_feedback = build_cluster_feedback(pdf_path, weak, meta, stats)
            if not cluster_feedback:
                # the weak-cluster builder returns "" when every candidate page
                # was already shown; real doc-wide holes must still surface
                cluster_feedback = build_uncovered_feedback(pdf_path, result, meta)
        except Exception as e:  # noqa: BLE001
            print(f"    (coverage-feedback build failed, continuing without it: {e})")
            cluster_feedback, stats, weak = "", [], []
    return {"source": source, "result": result, "metrics": metrics,
            "problems": problems, "warnings": warnings, "sample": sample,
            "cluster_stats": stats, "weak_clusters": weak,
            "cluster_feedback": cluster_feedback}


# --------------------------------------------------------------------------- #
# iteration scoring: one comparable "result" per parser version so the loop
# controller can tell convergence from diminishing returns
# --------------------------------------------------------------------------- #
AUDIT_NOT_RUN = float("inf")


def version_score(verdict: dict, audit_issue_count: int | None) -> tuple:
    """Lexicographic quality of one parser version; LOWER is better.

    Order of importance:
      1. contract blockers (crash / effectively-no-output)  - dominate everything
      2. page-grounded audit issues                          - the real quality signal
      3. soft gate warnings (corpus-free shape priors)
      4. page coverage (negated)                             - tie-break only
    The audit element is the issue count over the version's OWN audited sample
    (fixed core + rotating exploration slots). Because samples can differ
    across versions, improves() re-bases the audit element onto the SHARED
    audited pages before comparing two scores - raw tuples are only compared
    directly when either side carries no per-page audit map."""
    m = verdict.get("metrics") or {}
    return (len(verdict["problems"]),
            AUDIT_NOT_RUN if audit_issue_count is None else audit_issue_count,
            len(verdict.get("warnings") or []),
            -(m.get("pages_with_fields") or 0))


def _norm_junk(s) -> str:
    """Whitespace/case-insensitive form for junk-value matching: junk is a
    repeated stamp, so its variance across pages is layout noise (spacing,
    case), not content."""
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def forgivable_junk_pages(result, lost_pages, junk_values) -> set:
    """The subset of `lost_pages` (0-based) whose extraction in `result` (the
    INCUMBENT best version) consists ENTIRELY of records whose field_name
    matches the junk evidence - values the page-grounded audit flagged as
    false extractions, or doc-wide furniture candidates.

    This is the evidence check behind the junk-coverage carve-out in
    improves(): a page may only be forgiven for going uncovered if every
    record it is losing is VERIFIED junk. The check deliberately scales with
    evidence, not with any assumed junk-to-content ratio - a document whose
    parser stamped junk on half its pages gets half its pages forgiven once
    the audit flags that junk, while a page carrying even one unflagged (i.e.
    presumed real) record is never forgiven. Matching is by normalized value:
    junk is a repeated stamp, so a value flagged false on one sampled page
    identifies the same record on the hundreds of pages the audit never saw.
    Junk whose text varies per page will not match and the drop stays vetoed:
    the failure direction is keeping junk, never losing real fields."""
    junk = {_norm_junk(v) for v in junk_values if _norm_junk(v)}
    if not junk:
        return set()
    by_page: dict = {}
    for r in getattr(result, "records", None) or ():
        if r.page:
            by_page.setdefault(r.page - 1, []).append(_norm_junk(r.field_name))
    return {p for p in lost_pages
            if by_page.get(p) and all(n in junk for n in by_page[p])}


def improves(best_score: tuple | None, cand_score: tuple,
             best_cov=(), cand_cov=(), cov_floor: float = 0.9,
             best_issue_pages: dict | None = None,
             cand_issue_pages: dict | None = None,
             forgivable=()) -> bool:
    """Strict improvement over the best version so far.

    best_cov / cand_cov are covered PAGE SETS (any iterable of page numbers).
    A candidate that RETAINS less than `cov_floor` of the pages the incumbent
    covered is never an improvement, whatever its other numbers: audit issues
    are counted on a handful of pages, page coverage is doc-wide, and a 'fix'
    that silently drops whole layouts must not win on a lower issue count.
    Retention is measured on the page SET, not the count - a version covering
    the same NUMBER of pages while swapping WHICH pages they are has still
    lost working extraction, and a count comparison would wave it through.

    best_issue_pages / cand_issue_pages: optional {page: issue_count} maps of
    each version's audited sample. With rotating audit slots the two samples
    can differ, so raw audit totals are not comparable; when both maps exist,
    the audit element of each score tuple is re-computed over the SHARED
    audited pages (the fixed core is always shared) before comparing.

    Junk-coverage carve-out (VERIFIED, not inferred): `forgivable` is the set
    of pages - computed by forgivable_junk_pages from the incumbent's own
    records against audit-flagged false values and furniture candidates -
    whose only extraction was verified junk. Pages lost below the retention
    floor are excused exactly when EVERY lost page is in that set: a parser
    that stamped furniture on many pages 'covers' them only in the junk
    sense, and the cleanup that stops emitting it would otherwise be vetoed
    forever. There is no ratio cap and no inference from audit deltas - an
    earlier version of this carve-out inferred 'cleanup' from a falling
    audit count and blessed a rewrite that dropped 340 truly-covered pages
    for a 1-issue audit improvement measured on 13 sampled pages. If even one
    lost page is not verified junk-only, the coverage guard vetoes as usual."""
    if best_score is None:
        return True
    b_adj, c_adj = list(best_score), list(cand_score)
    if (best_issue_pages and cand_issue_pages
            and best_score[1] != AUDIT_NOT_RUN and cand_score[1] != AUDIT_NOT_RUN):
        shared = set(best_issue_pages) & set(cand_issue_pages)
        if shared:
            b_adj[1] = sum(best_issue_pages[p] for p in shared)
            c_adj[1] = sum(cand_issue_pages[p] for p in shared)
    best_pages = set(best_cov or ())
    if best_pages:
        cand_pages = set(cand_cov or ())
        lost = best_pages - cand_pages
        if len(best_pages) - len(lost) < cov_floor * len(best_pages):
            if not (lost and lost <= set(forgivable or ())):
                return False
    return tuple(c_adj) < tuple(b_adj)


def _src_excerpt(source: str, cap: int = 40000) -> str:
    """The model is asked to EXTEND its own program; silently cutting the tail
    off makes it rewrite blind and lose coverage. Some models routinely write
    15-20 KB parsers (a 16k-token reply budget allows ~50 KB of source), so the
    cap only exists as a runaway guard - a truncated echo of the model's own
    program reliably produces a broken rewrite, which costs far more than the
    prompt tokens saved. When the cap does hit, the cut is announced instead
    of silent."""
    if len(source) <= cap:
        return source
    return (source[:cap]
            + f"\n# ... TRUNCATED: {len(source) - cap} more chars of your program "
              "are not shown; preserve the unshown logic when you rewrite ...")


# Restated in every revision/confirm round of a tail-specialist pass:
# transports are stateless, so from v2 onward this is the model's ONLY way to
# know the metrics it sees are scope-restricted (the initial SPECIALIST_NOTE is
# not in context). Same harness-descriptive framing as SPECIALIST_NOTE - it
# explains the numbers, it does not tell the model to restrict what it reads.
# The main pass gets no note here either.
SPECIALIST_LOOP_NOTE = """

NOTE: this document is processed by several independent extraction programs
whose outputs the harness assembles. The metrics, records and coverage shown
in this message are RESTRICTED to the pages assigned to your program; records
you emit for other pages are discarded without penalty. Judge the numbers in
this message against your assigned pages only - and keep your program
extracting from every page it can recognize rather than filtering pages
yourself."""


def build_code_revision_prompt(verdict: dict, scope_note: str = "") -> str:
    issues = ([f"- {p}" for p in verdict["problems"]]
              + [f"- (quality warning) {w}" for w in verdict.get("warnings", [])])
    return CODE_REVISION_TEMPLATE.format(
        code=_src_excerpt(verdict["source"]),
        metrics=json.dumps(verdict["metrics"], indent=1),
        sample=verdict["sample"],
        problems="\n".join(issues) or "- (see coverage feedback below)",
        cluster_feedback=verdict.get("cluster_feedback", ""),
        scope_note=scope_note,
    )


def build_coverage_confirm_prompt(verdict: dict, scope_note: str = "") -> str:
    """For programs that PASS gates but leave whole clusters uncovered.
    Self-contained (includes the program) because transports are stateless."""
    return COVERAGE_CONFIRM_TEMPLATE.format(code=_src_excerpt(verdict["source"]),
                                            cluster_feedback=verdict["cluster_feedback"],
                                            scope_note=scope_note)


CONFIRM_TOKEN = "CONFIRM_NO_FIELDS"


def is_confirm_no_fields(reply: str) -> bool:
    """True only when the token IS the answer - alone on its own line and with no
    program in the reply. A substring test would misread prose that merely
    mentions the token ("I cannot CONFIRM_NO_FIELDS, here is the extension...")
    and silently discard the extension."""
    if "def extract" in reply:
        return False
    return any(line.strip() == CONFIRM_TOKEN for line in reply.splitlines())


# --------------------------------------------------------------------------- #
# grounded audit: judge quality against the document itself, never against
# corpus statistics (no assumptions about what a "typical" CRF looks like)
# --------------------------------------------------------------------------- #
AUDIT_PROMPT_TEMPLATE = """You are auditing the output of a deterministic extraction program that was run over a clinical CRF PDF. The program's task contract: for every data-entry field on every page, extract form_name (the printed title of the CRF form/section the field belongs to - a title is shared by the fields it groups, never a per-field code or technical annotation) and field_name (the human-readable field label/question). Field labels only - machine codes, answer options (Yes/No/choice-list values), filled values, instructions, and page furniture (headers/footers/page numbers/legends) are NOT fields.

Below are {k} sampled pages of the document (structured text lines with geometry:
x=<left> y=<top> sz=<font-size> <color> <B if bold> | <text>), each followed by the
records the program extracted FROM THAT PAGE. Before each audited page you may
also see the TOP regions of up to two immediately preceding pages, labeled
TITLE LOOKBACK CONTEXT. They are context only: use them to resolve a title
announced before a continuation page, but do not audit their fields and do not
return JSON objects for them.

Audit each page strictly against what is printed on it:
- missed      : data-entry fields visible on the page that were not extracted
- false       : extracted records that are not actually data-entry fields
- wrong_form  : extracted records whose form_name does not match the form/section
                this page belongs to, OR whose form_name is not a printed
                form/section title at all (e.g. the field's own label, a machine
                code, or a per-field technical annotation used as form_name)

Three calibration rules: (1) a label wrapped over several visual lines is ONE
field, not several; (2) text that recurs identically on page after page as part
of the page template (headers, footers, watermarks, per-page signature/initials
blocks) is template furniture - do not report it under "missed", and do not
demand the program extract it; (3) rows of a printed reference or enumeration
table - a list of items (names, codes, categories) where the row itself carries
no data-entry cell on this page - are page content, not data-entry fields:
report extracted rows of such a table under "false", and do not demand them
under "missed". A table row IS a field when the row has its own entry cell to
be filled per row - and note an entry cell is often a DRAWN blank box or empty
table cell that prints no text at all, so it may be invisible in the text dump:
judge from the table's purpose and column headers (a column meant to be filled
in per row makes the rows fields), not only from visible text.

Some sampled pages may have NO extracted records: if such a page prints data-entry
fields, list them under "missed"; if it is genuinely field-free (title/TOC/
instructions/definitions-only), return empty lists for it. If a page dump ends
with <...page truncated...>, audit only the shown region - records that belong
beyond the cut are not visible to you and must not be reported as "false".

# Reply format (JSON only, no prose)

[
 {{"page": <n>, "missed": ["<field label>", ...], "false": ["<field_name>", ...], "wrong_form": ["<field_name>", ...]}}
]

One object per audited page; empty lists mean that page's extraction is correct.
In "false" and "wrong_form", copy the record's field_name EXACTLY as printed
after the | in its "extracted:" line (not the page text, not a paraphrase):
the harness matches these strings against the program's records, and an entry
that matches no record is ignored.

{pages_and_records}
"""


def audit_budget(pages_total: int) -> int:
    """Audit sample size, scaled with document size: 6 pages up to 300, then
    +1 per further 150 pages, capped at 12. A fixed 6-page sample is 2% of a
    300-page book but 0.6% of a 1000-page one - issue counts lose all
    resolution exactly on the documents with the most layouts to get wrong."""
    if pages_total <= 300:
        return 6
    return min(12, 6 + -(-(pages_total - 300) // 150))


def pick_audit_pages(outdir: str, result: ReplayResult,
                     max_pages: int | None = None,
                     scope: dict | None = None) -> list[int]:
    """Representative pages + covered NON-representative pages + uncovered pages
    in PROPORTION to how much of the document is uncovered (1-based).

    max_pages=None resolves to audit_budget(document size) - the size-scaled
    default. scope (multi-pass specialists) restricts every pool to the pass's
    own pages; `result` is already masked to that scope by validate_generated.

    The non-rep covered picks test GENERALIZATION: representative pages were
    visible at induction time, so auditing only those would validate what the
    model already saw. The uncovered slots scale with the uncovered share of
    the document: a parser reading 15% of a book must not be judged on a
    mostly-covered sample, or under-coverage never shows up in the issue count
    that drives revision and stopping. Floors/caps: at least one uncovered page
    whenever any exists (a wrong CONFIRM_NO_FIELDS verdict must stay
    re-examinable), and at least two covered pages whenever any exist (the
    audit must also judge precision of what IS extracted). On an uncovered page
    the auditor either lists missed fields (driving a revision) or returns
    empty lists (independently confirming it field-free). Deterministic
    (spread picks, no RNG)."""
    meta = _load_cluster_meta(outdir)
    if scope is not None:
        meta = _scope_meta(meta, scope)
    pool = [p + 1 for p in meta.get("page_pool") or range(meta["pages"])]
    pool_set = set(pool)
    if max_pages is None:
        max_pages = audit_budget(len(pool))
    covered = sorted({r.page for r in result.records if r.page and r.page in pool_set})
    covered_set = set(covered)
    uncovered = [p for p in pool if p not in covered_set]
    unc_slots = round(max_pages * len(uncovered) / max(1, len(pool)))
    unc_slots = max(unc_slots, 1 if uncovered else 0)
    if covered:
        unc_slots = min(unc_slots, max_pages - 2)
    unc_slots = min(unc_slots, len(uncovered))
    reps = set(meta["representative_pages_1based"])
    covered_reps = [p for p in covered if p in reps]
    covered_other = [p for p in covered if p not in reps]
    budget = max_pages - unc_slots
    half = budget // 2
    picks = _spread(covered_reps, half) + _spread(covered_other, budget - half)
    if len(picks) < budget:  # one pool was short - refill from the other
        rest = [p for p in covered if p not in picks]
        picks += _spread(rest, budget - len(picks))
    picks += _spread(uncovered, unc_slots)
    return sorted(set(picks))


def pick_rotation_pages(outdir: str, result: ReplayResult, core: list[int],
                        history, k: int, salt: int = 0,
                        scope: dict | None = None) -> list[int]:
    """Deterministic EXPLORATION slots for the audit sample (1-based pages).

    The fixed core keeps version scores comparable, but on a large book a
    fixed handful of pages is also all the loop ever verifies - broken layouts
    outside it stay invisible forever. Each round therefore adds up to k
    rotating slots: never-audited pages first (`history` = every page audited
    in earlier rounds), round-robin across layout clusters (structural
    stratification), uncovered pages before covered ones within each cluster
    (least-evidenced first), and the starting cluster rotated by `salt` (the
    version number) so consecutive rounds fan out instead of re-picking the
    same cluster's head. When every page has been audited once, previously
    rotated pages become eligible again (only the core is permanently
    excluded, it is re-audited every round anyway). Degrades gracefully:
    missing/corrupt cluster meta falls back to a doc-wide spread, and no
    candidates at all -> []."""
    if k <= 0:
        return []
    core_set = set(core or ())
    seen = core_set | set(history or ())
    covered = {r.page for r in (getattr(result, "records", None) or ())
               if getattr(r, "page", None)}
    try:
        meta = _load_cluster_meta(outdir)
        if scope is not None:
            meta = _scope_meta(meta, scope)
        pool = [p + 1 for p in meta.get("page_pool") or range(meta["pages"])]
        pool_set = set(pool)
        cluster_lists = [[p + 1 for p in c["pages"] if p + 1 in pool_set]
                         for c in meta.get("clusters", [])]
        cluster_lists = [c for c in cluster_lists if c]
    except Exception:  # noqa: BLE001 - synthetic dirs (tests) have no meta
        if scope is not None:
            # a masked result's pages_total is the SCOPE SIZE, not a page range;
            # inventing pages 1..n here would audit pages outside the pass
            return []
        n = getattr(result, "pages_total", 0) or 0
        if not n:
            return []
        pool = list(range(1, n + 1))
        cluster_lists = []

    def queued(pages, exclude):
        cand = [p for p in pages if p not in exclude]
        return [p for p in cand if p not in covered] + [p for p in cand if p in covered]

    picks: list[int] = []
    # pass 1 excludes everything audited before (never-audited first);
    # pass 2 relaxes to core-only exclusion (re-audit old rotation pages)
    for exclude in (seen, core_set):
        if len(picks) >= k:
            break
        ex = exclude | set(picks)
        if cluster_lists:
            queues = [q for q in (queued(c, ex)
                                  for c in sorted(cluster_lists, key=len, reverse=True)) if q]
            if queues:
                start = salt % len(queues)
                queues = queues[start:] + queues[:start]
                # interleave: round r takes the r-th head of every queue in turn
                for r in range(max(len(q) for q in queues)):
                    for q in queues:
                        if r < len(q) and len(picks) < k and q[r] not in picks:
                            picks.append(q[r])
                    if len(picks) >= k:
                        break
        if len(picks) < k:
            picks += queued(pool, ex | set(picks))[: k - len(picks)]
    return sorted(picks[:k])


def _title_lookback_text(doc, page_1based: int, max_chars: int = 1400) -> str:
    """Top-region context from up to two preceding pages for form attribution.

    An audited continuation page can correctly carry a title that is not printed
    on that page. Without lookback the auditor has no evidence to distinguish a
    correct carry from a per-field annotation. Top-only dumps bound prompt cost
    and avoid asking the auditor to judge fields on context pages.
    """
    blocks = []
    for q in range(max(1, page_1based - 2), page_1based):
        page = doc[q - 1]
        top = [L for L in build_page_lines(page)
               if L.y0 <= 0.30 * max(page.rect.height, 1.0)]
        text = _dump_lines_text(top, max_chars=max_chars)
        blocks.append(f"--- page {q} TITLE LOOKBACK CONTEXT (top only; "
                      f"do not audit) ---\n{text}")
    return "\n\n".join(blocks)


def build_audit_prompt(pdf_path: str, outdir: str, result: ReplayResult,
                       max_pages: int | None = None, pages: list[int] | None = None,
                       scope: dict | None = None) -> tuple[str, list[int]]:
    """Pair each sampled page dump with the records the program extracted from it.
    Pass `pages` to audit an explicit sample (the loop controller composes
    fixed-core + rotation samples itself after the first audit)."""
    audit_pages = pages if pages is not None else pick_audit_pages(outdir, result,
                                                                   max_pages, scope)
    by_page: dict[int, list] = collections.defaultdict(list)
    for r in result.records:
        by_page[r.page].append(r)
    doc = fitz.open(pdf_path)
    sections = []
    for p in audit_pages:
        lookback = _title_lookback_text(doc, p)
        recs = "\n".join(f"  extracted: {r.form_name} | {r.field_name}"
                         for r in by_page.get(p, [])) or "  (no records extracted from this page)"
        # roomier cap than the induction dumps: the auditor judges records
        # against the page, so cutting the page bottom would turn every record
        # from the hidden region into a phantom "false" finding
        sections.append((lookback + "\n\n" if lookback else "")
                        + f"--- page {p} AUDIT THIS PAGE ---\n"
                        f"{_dump_lines_text(build_page_lines(doc[p - 1]), max_chars=6000)}\n\n"
                        f"Records the program extracted from page {p}:\n{recs}")
    doc.close()
    prompt = AUDIT_PROMPT_TEMPLATE.format(k=len(audit_pages),
                                          pages_and_records="\n\n".join(sections))
    return prompt, audit_pages


def parse_audit_reply(raw: str) -> list[dict]:
    """First complete JSON array in the reply (balanced parse, not greedy regex -
    prose containing brackets before/after the payload must not corrupt it)."""
    dec = json.JSONDecoder()
    idx = raw.find("[")
    while idx != -1:
        try:
            out, _ = dec.raw_decode(raw, idx)
            if isinstance(out, list):
                return out
        except json.JSONDecodeError:
            pass
        idx = raw.find("[", idx + 1)
    raise ValueError("no JSON array in audit reply")


def audit_issues(verdicts: list[dict]) -> int:
    return sum(len(v.get("missed") or []) + len(v.get("false") or []) + len(v.get("wrong_form") or [])
               for v in verdicts)


def audit_problem_lines(verdicts: list[dict]) -> list[str]:
    problems = []
    for v in verdicts:
        p = v.get("page")
        for kind, label in (("missed", "fields visible on the page but NOT extracted"),
                            ("false", "extracted records that are not data-entry fields"),
                            ("wrong_form", "records attributed to the wrong form")):
            items = v.get(kind) or []
            if items:
                shown = "; ".join(str(x) for x in items[:8])
                problems.append(f"Page {p}: {label}: {shown}"
                                + (f" (+{len(items) - 8} more)" if len(items) > 8 else ""))
    return problems


# --------------------------------------------------------------------------- #
# multi-pass specialists: when one prompt cannot show a rep page for every
# layout family, split the families across several independent programs
# --------------------------------------------------------------------------- #
# Split-planning knobs. Defaults reproduce the shipped "splitting is rare"
# behavior; the ECS_* env vars let an ablation force narrow, many-cluster splits
# without editing code. Unset = identical to before.
_REP_BUDGET = int(os.environ.get("ECS_REP_BUDGET", "14"))
_MAX_PASSES = int(os.environ.get("ECS_MAX_PASSES", "4"))
_MIN_TAIL_REPS = int(os.environ.get("ECS_MIN_TAIL_REPS", "8"))
_MIN_TAIL_CONTENT = int(os.environ.get("ECS_MIN_TAIL_CONTENT", "20"))


def plan_passes(meta: dict, rep_budget: int | None = None,
                max_passes: int | None = None,
                min_tail_reps: int | None = None,
                min_tail_content: int | None = None) -> list[dict]:
    """Split a document's clusters into specialist passes.

    Returns [{"clusters": [cluster indices], "rep_pages": [1-based pages]}, ...].
    A single-element list is the ordinary single-pass path: its rep_pages are
    exactly the stage-0 budgeted selection (representative_pages_1based), so
    drivers taking that branch produce byte-identical prompts to before.

    Pass 0 owns the clusters whose representatives made the stage-0 budget
    (plus blank/rep-less clusters - they need no parser, but their pages must
    belong to exactly one pass for the ownership join). The remaining content
    clusters - which stage 0 gives one representative each since the
    multi-pass change ('all_rep_pages_1based'); older metas have none and
    yield a single pass - are bin-packed largest-first into further passes of
    at most rep_budget representative pages. Tail clusters with FEWER than 3
    content-bearing pages fold into pass 0 instead of earning a specialist:
    below the same threshold the coverage safety net uses for holes, a
    dedicated pass (its own version budget and audits) cannot pay for itself,
    and pass 0's program - which reads every page - may still pick such pages
    up.

    SPLITTING IS THE EXCEPTION, not the rule: a specialist pass costs a full
    induction loop, while a tail folded into the single pass is still served
    by the coverage machinery - per-cluster feedback dumps up to 3 clusters x
    2 pages per revision round, plus the confirmation round. So the document
    splits only when the whole tail is too big for that channel: at least
    min_tail_reps representative pages (more than ~2 revision rounds of
    feedback could ever show) AND at least min_tail_content content-bearing
    pages (enough owned mass for a dedicated loop to pay for itself). Smaller
    tails fold into pass 0 and the run stays single-pass with the exact
    single-pass prompt.

    max_passes bounds the LLM budget on pathologically fragmented documents:
    overflow clusters fold into the last pass, keeping their page ownership
    (and thus coverage visibility) even where their reps no longer fit the
    prompt."""
    if rep_budget is None:
        rep_budget = _REP_BUDGET
    if max_passes is None:
        max_passes = _MAX_PASSES
    if min_tail_reps is None:
        min_tail_reps = _MIN_TAIL_REPS
    if min_tail_content is None:
        min_tail_content = _MIN_TAIL_CONTENT
    budget_reps = set(meta.get("representative_pages_1based") or [])
    clusters = meta.get("clusters") or []
    line_counts = meta.get("line_counts")

    def content_pages(c: dict) -> int:
        if line_counts is None:
            return len(c["pages"])
        return sum(1 for p in c["pages"]
                   if not (0 <= p < len(line_counts)) or line_counts[p] >= 3)

    pass0, rest = [], []
    for ci, c in enumerate(clusters):
        creps = [r + 1 for r in c.get("representatives") or []]
        if not creps or any(r in budget_reps for r in creps) or content_pages(c) < 3:
            pass0.append(ci)
        else:
            rest.append((ci, creps))
    tail_reps = sum(len(creps) for _, creps in rest)
    tail_content = sum(content_pages(clusters[ci]) for ci, _ in rest)
    if not rest or tail_reps < min_tail_reps or tail_content < min_tail_content:
        return [{"clusters": list(range(len(clusters))),
                 "rep_pages": sorted(budget_reps)}]

    rest.sort(key=lambda t: -len(clusters[t[0]]["pages"]))
    groups: list[dict] = [{"clusters": pass0, "rep_pages": sorted(budget_reps)}]
    cur, cur_reps = [], []
    for ci, creps in rest:
        if cur and len(cur_reps) + len(creps) > rep_budget:
            groups.append({"clusters": cur, "rep_pages": sorted(cur_reps)})
            cur, cur_reps = [], []
        cur.append(ci)
        cur_reps.extend(creps)
    if cur:
        groups.append({"clusters": cur, "rep_pages": sorted(cur_reps)})

    if len(groups) > max_passes:  # fold overflow into the last kept pass
        last = groups[max_passes - 1]
        for g in groups[max_passes:]:
            last["clusters"].extend(g["clusters"])
            room = rep_budget - len(last["rep_pages"])
            if room > 0:
                last["rep_pages"] = sorted(set(last["rep_pages"]) | set(g["rep_pages"][:room]))
        groups = groups[:max_passes]

    # every specialist prompt keeps the document's first two pages for format
    # identity (their dumps always exist - stage 0 reps include pages 0/1)
    front = [p for p in (1, 2) if p in budget_reps or p <= meta.get("pages", 0)]
    for g in groups[1:]:
        g["rep_pages"] = sorted(set(g["rep_pages"]) | set(front))
    return groups
