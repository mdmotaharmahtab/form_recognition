# Project history — code versions, runs, and results

This folder is the single place that answers three questions that used to be
impossible to answer:

1. **What did the code look like at each stage?** → `code_versions/`
2. **What results did that code produce?** → `results/`
3. **What changed between stages, and did it help or hurt?** → the timeline below.

Everything before this folder was tracked only by ad-hoc full-folder copies of
`data/outputs/` and a couple of narrative reports. There was **no git history**
and the CLI overwrote per-model artifacts on every run. This folder reconstructs
the timeline from what was actually saved, and from this point on the repo is
under **git** (see "Going forward").

---

## What is recoverable, honestly

| Asset | Availability |
|---|---|
| Pipeline **source** at each stage | Partial. Three Dataiku `folder_code` bundles were saved on 07-22 (`ECSGENERATION/backup/folder_code*.zip`) plus the current live `scripts/`. The 07-20/07-21 early CLI source and the intermediate 07-23 loop-2/loop-3 edits were **not** separately snapshotted. The early stages have since been **recovered from surviving bytecode** — see `code_versions/recovered_bytecode/` (decompiled `.py` + faithful disassembly/constants; prompts verbatim). Only the outputs survive for the rest. |
| **Generated extractors** per run | Yes — inside each `data/outputs/out*` backup, as `generated_extractor_*.py` per document. |
| **Prompts** used per run | Yes — `codegen_prompt*.txt`, `induction_prompt.txt` inside each backup. |
| **Version trails** (per-attempt metrics) | Yes — `codegen_trail_*.json` inside each backup. |
| **Scored results** per stage | Yes — `accuracy_audit/scored*.json` snapshots, copied into each `results/rN_*`. |
| **Narrative of each change + measured effect** | Yes — the two eval reports, reproduced in `results/r6_backpocket_2026-07-23/` and summarized below. |

> The heavy per-document artifacts (rep page PNGs, per-version replies, per-doc
> CSVs) are **not** duplicated here; they remain in their original
> `data/outputs/out*` backup and are linked from the table below.

---

## Timeline (oldest → newest)

Metrics are page-sampled precision / page-recall / doc-recall, plus form
accuracy and the full-document Rave precision/recall, taken from the eval
reports (`results/r6_backpocket_2026-07-23/eval_report_loop2_20260723.md` and
`eval_report_backpocket_20260723.md`), which are the authoritative source.

| # | Stage | Date | Code | Results folder | Original backup | Headline (Sonnet unless noted) |
|---|---|---|---|---|---|---|
| 1 | Early CLI bring-up v1 | 07-20 22:47 | `code_versions/recovered_bytecode/stage1_v1_2026-07-20` *(from bytecode)* | `results/r1_v1_baseline_2026-07-20` | `data/outputs/snapshots/1_early_v1_2026-07-20` | superseded; source recovered from `.pyc` |
| 2 | Early CLI v2 | 07-21 08:06 | `code_versions/recovered_bytecode/stage2_v2_2026-07-21` *(from bytecode)* | `results/r2_v2_2026-07-21` | `data/outputs/snapshots/2_early_v2_2026-07-21` | superseded; source recovered from `.pyc` |
| 3 | Loop-1 baseline (pre-loopfix) | 07-22 15:20 | `code_versions/c1_2026-07-22_1520` | `results/r3_pre_loopfix_2026-07-22` | `data/outputs/snapshots/3_loop1_pre_loopfix_2026-07-22` | 78% / 76% / — · forms 48/49 · Rave 67% / 89% |
| — | Dataiku code iteration | 07-22 16:23 | `code_versions/c2_2026-07-22_1623` | *(no separate run)* | — | adds `run_report.py`, oid/stage0 tweaks |
| 4 | Pre-loop-2 baseline | 07-22 17:27–18:46 | `code_versions/c3_2026-07-22_1727` | `results/r4_pre_loop2_2026-07-22` | `data/outputs/snapshots/4_pre_loop2_baseline_2026-07-22` | baseline for loop-2 comparison |
| 4b | Sanity (guidance regression) | 07-22 22:08 | *(live)* | `results/r4b_sanity_guidance_2026-07-22` | `data/outputs/snapshots/4b_sanity_guidance_2026-07-22` | diagnostic only |
| 5 | Loop-2 eval (11 docs × 2 models) | 07-23 09:05 | *(live, evolving)* | `results/r5_loop2_eval_2026-07-23` | `data/outputs/snapshots/5_loop2_eval_2026-07-23` | Sonnet 78% / 63% / 91% · forms 43/45 · Rave 87% / 83% · **GPT 74% / 85% / 96% · forms 18/51 · Rave 97% / 84%** |
| 6 | Backpocket (current) | 07-23 | `code_versions/c4_current_2026-07-23` **= live `scripts/`** | `results/r6_backpocket_2026-07-23` | `data/outputs/out` (live) | Sonnet 73.2% / 73.6% / 93.9% · F1 73.4% · forms 50/51 · Rave 85.4% / 84.7% · **GPT 80.3% / 82.7% / 96.5% · F1 81.5% · forms 44/57 · Rave 47.5% / 84.5%** |

`code_versions/DIFFS.txt` is the full unified diff between consecutive code
snapshots; `code_versions/DIFFS_summary.txt` shows how each core file grew. The
big `c3 → c4` jump (e.g. `codegen.py` 611 → 1274 lines, `run_cli_induction.py`
605 → 1010) is all the 07-23 loop-2/loop-3/backpocket work described below.

---

## What each change did (and whether it worked)

Synthesized from the eval reports. Each item is a concrete change and its
measured effect.

### Loop-1 → Loop-2 (multi-pass specialists, audit rotation, junk carve-out)
- **Multi-pass "specialist" induction, audit rotation/promotion, sparse-scope
  softening, cluster safety net, radius-driven representatives.**
  - Worked: reliability (22/22 doc runs exported), GPT recall jumped to 85%
    page / 96% doc, Rave precision cleaned up (Sonnet 67%→87%, GPT 97%).
  - Broke: the `SPECIALIST_NOTE` ownership framing made Sonnet write narrow
    parsers — MAC186 collapsed to 5% coverage, corpus page recall 76%→63%.
    GPT started naming forms by per-field annotations (forms 18/51).

### Loop-2 fix 3 — form-name contract + structural gate
- Pinned `form_name` by definition (grouping title, not per-field text), added a
  two-tier explosion gate and a `wrong_form` audit channel.
  - Effect: blocked the worst GPT explosions mid-loop, but GPT's best version
    still sat just above the gate → **necessary but not sufficient** for GPT.

### Loop-2 fixes 1,2,4 — specialist framing, rare splitting, enumeration guard
- Pass-1 is now a byte-identical generalist; tail passes get a harness-descriptive
  note. Splitting made rare (9/11 → 3/11 docs). Enumeration-row audit rule added.
  - Worked: **the multi-pass collapse is fixed** — Sonnet corpus recall recovered
    to 75.5% (from 62.7%), 04_Jul generalist reached 88% coverage, 16JAN beat its
    baseline. GPT form titles on 326 still 0/10.

### Junk-coverage carve-out rebuilt on evidence
- Replaced inference-based "junk cleanup" forgiveness with evidence-based
  `forgivable_junk_pages` (a lost page is forgiven only if **every** record on it
  matches audited-false values or doc-wide furniture).
  - Worked: MAC186 no longer sheds real coverage for a 1-issue audit gain; Sonnet
    corpus reached 78% / 80%, above the pre-loop-2 baseline on both axes.

### Family-labeled prompt / handler architecture
- Representatives labeled by layout family; model asked for per-family handlers;
  AST warning for ≥10 literal text filters.
  - Mixed: Sonnet MAC186 recall improved substantially (page recall 62.4%, 859
    pages covered); **GPT regressed hard** on 326 (field recall collapsed). Not
    model-neutral → later made optional.

### Independent title-context channel
- Corpus-free channel: top-region signatures, chrome removal, dedicated
  `TITLE/FORM CONTEXT ONLY` prompt section, two-page audit lookback.
  - Worked on target: GPT 326 form accuracy **0/10 → 10/10**; Sonnet preserved
    10/10. This addressed the "sample pages may not contain the title" gap.

### Backpocket full rerun + targeted hybrid (current, c4)
- Persistence signal, model-neutral family handling, literal-blocklist hard
  rejection at 30 (warn at 10, incl. named collections), size-scaled version
  budget, purge-before-run, collision-resistant hybrid tags.
  - GPT is now the strongest sampled extractor (80.3% / 82.7% / F1 81.5%, forms
    44/57). Sonnet form attribution near-perfect (50/51).
  - **Regression:** GPT full-document Rave precision **97.5% → 47.5%** (distinct
    pairs 792 → 1,628, matched flat) — proportional audit sampling missed
    unsampled over-extraction. Top-priority follow-up.
  - One Sonnet doc (2021 331) is `needs_manual_template` (a specialist pass
    failed); its scored row is fresh but partial.

### Cluster-sampling ablation → approach D (current best for Sonnet)
- **Question tested:** should each generalist get *fewer* clusters but *more*
  samples per cluster, offloading the rest to specialist passes that also see
  several samples each? Added env-gated knobs (`ECS_REPS_PER_CLUSTER`,
  `ECS_SPECIALIST_REPS_PER_CLUSTER`, `ECS_MAX_REPS`, `ECS_REP_BUDGET`,
  `ECS_MIN_TAIL_*`, `ECS_MAX_PASSES`) and ran four configs (a=baseline,
  b=more_samples, c=narrow_split, **d=few clusters + rich per-cluster samples,
  offloaded**) for both models on the 2021 book (32-field truth packet).
- **Key gap found and fixed:** `ECS_REPS_PER_CLUSTER` only enriched the
  generalist's clusters — every *offloaded* cluster was hardwired to a single
  sample page. The new `ECS_SPECIALIST_REPS_PER_CLUSTER` knob (default 1 =
  unchanged) lets specialist passes see several samples per cluster, which is
  what makes approach D expressible at all.
- **Scored F1 on the 2021 doc:**

  | config | Sonnet 4.5 | GPT 5.2 |
  |---|---|---|
  | a_baseline | 50.0% | 84.8% |
  | b_more_samples | 45.3% | 86.2% |
  | c_narrow_split | 83.6% | 73.8% |
  | **d_your_design** | **89.2%** | *(pending)* |

  - **Approach D is the best Sonnet result on this doc ever** (prec 87.9% /
    recall 90.6% / F1 89.2%, 29/4/3) — beating every prior Sonnet run including
    backpocket's 85.2%, and it is the only run at/near the top on *both* axes.
  - It also **fixed the doc Sonnet failed on completely in Dataiku**
    (`384-201-00004 v1.0 05 Mar 2025`): from 0 extracted fields
    (`needs_manual_template`) to **F1 90.5%** (19/20 truth fields recovered),
    above even the healthy Sonnet-CLI baseline (75%).
  - **Model-dependent:** narrow-splitting *helps Sonnet* but *hurts GPT*
    (`c_narrow_split` is GPT's worst config). GPT prefers more context in fewer
    passes. Whether approach D recovers GPT's losses is still open (`d_gpt`
    running).
- **Status — awaiting Dataiku results.** The Dataiku notebook
  (`dataiku_notebook_pipeline/CRF_codegen_induction.ipynb`) is now preset to
  approach D for Sonnet, with a `CONCURRENCY` knob for parallel batching. A full
  11-document Dataiku validation run has **not yet been run** — these single-doc
  numbers are strong but directional until the corpus run confirms they
  generalize.

---

## Open follow-ups (from the backpocket report, not started)

1. Risk-targeted audit sampling for over-extraction (targets the Rave 1,628-pair failure).
2. Title-source support validation beyond same-page persistence.
3. Keep Sonnet-generate / GPT-audit hybrid as a targeted fallback, not the default.
4. Diagnose Sonnet 384 regressions and GPT Rave explosion from the accepted extractors.
5. Measure marginal value of the 6th version on 900+ page books.
6. First-class parallel disjoint-document runner with atomic summary merge.
7. Validate fixes on unseen CRF books before changing the production default.

---

## Going forward — git workflow

The repo root (`D:\ubuntu\codes\ZS\otsuka\ECS`) is now a git repository. Heavy
and generated data (`data/`, `*.zip`, PDFs, PNGs, xlsx, notebooks, `__pycache__`)
are git-ignored so only source and this history folder are tracked.

To keep the "which change → which result" chain intact from now on:

1. **Before a run**, commit the code: `git add -A && git commit -m "..."`.
   Note the commit hash.
2. **After a run**, copy the run's small artifacts into a new
   `project_history/results/rN_<name>_<date>/` folder (summary json, `scored.json`
   snapshot, cost/error reports, the eval report) and add a row to the timeline
   table above with the commit hash.
3. Tag notable runs: `git tag run-<name>`.

This replaces the old pattern of overwriting `out/<doc>/` artifacts keyed only by
model name and hand-copying `out_*` backups.
