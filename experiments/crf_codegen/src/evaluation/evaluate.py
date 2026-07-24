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

# pipeline modules (common.py etc.) live in the sibling src/pipeline/ package
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from common import BASE, OUT_DIR  # noqa: E402

GT = os.path.join(BASE, "data", "outputs", "outputs_from_384_201_00002_annotated_unique_crf", "digitized.csv")
INDEX = os.path.join(BASE, "data", "index", "ecs_index.csv")
RAVE_KEY = "384-201-00002_Annotated_Unique_CRF_04Nov2024"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def load_fields(key: str) -> list[dict]:
    path = os.path.join(OUT_DIR, key, "fields_induced.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def eval_rave() -> dict:
    with open(GT, encoding="utf-8") as f:
        gt = list(csv.DictReader(f))
    got = load_fields(RAVE_KEY)

    gt_oid = {norm(r["field_oid"]) for r in gt if r["field_oid"]}
    got_oid = {norm(r["field_oid"]) for r in got if r["field_oid"]}
    gt_pairs = {(norm(r["form_name"]), norm(r["field_oid"])) for r in gt if r["field_oid"]}
    got_pairs = {(norm(r["form_name"]), norm(r["field_oid"])) for r in got if r["field_oid"]}

    inter_oid = gt_oid & got_oid
    inter_pairs = gt_pairs & got_pairs
    res = {
        "gt_rows": len(gt), "induced_rows": len(got),
        "gt_distinct_oids": len(gt_oid), "induced_distinct_oids": len(got_oid),
        "oid_recall_pct": round(100 * len(inter_oid) / max(1, len(gt_oid))),
        "oid_precision_pct": round(100 * len(inter_oid) / max(1, len(got_oid))),
        "form_oid_pair_recall_pct": round(100 * len(inter_pairs) / max(1, len(gt_pairs))),
        "missed_oids_sample": sorted(gt_oid - got_oid)[:15],
        "extra_oids_sample": sorted(got_oid - gt_oid)[:15],
    }
    return res


def load_index_oids() -> set[str]:
    oids = set()
    with open(INDEX, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = row.get("field_oids") or ""
            try:
                vals = ast.literal_eval(raw) if raw.startswith("[") else [raw]
            except (ValueError, SyntaxError):
                vals = [raw]
            for v in vals:
                if v:
                    oids.add(norm(str(v)))
    return oids


def eval_index_coverage() -> list[dict]:
    lib = load_index_oids()
    out = []
    for key in sorted(os.listdir(OUT_DIR)):
        rows = load_fields(key)
        if not rows:
            continue
        oids = {norm(r["field_oid"]) for r in rows if r["field_oid"]}
        hit = sum(1 for o in oids if o in lib)
        out.append({"doc": key[:52], "fields": len(rows), "distinct_oids": len(oids),
                    "oids_in_ecs_index_pct": round(100 * hit / max(1, len(oids)))})
    return out


if __name__ == "__main__":
    report = {"rave_vs_ground_truth": eval_rave(), "ecs_index_oid_coverage": eval_index_coverage()}
    with open(os.path.join(OUT_DIR, "evaluation.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
