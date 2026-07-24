"""Stage 0: cluster every page of every CRF by structural layout, save representative
page dumps (structured text) and PNGs. These representatives are all the FIRST
code-generation call gets to see; later loop rounds may additionally show the
model pages it under-covered (cluster feedback, coverage confirmation) and the
audit's sampled pages - always dumps produced by this same page model, never
raw PDF access.

Clustering front-end: generic_profile.cluster_pages_generic - word-blind typography
tokens per line, per-document ubiquity damping (chrome discovery), weighted-Jaccard
leader clustering, and a similarity threshold theta selected PER DOCUMENT by
stability. The five-signal fingerprint it replaced lives on in common.py as the v1
reference used by comparison probes.
"""
import json
import os
import shutil
import time

import fitz

from common import (OUT_DIR, art, art_bucket_dir, doc_key, dump_rep_page,
                    list_root_pdfs, pick_title_context_pages)
from generic_profile import cluster_pages_generic


def run(path: str) -> dict:
    """Cluster one document; returns meta. Documents the pipeline cannot process
    are detected HERE, before any LLM budget is spent, and marked with a non-ok
    status in the meta (drivers must check it): encrypted PDFs, and scanned/
    image-only PDFs with no text layer (OCR is out of scope - fail loudly).

    The meta carries elapsed_s (wall time of this stage-0 pass) so downstream
    profiling artifacts can attribute per-document time without re-measuring."""
    t0 = time.perf_counter()
    key = doc_key(path)
    out = os.path.join(OUT_DIR, key)
    os.makedirs(out, exist_ok=True)
    # remove stale outputs FIRST (the whole stage0 bucket: clusters.json + rep_/
    # title_ dumps): if this run crashes mid-way, a leftover meta from a previous
    # run would otherwise pass doc_status() as 'ok' while its rep dumps are gone
    stage0_dir = art_bucket_dir(out, "stage0")
    if os.path.isdir(stage0_dir):
        shutil.rmtree(stage0_dir, ignore_errors=True)
    os.makedirs(stage0_dir, exist_ok=True)
    doc = fitz.open(path)
    try:  # close in finally: a mid-run exception must not leak the handle
        # (on Windows an open handle keeps the staged PDF locked for re-runs)
        if doc.needs_pass or doc.page_count == 0:
            status = "encrypted" if doc.needs_pass else "no_pages"
            meta = {"file": os.path.basename(path), "status": status,
                    "pages": 0, "n_clusters": 0, "representative_pages_1based": [], "clusters": [],
                    "elapsed_s": round(time.perf_counter() - t0, 3)}
            with open(art(out, "clusters.json", True), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=1)
            return meta
        res = cluster_pages_generic(doc)
        clusters = res["clusters"]
        page_lines = res["page_lines"]

        pages_without_text = sum(1 for lines in page_lines.values() if not lines)
        text_layer_pct = round(100 * (doc.page_count - pages_without_text) / max(1, doc.page_count))

        rep_pages = res["representatives"]
        # all_representatives additionally holds one rep per tail cluster the
        # budget pass skipped - the multi-pass specialist inventory. Dumps are
        # saved for ALL of them (specialist prompts read the tail dumps);
        # representative_pages_1based stays the budgeted list, so single-pass
        # prompts are unchanged.
        all_reps = res.get("all_representatives", rep_pages)
        for p in all_reps:
            dump_rep_page(page_lines[p], art(out, f"rep_p{p + 1}.txt", True))
            doc[p].get_pixmap(dpi=100).save(art(out, f"rep_p{p + 1}.png", True))
        # Independent TITLE-CONTEXT channel: layout reps optimize structural
        # diversity, not title visibility, so continuation pages can consume the
        # whole rep budget. Select pages where repeated top-of-page context
        # changes, excluding reps already shown. These pages are prompt context,
        # never additional layout-family representatives.
        heights = {p: doc[p].rect.height for p in range(doc.page_count)}
        title_pages = pick_title_context_pages(
            page_lines, heights, exclude=all_reps, max_pages=6)
        for p in title_pages:
            dump_rep_page(page_lines[p], art(out, f"title_p{p + 1}.txt", True))
            doc[p].get_pixmap(dpi=100).save(
                art(out, f"title_p{p + 1}.png", True))

        meta = {
            "file": os.path.basename(path),
            # >=20% text pages -> proceed, but text_layer_pct travels with the
            # meta so drivers can surface partially scanned books (their scanned
            # pages are unreachable by design - OCR is out of scope)
            "status": "ok" if text_layer_pct >= 20 else "no_text_layer",
            "pages": doc.page_count,
            "text_layer_pct": text_layer_pct,
            "theta": res["theta"],  # per-document similarity threshold chosen by stability
            "theta_selection": res.get("theta_selection"),
            "n_clusters": len(clusters),
            "representative_pages_1based": [p + 1 for p in rep_pages],
            "all_rep_pages_1based": [p + 1 for p in all_reps],
            "title_context_pages_1based": [p + 1 for p in title_pages],
            # per-page text-line counts: the downstream blank/content predicate
            # (a page with 0-2 lines - at most a header+footer - cannot carry a
            # data-entry field; the cluster safety net must not count it as a
            # coverage hole). Derived from THIS document only.
            "line_counts": [len(page_lines[i]) for i in range(doc.page_count)],
            "clusters": [{k: v for k, v in c.items() if k != "signature"} | {"header": c["signature"][0]} for c in clusters],
            "elapsed_s": round(time.perf_counter() - t0, 3),
        }
        with open(art(out, "clusters.json", True), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1)
        return meta
    finally:
        doc.close()


if __name__ == "__main__":
    summary = []
    for path in list_root_pdfs():
        try:
            m = run(path)
        except Exception as e:  # same policy as the notebook cell: one corrupt
            print(f"{os.path.basename(path)[:60]:60s} stage0 FAILED: {e!r}")
            continue            # PDF must not sink the batch
        summary.append(m)
        flag = "" if m.get("status", "ok") == "ok" else f"  [{m['status']} - skipping induction]"
        theta = f" theta*={m['theta']:.2f}" if m.get("theta") is not None else ""
        n_tail = len(m.get("all_rep_pages_1based", [])) - len(m["representative_pages_1based"])
        tail = f" (+{n_tail} tail)" if n_tail > 0 else ""
        print(f"{m['file'][:60]:60s} pages={m['pages']:5d} clusters={m['n_clusters']:3d} "
              f"reps={len(m['representative_pages_1based']):3d}{tail}{theta}{flag}")
    total_pages = sum(m["pages"] for m in summary)
    total_reps = sum(len(m["representative_pages_1based"]) for m in summary)
    print(f"\nTOTAL pages={total_pages}  representative pages={total_reps} "
          f"({100 * total_reps / total_pages:.1f}% would go to the LLM)")
