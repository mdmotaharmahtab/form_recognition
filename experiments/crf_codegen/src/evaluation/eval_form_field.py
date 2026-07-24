"""Evaluate the form+field pipeline (codegen scope) end to end.

1. Extraction quality (Rave doc only - the one with production ground truth):
   fuzzy-match extracted (form_name, field_name) pairs against digitized.csv.
2. Downstream OID resolution by NAME MAPPING (all finalized docs):
   map each extracted (form, field) to a library OID via ecs_index_data
   (form_field_value -> variable_name), lexical fuzzy matching locally
   (production would add the stored field embeddings on top).
   On the Rave doc, mapped OIDs are checked against the printed truth.
"""
import csv
import json
import os
import re
import sys

import fitz
from rapidfuzz import fuzz

# pipeline modules (common.py etc.) live in the sibling src/pipeline/ package
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from common import BASE, OUT_DIR, art, art_bucket_dir  # noqa: E402

GT = os.path.join(BASE, "data", "outputs", "outputs_from_384_201_00002_annotated_unique_crf", "digitized.csv")
INDEX_DATA = os.path.join(BASE, "data", "index", "ecs_index_data.csv")
RAVE_PDF = os.path.join(BASE, "data", "crf_forms", "384-201-00002_Annotated Unique CRF_04Nov2024.pdf")
RAVE_KEY = "384-201-00002_Annotated_Unique_CRF_04Nov2024"

FIELD_T = 85   # min field-name similarity for a pair match / mapping hit
FORM_T = 75    # min form-name similarity


def norm(s: str) -> str:
    # CAVEAT: strips everything non-ASCII, so this evaluation can only measure
    # English/Latin documents (which our sole ground-truth doc is). It says
    # NOTHING about non-Latin generality of the extraction pipeline itself.
    s = (s or "").lower()
    s = re.sub(r"\(.*?\)", " ", s)          # parentheticals: units, examples
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _export_csv(key: str) -> str | None:
    """Prefer the newest model-tagged export (fields_codegen_<model>.csv);
    fall back to the untagged prototype export."""
    folder = os.path.join(OUT_DIR, key)
    fields_dir = art_bucket_dir(folder, "fields")
    tagged = []
    if os.path.isdir(fields_dir):
        tagged = sorted(
            (os.path.join(fields_dir, f) for f in os.listdir(fields_dir)
             if f.startswith("fields_codegen_") and f.endswith(".csv")),
            key=os.path.getmtime, reverse=True)
    for path in tagged + [art(folder, "fields_codegen.csv")]:
        if os.path.exists(path):
            return path
    return None


def load_extracted(key: str) -> list[dict]:
    path = _export_csv(key)
    if not path:
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_gt() -> list[dict]:
    with open(GT, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_library() -> list[dict]:
    with open(INDEX_DATA, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    lib = []
    for r in rows:
        if not (r.get("form_field_value") and r.get("variable_name")):
            continue
        field = norm(r["form_field_value"])
        if not field:  # all-parenthetical / non-ASCII labels normalize away
            continue
        lib.append({"field": field,
                    "form": norm(r.get("form_name", "")),
                    "oid": r["variable_name"].strip(),
                    "field_raw": r["form_field_value"].strip(),
                    "form_raw": (r.get("form_name") or "").strip()})
    return lib


# --------------------------------------------------------------------------- #
# 1. extraction quality vs ground truth
# --------------------------------------------------------------------------- #
def eval_pairs_vs_gt() -> dict:
    gt = [(norm(r["form_name"]), norm(r["field_name"]), r["field_oid"].strip())
          for r in load_gt()]
    rows = load_extracted(RAVE_KEY)
    got = [(norm(r["form_name"]), norm(r["field_name"])) for r in rows]
    gt_pairs = sorted({(f, l) for f, l, _ in gt})
    got_pairs = sorted(set(got))

    def best_match(pair, pool):
        pf, pl = pair
        best = 0.0
        for qf, ql in pool:
            fl = fuzz.token_sort_ratio(pl, ql)
            if fl < FIELD_T:
                continue
            fm = fuzz.token_sort_ratio(pf, qf)
            if fm < FORM_T:
                continue
            best = max(best, (fl + fm) / 2)
        return best

    matched_gt = sum(1 for p in gt_pairs if best_match(p, got_pairs) > 0)
    matched_got = sum(1 for p in got_pairs if best_match(p, gt_pairs) > 0)
    return {
        "gt_distinct_pairs": len(gt_pairs),
        "extracted_distinct_pairs": len(got_pairs),
        "pair_recall_pct": round(100 * matched_gt / max(1, len(gt_pairs))),
        "pair_precision_pct": round(100 * matched_got / max(1, len(got_pairs))),
        "precision_breakdown": _precision_breakdown(rows, gt_pairs, best_match),
        "recall_breakdown": _recall_breakdown(gt_pairs, got_pairs, best_match),
    }


def _recall_breakdown(gt_pairs: list, got_pairs: list, best_match) -> dict:
    """Classify every truth pair the export lacks.

    Buckets, checked in order:
      no_oid_in_truth      - the truth row itself carries no OID (page footer
                             '01.025 GMK (432)' recorded once per form, plus a
                             few OID-less option rows). Excluded because they
                             are page furniture, NOT because OID-less fields
                             lack downstream value - production writes
                             LLM-generated rules for unmatched fields from
                             their names alone (review_table.py)
      different_form       - the field name WAS extracted (>= FIELD_T) but
                             under a form that misses the FORM_T bar
      near_miss_wording    - best in-form match lands at 70..84: extracted,
                             but the truth wording (numbering / embedded
                             option text) keeps it under the fuzzy bar
      printed_not_extracted- some page prints the label yet no record matches:
                             the real parser misses
      label_not_printed    - the label appears on no page at all (derived /
                             split fields only the production tool knows)
    Also reports recall restricted to OID-bearing truth pairs - the only
    pairs the downstream name->OID join can ever use."""
    oid_of: dict[tuple, str] = {}
    for r in load_gt():
        p = (norm(r["form_name"]), norm(r["field_name"]))
        if r["field_oid"].strip():
            oid_of[p] = r["field_oid"].strip()

    doc = fitz.open(RAVE_PDF)
    book_lines = sorted({norm(ln) for page in doc
                         for ln in page.get_text("text").splitlines() if norm(ln)})
    doc.close()

    missed = [p for p in gt_pairs if best_match(p, got_pairs) == 0]
    buckets: dict[str, list] = {k: [] for k in (
        "no_oid_in_truth", "different_form", "near_miss_wording",
        "printed_not_extracted", "label_not_printed")}
    for pf, pl in missed:
        if (pf, pl) not in oid_of:
            buckets["no_oid_in_truth"].append((pf, pl))
        elif any(fuzz.token_sort_ratio(pl, ql) >= FIELD_T for _, ql in got_pairs):
            buckets["different_form"].append((pf, pl))
        elif max((fuzz.token_sort_ratio(pl, ql) for qf, ql in got_pairs
                  if fuzz.token_sort_ratio(pf, qf) >= FORM_T), default=0) >= 70:
            buckets["near_miss_wording"].append((pf, pl))
        elif any(fuzz.token_sort_ratio(pl, ln) >= FIELD_T for ln in book_lines):
            buckets["printed_not_extracted"].append((pf, pl))
        else:
            buckets["label_not_printed"].append((pf, pl))

    oid_pairs = [p for p in gt_pairs if p in oid_of]
    oid_found = sum(1 for p in oid_pairs if best_match(p, got_pairs) > 0)
    out: dict = {"missed_total": len(missed)}
    for k, v in buckets.items():
        out[k] = len(v)
        if v:
            out[k + "_examples"] = [" | ".join(p) for p in v[:4]]
    out["oid_bearing_truth_pairs"] = len(oid_pairs)
    out["oid_bearing_found"] = oid_found
    out["oid_bearing_recall_pct"] = round(100 * oid_found / max(1, len(oid_pairs)))
    return out


def _precision_breakdown(rows: list[dict], gt_pairs: list, best_match) -> dict:
    """Classify every extracted pair that matches nothing in the truth.

    'Appendix-only' pairs are those seen exclusively on the Rave book's
    data-dictionary appendix (its largest layout cluster - 249 spec-table
    pages). This is an eval-side classification specific to the ground-truth
    document, used to show how much of the precision gap is that single
    extraction decision rather than misread fields."""
    pair_pages: dict[tuple, set] = {}
    pair_raw: dict[tuple, tuple] = {}
    for r in rows:
        p = (norm(r["form_name"]), norm(r["field_name"]))
        if r.get("page"):
            pair_pages.setdefault(p, set()).add(int(r["page"]))
        pair_raw.setdefault(p, (r["form_name"], r["field_name"]))

    meta_path = art(os.path.join(OUT_DIR, RAVE_KEY), "clusters.json")
    appendix_pages: set[int] = set()
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            clusters = json.load(f)["clusters"]
        largest = max(clusters, key=lambda c: len(c["pages"]))
        appendix_pages = {p + 1 for p in largest["pages"]}

    gt_forms = sorted({f for f, _ in gt_pairs})
    appendix_only, field_wording, form_absent = [], [], []
    for p in sorted(pair_pages):
        if best_match(p, gt_pairs) > 0:
            continue
        if appendix_pages and pair_pages[p] <= appendix_pages:
            appendix_only.append(p)
        elif any(fuzz.token_sort_ratio(p[0], qf) >= FORM_T for qf in gt_forms):
            field_wording.append(p)
        else:
            form_absent.append(p)

    # counterfactual: the same export with appendix-only pairs excluded
    kept = [p for p in pair_pages
            if not (appendix_pages and pair_pages[p] <= appendix_pages)]
    cf_prec = round(100 * sum(1 for p in kept if best_match(p, gt_pairs) > 0)
                    / max(1, len(kept)))
    cf_rec = round(100 * sum(1 for g in gt_pairs if best_match(g, kept) > 0)
                   / max(1, len(gt_pairs)))

    def ex(pairs, n=4):
        return [" | ".join(pair_raw[p]) for p in pairs[:n]]

    return {
        "unmatched_total": len(appendix_only) + len(field_wording) + len(form_absent),
        "appendix_code_rows": len(appendix_only),
        "appendix_examples": ex(appendix_only),
        "field_wording_gaps": len(field_wording),
        "field_wording_examples": ex(field_wording),
        "forms_not_in_truth": len(form_absent),
        "excluding_appendix": {"pair_precision_pct": cf_prec,
                               "pair_recall_pct": cf_rec},
    }


# --------------------------------------------------------------------------- #
# 2. name -> OID mapping via the library (form-first funnel, oid_mapping.py)
# --------------------------------------------------------------------------- #
def eval_mapping(keys: list[str], llm=None) -> list[dict]:
    """Run the funnel per document. With llm=None abstained pairs stay
    ABSTAIN (deterministic-only); with an llm they resolve via the ranker."""
    from oid_mapping import ABSTAIN, MAPPED, map_pairs

    lib = load_library()
    # keep the first NON-EMPTY OID per pair: an empty-OID truth row must not
    # shadow a later row that carries the real OID (footer stamps do this)
    gt_lookup = {}
    for r in load_gt():
        oid = r["field_oid"].strip().upper()
        if oid:
            gt_lookup.setdefault((norm(r["form_name"]), norm(r["field_name"])), oid)

    out = []
    for key in keys:
        rows = load_extracted(key)
        if not rows:
            continue
        pairs = sorted({(norm(r["form_name"]), norm(r["field_name"])) for r in rows})
        results = map_pairs(pairs, lib, llm=llm)

        mapped = [r for r in results if r.status == MAPPED]
        abstained = [r for r in results if r.status == ABSTAIN]
        correct, checkable, examples = 0, 0, []
        if key == RAVE_KEY:
            for r in mapped:
                truth = gt_lookup.get((r.form, r.field))
                if not truth:
                    continue
                checkable += 1
                if r.oid.upper() == truth:
                    correct += 1
                elif len(examples) < 8:
                    examples.append(f"{r.field!r} -> mapped {r.oid} via {r.via}, printed truth {truth}")

        rec = {"doc": key[:52], "distinct_pairs": len(pairs),
               "mapped": len(mapped),
               "mapped_by": {v: sum(1 for r in mapped if r.via == v)
                             for v in sorted({r.via for r in mapped})},
               "abstained_unresolved": len(abstained),
               "mapped_pct": round(100 * len(mapped) / max(1, len(pairs)))}
        if key == RAVE_KEY:
            # accuracy denominator: mapped pairs whose (form, field) exists in
            # the printed truth. Mapped-but-uncheckable pairs are reported so
            # the accuracy claim states its own blind spot.
            rec.update(checkable_against_truth=checkable,
                       mapped_but_uncheckable=len(mapped) - checkable,
                       mapping_accuracy_pct=round(100 * correct / max(1, checkable)),
                       accuracy_note="accuracy over the truth-checkable subset "
                                     "of mapped pairs, not over all mappings",
                       mismatch_examples=examples)
        out.append(rec)
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ranker-model", default=None,
                    help="resolve abstained pairs with this LLM via the cursor "
                         "CLI (e.g. claude-4.5-sonnet); omit for deterministic-only")
    args = ap.parse_args()

    llm = None
    if args.ranker_model:
        from run_cli_induction import call_cli, find_agent
        agent_bin = find_agent()
        llm = lambda prompt: call_cli(agent_bin, args.ranker_model, prompt)

    keys = [k for k in sorted(os.listdir(OUT_DIR))
            if os.path.isdir(os.path.join(OUT_DIR, k)) and _export_csv(k)]
    report = {
        "extraction_vs_ground_truth_rave": eval_pairs_vs_gt(),
        "name_to_oid_mapping": eval_mapping(keys, llm=llm),
        "mapping_logic_note": "form-first funnel (oid_mapping.py): form scoping at "
                              "partial_ratio>=70 as in review_table.get_standard_crf, "
                              "field>=85 within the form, every candidate-bearing pair "
                              "judged by the LLM ranker (pick a listed OID or refuse)"
                              + ("" if llm else " -- ranker OFF this run: clear "
                                 "leaders map lexically, near-ties stay abstained"),
        "library_size_note": "ecs_index_data has only 286 Standard rows; mapping coverage is bounded by library breadth, not extraction quality.",
    }
    with open(os.path.join(OUT_DIR, "evaluation_form_field.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
