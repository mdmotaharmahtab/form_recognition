"""End-to-end generalization review of the pipeline by a fresh reviewer model.

Concatenates the pipeline source into one prompt and asks a reviewer (via the
Cursor CLI, default Opus medium thinking) to audit it for hardcoding, hidden
format/corpus priors, and generalization risks. The reviewer sees code only -
no repo access (empty sandbox cwd).

  python run_review.py [--model claude-opus-4-8-thinking-medium]
Writes out/pipeline_review_<model>.md
"""
import argparse
import os
import re

from common import OUT_DIR
from run_cli_induction import call_cli, find_agent, slug

HERE = os.path.dirname(os.path.abspath(__file__))

# (path, role) - role tells the reviewer what is production-intent vs harness
FILES = [
    ("common.py", "PRODUCTION-INTENT: page/Line model, PDF parsing, rep-page dumps (its five-signal fingerprint is the replaced v1, kept as reference)"),
    ("generic_profile.py", "PRODUCTION-INTENT: SHIPPED stage-0 clustering - typography tokens, per-document chrome damping, weighted-Jaccard leader clustering, per-document theta selection"),
    ("stage0_cluster.py", "PRODUCTION-INTENT: stage-0 driver (local variant; Dataiku notebook will mirror it)"),
    ("codegen.py", "PRODUCTION-INTENT: codegen prompt, executor parent side, cluster feedback, coverage confirm, grounded audit"),
    ("sandbox_runner.py", "PRODUCTION-INTENT: child process that executes generated code in a restricted namespace"),
    ("induction.py", "MIXED: score/gate_problems are PRODUCTION-INTENT; the recipe/engine-catalog prompt path is LEGACY comparison only"),
    ("replay.py", "LEGACY comparison path (engine catalog) - review only for anything the production path imports from it (FieldRec, ReplayResult)"),
    ("subagent_bridge.py", "LOCAL HARNESS: file-based bridge for manual/blind testing"),
    ("run_cli_induction.py", "MIXED: induce_document/finalize_document are the PRODUCTION loop controller (shared with the Dataiku notebook); the CLI transport/main are LOCAL HARNESS"),
    ("build_dataiku_notebook.py", "PRODUCTION-INTENT: generator emitting the Dataiku notebook - folder-code bootstrap, LLM Mesh transport, managed-folder IO under runs/<RUN_ID>/, per-document statuses; review the cell code it generates"),
    ("oid_mapping.py", "PRODUCTION-INTENT: downstream name->OID funnel - prod-aligned form scoping, in-form field gate, LLM ranker over every candidate (pick-or-refuse)"),
    ("run_report.py", "PRODUCTION-INTENT: stage-attributed error/event report derived post-hoc from trails + summary rows (traceability of where errors come from)"),
    ("cost_report.py", "LOCAL ANALYSIS: token/cost estimation over llm_calls_*.jsonl (tiktoken proxy; never runs in Dataiku)"),
    ("eval_form_field.py", "EVALUATION ONLY: ground-truth comparison + name->OID mapping experiment"),
    ("evaluate.py", "EVALUATION ONLY: legacy OID-scope evaluation"),
]

CHARTER = """You are reviewing a document-extraction pipeline for clinical CRF PDFs. Its core claim: GENERALITY. It must work on any CRF-like PDF form book with NO prior knowledge beyond "this is a CRF" - unlimited vendors, layouts, languages. Up to ~1000 pages per document; the only LLM calls allowed are: one program-synthesis call on 4-12 representative pages, a bounded revision loop, one coverage-confirmation round, one grounded audit round per version (with one reprompt on malformed/partial replies). Everything else is deterministic Python. Scope: extract (form_name, field_name) per data-entry field; machine codes/OIDs are resolved downstream and are OUT of extraction scope.

Architecture (intended production flow, to run in a Dataiku notebook via LLM Mesh):
 stage 0: cluster pages by structural layout profile (word-blind typography tokens,
          per-document chrome damping, weighted-Jaccard stacking, theta selected
          per document by stability), pick representatives (no LLM)
 stage 1: LLM writes extract(pages) Python from representative page dumps only
 gates:   mechanical, contract-level checks on the FULL-document run of that program
 loop:    failures -> revision prompt (metrics + per-cluster coverage + unseen sample
          pages from weak clusters); pass-but-uncovered-clusters -> one confirm round;
          pass -> grounded audit (sampled pages side-by-side with extracted records,
          model lists missed/false/wrong_form; one fix round, regression-guarded)
 output:  (form_name, field_name, page) records

REVIEW CHARTER - report in these sections, every item actionable with file/symbol refs:

1. HARDCODING & CORPUS PRIORS (the main concern): every constant, regex, threshold,
   prompt sentence, or heuristic that encodes knowledge of specific CRF vendors,
   the author's 11 sample documents, English/Latin text, or the local machine
   (paths, OS). For each: severity (blocker / should-fix / acceptable-with-comment),
   why it threatens generality, and a concrete fix. Judge PROMPT TEXT too.
2. BUGS: wrong logic, order-of-operations, off-by-one, exception swallowing,
   state leaks across documents/attempts.
3. LOGICAL FLOW: loop bounds, acceptance/regression rules, dead paths, cases where
   a bad program can be accepted or a good one rejected.
4. EDGE CASES vs the generality claim: scanned/no-text-layer PDFs, multi-column,
   RTL/CJK text, huge/tiny documents, PDFs where the fingerprint degenerates
   (all pages one cluster / every page unique), programs that return generators,
   unicode, empty pages, encrypted PDFs.
5. SANDBOX & SAFETY: escapes from the restricted exec namespace, resource abuse
   (memory/CPU), thread-timeout leaks, and whether restrictions could also block
   LEGITIMATE extraction programs.
6. CONSISTENCY: places where harness behavior diverges from the documented
   production intent (e.g. bridge vs run_cli_induction vs prompts).

Do NOT propose new features. Do NOT restyle code. Focus on the generality claim
and correctness. Be specific and terse; no praise.
"""


def build_prompt() -> str:
    parts = [CHARTER, "\n\n# PIPELINE SOURCE\n"]
    for name, role in FILES:
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            src = f.read()
        parts.append(f"\n---------- {name}  [{role}] ----------\n{src}")
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-opus-4-8-thinking-medium")
    args = ap.parse_args()
    prompt = build_prompt()
    print(f"review prompt: {len(prompt)} chars; calling {args.model} ...")
    reply = call_cli(find_agent(), args.model, prompt, timeout_s=1800)
    out_path = os.path.join(OUT_DIR, f"pipeline_review_{slug(args.model)}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(reply)
    print(f"review -> {out_path}\n")
    print(reply)


if __name__ == "__main__":
    main()
