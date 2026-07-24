# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage2_v2_2026-07-21\replay.cpython-311.pyc (Python 3.11)

'''LEGACY COMPARISON PATH - not the production flow.

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
  anchored_blocks     - repeated anchor rows (e.g. bold \'Prefix: Activity #n\' with a
                        number in a far column) delimit blocks; codes found per block
  numbered_join       - two page types joined by a printed number: content pages
                        (label + number) and definition pages (number + code column)
  column_table        - definition tables with a header row; label and code are
                        cells in configurable columns
  line_pattern        - generic fallback: regex roles over sequential text lines
'''
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field
import fitz
from common import Line, build_page_lines
FieldRec = <NODE:12>()
ReplayResult = <NODE:12>()

def _compile(rxs = None):
