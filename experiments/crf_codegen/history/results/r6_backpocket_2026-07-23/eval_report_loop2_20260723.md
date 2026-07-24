# Loop-2 evaluation report - 11 documents x Sonnet 4.5 + GPT 5.2 (CLI)

Date: 2026-07-23. Pipeline state: loop-2 changes (audit rotation/promotion/scaling,
junk-coverage carve-out, cluster safety net, radius-driven representatives,
multi-pass specialists, sandbox module additions) plus all fixes from the
pre-launch consistency review. Both models ran the IDENTICAL pipeline, back to
back, on freshly purged per-document outdirs; stage 0 was rerun beforehand with
the radius-driven representative policy.

- Sonnet run: `cli_induction_summary_claude_4_5_sonnet.json`, log `eval_sonnet_20260723.log`
- GPT run: `cli_induction_summary_gpt_5_2.json`, log `eval_gpt52_20260723.log`
- Scores: `accuracy_audit/scored.json` (page-sampled truth + Rave full-document truth);
  baseline snapshot preserved in `accuracy_audit/scored_baseline_pre_loop2.json`
- Costs: `cost_report_claude_4_5_sonnet.csv`, `cost_report_gpt_5_2.csv`

## 1. Headline results

Page-sampled ground truth (45-51 scored pages across the corpus), plus the
full-document Rave comparison against `digitized.csv`:

| run | loop | precision | page recall | doc recall | TP | FP | missed | forms correct | Rave prec | Rave rec |
|---|---|---|---|---|---|---|---|---|---|---|
| Sonnet 4.5 CLI (this run) | loop-2 | 78% | 63% | 91% | 235 | 68 | 140 | 43/45 | **87%** | 83% |
| GPT 5.2 CLI (this run) | loop-2 | 74% | **85%** | **96%** | **319** | 111 | **56** | 18/51 | **97%** | **84%** |
| Sonnet 4.5 CLI (baseline) | loop-1 | 78% | 76% | - | 286 | 81 | 89 | 48/49 | 67% | 89% |
| Sonnet 4.5 Dataiku | loop-1 | 75% | 73% | 86% | 273 | 93 | 102 | 47/48 | 52% | 85% |
| GPT 5.2 Dataiku | loop-1 | 74% | 62% | 94% | 231 | 82 | 144 | 47/47 | 63% | 93% |

Reliability: **both models exported all 11 documents** (no `needs_manual_template`,
no crashes, no transport failures). 9 of 11 documents took the new multi-pass
specialist path under both models.

| run | LLM calls | in / out tokens | LLM time | wall time | est. cost* |
|---|---|---|---|---|---|
| Sonnet 4.5 | 161 | 1.58M / 168K | 70.3 min | 72.7 min | $7.26 |
| GPT 5.2 | 156 | 1.65M / 401K | 301.3 min | 304.9 min | $10.98* |

*tiktoken proxy at $3/$15 per MTok for BOTH models (Sonnet list pricing; GPT 5.2
priced differently in reality - compare token columns, not dollars). GPT averages
116 s per call vs Sonnet's 26 s and emits 2.4x the output tokens.

## 2. Per-document detail

Page-sampled tp/fp/missed. "Sonnet base" is the pre-loop-2 baseline run of the
same CLI pipeline.

| document | Sonnet base | Sonnet now | GPT now | GPT forms | Sonnet forms |
|---|---|---|---|---|---|
| 326-...v1.0_30_Sep_2024 | 33/8/0 | 32/8/1 | 33/17/0 | 0/10 | 10/10 |
| 326-...30_Sep_2024_1_ | 27/32/0 | 27/4/0 | 26/21/1 | 0/10 | 10/10 |
| 331-...04_Jul_2023 | 19/0/9 | **1/0/27** | 18/7/10 | 3/3 | 0/1 |
| 331-...26_Jul_2023 | 15/0/13 | 23/2/5 | 19/2/9 | n/a | n/a |
| 384-...04Nov2024 | 31/0/0 | 31/0/0 | 31/0/0 | 4/4 | 4/4 |
| 384-...05_Mar_2025 | 19/4/1 | 20/10/0 | 19/20/1 | 1/1 | 0/1 |
| 384-...20_May_2025 | 22/13/3 | 25/1/0 | 21/2/4 | 2/2 | 2/2 |
| 384-...aCRF_16JAN2025 | 23/5/4 | **2/2/25** | 27/11/0 | 2/5 | 3/3 |
| MAC186 form tracker | 58/10/43 | **24/2/77** | **82/0/19** | 4/4 | 2/2 |
| QSC302573_Final | 14/4/9 | 23/4/0 | 15/20/8 | 0/10 | 10/10 |
| annotatedCRF_2021 | 25/5/7 | 27/**35**/5 | 28/11/4 | 2/2 | 2/2 |

Total extracted fields (full documents): Sonnet baseline ~22.4K, Sonnet now 16.0K,
GPT now 28.9K.

## 3. What worked

- **Reliability of the loop machinery.** 22/22 document runs exported. The
  multi-pass merge, per-pass artifacts, scope masking, stale-artifact purge,
  audit rotation/promotion and per-pass profiling all ran without a single
  orchestration error across both models (after the pre-launch fixes below).
- **Sparse-scope softening + coverage confirm round.** MAC186's tail pass
  produced 0 records at v1; instead of hard-failing the document, the confirm
  round extended the program to 116 records at 94% scope coverage. On
  aCRF_16JAN the model correctly answered CONFIRM_NO_FIELDS for a 7-page
  furniture-only scope, spending only 2 calls. Under loop-1 gates, both would
  have been `needs_manual_template`.
- **False-positive reduction on Sonnet.** The doc that previously emitted 32
  sampled FPs (326-..._1_) dropped to 4; 20_May went 13 -> 1. Corpus-wide Sonnet
  FPs fell 81 -> 68 while precision held at 78%.
- **Rave full-document precision.** Sonnet 67% -> 87%, and GPT-on-loop-2 reached
  97% (its loop-1 Dataiku run: 63%). The extraction is much cleaner end-to-end
  on the digitized-truth format.
- **Three documents materially improved for Sonnet**: 26_Jul (tp 15 -> 23),
  QSC302573 (tp 14 -> 23, missed 9 -> 0), 20_May (tp 22 -> 25). These are the books
  the bigger audit samples (6 -> 9-12 pages) and hole-first cluster dumps were
  aimed at.
- **GPT 5.2 recall.** 85% page recall / 96% doc recall / 319 TP - the best
  recall of ANY run to date on either loop, at equal-or-better precision than
  its own loop-1 run. The loop-2 feedback machinery (not just the model swap)
  contributed: GPT loop-1 on Dataiku scored 62% page recall.
- **Audit promotion/rotation working as designed** - trails show cores growing
  by exactly the pages the audit flagged (e.g. "audit core grew by [5]"), and
  rotation exploring fresh pages every round instead of re-auditing the same 6.

## 4. What did not work

- **`SPECIALIST_NOTE` collapses Sonnet's v1 coverage on multi-pass books.**
  The ownership framing ("you own ONLY the layout families shown...") makes
  Sonnet write narrow, representative-matching parsers. MAC186 main pass:
  v1 = 5% coverage / 327 records, climbing only to 15% / 805 by budget
  exhaustion - versus 88% / 4,852 at v1 for the identical model without the
  note (baseline trail). Three documents collapsed this way (MAC186 -85%
  fields, 04_Jul -65%, aCRF_16JAN -59%), erasing the corpus-wide recall gains:
  Sonnet page recall 76% -> 63%. GPT largely ignored the framing (it kept
  doc-wide parsers) and so was not hurt. This is the single biggest regression
  and is prompt-fixable.
- **GPT form-name regression on annotated 326/QSC-style books.** GPT names
  forms by per-field section headers ("Concomitant Medication: CM Witness
  Check 8 #1") instead of the page's form title ("QSC302573, Prior and
  Concomitant Medications"): 0/10 forms correct on each of the three books,
  18/51 overall (its loop-1 Dataiku run: 47/47). Sonnet is near-perfect
  (43/45) on the same pages. The distinct-form-count warning fired during the
  run but GPT kept its convention; the audit's wrong_form channel did not
  overrule it.
- **Lab-panel over-extraction on the 2021 book (Sonnet).** FPs 5 -> 35 on
  sampled pages: every analyte row (Albumin, ALT, Hematocrit, ...) of lab
  result tables is now extracted as a field where truth counts only the actual
  data-entry fields. A side effect of the aggressive coverage push (hole-first
  dumps + lowered uncovered threshold); recall on the same book improved
  slightly (tp 25 -> 27, missed 7 -> 5).
- **`plan_passes` splits too eagerly.** 9/11 documents went multi-pass, mostly
  spawning tiny tail passes (3-17 pages) that cost a full induction loop each.
  Combined with the specialist framing, splitting was a net negative for
  Sonnet; it should be the exception (genuinely fragmented books), not the
  default.

## 5. Pre-launch consistency review and fixes

An independent code review of all loop-2 changes ran before this evaluation
(verdict: conditionally safe). Fixed before launch: stale per-pass CSV
resurrection on CLI reruns; sparse-scope volume gates hard-failing legitimate
specialist scopes; specialist framing missing from revision/confirm prompts;
scoped metadata dropping the pass's own shown pages; cumulative (double-counted)
per-pass timings; audit count vs per-page map disagreement on duplicate page
objects; two latent crashes (`_spread(k=0)`, rotation fallback under scope);
audit history recording unaudited pages; smoke-test false failures on masked
specialist CSVs; stale documentation paths. A new mechanical test now covers
multi-pass orchestration (stale purge, worst-status, per-pass profile slicing).
The first launch attempt crashed on a profile-accumulator `KeyError` that the
test had masked by pre-seeding state `main()` does not provide; fixed, test
hardened to reproduce `main()` exactly, relaunched clean. Full suite: 41 checks
green; notebook bundle regenerated and selftest passed.

## 6. Next plan (NOT started - for discussion)

1. **Fix the specialist framing (highest value, small change).** The pass that
   owns the budgeted clusters (the de-facto generalist, usually >90% of pages)
   should get NO ownership framing - or the note should read "write a GENERAL
   parser for the whole document; the harness handles ownership/masking",
   keeping masking as a safety net instead of a behavioral instruction. Tail
   specialist passes keep a scoped note. Expected to recover the three
   collapsed Sonnet books while keeping multi-pass benefits (MAC186 tail pass,
   QSC gains).
2. **Make splitting rare.** Raise the `plan_passes` threshold so a specialist
   pass requires a substantial tail (e.g. >= 8 tail rep pages or >= 30 owned
   content pages), folding small tails into the main pass. Target: 2-3
   multi-pass documents on this corpus, not 9.
3. **Form-name contract in the prompt/audit.** Add one CODEGEN_PROMPT line
   pinning form_name to the page-level form title (not per-field section
   headers), and make repeated `wrong_form` audit findings block convergence
   the way `missed` does. This targets GPT's 18/51; Sonnet is unaffected.
   *(IMPLEMENTED 2026-07-23, see "Post-report update" below.)*
4. **Enumeration-row guard for lab panels.** Extend the furniture warning to
   flag pages whose extracted fields are mostly rows of a repeated table
   structure (analyte lists), and let the audit's false-extraction channel veto
   them; targets the 2021 book FP regression.
5. **Cheap validation loop.** Re-run ONLY the three collapsed documents with
   fix 1+2 (about $1.5-2 of Sonnet budget) before deciding on a full 11-doc
   re-eval.
6. **Model choice.** On loop-2, GPT 5.2 is the recall/Rave-precision leader but
   3-4x slower, wordier, and currently broken on form names; Sonnet is the
   form-fidelity leader and 4x faster. If fixes 1-3 land, re-compare; a hybrid
   (Sonnet generate, GPT audit) is worth one experiment.

## 7. Post-report update (2026-07-23): next-plan item 3 implemented

Root cause was confirmed against the raw outputs before fixing: on the same
document, GPT loop-1 produced 6 distinct forms (printed page titles), Sonnet
loop-2 produced 7, GPT loop-2 produced 331 distinct forms out of 996 records -
per-field annotation stamps used as form_name. The contract line "the CRF
form/section the field belongs to" was ambiguous between the two printed
signals on annotated CRFs, the degenerate-forms check was only a warning (and
its old threshold went silent above 2 fields/form), and the self-graded audit
accepted its own convention.

Implemented - deliberately structural, nothing fitted to this corpus's
annotation shapes (no regex for annotation stamps, no vendor conventions):

- **Contract pinned by definition, not by pattern** (`CODEGEN_PROMPT`, revision
  contract restatement, confirm template): form_name is the title printed for
  human readers that GROUPS a form's fields, carried across continuation pages;
  never text attached to a single field (its own label, a machine code, or a
  per-field technical annotation). The structural self-check is stated in the
  prompt: near-unique form_name per record means per-field text was read.
- **Two-tier structural gate** (`induction.py`): an output of >=20 records
  averaging <2 fields per "form" violates the grouping definition itself and is
  now a hard gate (`gate_form_explosion`); an average under 4 is an advice-tier
  warning (band widened from the old records/2 threshold, which had gone silent
  exactly where GPT converged at 3.0 fields/form). Tiny outputs stay in the
  advice tier; scoped specialist passes are NOT exempt from this gate.
- **Audit given the convention** (`AUDIT_PROMPT_TEMPLATE`): `wrong_form` now
  explicitly covers form_name values that are not printed titles at all, so the
  auditor's issue counts block convergence in the 2-4 fields/form band that the
  hard gate deliberately leaves open.

Against the observed failure: v1 (334 records / 333 forms) now hard-gates and
forces a revision with the definitional feedback; the previously-converged
final shape (996 / 331) now draws both the warning and page-grounded
`wrong_form` findings. Tests: 3 new checks (hard tier, advice band + silence,
tiny-output exemption), full suite 44/44 green; notebook bundle regenerated,
selftest passed. Not yet re-run on the corpus - validation rides with the
next-plan re-run (items 1-2, 5).

## 8. Post-report update (2026-07-23): items 1, 2, 4 implemented + validated

### Implemented

- **Specialist framing fixed** (item 1). Pass 1 of a multi-pass run is now a
  GENERALIST: its initial, revision and confirm prompts are byte-identical to a
  single-pass run - no ownership language anywhere. Tail passes keep a note,
  rewritten from behavior-restricting ("responsible ONLY for these families")
  to harness-descriptive: the harness credits the pass only for its assigned
  pages, over-extraction costs nothing, so write the program as if it owned the
  whole document. Volume-gate softening (`soften_scoped_volume_gates`) now
  applies to tail specialists only; the main pass keeps every single-pass gate.
- **Splitting made rare** (item 2). `plan_passes` folds the whole tail into the
  single pass unless it is substantial: >= 8 tail rep pages (more than ~2
  revision rounds of cluster feedback could show) AND >= 20 content pages.
  Corpus effect: 3/11 documents split (the two 1083-page 331 books and the
  35-cluster 2021 book) instead of 9/11. MAC186 and 384-aCRF_16JAN no longer
  split at all.
- **Enumeration-row guard** (item 4, scoped down). Implemented as a third audit
  calibration rule plus a mirrored generator quality-bar line - printed
  reference/enumeration rows with no per-row entry cell are content, report
  extractions under `false` - rather than a mechanical page-shape detector,
  which risked flagging legitimate questionnaire grids. The rule states that
  entry cells are often DRAWN boxes invisible in the text dump, to be judged
  from column purpose.
- **Review hardening.** An independent code review found no critical issues;
  its moderate findings were fixed: the audit rule's drawn-box blind spot
  (above), test coverage pinning the main/tail note wiring and the
  `scope["main"]` plumbing (a revert of either now fails the suite), and the
  gate-prefix coupling now tested against real `gate_problems` output. Suite:
  51/51 green; bundle selftest passed.

### Validation runs (Sonnet on the 3 collapsed docs, GPT 5.2 on 326 v1.0)

Page-sampled truth, same packets as the loop-2 eval:

| doc | run | baseline TP/miss | loop-2 TP/miss | now TP/miss |
|---|---|---|---|---|
| 331 04_Jul (1083p) | Sonnet | 19 / 9 | 1 / 27 | **19 / 9** (FP 0 -> 7) |
| 384 aCRF_16JAN (206p) | Sonnet | 23 / 4 | 2 / 25 | **27 / 0** (converged, 0 audit issues) |
| MAC186 (913p) | Sonnet | 58 / 43 | 24 / 77 | **29 / 72** (doc-level recall 74%) |
| 326 v1.0 (112p) | GPT 5.2 | - | 33 / 0 | 33 / 0 (FP 17 -> 22) |

Sonnet run totals across all 11 docs: precision 78.2%, page recall 75.5%
(baseline 77.9% / 76.3%; loop-2 was 77.6% / 62.7%). **The multi-pass collapse
is fixed** - the loop-2 recall regression is fully recovered, at 3 fewer
specialist passes per corpus run. 04_Jul's generalist pass alone reached 88%
page coverage / 2895 fields (loop-2 main pass: 5%); 16JAN beats its baseline
(27 TP / 0 missed).

### What is NOT fixed

- **GPT form titles on annotated books (326 v1.0)**: form pages still 0/10
  correct. The new hard gate fired mid-loop and blocked a worse version (v4:
  289 forms / 311 records), and the warning fired every round, but GPT's best
  version (v3, 1091 records / 329 forms, 3.3 fields per form) sits just above
  the definitional 2-fields/form gate and kept the annotation-as-title
  strategy to budget exhaustion ("Exclusion: E05 #1"-style form names).
  Contract + ratio gate are necessary but not sufficient for GPT here. Next
  generic idea (not started): a form-name PERSISTENCE signal - printed titles
  repeat across runs of consecutive records/pages, per-field text churns on
  nearly every record - as a gate or audit hint; still structural, no
  annotation regexes.
- **MAC186 page-instance coverage**: partially recovered (6/10 sampled field
  pages covered vs 3 in loop-2, 9 at baseline; page recall 29% vs 57%
  baseline; doc-level recall 74% - the fields are extracted, but not on every
  repeated instance of the same visit form). Single-pass now, plateaued at
  budget with 15 audit issues. Candidate: instance-coverage feedback
  (per-cluster covered-instance counts) or a higher version budget for
  900+-page books.
- **GPT precision creep on 326 v1.0** (FP 17 -> 22 on sampled pages): the
  extract-everything energy of the reworded framing costs a little junk;
  worth watching, not acting on yet.

Artifacts: pre-rerun state preserved in `out_backup_loop2eval/` (4 doc
folders), `cli_induction_summary_*.preloop3.bak.json`, and
`accuracy_audit/scored_loop2_eval.json`; rerun rows merged back into the full
11-doc summaries and `scored.json` rescored over all runs.

## 9. Post-report update (2026-07-23): junk-coverage carve-out rebuilt on evidence

### Root cause of the MAC186 residual regression

Replaying MAC186's discarded v2 extractor against the PDF showed it had been
extracting REAL fields on the pages the final v3 lost - not junk. The old
carve-out in `improves()` INFERRED "junk cleanup" from proxies (audit issues
strictly down on shared pages, few new pages, half retained) and on that basis
blessed v3, which dropped 340 truly-covered pages (~3,000 records) for a
1-issue audit improvement measured on a 13-page sample. The inference had no
way to know what was on the dropped pages, and its half-retention floor also
baked in an assumed junk-to-content ratio that other CRF books would violate
in both directions.

### The fix (generic, evidence-scaled, no ratio knobs)

- **`forgivable_junk_pages`** (`codegen.py`): a lost page is forgiven only if
  EVERY record the incumbent extracted on it matches verified junk evidence -
  values the page-grounded audit flagged under `false`, or doc-wide furniture
  candidates (values on >= 70% of pages). Matching is normalized
  (whitespace/case) exact-value: junk is a repeated stamp, so a value flagged
  on one sampled page identifies the same record on unsampled pages.
- **`improves()`**: the retention veto is lifted exactly when ALL lost pages
  are verified junk-only. The audit-delta inference, the new-page cap and the
  half-retention floor are gone - forgiveness scales with evidence, so a book
  whose parser stamped junk on half its pages can shed half its pages, and a
  book with one unverified lost page keeps its veto. Failure direction is
  one-way: missing evidence keeps junk (visible, bounded); it never releases
  real coverage (invisible, unbounded - the MAC186 failure).
- **Wiring** (`run_cli_induction.py`): `junk_evidence` accumulates per pass
  from every audit round plus each version's furniture candidates; forgiven
  drops are printed and recorded in the trail (`forgiven_pages`), so a
  coverage-sacrificing best-switch is now diagnosable post-hoc.
- **Audit contract tightened** (review finding): the auditor must echo the
  record's field_name exactly as shown in its `extracted:` line for
  `false`/`wrong_form` entries - a paraphrase would silently disable
  forgiveness (conservative, but pointlessly so).
- Review: independent pass found no criticals; both moderates fixed (echo
  contract above; furniture-evidence path now pinned by its own test). Suite
  52 checks green, including: verified cleanup accepted, unverified/partial
  vetoed, 70%-drop accepted when fully verified (ratio independence), and
  end-to-end wiring for both evidence sources. Bundle selftest passed.

### Validation: MAC186 rerun (Sonnet, single-pass, ~8 min)

| version | records | pages | audit issues | became best |
|---|---|---|---|---|
| v1 | 3,087 | 439 | 16 | yes |
| v2 | 3,313 | 414 | 6 | **yes (exported)** |
| v3 | 3,847 | 451 | 26 | no |
| v4 | 3,968 | 456 | 23 | no |
| v5 | 3,968 | 456 | 25 | no |

The guard held: nothing displaced v2, no forgiveness was needed (the broken
run's collapse scenario is pinned by unit tests instead). Scored against the
sampled truth:

| metric | pre-loop2 baseline | broken carve-out rerun | now |
|---|---|---|---|
| TP / missed | 58 / 43 | 29 / 72 | 45 / 56 |
| precision | 85.3% | ~79% | 84.9% |
| page recall | 57.4% | 29% | 44.6% |
| doc-level recall | 87.1% | 74% | **90.1%** |
| pages covered (doc-wide) | 407 | 74-340 | **414** |

Corpus totals (Sonnet CLI, 11 docs): precision 78%, page recall 80% - now
ABOVE the pre-loop2 baseline (77.9% / 76.3%) on both axes.

### Remaining gap

MAC186 sampled-page recall (44.6%) still trails its baseline run (57.4%)
while doc-level recall exceeds it: this run's program covers MORE pages but a
partly different set - 5 of the 10 sampled field pages vs the baseline run's
9 - and v3-v5 spent the budget adding sloppy coverage (audit 23-26) rather
than closing those holes. That is run variance plus the known
instance-coverage weakness (section 8), not a guard failure; the candidate
fixes stand: per-cluster covered-instance feedback, or a higher version
budget for 900+-page books. GPT's form-title persistence idea also remains
open.

## 10. Post-report update (2026-07-23): family-handler prompt validation

### Change tested

Stage-0 representative pages are now explicitly grouped and labeled by
structural layout family. The generator is asked to mirror those families
with separate handlers and a structural dispatcher, use relative/tolerant
geometry, avoid literal-text blocklists, and never skip whole pages using
density heuristics. Audit revisions explicitly say that `false` findings are
examples of a structural class, not strings to append to a blocklist. An
AST-based warning identifies generated programs with >=10 literal text
filters; it is advisory only. Mechanical suite and bundle selftest passed.
The independent review was intentionally skipped to proceed directly to live
testing.

### Targeted validation

| document/model | previous targeted result | family-handler result | verdict |
|---|---|---|---|
| MAC186 / Sonnet 4.5 | TP 45, FP 8, missed 56; page recall 44.6%; doc recall 90.1%; 414 pages covered | **TP 63, FP 9, missed 38; precision 87.5%; page recall 62.4%; doc recall 93.1%; 859 pages covered** | substantial recall improvement |
| 326 v1.0 / GPT 5.2 | TP 33, missed 0, FP 22; form pages 0/10 | **TP 0, missed 33, FP 17; form pages 0/10** | severe field-recall regression; form-title failure unchanged |

Sonnet/MAC186 confirms that exposing the family grouping and asking for
family-local logic can recover the repeated-instance coverage that a single
global 7.5pt cutoff lost. It now exceeds the original pre-loop2 MAC186 result
(TP 58 / missed 43) on sampled recall while retaining comparable precision.
Across the current 11-document score, Sonnet reaches **79% precision / 85%
page recall / 96% document recall** (317 TP, 85 FP, 58 missed).

The same prompt is not model-neutral. GPT interpreted the 326 activity-block
layout too narrowly: it emitted only activity-associated question rows and
repeated left labels, still used per-field activity text as `form_name`
(333 forms for 668 records), and matched none of the 33 truth field labels.
Later versions became worse (including one zero-record rewrite); v1 remained
best. GPT's corpus total consequently fell to 72% precision / 76% page recall.

### Additional findings from the live loop

- The blocklist warning detects the behavior but does not stop it. MAC186
  Sonnet started with 11 literal filters and later versions grew to 15 and
  18 despite repeated guidance. Prompt advice alone cannot reliably enforce
  structural exclusions.
- MAC186's exported v3 covers 859/913 pages and scores better against sampled
  truth, but its grounded audit reported 45 issues. Family dispatch improved
  recall while making precision control harder; the audit/version-selection
  policy needs calibration before a full re-evaluation.
- The family-handler architecture should therefore not be promoted unchanged
  to both models. The next iteration should preserve the family labels (useful
  for Sonnet), make the architecture optional rather than prescriptive for
  simple/single-family layouts, and turn large content blocklists into a
  stronger revision gate or mechanically reject only the offending source
  shape. GPT still needs the backpocket form-name persistence gate.

## 11. Post-report update (2026-07-23): independent title-context channel

### Gap and implementation

Layout sampling had no title-visibility guarantee. Representatives optimize
structural coverage, so a prompt can contain only continuation pages while
the form title was announced earlier. The generator would then have to guess;
the grounded auditor had the same blind spot because it saw each sampled page
in isolation.

The fix is an independent, corpus-free title-context channel:

- Stage 0 examines only the top 30% of each page and removes text repeated on
  >=95% of pages as invariant chrome. Strings repeated on at least two but
  fewer than 95% of pages define changing top-context signatures. One
  non-representative page from each largest distinct signature is selected
  (maximum six), dumped as `title_p<N>.*`, and recorded separately in
  `title_context_pages_1based`.
- These pages appear in a dedicated `TITLE/FORM CONTEXT ONLY` prompt section.
  They do not become layout representatives, do not change cluster ownership,
  and do not affect coverage or multi-pass masking. The model is told to
  distinguish invariant chrome, the title that changes by a run of pages, and
  per-field activity/annotation text.
- Every grounded-audit page now receives the top region of its two immediately
  preceding pages as `TITLE LOOKBACK CONTEXT`. Those pages are context only,
  not audit targets, so carried titles can be judged without adding false
  field findings.

No title vocabulary, vendor pattern, language, embedding or external model is
used. Mechanical tests cover changing-header selection, ubiquitous-chrome
removal, representative exclusion, prompt loading and audit lookback; the
full stop-policy suite and regenerated Dataiku bundle selftest pass.

### Selected evidence on 326 v1.0

Stage 0 selected non-representative pages 5, 8, 9, 19, 53 and 85. The pack
showed the same structural header:

`Schedule Category & Name:` -> changing schedule value

including both `QSC302573, 03 - Screening Draft v0.1` and
`QSC302573, Prior and Concomitant Medications Draft`, alongside per-field
activity names lower on the page. This supplied direct contrast between the
grouping title and the text GPT had previously used as form_name.

### Exact-document validation

| model | before title channel | with title channel | title verdict |
|---|---|---|---|
| GPT 5.2 | TP 0, FP 17, missed 33; **form 0/10** (family-handler validation) | TP 27, FP 24, missed 6; precision 52.9%, page recall 81.8%, doc recall 87.9%; **form 10/10** | fixed |
| Sonnet 4.5 | TP 32, FP 8, missed 1; **form 10/10** | TP 30, FP 6, missed 3; precision 83.3%, page recall 90.9%; **form 10/10** | preserved |

Both accepted programs now explicitly read the printed schedule value and
carry it forward; neither uses the per-field activity title as form_name.
GPT's title regression is therefore fixed on the target document without the
planned persistence gate. Its field extraction also recovered substantially
from the family-handler failure, though precision remains weak.

Current 11-document totals after replacing only this target's artifacts:

- Sonnet CLI: 79% precision, 84% page recall, 95% document recall, form 48/49.
- GPT 5.2 CLI: 73% precision, 83% page recall, 95% document recall,
  **form 28/51** (up from 18/51; all ten recovered pages are this document).

### Interpretation

This validates the title channel as a solution to missing or ambiguous title
evidence. On 326 the title was technically printed on every page, so the gain
came from independent repetition and contrast: the model saw several changing
schedule values explicitly labeled as title context instead of having to
choose among all prominent strings in ordinary field samples. For genuine
continuation-only audit pages, the new lookback closes the original absence
case directly.

The persistence gate remains in the backpocket rather than being implemented
now. A full 11-document rerun is still required to determine whether the
channel generalizes without the small Sonnet field-recall variance observed
here.

## 12. Post-backpocket full rerun and targeted hybrid (2026-07-23)

The deferred persistence, model-neutral family handling, literal-blocklist
enforcement, and large-document budget changes were implemented and evaluated
on all 11 documents with both CLI models.

Headline results:

- Sonnet: 73.2% precision, 73.6% page recall, 93.9% document recall,
  73.4% F1, form 50/51. The 2021 331 book remains
  `needs_manual_template` because one specialist pass failed; its scored output
  is fresh but partial.
- GPT 5.2: 80.3% precision, 82.7% page recall, 96.5% document recall,
  81.5% F1, form 44/57.
- The targeted Sonnet-generation/GPT-audit hybrid recovered form accuracy to
  10/10 on the 489-page 326 book and 2/2 on the January aCRF.
- GPT's full-document Rave precision regressed from 97.5% to 47.5% because
  extracted distinct pairs grew from 792 to 1,628 while matched pairs remained
  essentially unchanged (772 to 773). This is the highest-priority follow-up.

The complete report, per-document deltas, interpretation, artifacts, and
prioritized next todos are in
`data/outputs/out/eval_report_backpocket_20260723.md`.
