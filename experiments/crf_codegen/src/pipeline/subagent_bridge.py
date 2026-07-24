"""Bridge for running induction with an external LLM that communicates via files.

Recipe mode (engine catalog - kept for comparison):
  prompts                      write out/<doc>/induction_prompt.txt for every document
  validate <dockey> <reply>    execute the replied recipe over the full pdf, print
                               metrics/problems; on failure write revision_prompt.txt
  finalize <dockey> <reply>    accept the recipe, write induced_recipe.json +
                               fields_induced.csv

Codegen mode (no catalog, no few-shots - the format-agnostic path):
  prompts-code                     write out/<doc>/codegen_prompt.txt for every document
  validate-code <dockey> <reply>   run the replied PROGRAM over the full pdf in a
                                   sandbox, print metrics/problems; on failure write
                                   code_revision_prompt.txt
  finalize-code <dockey> <reply>   accept the program, write generated_extractor.py +
                                   fields_codegen.csv
"""
import json
import os
import sys

import fitz

from codegen import (build_code_revision_prompt, build_codegen_prompt,
                     build_coverage_confirm_prompt, extract_source,
                     run_extractor, validate_generated)
from common import OUT_DIR, art, doc_key, list_root_pdfs
from induction import (PROMPT_TEMPLATE, build_revision_prompt, load_rep_pages,
                       parse_recipe, validate_recipe)
from replay import replay


def pdf_for(dockey: str) -> str:
    for p in list_root_pdfs():
        if doc_key(p) == dockey:
            return p
    raise SystemExit(f"no pdf for dockey {dockey}")


def cmd_prompts() -> None:
    for pdf in list_root_pdfs():
        key = doc_key(pdf)
        outdir = os.path.join(OUT_DIR, key)
        pages_text, _ = load_rep_pages(outdir)
        doc = fitz.open(pdf)
        prompt = PROMPT_TEMPLATE.format(n_pages=doc.page_count, pages=pages_text)
        doc.close()
        path = art(outdir, "induction_prompt.txt", True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"{key}: {len(prompt)} chars -> {path}")


def _load_reply(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def cmd_validate(dockey: str, reply_path: str) -> None:
    pdf = pdf_for(dockey)
    outdir = os.path.join(OUT_DIR, dockey)
    raw = _load_reply(reply_path)
    verdict = validate_recipe(pdf, raw)
    print(json.dumps({"dockey": dockey, "ok": not verdict["problems"],
                      "metrics": verdict["metrics"], "problems": verdict["problems"]}, indent=1))
    if verdict["problems"]:
        rev_path = art(outdir, "revision_prompt.txt", True)
        with open(rev_path, "w", encoding="utf-8") as f:
            f.write(build_revision_prompt(raw, verdict))
        print(f"revision prompt -> {rev_path}")


def cmd_finalize(dockey: str, reply_path: str) -> None:
    import csv
    pdf = pdf_for(dockey)
    outdir = os.path.join(OUT_DIR, dockey)
    recipe = parse_recipe(_load_reply(reply_path))
    with open(os.path.join(outdir, "induced_recipe.json"), "w", encoding="utf-8") as f:
        json.dump(recipe, f, indent=1)
    full = replay(pdf, recipe)
    with open(os.path.join(outdir, "fields_induced.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["form_name", "field_name", "field_oid", "oid_alt", "page"])
        for r in full.records:
            w.writerow([r.form_name, r.field_name, r.field_oid or "", r.oid_alt or "", r.page])
    print(json.dumps({
        "dockey": dockey, "format_id": recipe.get("format_id"),
        "engine": recipe.get("fields", {}).get("engine"),
        "fields": len(full.records),
        "fields_with_oid": sum(1 for r in full.records if r.field_oid),
        "forms": len({r.form_name for r in full.records if r.form_name}),
    }, indent=1))


def cmd_prompts_code() -> None:
    for pdf in list_root_pdfs():
        key = doc_key(pdf)
        outdir = os.path.join(OUT_DIR, key)
        prompt = build_codegen_prompt(pdf, outdir)
        path = art(outdir, "codegen_prompt.txt", True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"{key}: {len(prompt)} chars -> {path}")


def cmd_validate_code(dockey: str, reply_path: str) -> None:
    """NOTE: the bridge runs gates + one prompt only. It does NOT run the
    confirmation/audit rounds run_cli_induction (and production) run - a program
    that is 'ok' here would still face those challenges in the real loop.
    Warning semantics match production: warnings NEVER trigger a revision prompt
    by themselves (they ride along with audit findings in the real loop) - a
    program tuned through this bridge must face the same acceptance pressure."""
    pdf = pdf_for(dockey)
    outdir = os.path.join(OUT_DIR, dockey)
    verdict = validate_generated(pdf, _load_reply(reply_path), outdir)
    print(json.dumps({"dockey": dockey, "ok": not verdict["problems"],
                      "metrics": verdict["metrics"], "problems": verdict["problems"],
                      "warnings": verdict["warnings"],
                      "weak_clusters": verdict["weak_clusters"]}, indent=1))
    if verdict["problems"]:
        rev_path = art(outdir, "code_revision_prompt.txt", True)
        with open(rev_path, "w", encoding="utf-8") as f:
            f.write(build_code_revision_prompt(verdict))
        print(f"revision prompt -> {rev_path}")
    elif verdict["cluster_feedback"]:
        # gates passed but coverage holes remain (weak clusters, or doc-wide holes
        # when the clustering is degenerate): one confirmation round
        confirm_path = art(outdir, "coverage_confirm_prompt.txt", True)
        with open(confirm_path, "w", encoding="utf-8") as f:
            f.write(build_coverage_confirm_prompt(verdict))
        print(f"coverage confirmation prompt -> {confirm_path}")
    elif verdict["warnings"]:
        print("(warnings are quality signals, not blockers - in the real loop the "
              "grounded audit judges them; no revision prompt written)")


def cmd_finalize_code(dockey: str, reply_path: str) -> None:
    import csv
    pdf = pdf_for(dockey)
    outdir = os.path.join(OUT_DIR, dockey)
    source = extract_source(_load_reply(reply_path))
    with open(art(outdir, "generated_extractor.py", True), "w", encoding="utf-8") as f:
        f.write(source + "\n")
    full = run_extractor(source, pdf)
    with open(art(outdir, "fields_codegen.csv", True), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["form_name", "field_name", "page"])
        for r in full.records:
            w.writerow([r.form_name, r.field_name, r.page])
    print(json.dumps({
        "dockey": dockey,
        "fields": len(full.records),
        "forms": len({r.form_name for r in full.records if r.form_name}),
        "pages_with_fields": full.pages_with_fields,
    }, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "prompts":
        cmd_prompts()
    elif cmd == "validate":
        cmd_validate(sys.argv[2], sys.argv[3])
    elif cmd == "finalize":
        cmd_finalize(sys.argv[2], sys.argv[3])
    elif cmd == "prompts-code":
        cmd_prompts_code()
    elif cmd == "validate-code":
        cmd_validate_code(sys.argv[2], sys.argv[3])
    elif cmd == "finalize-code":
        cmd_finalize_code(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
