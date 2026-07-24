"""Token + cost report for induction runs. Runs LOCALLY - never inside Dataiku.

Reads each document's llm_calls_<tag>.jsonl (the verbatim prompt/reply record
induce_document writes) and tokenizes both sides with tiktoken when it is
installed. Fallbacks, clearly labeled in the `method` column:
  - tiktoken installed, jsonl present   -> real tokenization (o200k_base)
  - jsonl missing (older run)           -> chars/4 from timings_<tag>.json
  - tiktoken not installed              -> chars/4 from the jsonl entries

Accuracy note printed with every report: tiktoken is OpenAI's tokenizer;
Anthropic does not publish Claude's, so counts are a ~+/-10-15% proxy - good
for "which document/stage eats the budget", not for invoicing.

Usage:
  python cost_report.py --tag claude_4_5_sonnet [--run-dir out]
                        [--price-in 3.0] [--price-out 15.0]

--run-dir accepts the local out/ tree (default) or a downloaded runs/<RUN_ID>/
tree from the Dataiku managed folder - both have the same <doc>/artifact
layout. Prices are $ per million tokens (defaults: Claude Sonnet class).
Writes <run-dir>/cost_report_<tag>.csv (one row per document x call kind,
plus per-document and run totals) and prints the same as tables.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

# pipeline modules (common.py etc.) live in the sibling src/pipeline/ package
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from common import art  # noqa: E402

CHARS_PER_TOKEN = 4.0  # fallback ratio, standard rule of thumb for English text


def make_tokenizer():
    """Returns (fn(text)->n_tokens, method_label)."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        return (lambda t: len(enc.encode(t or "", disallowed_special=()))), "tiktoken:o200k_base"
    except ImportError:
        return (lambda t: round(len(t or "") / CHARS_PER_TOKEN)), f"chars/{CHARS_PER_TOKEN:g}"


def doc_calls(outdir: str, tag: str, tokenize, tok_method: str) -> list[dict]:
    """Per-call token counts for one document dir; [] when no artifacts exist.
    Each item: {kind, version, s, tokens_in, tokens_out, method}."""
    jsonl = art(outdir, f"llm_calls_{tag}.jsonl")
    if os.path.isfile(jsonl):
        calls = []
        with open(jsonl, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                has_text = rec.get("prompt") is not None
                calls.append({
                    "kind": rec.get("kind", "?"),
                    "version": rec.get("version"),
                    "s": rec.get("s", 0.0),
                    "tokens_in": (tokenize(rec["prompt"]) if has_text
                                  else round(rec.get("prompt_chars", 0) / CHARS_PER_TOKEN)),
                    "tokens_out": (tokenize(rec.get("reply") or "") if has_text
                                   else round(rec.get("reply_chars", 0) / CHARS_PER_TOKEN)),
                    "method": tok_method if has_text else f"chars/{CHARS_PER_TOKEN:g}",
                })
        return calls
    timings = art(outdir, f"timings_{tag}.json")
    if os.path.isfile(timings):  # older run: sizes survived, text did not
        with open(timings, encoding="utf-8") as f:
            entries = json.load(f).get("calls", [])
        return [{"kind": c.get("kind", "?"), "version": c.get("version"),
                 "s": c.get("s", 0.0),
                 "tokens_in": round(c.get("prompt_chars", 0) / CHARS_PER_TOKEN),
                 "tokens_out": round(c.get("reply_chars", 0) / CHARS_PER_TOKEN),
                 "method": f"chars/{CHARS_PER_TOKEN:g}"} for c in entries]
    return []


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="model tag, e.g. claude_4_5_sonnet")
    ap.add_argument("--run-dir", default=os.path.join(here, "out"),
                    help="local out/ tree or a downloaded runs/<RUN_ID>/ tree")
    ap.add_argument("--price-in", type=float, default=3.0, help="$ per MTok input")
    ap.add_argument("--price-out", type=float, default=15.0, help="$ per MTok output")
    args = ap.parse_args()

    tokenize, tok_method = make_tokenizer()
    if tok_method.startswith("chars"):
        print("NOTE: tiktoken not installed - falling back to chars/4 estimates "
              "(pip install tiktoken for real tokenization)\n")

    rows = []  # one per (doc, kind)
    for doc in sorted(os.listdir(args.run_dir)):
        outdir = os.path.join(args.run_dir, doc)
        if not os.path.isdir(outdir):
            continue
        calls = doc_calls(outdir, args.tag, tokenize, tok_method)
        if not calls:
            continue
        by_kind: dict[str, dict] = {}
        for c in calls:
            k = by_kind.setdefault(c["kind"], {"calls": 0, "s": 0.0,
                                               "tokens_in": 0, "tokens_out": 0,
                                               "method": c["method"]})
            k["calls"] += 1
            k["s"] = round(k["s"] + c["s"], 3)
            k["tokens_in"] += c["tokens_in"]
            k["tokens_out"] += c["tokens_out"]
        for kind, k in sorted(by_kind.items()):
            cost = (k["tokens_in"] / 1e6 * args.price_in
                    + k["tokens_out"] / 1e6 * args.price_out)
            rows.append({"doc": doc, "kind": kind, **k, "cost_usd": round(cost, 4)})

    if not rows:
        raise SystemExit(f"no llm_calls_{args.tag}.jsonl / timings_{args.tag}.json "
                         f"found under {args.run_dir}")

    out_csv = os.path.join(args.run_dir, f"cost_report_{args.tag}.csv")
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doc", "kind", "calls", "s", "tokens_in",
                                          "tokens_out", "cost_usd", "method"])
        w.writeheader()
        w.writerows(rows)

    print(f"{'document':44s} {'kind':16s} {'calls':>5s} {'sec':>8s} "
          f"{'tok_in':>9s} {'tok_out':>8s} {'cost $':>8s}")
    docs = sorted({r["doc"] for r in rows})
    total = {"calls": 0, "s": 0.0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
    for doc in docs:
        sub = [r for r in rows if r["doc"] == doc]
        for r in sub:
            print(f"{r['doc'][:44]:44s} {r['kind']:16s} {r['calls']:5d} {r['s']:8.1f} "
                  f"{r['tokens_in']:9,d} {r['tokens_out']:8,d} {r['cost_usd']:8.3f}")
        d = {k: round(sum(r[k] for r in sub), 4) for k in total}
        print(f"{'  = ' + doc[:40]:44s} {'TOTAL':16s} {int(d['calls']):5d} {d['s']:8.1f} "
              f"{int(d['tokens_in']):9,d} {int(d['tokens_out']):8,d} {d['cost_usd']:8.3f}")
        for k in total:
            total[k] = round(total[k] + d[k], 4)
    print(f"\n{'RUN TOTAL':44s} {'':16s} {int(total['calls']):5d} {total['s']:8.1f} "
          f"{int(total['tokens_in']):9,d} {int(total['tokens_out']):8,d} "
          f"{total['cost_usd']:8.3f}")
    print(f"\nmethod: {tok_method} - a proxy for Claude's tokenizer (~+/-10-15%); "
          f"prices: ${args.price_in}/MTok in, ${args.price_out}/MTok out")
    print(f"wrote {out_csv}")


if __name__ == "__main__":
    main()
