# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage3plus_2026-07-22\run_cli_induction.cpython-311.pyc (Python 3.11)

'''Run the codegen induction loop against a REAL external model via the Cursor CLI.

This exists to validate the production model (Claude Sonnet 4.5) locally, before
the Dataiku notebook run. The CLI call is a plain chat completion: the prompt file
goes in on stdin, the reply comes out on stdout. The agent process runs in an
EMPTY sandbox directory outside the repo: its working dir exposes nothing. (A
print-mode agent does retain tool access to absolute paths, so the blind
property also rests on the prompt containing page dumps only - never repo or
artifact paths.)

Loop semantics (mirrors the intended Dataiku notebook). Every cycle produces ONE
parser version and ends with one comparable result:

  generate/revise -> full-document run + gates
                  -> [one-time coverage confirmation; an adopted extension is
                     scored as its OWN next version, after the pre-extension
                     program got its own trail entry and chance at best]
                  -> grounded audit on a page sample FIXED at the first audit
                  -> version_score = (hard problems, audit issues, warnings, -coverage)

Stopping (no phase-local budgets; one rule set for the whole loop):
  converged  gates pass, the audit finds zero issues, and the version is the new
             best -> accept immediately
  plateau    a version fails to strictly improve on the PREVIOUS one
             (diminishing returns; audit counts are compared on the same pages,
             and a version that loses >10% page coverage never counts as improved
             - neither for continuing the loop nor for best selection). Two
             CONSECUTIVE gate-failed versions never plateau: identical crash
             scores are not diminishing returns, they are zero returns - the
             revision loop keeps trying until the budget cap.
  budget     at most --max-versions cycles (default 5)
  error      transport/audit failure -> stop with what we have

A zero-issue audit is only TRUSTED when the reply actually covers every audited
page; a malformed or partial audit reply gets ONE reprompt before it counts as
failed/partial. Issue counts ignore pages outside the fixed sample. The BEST
version (not the last) is exported; if every version hard-failed the document is
flagged needs_manual_template. The controller is a small explicit state machine
on purpose - it maps 1:1 onto a LangGraph StateGraph (nodes: generate / validate
/ confirm / audit; conditional edges = the stop rules) if the Dataiku notebook
later wants checkpointing/tracing, with zero logic changes.

Usage:
  python run_cli_induction.py --model claude-4.5-sonnet [--only substring] [--max-versions 5]

Outputs per document (suffix keeps them separate from the parent-model runs):
  codegen_reply_<model>_<n>.py   raw model replies (one per version; an adopted
                                 coverage extension is also kept as _confirm.txt)
  codegen_trail_<model>.json     {stop_reason, versions, best_version, score_key,
                                 cycles}; an adopted extension appears as its own
                                 version right after the version it extends
  generated_extractor_<model>.py best accepted program
  fields_codegen_<model>.csv     full-document extraction
  llm_calls_<model>.jsonl        every LLM call verbatim: {seq, kind, version, s,
                                 prompt_chars, reply_chars, prompt, reply} - the
                                 traceability + token/cost record (cost_report.py)
  timings_<model>.json           per-document profile: stage0_s, llm time by call
                                 kind, sandbox time, export_s, total_s

Run-root outputs:
  cli_induction_summary_<model>.json  one row per document (now incl. elapsed_s,
                                      llm_s, llm_calls, stage0_s)
  cli_error_events_<model>.csv        stage-attributed error/event log (run_report)
  cli_error_summary_<model>.json      event counts by stage / code / severity
'''
from __future__ import annotations
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import run_report
from codegen import AUDIT_NOT_RUN, audit_issues, audit_problem_lines, build_audit_prompt, build_code_revision_prompt, build_codegen_prompt, build_coverage_confirm_prompt, improves, is_confirm_no_fields, parse_audit_reply, run_extractor, validate_generated, version_score
from common import OUT_DIR, doc_key, list_root_pdfs
DEFAULT_DOCS = [
    '384-201-00002_Annotated_Unique_CRF_04Nov2024',
    'QSC302573_Final_AnnotatedCRFs_16Oct2024-326-201-00007_1_',
    'MAC186_X11-201-00001_eCRF_v1.10_form_tracker_v1.6_06Mar2025']

def find_agent():
    for cand in (shutil.which('agent'), os.path.join(os.environ.get('USERPROFILE', ''), '.local', 'bin', 'agent.exe'), os.path.join(os.environ.get('USERPROFILE', ''), '.local', 'bin', 'agent')):
        if cand and os.path.exists(cand):
            
            return None, cand
        raise SystemExit("cursor CLI 'agent' not found on PATH or in ~/.local/bin")


def call_cli(agent_bin = None, model = None, prompt = None, timeout_s = (1200,)):
    sandbox = tempfile.mkdtemp(prefix = 'crf_llm_sandbox_')
    
    try:
        proc = subprocess.run([
            agent_bin,
            '-p',
            '--trust',
            '--model',
            model,
            '--output-format',
            'text'], input = prompt.encode('utf-8'), capture_output = True, timeout = timeout_s, cwd = sandbox)
        shutil.rmtree(sandbox, ignore_errors = True)
    except:
        shutil.rmtree(sandbox, ignore_errors = True)

    out = proc.stdout.decode('utf-8', 'replace')
    if proc.returncode != 0:
        err = proc.stderr.decode('utf-8', 'replace')
        raise RuntimeError(f'''agent CLI exited {proc.returncode}: {err[:1500]}''')
    if not out.strip():
        raise RuntimeError(f'''agent CLI returned empty reply; stderr: {proc.stderr.decode('utf-8', 'replace')[:800]}''')
    return out


def slug(model = None):
    return re.sub('[^a-z0-9]+', '_', model.lower()).strip('_')


def doc_meta(outdir = None):
    
    try:
        f = open(os.path.join(outdir, 'clusters.json'), encoding = 'utf-8')
        
        try:
            None(None, None)
            return 
            with None:
                if not None, json.load(f):
                    
                    try:
                        
                        try:
                            return None
                        except (OSError, ValueError):
                            return 






def doc_status(outdir = None):
    return doc_meta(outdir).get('status', 'ok')


def save_reply(outdir = None, tag = None, name = None, reply = ('py',), ext = ('outdir', 'str', 'tag', 'str', 'name', 'str | int', 'reply', 'str', 'ext', 'str', 'return', 'None')):
    f = open(os.path.join(outdir, f'''codegen_reply_{tag}_{name}.{ext}'''), 'w', encoding = 'utf-8')
    f.write(reply)
    None(None, None)
    return None
    with None:
        if not None:
            pass


def jsonable_score(score = None):
    return score()


def coverage_of(verdict = None):
