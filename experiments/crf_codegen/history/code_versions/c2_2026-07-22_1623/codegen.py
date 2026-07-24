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

import collections
import json
import os
import re
import subprocess
import sys
import tempfile

import fitz

from common import build_page_lines
from induction import gate_problems, gate_warnings, load_rep_pages, score
from replay import FieldRec, ReplayResult

HERE = os.path.dirname(os.path.abspath(__file__))

CODEGEN_PROMPT = """You are writing a deterministic extraction program for one specific clinical Case Report Form (CRF) PDF document. Below you will find a small sample of REPRESENTATIVE PAGES (one or two per page-layout cluster) from a document that is {n_pages} pages long. The document is highly repetitive: the sampled pages cover its layouts, but the unsampled pages contain different content in the same layouts.

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
  itertools, functools, string, unicodedata, bisect, statistics, json. You may not
  import anything else, access files/network, or print.
- Deterministic, fast, simple: loops, regexes, coordinate arithmetic. It must
  process all {n_pages} pages in seconds.
- Generalize from STRUCTURE, not content. The unsampled pages contain questions,
  values and section names you have never seen. Never key your logic on specific
  question wording from the samples; key it on geometry (x positions, font sizes,
  color, boldness), on repeated marker/header patterns, and on the SHAPE of text
  (regexes over character classes). The document may be in any language.
- You may keep state across pages (the function receives the whole document) -
  e.g. a form name announced once may govern many following pages.

# Quality bar (your program's output is machine-checked before acceptance)

- It must extract from every page that carries fields, not just the sampled ones.
- form_name should be non-empty for the large majority of records. If the document
  genuinely prints no form/section names, use the best available section context;
  leave it empty only as a last resort.
- field_name values must be human-readable label text - not machine codes, bare
  numbers, dates, or page furniture (headers/footers/page numbers/legends).
- Answer OPTIONS are not fields: choice values (e.g. Yes / No / Unknown / list
  items - examples here are English, apply the concept in the document's language)
  belong to a field, they are not field_name records themselves.
- No duplicate records for the same (form_name, field_name) pair beyond what the
  document itself repeats.

# Reply format

Reply with ONLY Python source code (no prose outside code comments). Start with a
comment block (3-6 lines) stating what layout you observed in the samples and the
extraction strategy you chose. Then define extract(pages) plus any helpers.

# Representative pages of this document

{pages}
"""

CODE_REVISION_TEMPLATE = """Your extraction program was executed over the FULL document. It did not pass the quality gates.

Your previous program:
{code}

Execution metrics:
{metrics}

Sample of extracted records (pN: form_name | field_name):
{sample}

Problems to fix (in priority order):
{problems}
{cluster_feedback}
Rewrite the program now. Same reply format: Python source only, define extract(pages).
Where your program already works, EXTEND it rather than rewriting it - do not lose
coverage on pages that were extracting correctly. Different page layouts may need
different handling inside the same extract() function.
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

COVERAGE_CONFIRM_TEMPLATE = """You previously wrote the extraction program below for a clinical CRF PDF (task: extract form_name + field_name for every data-entry field; field labels only, never machine codes, answer options, or page furniture). It passed the aggregate quality gates, but substantial parts of the document produced ZERO records. Below are sample pages from those parts (you have not seen these pages before).

Your current program:
{code}

For each sampled page decide: does this layout carry data-entry fields your program is missing, or is it genuinely field-free (title/TOC/instructions/definitions-only pages)?

{cluster_feedback}

Reply with EXACTLY one of:
- the single line: CONFIRM_NO_FIELDS
  (meaning: all shown layouts are genuinely field-free; the program is complete), or
- the FULL updated Python program (same reply format: source only, define
  extract(pages)) that keeps existing behavior for covered layouts and ADDS
  handling for the missed ones.
"""

_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)


def extract_source(raw: str) -> str:
    """Accept both bare source and fenced code blocks."""
    blocks = _FENCE.findall(raw)
    return (max(blocks, key=len) if blocks else raw).strip()


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


def build_codegen_prompt(pdf_path: str, outdir: str) -> str:
    pages_text, _ = load_rep_pages(outdir)
    doc = fitz.open(pdf_path)
    n_pages = doc.page_count
    doc.close()
    return CODEGEN_PROMPT.format(n_pages=n_pages, pages=pages_text)


# --------------------------------------------------------------------------- #
# per-cluster / per-page localization of coverage holes
# --------------------------------------------------------------------------- #
def _load_cluster_meta(outdir: str) -> dict:
    with open(os.path.join(outdir, "clusters.json"), encoding="utf-8") as f:
        return json.load(f)


def cluster_stats(result, meta: dict) -> list[dict]:
    """Coverage of the extraction per layout cluster (0-based pages in meta).
    Uses PRE-dedup page coverage: dedup keeps only the first occurrence of a
    repeated field, which would make repetition-heavy clusters look uncovered."""
    stats = []
    covered_pages = result.covered_pages or {r.page - 1 for r in result.records if r.page}
    rec_pages = collections.Counter(r.page - 1 for r in result.records if r.page)
    for ci, c in enumerate(meta["clusters"]):
        pages = c["pages"]
        with_rec = [p for p in pages if p in covered_pages]
        stats.append({
            "cluster": ci,
            "n_pages": len(pages),
            "pages_with_records": len(with_rec),
            "coverage_pct": round(100 * len(with_rec) / max(1, len(pages))),
            "records": sum(rec_pages[p] for p in pages),
        })
    return stats


def weak_clusters(stats: list[dict], min_pages: int = 4, coverage_lt: int = 30) -> list[dict]:
    return sorted((s for s in stats if s["n_pages"] >= min_pages and s["coverage_pct"] < coverage_lt),
                  key=lambda s: -s["n_pages"])


def _dump_lines_text(lines, max_chars: int = 3200) -> str:
    buf = []
    for L in lines:
        color = "#{:06x}".format(L.colors[-1]) if L.non_black else "black  "
        buf.append(f"x={L.x0:6.1f} y={L.y0:6.1f} sz={L.size:4.1f} {color} {'B' if L.bold else ' '} | {L.text}")
    s = "\n".join(buf)
    return s[:max_chars] + ("\n<...page truncated...>" if len(s) > max_chars else "")


def _spread(items: list, k: int) -> list:
    """Deterministically pick up to k items spread across the list."""
    if len(items) <= k:
        return list(items)
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def build_cluster_feedback(pdf_path: str, weak: list[dict], meta: dict,
                           stats: list[dict], max_clusters: int = 2,
                           pages_per_cluster: int = 2) -> str:
    """Coverage table + dumps of previously-unshown pages from the weakest clusters."""
    if not weak:
        return ""
    shown = {p - 1 for p in meta["representative_pages_1based"]}
    table = "\n".join(
        f"  cluster {s['cluster']:>3}: {s['n_pages']:>4} pages, "
        f"{s['pages_with_records']:>4} with records ({s['coverage_pct']}%), {s['records']} records"
        for s in stats if s["n_pages"] >= 2)

    doc = fitz.open(pdf_path)
    sections = []
    for s in weak[:max_clusters]:
        candidates = [p for p in meta["clusters"][s["cluster"]]["pages"] if p not in shown]
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
                             uncovered_pct_min: int = 40, max_pages: int = 4) -> str:
    """Fallback coverage signal for DEGENERATE clusterings (e.g. every page its own
    cluster): weak_clusters() only sees clusters of >=4 pages, so a document whose
    layout profiles fragment would never surface coverage holes. This samples
    uncovered pages directly, doc-wide, whenever a large share of pages produced
    nothing."""
    total = meta["pages"]
    covered = result.covered_pages or {r.page - 1 for r in result.records if r.page}
    uncovered = [p for p in range(total) if p not in covered]
    if 100 * len(uncovered) / max(1, total) < uncovered_pct_min:
        return ""
    shown = {p - 1 for p in meta["representative_pages_1based"]}
    candidates = [p for p in uncovered if p not in shown] or uncovered
    doc = fitz.open(pdf_path)
    sections = [f"--- page {p + 1} (uncovered) ---\n" + _dump_lines_text(build_page_lines(doc[p]))
                for p in _spread(candidates, max_pages)]
    doc.close()
    table = (f"  {len(uncovered)} of {total} pages ({round(100 * len(uncovered) / max(1, total))}%) "
             "produced no records (page layouts too fragmented for a per-cluster table)")
    return CLUSTER_FEEDBACK_TEMPLATE.format(table=table, failing_pages="\n\n".join(sections))


def validate_generated(pdf_path: str, raw_reply: str, outdir: str | None = None) -> dict:
    """Run + gate a generated program. Returns:
      problems  - contract blockers (crash / effectively-no-output): must be fixed
      warnings  - quality signals (form pct, label shape, form explosion): feed the
                  revision loop but never permanently reject a document by themselves
      cluster_feedback - coverage holes localized to clusters (or raw pages when the
                  clustering is degenerate), for revision/confirmation prompts"""
    source = extract_source(raw_reply)
    cluster_feedback, stats, weak = "", [], []
    try:
        result = run_extractor(source, pdf_path)
        metrics = score(result, "codegen")
        problems = gate_problems(metrics)
        warnings = gate_warnings(metrics)
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
            stats = cluster_stats(result, meta)
            weak = weak_clusters(stats)
            metrics["pages_covered_pct"] = round(
                100 * len(result.covered_pages) / max(1, meta["pages"]))
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
    Audit counts are only comparable when produced on the SAME audit pages;
    the loop controller guarantees that by fixing the page sample once."""
    m = verdict.get("metrics") or {}
    return (len(verdict["problems"]),
            AUDIT_NOT_RUN if audit_issue_count is None else audit_issue_count,
            len(verdict.get("warnings") or []),
            -(m.get("pages_with_fields") or 0))


def improves(best_score: tuple | None, cand_score: tuple,
             best_cov: int = 0, cand_cov: int = 0,
             cov_floor: float = 0.9) -> bool:
    """Strict improvement over the best version so far.

    A candidate that loses more than 10% of covered pages is never an
    improvement, whatever its other numbers: audit issues are counted on a
    handful of pages, page coverage is doc-wide, and a 'fix' that silently
    drops whole layouts must not win on a lower issue count."""
    if best_score is None:
        return True
    if best_cov and cand_cov < cov_floor * best_cov:
        return False
    return cand_score < best_score


def _src_excerpt(source: str, cap: int = 12000) -> str:
    """The model is asked to EXTEND its own program; silently cutting the tail
    off makes it rewrite blind and lose coverage. Generated parsers routinely
    run 5-10 KB, so the cap is roomy - and when it does hit, the cut is
    announced instead of silent."""
    if len(source) <= cap:
        return source
    return (source[:cap]
            + f"\n# ... TRUNCATED: {len(source) - cap} more chars of your program "
              "are not shown; preserve the unshown logic when you rewrite ...")


def build_code_revision_prompt(verdict: dict) -> str:
    issues = ([f"- {p}" for p in verdict["problems"]]
              + [f"- (quality warning) {w}" for w in verdict.get("warnings", [])])
    return CODE_REVISION_TEMPLATE.format(
        code=_src_excerpt(verdict["source"]),
        metrics=json.dumps(verdict["metrics"], indent=1),
        sample=verdict["sample"],
        problems="\n".join(issues) or "- (see coverage feedback below)",
        cluster_feedback=verdict.get("cluster_feedback", ""),
    )


def build_coverage_confirm_prompt(verdict: dict) -> str:
    """For programs that PASS gates but leave whole clusters uncovered.
    Self-contained (includes the program) because transports are stateless."""
    return COVERAGE_CONFIRM_TEMPLATE.format(code=_src_excerpt(verdict["source"]),
                                            cluster_feedback=verdict["cluster_feedback"])


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
AUDIT_PROMPT_TEMPLATE = """You are auditing the output of a deterministic extraction program that was run over a clinical CRF PDF. The program's task contract: for every data-entry field on every page, extract form_name (the CRF form/section the field belongs to) and field_name (the human-readable field label/question). Field labels only - machine codes, answer options (Yes/No/choice-list values), filled values, instructions, and page furniture (headers/footers/page numbers/legends) are NOT fields.

Below are {k} sampled pages of the document (structured text lines with geometry:
x=<left> y=<top> sz=<font-size> <color> <B if bold> | <text>), each followed by the
records the program extracted FROM THAT PAGE.

Audit each page strictly against what is printed on it:
- missed      : data-entry fields visible on the page that were not extracted
- false       : extracted records that are not actually data-entry fields
- wrong_form  : extracted records whose form_name does not match the form/section
                this page belongs to

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

{pages_and_records}
"""


def pick_audit_pages(outdir: str, result: ReplayResult, max_pages: int = 6) -> list[int]:
    """Representative pages + covered NON-representative pages + up to two
    UNCOVERED pages (1-based).

    The non-rep covered picks test GENERALIZATION: representative pages were
    visible at induction time, so auditing only those would validate what the
    model already saw. The uncovered picks close two review blind spots: a
    wrong CONFIRM_NO_FIELDS verdict would otherwise never be re-examined, and
    coverage holes too small/diffuse for the confirm-round thresholds would
    never reach any reviewer. On an uncovered page the auditor either lists
    missed fields (driving a revision) or returns empty lists (independently
    confirming it field-free). Deterministic (spread picks, no RNG)."""
    meta = _load_cluster_meta(outdir)
    covered = sorted({r.page for r in result.records if r.page})
    covered_set = set(covered)
    uncovered = [p for p in range(1, meta["pages"] + 1) if p not in covered_set]
    unc_slots = min(2, max_pages // 3, len(uncovered))
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


def build_audit_prompt(pdf_path: str, outdir: str, result: ReplayResult,
                       max_pages: int = 6, pages: list[int] | None = None,
                       ) -> tuple[str, list[int]]:
    """Pair each sampled page dump with the records the program extracted from it.
    Pass `pages` to re-audit a fixed sample (issue counts are only comparable
    across programs when they are counted on the SAME pages)."""
    audit_pages = pages if pages is not None else pick_audit_pages(outdir, result, max_pages)
    by_page: dict[int, list] = collections.defaultdict(list)
    for r in result.records:
        by_page[r.page].append(r)
    doc = fitz.open(pdf_path)
    sections = []
    for p in audit_pages:
        recs = "\n".join(f"  extracted: {r.form_name} | {r.field_name}"
                         for r in by_page.get(p, [])) or "  (no records extracted from this page)"
        # roomier cap than the induction dumps: the auditor judges records
        # against the page, so cutting the page bottom would turn every record
        # from the hidden region into a phantom "false" finding
        sections.append(f"--- page {p} ---\n"
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
