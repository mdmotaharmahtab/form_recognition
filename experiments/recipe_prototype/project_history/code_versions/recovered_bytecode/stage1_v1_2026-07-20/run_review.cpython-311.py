# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage1_v1_2026-07-20\run_review.cpython-311.pyc (Python 3.11)

'''End-to-end generalization review of the pipeline by a fresh reviewer model.

Concatenates the pipeline source into one prompt and asks a reviewer (via the
Cursor CLI, default Opus medium thinking) to audit it for hardcoding, hidden
format/corpus priors, and generalization risks. The reviewer sees code only -
no repo access (empty sandbox cwd).

  python run_review.py [--model claude-opus-4-8-thinking-medium]
Writes out/pipeline_review_<model>.md
'''
import argparse
import os
import re
from common import OUT_DIR
from run_cli_induction import call_cli, find_agent, slug
HERE = os.path.dirname(os.path.abspath(__file__))
FILES = [
    ('common.py', 'PRODUCTION-INTENT: page model, layout fingerprint, clustering, rep selection'),
    ('stage0_cluster.py', 'PRODUCTION-INTENT: stage-0 driver (local variant; Dataiku notebook will mirror it)'),
    ('codegen.py', 'PRODUCTION-INTENT: codegen prompt, executor parent side, cluster feedback, coverage confirm, grounded audit'),
    ('sandbox_runner.py', 'PRODUCTION-INTENT: child process that executes generated code in a restricted namespace'),
    ('induction.py', 'MIXED: score/gate_problems are PRODUCTION-INTENT; the recipe/engine-catalog prompt path is LEGACY comparison only'),
    ('replay.py', 'LEGACY comparison path (engine catalog) - review only for anything the production path imports from it (FieldRec, ReplayResult)'),
    ('subagent_bridge.py', 'LOCAL HARNESS: file-based bridge for manual/blind testing'),
    ('run_cli_induction.py', 'LOCAL HARNESS mirroring the production loop: transport + revision/confirm/audit orchestration'),
    ('eval_form_field.py', 'EVALUATION ONLY: ground-truth comparison + name->OID mapping experiment'),
    ('evaluate.py', 'EVALUATION ONLY: legacy OID-scope evaluation')]
CHARTER = 'You are reviewing a document-extraction pipeline for clinical CRF PDFs. Its core claim: GENERALITY. It must work on any CRF-like PDF form book with NO prior knowledge beyond "this is a CRF" - unlimited vendors, layouts, languages. Up to ~1000 pages per document; the only LLM calls allowed are: one program-synthesis call on ~12 representative pages, a bounded revision loop, one coverage-confirmation round, one grounded audit round. Everything else is deterministic Python. Scope: extract (form_name, field_name) per data-entry field; machine codes/OIDs are resolved downstream and are OUT of extraction scope.\n\nArchitecture (intended production flow, to run in a Dataiku notebook via LLM Mesh):\n stage 0: cluster pages by structural fingerprint, pick representatives (no LLM)\n stage 1: LLM writes extract(pages) Python from representative page dumps only\n gates:   mechanical, contract-level checks on the FULL-document run of that program\n loop:    failures -> revision prompt (metrics + per-cluster coverage + unseen sample\n          pages from weak clusters); pass-but-uncovered-clusters -> one confirm round;\n          pass -> grounded audit (sampled pages side-by-side with extracted records,\n          model lists missed/false/wrong_form; one fix round, regression-guarded)\n output:  (form_name, field_name, page) records\n\nREVIEW CHARTER - report in these sections, every item actionable with file/symbol refs:\n\n1. HARDCODING & CORPUS PRIORS (the main concern): every constant, regex, threshold,\n   prompt sentence, or heuristic that encodes knowledge of specific CRF vendors,\n   the author\'s 11 sample documents, English/Latin text, or the local machine\n   (paths, OS). For each: severity (blocker / should-fix / acceptable-with-comment),\n   why it threatens generality, and a concrete fix. Judge PROMPT TEXT too.\n2. BUGS: wrong logic, order-of-operations, off-by-one, exception swallowing,\n   state leaks across documents/attempts.\n3. LOGICAL FLOW: loop bounds, acceptance/regression rules, dead paths, cases where\n   a bad program can be accepted or a good one rejected.\n4. EDGE CASES vs the generality claim: scanned/no-text-layer PDFs, multi-column,\n   RTL/CJK text, huge/tiny documents, PDFs where the fingerprint degenerates\n   (all pages one cluster / every page unique), programs that return generators,\n   unicode, empty pages, encrypted PDFs.\n5. SANDBOX & SAFETY: escapes from the restricted exec namespace, resource abuse\n   (memory/CPU), thread-timeout leaks, and whether restrictions could also block\n   LEGITIMATE extraction programs.\n6. CONSISTENCY: places where harness behavior diverges from the documented\n   production intent (e.g. bridge vs run_cli_induction vs prompts).\n\nDo NOT propose new features. Do NOT restyle code. Focus on the generality claim\nand correctness. Be specific and terse; no praise.\n'

def build_prompt():
    parts = [
        CHARTER,
        '\n\n# PIPELINE SOURCE\n']
    for name, role in FILES:
        f = open(os.path.join(HERE, name), encoding = 'utf-8')
        src = f.read()
        None(None, None)
    with None:
        if not None:
            pass
    parts.append(f'''\n---------- {name}  [{role}] ----------\n{src}''')
    continue
    return '\n'.join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default = 'claude-opus-4-8-thinking-medium')
    args = ap.parse_args()
    prompt = build_prompt()
    print(f'''review prompt: {len(prompt)} chars; calling {args.model} ...''')
    reply = call_cli(find_agent(), args.model, prompt, timeout_s = 1800)
    out_path = os.path.join(OUT_DIR, f'''pipeline_review_{slug(args.model)}.md''')
    f = open(out_path, 'w', encoding = 'utf-8')
    f.write(reply)
    None(None, None)

if __name__ == '__main__':
    main()
    return None
