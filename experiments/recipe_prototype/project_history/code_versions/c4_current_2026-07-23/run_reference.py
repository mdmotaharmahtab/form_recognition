"""REFERENCE RUN (engine smoke-test only - not the production flow).

Replays the hand-authored reference recipes over data/crf_forms to verify the
replay engines and to produce a baseline the LLM-induced recipes can be compared
against. The production flow (run_induction.py) treats every document as an
unknown format and asks the LLM to induce the recipe from stage-0 representative
pages - it never sees these reference recipes."""
import argparse
import csv
import glob
import json
import os

from common import OUT_DIR, doc_key, list_root_pdfs
from replay import detect_format, replay

RECIPE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference_recipes")


def load_recipes(recipe_dir: str) -> list[dict]:
    out = []
    for path in sorted(glob.glob(os.path.join(recipe_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipes", default=RECIPE_DIR,
                    help="registry dir of recipe JSONs (default: hand-authored reference set)")
    args = ap.parse_args()
    recipes = load_recipes(args.recipes)
    summary = []
    for pdf in list_root_pdfs():
        key = doc_key(pdf)
        outdir = os.path.join(OUT_DIR, key)
        with open(os.path.join(outdir, "clusters.json"), encoding="utf-8") as f:
            reps = [p - 1 for p in json.load(f)["representative_pages_1based"]]

        recipe, scores = detect_format(pdf, recipes, reps)
        row = {"file": os.path.basename(pdf), "detected": recipe["format_id"] if recipe else None,
               "detect_scores": scores}
        if recipe:
            res = replay(pdf, recipe)
            with_oid = sum(1 for r in res.records if r.field_oid)
            row.update(fields=len(res.records), fields_with_oid=with_oid,
                       forms=len({r.form_name for r in res.records if r.form_name}),
                       pages_with_fields=res.pages_with_fields, pages_total=res.pages_total)
            with open(os.path.join(outdir, "fields.csv"), "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["form_name", "field_name", "field_oid", "oid_alt", "page"])
                for r in res.records:
                    w.writerow([r.form_name, r.field_name, r.field_oid or "", r.oid_alt or "", r.page])
        summary.append(row)
        print(f"{row['file'][:58]:58s} -> {row['detected'] or 'UNDETECTED':16s} "
              f"forms={row.get('forms','-'):>4} fields={row.get('fields','-'):>5} "
              f"with_oid={row.get('fields_with_oid','-'):>5}")

    with open(os.path.join(OUT_DIR, "run_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)


if __name__ == "__main__":
    main()
