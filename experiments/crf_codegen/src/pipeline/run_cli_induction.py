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
                  -> grounded audit: a CORE page sample fixed at the first
                     audit (size-scaled, 6-12 pages) re-audited every round,
                     plus ROTATING exploration slots (never-audited pages
                     first, cluster-stratified, uncovered-weighted); a rotating
                     page that produces issues is PROMOTED into the core
                  -> version_score = (hard problems, audit issues, warnings, -coverage)

Stopping (no phase-local budgets; one rule set for the whole loop):
  converged  gates pass, the audit finds zero issues over the whole sample
             (core + fresh rotation pages), and the version is the new
             best -> accept immediately
  plateau    TWO CONSECUTIVE versions fail to strictly improve on their
             predecessor (diminishing returns over two runs; audit counts are
             re-based onto the SHARED audited pages before comparing - the
             core is always shared - and a version that retains <90% of
             the previously covered PAGE SET never counts as improved -
             neither for continuing the loop nor for best selection, and
             swapping which pages are covered counts as losing them; the one
             exception is the junk-coverage carve-out in codegen.improves).
             A single non-improvement is allowed:
             audit issue counts come from a small page sample, so one noisy
             count must not end the document. Two CONSECUTIVE gate-failed
             versions never plateau either: identical crash scores are not
             diminishing returns, they are zero returns - the revision loop
             keeps trying until the budget cap.
  budget     at most --max-versions cycles (default 5), plus the bounded
             size allowance documented by scaled_version_budget for 900+ pages
  error      transport/audit failure -> stop with what we have

A zero-issue audit is only TRUSTED when the reply actually covers every audited
page; a malformed or partial audit reply gets ONE reprompt before it counts as
failed/partial. Issue counts ignore pages outside the round's sample. The BEST
version (not the last) is exported; if every version hard-failed the document is
flagged needs_manual_template. The controller is a small explicit state machine
on purpose - it maps 1:1 onto a LangGraph StateGraph (nodes: generate / validate
/ confirm / audit; conditional edges = the stop rules) if the Dataiku notebook
later wants checkpointing/tracing, with zero logic changes.

Multi-pass (run_document): when stage 0 finds far more layout families than one
prompt's representative budget can show, the clusters are split across several
independent induction passes (codegen.plan_passes; splitting is deliberately
rare - small tails fold into the single pass). Pass 1 is a GENERALIST whose
prompts are identical to a single-pass run; tail passes are specialists whose
prompts carry a harness-descriptive note. Each pass runs this same controller
restricted to its clusters' pages (prompts show that pass's reps,
gates/audits/coverage judge its pages only, artifacts carry a _passN tag
suffix) and the per-pass outputs merge into the document-level CSV/trail/row.

Usage:
  python run_cli_induction.py --model claude-4.5-sonnet [--only substring] [--max-versions 5]
                              [--audit-model gpt-5.2]
  (all staged PDFs run by default; --only/--skip narrow the set)

Outputs per document (suffix keeps them separate from the parent-model runs):
  codegen_reply_<model>_<n>.py   raw model replies (one per version; an adopted
                                 coverage extension is also kept as _confirm.txt)
  codegen_trail_<model>.json     {stop_reason, versions, best_version, score_key,
                                 cycles}; an adopted extension appears as its own
                                 version right after the version it extends
  generated_extractor_<model>.py best accepted program
  fields_codegen_<model>.csv     full-document extraction
  llm_calls_<model>.jsonl        every LLM call verbatim: {seq, kind, version, s,
                                 prompt_chars, reply_chars, prompt, reply} - the
                                 traceability + token/cost record (cost_report.py)
  timings_<model>.json           per-document profile: stage0_s, llm time by call
                                 kind, sandbox time, export_s, total_s

Run-root outputs:
  cli_induction_summary_<model>.json  one row per document (now incl. elapsed_s,
                                      llm_s, llm_calls, stage0_s)
  cli_error_events_<model>.csv        stage-attributed error/event log (run_report)
  cli_error_summary_<model>.json      event counts by stage / code / severity
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

import run_report
from codegen import (AUDIT_NOT_RUN, COVERAGE_FLOOR_UNCOVERED_PCT,
                     FIELD_FREE_CLAIM_MAX_UNCOVERED_PCT,
                     SPECIALIST_LOOP_NOTE, SPECIALIST_NOTE,
                     audit_problem_lines, build_audit_prompt,
                     build_code_revision_prompt, build_codegen_prompt,
                     build_coverage_confirm_prompt, forgivable_junk_pages,
                     improves, is_confirm_no_fields, mask_result,
                     parse_audit_reply, pick_rotation_pages, plan_passes,
                     run_extractor, validate_generated, version_score)
from common import ART_BUCKETS, OUT_DIR, art, art_bucket_dir, doc_key, list_root_pdfs


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


def is_audit_prompt(prompt: str) -> bool:
    """Whether a controller prompt is a grounded audit (including retries)."""
    return prompt.lstrip().startswith(
        "You are auditing the output of a deterministic extraction program")


def slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")


def run_tag(model: str, audit_model: str | None = None) -> str:
    """Stable artifact tag; preserve historical single-model tags.

    Hybrid tags encode each component separately and add a digest of the raw
    pair so lossy slug normalization cannot make distinct model IDs collide.
    """
    if not audit_model:
        return slug(model)
    digest = hashlib.sha256(
        f"{model}\0{audit_model}".encode("utf-8")).hexdigest()[:8]
    return f"{slug(model)}__audit__{slug(audit_model)}__{digest}"


def doc_meta(outdir: str) -> dict:
    try:
        with open(art(outdir, "clusters.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):  # missing or corrupt stage-0 output
        return {"status": "missing_stage0"}


def doc_status(outdir: str) -> str:
    return doc_meta(outdir).get("status", "ok")


def save_reply(outdir: str, tag: str, name: str | int, reply: str, ext: str = "py") -> None:
    with open(art(outdir, f"codegen_reply_{tag}_{name}.{ext}", True), "w", encoding="utf-8") as f:
        f.write(reply)


def jsonable_score(score: tuple) -> list:
    return ["not_audited" if s == AUDIT_NOT_RUN else s for s in score]


def coverage_of(verdict: dict) -> set:
    """Covered page set (0-based) of a version. Prefers the replay result's
    actual page set (what the improves() retention guard needs); falls back to
    a synthetic 0..n-1 range when the result object carries no covered_pages
    (test doubles), which degrades the guard to the old count comparison."""
    r = verdict.get("result")
    pages = getattr(r, "covered_pages", None) if r is not None else None
    if pages:
        return set(pages)
    n = (verdict.get("metrics") or {}).get("pages_with_fields", 0) or 0
    return set(range(int(n)))


def audit_page_num(v: dict) -> int | None:
    try:
        return int(v.get("page"))
    except (TypeError, ValueError):
        return None


def induce_document(call, model: str, tag: str, pdf: str, outdir: str,
                    initial_prompt: str, max_versions: int,
                    profile: dict | None = None, scope: dict | None = None,
                    ) -> tuple[dict | None, list[dict], str, int]:
    """One document (or one specialist pass) through the loop.
    Returns (best, trail, stop_reason, versions).

    `call` is the LLM transport: fn(prompt: str) -> reply str. The Cursor-CLI
    driver below and the Dataiku notebook (LLM Mesh) inject different transports
    around this SAME controller; `model` is a label for logs only.

    `scope` (multi-pass, optional): {"pages": 0-based page set, "clusters":
    cluster-index set, "main": bool}. Validation masks the replay to the scope
    and audits sample only scope pages; None = whole document (the ordinary
    path, byte-identical behavior). main=True marks the generalist pass 1: no
    specialist notes in its prompts and no volume-gate softening.

    `profile` (optional, mutated in place) collects wall-time instrumentation:
    every LLM call as {seq, kind, version, s, prompt_chars, reply_chars} plus
    accumulated sandbox time. The full prompt/reply text of every call is
    additionally appended to llm_calls_<tag>.jsonl in outdir - the traceability
    record cost_report.py tokenizes locally. Instrumentation never fails the
    run: an unwritable outdir (synthetic test dirs) disables the JSONL log.

    `best` is the best-scoring version so far (never the merely-latest one):
    {reply, verdict, score, version, audit_issues, audit_map}. Plateau stopping
    compares CONSECUTIVE version scores; best selection additionally applies
    the coverage-regression guard in improves(). audit_map ({page: issues} of
    the version's audited sample) lets improves() re-base audit counts onto
    shared pages when rotation makes two versions' samples differ."""
    trail: list[dict] = []
    best: dict | None = None
    prev: dict | None = None            # previous version's score/cov/map/had_problems
    core_pages: list[int] | None = None  # fixed at the first audit; grows by promotion
    rot_slots, max_sample = 0, 0        # set once core_pages is known
    audit_history: set[int] = set()     # every page audited so far (rotation memory)
    confirm_pending = True              # one coverage-confirm round per document
    field_free_confirmed = False        # model verified uncovered layouts hold no
    #                                     fields -> the coverage floor stands down
    stalls = 0                          # consecutive versions with no improvement
    prompt, kind = initial_prompt, "generate"
    versions, stop = 0, None
    # stateless transports: every revision/confirm prompt of a TAIL-SPECIALIST
    # pass must restate that its metrics are scope-restricted, or from v2
    # onward the model cannot interpret the numbers. The MAIN pass gets no
    # note: its prompts stay identical to a single-pass run (ownership framing
    # made models write narrow parsers - the v1 multi-pass coverage collapse).
    snote = (SPECIALIST_LOOP_NOTE
             if scope is not None and not scope.get("main") else "")

    prof = profile if profile is not None else {}
    prof.setdefault("llm_calls", [])
    prof.setdefault("sandbox_validate_s", 0.0)
    prof.setdefault("sandbox_validate_calls", 0)
    calls_path = art(outdir, f"llm_calls_{tag}.jsonl", True)
    try:
        open(calls_path, "w", encoding="utf-8").close()  # fresh log per document run
    except OSError:
        calls_path = None

    def timed_call(prompt_: str, kind_: str) -> str:
        """The transport, timed + logged. Failed calls are recorded too (with
        `error` and no reply) before the exception propagates to the caller's
        existing handling."""
        reply_, err, t0 = None, None, time.perf_counter()
        try:
            reply_ = call(prompt_)
            return reply_
        except Exception as e:
            err = e
            raise
        finally:
            entry = {"seq": len(prof["llm_calls"]) + 1, "kind": kind_,
                     "version": versions, "s": round(time.perf_counter() - t0, 3),
                     "prompt_chars": len(prompt_),
                     "reply_chars": len(reply_) if reply_ is not None else 0}
            if err is not None:
                entry["error"] = str(err)
            prof["llm_calls"].append(entry)
            if calls_path:
                try:
                    with open(calls_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({**entry, "prompt": prompt_,
                                            "reply": reply_},
                                           ensure_ascii=False) + "\n")
                except OSError:
                    pass  # profiling must never fail the run

    def timed_validate(reply_: str) -> dict:
        # resolves validate_generated at call time on purpose: the stop-policy
        # test harness monkeypatches the module global
        t0 = time.perf_counter()
        try:
            return validate_generated(pdf, reply_, outdir, scope=scope)
        finally:
            prof["sandbox_validate_s"] = round(
                prof["sandbox_validate_s"] + time.perf_counter() - t0, 3)
            prof["sandbox_validate_calls"] += 1

    # every value the page-grounded audit flagged as a false extraction, plus
    # doc-wide furniture candidates - the EVIDENCE that lets the coverage
    # guard's junk carve-out forgive pages whose only records were junk
    # (codegen.forgivable_junk_pages). Accumulated across this whole pass: junk
    # flagged while auditing v2 is what justifies v3's cleanup. Deliberately
    # NOT shared across multi-pass specialists: each pass has its own program
    # lineage and masked coverage, so evidence about what pass 1's program
    # stamped says nothing about pass 2's records - a pass re-earns its flags
    # from its own audits (costs at most delayed forgiveness, never wrong
    # forgiveness).
    junk_evidence: set = set()

    def forgiven(old_verdict, old_cov, new_cov):
        """Verified junk-only pages among those a candidate stops covering."""
        lost_ = set(old_cov or ()) - set(new_cov or ())
        if not (lost_ and old_verdict):
            return ()
        return forgivable_junk_pages(old_verdict.get("result"), lost_, junk_evidence)

    last_forgiven: list = []  # 1-based pages the carve-out released, per track()

    def track(reply_, verdict_, score_, aud_, amap_=None):
        """Update best with a candidate version; returns whether it improved."""
        nonlocal best, last_forgiven
        last_forgiven = []
        best_cov_ = set(coverage_of(best["verdict"])) if best else set()
        cand_cov_ = coverage_of(verdict_)
        forgivable = forgiven(best["verdict"], best_cov_, cand_cov_) if best else ()
        improved_ = improves(best["score"] if best else None, score_,
                             best_cov_, cand_cov_,
                             best_issue_pages=best.get("audit_map") if best else None,
                             cand_issue_pages=amap_, forgivable=forgivable)
        lost_ = best_cov_ - set(cand_cov_)
        if improved_ and forgivable and len(lost_) > 0.1 * len(best_cov_):
            # the retention veto (cov_floor=0.9) engaged and was lifted: every
            # lost page was verified junk-only. Surface it - a forgiven drop
            # must be distinguishable from an ordinary improvement post-hoc.
            last_forgiven = sorted(p + 1 for p in lost_)
            print(f"    coverage drop forgiven: {len(lost_)} page(s) verified "
                  "junk-only released")
        if improved_:
            best = {"reply": reply_, "verdict": verdict_, "score": score_,
                    "version": versions, "audit_issues": aud_, "audit_map": amap_}
        return improved_

    while stop is None:
        if versions >= max_versions:
            stop = "budget"
            break
        versions += 1
        print(f"    v{versions} [{kind}]: calling {model} ...", flush=True)
        try:
            reply = timed_call(prompt, kind)
        except Exception as e:  # noqa: BLE001
            trail.append({"version": versions, "kind": kind, "transport_error": str(e)})
            print(f"    transport error: {e}")
            stop = "transport_error"
            break
        save_reply(outdir, tag, versions, reply)
        verdict = timed_validate(reply)

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
                reply2 = timed_call(build_coverage_confirm_prompt(verdict, scope_note=snote),
                                    "confirm")
                save_reply(outdir, tag, "confirm", reply2, ext="txt")
                if is_confirm_no_fields(reply2):
                    # The claim keeps the program as-is, so it also stands the
                    # coverage floor down - but only while it is believable. Once
                    # the program is reading almost none of the document's
                    # content-bearing pages, "all the rest is field-free" is the
                    # excuse a title-gated program would use to dodge the floor,
                    # so we record the claim and leave the floor armed.
                    _ucp = verdict["metrics"].get("uncovered_content_pct")
                    credible = (_ucp is None
                                or _ucp <= FIELD_FREE_CLAIM_MAX_UNCOVERED_PCT)
                    field_free_confirmed = credible
                    trail.append({"version": versions, "kind": "confirm",
                                  "outcome": "confirmed_no_fields" if credible
                                  else "confirmed_no_fields_not_credible",
                                  "uncovered_content_pct": _ucp})
                    if credible:
                        print("    model confirmed uncovered clusters are field-free")
                    else:
                        print(f"    field-free claim not credible at {_ucp}% of "
                              "content pages empty; coverage floor stays armed")
                else:
                    verdict2 = timed_validate(reply2)
                    # an extension may only ADD layouts: record count must not
                    # drop, and the new covered PAGE SET must contain the old
                    # one (>= on sets = superset). Records alone can grow while
                    # whole covered layouts are dropped, and a count comparison
                    # would even accept swapping which pages are covered.
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
                                      "forgiven_pages": last_forgiven or None,
                                      "score": jsonable_score(orig_score),
                                      "became_best": orig_improved})
                        prev = {"score": orig_score, "cov": coverage_of(verdict),
                                "amap": None, "verdict": verdict,
                                "had_problems": False}
                        # the scoring section only ingests the SURVIVING
                        # verdict's furniture; collect the pre-extension one
                        # here or its evidence is lost with the swap below
                        junk_evidence.update(
                            str(x) for x in
                            (verdict["metrics"].get("furniture_candidates") or ()))
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

        # ---- coverage floor --------------------------------------------------
        # A MAIN-pass program that leaves most content-bearing pages empty has
        # over-gated: it keyed whole pages on one fixed cue (a font size, a
        # y-position, a specific wording) that many real pages lack. Make that a
        # hard PROBLEM so it cannot converge or claim best on a clean audit
        # alone; the gate revision then tells the model to stop skipping pages
        # for want of a title. It fires only AFTER the confirmation round (so the
        # model keeps its one chance to declare the layouts field-free), never
        # once field-free is confirmed, and never on tail-specialist scopes
        # (which keep the softened-gate philosophy).
        is_main_pass = scope is None or scope.get("main", True)
        ucp = verdict["metrics"].get("uncovered_content_pct")
        if (is_main_pass and not field_free_confirmed and not verdict["problems"]
                and ucp is not None and ucp > COVERAGE_FLOOR_UNCOVERED_PCT):
            ccp = verdict["metrics"].get("content_covered_pct")
            verdict["problems"].append(
                f"Coverage floor: only {ccp}% of content-bearing pages produced "
                f"any records ({ucp}% left empty). A page that carries data-entry "
                "fields must yield them even when its title/header is absent, in "
                "smaller text, or placed differently. Do not gate an entire page "
                "on a single fixed cue (one font size, one y-position, one "
                "wording); read the form/section name where it exists but never "
                "skip a page for lacking it.")
            print(f"    coverage floor tripped: {ccp}% content pages covered "
                  f"({ucp}% empty > {COVERAGE_FLOOR_UNCOVERED_PCT}% floor)")

        # ---- grounded audit (fixed core + rotating exploration slots) --------
        # aud_count semantics: None = this version was NOT verified against pages
        # (no auditable pages / reply didn't cover the sample / audit errored).
        # None scores AUDIT_NOT_RUN, so an unverified version can never converge.
        # A malformed or page-skipping reply gets ONE reprompt before giving up:
        # a single bad completion must not end the whole document.
        aud_count, audit_verdicts, audit_partial = None, [], False
        cand_map: dict | None = None    # {page: issues} over this round's sample
        promoted: list[int] = []        # rotation pages promoted into the core
        sample_list: list[int] = []
        if not verdict["problems"] and verdict.get("result"):
            try:
                if core_pages is None:
                    # first audit: the size-scaled doc-wide pick becomes the CORE,
                    # re-audited every round (the comparability anchor)
                    aprompt, apages = build_audit_prompt(pdf, outdir, verdict["result"],
                                                         pages=None, scope=scope)
                    core_pages = list(apages)
                    rot_slots = max(1, len(core_pages) // 3) if core_pages else 0
                    max_sample = len(core_pages) + rot_slots
                    sample_list = list(apages)
                else:
                    rot = pick_rotation_pages(outdir, verdict["result"], core_pages,
                                              audit_history,
                                              max_sample - len(core_pages),
                                              salt=versions, scope=scope)
                    sample_list = sorted(set(core_pages) | set(rot))
                    aprompt, apages = build_audit_prompt(pdf, outdir, verdict["result"],
                                                         pages=sample_list, scope=scope)
                if apages:
                    sample = set(sample_list)
                    for audit_try in (1, 2):
                        areply = timed_call(aprompt, "audit")
                        try:
                            # only this round's sample counts - issues reported for
                            # other pages would corrupt the per-page issue map
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
                                        + ", ".join(str(p) for p in sample_list) + ".")
                    # rotation memory records pages the reply actually covered,
                    # not the request: a skipped page keeps 'never audited'
                    # priority for future rotation rounds
                    audit_history |= {audit_page_num(v) for v in audit_verdicts}
                    for v in audit_verdicts:  # junk evidence for the carve-out
                        junk_evidence.update(str(x) for x in (v.get("false") or ()))
                    # aggregate per page FIRST (a reply may emit several objects
                    # for one page), then derive the total from the same map -
                    # convergence, promotion and improves() re-basing must all
                    # see one consistent set of numbers
                    cand_map = {}
                    for v in audit_verdicts:
                        pg = audit_page_num(v)
                        n_issues = (len(v.get("missed") or []) + len(v.get("false") or [])
                                    + len(v.get("wrong_form") or []))
                        cand_map[pg] = cand_map.get(pg, 0) + n_issues
                    aud_count = sum(cand_map.values())
                    if {audit_page_num(v) for v in audit_verdicts} != sample:
                        audit_partial = True
                        if aud_count == 0:
                            aud_count, cand_map = None, None  # zero by omission is
                            print(f"    audit reply skipped some of pages {sample_list}; "
                                  "zero-issue count not trusted")  # not a clean audit
                        else:  # a partial nonzero count UNDERCOUNTS; keep it (it
                            # still drives the revision) but flag it in the trail
                            print(f"    audit: {aud_count} issue(s) on a PARTIAL reply "
                                  f"(pages {sample_list})")
                    else:
                        print(f"    audit: {aud_count} issue(s) on pages {sample_list}")
                    # promotion: a rotating page that produced issues joins the
                    # core - it gets re-checked every remaining round. Bounded:
                    # the core never eats the last rotation slot.
                    if cand_map:
                        in_core = set(core_pages)
                        for p in sorted(cand_map):
                            if (cand_map[p] > 0 and p not in in_core
                                    and len(core_pages) < max_sample - 1):
                                core_pages.append(p)
                                in_core.add(p)
                                promoted.append(p)
                        if promoted:
                            core_pages.sort()
                            print(f"    audit core grew by {promoted} "
                                  f"(now {len(core_pages)} pages)")
            except Exception as e:  # noqa: BLE001
                trail.append({"version": versions, "kind": "audit", "transport_error": str(e)})
                print(f"    audit error: {e}")
                stop = "audit_error"  # score this version un-audited, then stop

        # ---- score, track best, decide ---------------------------------------
        junk_evidence.update(  # doc-wide furniture is junk evidence too
            str(x) for x in (verdict["metrics"].get("furniture_candidates") or ()))
        cand_score, cand_cov = version_score(verdict, aud_count), coverage_of(verdict)
        improved = track(reply, verdict, cand_score, aud_count, cand_map)
        trail.append({"version": versions, "kind": kind,
                      "metrics": verdict["metrics"], "problems": verdict["problems"],
                      "warnings": verdict["warnings"], "audit_issues": aud_count,
                      "audit_pages": sample_list if aud_count is not None else None,
                      "audit_partial": audit_partial or None,
                      "audit_promoted": promoted or None,
                      "audit_verdicts": audit_verdicts or None,
                      "forgiven_pages": last_forgiven or None,
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
        if prev is not None and not (prev["had_problems"] and bool(verdict["problems"])):
            # consecutive GATE-FAILED pairs are exempt from stall accounting
            # entirely (neither counted nor reset): identical crash scores are
            # zero returns, not diminishing returns - the budget cap bounds them
            if improves(prev["score"], cand_score, prev["cov"], cand_cov,
                        best_issue_pages=prev.get("amap"), cand_issue_pages=cand_map,
                        forgivable=forgiven(prev.get("verdict"), prev["cov"], cand_cov)):
                stalls = 0
            else:
                stalls += 1
                if stalls >= 2:
                    stop = "plateau"  # diminishing returns across two consecutive versions
                    break
                print(f"    no improvement over v{versions - 1} (stall 1/2); one more try")
        prev = {"score": cand_score, "cov": cand_cov, "amap": cand_map,
                "verdict": verdict, "had_problems": bool(verdict["problems"])}

        # ---- next revision prompt --------------------------------------------
        if verdict["problems"]:
            prompt, kind = build_code_revision_prompt(verdict, scope_note=snote), "revise_gates"
        else:
            # coverage feedback rides along on EVERY audit revision, not just the
            # one-time confirmation round: a parser stuck at low coverage must
            # keep seeing its uncovered layouts, or revisions only ever polish
            # the pages it already reads
            audit_probs = audit_problem_lines(audit_verdicts)
            if any((v.get("false") or v.get("wrong_form")) for v in audit_verdicts):
                # the flagged strings are INSTANCES of a structural class; the
                # cheap fix (blocklist the exact strings) is the wrong fix -
                # unsampled pages carry the same class with other wording
                audit_probs.append(
                    "(fix false/wrong_form findings by correcting the structural "
                    "rule that admits them - position, style, column membership. "
                    "Do NOT blocklist these exact strings: unsampled pages carry "
                    "the same problem with different wording, and real fields "
                    "elsewhere may share these words.)")
            prompt = build_code_revision_prompt({
                "source": verdict["source"],
                "metrics": verdict["metrics"],
                "sample": verdict["sample"],
                "problems": ["(aggregate gates passed; a page-level audit of the document "
                             "found the issues below)"] + audit_probs,
                "warnings": verdict["warnings"],
                "cluster_feedback": verdict.get("cluster_feedback", ""),
            }, scope_note=snote)
            kind = "revise_audit"

    return best, trail, stop or "budget", versions


def write_timings(outdir: str, tag: str, profile: dict | None,
                  export_s: float | None = None) -> dict | None:
    """Assemble the per-document time profile from the filled `profile` dict
    (plus stage-0's own elapsed_s from clusters.json) and persist it as
    timings_<tag>.json. Returns the profile dict (None when not profiling)."""
    if profile is None:
        return None
    calls = profile.get("llm_calls", [])
    by_kind: dict[str, dict] = {}
    for c in calls:
        k = by_kind.setdefault(c["kind"], {"calls": 0, "s": 0.0,
                                           "prompt_chars": 0, "reply_chars": 0})
        k["calls"] += 1
        k["s"] = round(k["s"] + c["s"], 3)
        k["prompt_chars"] += c["prompt_chars"]
        k["reply_chars"] += c["reply_chars"]
    timings = {
        "stage0_s": doc_meta(outdir).get("elapsed_s"),
        "llm_s": round(sum(c["s"] for c in calls), 3),
        "llm_calls": len(calls),
        "llm_prompt_chars": sum(c["prompt_chars"] for c in calls),
        "llm_reply_chars": sum(c["reply_chars"] for c in calls),
        "llm_by_kind": by_kind,
        "sandbox_validate_s": profile.get("sandbox_validate_s"),
        "sandbox_validate_calls": profile.get("sandbox_validate_calls"),
        "export_s": export_s,
        "total_s": (round(time.perf_counter() - profile["doc_t0"], 3)
                    if "doc_t0" in profile else None),
        "calls": calls,  # per-call breakdown (sizes + seconds, no text)
    }
    try:
        with open(art(outdir, f"timings_{tag}.json", True), "w", encoding="utf-8") as f:
            json.dump(timings, f, indent=1)
    except OSError:
        pass  # profiling must never fail the run
    return timings


def finalize_document(key: str, pdf: str, outdir: str, tag: str,
                      best: dict | None, trail: list[dict], stop_reason: str,
                      versions: int, profile: dict | None = None,
                      scope: dict | None = None) -> dict:
    """Persist the trail, export the best program + full-document CSV, and build
    the summary row. Shared verbatim by this CLI driver and the Dataiku notebook.
    With a `profile` (the dict induce_document filled), also writes
    timings_<tag>.json and adds headline timing fields to the row.
    With a `scope` (multi-pass specialist), the exported CSV and counts are
    masked to the pass's own pages - the ownership join that keeps specialist
    outputs disjoint."""
    with open(art(outdir, f"codegen_trail_{tag}.json", True), "w", encoding="utf-8") as f:
        json.dump({"stop_reason": stop_reason, "versions": versions,
                   "best_version": best["version"] if best else None,
                   "score_key": ["gate_problems", "audit_issues",
                                 "warnings", "neg_pages_with_fields"],
                   "cycles": trail}, f, indent=1)

    def finish(row_: dict, export_s: float | None = None) -> dict:
        t = write_timings(outdir, tag, profile, export_s)
        if t:
            row_.update(elapsed_s=t["total_s"], stage0_s=t["stage0_s"],
                        llm_s=t["llm_s"], llm_calls=t["llm_calls"])
        return row_

    row = {"doc": key, "versions": versions, "stop_reason": stop_reason}
    usable = best is not None and not best["verdict"]["problems"]
    if not usable:
        row["status"] = "needs_manual_template"
        return finish(row)

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
    with open(art(outdir, f"generated_extractor_{tag}.py", True), "w", encoding="utf-8") as f:
        f.write(source + "\n")
    t0 = time.perf_counter()
    try:
        full = run_extractor(source, pdf)
    except Exception as e:  # noqa: BLE001 - a flaky final replay must not
        row["status"] = "export_failed"    # abort the remaining documents
        row["error"] = str(e)
        return finish(row, export_s=round(time.perf_counter() - t0, 3))
    if scope is not None:
        full = mask_result(full, scope["pages"])
    export_s = round(time.perf_counter() - t0, 3)
    with open(art(outdir, f"fields_codegen_{tag}.csv", True), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["form_name", "field_name", "page"])
        for r in full.records:
            w.writerow([r.form_name, r.field_name, r.page])
    row.update(fields=len(full.records),
               forms=len({r.form_name for r in full.records if r.form_name}),
               pages_with_fields=full.pages_with_fields,
               audit_issues=best["audit_issues"],
               warnings=verdict.get("warnings", []))
    return finish(row, export_s=export_s)


# --------------------------------------------------------------------------- #
# document orchestrator: single pass, or multi-pass specialists on documents
# whose layout families exceed one prompt's representative budget
# --------------------------------------------------------------------------- #
_STATUS_RANK = ["ok", "ok_with_warnings", "ok_audit_issues", "ok_unaudited",
                "needs_manual_template", "export_failed", "error"]


def _worse_status(a: str, b: str) -> str:
    ra = _STATUS_RANK.index(a) if a in _STATUS_RANK else len(_STATUS_RANK)
    rb = _STATUS_RANK.index(b) if b in _STATUS_RANK else len(_STATUS_RANK)
    return a if ra >= rb else b


def scaled_version_budget(base: int, pages_total: int) -> int:
    """Bounded extra revision capacity for unusually large documents.

    The ordinary budget remains unchanged below 900 pages. Each full 900-page
    block adds one version, capped at two extras, so runtime remains predictable
    even for very large inputs. This depends only on the current document size,
    not its filename, vendor, layout family count, or evaluation history.
    """
    return base + min(2, max(0, pages_total) // 900)


def purge_tag_artifacts(outdir: str, tag: str) -> None:
    """Remove outputs that could make a failed rerun look successful."""
    exact = {
        f"fields_codegen_{tag}.csv",
        f"generated_extractor_{tag}.py",
        f"codegen_trail_{tag}.json",
        f"llm_calls_{tag}.jsonl",
        f"timings_{tag}.json",
    }
    prefixes = (
        f"codegen_reply_{tag}_",
        f"fields_codegen_{tag}_pass",
        f"generated_extractor_{tag}_pass",
        f"codegen_trail_{tag}_pass",
        f"llm_calls_{tag}_pass",
        f"timings_{tag}_pass",
    )
    # artifacts now live in per-type buckets under the doc dir; scan each bucket
    for bucket in ART_BUCKETS:
        bdir = art_bucket_dir(outdir, bucket)
        if not os.path.isdir(bdir):
            continue
        for fn in os.listdir(bdir):
            if fn in exact or fn.startswith(prefixes):
                # A failed purge must stop this document. Continuing would let a
                # locked/permission-denied CSV from an older run masquerade as
                # the current result if generation or export later fails.
                os.remove(os.path.join(bdir, fn))


def run_document(call, model: str, tag: str, key: str, pdf: str, outdir: str,
                 max_versions: int, profile: dict | None = None) -> dict:
    """One document end-to-end. Single-pass documents take exactly the
    historical path (same prompts, same artifacts). When codegen.plan_passes
    finds more layout families than one prompt's rep budget can show, each
    pass runs the same induce_document controller restricted to its clusters'
    pages, per-pass artifacts carry a _passN tag suffix, and the merged
    document-level artifacts (fields_codegen_<tag>.csv, codegen_trail_<tag>.json,
    llm_calls_<tag>.jsonl, summary row) cover the whole document."""
    meta = doc_meta(outdir)
    purge_tag_artifacts(outdir, tag)
    version_budget = scaled_version_budget(max_versions, int(meta.get("pages", 0)))
    if version_budget != max_versions:
        print(f"    size-scaled version budget: {max_versions} -> {version_budget} "
              f"for {meta.get('pages')} pages")
    groups = plan_passes(meta)
    if len(groups) <= 1:
        initial_prompt = build_codegen_prompt(pdf, outdir)
        with open(art(outdir, "codegen_prompt.txt", True), "w", encoding="utf-8") as f:
            f.write(initial_prompt)
        best, trail, stop_reason, versions = induce_document(
            call, model, tag, pdf, outdir, initial_prompt, version_budget,
            profile=profile)
        row = finalize_document(key, pdf, outdir, tag, best, trail,
                                stop_reason, versions, profile=profile)
        row["version_budget"] = version_budget
        return row

    print(f"    multi-pass: {len(groups)} passes (generalist + tail specialists; "
          f"{[len(g['clusters']) for g in groups]} clusters each)")
    # stale-artifact purge: the CLI never wipes a document's outdir between
    # runs (the notebook does). A pass that fails THIS run writes no CSV, and
    # the merge below reads whatever file exists - without this purge it would
    # silently resurrect the previous run's rows for that pass. Same-tag pass
    # artifacts of any index are removed (an earlier run may have had more
    # passes); the single-pass prompt is removed too (this document is now
    # multi-pass, keeping it would misrepresent what the model saw).
    stale_prefixes = tuple(f"{stem}_{tag}_pass" for stem in
                           ("fields_codegen", "llm_calls", "codegen_trail",
                            "generated_extractor", "timings", "codegen_reply"))
    stale_exact = ("codegen_prompt.txt", f"generated_extractor_{tag}.py")
    for bucket in ART_BUCKETS:
        bdir = art_bucket_dir(outdir, bucket)
        if not os.path.isdir(bdir):
            continue
        for fn in os.listdir(bdir):
            if fn.startswith(stale_prefixes) or fn.startswith("codegen_prompt_pass") \
                    or fn in stale_exact:
                try:
                    os.remove(os.path.join(bdir, fn))
                except OSError:
                    pass
    pass_rows, all_cycles, merged_csv_rows = [], [], []
    total_versions, statuses, stop_reasons = 0, [], []
    for gi, g in enumerate(groups, 1):
        ptag = f"{tag}_pass{gi}"
        scope = {"pages": {p for ci in g["clusters"] for p in meta["clusters"][ci]["pages"]},
                 "clusters": set(g["clusters"]),
                 "rep_pages": list(g["rep_pages"]),  # pages this pass's prompt shows
                 "main": gi == 1}  # pass 1 owns the budgeted clusters
        # pass 1 is a GENERALIST: its prompt carries no ownership note at all
        # (framing models as specialists made them write narrow parsers); tail
        # passes get the harness-descriptive note. Trade-off accepted for pass
        # 1: its metrics are still masked to its scope while its prompt claims
        # the full page count, so a doc-wide extractor sees slightly deflated
        # numbers with no explanation. plan_passes only guarantees the tail is
        # SUBSTANTIAL (>= 8 reps / 20 content pages), not small - but keeping
        # the prompt free of any multi-pass framing beats explaining the mask
        # (the v1 collapse showed framing is the greater risk).
        prompt = build_codegen_prompt(pdf, outdir, rep_pages=g["rep_pages"],
                                      scope_note="" if gi == 1 else SPECIALIST_NOTE)
        with open(art(outdir, f"codegen_prompt_pass{gi}.txt", True), "w",
                  encoding="utf-8") as f:
            f.write(prompt)
        print(f"    -- pass {gi}/{len(groups)}: {len(g['clusters'])} clusters, "
              f"{len(scope['pages'])} pages, reps {g['rep_pages']}")
        # each pass profiles into its OWN dict (per-pass timings must not report
        # cumulative numbers); slices merge into the document profile afterwards
        pf = None
        if profile is not None:
            pf = {"llm_calls": [], "sandbox_validate_s": 0.0,
                  "sandbox_validate_calls": 0, "doc_t0": time.perf_counter()}
        best, trail, stop_reason, versions = induce_document(
            call, model, ptag, pdf, outdir, prompt, version_budget,
            profile=pf, scope=scope)
        row = finalize_document(key, pdf, outdir, ptag, best, trail,
                                stop_reason, versions, profile=pf, scope=scope)
        if profile is not None:
            # main() seeds the document profile with doc_t0 only - create the
            # accumulator keys here rather than assuming induce_document did
            profile.setdefault("llm_calls", []).extend(pf["llm_calls"])
            profile["sandbox_validate_s"] = round(
                profile.get("sandbox_validate_s", 0.0) + pf["sandbox_validate_s"], 3)
            profile["sandbox_validate_calls"] = (
                profile.get("sandbox_validate_calls", 0) + pf["sandbox_validate_calls"])
        row["pass"] = gi
        row["clusters"] = sorted(scope["clusters"])
        pass_rows.append(row)
        total_versions += versions
        statuses.append(row["status"])
        stop_reasons.append(f"p{gi}:{stop_reason}")
        for c in trail:
            all_cycles.append({**c, "pass": gi})
        csv_path = art(outdir, f"fields_codegen_{ptag}.csv")
        if os.path.isfile(csv_path):
            with open(csv_path, encoding="utf-8", newline="") as f:
                rd = csv.DictReader(f)
                merged_csv_rows.extend(rd)

    # merged document-level artifacts under the plain tag
    merged_csv_rows.sort(key=lambda r: int(r.get("page") or 0))
    with open(art(outdir, f"fields_codegen_{tag}.csv", True), "w",
              encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["form_name", "field_name", "page"])
        for r in merged_csv_rows:
            w.writerow([r["form_name"], r["field_name"], r["page"]])
    with open(art(outdir, f"codegen_trail_{tag}.json", True), "w", encoding="utf-8") as f:
        json.dump({"multipass": len(groups),
                   "stop_reason": ";".join(stop_reasons),
                   "versions": total_versions,
                   "best_version": None,  # per-pass bests; see passes
                   "passes": [{k: r.get(k) for k in
                               ("pass", "clusters", "status", "stop_reason",
                                "versions", "best_version", "fields")}
                              for r in pass_rows],
                   "score_key": ["gate_problems", "audit_issues",
                                 "warnings", "neg_pages_with_fields"],
                   "cycles": all_cycles}, f, indent=1)
    # one merged verbatim call log so cost_report finds the whole document
    with open(art(outdir, f"llm_calls_{tag}.jsonl", True), "w", encoding="utf-8") as out:
        for gi in range(1, len(groups) + 1):
            p = art(outdir, f"llm_calls_{tag}_pass{gi}.jsonl")
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as src:
                    out.write(src.read())

    status = "ok"
    for s in statuses:
        status = _worse_status(status, s)
    row = {"doc": key, "status": status, "multipass": len(groups),
           "version_budget": version_budget,
           "versions": total_versions, "stop_reason": ";".join(stop_reasons),
           "fields": sum(r.get("fields") or 0 for r in pass_rows),
           "forms": len({fr["form_name"] for fr in merged_csv_rows if fr["form_name"]}),
           "pages_with_fields": sum(r.get("pages_with_fields") or 0 for r in pass_rows),
           "audit_issues": (None if any(r.get("audit_issues") is None for r in pass_rows)
                            else sum(r.get("audit_issues") or 0 for r in pass_rows)),
           "passes": pass_rows}
    t = write_timings(outdir, tag, profile, export_s=None)
    if t:
        row.update(elapsed_s=t["total_s"], stage0_s=t["stage0_s"],
                   llm_s=t["llm_s"], llm_calls=t["llm_calls"])
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--audit-model",
                    help="optional model used only for grounded audit calls; "
                         "generation, revision, and coverage confirmation continue "
                         "to use --model")
    ap.add_argument("--only", help="substring filter on doc key")
    ap.add_argument("--skip", action="append", default=[],
                    help="substring of doc keys to EXCLUDE (repeatable) - e.g. to "
                         "run the corpus minus already-run documents")
    ap.add_argument("--all-docs", action="store_true",
                    help="(deprecated no-op: every staged PDF runs by default; "
                         "use --only/--skip to narrow the set)")
    ap.add_argument("--max-versions", type=int, default=5,
                    help="base cap on parser versions per document; 900+ page books "
                         "receive up to two bounded extra versions (the loop still "
                         "stops earlier on convergence or plateau)")
    args = ap.parse_args()
    if args.max_versions < 1:
        ap.error("--max-versions must be >= 1")
    agent_bin = find_agent()
    tag = run_tag(args.model, args.audit_model)

    all_pdfs = list_root_pdfs()
    pdfs = {doc_key(p): p for p in all_pdfs}
    if len(pdfs) != len(all_pdfs):  # a collision would silently drop a document
        raise SystemExit("doc_key collision among input PDFs (near-identical names) "
                         "- rename the colliding files")
    docs = sorted(pdfs)  # every staged PDF; the corpus IS the default run
    if args.only:
        docs = [d for d in docs if args.only.lower() in d.lower()]
    for s in args.skip:
        docs = [d for d in docs if s.lower() not in d.lower()]
    if not docs:
        raise SystemExit("no documents left after --only/--skip filtering")

    summary = []
    for key in docs:
        pdf = pdfs[key]
        outdir = os.path.join(OUT_DIR, key)
        print(f"=== {key}")
        profile = {"doc_t0": time.perf_counter()}
        try:  # one bad document must not sink a multi-hour paid batch
            meta = doc_meta(outdir)
            status = meta.get("status", "ok")
            if status != "ok":
                # encrypted / scanned / zero-page / stage0 not run: no LLM budget spent
                row = {"doc": key, "status": f"skipped_{status}"}
                if meta.get("elapsed_s") is not None:
                    row["stage0_s"] = meta["elapsed_s"]
                summary.append(row)
                print(f"    skipped: {status}")
                continue
            # prompts are built fresh from the CURRENT stage-0 artifacts inside
            # run_document (and saved for inspection) - reading a pre-existing
            # codegen_prompt.txt would silently reuse stale rep dumps after a
            # stage-0 rerun
            def transport(prompt):
                chosen_model = (args.audit_model
                                if args.audit_model and is_audit_prompt(prompt)
                                else args.model)
                return call_cli(agent_bin, chosen_model, prompt)
            row = run_document(transport, args.model, tag, key, pdf, outdir,
                               args.max_versions, profile=profile)
            if meta.get("text_layer_pct", 100) < 100:
                # partially scanned book: those pages are unreachable by design
                row["text_layer_pct"] = meta["text_layer_pct"]
        except Exception as e:  # noqa: BLE001
            row = {"doc": key, "status": "error", "error": repr(e),
                   "elapsed_s": round(time.perf_counter() - profile["doc_t0"], 3)}
        summary.append(row)
        print(f"    -> {row}")

    with open(os.path.join(OUT_DIR, f"cli_induction_summary_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))

    # stage-attributed error report (derived from trails + summary; see run_report)
    events = run_report.collect_run_events(OUT_DIR, tag, summary)
    ev_csv, ev_json = run_report.write_reports(OUT_DIR, tag, summary, events, prefix="cli_")
    by_stage = {}
    for e in events:
        by_stage[e["stage"]] = by_stage.get(e["stage"], 0) + 1
    print(f"error report: {len(events)} event(s) {by_stage or ''} -> {ev_csv}")


if __name__ == "__main__":
    main()
