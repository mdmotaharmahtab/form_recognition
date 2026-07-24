# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage1_v1_2026-07-20\subagent_bridge.cpython-311.pyc (Python 3.11)

'''Bridge for running induction with an external LLM that communicates via files.

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
'''
import json
import os
import sys
import fitz
from codegen import build_code_revision_prompt, build_codegen_prompt, build_coverage_confirm_prompt, extract_source, run_extractor, validate_generated
from common import OUT_DIR, doc_key, list_root_pdfs
from induction import PROMPT_TEMPLATE, build_revision_prompt, load_rep_pages, parse_recipe, validate_recipe
from replay import replay

def pdf_for(dockey = None):
    for p in list_root_pdfs():
        if doc_key(p) == dockey:
            
            return None, p
        raise SystemExit(f'''no pdf for dockey {dockey}''')


def cmd_prompts():
    for pdf in list_root_pdfs():
        key = doc_key(pdf)
        outdir = os.path.join(OUT_DIR, key)
        (pages_text, _) = load_rep_pages(outdir)
        doc = fitz.open(pdf)
        prompt = PROMPT_TEMPLATE.format(n_pages = doc.page_count, pages = pages_text)
        doc.close()
        path = os.path.join(outdir, 'induction_prompt.txt')
        f = open(path, 'w', encoding = 'utf-8')
        f.write(prompt)
        None(None, None)
    with None:
        if not None:
            pass
    print(f'''{key}: {len(prompt)} chars -> {path}''')
    continue


def _load_reply(path = None):
    f = open(path, encoding = 'utf-8')
    None(None, None)
    return 
    with None:
        if not None, f.read():
            pass


def cmd_validate(dockey = None, reply_path = None):
    pdf = pdf_for(dockey)
    outdir = os.path.join(OUT_DIR, dockey)
    raw = _load_reply(reply_path)
    verdict = validate_recipe(pdf, raw)
    print(json.dumps({
        'dockey': dockey,
        'ok': not verdict['problems'],
        'metrics': verdict['metrics'],
        'problems': verdict['problems'] }, indent = 1))
    if verdict['problems']:
        rev_path = os.path.join(outdir, 'revision_prompt.txt')
        f = open(rev_path, 'w', encoding = 'utf-8')
        f.write(build_revision_prompt(raw, verdict))
        None(None, None)
    else:
        with None:
            if not None:
                pass
    print(f'''revision prompt -> {rev_path}''')
    return None


def cmd_finalize(dockey = None, reply_path = None):
    import csv
    pdf = pdf_for(dockey)
    outdir = os.path.join(OUT_DIR, dockey)
    recipe = parse_recipe(_load_reply(reply_path))
    f = open(os.path.join(outdir, 'induced_recipe.json'), 'w', encoding = 'utf-8')
    json.dump(recipe, f, indent = 1)
    None(None, None)


def cmd_prompts_code():
    for pdf in list_root_pdfs():
        key = doc_key(pdf)
        outdir = os.path.join(OUT_DIR, key)
        prompt = build_codegen_prompt(pdf, outdir)
        path = os.path.join(outdir, 'codegen_prompt.txt')
        f = open(path, 'w', encoding = 'utf-8')
        f.write(prompt)
        None(None, None)
    with None:
        if not None:
            pass
    print(f'''{key}: {len(prompt)} chars -> {path}''')
    continue


def cmd_validate_code(dockey = None, reply_path = None):
    """NOTE: the bridge runs gates + one prompt only. It does NOT run the
    confirmation/audit rounds run_cli_induction (and production) run - a program
    that is 'ok' here would still face those challenges in the real loop."""
    pdf = pdf_for(dockey)
    outdir = os.path.join(OUT_DIR, dockey)
    verdict = validate_generated(pdf, _load_reply(reply_path), outdir)
    print(json.dumps({
        'dockey': dockey,
        'ok': not verdict['problems'],
        'metrics': verdict['metrics'],
        'problems': verdict['problems'],
        'warnings': verdict['warnings'],
        'weak_clusters': verdict['weak_clusters'] }, indent = 1))
    if verdict['problems'] or verdict['warnings']:
        rev_path = os.path.join(outdir, 'code_revision_prompt.txt')
        f = open(rev_path, 'w', encoding = 'utf-8')
        f.write(build_code_revision_prompt(verdict))
        None(None, None)
    else:
        with None:
            if not None:
                pass
    print(f'''revision prompt -> {rev_path}''')
    return None
    if verdict['cluster_feedback']:
        confirm_path = os.path.join(outdir, 'coverage_confirm_prompt.txt')
        f = open(confirm_path, 'w', encoding = 'utf-8')
        f.write(build_coverage_confirm_prompt(verdict))
        None(None, None)
    else:
        with None:
            if not None:
                pass
    print(f'''coverage confirmation prompt -> {confirm_path}''')
    return None


def cmd_finalize_code(dockey = None, reply_path = None):
    import csv
    pdf = pdf_for(dockey)
    outdir = os.path.join(OUT_DIR, dockey)
    source = extract_source(_load_reply(reply_path))
    f = open(os.path.join(outdir, 'generated_extractor.py'), 'w', encoding = 'utf-8')
    f.write(source + '\n')
    None(None, None)

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'prompts':
        cmd_prompts()
        return None
    if None == 'validate':
        cmd_validate(sys.argv[2], sys.argv[3])
        return None
    if None == 'finalize':
        cmd_finalize(sys.argv[2], sys.argv[3])
        return None
    if None == 'prompts-code':
        cmd_prompts_code()
        return None
    if None == 'validate-code':
        cmd_validate_code(sys.argv[2], sys.argv[3])
        return None
    if None == 'finalize-code':
        cmd_finalize_code(sys.argv[2], sys.argv[3])
        return None
    raise SystemExit(__doc__)
