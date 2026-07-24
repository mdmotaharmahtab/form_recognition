# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage2_v2_2026-07-21\induction.cpython-311.pyc (Python 3.11)

'''Stage 1 shared scoring/gates + the LEGACY recipe-induction path.

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
'''
from __future__ import annotations
import json
import os
import re
from replay import ENGINES, ReplayResult, replay
PROMPT_TEMPLATE = 'You are configuring a deterministic PDF extraction engine for a clinical Case Report Form (CRF) document. You will see a small sample of REPRESENTATIVE PAGES (one or two per page-layout cluster) from a document that is {n_pages} pages long. The whole document is repetitive: what you see is representative of everything.\n\nEach page is given as structured text lines with geometry:\n    x=<left> y=<top> sz=<font-size> <color> <B if bold> | <text>\n\n# Your task\n\nProduce a JSON "recipe" that tells the engine how to extract, for EVERY field on EVERY page of the document:\n  - form_name   : the name of the CRF form/section the field belongs to\n  - field_name  : the human-readable field label/question\n  - field_oid   : the machine identifier (OID / SAS name / export name / variable\n                  code) if the document prints one; null if the document is not\n                  annotated with machine codes\n\n# Engines you can parameterise (pick exactly one)\n\n1. "adjacent_annotation" - machine codes are printed on their own annotation lines\n   (often bracketed, often colored) directly next to/under the field label, in the\n   same column. Params: column_x_max, oid_regex (capture group 1 = code),\n   alt_regex/alt_is_primary (a second code on nearby lines), oid_color_non_black,\n   annotation_group_dy, label_max_dy, label_noise (regexes for lines that are\n   never labels).\n2. "anchored_blocks" - each field starts at a repeated anchor row (e.g. a bold\n   \'Prefix: Activity #1\' line with a number in a far-right column); everything\n   until the next anchor belongs to that field. Params: activity_regex (group 1 =\n   form, group 2 = field), activity_x [min,max], line_number_x_min, oid_regex.\n3. "numbered_join" - two page types per form: content pages print each label with\n   a join number, definition pages map the same numbers to codes in a column\n   under a header. Params: definition_page_all (regexes that all appear on\n   definition pages), oid_header (text of the column header the codes sit under),\n   row_number_x_max (join keys on definition pages must start left of this),\n   data_number_regex (group 1 = join key; same regex applies on BOTH page types),\n   data_number_x_min, data_label_x_max, label_noise,\n   number_embedded_in_label (true when the join key is printed on/next to the\n   label line itself, e.g. \'Consent Date  [2]\', rather than in a separate far\n   column; the engine then searches the regex inside lines right of\n   data_number_x_min and takes the remaining text on that row as the label),\n   definition_form_from_carry (true when definition pages do NOT print the form\n   name; they are then attributed to the most recent content-page form).\n   form_name.strategy must be "regex" for this engine (carry_forward supported).\n4. "column_table" - definition tables with an explicit header row; label and code\n   are cells of configurable columns. Params: definition_page_regex, row_key_regex,\n   name_header, oid_header, type_header.\n5. "line_pattern" - fallback: a code regex over lines, label = nearest previous\n   line matching label_regex within label_window_lines. Params: code_regex,\n   code_search (true = search inside line), label_regex, label_window_lines,\n   label_noise.\n\n# form_name strategies\n\n- {{"strategy":"regex","regex":"^Form:\\\\s*(.+)$"}} - a header line matches a regex (group 1 = name)\n- {{"strategy":"colored_font","min_size":14,"carry_forward":true,"noise":[...]}} - the form title is the big colored heading; carry_forward repeats the last seen title on continuation pages\n- {{"strategy":"font","min_size":14,"carry_forward":true,"noise":[...]}} - same but title is not colored\n- for engine anchored_blocks the form name comes from activity_regex group 1 automatically\n\n# Output format (JSON only, no prose)\n\n{{\n  "format_id": "<short slug you invent>",\n  "reasoning": "<2-4 sentences: what layout you saw and why you chose the engine>",\n  "detect": {{"all": ["<2-3 regexes that identify this layout>"]}},\n  "skip_page_if": ["<optional regexes: pages to skip entirely (title/TOC/approval)>"],\n  "form_name": {{...}},\n  "fields": {{"engine": "<one of the 5>", ...params...}}\n}}\n\n# Rules\n\n- Regexes are Python re syntax inside JSON strings (escape backslashes).\n- Codes are machine identifiers like AESTDAT / QVAL_GENDOTH - short, uppercase,\n  underscores/digits allowed. Human text, dates and option values are NOT codes.\n- Prefer the most specific engine that fits; use line_pattern only if nothing fits.\n- If the document prints NO machine codes at all, still extract form_name +\n  field_name (choose the engine that best yields labels; oid_regex may then match\n  nothing) and say so in "reasoning".\n- Numbers like x/y/size in the dumps are points; use them to set column bounds.\n\n# Representative pages\n\n{pages}\n'
REVISION_TEMPLATE = 'Your previous recipe was executed on the SAME representative pages. It did not pass the quality gates.\n\nPrevious recipe:\n{recipe}\n\nExecution metrics:\n{metrics}\n\nSample of extracted records (form_name | field_name | field_oid):\n{sample}\n\nProblems to fix (in priority order):\n{problems}\n\nEmit a corrected recipe now. Same output format: JSON only, no prose. You may switch engine entirely.\n'

def load_rep_pages(outdir = None, max_chars_per_page = None):
    '''Concatenate the stage-0 representative page dumps for the prompt.'''
    pass
# WARNING: Decompyle incomplete


def parse_recipe(raw = None):
    '''First complete JSON object in an LLM reply. Balanced parse (raw_decode) -
    a greedy `\\{.*\\}` regex would span from the first to the LAST brace and be
    corrupted by prose containing braces around the payload.'''
    dec = json.JSONDecoder()
    idx = raw.find('{')
# WARNING: Decompyle incomplete

CODE_SHAPE = re.compile('^[A-Z][A-Z0-9_]{1,39}$')

def score(result = None, engine = None):
    recs = result.records
    n = len(recs)
    m = {
        'engine': None(sum * (lambda .0: pass# WARNING: Decompyle incomplete
)(recs()) / n) if n else 0,
        'records': None,
        'pages_total': round,
        'pages_with_fields': 100,
        'definition_pages_seen': None,
        'forms_nonempty_pct': sum * (lambda .0: pass# WARNING: Decompyle incomplete
)(recs()),
        'labels_look_human_pct': max(1 / None(sum, (lambda .0: pass# WARNING: Decompyle incomplete
)(recs()))),
        'oids_present_pct': None,
        'oids_look_like_codes_pct': len,
        'distinct_forms': (lambda .0: pass# WARNING: Decompyle incomplete
)(recs()) }
    m['fields_per_form'] = round(n / max(1, m['distinct_forms']), 1)
    m['forms_per_100_pages'] = round(100 * m['distinct_forms'] / max(1, result.pages_total), 1)
    return m


def gate_problems(m = None):
    '''Contract blockers only: the program crashed upstream, or its output is so
    small it is effectively not extracting. Nothing here encodes corpus statistics.

    The <5-records floor applies only to documents of >=20 pages: on a big book
    it means the program is broken, but a 1-2 page CRF can legitimately carry
    3 fields total, and a hard gate would flag every version of a correct
    program as needs_manual_template. Tiny-document low volume is a warning
    (gate_warnings) so the audit still scrutinizes it.'''
    problems = []
    if m['records'] == 0:
        problems.append('The program extracted ZERO records from the document.')
        return problems
    if None['records'] < 5 and m['pages_total'] >= 20:
        problems.append(f'''Only {m['records']} records from a {m['pages_total']}-page document - the program is effectively not extracting.''')
    if not m['records'] and m['pages_with_fields']:
        problems.append('Records carry no valid 1-based `page` numbers - the `page` field of every returned record must be the page the field appears on.')
    return problems


def gate_warnings(m = None):
    '''Quality signals fed back to the revision loop. A document may legitimately
    violate these (unlabeled forms, very short labels, dense form books), so after
    the revision budget is exhausted the best warning-only attempt is still
    accepted - final quality judgment belongs to the grounded audit.'''
    warnings = []
    if  < 0, m['records'] or 0, m['records'] < 5:
        pass
    
    if m['pages_total'] < 20:
        warnings.append(f'''Only {m['records']} records from this {m['pages_total']}-page document - plausible for a document this small, but make sure no fields were missed.''')
    if m['forms_nonempty_pct'] < 70:
        warnings.append(f'''form_name empty for {100 - m['forms_nonempty_pct']}% of records - if the document does print form/section names, fix the form_name strategy (consider carrying the last seen title forward).''')
    if m['labels_look_human_pct'] < 60:
        warnings.append(f'''Only {m['labels_look_human_pct']}% of field_name values look like human labels (they look like codes/dates/junk) - fix label selection.''')
    if m['oids_present_pct'] > 0 and m['oids_look_like_codes_pct'] < 80:
        warnings.append(f'''Extracted field_oid values often don\'t look like machine codes ({m['oids_look_like_codes_pct']}% ok) - tighten oid_regex.''')
    if m['engine'] == 'numbered_join' and m['definition_pages_seen'] > 0 and m['oids_present_pct'] < 10:
        warnings.append(f'''{m['definition_pages_seen']} definition pages were detected but codes were joined to only {m['oids_present_pct']}% of labels. The join is broken: check data_number_regex (group 1 must capture the SAME key on both page types), row_number_x_max, oid_header, and consider number_embedded_in_label:true (key printed on the label line) or definition_form_from_carry:true (definition pages don\'t print the form name; attribute them to the most recent content-page form).''')
    if m['distinct_forms'] > max(10, m['records'] // 2):
        warnings.append(f'''{m['distinct_forms']} distinct form_names for {m['records']} records - check whether form detection is picking up field labels or body text as form names; if so, make the form_name pattern stricter (font size / color / position) or carry the last seen title forward. If the document genuinely has this many forms, keep it as is.''')
    return warnings


def validate_recipe(pdf_path = None, raw_reply = None):
