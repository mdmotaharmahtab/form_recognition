Below is the review. References are `file:symbol`. I did not run the code (no repo on disk; the source is inline and self-contained). Severities: **[blocker]**, **[should-fix]**, **[acceptable-with-comment]**.

## 1. Hardcoding & corpus priors

The shipped stage-0 path (`generic_profile.py`) is genuinely well-defended (word-blind tokens, per-document damping/theta). The remaining priors:

- **[should-fix]** `run_cli_induction.py:DEFAULT_DOCS` — hardcodes the author's 3 sample document keys (`384-201-00002…`, `QSC302573…`, `MAC186…`). It's a local-harness default (overridable with `--all-docs`), but it encodes the author's corpus into shippable code. Fix: default to all staged PDFs; keep the 3 keys behind an explicit `--only`.
- **[should-fix]** `build_dataiku_notebook.py:CONFIG_CELL` — `LLM_ID = 'azureopenai:…:gpt-5.2'` contradicts every prose claim of "Claude Sonnet 4.5" (`INTRO_MD`, `run_cli_induction` docstring, `cost_report` price defaults). Also `INPUT_FOLDER='3UkrB0N9'` is a specific tenant folder id. These are config, but the model mismatch means the "production model" is undefined. Fix: reconcile the model, and make the folder id an obvious placeholder.
- **[acceptable-with-comment]** `generic_profile.py:_charclass` — the `code` branch (`" " not in t and (digits>0 or t.upper()==t)`) and the caseless split (`len(t.split())>=3 or len(t)>=12`) are Latin/CJK-flavored, but they only affect a bucketing token; a wrong bucket costs an extra representative page, not a wrong extraction (as the module argues). Fine, but the 12-char / 3-word constant is a language prior worth a one-line comment (it already has one).
- **[acceptable-with-comment]** `induction.py:CODE_SHAPE = ^[A-Z][A-Z0-9_]{1,39}$` and `labels_look_human_pct` — Latin-uppercase code shape. It only feeds a *warning*, and human-label detection uses `re.search(r"[^\W\d_]")` (unicode-aware), so non-Latin labels still count as human. Acceptable.
- **[acceptable-with-comment]** `replay.py` engine defaults (`oid_header="Include"`, `"Name"/"Export Name"`, `column_x_max=320`, `line_number_x_min=460`, `data_number_x_min=480`) are hard corpus priors, but the file is explicitly LEGACY and production imports only `FieldRec`/`ReplayResult` from it. Confirm no production path ever calls `replay()`/`ENGINES` — it doesn't. OK.
- **[acceptable-with-comment]** `common.py:doc_key` / `oid_mapping`+`eval_*` `_norm`/`norm` strip non-ASCII (`[^A-Za-z0-9…]`). For `doc_key` this is defended (hash fallback). For `_norm` it means OID mapping/eval coverage ≈0% on non-Latin docs — but that's downstream of extraction scope and is documented as a caveat. Acceptable given scope.

Prompt text (`codegen.py:CODEGEN_PROMPT`, `AUDIT_PROMPT_TEMPLATE`, etc.): English "Yes/No/Unknown" examples are explicitly annotated "apply the concept in the document's language." No vendor/format names leak. Prose is in English but that's fine for an LLM. **No blockers in prompt text.**

## 2. Bugs

- **[should-fix]** `codegen.py:cluster_stats` — docstring says "Uses PRE-dedup page coverage," but `rec_pages` counts `result.records` which is **post-dedup** (`dedup()` already ran in `run_extractor`). `coverage_pct` is unaffected (within-page dedup doesn't change the covered *set*), but the per-cluster `records` count is post-dedup, contradicting the comment. Harmless to coverage logic; fix the comment or the source.
- **[acceptable-with-comment]** `run_cli_induction.py:pick_audit_pages` fixes the audit sample from the **first** gate-passing version's coverage. If that version has poor coverage, later much-better versions are judged on a stale, low-coverage sample — under-representing newly covered regions in the issue count that drives revision/stopping. By-design for comparability, but a real blind spot.
- No state leaks found across documents/attempts: `sandbox_runner.py` is a fresh process per run; `induce_document` state is all local; Dataiku FETCH_CELL/import cell rehydrate cleanly. Good.
- Exception handling is deliberate (generated-code failures → revision feedback; harness failures separated in `validate_generated`). No accidental swallowing spotted.

## 3. Logical flow

- **[should-fix]** `codegen.py:improves` coverage-retention floor (`retained < cov_floor*len(best_pages)` on the page **set**) can **reject a genuinely-better program**. If the incumbent over-covered furniture/scanned pages and the fix correctly *stops* extracting them, the fix retains <90% of the incumbent's page set → never counts as an improvement, regardless of lower audit issues. Combined with `induce_document`'s `converged` requiring `improved`, a correct precision fix can be permanently blocked and the worse incumbent exported. Consider exempting page-set loss when audit issues strictly drop, or measuring retention against *audit-confirmed* pages only.
- **[acceptable-with-comment]** Plateau/gate-fail exemption in `induce_document` is sound (two consecutive gate-failed versions don't count as diminishing returns; bounded by `--max-versions`). The `converged` branch correctly refuses to accept a clean-but-coverage-dropping version. Fine, modulo the item above.
- Confirm-extension bookkeeping (`versions += 1`, pre-extension scored/trailed first, `prev` set to pre-extension) is correct and matches the documented intent.

## 4. Edge cases vs generality

- **Degenerate clustering** (every page unique): `weak_clusters` needs ≥4-page clusters, so per-cluster feedback is empty; `build_uncovered_feedback` correctly backfills doc-wide holes. Good. But `select_theta` is O(n²) per grid point on genuinely heterogeneous 1000-page docs → minutes, unbounded by any timeout (stage-0 is not sandboxed). Documented; still a real cost/DoS surface on adversarial input.
- **Generators from `extract()`**: `sandbox_runner.py:main` materializes via `list(raw)`. Good.
- **Scanned/partial-text**: `stage0_cluster.run` proceeds at ≥20% text pages; scanned pages yield empty lines → auditor returns empty for them. OK, but a partially-scanned book can still be `status ok` and silently miss all image-only fields (surfaced only via `text_layer_pct`). Documented.
- **Rotated/landscape pages**: `page_profile`/`page_fingerprint` normalize `x0` by `page_width`; fitz rotation isn't accounted for. Minor edge; profiles may split, not misextract.
- **Empty/encrypted/tiny**: handled (`stage0` `no_pages`/`encrypted`; blank clusters excluded from reps; `gate_problems` <5-record floor only ≥20 pages). Good.
- **Unicode**: regexes are unicode-aware by default. Good.

## 5. Sandbox & safety

- **[acceptable-with-comment / blocker for untrusted input]** `sandbox_runner.py` restricted namespace is **not** a security boundary — `().__class__.__bases__[0].__subclasses__()` reaches `os`/`subprocess`, and a hostile PDF can prompt-inject the code-writing round. This is explicitly acknowledged in the module's THREAT MODEL and mitigated only by "run in an unprivileged, network-less container." That mitigation is not enforced anywhere in code. For the stated generality claim (any vendor PDF, i.e. untrusted), this is a real blocker unless the container requirement is guaranteed operationally.
- **[should-fix]** `_ALLOWED_MODULES` omits commonly-written harmless modules: `typing`, `dataclasses`, `enum`, `datetime`. A legitimate parser doing `from typing import List` or `import datetime` dies with `ImportError` → wasted revision cycle. The prompt lists allowed modules, but models habitually import `typing`. Add at least `typing`.
- **[acceptable-with-comment]** Resource limits: `RLIMIT_AS` 4GB Linux-only (Windows/local unprotected); no CPU/`RLIMIT_CPU` limit — only the 300s parent wall-timeout (`run_extractor`). `MAX_RECORDS=200k` caps serialization. `proc.kill()` doesn't reap grandchildren if a program escaped the namespace and forked. Fine for the intended Linux/Dataiku target; note the local/Windows gap.
- `tempfile.NamedTemporaryFile(dir=HERE)` writes generated source into the module dir; unique per call and cleaned in `finally`. OK.

## 6. Consistency (harness vs documented intent)

- **[should-fix]** Production model identity is inconsistent (see §1: `gpt-5.2` in the notebook vs "Claude Sonnet 4.5" everywhere in prose and `cost_report` prices). Pick one.
- **[acceptable-with-comment]** `subagent_bridge.py:cmd_validate_code` runs gates + one prompt only — no confirm/audit rounds. Explicitly documented as a manual tool, and warning semantics are aligned with production. OK, but a program "ok" via the bridge is not production-accepted; the docstring says so.
- **[acceptable-with-comment]** `subagent_bridge.py:pdf_for` has no `doc_key`-collision guard, unlike both real drivers (`run_cli_induction.main`, Dataiku FETCH_CELL). Local tool only.
- **[acceptable-with-comment]** `common.cluster_pages`/`page_fingerprint` (v1) and `replay.py` engines are retained as reference/legacy and clearly labeled; verified they are not on the production path. `induction.py`'s recipe path (`induce_recipe`, `validate_recipe`) is legacy but `score`/`gate_problems`/`gate_warnings`/`load_rep_pages` are shared with production — those are corpus-free. Consistent.
- `group_rows` in `common.py` appears unused by the shipped path — dead code (not a bug).

### Top priorities
1. Enforce/verify the container isolation for `sandbox_runner.py` (§5) — the only item that directly breaks the "any untrusted CRF" claim.
2. Fix `improves` coverage floor so correct precision fixes aren't rejected (§3).
3. Resolve the production-model inconsistency and remove `DEFAULT_DOCS`/tenant folder priors from shippable code (§1, §6).
4. Add `typing` (and likely `datetime`) to the sandbox allowlist (§5).
