"""Smoke: cluster_pages_generic output must survive the exact meta-building
expression stage0_cluster.py uses (incl. the c['signature'][0] read) AND the
full meta must be JSON-serializable (theta + theta_selection diagnostics go
into clusters.json verbatim). Also covers degenerate inputs (single-page doc)
and the encrypted early-return meta shape."""
import json
import os

import fitz

from generic_profile import cluster_pages_generic

for path in (os.path.join("..", "..", "data", "crf_forms",
                          "326-201-00007 Annotated CRF__ v1.0 30 Sep 2024.pdf"),
             r"D:\ubuntu\codes\ZS\otsuka\CCM\poc\output\cjk_f14_full.pdf"):
    doc = fitz.open(path)
    res = cluster_pages_generic(doc)
    clusters = res["clusters"]
    # the exact meta stage0_cluster.py run() writes - clusters expression plus
    # theta / theta_selection - must round-trip through JSON unchanged
    meta = {
        "status": "ok",
        "pages": doc.page_count,
        "theta": res["theta"],
        "theta_selection": res.get("theta_selection"),
        "n_clusters": len(clusters),
        "representative_pages_1based": [p + 1 for p in res["representatives"]],
        "clusters": [{k: v for k, v in c.items() if k != "signature"}
                     | {"header": c["signature"][0]} for c in clusters],
    }
    assert json.loads(json.dumps(meta)) == meta, "meta does not JSON round-trip"
    assert meta["theta"] in (res.get("theta_selection") or {}).get("grid", [meta["theta"]])
    all_pages = sorted(p for c in clusters for p in c["pages"])
    assert all_pages == list(range(doc.page_count)), "pages lost or duplicated"
    reps = res["representatives"]
    assert reps == sorted(set(reps)) and all(0 <= p < doc.page_count for p in reps)
    print(f"OK  {os.path.basename(path)[:40]:42s} clusters={len(clusters)} "
          f"reps={len(reps)} theta={meta['theta']} header0={meta['clusters'][0]['header']!r}")
    doc.close()

# the encrypted early-return meta (stage0_cluster.run writes this shape without
# theta) must satisfy every consumer that reads clusters.json: doc_status(),
# and the stage0 __main__ / notebook print paths that guard on m.get('theta')
enc_meta = {"file": "x.pdf", "status": "encrypted", "pages": 0,
            "n_clusters": 0, "representative_pages_1based": [], "clusters": []}
json.dumps(enc_meta)
assert enc_meta.get("status", "ok") != "ok"          # doc_status -> skip
assert enc_meta.get("theta") is None                  # print path: no theta chip
assert len(enc_meta["representative_pages_1based"]) == 0
print("OK  encrypted early-return meta shape")
print("stage0 shape smoke passed")
