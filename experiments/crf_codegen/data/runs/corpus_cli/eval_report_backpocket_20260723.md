# Full 11-document CLI evaluation after backpocket changes

Date: 2026-07-23

Models: Claude Sonnet 4.5 and GPT 5.2 through the Cursor CLI.

Comparison baseline: `accuracy_audit/scored_loop2_eval.json` (the previous full loop-2 11-document CLI evaluation). Current scores use the same frozen 110-page ground-truth sample.

## 1. Aggregate accuracy

| Model | Precision | Δ | Page recall | Δ | Doc recall | Δ | F1 | Δ | Form accuracy | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Claude Sonnet 4.5 | 73.2% | -4.3 pp | 73.6% | +10.9 pp | 93.9% | +2.7 pp | 73.4% | +4.1 pp | 50/51 (98.0%) | +2.5 pp |
| GPT 5.2 | 80.3% | +6.1 pp | 82.7% | -2.4 pp | 96.5% | +0.5 pp | 81.5% | +2.2 pp | 44/57 (77.2%) | +41.9 pp |

## 2. Full-document Rave pair evaluation

| Model | Precision | Δ | Recall | Δ | Matched / GT |
|---|---:|---:|---:|---:|---:|
| Claude Sonnet 4.5 | 85.4% | -1.7 pp | 84.7% | +2.0 pp | 775 / 915 |
| GPT 5.2 | 47.5% | -50.0 pp | 84.5% | +0.1 pp | 773 / 915 |

## 3. Claude Sonnet 4.5 per-document results

| Document | Status | Precision | Δ | Page recall | Δ | Doc recall | Δ | Form | TP / FP / missed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `326-201-00007_Annotated_CRF___v1.0_30_Sep_2024` | ok_audit_issues | 53.6% | -26.4 pp | 90.9% | -6.1 pp | 100.0% | +3.0 pp | 10/10 | 30 / 26 / 3 |
| `326-201-00007_Annotated_CRF___v1.0_30_Sep_2024_1_` | ok_audit_issues | 89.3% | +2.2 pp | 92.6% | -7.4 pp | 96.3% | -3.7 pp | 8/8 | 25 / 3 / 2 |
| `331-201-00246_Annotated_CRF___v_04_Jul_2023` | ok_audit_issues | 52.8% | -47.2 pp | 100.0% | +96.4 pp | 100.0% | +3.6 pp | 3/3 | 28 / 25 / 0 |
| `331-201-00246_Annotated_CRF___v_26_Jul_2023` | ok_audit_issues | 94.7% | +2.7 pp | 64.3% | -17.9 pp | 100.0% | +10.7 pp | 0/0 | 18 / 1 / 10 |
| `384-201-00002_Annotated_Unique_CRF_04Nov2024` | ok_audit_issues | 100.0% | +0.0 pp | 87.1% | -12.9 pp | 93.5% | -6.5 pp | 4/4 | 27 / 0 / 4 |
| `384-201-00004_Annotated_CRF___v1.0_05_Mar_2025` | ok_audit_issues | 100.0% | +33.3 pp | 60.0% | -40.0 pp | 90.0% | -10.0 pp | 1/1 | 12 / 0 / 8 |
| `384-201-00004_Annotated_CRF___v2.0_20_May_2025` | ok_audit_issues | 29.7% | -66.4 pp | 44.0% | -56.0 pp | 92.0% | -8.0 pp | 5/6 | 11 / 26 / 14 |
| `384-201-00004_aCRF_16JAN2025` | ok_audit_issues | 66.7% | +16.7 pp | 7.4% | +0.0 pp | 70.4% | +18.5 pp | 2/2 | 2 / 1 / 25 |
| `MAC186_X11-201-00001_eCRF_v1.10_form_tracker_v1.6_06Mar2025` | ok_audit_issues | 91.4% | -0.9 pp | 73.3% | +49.5 pp | 94.1% | +7.9 pp | 5/5 | 74 / 7 / 27 |
| `QSC302573_Final_AnnotatedCRFs_16Oct2024-326-201-00007_1_` | ok_audit_issues | 71.9% | -13.3 pp | 100.0% | +0.0 pp | 100.0% | +0.0 pp | 10/10 | 23 / 9 / 0 |
| `annotatedCRF_33120100246-_v1.0_-17Aug2021` | needs_manual_template | 89.7% | +46.1 pp | 81.2% | -3.1 pp | 93.8% | -3.1 pp | 2/2 | 26 / 3 / 6 |

## 4. GPT 5.2 per-document results

| Document | Status | Precision | Δ | Page recall | Δ | Doc recall | Δ | Form | TP / FP / missed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `326-201-00007_Annotated_CRF___v1.0_30_Sep_2024` | ok_audit_issues | 100.0% | +34.0 pp | 100.0% | +0.0 pp | 100.0% | +0.0 pp | 10/10 | 33 / 0 / 0 |
| `326-201-00007_Annotated_CRF___v1.0_30_Sep_2024_1_` | ok_audit_issues | 48.7% | -6.6 pp | 70.4% | -25.9 pp | 96.3% | -3.7 pp | 0/10 | 19 / 20 / 8 |
| `331-201-00246_Annotated_CRF___v_04_Jul_2023` | ok_audit_issues | 91.3% | +19.3 pp | 75.0% | +10.7 pp | 100.0% | +3.6 pp | 3/3 | 21 / 2 / 7 |
| `331-201-00246_Annotated_CRF___v_26_Jul_2023` | ok_audit_issues | 95.7% | +5.2 pp | 78.6% | +10.7 pp | 96.4% | +10.7 pp | 0/0 | 22 / 1 / 6 |
| `384-201-00002_Annotated_Unique_CRF_04Nov2024` | ok_audit_issues | 100.0% | +0.0 pp | 100.0% | +0.0 pp | 100.0% | +0.0 pp | 9/9 | 31 / 0 / 0 |
| `384-201-00004_Annotated_CRF___v1.0_05_Mar_2025` | ok_audit_issues | 85.7% | +37.0 pp | 60.0% | -35.0 pp | 75.0% | -25.0 pp | 1/1 | 12 / 2 / 8 |
| `384-201-00004_Annotated_CRF___v2.0_20_May_2025` | ok_audit_issues | 96.0% | +4.7 pp | 96.0% | +12.0 pp | 100.0% | +0.0 pp | 2/2 | 24 / 1 / 1 |
| `384-201-00004_aCRF_16JAN2025` | ok_audit_issues | 89.7% | +18.6 pp | 96.3% | -3.7 pp | 96.3% | -3.7 pp | 2/5 | 26 / 3 / 1 |
| `MAC186_X11-201-00001_eCRF_v1.10_form_tracker_v1.6_06Mar2025` | ok_audit_issues | 87.5% | -12.5 pp | 76.2% | -5.0 pp | 100.0% | +2.0 pp | 5/5 | 77 / 11 / 24 |
| `QSC302573_Final_AnnotatedCRFs_16Oct2024-326-201-00007_1_` | ok_audit_issues | 47.7% | +4.9 pp | 91.3% | +26.1 pp | 91.3% | +21.7 pp | 10/10 | 21 / 23 / 2 |
| `annotatedCRF_33120100246-_v1.0_-17Aug2021` | ok_audit_issues | 64.9% | -6.9 pp | 75.0% | -12.5 pp | 90.6% | -6.2 pp | 2/2 | 24 / 13 / 8 |

## 5. Targeted hybrid experiment

Triggered because GPT still had form-title failures after the full run. Sonnet generated/revised the extractor; GPT performed only grounded audit calls.

| Document | Precision | Page recall | Doc recall | Form | TP / FP / missed |
|---|---:|---:|---:|---:|---:|
| `326-201-00007_Annotated_CRF___v1.0_30_Sep_2024_1_` | 68.4% | 96.3% | 96.3% | 10/10 | 26 / 12 / 1 |
| `384-201-00004_aCRF_16JAN2025` | 83.3% | 92.6% | 96.3% | 2/2 | 25 / 5 / 2 |

## 6. Runtime summary

| Model | Documents | Versions | LLM calls | LLM time | Exported fields | Pages with fields | Final audit issues |
|---|---:|---:|---:|---:|---:|---:|---:|
| Claude Sonnet 4.5 | 11 | 70 | 125 | 1.32 h | 27037 | 4893 | 285 |
| GPT 5.2 | 11 | 59 | 113 | 5.21 h | 24945 | 5249 | 290 |

## 7. Changes evaluated

- Same-page form-title persistence signal and revision warning.
- Vocabulary-neutral, candidate-based title-context guidance.
- Optional/model-neutral family-handler architecture.
- Literal blocklist warning at 10 and hard rejection at 30, including named collections.
- Size-scaled parser-version budget: +1 at 900 pages, capped at +2.
- Existing title-context, coverage, audit rotation, and evidence-based junk safeguards.

## 8. Interpretation and next actions

### What worked

- **GPT is now the strongest field extractor on the sampled benchmark:** 80.3% precision, 82.7% page recall and 81.5% F1. Relative to the prior full run, precision rose 6.1 points, F1 rose 2.2 points and form accuracy rose from 35.3% to 77.2%.
- **Sonnet form attribution is reliable:** 50/51 scored form pages (98.0%). Its page recall rose 10.9 points and F1 rose 4.1 points.
- **The hybrid recovered both targeted title failures:** 326 improved from GPT's 0/10 forms to 10/10 with 96.3% page recall; the January aCRF scored 2/2 forms with 92.6% page recall.
- **The blocklist ceiling worked as a safety guard:** multiple later versions with 30-71 literal filters were rejected while earlier, less content-fitted versions remained eligible as best.

### What remains broken or mixed

- **GPT has a severe unsampled-page precision failure on the full Rave book.** Matched pairs stayed essentially flat (772 -> 773), but distinct extracted pairs doubled from 792 to 1,628, collapsing full-document precision from 97.5% to 47.5%. The 10-page sample scored 100% precision, so current audit sampling did not expose this over-extraction.
- **The form-name persistence signal is necessary but insufficient.** GPT still scored 0/10 forms on the 489-page 326 book because repeated non-title annotations can satisfy same-page persistence. The 112-page 326 book scored 10/10, so title behavior remains model/run sensitive.
- **Sonnet traded precision for recall:** aggregate precision fell 4.3 points. The largest regressions were 326 v1.0 (53.6% precision) and 384 v2.0 (29.7% precision); 384 v1.0 and v2.0 also lost substantial page recall.
- **One Sonnet document remains non-usable as a complete extraction:** the 2021 331 book is `needs_manual_template` because one specialist pass failed. Its displayed accuracy is for the fresh partial export and the status is now explicit; it is not a production-success row.
- **The large-document budget is mixed rather than proven.** GPT improved page recall by 10.7 points on both 331 books, while Sonnet improved one 331 book and regressed on the other. Marginal v6 benefit must be measured from trails before retaining the extra call universally.
- **GPT runtime is materially higher:** 5.21 LLM-hours versus Sonnet's 1.32 LLM-hours for the same 11 documents.

### Prioritized next todos (do not start automatically)

1. **Add risk-targeted audit sampling for over-extraction.** Reserve audit slots for pages/families with unusually high unique-label density, option-like rows, or extraction density relative to sibling pages. This directly targets the Rave 1,628-pair failure that proportional sampling missed.
2. **Replace persistence-only form validation with title-source support.** Measure whether emitted form names are supported by structurally prominent top-region candidates or a valid carried-forward candidate, while allowing document-wide invariant titles. Use this as revision evidence, not a vendor vocabulary rule.
3. **Keep hybrid routing as a targeted fallback, not the global default.** Trigger Sonnet-generation/GPT-audit when grounded audits report wrong-form issues or title-source support is weak. GPT remains preferable for aggregate field F1; Sonnet remains preferable for form attribution.
4. **Diagnose Sonnet's 384 regressions and GPT's Rave explosion from the accepted extractor/trail before changing global thresholds.** Classify false positives as wrapped-line splits, options, headers, or reference rows.
5. **Measure marginal value of the sixth version on 900+ page books.** Retain scaling only where v6 becomes best or materially improves uncovered families; otherwise spend the call on an additional risk-targeted audit.
6. **Promote parallel disjoint-document execution to a first-class runner.** Write one run manifest and atomically merge worker summaries so long GPT runs do not require terminal-log reconstruction.
7. **Validate the selected fixes on additional unseen CRF books** before changing the production default model or hybrid policy.

## 9. Artifacts

- `accuracy_audit/scored.json`
- `data/outputs/out/accuracy_audit_claude_4_5_sonnet.xlsx`
- `data/outputs/out/accuracy_audit_gpt_5_2.xlsx`
- `data/outputs/out/cli_induction_summary_claude_4_5_sonnet.json`
- `data/outputs/out/cli_induction_summary_gpt_5_2.json`
- `data/outputs/out/eval_comparison_backpocket_20260723.json`
