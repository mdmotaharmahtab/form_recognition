"""A/B: leader clustering vs average-linkage agglomerative on the SAME
profiles/weights/theta-selection. Reports, per document and method:
theta*, clusters, reps, pages in clusters WITHOUT a representative
(the LLM's blind spot), labeled-pair violations, runtime."""
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import fitz

from common import build_page_lines
from generic_profile import (build_agglo_dendrogram, cluster_profiles,
                             cluster_profiles_agglo, page_profile,
                             pick_representatives, select_theta, token_weights)

CRF = os.path.join("..", "..", "..", "data", "crf_forms")
DOCS = {}
for fn in sorted(os.listdir(CRF)):
    if fn.lower().endswith(".pdf"):
        DOCS[fn[:28]] = os.path.join(CRF, fn)
for key, path in {
    "OOD:msa": r"D:\ubuntu\codes\ZS\otsuka\CCM\UATP\results\informal_feedback\feedbacks\pdfs\MSA_OPEL-IQVIA_16Dec2024.pdf",
    "OOD:lic": r"D:\ubuntu\codes\ZS\otsuka\CCM\pv_classification_test\data\gt_data\PV Contracts\validation_needed_pv_contracts\37327 Ionis- Otsuka FUS License Agreement (Executed - November 22, 2024).pdf",
}.items():
    if os.path.exists(path):
        DOCS[key] = path

# labeled invariants from theta_sanity_sweep (0-based pages, must_be_together)
PAIRS = {
    "384-201-00002_Annotated Uniq": [(0, 132, False), (115, 132, False)],
    "384-201-00004_aCRF_16JAN2025": [(3, 4, True), (4, 5, True)],
    "QSC302573 Final AnnotatedCRF": [(2, 9, True)],
}

def frag_stats(clusters, n_pages, profiles):
    res = pick_representatives(clusters, n_pages,
                               is_blank=lambda p: not profiles[p])
    unrepped = sum(c["n_pages"] for c in res["clusters"]
                   if not c["representatives"] and any(profiles[p] for p in c["pages"]))
    reps = len(res["representatives"])
    return reps, unrepped

print(f"{'doc':30s} {'method':8s} {'theta':>5s} {'clus':>5s} {'reps':>4s} "
      f"{'unrepped_pages':>14s} {'violations':>10s} {'sec':>6s}")
for key, path in DOCS.items():
    doc = fitz.open(path)
    pl = {i: build_page_lines(doc[i]) for i in range(doc.page_count)}
    profs = {i: page_profile(pl[i], doc[i].rect.width, doc[i].rect.height) for i in pl}
    n = doc.page_count
    doc.close()
    w = token_weights(profs)
    for method in ("leader", "average"):
        t0 = time.perf_counter()
        theta, diag, clusters = select_theta(profs, w, return_clusters=True, method=method)
        dt = time.perf_counter() - t0
        nonempty = [c for c in clusters if any(profs[p] for p in c)]
        reps, unrepped = frag_stats(clusters, n, profs)
        loc = {p: ci for ci, c in enumerate(clusters) for p in c}
        viols = []
        for (a, b, together) in PAIRS.get(key, []):
            if (loc[a] == loc[b]) != together:
                viols.append(f"p{a+1}/p{b+1}:{'SPLIT' if together else 'MERGED'}")
        print(f"{key:30s} {method:8s} {theta:5.2f} {len(nonempty):5d} {reps:4d} "
              f"{unrepped:8d} ({100*unrepped//max(1,n):2d}%) {';'.join(viols) or '-':>10s} {dt:6.1f}")
