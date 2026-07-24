"""Mechanical edge tests for the generic stage-0 front-end (no PDFs from the
corpus, no LLM):

  1. select_theta NO-PLATEAU fallback: a synthetic document whose partition
     changes at every grid step (runs == []) must fall back to the lower end
     of the most-stable adjacent pair - deterministically.
  2. select_theta full-plateau degeneracy: identical/empty profiles -> every
     pair marked -> middle of the grid.
  3. cluster_pages_generic on 0-, 1- and 2-page documents (built in-memory
     with fitz): no crash, pages conserved, reps in range.
  4. pick_representatives blank-cluster ranking: a huge all-blank cluster must
     never consume a rep slot ahead of content clusters.
  5. cluster_pages_generic page_lines contract: partial page_lines must raise
     ValueError, not a latent KeyError downstream.
"""
from collections import Counter

import fitz

from generic_profile import (THETA_GRID, cluster_pages_generic,
                             pick_representatives, select_theta)

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


# ---- 1. no-plateau fallback --------------------------------------------------
# Two token-disjoint page groups on a 3-point grid (the code path is
# grid-agnostic; a small grid lets a tiny document change partition at EVERY
# step). Group A (6 pages, internal similarity ~0.31) shatters between 0.30
# and 0.45; group B (5 pages, ~0.56) shatters between 0.45 and 0.60. Both
# Rand indices land far below the 0.97 plateau bar -> runs == [] -> fallback.
# Gap 2 changes fewer page pairs (C(5,2)=10 < C(6,2)=15), so it is the
# most-stable pair and its lower end (0.45) must be chosen.
print("1) select_theta no-plateau fallback")
profiles: dict[int, Counter] = {}
for i in range(6):  # group A: 14 shared core tokens + 13 unique fillers
    toks = [("A_core", j) for j in range(14)] + [("A_fill", i, j) for j in range(13)]
    profiles[i] = Counter(dict.fromkeys(toks, 1))
for i in range(5):  # group B: 20 shared core tokens + 7 unique fillers
    toks = [("B_core", j) for j in range(20)] + [("B_fill", i, j) for j in range(7)]
    profiles[6 + i] = Counter(dict.fromkeys(toks, 1))
theta, diag = select_theta(profiles, grid=(0.30, 0.45, 0.60))
check("no plateau found", diag["runs"] == [], f"adjacent_rand={diag['adjacent_rand']}")
check("all pairs below plateau bar", all(not m for m in diag["marked"]))
check("fallback picks lower end of most-stable pair",
      theta == 0.45 and diag["chosen_index"] == 1, f"theta={theta}")

# Same document on a 4-point grid produces TWO equal-length plateaus:
# (0.28-0.30) both groups intact (A's internal similarity ~0.31 > 0.30) and
# (0.45-0.50) A fully shattered / B intact. Equal length -> the LOOSER
# (lower-theta) plateau must win.
theta_t, diag_t = select_theta(profiles, grid=(0.28, 0.30, 0.45, 0.50))
check("equal-length plateaus -> lower theta wins",
      diag_t["runs"] == [[0, 0], [2, 2]] and theta_t == 0.28,
      f"theta={theta_t} runs={diag_t['runs']}")

# ---- 2. full-plateau degeneracy ----------------------------------------------
print("2) select_theta full-plateau degeneracy")
same = {i: Counter({("t", 0): 1, ("t", 1): 1}) for i in range(8)}
theta_s, diag_s = select_theta(same)
mid = THETA_GRID[(0 + (len(THETA_GRID) - 2) + 1) // 2]
check("identical pages -> one full plateau, middle of grid",
      theta_s == mid and diag_s["runs"] == [[0, len(THETA_GRID) - 2]],
      f"theta={theta_s}")
theta_e, diag_e = select_theta({})
check("empty profiles dict -> full plateau, no crash", theta_e == mid)

# ---- 3. tiny documents through the full front-end ----------------------------
print("3) cluster_pages_generic on 0/1/2-page documents")
doc0 = fitz.open()
res0 = cluster_pages_generic(doc0)
check("0-page: no clusters, no reps",
      res0["clusters"] == [] and res0["representatives"] == []
      and res0["theta"] in THETA_GRID)
doc0.close()

doc1 = fitz.open()
doc1.new_page(width=595, height=842)  # one blank page
res1 = cluster_pages_generic(doc1)
pages1 = sorted(p for c in res1["clusters"] for p in c["pages"])
check("1-page blank: page conserved, rep in range",
      pages1 == [0] and res1["representatives"] == [0])
doc1.close()

doc2 = fitz.open()
p = doc2.new_page(width=595, height=842)
p.insert_text((72, 100), "Adverse Event Form", fontsize=14)
p.insert_text((72, 130), "Severity", fontsize=10)
doc2.new_page(width=595, height=842)  # second page blank
res2 = cluster_pages_generic(doc2)
pages2 = sorted(p for c in res2["clusters"] for p in c["pages"])
check("2-page mixed: pages conserved, both forced reps present",
      pages2 == [0, 1] and res2["representatives"] == [0, 1])
doc2.close()

# ---- 4. blank clusters never consume rep slots -------------------------------
print("4) pick_representatives excludes blank clusters from rep slots")
content = [list(range(k * 10, k * 10 + 10)) for k in range(12)]   # 12 x 10 pages
blank = [list(range(120, 420))]                                    # 300 blank pages
res = pick_representatives(blank + content, 420, max_reps=10,
                           is_blank=lambda p: p >= 120)
blank_cluster = next(c for c in res["clusters"] if c["n_pages"] == 300)
n_content_repped = sum(1 for c in res["clusters"]
                       if c["n_pages"] == 10 and c["representatives"])
check("blank cluster got no rep", blank_cluster["representatives"] == [])
check("all 10 slots went to content clusters", n_content_repped == 10,
      f"repped={n_content_repped}")
# even when slots REMAIN after all content clusters, a blank cluster gets none
# (an empty dump is a wasted prompt slot, not a low-priority one)
res_spare = pick_representatives(blank + content[:3], 330, max_reps=10,
                                 is_blank=lambda p: p >= 120)
spare_blank = next(c for c in res_spare["clusters"] if c["n_pages"] == 300)
check("blank cluster skipped even with spare slots",
      spare_blank["representatives"] == [])
res_nb = pick_representatives(blank + content, 420, max_reps=10)
nb_blank = next(c for c in res_nb["clusters"] if c["n_pages"] == 300)
check("without predicate the old policy is unchanged (blank cluster reps)",
      len(nb_blank["representatives"]) == 2)

# ---- 5. page_lines contract --------------------------------------------------
print("5) cluster_pages_generic rejects partial page_lines")
doc3 = fitz.open()
doc3.new_page()
doc3.new_page()
try:
    cluster_pages_generic(doc3, page_lines={0: []})
    check("partial page_lines raises ValueError", False)
except ValueError as e:
    check("partial page_lines raises ValueError", "must cover" in str(e))
doc3.close()

print()
if failures:
    raise SystemExit(f"FAILED: {failures}")
print("stage0 edge tests passed")
