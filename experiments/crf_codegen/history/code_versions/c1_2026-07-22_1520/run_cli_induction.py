"""Run the codegen induction loop against a REAL external model via the Cursor CLI.

This exists to validate the production model (Claude Sonnet 4.5) locally, before
the Dataiku notebook run. The CLI call is a plain chat completion: the prompt file
goes in on stdin, the reply comes out on stdout. The agent process runs in an
EMPTY sandbox directory outside the repo: its working dir exposes nothing. (A
print-mode agent does retain tool access to absolute paths, so the blind
property also rests on the prompt containing page dumps only - never repo or
artifact paths.)

Loop semantics (mirrors the intended Dataiku notebook). Every cycle produces ONE
parser version and ends with one comparable result:

  generate/revise -> full-document run + gates
                  -> [one-time coverage confirmation; an adopted extension is
                     scored as its OWN next version, after the pre-extension
                     program got its own trail entry and chance at best]
                  -> grounded audit on a page sample FIXED at the first audit
                  -> version_score = (hard problems, audit issues, warnings, -coverage)

Stopping (no phase-local budgets; one rule set for the whole loop):
  converged  gates pass, the audit finds zero issues, and the version is the new
             best -> accept immediately
  plateau    a version fails to strictly improve on the PREVIOUS one
             (diminishing returns; audit counts are compared on the same pages,
             and a version that loses >10% page coverage never counts as improved
             - neither for continuing the loop nor for best selection). Two
             CONSECUTIVE gate-failed versions never plateau: identical crash
             scores are not diminishing returns, they are zero returns - the
             revision loop keeps trying until the budget cap.
  budget     at most --max-versions cycles (default 5)
  error      transport/audit failure -> stop with what we have

A zero-issue audit is only TRUSTED when the reply actually covers every audited
page; a malformed or partial audit reply gets ONE reprompt before it counts as
failed/partial. Issue counts ignore pages outside the fixed sample. The BEST
version (not the last) is exported; if every version hard-failed the document is
flagged needs_manual_template. The controller is a small explicit state machine
on purpose - it maps 1:1 onto a LangGraph StateGraph (nodes: generate / validate
/ confirm / audit; conditional edges = the stop rules) if the Dataiku notebook
later wants checkpointing/tracing, with zero logic changes.

Usage:
  python run_cli_induction.py --model claude-4.5-sonnet [--only substring] [--max-versions 5]

Outputs per document (suffix keeps them separate from the parent-model runs):
  codegen_reply_<model>_<n>.py   raw model replies (one per version; an adopted
                                 coverage extension is also kept as _confirm.txt)
  codegen_trail_<model>.json     {stop_reason, versions, best_version, score_key,
                                 cycles}; an adopted extension appears as its own
                                 version right after the version it extends
  generated_extractor_<model>.py best accepted program
  fields_codegen_<model>.csv     full-document extraction
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile

from codegen import (AUDIT_NOT_RUN, audit_issues, audit_problem_lines,
                     build_audit_prompt, build_code_revision_prompt,
                     build_codegen_prompt, build_coverage_confirm_prompt,
                     improves, is_confirm_no_fields, parse_audit_reply,
                     run_extractor, validate_generated, version_score)
from common import OUT_DIR, doc_key, list_root_pdfs

DEFAULT_DOCS = [
    "384-201-00002_Annotated_Unique_CRF_04Nov2024",
    "QSC302573_Final_AnnotatedCRFs_16Oct2024-326-201-00007_1_",
    "MAC186_X11-201-00001_eCRF_v1.10_form_tracker_v1.6_06Mar2025",
]


def find_agent() -> str:
    for cand in (shutil.which("agent"),
                 os.path.join(os.environ.get("USERPROFILE", ""), ".local", "bin", "agent.exe"),
                 os.path.join(os.environ.get("USERPROFILE", ""), ".local", "bin", "agent")):
        if cand and os.path.exists(cand):
            return cand
    raise SystemExit("cursor CLI 'agent' not found on PATH or in ~/.local/bin")


def call_cli(agent_bin: str, model: str, prompt: str, timeout_s: int = 1200) -> str:
    sandbox = tempfile.mkdtemp(prefix="crf_llm_sandbox_")
    try:
        proc = subprocess.run(
            # --trust only trusts the EMPTY sandbox dir the process is started in
            [agent_bin, "-p", "--trust", "--model", model, "--output-format", "text"],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=timeout_s,
            cwd=sandbox,
        )
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"agent CLI exited {proc.returncode}: {err[:1500]}")
    if not out.strip():
        raise RuntimeError(f"agent CLI returned empty reply; stderr: {proc.stderr.decode('utf-8', 'replace')[:800]}")
    return out


def slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")


def doc_meta(outdir: str) -> dict:
    try:
        with open(os.path.join(outdir, "clusters.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):  # missing or corrupt stage-0 output
        return {"status": "missing_stage0"}


def doc_status(outdir: str) -> str:
    return doc_meta(outdir).get("status", "ok")


def save_reply(outdir: str, tag: str, name: str | int, reply: str, ext: str = "py") -> None:
    with open(os.path.join(outdir, f"codegen_reply_{tag}_{name}.{ext}"), "w", encoding="utf-8") as f:
        f.write(reply)


def jsonable_score(score: tuple) -> list:
    return ["not_audited" if s == AUDIT_NOT_RUN else s for s in score]


def coverage_of(verdict: dict) -> int:
    return (verdict.get("metrics") or {}).get("pages_with_fields", 0) or 0


def audit_page_num(v: dict) -> int | None:
    try:
        return int(v.get("page"))
    except (TypeError, ValueError):
        return None


def induce_document(call, model: str, tag: str, pdf: str, outdir: str,
                    initial_prompt: str, max_versions: int,
                    ) -> tuple[dict | None, list[dict], str, int]:
    """One document through the loop. Returns (best, trail, stop_reason, versions).

    `call` is the LLM transport: fn(prompt: str) -> reply str. The Cursor-CLI
    driver below and the Dataiku notebook (LLM Mesh) inject different transports
    around this SAME controller; `model` is a label for logs only.

    `best` is the best-scoring version so far (never the merely-latest one):
    {reply, verdict, score, version, audit_issues}. Plateau stopping compares
    CONSECUTIVE version scores; best selection additionally applies the
    coverage-regression guard in improves()."""
    trail: list[dict] = []
    best: dict | None = None
    prev: dict | None = None                # previous version's score/cov/had_problems
    audited_pages: list[int] | None = None  # fixed at the first audit forever
    confirm_pending = True                  # one coverage-confirm round per document
    prompt, kind = initial_prompt, "generate"
    versions, stop = 0, None

    def track(reply_, verdict_, score_, aud_):
        """Update best with a candidate version; returns whether it improved."""
        nonlocal best
        improved_ = improves(best["score"] if best else None, score_,
                             coverage_of(best["verdict"]) if best else 0,
                             coverage_of(verdict_))
        if improved_:
            best = {"reply": reply_, "verdict": verdict_, "score": score_,
                    "version": versions, "audit_issues": aud_}
        return improved_

    while stop is None:
        if versions >= max_versions:
            stop = "budget"
            break
        versions += 1
        print(f"    v{versions} [{kind}]: calling {model} ...", flush=True)
        try:
            reply = call(prompt)
        except Exception as e:  # noqa: BLE001
            trail.append({"version": versions, "kind": kind, "transport_error": str(e)})
            print(f"    transport error: {e}")
            stop = "transport_error"
            break
        save_reply(outdir, tag, versions, reply)
        verdict = validate_generated(pdf, reply, outdir)

        # ---- one-shot coverage confirmation, folded into this cycle ----------
        # The model either confirms the uncovered layouts are field-free or
        # extends its program. An adopted extension becomes a NEW version (it
        # costs budget) and is the program audited below - but the
        # PRE-extension version is scored and recorded FIRST: adoption only
        # checks record/coverage monotonicity, so an extension that is worse
        # on warnings must not silently erase a better program's claim to best.
        if (confirm_pending and not verdict["problems"] and verdict["cluster_feedback"]
                and versions < max_versions):
            confirm_pending = False
            wk = [(w["cluster"], w["n_pages"]) for w in verdict["weak_clusters"]]
            print(f"    coverage confirmation (uncovered: {wk or 'doc-wide holes'}) ...", flush=True)
            try:
                reply2 = call(build_coverage_confirm_prompt(verdict))
                save_reply(outdir, tag, "confirm", reply2, ext="txt")
                if is_confirm_no_fields(reply2):
                    trail.append({"version": versions, "kind": "confirm",
                                  "outcome": "confirmed_no_fields"})
                    print("    model confirmed uncovered clusters are field-free")
                else:
                    verdict2 = validate_generated(pdf, reply2, outdir)
                    # an extension may only ADD layouts: record count and page
                    # coverage must both hold (records alone can grow while whole
                    # covered layouts are dropped)
                    grew = (not verdict2["problems"]
                            and verdict2["metrics"].get("records", 0)
                            >= verdict["metrics"].get("records", 0)
                            and coverage_of(verdict2) >= coverage_of(verdict))
                    trail.append({"version": versions, "kind": "confirm",
                                  "metrics": verdict2["metrics"],
                                  "problems": verdict2["problems"],
                                  "outcome": "extended_program" if grew else "extension_rejected"})
                    if grew:
                        # close out the pre-extension version: own trail entry,
                        # own shot at best (un-audited -> AUDIT_NOT_RUN score)
                        orig_score = version_score(verdict, None)
                        orig_improved = track(reply, verdict, orig_score, None)
                        trail.append({"version": versions, "kind": kind,
                                      "metrics": verdict["metrics"],
                                      "problems": verdict["problems"],
                                      "warnings": verdict["warnings"],
                                      "audit_issues": None, "audit_pages": None,
                                      "audit_verdicts": None,
                                      "score": jsonable_score(orig_score),
                                      "became_best": orig_improved})
                        prev = {"score": orig_score, "cov": coverage_of(verdict),
                                "had_problems": False}
                        versions += 1
                        save_reply(outdir, tag, versions, reply2)
                        reply, verdict, kind = reply2, verdict2, "confirm_extension"
                        print(f"    extended program adopted as v{versions}: "
                              f"{json.dumps(verdict2['metrics'])}")
                    else:
                        print("    extension rejected (regression or gate failure); keeping current")
            except Exception as e:  # noqa: BLE001
                trail.append({"version": versions, "kind": "confirm", "transport_error": str(e)})
                print(f"    confirmation transport error: {e}")

        # ---- grounded audit (page sample fixed at the first audit) -----------
        # aud_count semantics: None = this version was NOT verified against pages
        # (no auditable pages / reply didn't cover the sample / audit errored).
        # None scores AUDIT_NOT_RUN, so an unverified version can never converge.
        # A malformed or page-skipping reply gets ONE reprompt before giving up:
        # a single bad completion must not end the whole document.
        aud_count, audit_verdicts, audit_partial = None, [], False
        if not verdict["problems"] and verdict.get("result"):
            try:
                aprompt, apages = build_audit_prompt(pdf, outdir, verdict["result"],
                                                     pages=audited_pages)
                if apages:
                    if audited_pages is None:
                        audited_pages = apages
                    sample = set(audited_pages)
                    for audit_try in (1, 2):
                        areply = call(aprompt)
                        try:
                            # only the fixed sample counts - issues reported for
                            # other pages would make version scores incomparable
                            audit_verdicts = [v for v in parse_audit_reply(areply)
                                              if audit_page_num(v) in sample]
                        except ValueError:
                            if audit_try == 1:
                                aprompt += ("\n\nYour previous reply contained no valid "
                                            "JSON array. Reply again with ONLY the JSON "
                                            "array described above, one object per "
                                            "audited page.")
                                continue
                            raise
                        if {audit_page_num(v) for v in audit_verdicts} == sample:
                            break
                        if audit_try == 1:
                            aprompt += ("\n\nYour previous reply skipped some audited "
                                        "pages. Reply again with ONLY the JSON array, "
                                        "exactly one object per page, for pages "
                                        + ", ".join(str(p) for p in audited_pages) + ".")
                    aud_count = audit_issues(audit_verdicts)
                    if {audit_page_num(v) for v in audit_verdicts} != sample:
                        audit_partial = True
                        if aud_count == 0:
                            aud_count = None  # zero by omission is not a clean audit
                            print(f"    audit reply skipped some of pages {audited_pages}; "
                                  "zero-issue count not trusted")
                        else:  # a partial nonzero count UNDERCOUNTS; keep it (it
                            # still drives the revision) but flag it in the trail
                            print(f"    audit: {aud_count} issue(s) on a PARTIAL reply "
                                  f"(pages {audited_pages})")
                    else:
                        print(f"    audit: {aud_count} issue(s) on pages {audited_pages}")
            except Exception as e:  # noqa: BLE001
                trail.append({"version": versions, "kind": "audit", "transport_error": str(e)})
                print(f"    audit error: {e}")
                stop = "audit_error"  # score this version un-audited, then stop

        # ---- score, track best, decide ---------------------------------------
        cand_score, cand_cov = version_score(verdict, aud_count), coverage_of(verdict)
        improved = track(reply, verdict, cand_score, aud_count)
        trail.append({"version": versions, "kind": kind,
                      "metrics": verdict["metrics"], "problems": verdict["problems"],
                      "warnings": verdict["warnings"], "audit_issues": aud_count,
                      "audit_pages": audited_pages if aud_count is not None else None,
                      "audit_partial": audit_partial or None,
                      "audit_verdicts": audit_verdicts or None,
                      "score": jsonable_score(cand_score), "became_best": improved})
        if verdict["problems"]:
            print(f"    problems: {verdict['problems']}")
        elif verdict["warnings"]:
            print(f"    warnings: {verdict['warnings']}")

        if stop:  # audit failed mid-cycle; version already scored and recorded
            break
        if not verdict["problems"] and aud_count == 0 and improved:
            # verified clean AND the new best - nothing left to iterate on.
            # (clean but NOT improved = it got there by dropping coverage; the
            # plateau rule below stops the loop and the earlier best is exported)
            stop = "converged"
            break
        if (prev is not None
                and not (prev["had_problems"] and bool(verdict["problems"]))
                and not improves(prev["score"], cand_score, prev["cov"], cand_cov)):
            # two consecutive GATE-FAILED versions are exempt: identical crash
            # scores are zero returns, not diminishing returns - keep revising
            # until the budget cap instead of giving up at version 2
            stop = "plateau"  # diminishing returns across two consecutive versions
            break
        prev = {"score": cand_score, "cov": cand_cov,
                "had_problems": bool(verdict["problems"])}

        # ---- next revision prompt --------------------------------------------
        if verdict["problems"]:
            prompt, kind = build_code_revision_prompt(verdict), "revise_gates"
        else:
            prompt = build_code_revision_prompt({
                "source": verdict["source"],
                "metrics": verdict["metrics"],
                "sample": verdict["sample"],
                "problems": ["(aggregate gates passed; a page-level audit of the document "
                             "found the issues below)"] + audit_problem_lines(audit_verdicts),
                "warnings": verdict["warnings"],
                "cluster_feedback": "",
            })
            kind = "revise_audit"

    return best, trail, stop or "budget", versions


def finalize_document(key: str, pdf: str, outdir: str, tag: str,
                      best: dict | None, trail: list[dict], stop_reason: str,
                      versions: int) -> dict:
    """Persist the trail, export the best program + full-document CSV, and build
    the summary row. Shared verbatim by this CLI driver and the Dataiku notebook."""
    with open(os.path.join(outdir, f"codegen_trail_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump({"stop_reason": stop_reason, "versions": versions,
                   "best_version": best["version"] if best else None,
                   "score_key": ["gate_problems", "audit_issues",
                                 "warnings", "neg_pages_with_fields"],
                   "cycles": trail}, f, indent=1)

    row = {"doc": key, "versions": versions, "stop_reason": stop_reason}
    usable = best is not None and not best["verdict"]["problems"]
    if not usable:
        row["status"] = "needs_manual_template"
        return row

    verdict, aud = best["verdict"], best["audit_issues"]
    if aud is None:
        row["status"] = "ok_unaudited"     # never page-verified (audit error)
    elif aud > 0:
        row["status"] = "ok_audit_issues"  # best still has known page issues
    elif verdict["warnings"]:
        row["status"] = "ok_with_warnings"
    else:
        row["status"] = "ok"
    row["best_version"] = best["version"]
    source = verdict["source"]
    with open(os.path.join(outdir, f"generated_extractor_{tag}.py"), "w", encoding="utf-8") as f:
        f.write(source + "\n")
    try:
        full = run_extractor(source, pdf)
    except Exception as e:  # noqa: BLE001 - a flaky final replay must not
        row["status"] = "export_failed"    # abort the remaining documents
        row["error"] = str(e)
        return row
    with open(os.path.join(outdir, f"fields_codegen_{tag}.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["form_name", "field_name", "page"])
        for r in full.records:
            w.writerow([r.form_name, r.field_name, r.page])
    row.update(fields=len(full.records),
               forms=len({r.form_name for r in full.records if r.form_name}),
               pages_with_fields=full.pages_with_fields,
               audit_issues=best["audit_issues"],
               warnings=verdict.get("warnings", []))
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--only", help="substring filter on doc key")
    ap.add_argument("--all-docs", action="store_true", help="run every doc, not just the default 3")
    ap.add_argument("--max-versions", type=int, default=5,
                    help="hard cap on parser versions per document (loop also stops "
                         "earlier on convergence or plateau)")
    args = ap.parse_args()
    if args.max_versions < 1:
        ap.error("--max-versions must be >= 1")
    agent_bin = find_agent()
    tag = slug(args.model)

    all_pdfs = list_root_pdfs()
    pdfs = {doc_key(p): p for p in all_pdfs}
    if len(pdfs) != len(all_pdfs):  # a collision would silently drop a document
        raise SystemExit("doc_key collision among input PDFs (near-identical names) "
                         "- rename the colliding files")
    docs = sorted(pdfs) if args.all_docs else [d for d in DEFAULT_DOCS if d in pdfs]
    if args.only:
        docs = [d for d in docs if args.only.lower() in d.lower()]

    summary = []
    for key in docs:
        pdf = pdfs[key]
        outdir = os.path.join(OUT_DIR, key)
        print(f"=== {key}")
        try:  # one bad document must not sink a multi-hour paid batch
            meta = doc_meta(outdir)
            status = meta.get("status", "ok")
            if status != "ok":
                # encrypted / scanned / zero-page / stage0 not run: no LLM budget spent
                summary.append({"doc": key, "status": f"skipped_{status}"})
                print(f"    skipped: {status}")
                continue
            # build the prompt fresh from the CURRENT stage-0 artifacts (and keep
            # a copy for inspection) - reading a pre-existing codegen_prompt.txt
            # would silently reuse stale rep dumps after a stage-0 rerun
            initial_prompt = build_codegen_prompt(pdf, outdir)
            with open(os.path.join(outdir, "codegen_prompt.txt"), "w", encoding="utf-8") as f:
                f.write(initial_prompt)

            transport = lambda prompt: call_cli(agent_bin, args.model, prompt)  # noqa: E731
            best, trail, stop_reason, versions = induce_document(
                transport, args.model, tag, pdf, outdir, initial_prompt, args.max_versions)
            row = finalize_document(key, pdf, outdir, tag, best, trail, stop_reason, versions)
            if meta.get("text_layer_pct", 100) < 100:
                # partially scanned book: those pages are unreachable by design
                row["text_layer_pct"] = meta["text_layer_pct"]
        except Exception as e:  # noqa: BLE001
            row = {"doc": key, "status": "error", "error": repr(e)}
        summary.append(row)
        print(f"    -> {row}")

    with open(os.path.join(OUT_DIR, f"cli_induction_summary_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
