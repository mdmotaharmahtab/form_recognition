# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage1_v1_2026-07-20\evaluate.cpython-311.pyc (Python 3.11)

"""Evaluate induced-recipe extractions.

1. Rave document vs production ground truth (data/outputs/.../digitized.csv):
   recall/precision of (form, oid) and oid-only sets.
2. Every document vs the ecs_index rule library: how many extracted OIDs appear
   in the library's field_oids (the signal Phase-2 matching runs on).
"""
import ast
import csv
import json
import os
import re
import sys
from common import BASE, OUT_DIR
GT = os.path.join(BASE, 'data', 'outputs', 'outputs_from_384_201_00002_annotated_unique_crf', 'digitized.csv')
INDEX = os.path.join(BASE, 'data', 'index', 'ecs_index.csv')
RAVE_KEY = '384-201-00002_Annotated_Unique_CRF_04Nov2024'

def norm(s = None):
