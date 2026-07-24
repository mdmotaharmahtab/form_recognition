"""Final theta selection, done on principle: find the widest theta plateau
where (a) all known DIFFERENT-layout pairs stay apart, (b) known SAME-template
pairs stay together, (c) coverage holds across BOTH corpora (CRF + OOD).
Also inspects the QSC 229/216 split: systematic sub-template or noise?"""
import os
from collections import Counter

import fitz

from common import build_page_lines
from generic_profile import (cluster_profiles, page_profile, pick_representatives,
                             token_weights, weighted_jaccard)

CRF = os.path.join("..", "..", "data", "crf_forms")
DOCS = {
    "rave": os.path.join(CRF, "384-201-00002_Annotated Unique CRF_04Nov2024.pdf"),
    "acrf": os.path.join(CRF, "384-201-00004_aCRF_16JAN2025.pdf"),
    "qsc": os.path.join(CRF, "QSC302573 Final AnnotatedCRFs 16Oct2024-326-201-00007 (1).pdf"),
    "mac": os.path.join(CRF, "MAC186_X11-201-00001_eCRF v1.10_form tracker v1.6_06Mar2025.pdf"),
    "331": os.path.join(CRF, "331-201-00246 Annotated CRF__ v 26 Jul 2023.pdf"),
    "msa": r"D:\ubuntu\codes\ZS\otsuka\CCM\UATP\results\informal_feedback\feedbacks\pdfs\MSA_OPEL-IQVIA_16Dec2024.pdf",
    "lic": r"D:\ubuntu\codes\ZS\otsuka\CCM\pv_classification_test\data\gt_data\PV Contracts\validation_needed_pv_contracts\37327 Ionis- Otsuka FUS License Agreement (Executed - November 22, 2024).pdf",
}
PAIRS = [  # (doc, a, b, must_be_together) - list, so print order is stable
    ("rave", 0, 132, False), ("rave", 115, 132, False),
    ("acrf", 3, 4, True), ("acrf", 4, 5, True),
    ("qsc", 2, 9, True),
]

data = {}
for key, path in DOCS.items():
    doc = fitz.open(path)
    pl = {i: build_page_lines(doc[i]) for i in range(doc.page_count)}
    prof = {i: page_profile(pl[i], doc[i].rect.width, doc[i].rect.height) for i in pl}
    data[key] = (doc.page_count, prof)
    doc.close()

print("theta sweep (per doc: stacks/repped%; sanity verdicts):")
for th in (0.35, 0.40, 0.45, 0.50, 0.55):
    cells = []
    verdicts = []
    for key, (n, prof) in data.items():
        clusters = cluster_profiles(prof, th)
        res = pick_representatives(clusters, n)
        repped = sum(c["n_pages"] for c in res["clusters"] if c["representatives"])
        cells.append(f"{key}:{len(clusters)}/{100*repped//n}%")
        loc = {p: ci for ci, c in enumerate(clusters) for p in c}
        for (dk, a, b, together) in PAIRS:
            if dk != key:
                continue
            ok = (loc[a] == loc[b]) == together
            if not ok:
                verdicts.append(f"{dk}(p{a+1},p{b+1}){'MERGED' if not together else 'SPLIT'}")
    print(f"  theta={th:.2f}  {'  '.join(cells)}")
    print(f"             violations: {verdicts if verdicts else 'none'}")

# ---- QSC split anatomy -----------------------------------------------------
n, prof = data["qsc"]
w = token_weights(prof)
clusters = cluster_profiles(prof, 0.5)
big = [c for c in clusters if len(c) > 100][:2]
if len(big) == 2:
    A, B = big
    ca = Counter()
    for m in A:
        ca.update(prof[m])
    cb = Counter()
    for m in B:
        cb.update(prof[m])
    fa = {t: v / len(A) for t, v in ca.items()}
    fb = {t: v / len(B) for t, v in cb.items()}
    print(f"\nQSC big stacks: {len(A)} pages (has p3={2 in A}) vs {len(B)} pages (has p10={9 in B})")
    print(f"centroid J = {weighted_jaccard(fa, fb, w):.3f}")
    print("tokens most systematically different (frac in A vs B, weight):")
    diffs = sorted(((abs(fa.get(t, 0) - fb.get(t, 0)) * w.get(t, 0), t)
                    for t in set(fa) | set(fb)), reverse=True)[:10]
    for gap, t in diffs:
        print(f"   {t}: {fa.get(t, 0):.2f} vs {fb.get(t, 0):.2f}  (w={w.get(t, 0):.2f}, wgap={gap:.2f})")
