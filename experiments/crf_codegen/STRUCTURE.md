# `crf_codegen` — folder & artifact map

This is the **structured, canonical home** for the CRF code-generation pipeline.
It is a reorganized copy of the older `experiments/recipe_prototype/` (which is
left frozen as legacy). From now on, run and read everything here.

The two things that used to be confusing are fixed:

1. **Top level** is grouped by role (`src/`, `notebooks/`, `data/`, …) instead
   of a flat pile of scripts + outputs.
2. **Per-document run outputs** are grouped into **type buckets** instead of ~90
   flat files in one folder. See [Per-document artifact buckets](#per-document-artifact-buckets).

---

## Top-level folders

| folder | what's inside |
|---|---|
| `src/pipeline/` | the core pipeline (mutually-importing): `common.py` (paths + page model + the `art()` bucket helper), `generic_profile.py` (stage-0 clustering), `stage0_cluster.py` (stage 0 runner), `codegen.py` (prompt building + gates + `plan_passes`), `induction.py` (shared gates + legacy recipe path), `run_cli_induction.py` (the induction loop / orchestrator), `replay.py`, `sandbox_runner.py`, `run_report.py`, `oid_mapping.py`, plus legacy runners (`run_induction.py`, `run_reference.py`, `run_review.py`, `subagent_bridge.py`). |
| `src/evaluation/` | scoring & reporting: `accuracy_audit.py` (sample/score vs ground truth), `accuracy_report.py`, `eval_form_field.py`, `evaluate.py`, `cost_report.py`, `build_backpocket_eval_report.py`. |
| `src/probes/` | one-off diagnostics, sweeps and clustering/stop-policy experiments (not part of the shipped path). |
| `notebooks/` | the Dataiku notebooks (`CRF_codegen_induction.ipynb`, `LLM_reasoning_probe.ipynb`), `build_dataiku_notebook.py`, `folder_code/` (the module bundle uploaded to Dataiku), and the downloaded Dataiku run outputs (`out_dataiku_sonnet_4_5/`, `out_dataiku_gpt_5_2/`). |
| `docs/` | supporting docs and end-to-end logs. The full narrative deep-dive lives at the repo-level `docs/crf_codegen_deep_dive.html`. |
| `reference/` | hand-authored reference recipes (engine smoke-test baselines). |
| `eval_assets/` | ground-truth `truth/`, annotation `packets/`, `manifest.json`, and consolidated `scored*.json` score snapshots. |
| `history/` | project history: recovered `code_versions/`, per-stage `results/`, and the timeline `README.md`. |
| `data/runs/` | all run outputs (see below). |
| `tools/` | maintenance utilities: `migrate_to_buckets.py` (the one-time flat→bucket migration), `smoke_refactor.py` (writer/reader smoke test). |

**Inputs are shared, not duplicated.** The CRF PDF corpus stays at the repo root
`data/crf_forms/`; `common.CRF_DIR` resolves to it by walking up the tree.

---

## `data/runs/` — run outputs

Each subdirectory is one *run root* holding per-document folders plus run-root
summary files:

| run root | what it is |
|---|---|
| `corpus_cli/` | the default local CLI run over the whole corpus (`common.OUT_DIR` points here when `ECS_OUT_DIR` is unset). |
| `probe_clusters_2021/` | the cluster-sampling ablation runs (`a_baseline`, `b_more_samples`, `c_narrow_split`, `d_*`, and per-model variants). |
| `dataiku_fail_384v1/` | approach-D rerun of the document Sonnet-Dataiku failed on. |
| `snapshots/` | **frozen historical** output snapshots. These keep their original flat layout on purpose and are NOT re-bucketed. |

Run-root files (not per-document): `cli_induction_summary_<tag>.json`,
`cli_error_events_<tag>.csv`, `cli_error_summary_<tag>.json`, and any
`eval_report_*.md` / `*.xlsx` reports.

---

## Per-document artifact buckets

Inside every `<run_root>/<doc_key>/`, artifacts are grouped by **type**. Routing
is deterministic from the filename (`common.artifact_bucket`), so writers and
readers stay in sync via `common.art(outdir, name)`.

```
<doc_key>/
  stage0/       clusters.json, rep_p<N>.txt/.png, title_p<N>.txt/.png
  prompts/      codegen_prompt.txt, codegen_prompt_pass<N>.txt,
                induction_prompt.txt, coverage_confirm_prompt.txt
  extractors/   generated_extractor_<tag>[_pass<N>].py   (final programs)
  fields/       fields_codegen_<tag>[_pass<N>].csv       (extraction output)
  trails/       codegen_trail_<tag>[_pass<N>].json       (per-version decision log)
  llm_calls/    llm_calls_<tag>[_pass<N>].jsonl          (verbatim prompt/reply)
  timings/      timings_<tag>[_pass<N>].json             (per-doc time profile)
  replies/      codegen_reply_<tag>_<n>.py, ..._confirm.txt   (raw model replies)
  (root)        oid_mapping_<tag>.csv and any file not matching a bucket
```

### Decoding a filename

- **`<tag>`** = the model/run tag, e.g. `claude_4_5_sonnet`, `gpt_5_2`, or a
  composite `…__audit__…__<digest>` for hybrid generation/audit runs.
- **`_pass<N>`** = a multi-pass *specialist* pass (documents whose layout
  families exceed one prompt's budget). Files **without** `_pass<N>` under the
  plain tag are the **merged, document-level** outputs.
- **`codegen_reply_<tag>_<n>`** = parser version *n*; `_confirm` = the
  coverage-confirmation reply.

So `extractors/generated_extractor_claude_4_5_sonnet.py` is Sonnet's final
merged program; `trails/codegen_trail_gpt_5_2_pass2.json` is GPT's decision log
for specialist pass 2.

---

## Running from here

The core loop runs standalone (its own dir is on `sys.path`):

```bash
python src/pipeline/stage0_cluster.py
python src/pipeline/run_cli_induction.py --model claude-4.5-sonnet [--only <substr>]
```

Evaluation/probe scripts import the pipeline modules, so add them to
`PYTHONPATH`:

```bash
export PYTHONPATH=src/pipeline:src/evaluation:src/probes
python src/evaluation/accuracy_audit.py score
python src/evaluation/cost_report.py --tag claude_4_5_sonnet --run-dir data/runs/corpus_cli
```

Override the output location with `ECS_OUT_DIR` (isolated runs / ablations);
the Dataiku notebook additionally sets `ECS_BASE`.
