"""Side-by-side comparison: v1 five-signal fingerprint (reference baseline in
common.py) vs the SHIPPED generic structural profile + Jaccard threshold
clustering (generic_profile.py).

Runs both on the full CRF corpus AND the out-of-domain set (protocols,
contracts, CJK), reporting stack structure, representative budget, coverage,
runtime, template-integrity checks (known same/different-template page pairs)
and how well the generic partition preserves the v1 partition's big stacks.
"""
import os
import time
from collections import defaultdict

import fitz

from common import build_page_lines, page_fingerprint
from generic_profile import (cluster_pages_generic, cluster_profiles,
                             page_profile, pick_representatives)

CRF = os.path.join("..", "..", "data", "crf_forms")
CRF_DOCS = [
    "384-201-00002_Annotated Unique CRF_04Nov2024.pdf",
    "384-201-00004_aCRF_16JAN2025.pdf",
    "384-201-00004 Annotated CRF__ v2.0 20 May 2025.pdf",
    "QSC302573 Final AnnotatedCRFs 16Oct2024-326-201-00007 (1).pdf",
    "MAC186_X11-201-00001_eCRF v1.10_form tracker v1.6_06Mar2025.pdf",
    "326-201-00007 Annotated CRF__ v1.0 30 Sep 2024.pdf",
    "331-201-00246 Annotated CRF__ v 26 Jul 2023.pdf",
]
OOD_DOCS = [
    r"D:\ubuntu\codes\ZS\otsuka\ICF\docs\323-201-00014_Protocol (4) 1.pdf",
    r"D:\ubuntu\codes\ZS\otsuka\ICF\docs\405-201-00180 Protocol (1) 1 1.pdf",
    r"D:\ubuntu\codes\ZS\otsuka\CCM\UATP\results\informal_feedback\feedbacks\pdfs\MSA_OPEL-IQVIA_16Dec2024.pdf",
    r"D:\ubuntu\codes\ZS\otsuka\CCM\pv_classification_test\data\gt_data\blind_testing_docs\Blind Testing Folder\CW81322 en.pdf",
    r"D:\ubuntu\codes\ZS\otsuka\CCM\poc\output\cjk_f14_full.pdf",
    r"D:\ubuntu\codes\ZS\otsuka\CCM\pv_classification_test\data\gt_data\PV Contracts\validation_needed_pv_contracts\37327 Ionis- Otsuka FUS License Agreement (Executed - November 22, 2024).pdf",
]
# (doc substring, page_a 0-based, page_b 0-based, must_be_together)
SANITY_PAIRS = [
    ("QSC302573", 2, 9, True),      # different activities, same eSource template
    ("aCRF_16JAN2025", 3, 4, True),  # consecutive definition pages, same family
    ("aCRF_16JAN2025", 4, 5, True),
    ("384-201-00002", 0, 132, False),   # title vs PK entry form
    ("384-201-00002", 115, 132, False),  # data dictionary vs PK entry form
]


def run_v1(doc, page_lines):
    """The replaced five-signal fingerprint (reference baseline in common.py)."""
    sigs = defaultdict(list)
    for i, lines in page_lines.items():
        sigs[page_fingerprint(lines, doc[i].rect.width)].append(i)
    clusters = [sorted(v) for v in sigs.values()]
    return pick_representatives(clusters, doc.page_count)


def summarize(res, n):
    sizes = sorted((c["n_pages"] for c in res["clusters"]), reverse=True)
    repped = sum(c["n_pages"] for c in res["clusters"] if c["representatives"])
    return {"stacks": len(sizes), "top": sizes[:6], "reps": len(res["representatives"]),
            "repped_pct": 100 * repped // max(n, 1)}


def page2cluster(res):
    m = {}
    for ci, c in enumerate(res["clusters"]):
        for p in c["pages"]:
            m[p] = ci
    return m


def stack_recall(res_from, res_to, top_k=3, min_size=5):
    """For the top_k biggest stacks of res_from: fraction of each kept together
    in its majority cluster of res_to (1.0 = template not fragmented)."""
    to_map = page2cluster(res_to)
    out = []
    for c in sorted(res_from["clusters"], key=lambda c: -c["n_pages"])[:top_k]:
        if c["n_pages"] < min_size:
            break
        dest = defaultdict(int)
        for p in c["pages"]:
            dest[to_map[p]] += 1
        out.append(round(max(dest.values()) / c["n_pages"], 2))
    return out


def probe(path, label, theta=None, sweep=(0.35, 0.45, 0.55)):
    name = os.path.basename(path)[:52]
    try:
        doc = fitz.open(path)
    except Exception as e:
        print(f"{name}: OPEN FAILED {e}")
        return
    if doc.needs_pass:
        print(f"{name}: encrypted, skipped")
        doc.close()
        return
    n = doc.page_count
    t0 = time.perf_counter()
    page_lines = {i: build_page_lines(doc[i]) for i in range(n)}
    t_parse = time.perf_counter() - t0

    t0 = time.perf_counter()
    cur = run_v1(doc, page_lines)
    t_cur = time.perf_counter() - t0

    t0 = time.perf_counter()
    gen = cluster_pages_generic(doc, theta=theta, page_lines=page_lines)
    t_gen = time.perf_counter() - t0

    sc, sg = summarize(cur, n), summarize(gen, n)
    print(f"\n== [{label}] {name}  ({n} pages, parse {t_parse:.1f}s)")
    print(f"   v1-5sig  stacks={sc['stacks']:>3}  top={sc['top']}  reps={sc['reps']}  "
          f"repped={sc['repped_pct']}%  ({t_cur*1000:.0f} ms)")
    print(f"   generic  stacks={sg['stacks']:>3}  top={sg['top']}  reps={sg['reps']}  "
          f"repped={sg['repped_pct']}%  ({t_gen*1000:.0f} ms)  "
          f"theta*={gen.get('theta')}")
    print(f"   top-stack integrity  v1->generic {stack_recall(cur, gen)}  "
          f"generic->v1 {stack_recall(gen, cur)}")

    gmap, cmap = page2cluster(gen), page2cluster(cur)
    for sub, a, b, together in SANITY_PAIRS:
        if sub in name and a < n and b < n:
            for meth, m in (("v1-5sig", cmap), ("generic", gmap)):
                ok = (m[a] == m[b]) == together
                verdict = "OK " if ok else "FAIL"
                rel = "together" if together else "apart"
                print(f"   sanity {verdict} [{meth}] p{a+1} & p{b+1} expected {rel}, "
                      f"got {'together' if m[a] == m[b] else 'apart'}")

    if sweep:
        profiles = {i: page_profile(page_lines[i], doc[i].rect.width, doc[i].rect.height)
                    for i in page_lines}
        row = []
        for th in sweep:
            cl = cluster_profiles(profiles, th)
            r = pick_representatives(cl, n)
            s = summarize(r, n)
            row.append(f"theta={th}: {s['stacks']} stacks/{s['reps']} reps/{s['repped_pct']}%")
        print(f"   sweep    {'  |  '.join(row)}")
    doc.close()


if __name__ == "__main__":
    for fn in CRF_DOCS:
        probe(os.path.join(CRF, fn), "CRF")
    for p in OOD_DOCS:
        probe(p, "OOD")
