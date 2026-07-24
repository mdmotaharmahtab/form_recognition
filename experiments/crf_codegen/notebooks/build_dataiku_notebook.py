"""Generate the Dataiku notebook for the unknown-format CRF pipeline.

The notebook runs inside Dataiku with no repo checkout: the pipeline modules
(common/generic_profile/replay/induction/codegen/sandbox_runner/stage0_cluster/
run_cli_induction/oid_mapping) live in the shared managed folder under
CODE_SUBPATH ('code/'), the bootstrap cell downloads them into a local work
dir, and the notebook drives the SAME induce_document controller that the
local CLI runs - only the LLM transport differs (LLM Mesh vs Cursor CLI).

Usage:
  python build_dataiku_notebook.py               # write dataiku_notebook_pipeline/
                                                 #   CRF_codegen_induction.ipynb + refresh
                                                 #   dataiku_notebook_pipeline/folder_code/
                                                 #   (the .py set to upload to the folder)
  python build_dataiku_notebook.py --selftest    # also prove the module bundle works:
                                                 # import it from a scratch dir and run one
                                                 # document end-to-end with a scripted LLM

Regenerate after ANY change to the pipeline modules, then re-upload the changed
files from dataiku_notebook_pipeline/folder_code/ to the managed folder's code/
subpath. The notebook itself only changes when the CELL logic here changes.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# structured layout: this generator lives in notebooks/ next to the notebook and
# the folder_code staging dir; the pipeline modules live in ../src/pipeline/
SRC_DIR = os.path.join(os.path.dirname(HERE), "src", "pipeline")
PIPELINE_DIR = HERE
OUT_NOTEBOOK = os.path.join(PIPELINE_DIR, "CRF_codegen_induction.ipynb")
FOLDER_CODE_DIR = os.path.join(PIPELINE_DIR, "folder_code")

PIPELINE_MODULES = [
    "common.py",          # page model (+ v1 fingerprint kept as reference)
    "generic_profile.py",  # shipped stage-0 clustering (tokens/damping/theta selection)
    "replay.py",          # FieldRec/ReplayResult types (+ legacy engine baseline)
    "induction.py",       # score + gates (+ legacy recipe path)
    "codegen.py",         # prompts, validation, audit, sandbox launcher
    "sandbox_runner.py",  # child-process runner for generated code
    "stage0_cluster.py",  # stage-0 driver
    "run_cli_induction.py",  # induce_document controller + finalize_document
    "oid_mapping.py",     # name->OID funnel (mapping cell only; needs rapidfuzz)
    "run_report.py",      # stage-attributed error/event report (stdlib only)
]


def read_module(name: str) -> str:
    with open(os.path.join(SRC_DIR, name), encoding="utf-8") as f:
        src = f.read()
    if not src.endswith("\n"):
        src += "\n"
    return src


def code_cell(cell_id: str, src: str) -> dict:
    # nbformat >= 4.5 requires stable cell ids; semantic ids survive regeneration
    return {"cell_type": "code", "id": cell_id, "metadata": {}, "execution_count": None,
            "outputs": [], "source": src}


def md_cell(cell_id: str, src: str) -> dict:
    return {"cell_type": "markdown", "id": cell_id, "metadata": {}, "source": src}


# --------------------------------------------------------------------------- #
# notebook cell sources (plain strings; they must not contain triple-double quotes)
# --------------------------------------------------------------------------- #
INTRO_MD = """\
# Unknown-format CRF digitizer - code-generation induction

For every CRF PDF in the input managed folder - **any vendor format, no template,
no configuration** - a pure-Python pass clusters the pages by structural layout
(word-blind typography tokens, per-document chrome damping, similarity threshold
self-selected per document) and picks a handful of representative pages (~4-12);
the LLM (via LLM Mesh) writes a document-specific Python parser from those pages;
the parser runs in a sandboxed subprocess over the whole document; machine gates
plus an LLM page-grounded audit challenge the result; and the LLM revises its own
code in a bounded loop. Output per document: `(form_name, field_name, page)`
records. OIDs are resolved downstream by name mapping against the rule library.

**Requirements**
- Code env for this notebook (the sandbox subprocess uses the same interpreter):
  `PyMuPDF`, `pandas`; `rapidfuzz` optional (mapping cell only). `tiktoken` is
  deliberately NOT needed here: this notebook only records char counts and the
  verbatim call log; tokenization/cost estimation happens locally via
  `cost_report.py` after you download the run.
- ONE managed folder (`INPUT_FOLDER` = `OUTPUT_FOLDER` below) holding:
  the pipeline module `.py` files under `code/` (upload them from the repo's
  `experiments/recipe_prototype/dataiku_notebook_pipeline/folder_code/`), and
  the input CRF PDFs anywhere else in the folder. All artifacts are written
  back to it.
- LLM Mesh: uses the project variable `default_llm_model` (Claude Sonnet 4.5)
  unless `LLM_ID` overrides it below.

**Models.** Claude Sonnet 4.5 (the project variable `default_llm_model`) is the
PRODUCTION model - benchmark accuracy and the loop's stop rules were tuned
against it. Other models (e.g. GPT 5.2 via `LLM_ID`) are EXPERIMENTS: the
pipeline runs them unchanged, but their results are for comparison, not
production use, until they match the Sonnet benchmark.

**LLM budget - bounded, never endless.** `MAX_VERSIONS` is the base parser-version
budget. Documents below 900 pages use it unchanged; larger books receive one
extra version per full 900 pages, capped at two extras. Each version uses one
generation call, normally followed by one audit call (plus one audit reprompt
when malformed/partial), and the loop permits at most one coverage-confirmation
call. Documents whose page layouts fragment beyond one prompt are split across
up to 4 passes, each with the same effective per-document budget. The loop still
stops early on a clean audit or two consecutive non-improvements; consecutive
gate failures revise until the bounded cap. The best-scoring version, never
merely the last, is exported.

**Sandbox isolation - read before running untrusted PDFs.** Generated parsers
run in a separate killable subprocess with a restricted namespace, but CPython
offers no in-process security boundary - and the LLM that writes the code reads
the PDF's own text, so a hostile document could steer the generated code
(prompt injection). The subprocess runs with THIS kernel's OS privileges and
network access. For PDFs from untrusted sources, run the whole notebook (or at
least its kernel) in an unprivileged, network-less container; for the intended
use - internal CRF books from known sponsors - the standard DSS project
isolation is adequate.

**Every run is fully instrumented and never overwrites the previous one.** All
artifacts upload under a fresh `runs/<RUN_ID>/` prefix (`RUN_ID` = UTC start
time + model tag). Each document additionally gets `timings_<tag>.json` (wall
time per pipeline part), `llm_calls_<tag>.jsonl` (every prompt/reply verbatim -
tokenize locally with `cost_report.py` to estimate spend), and the run gets
`error_events_<tag>.csv` / `error_summary_<tag>.json` - a stage-attributed
error log answering "which part of the pipeline produced this".

*This notebook is generated by `experiments/recipe_prototype/scripts/build_dataiku_notebook.py`.
The pipeline code is NOT embedded here: the bootstrap cell downloads it from the
managed folder's `code/` subpath. To change pipeline behavior, edit the repo
modules and re-upload them from `dataiku_notebook_pipeline/folder_code/` -
regenerate this notebook only when cell logic changes.*
"""

CONFIG_CELL = """\
# ------------------------------- CONFIG -------------------------------------
# ONE managed folder for everything. The id below is ENVIRONMENT-SPECIFIC: it
# is the folder id of this project's shared managed folder on THIS DSS
# instance (the same folder the io-capture notebook ecs_io_capture_384_201_00002
# persists to) - replace it when running in another project/instance. It holds:
#   code/<module>.py        the pipeline modules (upload from
#                           dataiku_notebook_pipeline/folder_code/)
#   *.pdf                   the input CRFs (root or any subpath outside code/)
#   runs/<RUN_ID>/...       artifacts written back by this notebook - one prefix
#                           per run (UTC timestamp + model tag), so a re-run can
#                           never overwrite a previous run's artifacts
# Safe to share because the PDF fetch only picks *.pdf (code/ is skipped) and
# the artifact upload writes no PDFs.
INPUT_FOLDER = '3UkrB0N9'            # managed folder (name or id) with input CRF PDFs
OUTPUT_FOLDER = '3UkrB0N9'           # managed folder (name or id) for all artifacts
CODE_SUBPATH = 'code'                # subpath in that folder holding the module .py files
# Which LLM writes/audits the parsers. The model tag (slug of this id) is part
# of RUN_ID and of every artifact filename, so runs with different models can
# never overwrite or be confused with each other:
#   None                                        -> project var 'default_llm_model'
#                                                  (Claude Sonnet 4.5 on Bedrock -
#                                                  the PRODUCTION model)
#   'azureopenai:Azure-OpenAi-NoCache:gpt-5.2'  -> GPT 5.2 - EXPERIMENT runs only
LLM_ID = None
# maxOutputTokens mirrors production's max_tokens=16000 (python/utilities/llm.py).
# Largest reply observed in the benchmark runs was ~3.5K tokens, so this is ~5x
# headroom: a truncated parser is a syntax error that burns a whole revision
# cycle, while unused cap costs nothing (output tokens bill only when generated).
COMPLETION_SETTINGS = {'temperature': 0.2, 'maxOutputTokens': 16000}  # best effort

MAX_VERSIONS = 5     # base cap; 900+ page books receive up to 2 bounded extras
DOC_FILTER = ''      # substring filter on PDF names ('' = all)
MAX_DOCS = None      # int -> cap the number of documents (smoke runs)

UPLOAD_PAGE_PNGS = False   # representative-page PNGs are handy but heavy
RUN_OID_MAPPING = False    # name->OID funnel + LLM ranker (see mapping cell)
ECS_INDEX_DATASET = 'ecs_index_data'  # dataset with form_field_value / variable_name

WORK_DIR = None      # None -> ./crf_codegen_work under the kernel's cwd
"""

BOOTSTRAP_CELL = """\
# Bootstrap: download the pipeline modules from the managed folder's code/
# subpath into a local work dir (no repo checkout on the DSS host). The work
# dir is plain local scratch - created here, disposable, re-runnable.
import os
import sys

import dataiku

WORK = os.path.abspath(WORK_DIR or 'crf_codegen_work')
MODULES_DIR = os.path.join(WORK, 'modules')
os.makedirs(MODULES_DIR, exist_ok=True)
# pipeline paths (input staging dir, output dir) derive from this env var;
# it must be set BEFORE the modules are imported
os.environ['ECS_BASE'] = WORK

EXPECTED_MODULES = __MODULE_LIST__

_folder = dataiku.Folder(INPUT_FOLDER)
_prefix = '/' + CODE_SUBPATH.strip('/') + '/'
_found = {}
for _p in _folder.list_paths_in_partition():
    if ('/' + _p.lstrip('/')).startswith(_prefix) and _p.endswith('.py'):
        _found[_p.rsplit('/', 1)[-1]] = _p

_missing = sorted(set(EXPECTED_MODULES) - set(_found))
if _missing:
    raise RuntimeError(
        'pipeline modules missing from folder ' + str(INPUT_FOLDER) + ' under '
        + _prefix + ' : ' + ', '.join(_missing)
        + ' - upload them from the repo dir '
        + 'experiments/recipe_prototype/dataiku_notebook_pipeline/folder_code/')

for _name in EXPECTED_MODULES:
    with _folder.get_download_stream(_found[_name]) as _s:
        _src = _s.read()
    with open(os.path.join(MODULES_DIR, _name), 'wb') as _f:
        _f.write(_src)
    print('module fetched:', _name, '(' + str(len(_src)) + ' bytes)')
"""

IMPORT_CELL = """\
# Import the pipeline from the materialized modules. Pop-and-import (never
# importlib.reload): reload would re-execute a module from wherever it was FIRST
# imported, so a foreign 'codegen'/'common' already living in the kernel would
# silently shadow the bundle. Re-run safe top to bottom.
_PIPELINE_MODULES = ('common', 'generic_profile', 'replay', 'induction',
                     'codegen', 'stage0_cluster', 'run_cli_induction',
                     'run_report')
if MODULES_DIR not in sys.path:
    sys.path.insert(0, MODULES_DIR)
for _m in _PIPELINE_MODULES:
    sys.modules.pop(_m, None)

import common
import codegen
import stage0_cluster
import run_cli_induction as rci
import run_report

for _m in _PIPELINE_MODULES:
    _f = os.path.abspath(getattr(sys.modules[_m], '__file__', '') or '')
    assert _f.startswith(os.path.abspath(MODULES_DIR) + os.sep), \
        _m + ' imported from ' + _f + ' instead of the bundle - check sys.path'

from common import CRF_DIR, OUT_DIR, doc_key, list_root_pdfs

os.makedirs(CRF_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
print('work dir:', WORK)
"""

FETCH_CELL = """\
# Stage the input PDFs from the managed folder into the local work dir
# (PyMuPDF needs real files; managed folders may be S3-backed). PDFS - the list
# bound HERE - is what every later cell iterates: a warm work dir from an
# earlier session never adds documents the current DOC_FILTER excludes.
import re
import shutil

import dataiku

folder_in = dataiku.Folder(INPUT_FOLDER)
paths = sorted(p for p in folder_in.list_paths_in_partition() if p.lower().endswith('.pdf'))
if DOC_FILTER:
    paths = [p for p in paths if DOC_FILTER.lower() in p.lower()]
if MAX_DOCS:
    paths = paths[:MAX_DOCS]

flat = {}
for p in paths:
    local_name = re.sub(r'[\\\\/]+', '_', p.strip('/'))
    if local_name in flat:
        raise RuntimeError('two folder paths flatten to the same file name: '
                           + flat[local_name] + ' and ' + p + ' -> ' + local_name)
    flat[local_name] = p

PDFS = []
for local_name, p in sorted(flat.items()):
    dest = os.path.join(CRF_DIR, local_name)
    with folder_in.get_download_stream(p) as s, open(dest, 'wb') as f:
        shutil.copyfileobj(s, f)  # always overwrite - folder content may have changed
    PDFS.append(dest)
    # start each document from a CLEAN slate: a warm work dir from an earlier
    # session may hold artifacts of that session (e.g. a v3 reply when this run
    # stops at v2) which would otherwise leak into this run's timestamped upload
    shutil.rmtree(os.path.join(OUT_DIR, doc_key(dest)), ignore_errors=True)

_keys = [doc_key(p) for p in PDFS]
assert len(set(_keys)) == len(_keys), \
    'doc_key collision among input PDFs (near-identical names) - rename the colliding files'
assert CODE_SUBPATH.strip('/') not in _keys, \
    'a PDF resolves to doc_key "' + CODE_SUBPATH + '" - its artifacts would mingle ' \
    'with the module subpath; rename the file'
print(len(PDFS), 'pdf(s) staged')
for p in PDFS:
    print('  ', os.path.basename(p))
"""

STAGE0_CELL = """\
# Stage 0 (pure Python, no LLM): cluster every page by structural layout and
# pick representative pages. The clusterer (generic_profile) is word-blind:
# each line becomes a typography/geometry token, tokens the document repeats
# on nearly every page (its own header/footer chrome) are discovered and
# down-weighted, pages are grouped by weighted-Jaccard similarity, and the
# similarity threshold theta is selected PER DOCUMENT by stability - no
# corpus-tuned constants. Encrypted or scanned (no text layer) PDFs are
# flagged here and never spend LLM budget. One corrupt PDF must not sink the
# batch: it is reported and skipped (no clusters.json -> the induction cell
# records it as skipped).
for _pdf in PDFS:
    try:
        _m = stage0_cluster.run(_pdf)
    except Exception as _e:
        print(f"{os.path.basename(_pdf)[:58]:58s} stage0 FAILED: {_e!r}")
        continue
    _flag = '' if _m.get('status') == 'ok' else '  [' + _m['status'] + ' - will skip induction]'
    _theta = ' theta*=%.2f' % _m['theta'] if _m.get('theta') is not None else ''
    print(f"{_m['file'][:58]:58s} pages={_m['pages']:5d} clusters={_m['n_clusters']:3d} "
          f"reps={len(_m['representative_pages_1based']):3d}{_theta}{_flag}")
"""

MESH_CELL = """\
# LLM transport: Dataiku LLM Mesh (same get_llm/new_completion conventions as
# the ECS generation recipes). Plain-text completion per call, bounded retries.
# A system message frames every call: raw mesh completions arrive with no
# persona at all, unlike agent transports whose wrapper supplies one - and the
# same prompts measurably produce more careful programs under an engineer
# persona. Task-neutral on purpose (the same frame serves generation, revision,
# audits and coverage confirmation).
import time

SYSTEM_PROMPT = (
    'Read the task and its input completely before answering; verify your '
    'logic against the data shown; reply in exactly the format the task '
    'requests, with nothing extra.')

client = dataiku.api_client()
project = client.get_default_project()
llm_id = LLM_ID or project.get_variables()['local'].get('default_llm_model')
assert llm_id, 'set LLM_ID or the project variable default_llm_model'
llm = project.get_llm(llm_id)

def call_mesh(prompt, retries=2, backoff_s=15):
    last = None
    for attempt in range(retries + 1):
        try:
            comp = llm.new_completion()
            try:
                comp.settings.update(COMPLETION_SETTINGS)
            except Exception as e:
                # settings shape varies across mesh/provider versions; warn ONCE -
                # without maxOutputTokens the provider default cap may truncate
                # long generated programs (which then fail gates and burn budget)
                if not getattr(call_mesh, '_settings_warned', False):
                    call_mesh._settings_warned = True
                    print('WARNING: completion settings not applied (' + repr(e)
                          + '); mesh defaults in effect')
            try:
                comp.with_message(SYSTEM_PROMPT, role='system')
                comp.with_message(prompt)
            except TypeError:
                # very old mesh clients: with_message has no role kwarg - fold
                # the frame into the user message instead of dropping it
                if not getattr(call_mesh, '_sysrole_warned', False):
                    call_mesh._sysrole_warned = True
                    print('WARNING: system role unsupported; prepending preamble '
                          'to the user message')
                comp = llm.new_completion()
                try:
                    comp.settings.update(COMPLETION_SETTINGS)
                except Exception:
                    pass
                comp.with_message(SYSTEM_PROMPT + '\\n\\n' + prompt)
            resp = comp.execute()
            if getattr(resp, 'success', False) and (resp.text or '').strip():
                return resp.text
            last = RuntimeError('unsuccessful or empty completion')
        except Exception as e:
            last = e
        if attempt < retries:
            time.sleep(backoff_s * (attempt + 1))
    raise RuntimeError('LLM Mesh call failed after ' + str(retries + 1) + ' attempts: ' + repr(last))

print('LLM Mesh id:', llm_id)
"""

INDUCTION_CELL = """\
# The induction loop. rci.run_document drives the SAME controller validated by
# stop_policy_test.py locally; only the transport (call_mesh) is Dataiku-specific.
# Stop rules: converged (clean audit) / plateau (two consecutive versions
# without improvement) / budget (MAX_VERSIONS) - best version wins. Documents
# with more layout families than one prompt can show run as MULTI-PASS
# specialists (up to 4 passes, each with its own budget; artifacts carry a
# _passN suffix and merge into the plain-tag document artifacts).
# A per-document failure becomes a summary row, never a lost batch (this can be
# a multi-hour paid run). Summary file is induction_summary_<tag>.json - the
# 'cli_' prefix is reserved for the local CLI driver so runs cannot be confused.
#
# Instrumentation (all free of LLM budget):
#   RUN_ID                     minted here; every upload lands under runs/<RUN_ID>/
#   timings_<tag>.json         per document: stage0_s, llm time by call kind,
#                              sandbox time, export_s, total_s
#   llm_calls_<tag>.jsonl      per document: every prompt/reply verbatim
#   error_events_<tag>.csv     run-level: stage-attributed error/event log
#   run_info_<tag>.json        run-level: config + start/end + document list
import json
import time

tag = rci.slug(llm_id)
RUN_ID = time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '_' + tag
_run_started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
print('RUN_ID:', RUN_ID, '(all artifacts upload under runs/' + RUN_ID + '/)')

summary = []
for _pdf in PDFS:
    _key = doc_key(_pdf)
    _outdir = os.path.join(OUT_DIR, _key)
    print('===', _key)
    _profile = {'doc_t0': time.perf_counter()}
    try:
        _meta = rci.doc_meta(_outdir)
        _status = _meta.get('status', 'ok')
        if _status != 'ok':
            _row = {'doc': _key, 'status': 'skipped_' + _status}
            if _meta.get('elapsed_s') is not None:
                _row['stage0_s'] = _meta['elapsed_s']
            summary.append(_row)
            print('    skipped:', _status)
            continue
        # prompts are built fresh from the CURRENT stage-0 artifacts inside
        # run_document (and saved as codegen_prompt*.txt for inspection)
        _row = rci.run_document(call_mesh, llm_id, tag, _key, _pdf, _outdir,
                                MAX_VERSIONS, profile=_profile)
        if _meta.get('text_layer_pct', 100) < 100:
            # partially scanned book: its no-text pages are unreachable (OCR out
            # of scope) - surface that in the summary instead of hiding it
            _row['text_layer_pct'] = _meta['text_layer_pct']
    except Exception as _e:
        _row = {'doc': _key, 'status': 'error', 'error': repr(_e),
                'elapsed_s': round(time.perf_counter() - _profile['doc_t0'], 3)}
    summary.append(_row)
    print('    ->', _row)

with open(os.path.join(OUT_DIR, 'induction_summary_' + tag + '.json'), 'w', encoding='utf-8') as f:
    json.dump(summary, f, indent=1)

# run metadata: enough to know later what produced runs/<RUN_ID>/
with open(os.path.join(OUT_DIR, 'run_info_' + tag + '.json'), 'w', encoding='utf-8') as f:
    json.dump({'run_id': RUN_ID, 'llm_id': llm_id, 'max_versions': MAX_VERSIONS,
               'doc_filter': DOC_FILTER, 'max_docs': MAX_DOCS,
               'completion_settings': COMPLETION_SETTINGS,
               'documents': [doc_key(p) for p in PDFS],
               'started_utc': _run_started,
               'finished_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'total_s': round(sum(r.get('elapsed_s') or 0 for r in summary), 1)},
              f, indent=1)

# stage-attributed error report: WHERE do errors/quality issues come from?
_events = run_report.collect_run_events(OUT_DIR, tag, summary)
_ev_csv, _ev_json = run_report.write_reports(OUT_DIR, tag, summary, _events)
_by_stage = {}
for _e in _events:
    _by_stage[_e['stage']] = _by_stage.get(_e['stage'], 0) + 1
print('error report:', len(_events), 'event(s)', _by_stage or '(clean run)')

import pandas as pd
pd.DataFrame(summary)
"""

UPLOAD_CELL = """\
# Persist all artifacts to the output managed folder under runs/<RUN_ID>/,
# mirroring the local out/ tree: <doc_key>/clusters.json, rep_p*.txt,
# codegen_prompt.txt, codegen_reply_*<n>.py, codegen_trail_*.json,
# generated_extractor_*.py, fields_codegen_*.csv, timings_*.json,
# llm_calls_*.jsonl, plus induction_summary/run_info/error_* at the run root.
# The per-run prefix means a re-run NEVER overwrites a previous run.
# Scope: THIS run's documents only. A warm work dir may hold artifacts of
# documents an earlier session processed but the current DOC_FILTER excludes -
# re-uploading those would contradict the run scoping FETCH_CELL guarantees.
folder_out = dataiku.Folder(OUTPUT_FOLDER)
RUN_PREFIX = 'runs/' + RUN_ID + '/'
_run_keys = {doc_key(_p) for _p in PDFS}
uploaded = 0
for _root, _dirs, _files in os.walk(OUT_DIR):
    for _fn in _files:
        if _fn.endswith('.png') and not UPLOAD_PAGE_PNGS:
            continue
        _full = os.path.join(_root, _fn)
        _rel = os.path.relpath(_full, OUT_DIR).replace(os.sep, '/')
        _top = _rel.split('/')[0]
        if '/' in _rel and _top not in _run_keys:
            continue  # another session's document dir
        with open(_full, 'rb') as f:
            folder_out.upload_stream(RUN_PREFIX + _rel, f)
        uploaded += 1
print('uploaded', uploaded, 'file(s) to folder', OUTPUT_FOLDER,
      'under', RUN_PREFIX, 'for', len(_run_keys), 'document(s)')
"""

MAPPING_CELL = """\
# OPTIONAL - name->OID mapping via the form-first funnel (oid_mapping.py):
#   1. form scoping   partial_ratio >= 70 (production's own convention,
#                     review_table.get_standard_crf)
#   2. field in form  token_sort_ratio >= 85 against the scoped rows only
#   3. LLM ranker     EVERY candidate-bearing pair is judged via LLM Mesh -
#                     pick one of the listed OIDs or refuse. String scores
#                     generate candidates; they never certify them.
# Unmapped pairs are safe by design: production writes LLM-generated rules
# from the names alone. Measured on the ground-truth book: 94% of what it
# maps is correct; coverage is bounded by library breadth, not this logic.
# Needs rapidfuzz. CAVEAT: _norm strips every non-ASCII character, so on
# non-Latin documents (or a non-Latin library) mapping coverage will be ~0%.
if RUN_OID_MAPPING:
    import csv
    import re

    import pandas as pd

    sys.modules.pop('oid_mapping', None)  # same rerun hygiene as the import cell
    import oid_mapping
    assert os.path.abspath(oid_mapping.__file__).startswith(
        os.path.abspath(MODULES_DIR) + os.sep), 'oid_mapping imported from outside the bundle'

    def _norm(s):
        s = re.sub(r'\\(.*?\\)', ' ', str(s or '').lower())
        s = re.sub(r'[^a-z0-9 ]+', ' ', s)
        return re.sub(r'\\s+', ' ', s).strip()

    _lib_df = dataiku.Dataset(ECS_INDEX_DATASET).get_dataframe()
    _need = {'form_field_value', 'variable_name'}
    assert _need <= set(_lib_df.columns), ECS_INDEX_DATASET + ' must have columns ' + str(_need)
    _lib_df = _lib_df.fillna('')  # NaN is truthy - without this it becomes the string 'nan'
    _lib = []
    for _, _r in _lib_df.iterrows():
        _fv = str(_r.get('form_field_value') or '').strip()
        _vn = str(_r.get('variable_name') or '').strip()
        _fnorm = _norm(_fv)
        if not (_fv and _vn and _fnorm):  # drop rows whose label normalizes away
            continue
        _lib.append({'field': _fnorm, 'form': _norm(_r.get('form_name', '')),
                     'oid': _vn, 'field_raw': _fv,
                     'form_raw': str(_r.get('form_name', '')).strip()})
    print('library entries:', len(_lib))
    _formless = sum(1 for _e in _lib if not _e['form'])
    if _formless > len(_lib) // 2:
        # without form names layer-1 scoping matches nothing -> universal
        # unmapped that LOOKS like safe abstention but is a dataset problem
        print('WARNING:', _formless, 'of', len(_lib), 'library rows have no '
              'form_name - form scoping will unmap nearly everything')

    _done = _skipped = 0
    _map_events, _map_csvs = [], []
    for _key in sorted(os.listdir(OUT_DIR)):
        _src = os.path.join(OUT_DIR, _key, 'fields', 'fields_codegen_' + tag + '.csv')
        if not os.path.isdir(os.path.join(OUT_DIR, _key)):
            continue
        if not os.path.isfile(_src):
            _skipped += 1
            continue
        with open(_src, encoding='utf-8') as f:
            _pairs = sorted({(_norm(r['form_name']), _norm(r['field_name']))
                             for r in csv.DictReader(f)})
        try:
            # one Mesh failure must not sink the batch (rank_cases commits
            # nothing on failure, so there is no half-ranked state to persist)
            _results = oid_mapping.map_pairs(_pairs, _lib, llm=call_mesh)
        except Exception as _e:
            print(f'{_key[:52]:52s} mapping FAILED: {_e!r}')
            continue
        _rows = [{'form_name': r.form, 'field_name': r.field, 'status': r.status,
                  'oid': r.oid or '', 'via': r.via if r.status == 'mapped' else '',
                  'reason': r.reason, 'n_candidates': len(r.candidates)}
                 for r in _results]
        _csv_local = os.path.join(OUT_DIR, _key, 'oid_mapping_' + tag + '.csv')
        pd.DataFrame(_rows).to_csv(_csv_local, index=False)
        _map_events.extend(run_report.mapping_events(_key, _results))
        _map_csvs.append((_key, _csv_local))
        _done += 1
        _mapped = [r for r in _results if r.status == 'mapped']
        _by = {v: sum(1 for r in _mapped if r.via == v)
               for v in sorted({r.via for r in _mapped})}
        print(f'{_key[:52]:52s} pairs={len(_pairs):5d} mapped={len(_mapped):4d} '
              f'({100 * len(_mapped) // max(1, len(_pairs))}%) by={_by}')
    print('mapped', _done, 'document(s);', _skipped,
          'dir(s) had no fields_codegen_' + tag + '.csv (check tag/run)')

    # fold the mapping outcomes into the run error report (per-reason counts),
    # then persist everything under this run's prefix - no manual re-upload step
    _all_events = run_report.collect_run_events(OUT_DIR, tag, summary) + _map_events
    run_report.write_reports(OUT_DIR, tag, summary, _all_events)
    _folder_out = dataiku.Folder(OUTPUT_FOLDER)
    _prefix = 'runs/' + RUN_ID + '/'
    for _k, _p in _map_csvs:
        with open(_p, 'rb') as f:
            _folder_out.upload_stream(_prefix + _k + '/' + os.path.basename(_p), f)
    for _fn in ('error_events_' + tag + '.csv', 'error_summary_' + tag + '.json'):
        with open(os.path.join(OUT_DIR, _fn), 'rb') as f:
            _folder_out.upload_stream(_prefix + _fn, f)
    print('uploaded', len(_map_csvs), 'mapping CSV(s) + refreshed error report under', _prefix)
else:
    print('RUN_OID_MAPPING is False - skipped')
"""

OUTPUTS_MD = """\
## Reading the outputs

Everything for one run lives under `runs/<RUN_ID>/` in the output folder
(`RUN_ID` is printed by the induction cell); re-runs never overwrite it.

Per document (under `runs/<RUN_ID>/<doc_key>/`). Artifacts are grouped into
per-type **buckets** (no more flat file dumps); the bucket folder is shown in
each path below:

| artifact | meaning |
|---|---|
| `stage0/clusters.json` | stage-0 layout clusters, representative pages, selected `theta`, `status`, `elapsed_s` |
| `stage0/rep_p<N>.txt` | the representative page dumps the LLM saw (text + geometry) |
| `prompts/codegen_prompt.txt` | the exact induction prompt |
| `replies/codegen_reply_<tag>_<n>.py` | every parser version the LLM wrote |
| `replies/codegen_reply_<tag>_confirm.txt` | the coverage-confirmation reply, if that round ran |
| `trails/codegen_trail_<tag>.json` | per-version metrics/problems/audit + `stop_reason` + `best_version` |
| `extractors/generated_extractor_<tag>.py` | the accepted (best) parser |
| `fields/fields_codegen_<tag>.csv` | final `form_name, field_name, page` extraction |
| `prompts/codegen_prompt_pass<N>.txt`, `*/*_<tag>_pass<N>.*` | multi-pass specialists only: per-pass prompts/replies/trails/CSVs land in the same buckets with a `_passN` tag suffix; the plain-tag CSV/trail/call-log are the MERGED document-level outputs, and `codegen_prompt.txt` is not written for such documents |
| `oid_mapping_<tag>.csv` | optional name->OID funnel result: status / oid / via / reason (mapping cell); stays at the doc root |
| `timings/timings_<tag>.json` | time profile: `stage0_s`, LLM time by call kind, sandbox time, `export_s`, `total_s` |
| `llm_calls/llm_calls_<tag>.jsonl` | every LLM call verbatim (prompt + reply + seconds + sizes) |

At the run root (`runs/<RUN_ID>/`):

| artifact | meaning |
|---|---|
| `induction_summary_<tag>.json` | one row per document: status, versions, fields + `elapsed_s`, `llm_s`, `llm_calls`, `stage0_s` |
| `run_info_<tag>.json` | run config, document list, start/end UTC, total wall time |
| `error_events_<tag>.csv` | stage-attributed event log: `doc, stage, version, severity, code, detail` |
| `error_summary_<tag>.json` | event counts by stage / code / severity / doc |

**Cost analysis** happens locally, not here: download `runs/<RUN_ID>/` and run
`python cost_report.py --tag <tag> --run-dir <downloaded dir>` (repo:
`experiments/crf_codegen/src/evaluation/`). It tokenizes the `llm_calls` records
with tiktoken (~+/-10-15% proxy for Claude's tokenizer) and prices them per MTok.

Summary `status` values: `ok` (clean audit, no warnings) / `ok_with_warnings`
(soft quality signals; document may legitimately violate them) /
`ok_audit_issues` (best version still has known page-level issues - review) /
`ok_unaudited` (audit errored; parser passed gates but was never page-verified) /
`needs_manual_template` (every version hard-failed - human review) /
`export_failed` (best parser accepted but the final replay crashed - re-run) /
`error` (unexpected per-document failure; see the cell output for the traceback) /
`skipped_encrypted`, `skipped_no_text_layer`, `skipped_no_pages`,
`skipped_missing_stage0` (stage 0 refused or failed on the PDF; OCR is out of
scope by design - fail loudly, never guess). A row may additionally carry
`text_layer_pct` when the book is PARTIALLY scanned (>=20% text pages proceed,
but the scanned pages are unreachable and their fields cannot appear in the
output - review such documents).

**Not in this notebook**: ground-truth evaluation (no annotated truth exists on
the Dataiku side; the local repo has `eval_form_field.py` for the one document
with printed OIDs) and the production OID-assignment step (form-scoped
candidates + LLM ranking - designed separately; the mapping cell here is the
lexical baseline only).
"""


def build_notebook() -> dict:
    bootstrap = BOOTSTRAP_CELL.replace(
        "__MODULE_LIST__",
        "[" + ", ".join(repr(n) for n in PIPELINE_MODULES) + "]")
    cells = [
        md_cell("intro", INTRO_MD),
        code_cell("config", CONFIG_CELL),
        code_cell("bootstrap", bootstrap),
        code_cell("imports", IMPORT_CELL),
        code_cell("fetch-pdfs", FETCH_CELL),
        code_cell("stage0", STAGE0_CELL),
        code_cell("mesh-transport", MESH_CELL),
        code_cell("induction-loop", INDUCTION_CELL),
        code_cell("upload-artifacts", UPLOAD_CELL),
        code_cell("oid-mapping", MAPPING_CELL),
        md_cell("outputs-guide", OUTPUTS_MD),
    ]
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def export_folder_code() -> None:
    """Write the exact module set to dataiku/folder_code/ - the upload staging
    dir for the managed folder's code/ subpath. Stale files from renamed or
    dropped modules are removed so the dir always mirrors PIPELINE_MODULES."""
    os.makedirs(FOLDER_CODE_DIR, exist_ok=True)
    for fn in os.listdir(FOLDER_CODE_DIR):
        if fn.endswith(".py") and fn not in PIPELINE_MODULES:
            os.remove(os.path.join(FOLDER_CODE_DIR, fn))
    for name in PIPELINE_MODULES:
        with open(os.path.join(FOLDER_CODE_DIR, name), "w", encoding="utf-8",
                  newline="\n") as f:
            f.write(read_module(name))


# --------------------------------------------------------------------------- #
# selftest: prove the module bundle (what folder_code/ ships) is complete and
# the controller runs on it from a scratch dir, exactly like the notebook does
# --------------------------------------------------------------------------- #
SELFTEST_PROGRAM = """\
# selftest parser: two plausible text lines per page become field records.
# The page suffix keeps records distinct across pages (repeated headers/footers
# would otherwise dedup to a single record and trip the volume gate) - this
# validates PLUMBING, not extraction quality.
def extract(pages):
    out = []
    for pno, lines in pages:
        kept = 0
        for L in lines:
            letters = sum(1 for c in L.text if c.isalpha())
            if letters >= 4 and len(L.text) <= 120:
                out.append({'form_name': 'Selftest Section',
                            'field_name': L.text[:60] + ' (p' + str(pno + 1) + ')',
                            'page': pno + 1})
                kept += 1
                if kept == 2:
                    break
    return out
"""


def selftest() -> None:
    import re
    import shutil
    import tempfile
    import time

    import fitz

    work = tempfile.mkdtemp(prefix="crf_nb_selftest_")
    modules = os.path.join(work, "modules")
    os.makedirs(modules)
    # stage from folder_code/ (the dir the user uploads), not the repo sources:
    # this catches an export bug, not just a source bug
    export_folder_code()
    for name in PIPELINE_MODULES:
        with open(os.path.join(FOLDER_CODE_DIR, name), encoding="utf-8") as src:
            with open(os.path.join(modules, name), "w", encoding="utf-8") as f:
                f.write(src.read())

    os.environ["ECS_BASE"] = work
    sys.path.insert(0, modules)
    names = ("common", "generic_profile", "replay", "induction", "codegen",
             "stage0_cluster", "run_cli_induction", "run_report")
    for m in names:
        sys.modules.pop(m, None)  # same pop-and-import mechanism as the notebook's import cell
    import common  # noqa: PLC0415
    import codegen  # noqa: PLC0415
    import run_cli_induction as rci  # noqa: PLC0415
    import run_report  # noqa: PLC0415
    import stage0_cluster  # noqa: PLC0415
    # every module must come from the BUNDLE: the repo dir is still on sys.path
    # (this script's own dir), so a module missing from PIPELINE_MODULES would be
    # silently satisfied by the repo and the "standalone" claim would be false
    for m in names:
        f = os.path.abspath(getattr(sys.modules[m], "__file__", "") or "")
        assert f.startswith(modules + os.sep), f"{m} imported from {f}, not the bundle"
    assert os.path.isfile(os.path.join(modules, "sandbox_runner.py")), \
        "sandbox_runner.py missing from the bundle"
    assert common.BASE == work, f"bundle ignored ECS_BASE: {common.BASE}"

    os.makedirs(common.CRF_DIR, exist_ok=True)
    os.makedirs(common.OUT_DIR, exist_ok=True)

    # smallest local PDF keeps the run fast
    def page_count(p: str) -> int:
        with fitz.open(p) as d:
            return d.page_count

    # repo root = three levels above scripts/ (ECS/experiments/recipe_prototype/scripts)
    src_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))),
                           "data", "crf_forms")
    candidates = [os.path.join(src_dir, fn) for fn in os.listdir(src_dir)
                  if fn.lower().endswith(".pdf")]
    assert candidates, f"no PDFs in {src_dir} to selftest against"
    pdf_src = min(candidates, key=page_count)
    pdf = os.path.join(common.CRF_DIR, os.path.basename(pdf_src))
    shutil.copyfile(pdf_src, pdf)

    meta = stage0_cluster.run(pdf)
    assert meta["status"] == "ok", meta
    assert meta.get("elapsed_s", 0) > 0, "stage0 elapsed_s missing from clusters.json"

    key = common.doc_key(pdf)
    outdir = os.path.join(common.OUT_DIR, key)
    prompt = codegen.build_codegen_prompt(pdf, outdir)
    with open(os.path.join(outdir, "codegen_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(prompt)

    def transport(p: str) -> str:
        if "You are auditing the output" in p:  # audit -> clean verdict per shown page
            # Context lookback pages are deliberately NOT audit targets.
            pages = sorted({int(m) for m in re.findall(
                r"^--- page (\d+) AUDIT THIS PAGE ---", p, re.M)})
            return json.dumps([{"page": n, "missed": [], "false": [], "wrong_form": []}
                               for n in pages])
        if "You previously wrote the extraction program" in p:  # coverage confirm
            return "CONFIRM_NO_FIELDS"
        return SELFTEST_PROGRAM

    profile = {"doc_t0": time.perf_counter()}
    best, trail, stop, versions = rci.induce_document(
        transport, "selftest-model", "selftest", pdf, outdir, prompt, 3, profile=profile)
    row = rci.finalize_document(key, pdf, outdir, "selftest", best, trail, stop,
                                versions, profile=profile)
    print("selftest row:", row)
    # pin the exact happy path: a broken audit pipeline would surface as
    # plateau/ok_unaudited here, which a loose startswith("ok") would miss
    assert stop == "converged", f"expected converged, got {stop}"
    assert row["status"] == "ok", row
    assert os.path.isfile(os.path.join(outdir, "fields_codegen_selftest.csv"))
    assert os.path.isfile(os.path.join(outdir, "codegen_trail_selftest.json"))

    # ---- profiling artifacts: timings + verbatim call log --------------------
    # exact call count depends on whether the coverage-confirm round fires for
    # the chosen PDF; pin the structure instead: generate first, audit last,
    # nothing but generate/confirm/audit in between, and counts consistent
    assert row.get("elapsed_s", 0) > 0 and row.get("llm_calls", 0) >= 2, row
    with open(os.path.join(outdir, "timings_selftest.json"), encoding="utf-8") as f:
        tm = json.load(f)
    assert tm["stage0_s"] > 0 and tm["total_s"] > 0 and tm["export_s"] is not None, tm
    assert tm["sandbox_validate_calls"] >= 1, tm
    with open(os.path.join(outdir, "llm_calls_selftest.jsonl"), encoding="utf-8") as f:
        calls = [json.loads(ln) for ln in f if ln.strip()]
    kinds = [c["kind"] for c in calls]
    assert (len(calls) == row["llm_calls"] == tm["llm_calls"]
            and kinds[0] == "generate" and kinds[-1] == "audit"
            and set(kinds) <= {"generate", "confirm", "audit"}), kinds
    assert set(tm["llm_by_kind"]) == set(kinds), tm["llm_by_kind"]
    assert all(c["prompt"] and c["reply"] and c["s"] >= 0 for c in calls)

    # ---- error report: synthetic trail exercises the classifier --------------
    fake_trail = {"stop_reason": "plateau", "cycles": [
        {"version": 1, "kind": "generate",
         "problems": ["Program failed to run: boom"], "warnings": []},
        {"version": 2, "kind": "revise_gates", "problems": [],
         "warnings": ["form_name empty for 40% of records - ..."],
         "audit_verdicts": [{"page": 7, "missed": ["Weight"], "false": [],
                             "wrong_form": ["Height -> Vitals"]}],
         "audit_partial": True},
    ]}
    fake_row = {"doc": "fake", "status": "ok_audit_issues", "audit_issues": 2}
    ev = run_report.events_for_doc("fake", fake_trail, fake_row)
    codes = sorted(e["code"] for e in ev)
    assert codes == ["audit_missed", "audit_partial_reply", "audit_wrong_form",
                     "gate_crash", "stopped_with_open_issues",
                     "warn_form_names_empty"], codes
    stages = {e["code"]: e["stage"] for e in ev}
    assert stages["gate_crash"] == "gates" and stages["audit_missed"] == "audit"

    # and on the REAL selftest run: a clean converged doc yields zero events
    real_ev = run_report.collect_run_events(common.OUT_DIR, "selftest", [row])
    assert real_ev == [], real_ev
    ev_csv, ev_json = run_report.write_reports(common.OUT_DIR, "selftest", [row], real_ev)
    assert os.path.isfile(ev_csv) and os.path.isfile(ev_json)

    shutil.rmtree(work, ignore_errors=True)
    print("selftest PASSED: bundle imports cleanly, stage0 + loop + export + "
          "profiling + error report ran end-to-end")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true",
                    help="run the module bundle end-to-end with a scripted LLM")
    args = ap.parse_args()

    nb = build_notebook()
    os.makedirs(os.path.dirname(OUT_NOTEBOOK), exist_ok=True)
    with open(OUT_NOTEBOOK, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=1)
    size_kb = os.path.getsize(OUT_NOTEBOOK) // 1024
    print(f"wrote {OUT_NOTEBOOK} ({len(nb['cells'])} cells, {size_kb} KB)")

    export_folder_code()
    print(f"wrote {FOLDER_CODE_DIR}{os.sep} ({len(PIPELINE_MODULES)} modules "
          f"- upload these to the managed folder's code/ subpath)")

    if args.selftest:
        selftest()


if __name__ == "__main__":
    main()
