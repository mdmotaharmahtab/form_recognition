"""Are clusters hiding distinct structures? Deterministic, no LLM.

For every page of every staged CRF PDF: similarity (weighted Jaccard on the
shipped structural profile) to the nearest REPRESENTATIVE of its own cluster.
A page far below the doc's theta was merged into a cluster whose shown rep does
not look like it - a structure the induction model never saw.

Reports per document:
  - % of pages with sim-to-own-rep < theta ("unrepresented structure")
  - worst clusters (dispersion) and the known failure pages from the accuracy
    audit (MAC186 208/300/317, QSC 226/256) with their sim numbers
  - what farthest-point diversity reps (k up to 3/cluster) would recover

Usage: python cluster_dispersion_probe.py
"""
import io
import json
import os
import sys

import fitz

# pipeline modules (common.py etc.) live in the sibling src/pipeline/ package
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from common import (CRF_DIR, OUT_DIR, art, build_page_lines, doc_key,  # noqa: E402
                    list_root_pdfs)
from generic_profile import page_profile, token_weights, weighted_jaccard  # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# pages that scored badly in the ground-truth audit (1-based), for spot checks
KNOWN_BAD = {
    "MAC186_X11-201-00001_eCRF_v1.10_form_tracker_v1.6_06Mar2025": [208, 300, 317],
    "QSC302573_Final_AnnotatedCRFs_16Oct2024-326-201-00007_1_": [219, 226, 256, 355],
}


def farthest_point_reps(pages: list[int], profiles, weights, k: int) -> list[int]:
    """Greedy farthest-point selection: start from the densest profile, then
    repeatedly add the member least similar to the reps chosen so far."""
    if not pages:
        return []
    reps = [max(pages, key=lambda p: sum(profiles[p].values()))]
    while len(reps) < min(k, len(pages)):
        cand, cand_sim = None, 2.0
        for p in pages:
            if p in reps:
                continue
            s = max(weighted_jaccard(profiles[p], profiles[r], weights) for r in reps)
            if s < cand_sim:
                cand, cand_sim = p, s
        if cand is None:
            break
        reps.append(cand)
    return reps


def main() -> None:
    grand = {"pages": 0, "under": 0, "under_fp": 0}
    for pdf in list_root_pdfs():
        key = doc_key(pdf)
        outdir = os.path.join(OUT_DIR, key)
        cpath = art(outdir, "clusters.json")
        if not os.path.isfile(cpath):
            continue
        with open(cpath, encoding="utf-8") as f:
            meta = json.load(f)
        theta = meta.get("theta")
        if theta is None:
            print(f"{key}: no theta in clusters.json (old artifact?) - skipped")
            continue

        doc = fitz.open(pdf)
        profiles = {}
        for i in range(doc.page_count):
            page = doc[i]
            profiles[i] = page_profile(build_page_lines(page), page.rect.width,
                                       page.rect.height)
        doc.close()
        weights = token_weights(profiles)

        n_pages = meta["pages"]
        under = []            # (sim, page, cluster) below theta vs current reps
        under_fp_count = 0    # still below theta vs diversity reps (k=3)
        cluster_rows = []
        for ci, c in enumerate(meta["clusters"]):
            pages = c["pages"]
            reps = c.get("representatives") or []
            if not pages:
                continue
            # skip blank-profile pages: nothing to represent
            live = [p for p in pages if profiles[p]]
            if not live:
                continue
            eff_reps = reps or [live[len(live) // 2]]
            sims = {}
            for p in live:
                sims[p] = max(weighted_jaccard(profiles[p], profiles[r], weights)
                              for r in eff_reps)
            below = [p for p, s in sims.items() if s < theta]
            if below:
                fp = farthest_point_reps(live, profiles, weights, k=3)
                still = [p for p in below
                         if max(weighted_jaccard(profiles[p], profiles[r], weights)
                                for r in fp) < theta]
                under_fp_count += len(still)
                cluster_rows.append((len(below), len(live), ci,
                                     min(sims.values()), len(still)))
                under.extend((sims[p], p, ci) for p in below)

        under.sort()
        pct = 100 * len(under) / max(1, n_pages)
        pct_fp = 100 * under_fp_count / max(1, n_pages)
        grand["pages"] += n_pages
        grand["under"] += len(under)
        grand["under_fp"] += under_fp_count
        print("=" * 100)
        print(f"{key}")
        print(f"  pages={n_pages} clusters={len(meta['clusters'])} theta={theta}")
        print(f"  pages below theta vs OWN cluster reps: {len(under)} ({pct:.1f}%)"
              f"  -> with 3 diversity reps/cluster: {under_fp_count} ({pct_fp:.1f}%)")
        for nb, nl, ci, worst, still in sorted(cluster_rows, reverse=True)[:4]:
            print(f"    cluster {ci:>3}: {nb}/{nl} members below theta "
                  f"(worst sim {worst:.2f}); {still} still below with diversity reps")
        for p1 in KNOWN_BAD.get(key, []):
            p0 = p1 - 1
            ci = next((i for i, c in enumerate(meta["clusters"]) if p0 in c["pages"]), None)
            if ci is None:
                continue
            reps = meta["clusters"][ci].get("representatives") or []
            s = (max(weighted_jaccard(profiles[p0], profiles[r], weights) for r in reps)
                 if reps and profiles[p0] else float("nan"))
            print(f"    known-bad page {p1}: cluster {ci}, sim to shown rep = {s:.2f} "
                  f"({'UNREPRESENTED' if s < theta else 'represented'})")

    print("=" * 100)
    print(f"CORPUS: {grand['under']} of {grand['pages']} pages "
          f"({100 * grand['under'] / max(1, grand['pages']):.1f}%) sit below theta vs their "
          f"own cluster's shown reps; diversity reps would cut that to "
          f"{grand['under_fp']} ({100 * grand['under_fp'] / max(1, grand['pages']):.1f}%)")


if __name__ == "__main__":
    main()
