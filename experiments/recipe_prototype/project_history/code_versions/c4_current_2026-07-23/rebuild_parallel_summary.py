"""Rebuild a full CLI summary after disjoint parallel worker runs.

Each worker still writes normal per-document artifacts, but its root summary
contains only the documents selected for that invocation. This utility parses
the controller's printed final rows from one or more terminal logs, verifies
that every staged PDF is represented exactly once after de-duplication, and
regenerates the ordinary summary and error reports.
"""
from __future__ import annotations

import argparse
import ast
import json
import os

import run_report
from common import OUT_DIR, doc_key, list_root_pdfs


def rows_from_log(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            text = line.strip()
            if not text.startswith("-> "):
                continue
            row = ast.literal_eval(text[3:])
            if isinstance(row, dict) and row.get("doc"):
                rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--terminal", action="append", default=[])
    ap.add_argument("--summary", action="append", default=[],
                    help="existing JSON summary whose rows also participate")
    ap.add_argument("--replace-doc", action="append", default=[],
                    help="document key whose later non-identical row explicitly "
                         "replaces an earlier attempt")
    args = ap.parse_args()
    if not args.terminal and not args.summary:
        ap.error("at least one --terminal or --summary input is required")

    by_doc = {}
    source_by_doc = {}
    replace_docs = set(args.replace_doc)
    sources = [(path, rows_from_log(path)) for path in args.terminal]
    for path in args.summary:
        with open(path, encoding="utf-8") as f:
            sources.append((path, json.load(f)))
    for path, source_rows in sources:
        for row in source_rows:
            doc = row["doc"]
            if doc in by_doc and by_doc[doc] != row \
                    and doc not in replace_docs:
                raise SystemExit(
                    f"conflicting rows for {doc}: {source_by_doc[doc]} and {path}; "
                    "pass --replace-doc explicitly if the later run is authoritative")
            by_doc[doc] = row
            source_by_doc[doc] = path

    expected = sorted(doc_key(p) for p in list_root_pdfs())
    missing = sorted(set(expected) - set(by_doc))
    extra = sorted(set(by_doc) - set(expected))
    if missing or extra:
        raise SystemExit(f"summary mismatch: missing={missing}, extra={extra}")

    rows = [by_doc[key] for key in expected]
    summary_path = os.path.join(OUT_DIR, f"cli_induction_summary_{args.tag}.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)

    events = run_report.collect_run_events(OUT_DIR, args.tag, rows)
    event_csv, event_json = run_report.write_reports(
        OUT_DIR, args.tag, rows, events, prefix="cli_")
    print(f"wrote {summary_path}: {len(rows)} rows")
    print(f"wrote {event_csv} and {event_json}: {len(events)} events")


if __name__ == "__main__":
    main()
