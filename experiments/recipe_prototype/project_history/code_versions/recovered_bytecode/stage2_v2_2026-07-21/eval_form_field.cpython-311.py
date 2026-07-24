# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage2_v2_2026-07-21\eval_form_field.cpython-311.pyc (Python 3.11)

'''Evaluate the form+field pipeline (codegen scope) end to end.

1. Extraction quality (Rave doc only - the one with production ground truth):
   fuzzy-match extracted (form_name, field_name) pairs against digitized.csv.
2. Downstream OID resolution by NAME MAPPING (all finalized docs):
   map each extracted (form, field) to a library OID via ecs_index_data
   (form_field_value -> variable_name), lexical fuzzy matching locally
   (production would add the stored field embeddings on top).
   On the Rave doc, mapped OIDs are checked against the printed truth.
'''
import csv
import json
import os
import re
import fitz
from rapidfuzz import fuzz
from common import BASE, OUT_DIR
GT = os.path.join(BASE, 'data', 'outputs', 'outputs_from_384_201_00002_annotated_unique_crf', 'digitized.csv')
INDEX_DATA = os.path.join(BASE, 'data', 'index', 'ecs_index_data.csv')
RAVE_PDF = os.path.join(BASE, 'data', 'crf_forms', '384-201-00002_Annotated Unique CRF_04Nov2024.pdf')
RAVE_KEY = '384-201-00002_Annotated_Unique_CRF_04Nov2024'
FIELD_T = 85
FORM_T = 75

def norm(s = None):
