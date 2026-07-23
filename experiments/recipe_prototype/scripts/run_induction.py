"""PRODUCTION-SHAPED RUN: every document is treated as an UNKNOWN format.

For each PDF in data/crf_forms:
  stage 0   clusters.json + rep_p*.txt must exist (run stage0_cluster.py first)
  stage 1   LLM induces a recipe from the representative pages (bounded revise loop)
  stage 2   deterministic replay of the induced recipe over the whole document
  outputs   induction_trail.json, induced_recipe.json, fields_induced.csv

The LLM transport is chosen with --llm:
  openai-compat  POST {LLM_BASE_URL}/chat/completions with LLM_API_KEY / LLM_MODEL
                 (works for any OpenAI-compatible gateway, incl. Dataiku LLM Mesh
                 public API route)
  cmd            run the command in LLM_CMD, prompt on stdin, reply on stdout
"""
import argparse
import csv
import json
import os
import sys
import urllib.request

from common import OUT_DIR, doc_key, list_root_pdfs
from induction import induce_recipe
from replay import replay


def llm_openai_compat(prompt: str) -> str:
    base = os.environ["LLM_BASE_URL"].rstrip("/")
    body = {
        "model": os.environ.get("LLM_MODEL", ""),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        out = json.load(resp)
    return out["choices"][0]["message"]["content"]


def llm_cmd(prompt: str) -> str:
    import subprocess
    proc = subprocess.run(os.environ["LLM_CMD"], input=prompt.encode("utf-8"),
                          shell=True, capture_output=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:2000])
    return proc.stdout.decode("utf-8", "replace")


TRANSPORTS = {"openai-compat": llm_openai_compat, "cmd": llm_cmd}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", choices=sorted(TRANSPORTS), required=True)
    ap.add_argument("--only", help="substring filter on file name")
    args = ap.parse_args()
    call_llm = TRANSPORTS[args.llm]

    summary = []
    for pdf in list_root_pdfs():
        name = os.path.basename(pdf)
        if args.only and args.only.lower() not in name.lower():
            continue
        outdir = os.path.join(OUT_DIR, doc_key(pdf))
        print(f"=== {name}")
        res = induce_recipe(pdf, outdir, call_llm)
        with open(os.path.join(outdir, "induction_trail.json"), "w", encoding="utf-8") as f:
            json.dump(res["attempts"], f, indent=1)
        row = {"file": name, "status": res["status"],
               "attempts": len(res["attempts"]),
               "format_id": (res["recipe"] or {}).get("format_id"),
               "engine": ((res["recipe"] or {}).get("fields") or {}).get("engine")}
        if res["status"] == "ok":
            with open(os.path.join(outdir, "induced_recipe.json"), "w", encoding="utf-8") as f:
                json.dump(res["recipe"], f, indent=1)
            full = replay(pdf, res["recipe"])
            with open(os.path.join(outdir, "fields_induced.csv"), "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["form_name", "field_name", "field_oid", "oid_alt", "page"])
                for r in full.records:
                    w.writerow([r.form_name, r.field_name, r.field_oid or "", r.oid_alt or "", r.page])
            row.update(fields=len(full.records),
                       fields_with_oid=sum(1 for r in full.records if r.field_oid),
                       forms=len({r.form_name for r in full.records if r.form_name}))
        summary.append(row)
        print("   ", row)

    with open(os.path.join(OUT_DIR, "induction_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
