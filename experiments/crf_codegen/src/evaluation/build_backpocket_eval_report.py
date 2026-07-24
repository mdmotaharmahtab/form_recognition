"""Build the post-backpocket two-model evaluation comparison report."""
from __future__ import annotations

import argparse
import json
import os

from accuracy_audit import load_export, score_doc


def ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.1f}%"


def pp(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{100 * value:+.1f} pp"


def difference(current, baseline):
    return (current - baseline
            if isinstance(current, (int, float))
            and isinstance(baseline, (int, float)) else None)


def aggregate(run: dict) -> dict:
    docs = run["docs"].values()
    tp = sum(d["tp"] for d in docs)
    fp = sum(d["fp"] for d in docs)
    missed = sum(d["missed"] for d in docs)
    truth = sum(d["truth_fields"] for d in docs)
    doc_found = sum(d["doc_found"] for d in docs)
    form_pages = sum(d["form_pages"] for d in docs)
    form_ok = sum(d["form_ok_pages"] for d in docs)
    precision = ratio(tp, tp + fp)
    recall_page = ratio(tp, truth)
    recall_doc = ratio(tp + doc_found, truth)
    f1 = (2 * precision * recall_page / (precision + recall_page)
          if precision is not None and recall_page is not None
          and precision + recall_page > 0
          else (0.0 if precision is not None and recall_page is not None
                else None))
    return {
        "tp": tp, "fp": fp, "missed": missed, "truth": truth,
        "precision": precision, "recall_page": recall_page,
        "recall_doc": recall_doc, "f1": f1,
        "form_pages": form_pages, "form_ok": form_ok,
        "form_accuracy": ratio(form_ok, form_pages),
    }


def runtime_totals(rows: list[dict]) -> dict:
    return {
        "documents": len(rows),
        "fields": sum(r.get("fields") or 0 for r in rows),
        "pages_with_fields": sum(r.get("pages_with_fields") or 0 for r in rows),
        "versions": sum(r.get("versions") or 0 for r in rows),
        "llm_calls": sum(r.get("llm_calls") or 0 for r in rows),
        "llm_s": sum(r.get("llm_s") or 0 for r in rows),
        "audit_issues": sum(r.get("audit_issues") or 0 for r in rows
                            if r.get("audit_issues") is not None),
        "statuses": {s: sum(1 for r in rows if r.get("status") == s)
                     for s in sorted({r.get("status") for r in rows})},
    }


def doc_metrics(d: dict) -> dict:
    return {
        "status": d.get("status"),
        "precision": d.get("precision"),
        "recall_page": d.get("recall_page"),
        "recall_doc": d.get("recall_doc"),
        "f1": d.get("f1"),
        "tp": d["tp"],
        "fp": d["fp"],
        "missed": d["missed"],
        "form_ok": d["form_ok_pages"],
        "form_pages": d["form_pages"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--sonnet-summary", required=True)
    ap.add_argument("--gpt-summary", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--json-output", required=True)
    ap.add_argument("--hybrid-tag")
    ap.add_argument("--hybrid-doc", action="append", default=[])
    args = ap.parse_args()

    with open(args.current, encoding="utf-8") as f:
        current = json.load(f)
    with open(args.baseline, encoding="utf-8") as f:
        baseline = json.load(f)
    with open(args.sonnet_summary, encoding="utf-8") as f:
        sonnet_rows = json.load(f)
    with open(args.gpt_summary, encoding="utf-8") as f:
        gpt_rows = json.load(f)

    run_rows = {"sonnet-cli": sonnet_rows, "gpt52-cli": gpt_rows}
    labels = {
        "sonnet-cli": "Claude Sonnet 4.5",
        "gpt52-cli": "GPT 5.2",
    }
    comparison = {}
    for name in labels:
        cur = aggregate(current[name])
        old = aggregate(baseline[name])
        comparison[name] = {
            "label": labels[name],
            "current": cur,
            "baseline": old,
            "delta": {k: difference(cur[k], old[k])
                      for k in cur},
            "runtime": runtime_totals(run_rows[name]),
            "rave_current": current[name].get("rave_gt"),
            "rave_baseline": baseline[name].get("rave_gt"),
            "documents": {},
        }
        for doc, d in current[name]["docs"].items():
            dm = doc_metrics(d)
            bm = doc_metrics(baseline[name]["docs"][doc])
            comparison[name]["documents"][doc] = {
                "current": dm,
                "baseline": bm,
                "delta": {
                    k: difference(dm[k], bm[k])
                    for k in dm
                },
            }

    hybrid = {}
    if args.hybrid_tag and args.hybrid_doc:
        proto = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        run = {
            "root": os.path.join(proto, "data", "runs", "corpus_cli"),
            "tag": args.hybrid_tag,
            "dir_prefix": "",
        }
        for doc in args.hybrid_doc:
            with open(os.path.join(proto, "eval_assets", "truth",
                                   f"{doc}.json"), encoding="utf-8") as f:
                truth = json.load(f)
            hybrid[doc] = doc_metrics(score_doc(truth, load_export(run, doc)))
    comparison["hybrid"] = {
        "label": "Sonnet generation + GPT audit",
        "tag": args.hybrid_tag,
        "documents": hybrid,
    }

    with open(args.json_output, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=1)

    lines = [
        "# Full 11-document CLI evaluation after backpocket changes",
        "",
        "Date: 2026-07-23",
        "",
        "Models: Claude Sonnet 4.5 and GPT 5.2 through the Cursor CLI.",
        "",
        "Comparison baseline: `accuracy_audit/scored_loop2_eval.json` (the previous "
        "full loop-2 11-document CLI evaluation). Current scores use the same frozen "
        "110-page ground-truth sample.",
        "",
        "## 1. Aggregate accuracy",
        "",
        "| Model | Precision | Δ | Page recall | Δ | Doc recall | Δ | F1 | Δ | Form accuracy | Δ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in labels:
        c = comparison[name]["current"]
        d = comparison[name]["delta"]
        lines.append(
            f"| {labels[name]} | {pct(c['precision'])} | {pp(d['precision'])} | "
            f"{pct(c['recall_page'])} | {pp(d['recall_page'])} | "
            f"{pct(c['recall_doc'])} | {pp(d['recall_doc'])} | "
            f"{pct(c['f1'])} | {pp(d['f1'])} | "
            f"{c['form_ok']}/{c['form_pages']} ({pct(c['form_accuracy'])}) | "
            f"{pp(d['form_accuracy'])} |")

    lines += ["", "## 2. Full-document Rave pair evaluation", "",
              "| Model | Precision | Δ | Recall | Δ | Matched / GT |",
              "|---|---:|---:|---:|---:|---:|"]
    for name in labels:
        rc = comparison[name]["rave_current"] or {}
        rb = comparison[name]["rave_baseline"] or {}
        lines.append(
            f"| {labels[name]} | {pct(rc.get('precision'))} | "
            f"{pp(difference(rc.get('precision'), rb.get('precision')))} | "
            f"{pct(rc.get('recall'))} | "
            f"{pp(difference(rc.get('recall'), rb.get('recall')))} | "
            f"{rc.get('matched', 0)} / {rc.get('gt_pairs', 0)} |")

    for section, name in enumerate(labels, 3):
        lines += ["", f"## {section}. {labels[name]} per-document results", "",
                  "| Document | Status | Precision | Δ | Page recall | Δ | Doc recall | Δ | Form | TP / FP / missed |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for doc, values in comparison[name]["documents"].items():
            c, d = values["current"], values["delta"]
            lines.append(
                f"| `{doc}` | {c['status']} | {pct(c['precision'])} | {pp(d['precision'])} | "
                f"{pct(c['recall_page'])} | {pp(d['recall_page'])} | "
                f"{pct(c['recall_doc'])} | {pp(d['recall_doc'])} | "
                f"{c['form_ok']}/{c['form_pages']} | "
                f"{c['tp']} / {c['fp']} / {c['missed']} |")

    if hybrid:
        lines += ["", "## 5. Targeted hybrid experiment", "",
                  "Triggered because GPT still had form-title failures after the "
                  "full run. Sonnet generated/revised the extractor; GPT performed "
                  "only grounded audit calls.",
                  "",
                  "| Document | Precision | Page recall | Doc recall | Form | TP / FP / missed |",
                  "|---|---:|---:|---:|---:|---:|"]
        for doc, c in hybrid.items():
            lines.append(
                f"| `{doc}` | {pct(c['precision'])} | {pct(c['recall_page'])} | "
                f"{pct(c['recall_doc'])} | {c['form_ok']}/{c['form_pages']} | "
                f"{c['tp']} / {c['fp']} / {c['missed']} |")

    lines += ["", "## 6. Runtime summary", "",
              "| Model | Documents | Versions | LLM calls | LLM time | Exported fields | Pages with fields | Final audit issues |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name in labels:
        r = comparison[name]["runtime"]
        lines.append(
            f"| {labels[name]} | {r['documents']} | {r['versions']} | "
            f"{r['llm_calls']} | {r['llm_s'] / 3600:.2f} h | {r['fields']} | "
            f"{r['pages_with_fields']} | {r['audit_issues']} |")

    lines += [
        "",
        "## 7. Changes evaluated",
        "",
        "- Same-page form-title persistence signal and revision warning.",
        "- Vocabulary-neutral, candidate-based title-context guidance.",
        "- Optional/model-neutral family-handler architecture.",
        "- Literal blocklist warning at 10 and hard rejection at 30, including named collections.",
        "- Size-scaled parser-version budget: +1 at 900 pages, capped at +2.",
        "- Existing title-context, coverage, audit rotation, and evidence-based junk safeguards.",
        "",
        "## 8. Interpretation and next actions",
        "",
        "### What worked",
        "",
        "- **GPT is now the strongest field extractor on the sampled benchmark:** "
        "80.3% precision, 82.7% page recall and 81.5% F1. Relative to the prior "
        "full run, precision rose 6.1 points, F1 rose 2.2 points and form accuracy "
        "rose from 35.3% to 77.2%.",
        "- **Sonnet form attribution is reliable:** 50/51 scored form pages (98.0%). "
        "Its page recall rose 10.9 points and F1 rose 4.1 points.",
        "- **The hybrid recovered both targeted title failures:** 326 improved from "
        "GPT's 0/10 forms to 10/10 with 96.3% page recall; the January aCRF scored "
        "2/2 forms with 92.6% page recall.",
        "- **The blocklist ceiling worked as a safety guard:** multiple later "
        "versions with 30-71 literal filters were rejected while earlier, less "
        "content-fitted versions remained eligible as best.",
        "",
        "### What remains broken or mixed",
        "",
        "- **GPT has a severe unsampled-page precision failure on the full Rave "
        "book.** Matched pairs stayed essentially flat (772 -> 773), but distinct "
        "extracted pairs doubled from 792 to 1,628, collapsing full-document "
        "precision from 97.5% to 47.5%. The 10-page sample scored 100% precision, "
        "so current audit sampling did not expose this over-extraction.",
        "- **The form-name persistence signal is necessary but insufficient.** "
        "GPT still scored 0/10 forms on the 489-page 326 book because repeated "
        "non-title annotations can satisfy same-page persistence. The 112-page "
        "326 book scored 10/10, so title behavior remains model/run sensitive.",
        "- **Sonnet traded precision for recall:** aggregate precision fell 4.3 "
        "points. The largest regressions were 326 v1.0 (53.6% precision) and "
        "384 v2.0 (29.7% precision); 384 v1.0 and v2.0 also lost substantial "
        "page recall.",
        "- **One Sonnet document remains non-usable as a complete extraction:** "
        "the 2021 331 book is `needs_manual_template` because one specialist pass "
        "failed. Its displayed accuracy is for the fresh partial export and the "
        "status is now explicit; it is not a production-success row.",
        "- **The large-document budget is mixed rather than proven.** GPT improved "
        "page recall by 10.7 points on both 331 books, while Sonnet improved one "
        "331 book and regressed on the other. Marginal v6 benefit must be measured "
        "from trails before retaining the extra call universally.",
        "- **GPT runtime is materially higher:** 5.21 LLM-hours versus Sonnet's "
        "1.32 LLM-hours for the same 11 documents.",
        "",
        "### Prioritized next todos (do not start automatically)",
        "",
        "1. **Add risk-targeted audit sampling for over-extraction.** Reserve audit "
        "slots for pages/families with unusually high unique-label density, option-"
        "like rows, or extraction density relative to sibling pages. This directly "
        "targets the Rave 1,628-pair failure that proportional sampling missed.",
        "2. **Replace persistence-only form validation with title-source support.** "
        "Measure whether emitted form names are supported by structurally prominent "
        "top-region candidates or a valid carried-forward candidate, while allowing "
        "document-wide invariant titles. Use this as revision evidence, not a "
        "vendor vocabulary rule.",
        "3. **Keep hybrid routing as a targeted fallback, not the global default.** "
        "Trigger Sonnet-generation/GPT-audit when grounded audits report wrong-form "
        "issues or title-source support is weak. GPT remains preferable for aggregate "
        "field F1; Sonnet remains preferable for form attribution.",
        "4. **Diagnose Sonnet's 384 regressions and GPT's Rave explosion from the "
        "accepted extractor/trail before changing global thresholds.** Classify "
        "false positives as wrapped-line splits, options, headers, or reference rows.",
        "5. **Measure marginal value of the sixth version on 900+ page books.** "
        "Retain scaling only where v6 becomes best or materially improves uncovered "
        "families; otherwise spend the call on an additional risk-targeted audit.",
        "6. **Promote parallel disjoint-document execution to a first-class runner.** "
        "Write one run manifest and atomically merge worker summaries so long GPT "
        "runs do not require terminal-log reconstruction.",
        "7. **Validate the selected fixes on additional unseen CRF books** before "
        "changing the production default model or hybrid policy.",
        "",
        "## 9. Artifacts",
        "",
        "- `accuracy_audit/scored.json`",
        "- `data/outputs/out/accuracy_audit_claude_4_5_sonnet.xlsx`",
        "- `data/outputs/out/accuracy_audit_gpt_5_2.xlsx`",
        "- `data/outputs/out/cli_induction_summary_claude_4_5_sonnet.json`",
        "- `data/outputs/out/cli_induction_summary_gpt_5_2.json`",
        "- `data/outputs/out/eval_comparison_backpocket_20260723.json`",
    ]
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {args.output}")
    print(f"wrote {args.json_output}")


if __name__ == "__main__":
    main()
