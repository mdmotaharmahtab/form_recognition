# `data/runs/` — run outputs

Each subdirectory is one **run root**: it holds a per-document folder for every
CRF plus run-root summary files. Per-document artifacts are grouped into type
**buckets** (`stage0/`, `prompts/`, `extractors/`, `fields/`, `trails/`,
`llm_calls/`, `timings/`, `replies/`) — the full scheme and filename decoder are
in [`../../STRUCTURE.md`](../../STRUCTURE.md).

For the *historical* timeline (which code produced which results) see
[`../../history/README.md`](../../history/README.md).

### What is tracked in git

The interpretable results are versioned: `clusters.json`, `prompts/`,
`extractors/`, `fields/`, `trails/`, `timings/`, `replies/`, and the run-root
summaries. Three heavy, re-derivable payloads are **git-ignored** (they still
exist locally):

- `**/*.png` — rendered representative/title page images (~78 MB);
- `**/llm_calls/` — verbatim prompt+reply call logs (~43 MB); regenerate a run
  to reproduce, or read the `trails/` decision log for the distilled version;
- `snapshots/` — the frozen historical corpus backups (~41 MB); their curated
  scores live in [`../../history/`](../../history/).

## Run roots

| Entry | Meaning |
|---|---|
| `corpus_cli/` | The default / current CLI outputs for the full 11-document corpus. `common.OUT_DIR` points here when `ECS_OUT_DIR` is unset. |
| `probe_clusters_2021/` | Cluster-sampling ablation runs on the 2021 book (`a_baseline`, `b_more_samples`, `c_narrow_split`, `d_*`, and per-model `*_sonnet` / `*_gpt` cells). Each cell is a complete isolated `OUT_DIR`, driven by the `ECS_*` knobs. |
| `dataiku_fail_384v1/` | Approach-D rerun of the document Sonnet-Dataiku failed on. |
| `snapshots/` | **Frozen historical** corpus snapshots, one per milestone (see below). Kept in their original flat layout on purpose — NOT re-bucketed. |

### `snapshots/` — historical milestones

| Subdir | Stage |
|---|---|
| `1_early_v1_2026-07-20` | early CLI bring-up |
| `2_early_v2_2026-07-21` | early CLI v2 |
| `3_loop1_pre_loopfix_2026-07-22` | loop-1 baseline |
| `4_pre_loop2_baseline_2026-07-22` | pre-loop-2 baseline |
| `4b_sanity_guidance_2026-07-22` | guidance-regression sanity |
| `5_loop2_eval_2026-07-23` | loop-2 full eval (+run logs) |

## Run-root files (per model tag)

`<tag>` is the model slug: `claude_4_5_sonnet`, `gpt_5_2`, or a hybrid tag like
`claude_4_5_sonnet__audit__gpt_5_2__<hash>`.

| File | Meaning |
|---|---|
| `cli_induction_summary_<tag>.json` | One row per document: status, versions, fields, forms, timings. The run's headline. |
| `cost_report_<tag>.csv` | Token/cost breakdown per document. |
| `cli_error_events_<tag>.csv` / `cli_error_summary_<tag>.json` | Stage-attributed errors for the run. |
| `accuracy_audit_<tag>.xlsx` | Per-field scoring workbook. |
| `eval_report_*.md` | Narrative evaluation reports. |

Ground truth and consolidated scores live in [`../../eval_assets/`](../../eval_assets/).
