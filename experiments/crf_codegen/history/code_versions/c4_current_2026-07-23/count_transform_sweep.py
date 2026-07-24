"""Pick the count transform for the generic profile empirically, on ALL books
plus OOD docs (never on one document): capped raw counts vs presence-only vs
log-damped counts. Reports stacks / repped% / sanity-pair verdicts per doc."""
import os
from collections import Counter, defaultdict

import fitz

import generic_profile as gp
from common import build_page_lines
from generic_profile import cluster_profiles, pick_representatives, token_weights

CRF = os.path.join("..", "..", "data", "crf_forms")
DOCS = [
    (os.path.join(CRF, "384-201-00002_Annotated Unique CRF_04Nov2024.pdf"),
     [(0, 132, False), (115, 132, False)]),
    (os.path.join(CRF, "384-201-00004_aCRF_16JAN2025.pdf"), [(3, 4, True), (4, 5, True)]),
    (os.path.join(CRF, "384-201-00004 Annotated CRF__ v2.0 20 May 2025.pdf"), []),
    (os.path.join(CRF, "QSC302573 Final AnnotatedCRFs 16Oct2024-326-201-00007 (1).pdf"),
     [(2, 9, True)]),
    (os.path.join(CRF, "MAC186_X11-201-00001_eCRF v1.10_form tracker v1.6_06Mar2025.pdf"), []),
    (os.path.join(CRF, "326-201-00007 Annotated CRF__ v1.0 30 Sep 2024.pdf"), []),
    (os.path.join(CRF, "331-201-00246 Annotated CRF__ v 26 Jul 2023.pdf"), []),
    (r"D:\ubuntu\codes\ZS\otsuka\ICF\docs\323-201-00014_Protocol (4) 1.pdf", []),
    (r"D:\ubuntu\codes\ZS\otsuka\CCM\UATP\results\informal_feedback\feedbacks\pdfs\MSA_OPEL-IQVIA_16Dec2024.pdf", []),
    (r"D:\ubuntu\codes\ZS\otsuka\CCM\pv_classification_test\data\gt_data\PV Contracts\validation_needed_pv_contracts\37327 Ionis- Otsuka FUS License Agreement (Executed - November 22, 2024).pdf", []),
]

LOG_LEVELS = {0: 0, 1: 2, 2: 3, 3: 4}  # cap3 counts -> pseudo log levels (x2 to stay int)


def transform(prof: Counter, mode: str) -> Counter:
    if mode == "cap3":
        return prof
    if mode == "presence":
        return Counter({t: 1 for t in prof})
    if mode == "log":
        return Counter({t: LOG_LEVELS[c] for t, c in prof.items()})
    raise ValueError(mode)


for path, pairs in DOCS:
    name = os.path.basename(path)[:44]
    try:
        doc = fitz.open(path)
    except Exception as e:
        print(f"{name}: OPEN FAILED {e}")
        continue
    n = doc.page_count
    page_lines = {i: build_page_lines(doc[i]) for i in range(n)}
    base = {i: gp.page_profile(page_lines[i], doc[i].rect.width, doc[i].rect.height,
                               counts="capped")
            for i in range(n)}
    print(f"\n== {name} ({n}pp)")
    for mode in ("cap3", "presence", "log"):
        profiles = {i: transform(p, mode) for i, p in base.items()}
        clusters = cluster_profiles(profiles, 0.5)
        res = pick_representatives(clusters, n)
        sizes = sorted((c["n_pages"] for c in res["clusters"]), reverse=True)
        repped = sum(c["n_pages"] for c in res["clusters"] if c["representatives"])
        loc = {}
        for ci, c in enumerate(clusters):
            for p in c:
                loc[p] = ci
        verdicts = []
        for a, b, together in pairs:
            ok = (loc[a] == loc[b]) == together
            verdicts.append(("OK" if ok else "FAIL") + f"(p{a+1},p{b+1})")
        print(f"   {mode:<8} stacks={len(sizes):>3}  top={sizes[:5]}  "
              f"repped={100*repped//max(n,1)}%  {' '.join(verdicts)}")
    doc.close()
