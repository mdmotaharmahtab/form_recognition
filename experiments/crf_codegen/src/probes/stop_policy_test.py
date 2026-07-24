"""Mechanical tests for the loop controller's stopping policy (no LLM, no PDF).

Run after any controller change:  python stop_policy_test.py
Covers: converge / plateau / budget / consecutive hard-fail handling (revise to
budget, recover, regression plateau) / coverage-regression guard (best selection
AND plateau) / the verified junk-coverage carve-out (evidence-gated page
forgiveness) / clean-but-regressed versions /
zero-trust audits / audit-reply retry (malformed and partial) / the
coverage-confirm block (adopt with the pre-extension version scored, reject,
token, last-slot skip) / transport+audit error stops / best-version (not
last-version) export selection / audit rotation + problem-page promotion /
audit_budget scaling / plan_passes grouping + small-tail folding / scoped
volume-gate softening (tail specialists only) / mask_result scoping /
count_text_filters (literal-blocklist detector + hard ceiling) / family-labeled
rep pages / form-name same-page persistence / size-scaled version budget /
split-model audit routing / collision-resistant run tags / stale-artifact purge.

Harness notes: only the transport (call_cli), validate_generated and
build_audit_prompt are scripted (plus pick_rotation_pages in the rotation
test); scoring, stop rules, audit counting and the CONFIRM_NO_FIELDS detection
are the real implementations. Audit issue counts in `steps` are keyed by CYCLE
(an adopted confirm extension is audited with the same cycle's count).
"""
import csv
import json
import os
import tempfile
import time
from types import SimpleNamespace

import fitz

import codegen
import induction
import run_cli_induction as rci
import run_report
from common import Line, art, pick_title_context_pages
from replay import FieldRec, ReplayResult

ORIGINALS = {name: getattr(rci, name) for name in
             ("validate_generated", "build_audit_prompt", "parse_audit_reply",
              "build_code_revision_prompt", "build_coverage_confirm_prompt",
              "save_reply", "pick_rotation_pages", "build_codegen_prompt",
              "run_extractor")}

PASS, FAIL = "PASS", "FAIL"
failures = []


def check(name: str, ok: bool, note: str = "") -> None:
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  ({note})" if note else ""))
    if not ok:
        failures.append(name)


def make_verdict(problems=(), warnings=(), coverage=100, records=50, feedback="",
                 covered=None, uncovered_pct=None):
    # covered: explicit covered-page iterable for the page-SET retention guard;
    # without it coverage_of() falls back to range(pages_with_fields), which
    # keeps the guard equivalent to the old count comparison for these tests
    result = (SimpleNamespace(covered_pages=set(covered)) if covered is not None
              else object())  # otherwise only truthiness is used by the controller
    metrics = {"records": records, "pages_with_fields": coverage}
    # uncovered_pct: share of content-bearing pages with zero records (the
    # coverage-floor signal). None omits it entirely (metric absent), which is
    # how validate_generated behaves when it can't build cluster stats.
    if uncovered_pct is not None:
        metrics["uncovered_content_pct"] = uncovered_pct
        metrics["content_covered_pct"] = 100 - uncovered_pct
    return {"source": "def extract(pages): return []",
            "result": result,
            "metrics": metrics,
            "problems": list(problems), "warnings": list(warnings),
            "sample": "(none)", "cluster_stats": [], "weak_clusters": [],
            "cluster_feedback": feedback}


def full_audit_reply(pages, n_issues):
    """Reply covering every audited page, all issues piled on the first."""
    return [{"page": p, "missed": (["field"] * n_issues if i == 0 else []),
             "false": [], "wrong_form": []} for i, p in enumerate(pages)]


def _parse_list_or_raise(raw):
    if isinstance(raw, list):
        return raw
    raise ValueError("no JSON array in audit reply")


class Script:
    """Drives induce_document with a scripted sequence of steps.

    steps items:  (verdict, audit) where audit is an int issue count, an
                  Exception (audit transport fails), or a callable(pages)->reply;
                  or a bare Exception (the generate/revise call itself fails).
    confirm_reply/confirm_verdict script the one coverage-confirm round.
    """

    def __init__(self, steps, confirm_reply=None, confirm_verdict=None,
                 default_pages=(1, 2, 3)):
        self.steps = list(steps)
        self.confirm_reply = confirm_reply
        self.confirm_verdict = confirm_verdict
        self.default_pages = list(default_pages)
        self.i = -1
        self.last_pages = []
        self.pages_seen = []  # the `pages` argument of every build_audit_prompt call

    def install(self):
        rci.validate_generated = self.validate_generated
        rci.build_audit_prompt = self.build_audit_prompt
        # replies are already lists; anything else mimics "no JSON array found"
        rci.parse_audit_reply = _parse_list_or_raise
        rci.build_code_revision_prompt = lambda verdict, **kw: "revise-prompt"
        rci.build_coverage_confirm_prompt = lambda verdict, **kw: "confirm-prompt"
        rci.save_reply = lambda outdir, tag, name, reply, ext="py": None

    def build_audit_prompt(self, pdf, outdir, result, max_pages=None, pages=None,
                           scope=None):
        self.pages_seen.append(list(pages) if pages is not None else None)
        self.last_pages = list(pages) if pages is not None else self.default_pages
        return "audit-prompt", list(self.last_pages)

    def transport(self, prompt):
        # startswith, not ==: the controller's audit retry APPENDS a reminder
        if prompt.startswith("confirm-prompt"):
            return self.confirm_reply
        if prompt.startswith("audit-prompt"):
            audit = self.steps[self.i][1]
            if isinstance(audit, Exception):
                raise audit
            if callable(audit):
                return audit(self.last_pages)
            return full_audit_reply(self.last_pages, audit)
        nxt = self.steps[self.i + 1]
        if isinstance(nxt, Exception):
            raise nxt
        return f"reply-{self.i + 1}"

    def validate_generated(self, pdf, reply, outdir=None, scope=None):
        if self.confirm_reply is not None and reply == self.confirm_reply:
            return self.confirm_verdict
        self.i += 1
        return self.steps[self.i][0]

    def run(self, max_versions=5, scope=None):
        self.install()
        return rci.induce_document(self.transport, "model", "tag", "doc.pdf",
                                   "outdir", "initial-prompt", max_versions,
                                   scope=scope)


def trail_kinds(trail):
    return [(t.get("kind"), t.get("outcome")) for t in trail if t.get("kind") == "confirm"]


def main() -> None:
    # 1. clean first try: gates pass, audit 0 -> converged after one version
    best, trail, stop, versions = Script([(make_verdict(), 0)]).run()
    check("converges on clean audit", stop == "converged" and versions == 1
          and best["version"] == 1 and best["audit_issues"] == 0)

    # 2. improving then flat audit counts -> ONE stall is tolerated (audit
    #    counts are sampled and noisy), TWO consecutive stalls plateau
    steps = [(make_verdict(), 18), (make_verdict(), 5), (make_verdict(), 5),
             (make_verdict(), 5)]
    best, trail, stop, versions = Script(steps).run()
    check("plateau after two consecutive stalls", stop == "plateau" and versions == 4,
          f"stop={stop} versions={versions}")
    check("best version exported, not last", best["version"] == 2
          and best["audit_issues"] == 5)

    # 2b. a single stall followed by an improvement RESETS the stall count
    steps = [(make_verdict(), n) for n in (18, 5, 5, 4, 4)]
    best, trail, stop, versions = Script(steps).run(max_versions=5)
    check("stall count resets on improvement", stop == "budget" and versions == 5
          and best["version"] == 4 and best["audit_issues"] == 4,
          f"stop={stop} versions={versions} best=v{best['version']}")

    # 3a. consecutive hard-failing versions are NOT a plateau: identical crash
    #     scores are zero returns, not diminishing returns - revise to budget
    bad = make_verdict(problems=["crash"], coverage=0, records=0)
    best, trail, stop, versions = Script([(bad, None)] * 5).run()
    check("consecutive hard-fails revise until budget",
          stop == "budget" and versions == 5 and best["verdict"]["problems"],
          f"stop={stop} versions={versions}")

    # 3b. ...which lets a late recovery win: crash, crash, then clean converge
    steps = [(bad, None), (bad, None), (make_verdict(), 0)]
    best, trail, stop, versions = Script(steps).run()
    check("recovery after two hard-fails converges",
          stop == "converged" and versions == 3 and best["version"] == 3,
          f"stop={stop} versions={versions}")

    # 3c. a hard-fail AFTER a gate-passing version counts one stall; the
    #     following crash-crash pairs are exempt, so the loop revises to the
    #     budget with the working version protected as best
    steps = [(make_verdict(), 5)] + [(bad, None)] * 4
    best, trail, stop, versions = Script(steps).run()
    check("crashes after working version revise to budget, best protected",
          stop == "budget" and versions == 5 and best["version"] == 1,
          f"stop={stop} versions={versions} best=v{best['version'] if best else None}")

    # 4. strictly improving every cycle -> runs to the version budget
    steps = [(make_verdict(), n) for n in (9, 8, 7, 6, 5)]
    best, trail, stop, versions = Script(steps).run(max_versions=5)
    check("budget cap at 5 versions", stop == "budget" and versions == 5
          and best["version"] == 5)

    # 5. fewer audit issues but collapsed coverage: not an improvement for best
    #    NOR for stall accounting -> two such versions plateau, best stays v1
    steps = [(make_verdict(coverage=100), 18), (make_verdict(coverage=40), 3),
             (make_verdict(coverage=40), 3)]
    best, trail, stop, versions = Script(steps).run()
    check("coverage-regression guard (best + plateau)",
          stop == "plateau" and versions == 3 and best["version"] == 1,
          f"stop={stop} best=v{best['version']}")

    # 5b. same coverage COUNT, different PAGES: swapping which pages are
    #     covered is a loss of working extraction, not a tie - the retention
    #     guard must refuse it even though counts match and audits improved
    steps = [(make_verdict(coverage=100, covered=range(100)), 18),
             (make_verdict(coverage=100, covered=range(50, 150)), 3),
             (make_verdict(coverage=100, covered=range(50, 150)), 3)]
    best, trail, stop, versions = Script(steps).run()
    check("page-set guard rejects coverage swaps",
          stop == "plateau" and versions == 3 and best["version"] == 1,
          f"stop={stop} versions={versions} best=v{best['version']}")

    # 6. audit issue counts are compared on the SAME pages across versions
    s = Script([(make_verdict(), 4), (make_verdict(), 2), (make_verdict(), 2),
                (make_verdict(), 2)])
    s.run()
    check("audit pages fixed after first audit",
          s.pages_seen[0] is None and all(p == [1, 2, 3] for p in s.pages_seen[1:]),
          f"pages={s.pages_seen}")

    # 7. clean audit reached by dropping coverage: must NOT converge; earlier
    #    best wins (pins the converged-requires-improved branch)
    steps = [(make_verdict(coverage=100), 18), (make_verdict(coverage=40), 0),
             (make_verdict(coverage=40), 0)]
    best, trail, stop, versions = Script(steps).run()
    check("clean-but-regressed version does not converge",
          stop == "plateau" and best["version"] == 1 and best["audit_issues"] == 18,
          f"stop={stop} best=v{best['version']}")

    # 8. zero-issue audit that SKIPS audited pages is not trusted as clean
    #    (the controller retries once; here the reply stays partial both times)
    lazy = lambda pages: [{"page": pages[0], "missed": [], "false": [], "wrong_form": []}]  # noqa: E731
    steps = [(make_verdict(), lazy), (make_verdict(), lazy), (make_verdict(), lazy)]
    best, trail, stop, versions = Script(steps).run()
    check("zero-by-omission audit never converges",
          stop != "converged" and best["audit_issues"] is None,
          f"stop={stop} aud={best['audit_issues']}")

    # 8b. malformed audit reply is retried once; the retry's clean reply counts
    calls = {"n": 0}

    def flaky(pages):
        calls["n"] += 1
        if calls["n"] == 1:
            return "no json here at all"
        return full_audit_reply(pages, 0)

    best, trail, stop, versions = Script([(make_verdict(), flaky)]).run()
    check("malformed audit reply retried, then trusted",
          stop == "converged" and calls["n"] == 2 and best["audit_issues"] == 0,
          f"stop={stop} calls={calls['n']}")

    # 8c. partial NONZERO audit is retried; if still partial it is kept but
    #     flagged (an undercount still drives revision, never convergence)
    lazy_bad = lambda pages: [{"page": pages[0], "missed": ["x"], "false": [], "wrong_form": []}]  # noqa: E731
    steps = [(make_verdict(), lazy_bad), (make_verdict(), lazy_bad),
             (make_verdict(), lazy_bad)]
    best, trail, stop, versions = Script(steps).run()
    partial_flags = [t.get("audit_partial") for t in trail if t.get("kind") != "confirm"]
    check("partial nonzero audit kept and flagged",
          stop != "converged" and best["audit_issues"] == 1
          and all(partial_flags), f"stop={stop} flags={partial_flags}")

    # 9. confirm round: adopted extension consumes budget and is what gets audited
    base = make_verdict(coverage=100, records=50, feedback="uncovered clusters...")
    ext = make_verdict(coverage=120, records=60)
    best, trail, stop, versions = Script(
        [(base, 0)], confirm_reply="extension-code", confirm_verdict=ext).run()
    check("adopted extension consumes a version and converges",
          stop == "converged" and versions == 2 and best["version"] == 2
          and trail_kinds(trail) == [("confirm", "extended_program")],
          f"stop={stop} versions={versions} confirm={trail_kinds(trail)}")
    orig_entries = [t for t in trail if t.get("kind") == "generate"]
    check("pre-extension version scored in its own trail entry",
          len(orig_entries) == 1 and orig_entries[0]["version"] == 1
          and orig_entries[0]["score"][1] == "not_audited"
          and orig_entries[0]["became_best"],
          f"entries={[(t.get('kind'), t.get('version')) for t in trail]}")

    # 10. confirm round: CONFIRM_NO_FIELDS token accepted only as the answer
    best, trail, stop, versions = Script(
        [(base, 0)], confirm_reply="Checked the pages.\nCONFIRM_NO_FIELDS").run()
    check("CONFIRM_NO_FIELDS keeps program, converges on base",
          stop == "converged" and versions == 1
          and trail_kinds(trail) == [("confirm", "confirmed_no_fields")])

    # 11. confirm round: extension that shrinks coverage is rejected
    shrunk = make_verdict(coverage=50, records=70)
    best, trail, stop, versions = Script(
        [(base, 0)], confirm_reply="extension-code", confirm_verdict=shrunk).run()
    check("coverage-shrinking extension rejected",
          stop == "converged" and versions == 1 and best["version"] == 1
          and trail_kinds(trail) == [("confirm", "extension_rejected")])

    # 12. confirm never runs in the last budget slot (extension could not be paid for)
    best, trail, stop, versions = Script(
        [(base, 0)], confirm_reply="extension-code", confirm_verdict=ext).run(max_versions=1)
    check("confirm skipped at last budget slot",
          versions == 1 and not trail_kinds(trail))

    # 12b. coverage floor: a main-pass version that leaves most content pages
    #      empty becomes a PROBLEM (cannot converge on a clean audit), so a
    #      later well-covered version wins. v1 (80% empty) is blocked; v2 (10%)
    #      converges. The v1 trail entry carries the coverage-floor problem.
    steps = [(make_verdict(uncovered_pct=80), 0), (make_verdict(uncovered_pct=10), 0)]
    best, trail, stop, versions = Script(steps).run()
    v1_probs = next(t["problems"] for t in trail if t.get("version") == 1
                    and t.get("kind") != "confirm")
    check("coverage floor blocks a low-coverage version from converging",
          stop == "converged" and best["version"] == 2
          and any("Coverage floor" in p for p in v1_probs),
          f"stop={stop} best=v{best['version']} v1_probs={v1_probs}")

    # 12c. a CREDIBLE field-free confirmation stands the coverage floor down:
    #      60% empty is past the floor (50) but within the credibility bar (75),
    #      so CONFIRM_NO_FIELDS is honored and v1 converges with NO floor problem
    #      (we never force junk extraction out of genuinely field-free layouts).
    ffbase = make_verdict(uncovered_pct=60, feedback="uncovered clusters...")
    best, trail, stop, versions = Script(
        [(ffbase, 0)], confirm_reply="Checked.\nCONFIRM_NO_FIELDS").run()
    all_probs = [p for t in trail for p in (t.get("problems") or [])]
    check("credible field-free confirmation stands down the coverage floor",
          stop == "converged" and versions == 1
          and trail_kinds(trail) == [("confirm", "confirmed_no_fields")]
          and not any("Coverage floor" in p for p in all_probs),
          f"stop={stop} versions={versions} probs={all_probs}")

    # 12c2. an IMPLAUSIBLE field-free claim cannot dodge the floor: at 90% of
    #       content pages empty the program reads almost nothing, so the claim is
    #       recorded but the floor stays armed and the version cannot converge.
    ffbad = make_verdict(uncovered_pct=90, feedback="uncovered clusters...")
    best, trail, stop, versions = Script(
        [(ffbad, 0), (make_verdict(uncovered_pct=10), 0)],
        confirm_reply="Checked.\nCONFIRM_NO_FIELDS").run()
    bad_probs = [p for t in trail for p in (t.get("problems") or [])]
    check("implausible field-free claim leaves the coverage floor armed",
          trail_kinds(trail) == [("confirm", "confirmed_no_fields_not_credible")]
          and any("Coverage floor" in p for p in bad_probs)
          and best["version"] == 2,
          f"stop={stop} best=v{best['version']} kinds={trail_kinds(trail)}")

    # 12d. coverage floor never fires on a TAIL-SPECIALIST scope (those keep the
    #      softened-gate philosophy): an 80%-empty specialist still converges.
    best, trail, stop, versions = Script(
        [(make_verdict(uncovered_pct=80), 0)]).run(scope={"main": False})
    spec_probs = [p for t in trail for p in (t.get("problems") or [])]
    check("coverage floor skipped for tail-specialist scope",
          stop == "converged" and versions == 1
          and not any("Coverage floor" in p for p in spec_probs),
          f"stop={stop} versions={versions} probs={spec_probs}")

    # 13. transport error on generate -> stop, nothing usable
    best, trail, stop, versions = Script([RuntimeError("cli down")]).run()
    check("transport error stops with nothing", stop == "transport_error"
          and best is None)

    # 14. audit transport error -> stop, version kept but marked un-audited
    steps = [(make_verdict(), RuntimeError("audit down"))]
    best, trail, stop, versions = Script(steps).run()
    check("audit error stops; version kept un-audited",
          stop == "audit_error" and best is not None and best["audit_issues"] is None)

    # 15. max_versions=1 with remaining issues -> budget stop after one version
    best, trail, stop, versions = Script([(make_verdict(), 5)]).run(max_versions=1)
    check("max_versions=1 stops on budget", stop == "budget" and versions == 1
          and best["audit_issues"] == 5)

    # 16. token detection is anchored, not substring (real implementation)
    check("token in prose is not a confirmation",
          not codegen.is_confirm_no_fields("I cannot CONFIRM_NO_FIELDS, extension:\n...")
          and not codegen.is_confirm_no_fields("CONFIRM_NO_FIELDS\ndef extract(pages): ...")
          and codegen.is_confirm_no_fields("Reasoning here.\n CONFIRM_NO_FIELDS \n"))

    # 17. audit budget scales with document size, capped
    check("audit budget scaling",
          codegen.audit_budget(40) == 6 and codegen.audit_budget(300) == 6
          and codegen.audit_budget(331) == 7 and codegen.audit_budget(609) == 9
          and codegen.audit_budget(964) == 11 and codegen.audit_budget(5000) == 12,
          f"{[codegen.audit_budget(n) for n in (40, 300, 331, 609, 964, 5000)]}")

    # 18. improves(): junk-coverage carve-out is VERIFIED, not inferred. Pages
    #     lost below the retention floor are excused only when every lost page
    #     is in `forgivable` (verified junk-only); a falling audit count alone
    #     no longer buys anything - that inference once blessed dropping 340
    #     truly-covered pages for a 1-issue audit improvement.
    sc_best = (0, 5, 0, -100)
    lost40 = set(range(60, 100))
    ok_cleanup = codegen.improves(  # all lost pages verified junk-only
        sc_best, (0, 2, 0, -60), best_cov=range(100), cand_cov=range(60),
        best_issue_pages={1: 5, 2: 0}, cand_issue_pages={1: 2, 2: 0},
        forgivable=lost40)
    unverified = codegen.improves(  # audit down but NO junk evidence -> veto
        sc_best, (0, 2, 0, -60), best_cov=range(100), cand_cov=range(60),
        best_issue_pages={1: 5, 2: 0}, cand_issue_pages={1: 2, 2: 0})
    partial = codegen.improves(  # one lost page not verified junk -> veto
        sc_best, (0, 2, 0, -60), best_cov=range(100), cand_cov=range(60),
        best_issue_pages={1: 5, 2: 0}, cand_issue_pages={1: 2, 2: 0},
        forgivable=lost40 - {99})
    ratio_free = codegen.improves(  # 70% of pages dropped, all verified: no
        sc_best, (0, 2, 0, -30),    # ratio cap on evidence-backed cleanups
        best_cov=range(100), cand_cov=range(30),
        best_issue_pages={1: 5, 2: 0}, cand_issue_pages={1: 2, 2: 0},
        forgivable=set(range(30, 100)))
    swap = codegen.improves(  # swap: gains 50 new pages, loses 50 unverified
        sc_best, (0, 2, 0, -100), best_cov=range(100), cand_cov=range(50, 150),
        best_issue_pages={1: 5, 2: 0}, cand_issue_pages={1: 2, 2: 0})
    check("junk carve-out forgives only verified junk-only pages",
          ok_cleanup and ratio_free and not unverified and not partial and not swap,
          f"cleanup={ok_cleanup} ratio_free={ratio_free} unverified={unverified} "
          f"partial={partial} swap={swap}")

    # 18c. forgivable_junk_pages: a page is forgiven only when EVERY record it
    #      loses matches junk evidence (audit false values / furniture), with
    #      whitespace/case-normalized matching; no evidence -> nothing forgiven
    res18 = SimpleNamespace(records=[
        SimpleNamespace(page=7, field_name="Reason  Not Performed"),   # junk only
        SimpleNamespace(page=8, field_name="reason not performed"),    # junk only
        SimpleNamespace(page=8, field_name="Staff Initials:"),         # junk only (2nd value)
        SimpleNamespace(page=9, field_name="Reason Not Performed"),    # junk +
        SimpleNamespace(page=9, field_name="Sample Date"),             #   real field
        SimpleNamespace(page=10, field_name="Weight"),                 # real only
    ])
    ev = ["Reason Not Performed", "Staff Initials:"]
    forgiven18 = codegen.forgivable_junk_pages(res18, {6, 7, 8, 9, 11}, ev)
    empty18 = codegen.forgivable_junk_pages(res18, {6, 7}, [])
    check("forgivable_junk_pages: junk-only pages, normalized, evidence-gated",
          forgiven18 == {6, 7} and empty18 == set(),
          f"forgiven={forgiven18} empty={empty18}")

    # 18d. in-loop wiring: values the audit flags under "false" accumulate as
    #      junk evidence, so the NEXT version may drop exactly the pages whose
    #      only records carried those values - and converge as the new best
    v1_junk = make_verdict(coverage=10, covered=range(10))
    v1_junk["result"].records = (
        [SimpleNamespace(page=p, field_name="Footer stamp") for p in (6, 7, 8, 9, 10)]
        + [SimpleNamespace(page=1, field_name="Weight"),
           SimpleNamespace(page=2, field_name="Height")])
    v2_clean = make_verdict(coverage=5, covered=range(5))
    v2_clean["result"].records = [SimpleNamespace(page=1, field_name="Weight"),
                                  SimpleNamespace(page=2, field_name="Height")]

    def flag_footer(pages):
        return [{"page": p, "missed": [], "wrong_form": [],
                 "false": (["Footer stamp"] if p == 1 else [])} for p in pages]

    best, trail, stop, versions = Script([(v1_junk, flag_footer),
                                          (v2_clean, 0)]).run()
    forgiven_trail = [t.get("forgiven_pages") for t in trail
                      if t.get("version") == 2 and "metrics" in t]
    check("audit-flagged junk lets the cleanup version win and converge",
          stop == "converged" and versions == 2 and best["version"] == 2
          and forgiven_trail == [[6, 7, 8, 9, 10]],
          f"stop={stop} best={best['version'] if best else None} "
          f"forgiven={forgiven_trail}")

    # 18e. same wiring, evidence from the OTHER source: doc-wide furniture
    #      candidates (metrics) forgive the cleanup even when no audit reply
    #      ever used the "false" channel
    v1_furn = make_verdict(coverage=10, covered=range(10))
    v1_furn["metrics"]["furniture_candidates"] = ["Initials box"]
    v1_furn["result"].records = (
        [SimpleNamespace(page=p, field_name="Initials  BOX") for p in (6, 7, 8, 9, 10)]
        + [SimpleNamespace(page=1, field_name="Weight")])
    v2_furn = make_verdict(coverage=5, covered=range(5))
    v2_furn["result"].records = [SimpleNamespace(page=1, field_name="Weight")]
    best, trail, stop, versions = Script([(v1_furn, 1), (v2_furn, 0)]).run()
    check("furniture-candidate evidence forgives the cleanup too",
          stop == "converged" and versions == 2 and best["version"] == 2,
          f"stop={stop} best={best['version'] if best else None}")

    # 18b. shared-page re-basing: candidate audited on MORE pages (rotation)
    #      with all new issues on fresh pages still improves on the shared set
    ok_shared = codegen.improves(
        (0, 2, 0, -100), (0, 3, 0, -100), best_cov=range(100), cand_cov=range(100),
        best_issue_pages={1: 2, 2: 0, 3: 0},
        cand_issue_pages={1: 0, 2: 0, 3: 0, 9: 3})
    check("audit counts re-based on shared pages", ok_shared)

    # 19. rotation slots are added from v2 and problem pages get PROMOTED into
    #     the core (re-audited every later round, within the sample bound)
    rot_calls = {"n": 0}

    def scripted_rotation(outdir, result, core, history, k, salt=0, scope=None):
        rot_calls["n"] += 1
        fresh = [p for p in (9, 10, 11, 12) if p not in set(core) | set(history or ())]
        return fresh[:k]

    def issues_on_9(pages):
        return [{"page": p, "missed": (["x"] if p == 9 else []),
                 "false": [], "wrong_form": []} for p in pages]

    rci.pick_rotation_pages = scripted_rotation
    try:
        s = Script([(make_verdict(), 2), (make_verdict(), issues_on_9),
                    (make_verdict(), issues_on_9), (make_verdict(), 9)],
                   default_pages=(1, 2, 3, 4, 5, 6))
        best, trail, stop, versions = s.run()
    finally:
        rci.pick_rotation_pages = ORIGINALS["pick_rotation_pages"]
    v2_pages, v3_pages = s.pages_seen[1], s.pages_seen[2]
    promo = [t.get("audit_promoted") for t in trail if t.get("version") == 2]
    check("rotation explores fresh pages from v2",
          v2_pages is not None and 9 in v2_pages and 10 in v2_pages
          and set(v2_pages) >= {1, 2, 3, 4, 5, 6},
          f"v2={v2_pages}")
    check("problem rotation page promoted into core",
          promo == [[9]] and v3_pages is not None and 9 in v3_pages,
          f"promoted={promo} v3={v3_pages}")

    # 20. plan_passes: budgeted clusters in pass 0; tail clusters bin-packed;
    #     old metas (no tail reps) -> single pass. Thresholds are lowered here
    #     to exercise the PACKING logic; default-threshold folding is 20c.
    meta_mp = {"pages": 40, "representative_pages_1based": [1, 2, 5],
               "clusters": [
                   {"pages": list(range(0, 10)), "representatives": [4]},
                   {"pages": list(range(10, 20)), "representatives": [12]},
                   {"pages": list(range(20, 30)), "representatives": [22]},
                   {"pages": list(range(30, 40)), "representatives": []}]}
    groups = codegen.plan_passes(meta_mp, rep_budget=2,
                                 min_tail_reps=2, min_tail_content=10)
    single = codegen.plan_passes(
        {"pages": 40, "representative_pages_1based": [1, 2, 5],
         "clusters": [{"pages": list(range(40)), "representatives": [4]}]})
    check("plan_passes groups tail clusters",
          len(groups) == 2 and groups[0]["clusters"] == [0, 3]
          and groups[1]["clusters"] == [1, 2]
          and groups[0]["rep_pages"] == [1, 2, 5]
          and set(groups[1]["rep_pages"]) == {1, 2, 13, 23},
          f"{groups}")
    check("plan_passes single pass without tail reps",
          len(single) == 1 and single[0]["clusters"] == [0])

    # 20c. splitting is the exception: at DEFAULT thresholds the same small
    #      tail (2 reps / 20 content pages < 8 reps) folds into a single pass
    #      that owns every cluster and keeps the exact single-pass rep list
    folded_small = codegen.plan_passes(meta_mp, rep_budget=2)
    check("plan_passes folds small tails at default thresholds",
          len(folded_small) == 1
          and folded_small[0]["clusters"] == [0, 1, 2, 3]
          and folded_small[0]["rep_pages"] == [1, 2, 5],
          f"{folded_small}")

    # 20d. volume gates soften only for TAIL specialists: the main pass and
    #      the single-pass path keep them hard; non-volume gates always stay.
    #      Uses REAL gate_problems output so a rewording of induction.py that
    #      breaks the prefix match (or the run_report code mapping) fails here.
    tail_sc, main_sc = {"pages": set(), "main": False}, {"pages": set(), "main": True}
    mz = {"records": 0, "pages_total": 50, "pages_with_fields": 0, "distinct_forms": 0}
    ml = {"records": 3, "pages_total": 50, "pages_with_fields": 3, "distinct_forms": 2}
    pz, pl = induction.gate_problems(mz), induction.gate_problems(ml)
    pz_t, wz_t = codegen.soften_scoped_volume_gates(list(pz), [], mz, tail_sc)
    pl_t, wl_t = codegen.soften_scoped_volume_gates(list(pl), [], ml, tail_sc)
    pz_m, wz_m = codegen.soften_scoped_volume_gates(list(pz), [], mz, main_sc)
    pz_n, _ = codegen.soften_scoped_volume_gates(list(pz), [], mz, None)
    p_deg = ["Degenerate form grouping: 60 distinct form_names for 100 records."]
    pd_t, _ = codegen.soften_scoped_volume_gates(list(p_deg), [], {"records": 100}, tail_sc)
    check("volume gates soften for tail specialists only",
          pz_t == [] and pl_t == [] and pz_m == pz and pz_n == pz
          and pd_t == p_deg,
          f"tail_zero={pz_t} tail_low={pl_t} main={pz_m}")
    check("softened warnings map to scope report codes",
          [run_report.classify_warning(w) for w in (wz_t[0], wl_t[0])]
          == ["warn_scope_zero_records", "warn_scope_low_records"],
          f"{[run_report.classify_warning(w) for w in (wz_t[0], wl_t[0])]}")

    # 20b. max_passes folds overflow clusters into the last pass (ownership kept)
    meta_of = {"pages": 120, "representative_pages_1based": [1, 2],
               "clusters": [{"pages": list(range(0, 20)), "representatives": [1]}]
               + [{"pages": list(range(20 + 10 * i, 30 + 10 * i)),
                   "representatives": [25 + 10 * i]} for i in range(10)]}
    folded = codegen.plan_passes(meta_of, rep_budget=2, max_passes=3)
    owned = sorted(ci for g in folded for ci in g["clusters"])
    check("plan_passes respects max_passes and keeps ownership",
          len(folded) == 3 and owned == list(range(11)), f"{[g['clusters'] for g in folded]}")

    # 21. mask_result restricts records/coverage/pages_total to the scope
    rr = ReplayResult(format_id="t", pages_total=10)
    rr.records = [FieldRec("F", "a", None, page=1), FieldRec("F", "b", None, page=2),
                  FieldRec("F", "c", None, page=5)]
    rr.covered_pages = {0, 1, 4}
    rr.pages_with_fields = 3
    masked = codegen.mask_result(rr, {0, 1})
    check("mask_result scopes records and coverage",
          [r.field_name for r in masked.records] == ["a", "b"]
          and masked.covered_pages == {0, 1} and masked.pages_with_fields == 2
          and masked.pages_total == 2)

    # 22. pick_rotation_pages: cluster-stratified, uncovered-first, salt
    #     rotates the starting cluster, history excludes past picks
    tmp = tempfile.mkdtemp(prefix="rotpick_")
    with open(art(tmp, "clusters.json", True), "w", encoding="utf-8") as f:
        json.dump({"pages": 12, "representative_pages_1based": [1, 7],
                   "clusters": [{"pages": [0, 1, 2, 3, 4, 5]},
                                {"pages": [6, 7, 8, 9, 10, 11]}]}, f)
    rr2 = ReplayResult(format_id="t", pages_total=12)
    rr2.records = [FieldRec("F", "a", None, page=1), FieldRec("F", "b", None, page=2)]
    picks0 = codegen.pick_rotation_pages(tmp, rr2, core=[1, 7], history=set(), k=2, salt=0)
    picks1 = codegen.pick_rotation_pages(tmp, rr2, core=[1, 7], history=set(), k=1, salt=1)
    picks_h = codegen.pick_rotation_pages(tmp, rr2, core=[1, 7], history={3, 8}, k=2, salt=0)
    fallback = codegen.pick_rotation_pages("missing-dir", rr2, core=[1], history=set(), k=2)
    check("rotation picker stratifies and honors salt/history",
          picks0 == [3, 8] and picks1 == [8] and picks_h == [4, 9]
          and fallback == [3, 4],  # fallback spread: uncovered pages first
          f"p0={picks0} p1={picks1} ph={picks_h} fb={fallback}")

    # 22b. a scoped pass whose meta became unreadable must NOT invent doc-wide
    #      pages (masked pages_total is a scope SIZE, not a page range)
    scoped_fb = codegen.pick_rotation_pages("missing-dir", rr2, core=[1], history=set(),
                                            k=2, scope={"pages": {20, 21}})
    check("rotation fallback yields nothing under a scope", scoped_fb == [])

    # 23. run_document multi-pass orchestration: stale same-tag pass artifacts
    #     are purged (a rerun must not resurrect a failed pass's old CSV), the
    #     merged CSV holds only fresh rows, the WORST pass status labels the
    #     document, per-pass profiles slice (not accumulate) LLM calls, and
    #     the generalist pass 1 gets NO specialist note while tail passes do.
    #     The tail carries 8 reps / 30 content pages so the default thresholds
    #     genuinely split it.
    mp = tempfile.mkdtemp(prefix="mpass_")
    with open(art(mp, "clusters.json", True), "w", encoding="utf-8") as f:
        json.dump({"status": "ok", "pages": 60, "elapsed_s": 0.1,
                   "representative_pages_1based": [1, 2, 5],
                   "line_counts": [10] * 60,
                   "clusters": [
                       {"pages": list(range(0, 30)), "representatives": [4]},
                       {"pages": list(range(30, 60)),
                        "representatives": [30, 33, 36, 39, 42, 45, 48, 51]}]}, f)
    for stale in ("fields_codegen_tag_pass2.csv", "fields_codegen_tag_pass9.csv"):
        with open(art(mp, stale, True), "w", encoding="utf-8", newline="") as f:
            f.write("form_name,field_name,page\nSTALE,STALE,1\n")
    with open(art(mp, "codegen_prompt.txt", True), "w", encoding="utf-8") as f:
        f.write("stale single-pass prompt")

    def fake_extract(source, pdf):
        r_ = ReplayResult(format_id="t", pages_total=60)
        r_.records = [FieldRec("F", "a", None, page=1), FieldRec("F", "b", None, page=2),
                      FieldRec("F", "c", None, page=3)]
        r_.covered_pages = {0, 1, 2}
        r_.pages_with_fields = 3
        return r_

    # both passes take a revision round so the note/scope WIRING is pinned:
    # pass 1 revises on audit issues then converges; pass 2 crashes to budget
    s23 = Script([(make_verdict(), 5), (make_verdict(), 0),              # pass 1
                  (make_verdict(problems=["crash"], coverage=0, records=0), None),
                  (make_verdict(problems=["crash"], coverage=0, records=0), None)])
    s23.install()
    notes23, rev_notes23, val_mains23 = [], [], []

    def fake_gen_prompt(pdf, outdir, rep_pages=None, scope_note=""):
        notes23.append(scope_note)
        return "gen-prompt"

    def spy_revision(verdict, scope_note="", **kw):
        rev_notes23.append(scope_note)
        return "revise-prompt"

    inner_validate = rci.validate_generated

    def spy_validate(pdf, reply, outdir=None, scope=None):
        val_mains23.append(None if scope is None else scope.get("main"))
        return inner_validate(pdf, reply, outdir=outdir, scope=scope)

    rci.build_codegen_prompt = fake_gen_prompt
    rci.build_code_revision_prompt = spy_revision
    rci.validate_generated = spy_validate
    rci.run_extractor = fake_extract
    # exactly what main() passes: doc_t0 ONLY - the accumulator keys must be
    # created by run_document itself (a pre-seeded dict masked a live KeyError)
    prof23 = {"doc_t0": time.perf_counter()}
    try:
        row23 = rci.run_document(s23.transport, "model", "tag", "dockey", "doc.pdf",
                                 mp, max_versions=2, profile=prof23)
    finally:
        for name, fn in ORIGINALS.items():
            setattr(rci, name, fn)
    with open(art(mp, "fields_codegen_tag.csv"), encoding="utf-8", newline="") as f:
        merged_rows = [r["form_name"] for r in csv.DictReader(f)]
    check("multipass merges only fresh pass CSVs",
          merged_rows == ["F", "F", "F"], f"{merged_rows}")
    check("multipass purges stale artifacts",
          not os.path.exists(art(mp, "fields_codegen_tag_pass9.csv"))
          and not os.path.exists(art(mp, "codegen_prompt.txt")))
    check("multipass reports worst pass status and merged fields",
          row23["status"] == "needs_manual_template" and row23["multipass"] == 2
          and row23["fields"] == 3,
          f"status={row23['status']} fields={row23['fields']}")
    pcalls = [p["llm_calls"] for p in row23["passes"]]
    check("per-pass profiles slice llm calls (not cumulative)",
          pcalls == [4, 2] and len(prof23["llm_calls"]) == 6, f"{pcalls}")
    with open(art(mp, "codegen_trail_tag.json"), encoding="utf-8") as f:
        trail23 = json.load(f)
    check("merged trail carries pass numbers",
          sorted({c.get("pass") for c in trail23["cycles"]}) == [1, 2],
          f"{sorted({c.get('pass') for c in trail23['cycles']})}")
    check("generalist pass 1 gets no note; tail pass gets specialist note",
          notes23 == ["", codegen.SPECIALIST_NOTE], f"{[n[:40] for n in notes23]}")
    # pass 2 builds a revision prompt each cycle (incl. the final one the
    # budget then discards), hence two identical tail entries
    check("revision notes: empty for main pass, loop note for tail pass",
          rev_notes23 == ["", codegen.SPECIALIST_LOOP_NOTE,
                          codegen.SPECIALIST_LOOP_NOTE],
          f"{[n[:40] for n in rev_notes23]}")
    check("validate sees main=True for pass 1, False for pass 2",
          val_mains23 == [True, True, False, False], f"{val_mains23}")

    # 24. degenerate form grouping is structural, two-tier: an average "form" of
    #     <2 fields on a sizeable output violates the grouping definition (hard
    #     gate); <4 is fine-grained-forms advice (warning); healthy is silent;
    #     tiny outputs never hard-gate (one-field sections are plausible there)
    m24 = dict(engine="codegen", records=100, pages_total=50, pages_with_fields=40,
               definition_pages_seen=0, forms_nonempty_pct=100,
               labels_look_human_pct=100, oids_present_pct=0,
               oids_look_like_codes_pct=0, distinct_forms=60)
    hard = induction.gate_problems(m24)
    hard_warns = induction.gate_warnings(m24)
    band_warns = induction.gate_warnings({**m24, "distinct_forms": 30})
    quiet = induction.gate_warnings({**m24, "distinct_forms": 20})
    tiny = induction.gate_problems({**m24, "records": 15, "distinct_forms": 12})
    tiny_warns = induction.gate_warnings({**m24, "records": 15, "distinct_forms": 12})
    check("degenerate form grouping: hard gate at <2 fields/form",
          any(p.startswith("Degenerate form grouping") for p in hard)
          and not any("distinct form_names" in w for w in hard_warns),
          f"problems={hard}")
    check("fine-grained forms warn band and healthy silence",
          any("distinct form_names" in w for w in band_warns)
          and not any("distinct form_names" in w for w in quiet),
          f"band={band_warns} quiet={quiet}")
    check("tiny outputs stay in the advice tier",
          not any(p.startswith("Degenerate form grouping") for p in tiny)
          and any("distinct form_names" in w for w in tiny_warns),
          f"tiny_problems={tiny}")

    # 25. count_text_filters: membership blocklists + literal regex alternations
    #     are counted; structural code (geometry, char-class regexes) is not
    blocky = """
def extract(pages):
    out = []
    for pi, lines in pages:
        for ln in lines:
            t = ln.text.strip()
            if t in ['Name', 'Export Name', 'Type', 'Max length', 'Categories',
                     'Not Done', 'Reason Not Done', 'Test', 'Result',
                     'Interpretation', 'Parameter', 'Details']:
                continue
            if __import__('re').match(r'^(Asian|White|Unknown|Not Reported|Normal|Abnormal).*', t):
                continue
            out.append({"form_name": "F", "field_name": t, "page": pi + 1})
    return out
"""
    lean = """
import re
def extract(pages):
    out = []
    for pi, lines in pages:
        sizes = sorted({ln.size for ln in lines})
        for ln in lines:
            if ln.bold and ln.size >= sizes[-1] * 0.6 and re.search(r'[^\\W\\d_]', ln.text):
                out.append({"form_name": "F", "field_name": ln.text, "page": pi + 1})
    return out
"""
    named = """
BLOCKED_LIST = ['Header One', 'Header Two']
BLOCKED_SET = {'Header Three', 'Header Four'}
BLOCKED_TUPLE = ('Header Five', 'Header Six')
def extract(pages):
    return [line for _pi, lines in pages for line in lines
            if line.text not in BLOCKED_LIST
            and line.text not in BLOCKED_SET
            and line.text not in BLOCKED_TUPLE]
"""
    harmless_pipes = """
def extract(pages):
    display_template = 'alpha|beta|gamma|delta|epsilon'
    return []
"""
    nb = codegen.count_text_filters(blocky)
    nn = codegen.count_text_filters(named)
    nl = codegen.count_text_filters(lean)
    nh = codegen.count_text_filters(harmless_pipes)
    check("count_text_filters: inline/named blocklists counted, non-regex pipes ignored",
          nb >= 15 and nn == 6 and nl == 0 and nh == 0,
          f"blocky={nb} named={nn} lean={nl} harmless={nh}")

    # 25b. extract_source handles the STRATEGY-then-code reply format: a fenced
    #      block wins; bare source (incl. leading module-level constants) is kept
    #      verbatim; and an UNFENCED prose preamble is stripped by parseability,
    #      never by dropping real top-level code.
    fence = "```"
    es_fenced = ("STRATEGY:\nprose line\n- carry title forward\n\n" + fence
                 + "python\n# obs\ndef extract(pages):\n    return []\n" + fence
                 + "\ntrailing prose")
    es_bare_const = ("BLOCKLIST = ['a', 'b']\n"
                     "def extract(pages):\n    return []")
    es_prose = ("STRATEGY:\nsome prose\n## a heading\nmore prose\n\n"
                "import re\ndef extract(pages):\n    return []")
    check("extract_source: fenced block wins, prose dropped",
          codegen.extract_source(es_fenced)
          == "# obs\ndef extract(pages):\n    return []")
    check("extract_source: bare source with leading const kept verbatim",
          codegen.extract_source(es_bare_const) == es_bare_const)
    check("extract_source: unfenced prose preamble stripped to valid code",
          codegen.extract_source(es_prose)
          == "import re\ndef extract(pages):\n    return []")

    # 26. load_rep_pages labels reps by layout family: preamble groups the
    #     sample pages per family, headers carry the tag, and a specialist's
    #     only_pages subset re-letters within what it shows
    fam_dir = tempfile.mkdtemp(prefix="fams_")
    fam_meta = {"pages": 40,
                "representative_pages_1based": [3, 5, 20, 31],
                "title_context_pages_1based": [8, 28],
                "clusters": [
                    {"n_pages": 25, "pages": list(range(0, 25)),
                     "representatives": [2, 4]},
                    {"n_pages": 10, "pages": list(range(25, 35)),
                     "representatives": [19, 30]},
                    {"n_pages": 5, "pages": list(range(35, 40)),
                     "representatives": [36]}]}
    with open(art(fam_dir, "clusters.json", True), "w", encoding="utf-8") as f:
        json.dump(fam_meta, f)
    for p in (3, 5, 8, 20, 28, 31, 37):
        stem = "title" if p in (8, 28) else "rep"
        with open(art(fam_dir, f"{stem}_p{p}.txt", True), "w", encoding="utf-8") as f:
            f.write(f"line of page {p}\n")
    text26, idx26 = induction.load_rep_pages(fam_dir)
    ok_pre = ("family A (~25 pages of the document) - sample pages 3, 5" in text26
              and "family B (~10 pages of the document) - sample pages 20, 31" in text26)
    ok_hdr = ("--- page 5 of 40 | layout family A (~25 pages) ---" in text26
              and "--- page 31 of 40 | layout family B (~10 pages) ---" in text26)
    text26b, _ = induction.load_rep_pages(fam_dir, only_pages=[20, 37])
    ok_sub = ("--- page 20 of 40 | layout family A (~10 pages) ---" in text26b
              and "--- page 37 of 40 | layout family B (~5 pages) ---" in text26b)
    check("rep pages labeled by family (preamble + headers + scoped re-lettering)",
          ok_pre and ok_hdr and ok_sub and idx26 == [2, 4, 19, 30],
          f"pre={ok_pre} hdr={ok_hdr} sub={ok_sub}")

    # 27. title-context channel: selector ignores ubiquitous chrome, groups
    #     pages by changing repeated top context, excludes layout reps; loader
    #     presents those pages as context rather than layout representatives
    def ln(text, y=40, size=10, bold=False):
        return Line(text, 10, y, 300, y + 10, size, (0,), bold)

    title_lines = {}
    heights = {}
    for p in range(8):
        title = "Form Alpha" if p < 4 else "Form Beta"
        title_lines[p] = [
            ln("Invariant Annotated Document", y=15, bold=True),
            ln(title, y=55, size=14, bold=True),
            ln(f"Question {p}", y=400, bold=True),
        ]
        heights[p] = 800
    title_picks = pick_title_context_pages(
        title_lines, heights, exclude={0, 4}, max_pages=6)
    title_text = induction.load_title_context_pages(fam_dir)
    check("title context: changing repeated headers selected, reps excluded",
          title_picks == [1, 5]
          and "TITLE/FORM CONTEXT ONLY" in title_text
          and "title-context page 8" in title_text
          and "title-context page 28" in title_text
          and "layout family" not in title_text,
          f"picks={title_picks}")

    look_doc = fitz.open()
    for p in range(3):
        page = look_doc.new_page(width=600, height=800)
        page.insert_text((50, 50), f"FORM TITLE {p + 1}")
        page.insert_text((50, 500), f"BODY FIELD {p + 1}")
    look = codegen._title_lookback_text(look_doc, 3)
    look_doc.close()
    check("audit title lookback: two preceding top regions, no body fields",
          "page 1 TITLE LOOKBACK" in look
          and "page 2 TITLE LOOKBACK" in look
          and "FORM TITLE 1" in look and "FORM TITLE 2" in look
          and "BODY FIELD" not in look,
          look[:200])

    # 28. Form-name persistence is measured only where a page has multiple
    #     records. Shared page headings score 100%; per-field names score 0%
    #     and produce vocabulary-neutral structural feedback.
    shared = ReplayResult("codegen", pages_total=10, pages_with_fields=10)
    per_field = ReplayResult("codegen", pages_total=10, pages_with_fields=10)
    for p in range(1, 11):
        for i in range(3):
            shared.records.append(FieldRec(f"Form {p}", f"Field {p}-{i}", None,
                                           page=p))
            per_field.records.append(FieldRec(f"Annotation {p}-{i}",
                                              f"Field {p}-{i}", None, page=p))
    sm = induction.score(shared, "codegen")
    pm = induction.score(per_field, "codegen")
    pw = induction.gate_warnings(pm)
    check("form persistence: shared headings pass, per-field names warn",
          sm["form_same_page_persistence_pct"] == 100
          and pm["form_same_page_persistence_pct"] == 0
          and any("multi-field pages" in w for w in pw),
          f"shared={sm} per_field={pm} warnings={pw}")

    # 29. Documents below 900 pages keep the operator's budget; very large
    #     documents gain bounded capacity without any document-specific branch.
    check("size-scaled version budget is bounded and monotonic",
          rci.scaled_version_budget(5, 899) == 5
          and rci.scaled_version_budget(5, 900) == 6
          and rci.scaled_version_budget(5, 1799) == 6
          and rci.scaled_version_budget(5, 1800) == 7
          and rci.scaled_version_budget(5, 5000) == 7)

    # 30. Moderate literal matching remains revision advice; an extreme
    #     content-fitted blocklist is a hard problem and cannot be accepted.
    literals = ", ".join(repr(f"literal_{i}") for i in range(35))
    extreme_source = (
        f"BLOCKLIST = [{literals}]\n"
        "def extract(pages):\n"
        "    return [] if 'x' in BLOCKLIST else []\n"
    )
    old_run_extractor = codegen.run_extractor
    codegen.run_extractor = lambda _source, _pdf: shared
    try:
        extreme = codegen.validate_generated("unused.pdf", extreme_source)
    finally:
        codegen.run_extractor = old_run_extractor
    check("extreme literal blocklists hard-fail validation",
          any(p.startswith("Extreme content-fitted blocklist")
              for p in extreme["problems"]),
          f"problems={extreme['problems']}")

    # 31. Hybrid routing sends only grounded audits (including retry suffixes)
    #     to the optional audit model; generation/revision prompts stay put.
    audit_prompt = codegen.AUDIT_PROMPT_TEMPLATE.format(
        k=1, pages_and_records="--- page 1 AUDIT THIS PAGE ---")
    check("split-model routing recognizes only grounded audit prompts",
          rci.is_audit_prompt(audit_prompt)
          and rci.is_audit_prompt(audit_prompt + "\n\nReply again with JSON.")
          and not rci.is_audit_prompt(codegen.CODEGEN_PROMPT)
          and not rci.is_audit_prompt(codegen.CODE_REVISION_TEMPLATE))

    # 32. Single-model tags remain backward compatible; hybrid tags cannot
    #     collide merely because punctuation normalizes to the same slug.
    check("run tags preserve singles and disambiguate model pairs",
          rci.run_tag("gpt-5.2") == "gpt_5_2"
          and rci.run_tag("a:b", "c") != rci.run_tag("a_b", "c")
          and "__audit__" in rci.run_tag("sonnet", "gpt"))

    # 33. A failed rerun must not leave a previous successful export available
    #     for scoring. Purging is tag-scoped and leaves other model artifacts.
    purge_dir = tempfile.mkdtemp(prefix="purge_")
    stale = [
        "fields_codegen_tag.csv",
        "generated_extractor_tag.py",
        "codegen_trail_tag.json",
        "llm_calls_tag.jsonl",
        "timings_tag.json",
        "fields_codegen_tag_pass1.csv",
        "codegen_reply_tag_1.py",
    ]
    keep = ["fields_codegen_other.csv", "generated_extractor_tagged.py"]
    for fn in stale + keep:
        with open(art(purge_dir, fn, True), "w", encoding="utf-8") as f:
            f.write("x")
    rci.purge_tag_artifacts(purge_dir, "tag")
    check("same-tag artifact purge prevents stale export reuse",
          not any(os.path.exists(art(purge_dir, fn)) for fn in stale)
          and all(os.path.exists(art(purge_dir, fn)) for fn in keep))
    locked = art(purge_dir, "fields_codegen_tag.csv", True)
    with open(locked, "w", encoding="utf-8") as f:
        f.write("stale")
    old_remove = rci.os.remove
    rci.os.remove = lambda _path: (_ for _ in ()).throw(PermissionError("locked"))
    purge_failed = False
    try:
        rci.purge_tag_artifacts(purge_dir, "tag")
    except PermissionError:
        purge_failed = True
    finally:
        rci.os.remove = old_remove
    check("same-tag purge failure aborts instead of risking stale scoring",
          purge_failed)

    print(f"\n{len(failures)} failure(s)" if failures else "\nall stop-policy tests passed")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    try:
        main()
    finally:
        for name, fn in ORIGINALS.items():
            setattr(rci, name, fn)
