# crf_codegen

Structured home for the CRF **code-generation extraction** pipeline: an LLM
writes a deterministic Python extractor for each clinical Case Report Form (CRF)
PDF from a few structurally-representative pages, then a bounded generate →
validate → coverage-confirm → grounded-audit loop revises it and the best
version replays over the whole document.

This folder supersedes the legacy `experiments/recipe_prototype/` (kept frozen).
**Run and read everything from here.**

## Layout

Grouped by role at the top level and by artifact type per run. Full map and the
filename-decoding guide are in **[`STRUCTURE.md`](STRUCTURE.md)**.

- `src/pipeline/` — the pipeline (stage-0 clustering → induction loop → replay)
- `src/evaluation/` — scoring, cost, and reporting
- `src/probes/` — one-off diagnostics and experiments
- `notebooks/` — Dataiku notebooks + `folder_code/` bundle + downloaded runs
- `data/runs/` — run outputs, one folder per run, bucketed per document
- `eval_assets/`, `reference/`, `history/`, `docs/`, `tools/`

The CRF PDF corpus is shared at the repo root `data/crf_forms/` (not duplicated).

## Quickstart

```bash
# stage 0: cluster pages, pick representatives
python src/pipeline/stage0_cluster.py

# induction loop (local CLI transport)
python src/pipeline/run_cli_induction.py --model claude-4.5-sonnet

# scoring / cost (evaluation scripts need the pipeline on PYTHONPATH)
export PYTHONPATH=src/pipeline:src/evaluation:src/probes
python src/evaluation/accuracy_audit.py score
```

`ECS_OUT_DIR` redirects outputs to an isolated run root; unset, they go to
`data/runs/corpus_cli/`. The narrative deep-dive is at the repo-level
`docs/crf_codegen_deep_dive.html`.
