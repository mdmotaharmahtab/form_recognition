"""Compare OID-matching strategies on the Rave book against printed truth.

A  naive field-first     : field>=85 gate, score 0.75*field+0.25*form, best row
                           anywhere in the library (the strawman; never shipped)
B  form-scoped           : form>=75 required FIRST, candidates limited to that
                           form's rows, then field>=85 within them
C  form-scoped + abstain : as B, but abstain when two candidate OIDs score
                           within 5 points (the ambiguity an LLM ranker would judge)
D  shipped funnel        : oid_mapping.map_pairs -- prod-aligned form scoping
                           (partial_ratio>=70, as review_table.get_standard_crf),
                           field>=85 in-form, near-ties resolved by a live LLM
                           ranker (pass --ranker-model to enable)

A/B/C are frozen design evidence for the deep-dive doc; D is the implementation.
"""
import argparse

from rapidfuzz import fuzz

from eval_form_field import RAVE_KEY, load_extracted, load_gt, load_library, norm
from oid_mapping import MAPPED, UNMAPPED, map_pairs

FIELD_T, FORM_T = 85, 75

lib = load_library()
gt_lookup = {}
for r in load_gt():
    oid = r["field_oid"].strip().upper()
    if oid:  # empty-OID truth rows must not shadow the real OID for a pair
        gt_lookup.setdefault((norm(r["form_name"]), norm(r["field_name"])), oid)
pairs = sorted({(norm(r["form_name"]), norm(r["field_name"]))
                for r in load_extracted(RAVE_KEY)})
print(f"pairs={len(pairs)}  truth-checkable universe={sum(1 for p in pairs if gt_lookup.get(p))}")


def variant_a(form, field):
    best_oid, best = None, 0.0
    for e in lib:
        fl = fuzz.token_sort_ratio(field, e["field"])
        if fl < FIELD_T:
            continue
        score = 0.75 * fl + 0.25 * fuzz.token_sort_ratio(form, e["form"])
        if score > best:
            best_oid, best = e["oid"], score
    return best_oid


def form_scoped_candidates(form, field):
    cands = []
    for e in lib:
        if fuzz.token_sort_ratio(form, e["form"]) < FORM_T:
            continue
        fl = fuzz.token_sort_ratio(field, e["field"])
        if fl >= FIELD_T:
            cands.append((fl, e["oid"]))
    return sorted(cands, reverse=True)


def variant_b(form, field):
    c = form_scoped_candidates(form, field)
    return c[0][1] if c else None


def variant_c(form, field):
    c = form_scoped_candidates(form, field)
    if not c:
        return None
    distinct = {oid for _, oid in c}
    if len(distinct) > 1 and c[0][0] - max(s for s, o in c if o != c[0][1]) < 5:
        return "ABSTAIN"
    return c[0][1]


for name, fn in (("A field-first (strawman)", variant_a),
                 ("B form-scoped", variant_b),
                 ("C form-scoped+abstain", variant_c)):
    mapped = checkable = correct = abstained = 0
    wrong_examples = []
    for form, field in pairs:
        oid = fn(form, field)
        if oid is None:
            continue
        if oid == "ABSTAIN":
            abstained += 1
            continue
        mapped += 1
        truth = gt_lookup.get((form, field))
        if truth:
            checkable += 1
            if oid.upper() == truth:
                correct += 1
            elif len(wrong_examples) < 3:
                wrong_examples.append(f"{form[:28]}|{field[:24]} -> {oid} (truth {truth})")
    acc = round(100 * correct / checkable) if checkable else 0
    print(f"\n{name}: mapped={mapped} ({round(100*mapped/len(pairs))}%) "
          f"abstained={abstained} checkable={checkable} accuracy={acc}%")
    for w in wrong_examples:
        print("   wrong:", w)


# --------------------------------------------------------------------------- #
# D0/D: the shipped funnel (oid_mapping.py). D0 is deterministic-only (isolates
# the partial_ratio>=70 scoping change from the ranker); D adds the live ranker.
# --------------------------------------------------------------------------- #
ap = argparse.ArgumentParser()
ap.add_argument("--ranker-model", default=None,
                help="e.g. claude-4.5-sonnet; omit to stop at D0")
args = ap.parse_args()


def score_funnel(label: str, llm) -> None:
    results = map_pairs(pairs, load_library(), llm=llm)
    mapped_r = [r for r in results if r.status == MAPPED]
    checkable = correct = 0
    wrong_examples = []
    for r in mapped_r:
        truth = gt_lookup.get((r.form, r.field))
        if not truth:
            continue
        checkable += 1
        if r.oid.upper() == truth:
            correct += 1
        elif len(wrong_examples) < 5:
            wrong_examples.append(f"{r.form[:28]}|{r.field[:24]} -> {r.oid} "
                                  f"via {r.via} (truth {truth})")
    acc = round(100 * correct / checkable) if checkable else 0
    by_via = {v: sum(1 for r in mapped_r if r.via == v)
              for v in sorted({r.via for r in mapped_r})}
    abstained = sum(1 for r in results if r.status not in (MAPPED, UNMAPPED))
    print(f"\n{label}: mapped={len(mapped_r)} ({round(100*len(mapped_r)/len(pairs))}%) "
          f"by={by_via} abstained={abstained} "
          f"checkable={checkable} accuracy={acc}%")
    for w in wrong_examples:
        print("   wrong:", w)


score_funnel("D0 shipped funnel, deterministic (no ranker)", None)
if args.ranker_model:
    from run_cli_induction import call_cli, find_agent
    agent_bin = find_agent()
    score_funnel(f"D  shipped funnel + ranker({args.ranker_model})",
                 lambda prompt: call_cli(agent_bin, args.ranker_model, prompt))
