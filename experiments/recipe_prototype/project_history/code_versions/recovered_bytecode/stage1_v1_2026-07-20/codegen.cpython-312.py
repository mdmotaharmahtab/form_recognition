# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage1_v1_2026-07-20\codegen.cpython-312.pyc (Python 3.12)

'''Format-agnostic induction via CODE GENERATION - no strategy catalog, no few-shots.

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
'''
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
CODEGEN_PROMPT = 'You are writing a deterministic extraction program for one specific clinical Case Report Form (CRF) PDF document. Below you will find a small sample of REPRESENTATIVE PAGES (one or two per page-layout cluster) from a document that is {n_pages} pages long. The document is highly repetitive: the sampled pages cover its layouts, but the unsampled pages contain different content in the same layouts.\n\nEach sampled page is shown as structured text lines with geometry:\n    x=<left> y=<top> sz=<font-size> <color-hex or \'black\'> <B if bold> | <text>\n\n# Your task\n\nWrite a Python function that will run UNCHANGED over all {n_pages} pages and extract every data-entry field of the CRF:\n  - form_name : the CRF form/section the field belongs to\n  - field_name: the human-readable field label/question\n\nThat is the complete output. Some CRFs also print machine codes or technical\nannotations near fields - do NOT return those (they are resolved downstream by a\nseparate system). You may still USE such markings as structural landmarks if that\nhelps you locate fields reliably.\n\n# Runtime contract\n\ndef extract(pages):\n    # pages: list of (page_index_0based, lines) tuples for the ENTIRE document, in\n    #        page order. lines is a list of Line objects sorted by y, then x.\n    #        NOTE: y-then-x order is NOT reading order on multi-column pages; if the\n    #        layout has side-by-side columns, use x coordinates to separate them.\n    # Line attributes:\n    #   .text  (str, stripped visible text of one visual line)\n    #   .x0 .y0 .x1 .y1  (floats; PDF points; origin = top-left of the page)\n    #   .size  (float; font size in points; the largest span on the line)\n    #   .bold  (bool)\n    #   .non_black  (bool; True if any text on the line is printed in color)\n    # returns: list of dicts, one per extracted field occurrence:\n    #   {{"form_name": str, "field_name": str, "page": int_1based}}\n\n# Hard constraints\n\n- Pure computation only. These modules are already available: re, math, collections,\n  itertools, functools, string, unicodedata, bisect, statistics. You may not import\n  anything else, access files/network, or print.\n- Deterministic, fast, simple: loops, regexes, coordinate arithmetic. It must\n  process all {n_pages} pages in seconds.\n- Generalize from STRUCTURE, not content. The unsampled pages contain questions,\n  values and section names you have never seen. Never key your logic on specific\n  question wording from the samples; key it on geometry (x positions, font sizes,\n  color, boldness), on repeated marker/header patterns, and on the SHAPE of text\n  (regexes over character classes). The document may be in any language.\n- You may keep state across pages (the function receives the whole document) -\n  e.g. a form name announced once may govern many following pages.\n\n# Quality bar (your program\'s output is machine-checked before acceptance)\n\n- It must extract from every page that carries fields, not just the sampled ones.\n- form_name should be non-empty for the large majority of records. If the document\n  genuinely prints no form/section names, use the best available section context;\n  leave it empty only as a last resort.\n- field_name values must be human-readable label text - not machine codes, bare\n  numbers, dates, or page furniture (headers/footers/page numbers/legends).\n- Answer OPTIONS are not fields: choice values (e.g. Yes / No / Unknown / list\n  items - examples here are English, apply the concept in the document\'s language)\n  belong to a field, they are not field_name records themselves.\n- No duplicate records for the same (form_name, field_name) pair beyond what the\n  document itself repeats.\n\n# Reply format\n\nReply with ONLY Python source code (no prose outside code comments). Start with a\ncomment block (3-6 lines) stating what layout you observed in the samples and the\nextraction strategy you chose. Then define extract(pages) plus any helpers.\n\n# Representative pages of this document\n\n{pages}\n'
CODE_REVISION_TEMPLATE = 'Your extraction program was executed over the FULL document. It did not pass the quality gates.\n\nYour previous program:\n{code}\n\nExecution metrics:\n{metrics}\n\nSample of extracted records (pN: form_name | field_name):\n{sample}\n\nProblems to fix (in priority order):\n{problems}\n{cluster_feedback}\nRewrite the program now. Same reply format: Python source only, define extract(pages).\nWhere your program already works, EXTEND it rather than rewriting it - do not lose\ncoverage on pages that were extracting correctly. Different page layouts may need\ndifferent handling inside the same extract() function.\n'
CLUSTER_FEEDBACK_TEMPLATE = '\n# Per-layout coverage\n\nPages of this document are grouped into layout clusters (structural fingerprint).\nCoverage of your program per cluster (clusters your program extracted nothing or\nlittle from are the ones to investigate):\n\n{table}\n\n# Sample pages from poorly-covered parts of the document (you have NOT seen these before)\n\nIf these pages contain data-entry fields, add handling for their layout. If they\ngenuinely carry no fields (title/instructions/legend pages), ignore them - zero\ncoverage there is correct.\n\n{failing_pages}\n'
COVERAGE_CONFIRM_TEMPLATE = 'You previously wrote the extraction program below for a clinical CRF PDF (task: extract form_name + field_name for every data-entry field; field labels only, never machine codes, answer options, or page furniture). It passed the aggregate quality gates, but substantial parts of the document produced ZERO records. Below are sample pages from those parts (you have not seen these pages before).\n\nYour current program:\n{code}\n\nFor each sampled page decide: does this layout carry data-entry fields your program is missing, or is it genuinely field-free (title/TOC/instructions/definitions-only pages)?\n\n{cluster_feedback}\n\nReply with EXACTLY one of:\n- the single line: CONFIRM_NO_FIELDS\n  (meaning: all shown layouts are genuinely field-free; the program is complete), or\n- the FULL updated Python program (same reply format: source only, define\n  extract(pages)) that keeps existing behavior for covered layouts and ADDS\n  handling for the missed ones.\n'
_FENCE = re.compile('```(?:python)?\\s*\\n(.*?)```', re.S)

def extract_source(raw = None):
    '''Accept both bare source and fenced code blocks.'''
    blocks = _FENCE.findall(raw)
    if blocks:
        return max(blocks, key = len).strip()
    return None.strip()


def run_extractor(source = None, pdf_path = None, timeout_s = None):
    """Run generated code over the whole document in a SEPARATE process.

    The child (sandbox_runner.py) restricts the namespace; the process boundary is
    what makes a runaway program killable and keeps every run's module state fresh
    (an in-process thread can be neither killed nor isolated - in a long-lived
    notebook kernel that leaks CPU and cross-document state)."""
    src_file = tempfile.NamedTemporaryFile('w', suffix = '.py', delete = False, encoding = 'utf-8', dir = HERE)
# WARNING: Decompyle incomplete


def build_codegen_prompt(pdf_path = None, outdir = None):
    (pages_text, _) = load_rep_pages(outdir)
    doc = fitz.open(pdf_path)
    n_pages = doc.page_count
    doc.close()
    return CODEGEN_PROMPT.format(n_pages = n_pages, pages = pages_text)


def _load_cluster_meta(outdir = None):
    f = open(os.path.join(outdir, 'clusters.json'), encoding = 'utf-8')
    None(None, None)
    return 
    with None:
        if not None, json.load(f):
            pass


def cluster_stats(result = None, meta = None):
    '''Coverage of the extraction per layout cluster (0-based pages in meta).
    Uses PRE-dedup page coverage: dedup keeps only the first occurrence of a
    repeated field, which would make repetition-heavy clusters look uncovered.'''
    pass
# WARNING: Decompyle incomplete


def weak_clusters(stats = None, min_pages = None, coverage_lt = None):
    pass
# WARNING: Decompyle incomplete


def _dump_lines_text(lines = None, max_chars = None):
    buf = []
    for L in lines:
        color = '#{:06x}'.format(L.colors[-1]) if L.non_black else 'black  '
        buf.append(f'''x={L.x0:6.1f} y={L.y0:6.1f} sz={L.size:4.1f} {color} {'B' if L.bold else ' '} | {L.text}''')
    s = '\n'.join(buf)
    if len(s) > max_chars:
        return s[:max_chars] + '\n<...page truncated...>'
    return None + s[:max_chars]


def _spread(items = None, k = None):
    '''Deterministically pick up to k items spread across the list.'''
    if len(items) <= k:
        return list(items)
    step = None(items) / k
# WARNING: Decompyle incomplete


def build_cluster_feedback(pdf_path, weak = None, meta = None, stats = None, max_clusters = (2, 2), pages_per_cluster = ('pdf_path', 'str', 'weak', 'list[dict]', 'meta', 'dict', 'stats', 'list[dict]', 'max_clusters', 'int', 'pages_per_cluster', 'int', 'return', 'str')):
    '''Coverage table + dumps of previously-unshown pages from the weakest clusters.'''
    if not weak:
        return ''
# WARNING: Decompyle incomplete


def build_uncovered_feedback(pdf_path = None, result = None, meta = None, uncovered_pct_min = (40, 4), max_pages = ('pdf_path', 'str', 'meta', 'dict', 'uncovered_pct_min', 'int', 'max_pages', 'int', 'return', 'str')):
    '''Fallback coverage signal for DEGENERATE clusterings (e.g. every page its own
    cluster): weak_clusters() only sees clusters of >=4 pages, so a document whose
    fingerprint fragments would never surface coverage holes. This samples uncovered
    pages directly, doc-wide, whenever a large share of pages produced nothing.'''
    total = meta['pages']
# WARNING: Decompyle incomplete


def validate_generated(pdf_path = None, raw_reply = None, outdir = None):
    '''Run + gate a generated program. Returns:
      problems  - contract blockers (crash / effectively-no-output): must be fixed
      warnings  - quality signals (form pct, label shape, form explosion): feed the
                  revision loop but never permanently reject a document by themselves
      cluster_feedback - coverage holes localized to clusters (or raw pages when the
                  clustering is degenerate), for revision/confirmation prompts'''
    source = extract_source(raw_reply)
    weak = []
    stats = []
    cluster_feedback = ''
    
    try:
        result = run_extractor(source, pdf_path)
        metrics = score(result, 'codegen')
        problems = gate_problems(metrics)
        warnings = gate_warnings(metrics)
        if not (lambda .0: pass# WARNING: Decompyle incomplete
)(result.records[:25]()):
            (lambda .0: pass# WARNING: Decompyle incomplete
)(result.records[:25]())
        sample = '(none)'
        if outdir:
            meta = _load_cluster_meta(outdir)
            stats = cluster_stats(result, meta)
            weak = weak_clusters(stats)
            metrics['pages_covered_pct'] = round(100 * len(result.covered_pages) / max(1, meta['pages']))
        return {
            'source': source,
            'result': result,
            'metrics': metrics,
            'problems': problems,
            'warnings': warnings,
            'sample': sample,
            'cluster_stats': stats,
            'weak_clusters': weak,
            'cluster_feedback': cluster_feedback }
    except Exception:
        e = None
        result = None
        metrics = {
            'error': str(e) }
        problems = [
            f'''Program failed to run: {e}''']
        warnings = []
        sample = '(none)'
        e = None
        del e
        continue
        e = None
        del e


AUDIT_NOT_RUN = float('inf')

def version_score(verdict = None, audit_issue_count = None):
    '''Lexicographic quality of one parser version; LOWER is better.

    Order of importance:
      1. contract blockers (crash / effectively-no-output)  - dominate everything
      2. page-grounded audit issues                          - the real quality signal
      3. soft gate warnings (corpus-free shape priors)
      4. page coverage (negated)                             - tie-break only
    Audit counts are only comparable when produced on the SAME audit pages;
    the loop controller guarantees that by fixing the page sample once.'''
    if not verdict.get('metrics'):
        verdict.get('metrics')
    m = { }
# WARNING: Decompyle incomplete


def improves(best_score = None, cand_score = None, best_cov = None, cand_cov = (0, 0, 0.9), cov_floor = ('best_score', 'tuple | None', 'cand_score', 'tuple', 'best_cov', 'int', 'cand_cov', 'int', 'cov_floor', 'float', 'return', 'bool')):
    """Strict improvement over the best version so far.

    A candidate that loses more than 10% of covered pages is never an
    improvement, whatever its other numbers: audit issues are counted on a
    handful of pages, page coverage is doc-wide, and a 'fix' that silently
    drops whole layouts must not win on a lower issue count."""
    pass
# WARNING: Decompyle incomplete


def build_code_revision_prompt(verdict = None):
    pass
# WARNING: Decompyle incomplete


def build_coverage_confirm_prompt(verdict = None):
    '''For programs that PASS gates but leave whole clusters uncovered.
    Self-contained (includes the program) because transports are stateless.'''
    return COVERAGE_CONFIRM_TEMPLATE.format(code = verdict['source'][:6000], cluster_feedback = verdict['cluster_feedback'])

CONFIRM_TOKEN = 'CONFIRM_NO_FIELDS'

def is_confirm_no_fields(reply = None):
    '''True only when the token IS the answer - alone on its own line and with no
    program in the reply. A substring test would misread prose that merely
    mentions the token ("I cannot CONFIRM_NO_FIELDS, here is the extension...")
    and silently discard the extension.'''
    if 'def extract' in reply:
        return False
    return (lambda .0: pass# WARNING: Decompyle incomplete
)(reply.splitlines()())

AUDIT_PROMPT_TEMPLATE = 'You are auditing the output of a deterministic extraction program that was run over a clinical CRF PDF. The program\'s task contract: for every data-entry field on every page, extract form_name (the CRF form/section the field belongs to) and field_name (the human-readable field label/question). Field labels only - machine codes, answer options (Yes/No/choice-list values), filled values, instructions, and page furniture (headers/footers/page numbers/legends) are NOT fields.\n\nBelow are {k} sampled pages of the document (structured text lines with geometry:\nx=<left> y=<top> sz=<font-size> <color> <B if bold> | <text>), each followed by the\nrecords the program extracted FROM THAT PAGE.\n\nAudit each page strictly against what is printed on it:\n- missed      : data-entry fields visible on the page that were not extracted\n- false       : extracted records that are not actually data-entry fields\n- wrong_form  : extracted records whose form_name does not match the form/section\n                this page belongs to\n\n# Reply format (JSON only, no prose)\n\n[\n {{"page": <n>, "missed": ["<field label>", ...], "false": ["<field_name>", ...], "wrong_form": ["<field_name>", ...]}}\n]\n\nOne object per audited page; empty lists mean that page\'s extraction is correct.\n\n{pages_and_records}\n'

def pick_audit_pages(outdir = None, result = None, max_pages = None):
    '''Half representative pages, half covered NON-representative pages (1-based).

    The non-rep half is the part that tests GENERALIZATION: representative pages
    were visible at induction time, so auditing only those would validate what the
    model already saw. Deterministic (spread picks, no RNG).'''
    meta = _load_cluster_meta(outdir)
# WARNING: Decompyle incomplete


def build_audit_prompt(pdf_path = None, outdir = None, result = None, max_pages = (6, None), pages = ('pdf_path', 'str', 'outdir', 'str', 'result', 'ReplayResult', 'max_pages', 'int', 'pages', 'list[int] | None', 'return', 'tuple[str, list[int]]')):
    '''Pair each sampled page dump with the records the program extracted from it.
    Pass `pages` to re-audit a fixed sample (issue counts are only comparable
    across programs when they are counted on the SAME pages).'''
    pass
# WARNING: Decompyle incomplete


def parse_audit_reply(raw = None):
    '''First complete JSON array in the reply (balanced parse, not greedy regex -
    prose containing brackets before/after the payload must not corrupt it).'''
    dec = json.JSONDecoder()
    idx = raw.find('[')
    if idx != -1:
        
        try:
            (out, _) = dec.raw_decode(raw, idx)
            if isinstance(out, list):
                return out
            idx = raw.find('[', idx + 1)
            if idx != -1:
                continue
            raise ValueError('no JSON array in audit reply')
        except json.JSONDecodeError:
            continue



def audit_issues(verdicts = None):
    return (lambda .0: pass# WARNING: Decompyle incomplete
)(verdicts())


def audit_problem_lines(verdicts = None):
    problems = []
    for v in verdicts:
        p = v.get('page')
        for kind, label in (('missed', 'fields visible on the page but NOT extracted'), ('false', 'extracted records that are not data-entry fields'), ('wrong_form', 'records attributed to the wrong form')):
            if not v.get(kind):
                v.get(kind)
            items = []
            if not items:
                continue
            shown = (lambda .0: pass# WARNING: Decompyle incomplete
)(items[:8]())
            problems.append(f'''Page {p}: {label}: {shown}''' + f''' (+{len(items) - 8} more)''' if len(items) > 8 else '')
    return problems

