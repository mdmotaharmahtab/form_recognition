# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage3plus_2026-07-22\run_report.cpython-311.pyc (Python 3.11)

"""Stage-attributed error report: WHERE in the pipeline do errors come from?

Derived post-hoc from artifacts the pipeline already writes - each document's
codegen_trail_<tag>.json plus the run's summary rows - so the loop controller
carries no reporting logic and PAST runs can be re-analyzed with this same
module. One flat event row per finding:

    doc, stage, version, severity, code, detail

  stage     stage0 | generate | revise | confirm | audit | gates | loop |
            export | mapping | driver
  severity  fatal    the document yielded nothing usable (skipped, crashed,
                     no version ever passed gates, export failed)
            blocking a parser version was rejected or a call failed; the loop
                     handled it (revision / retry) but it cost budget
            quality  review signals: audit findings, soft gate warnings,
                     partial audit replies, open issues at stop

Stage attribution comes from the trail's structure (cycle `kind`, doc status),
never from parsing prose. The finer `code` classifies known gate/warning
strings by stable prefixes/substrings with an `*_other` fallback - so a new
gate message degrades to a coarser code, never to a wrong one.

Artifacts written by write_reports (at the run root, next to the summary):
  <prefix>error_events_<tag>.csv    the flat event log (analysis-friendly)
  <prefix>error_summary_<tag>.json  counts by stage / code / severity / doc
"""
import csv
import json
import os
import time
from collections import Counter
(FATAL, BLOCKING, QUALITY) = ('fatal', 'blocking', 'quality')
KIND_STAGE = {
    'generate': 'generate',
    'revise_gates': 'revise',
    'revise_audit': 'revise',
    'confirm': 'confirm',
    'confirm_extension': 'confirm',
    'audit': 'audit' }
_PROBLEM_CODES = [
    ('The program extracted ZERO records', 'gate_zero_records'),
    ('Only ', 'gate_too_few_records'),
    ('Records carry no valid 1-based', 'gate_no_page_numbers'),
    ('Program failed to run:', 'gate_crash'),
    ('Recipe failed to execute:', 'gate_crash')]
_WARNING_CODES = [
    ('form_name empty for', 'warn_form_names_empty'),
    ('look like human labels', 'warn_labels_not_human'),
    ('distinct form_names', 'warn_form_explosion'),
    ('plausible for a document this small', 'warn_low_volume_small_doc'),
    ('look like machine codes', 'warn_oid_shape'),
    ('definition pages were detected', 'warn_broken_join')]

def classify_problem(p = None):
    for prefix, code in _PROBLEM_CODES:
        if p.startswith(prefix):
            
            return None, code
        return 'gate_other'


def classify_warning(w = None):
    for sub, code in _WARNING_CODES:
        if sub in w:
            
            return None, code
        return 'warn_other'


def events_for_doc(doc = None, trail_obj = None, row = None):
    '''All events for one document, from its trail + its summary row.

    trail_obj is the codegen_trail_<tag>.json object ({} when the document
    never reached the loop); row is its summary row ({} tolerated).'''
    pass
# WARNING: Decompyle incomplete


def mapping_events(doc = None, results = None):
    '''Aggregate unmapped/abstained OID-mapping outcomes into per-reason events
    (one row per reason with a count - thousands of per-pair rows would drown
    the report). `results` are oid_mapping.MapResult objects.'''
    pass
# WARNING: Decompyle incomplete


def collect_run_events(out_dir = None, tag = None, summary = None):
    '''Events for every document in a run summary (trails loaded from disk).'''
    events = []
    for row in summary:
        doc = row.get('doc', '')
        trail_obj = { }
        trail_path = os.path.join(out_dir, doc, f'''codegen_trail_{tag}.json''')
        if doc and os.path.isfile(trail_path):
            f = open(trail_path, encoding = 'utf-8')
            trail_obj = json.load(f)
  