# Recovered early code (stages 1–2), from bytecode

The 07-20 / 07-21 early-CLI pipeline source was never snapshotted — only the
compiled `.pyc` bytecode survived, in the git-ignored
`experiments/recipe_prototype/__pycache__/`. That cache is transient (any run can
overwrite it), so the bytecode was copied here and decompiled before it was lost.

This partially answers the "source not saved" gap in the timeline: stages 1–2 are
now recoverable at the source level (with the caveats below), not just as outputs.

## How it was recovered (all local — no code left this machine)

1. **Preserved** the `.pyc` files out of the transient cache, grouped by their
   compile date (`stage1_v1_2026-07-20/`, `stage2_v2_2026-07-21/`,
   `stage3plus_2026-07-22/`).
2. **Faithful extraction** with the *matching* interpreter (bytecode is
   version-locked): venv Python 3.11.9 for the `cpython-311` files, msys Python
   3.12.12 for the one `cpython-312` file. This produced, per module:
   - `*.dis.txt` — full `dis` disassembly (100% faithful to the bytecode).
   - `*.meta.txt` — module structure: imports, every function/class with its
     argument names, and **every string/bytes constant verbatim** (the LLM
     prompts, messages, and regexes are recovered word-for-word here).
3. **Source-level decompilation** with Decompyle++ (`pycdc`, built locally from
   source with g++ 15.2) → `*.py`.

## Trust level of each artifact

| Artifact | Fidelity |
|---|---|
| `*.pyc` | Exact — the original compiled bytecode. |
| `*.dis.txt` | Exact — disassembly is a lossless view of the bytecode. |
| `*.meta.txt` | Exact for constants/signatures/imports (prompts are verbatim). |
| `*.py` (decompiled) | High for module structure, imports, constants, and most function bodies; **not guaranteed to run**. Functions with complex control flow carry a `# WARNING: Decompyle incomplete` marker — for those, read the matching `.dis.txt`/`.meta.txt` as the source of truth. `build_dataiku_notebook` crashed the decompiler, so only its `.dis.txt`/`.meta.txt` exist. |

Treat the decompiled `.py` as a **readable reconstruction for understanding what
the early code did**, not as a drop-in replacement for the (unrecoverable)
original formatting/comments.

## What this shows about the evolution

The stage-2 (`07-21`) `codegen.py` `CODEGEN_PROMPT` still defines
`form_name : the CRF form/section the field belongs to` — the ambiguous early
contract that (per the loop-2 report) later drove GPT's per-field-annotation
form-name regression. The four-layer title fix in the deep-dive §12.4 is the
descendant of exactly this line.

## Regenerating

```bash
# faithful dump (run per interpreter version)
python tmp/pyc_recover.py <file>.cpython-311.pyc      # 3.11.9
# source decompile
tmp/pycdc/pycdc.exe <file>.pyc > <file>.py
```
