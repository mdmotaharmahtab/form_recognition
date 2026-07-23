"""Out-of-domain probe for the V1 five-signal fingerprint (common.cluster_pages;
the shipped pipeline now uses generic_profile - see generic_cluster_probe.py for
its OOD numbers): run the unchanged v1 clustering on documents that are nothing
like data/crf_forms (clinical protocols, contracts, CJK docs). If the five
signals were overfit to the CRF corpus, these should degenerate: either every
page unique (no stacking) or everything in one pile with wildly mixed layouts.
Prints stack structure so we can judge."""
import sys

import fitz

from common import cluster_pages

DOCS = [
    r"D:\ubuntu\codes\ZS\otsuka\ICF\docs\323-201-00014_Protocol (4) 1.pdf",
    r"D:\ubuntu\codes\ZS\otsuka\ICF\docs\405-201-00180 Protocol (1) 1 1.pdf",
    r"D:\ubuntu\codes\ZS\otsuka\CCM\UATP\results\informal_feedback\feedbacks\pdfs\MSA_OPEL-IQVIA_16Dec2024.pdf",
    r"D:\ubuntu\codes\ZS\otsuka\CCM\pv_classification_test\data\gt_data\blind_testing_docs\Blind Testing Folder\CW81322 en.pdf",
    r"D:\ubuntu\codes\ZS\otsuka\CCM\poc\output\cjk_f14_full.pdf",
    r"D:\ubuntu\codes\ZS\otsuka\CCM\pv_classification_test\data\gt_data\PV Contracts\validation_needed_pv_contracts\37327 Ionis- Otsuka FUS License Agreement (Executed - November 22, 2024).pdf",
]

for path in DOCS:
    name = path.split("\\")[-1][:58]
    try:
        doc = fitz.open(path)
    except Exception as e:
        print(f"{name}: OPEN FAILED {e}")
        continue
    if doc.needs_pass:
        print(f"{name}: encrypted, would be flagged by stage0")
        doc.close()
        continue
    res = cluster_pages(doc)
    n = doc.page_count
    textless = sum(1 for i, lines in res["page_lines"].items() if not lines)
    sizes = sorted((len(c["pages"]) for c in res["clusters"]), reverse=True)
    reps = res["representatives"]
    top = sizes[:8]
    covered_by_rep_clusters = sum(len(c["pages"]) for c in res["clusters"] if c["representatives"])
    print(f"{name}")
    print(f"   pages={n}  textless={textless}  stacks={len(sizes)}  "
          f"top sizes={top}  reps={len(reps)}  "
          f"pages in repped stacks={covered_by_rep_clusters}/{n} ({100*covered_by_rep_clusters//max(n,1)}%)")
    doc.close()
