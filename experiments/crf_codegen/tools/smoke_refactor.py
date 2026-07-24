"""Smoke test for the bucketed-artifact refactor.

A) writers + stage-0 readers: run stage 0 for one PDF into a temp run root and
   confirm artifacts land in stage0/, then build a codegen prompt (which reads
   rep dumps back out of stage0/).
B) fields reader + scoring: read a MIGRATED extractor + its fields export from
   the real corpus_cli run and score against ground truth.

Run with the repo .venv so fitz/rapidfuzz are importable.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CC = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(CC, "src", "pipeline"))
sys.path.insert(0, os.path.join(CC, "src", "evaluation"))

TMP = tempfile.mkdtemp(prefix="crf_smoke_")
os.environ["ECS_OUT_DIR"] = TMP  # isolate stage-0 writes from corpus_cli

import common  # noqa: E402
import stage0_cluster  # noqa: E402
import codegen  # noqa: E402

DOC = "annotatedCRF_33120100246-_v1.0_-17Aug2021"

# ---- 0. art routing sanity -------------------------------------------------
checks = {
    "clusters.json": "stage0", "rep_p3.txt": "stage0", "title_p5.png": "stage0",
    "codegen_prompt.txt": "prompts", "codegen_prompt_pass2.txt": "prompts",
    "generated_extractor_gpt_5_2.py": "extractors",
    "fields_codegen_claude_4_5_sonnet_pass1.csv": "fields",
    "codegen_trail_gpt_5_2.json": "trails", "llm_calls_gpt_5_2.jsonl": "llm_calls",
    "timings_gpt_5_2.json": "timings", "codegen_reply_gpt_5_2_confirm.txt": "replies",
    "cli_induction_summary_gpt_5_2.json": "",
}
for name, want in checks.items():
    got = common.artifact_bucket(name)
    assert got == want, f"routing {name!r}: got {got!r} want {want!r}"
print("[0] art routing: OK")

# ---- A. writer + stage-0 reader --------------------------------------------
pdf = next(p for p in common.list_root_pdfs() if common.doc_key(p) == DOC)
meta = stage0_cluster.run(pdf)
out = os.path.join(TMP, DOC)
assert os.path.isfile(os.path.join(out, "stage0", "clusters.json")), "no stage0/clusters.json"
reps = [f for f in os.listdir(os.path.join(out, "stage0")) if f.startswith("rep_p")]
assert reps, "no rep dumps in stage0/"
assert not [f for f in os.listdir(out) if os.path.isfile(os.path.join(out, f))], \
    "stray files at doc root"
print(f"[A] stage0 wrote {meta['n_clusters']} clusters, {len(reps)} rep files into stage0/: OK")

prompt = codegen.build_codegen_prompt(pdf, out)
assert "family" in prompt and len(prompt) > 500, "prompt build (rep reader) failed"
print(f"[A] build_codegen_prompt read reps back ({len(prompt)} chars): OK")

# ---- B. fields reader + scoring on the migrated corpus run -----------------
from accuracy_audit import load_export, score_doc  # noqa: E402
import json  # noqa: E402

run = {"root": os.path.join(CC, "data", "runs", "corpus_cli"),
       "tag": "claude_4_5_sonnet", "dir_prefix": ""}
export = load_export(run, DOC)
assert export, "load_export returned nothing (fields bucket reader broken)"
with open(os.path.join(CC, "eval_assets", "truth", f"{DOC}.json"), encoding="utf-8") as f:
    truth = json.load(f)
s = score_doc(truth, export)
print(f"[B] load_export read {len(export)} rows from fields/; "
      f"score tp/fp/miss = {s['tp']}/{s['fp']}/{s['missed']}: OK")

print("\nSMOKE PASS")
