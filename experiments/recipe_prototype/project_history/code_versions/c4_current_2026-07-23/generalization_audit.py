"""Hardcoding audit for the generic clustering front (generic_profile.py).

The module's parameters were chosen while looking at OUR corpus, so this audit
proves the properties that hardcoding would violate - on CRF books AND
out-of-domain documents:

  T1 word-blindness   scramble every word on every page (preserving only
                      per-character class: upper/lower/digit/other). If any
                      domain vocabulary leaked into the method, profiles or
                      partitions would change. Requirement: bit-identical.
  T2 exponent plateau the ubiquity-damping exponent (df/n)^E was picked as 3
                      while fixing QSC. If only 3 works it is a magic number;
                      requirement: 2..5 all satisfy the labeled invariants.
  T3 mixture purity   chrome discovery must be per-document REACTIVE, not
                      tuned: concatenate two unrelated books; each book's
                      chrome drops to ~50% ubiquity (less damping), yet big
                      clusters must stay book-pure because layouts differ.
  T4 order robustness leader clustering sees pages in document order; feeding
                      pages in reverse must yield (near-)identical partitions
                      (stage0 always uses fixed order, so this measures
                      internal stability, not a production risk).
  T5 tiny documents   ubiquity damping degenerates when n is small (shared
                      template tokens hit df/n=1 and weigh 0). Requirement:
                      graceful - over-split at worst, and the rep budget means
                      the LLM sees everything anyway.
  T6 theta selection  the shipped path picks theta PER DOCUMENT by stability
                      (select_theta) instead of any fixed constant.
                      Requirement: the selected theta satisfies every labeled
                      invariant, on CRF and non-CRF docs alike - the labels
                      are used as a test here, never as the selector's input.
"""
import math
import os
import random
from collections import Counter, defaultdict
from dataclasses import replace

import fitz

from common import build_page_lines
from generic_profile import (DEFAULT_THETA, cluster_profiles, page_profile,
                             pick_representatives, select_theta, token_weights)

CRF = os.path.join("..", "..", "data", "crf_forms")
DOCS = {
    "rave404": os.path.join(CRF, "384-201-00002_Annotated Unique CRF_04Nov2024.pdf"),
    "acrf206": os.path.join(CRF, "384-201-00004_aCRF_16JAN2025.pdf"),
    "qsc609": os.path.join(CRF, "QSC302573 Final AnnotatedCRFs 16Oct2024-326-201-00007 (1).pdf"),
    "mac913": os.path.join(CRF, "MAC186_X11-201-00001_eCRF v1.10_form tracker v1.6_06Mar2025.pdf"),
    "book1085": os.path.join(CRF, "331-201-00246 Annotated CRF__ v 26 Jul 2023.pdf"),
    "protocol": r"D:\ubuntu\codes\ZS\otsuka\ICF\docs\323-201-00014_Protocol (4) 1.pdf",
    "contract": r"D:\ubuntu\codes\ZS\otsuka\CCM\pv_classification_test\data\gt_data\PV Contracts\validation_needed_pv_contracts\37327 Ionis- Otsuka FUS License Agreement (Executed - November 22, 2024).pdf",
}
PAIRS = [  # labeled invariants (same as theta_sanity_sweep)
    ("rave404", 0, 132, False), ("rave404", 115, 132, False),
    ("acrf206", 3, 4, True), ("acrf206", 4, 5, True),
    ("qsc609", 2, 9, True),
]

UP, LO, DG = "QXZVKWJHYB", "qxzvkwjhyb", "7391508264"


def scramble(text: str, rng: random.Random) -> str:
    return "".join(
        rng.choice(UP) if c.isupper() else
        rng.choice(LO) if c.islower() else
        rng.choice(DG) if c.isdigit() else c
        for c in text)


def partition_of(clusters: list[list[int]]) -> dict[int, int]:
    return {p: ci for ci, c in enumerate(clusters) for p in c}


def rand_index(pa: dict[int, int], pb: dict[int, int]) -> float:
    pages = sorted(pa)
    n = len(pages)
    cont: Counter = Counter((pa[p], pb[p]) for p in pages)
    sum_ij = sum(math.comb(v, 2) for v in cont.values())
    ra: Counter = Counter(pa[p] for p in pages)
    rb: Counter = Counter(pb[p] for p in pages)
    sum_a = sum(math.comb(v, 2) for v in ra.values())
    sum_b = sum(math.comb(v, 2) for v in rb.values())
    total = math.comb(n, 2)
    return (total + 2 * sum_ij - sum_a - sum_b) / total if total else 1.0


# ---- load everything once --------------------------------------------------
data = {}
for key, path in DOCS.items():
    doc = fitz.open(path)
    pl = {i: build_page_lines(doc[i]) for i in range(doc.page_count)}
    dims = {i: (doc[i].rect.width, doc[i].rect.height) for i in range(doc.page_count)}
    doc.close()
    prof = {i: page_profile(pl[i], *dims[i]) for i in pl}
    data[key] = (pl, dims, prof)

print("=== T1 word-blindness: scramble every word, require identical profiles & partition")
for key, (pl, dims, prof) in data.items():
    rng = random.Random(7)
    prof_s = {}
    for i, lines in pl.items():
        s_lines = [replace(L, text=scramble(L.text, rng)) for L in lines]
        prof_s[i] = page_profile(s_lines, *dims[i])
    same_profiles = all(prof_s[i] == prof[i] for i in prof)
    part_o = partition_of(cluster_profiles(prof))
    part_s = partition_of(cluster_profiles(prof_s))
    ri = rand_index(part_o, part_s)
    print(f"  {key:10s} profiles identical: {same_profiles}   partition RI={ri:.3f}"
          f"   {'PASS' if same_profiles and ri == 1.0 else 'FAIL'}")

print("\n=== T2 damping-exponent plateau: invariants must hold for E in 2..5 (3 = shipped)")
for E in (1, 2, 3, 4, 5):
    violations = []
    stats = []
    for key, (_pl, _dims, prof) in data.items():
        pages = [p for p in prof.values() if p]
        n = len(pages)
        df: Counter = Counter()
        for p in pages:
            for t in p:
                df[t] += 1
        w = {t: 1.0 - (c / n) ** E for t, c in df.items()}
        clusters = cluster_profiles(prof, DEFAULT_THETA, w)
        loc = partition_of(clusters)
        res = pick_representatives(clusters, len(prof))
        repped = sum(c["n_pages"] for c in res["clusters"] if c["representatives"])
        stats.append(f"{key.split('0')[0]}:{len(clusters)}/{100*repped//len(prof)}%")
        for dk, a, b, together in PAIRS:
            if dk == key and (loc[a] == loc[b]) != together:
                violations.append(f"{dk}(p{a+1},p{b+1})")
    flag = "shipped" if E == 3 else ""
    print(f"  E={E}  {'  '.join(stats)}")
    print(f"       violations: {violations if violations else 'none'}  {flag}")

print("\n=== T3 mixture purity: two books as one 'document'; big clusters must stay book-pure")
for ka, kb in (("rave404", "qsc609"), ("acrf206", "contract"), ("mac913", "protocol")):
    pa, pb = data[ka][2], data[kb][2]
    na = max(pa) + 1
    merged = dict(pa)
    for i, p in pb.items():
        merged[na + i] = p
    clusters = cluster_profiles(merged)
    big = [c for c in clusters if len(c) >= 5]
    purities = []
    for c in big:
        from_a = sum(1 for p in c if p < na)
        if not any(merged[p] for p in c):  # all-empty-page cluster: source-agnostic by design
            continue
        purities.append(max(from_a, len(c) - from_a) / len(c))
    worst = min(purities) if purities else 1.0
    mixed = sum(1 for x in purities if x < 0.95)
    print(f"  {ka}+{kb}: {len(big)} big clusters, worst purity={worst:.2f}, "
          f"mixed(<95%)={mixed}   {'PASS' if worst >= 0.95 else 'CHECK'}")

print("\n=== T4 page-order robustness: reversed arrival order vs document order")
for key, (_pl, _dims, prof) in data.items():
    n = len(prof)
    rev = {n - 1 - i: p for i, p in prof.items()}
    part_o = partition_of(cluster_profiles(prof))
    part_r_raw = partition_of(cluster_profiles(rev))
    part_r = {n - 1 - i: c for i, c in part_r_raw.items()}
    ri = rand_index(part_o, part_r)
    print(f"  {key:10s} RI={ri:.3f}   {'PASS' if ri >= 0.9 else 'CHECK'}")

print("\n=== T5 tiny documents: first K pages as a standalone doc (damping at its weakest)")
pl, dims, prof = data["rave404"]
for K in (2, 5, 10, 15):
    sub = {i: prof[i] for i in range(K)}
    clusters = cluster_profiles(sub)
    res = pick_representatives(clusters, K)
    reps = res["representatives"]
    repped = sum(c["n_pages"] for c in res["clusters"] if c["representatives"])
    all_pages = sorted(p for c in clusters for p in c)
    ok = all_pages == list(range(K))
    print(f"  K={K:>2}  stacks={len(clusters):>2}  reps={len(reps):>2}  "
          f"pages in repped stacks={repped}/{K}  conserved={ok}")

print("\n=== T6 per-document theta selection: labels used as TEST only")
for key, (_pl, _dims, prof) in data.items():
    th, diag = select_theta(prof)
    clusters = cluster_profiles(prof, th)
    loc = partition_of(clusters)
    res = pick_representatives(clusters, len(prof))
    repped = sum(c["n_pages"] for c in res["clusters"] if c["representatives"])
    verdicts = []
    for dk, a, b, together in PAIRS:
        if dk == key:
            ok = (loc[a] == loc[b]) == together
            verdicts.append(("OK" if ok else "FAIL") + f"(p{a+1},p{b+1})")
    print(f"  {key:10s} theta*={th:.2f}  stacks={len(clusters):>3}  "
          f"repped={100*repped//len(prof)}%  adjacent-RI={diag['adjacent_rand']}  "
          f"{' '.join(verdicts) if verdicts else ''}")
print("\naudit complete")
