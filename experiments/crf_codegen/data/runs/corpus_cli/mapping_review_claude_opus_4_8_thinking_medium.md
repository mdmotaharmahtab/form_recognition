## 1. BUGS

- **`rank_cases` — no atomicity on `llm` raising mid-batch.** `rank_cases` (oid_mapping.py) mutates `MapResult`s chunk-by-chunk in place; `map_pairs` doesn't wrap it. If `llm()` throws on chunk *k*, chunks `0..k-1` are already flipped to MAPPED/UNMAPPED while chunk *k..* keep their **lexical** verdict. Any lexically-MAPPED case in the unjudged tail ships as mapped without ever being ranked — directly violating "EVERY candidate-bearing case is judged." In Dataiku `call_mesh` re-raises after retries, so this is a live path. Judge into a local dict and commit only after the full loop succeeds, or mark unjudged→UNMAPPED on failure.

- **`parse_ranker_reply` greedy regex drops whole chunks.** `re.search(r"\[.*\]", reply, re.DOTALL)` spans first `[` to last `]`. Any bracket in prose/markdown before the real array (`"notes [see below] [{...}]"`) yields an unparseable span → `json.loads` fails → `{}` → **all 40 cases in the chunk silently become UNMAPPED**. Safe-direction but a large coverage cliff, and non-obvious. Also fails if the model wraps output as `{"results":[...]}` with any second array. Prefer a balanced/first-object scan or try `json.loads(reply)` first.

- **`gt_lookup` first-wins shadows real OIDs.** In both `eval_form_field.eval_mapping` and `oid_matching_experiment` the lookup is `setdefault(..., field_oid.strip().upper())` **including empty strings**. If the first truth row for a normalized `(form,field)` has an empty OID, it permanently shadows a later row that has the real OID → that pair is dropped from `checkable` (`if not truth: continue`). Correct maps go uncredited, wrong maps unpenalized. Skip empty OIDs when populating, and prefer non-empty on collision.

- **Empty-normalized library rows survive the filter.** `load_library` (and notebook `_lib` comprehension) filters on the *raw* `form_field_value`/`variable_name` being truthy, but stores `field=norm(...)`. A value that is all-parenthetical/non-ASCII normalizes to `""` yet is kept. Then `token_sort_ratio(field, "")` (and empty-vs-empty printed fields) is an untested match surface → potential spurious candidate. Filter on the normalized `field` being non-empty.

## 2. SAFETY OF THE DESIGN CLAIM (a wrong OID CAN slip through)

- **"pick-or-refuse" only bounds the OID to the shortlist, not to the correct form.** `scope_form` admits rows from *every* form ≥70, and `map_field` builds one shortlist across all of them. The shortlist therefore legitimately contains wrong-form OIDs; if the ranker echoes one, a mismap ships. This is exactly the measured "Contact Method @100 from the wrong follow-up form" failure. The gate does not structurally prevent mismaps — it delegates the entire safety guarantee to ranker judgment. Do not state the design "refuses to mismap"; it *reduces* mismaps.

- **Single-candidate confirm bias is real and demonstrated.** The lone-candidate path presents the model one OID at similarity 100 with a leading question — the known lexical-layer errors were exactly lone candidates the gate passed. `build_ranker_prompt` never tells the model these candidates may come from *different forms*, so on a lone wrong-form candidate there is no contrastive signal. Consider explicitly flagging cross-form shortlists / stating "the printed form may not exist in the library."

- **Ranker "confirm" can silently switch the OID.** In `rank_cases`, a lexically-MAPPED case (`was_tie=False`) whose ranker returns a *different* shortlist OID gets `via="ranker-confirm"` while `c.oid` changes. The label says confirm but the mapping was altered — misleading for audit and it lets a clear-leader be overridden by a rival.

## 3. PROD ALIGNMENT (`partial_ratio>=70` scoping)

- **Semantic mismatch with `get_standard_crf`.** `scope_form` is a per-row OR filter (`partial_ratio(form, e["form"]) >= 70` for each row). `process.extract`-style `get_standard_crf` selects the **single best** standard form, then restricts to that form's rows. `partial_ratio` at 70 is very permissive (short printed form as substring of many library forms → many at 100), so this over-scopes across forms and *manufactures* the cross-form shortlist that section 2 warns about. The comment "the exact scorer/threshold production already uses" overstates alignment: same scorer/threshold ≠ same set semantics (argmax-one-form vs threshold-many-forms). To actually mirror prod, pick the best-matching form first, then filter rows to it.

## 4. EDGE CASES

- **Missing `form_name` column → silent 0% mapping.** Notebook asserts only `{'form_field_value','variable_name'}`. If `form_name` is absent, every library `form` is `""`, `scope_form` returns nothing, and every pair is UNMAPPED with no error — looks like "safe abstain," is actually total failure. Warn when `form_name` is missing/empty for most rows.
- **>5 near-ties:** shortlist truncated to top-5 by score; the true OID at rank 6 is dropped, so ranker can only pick among 5 (which may all be wrong). Safe only if the ranker refuses. Note but acceptable.
- **Duplicate OID, different labels:** `per_oid` keeps the best-scoring row's label; the alternate human label is hidden from the ranker prompt. Minor prompt-fidelity loss.
- **Empty/whitespace printed name:** relies on `rapidfuzz` returning 0 for empty inputs; combined with the empty-normalized-library rows above, empty-vs-empty is an untested match. Guard explicitly rather than trusting scorer behavior.
- **`int(item.get("case"))` / non-string `oid`:** handled acceptably (invalid → skip/None).

## 5. EVAL VALIDITY

- **Accuracy is NOT "of what it maps."** `eval_mapping` computes `correct/checkable`, where `checkable` excludes any mapped pair whose `(form,field)` is absent from `gt_lookup`. A mapping to a pair the ground truth doesn't contain (a spurious/hallucinated pair) is invisible — never counted wrong. So a mismap on an out-of-truth pair cannot lower the 94%. The docstring/`mapping_logic_note` phrasing "accuracy-of-what-it-maps" is inaccurate; it's "accuracy over the truth-checkable subset of what it maps." State the denominator, and report how many mapped pairs were *un*checkable.
- **Ladder C→D conflates three changes.** D swaps the form scorer (`token_sort_ratio`→`partial_ratio`), lowers the threshold (75→70), *and* adds the ranker, vs C. Any C→D delta cannot be attributed to the ranker alone. If the ladder is "design evidence," add a D-minus (partial_ratio/70 scoping, no ranker) rung to isolate the scoping change from the ranker change.
- **Abstain accounting:** with `llm` set, ranker forces every candidate case to MAPPED/UNMAPPED, so `abstained_unresolved` is always 0 in ranker runs — fine, but means the field only reports something in deterministic mode; worth a note so a 0 isn't read as "no ambiguity."

## 6. NOTEBOOK CELL

- **No per-doc error isolation for Mesh.** `call_mesh` re-raises after retries; it's called inside `map_pairs` inside the `for _key` loop with no try/except. One transient Mesh failure on doc *N* aborts the whole batch: docs `<N` have CSVs, doc *N* and all `>N` get nothing, and no summary/tag of what completed. Wrap the per-`_key` body in try/except, log the failure, continue.
- **Tag mismatch fails silently.** The cell reads only `fields_codegen_<tag>.csv` (exact tag), unlike eval's `_export_csv` newest-tagged fallback. A wrong/missing `tag` → every `continue` → "library entries: N" then nothing mapped, no warning. Print how many `_key`s were skipped for missing source.
- **Combined with §1/§2:** a malformed Mesh reply → greedy-regex whole-chunk drop → 40 pairs silently UNMAPPED in the written CSV with no diagnostic. At minimum record parse failures per chunk.
- Rerun hygiene (`sys.modules.pop('oid_mapping')` + bundle-path assert) and `fillna('')` handling are correct.

No changes made — review only. Want me to turn the section 1–2 items (atomic `rank_cases`, robust reply parsing, empty-OID/empty-field filtering) into a todo list and implement?
