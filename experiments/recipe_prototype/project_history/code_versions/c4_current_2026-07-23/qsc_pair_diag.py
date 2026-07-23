"""Why do QSC p3 and p10 (same eSource template, five-signal-identical) split
under the damped generic profile? Measures their direct similarity, where they
landed, and their similarity to their clusters' anchor pages - separating
'measure is wrong' from 'leader anchoring is wrong'."""
import os
from collections import Counter

import fitz

from common import build_page_lines
from generic_profile import cluster_profiles, page_profile, token_weights, weighted_jaccard

PATH = os.path.join("..", "..", "data", "crf_forms",
                    "QSC302573 Final AnnotatedCRFs 16Oct2024-326-201-00007 (1).pdf")
doc = fitz.open(PATH)
n = doc.page_count
page_lines = {i: build_page_lines(doc[i]) for i in range(n)}
profiles = {i: page_profile(page_lines[i], doc[i].rect.width, doc[i].rect.height)
            for i in range(n)}
w = token_weights(profiles)

A, B = 2, 9  # 0-based p3, p10
print(f"J(p3,p10) damped = {weighted_jaccard(profiles[A], profiles[B], w):.3f}   "
      f"unweighted = {weighted_jaccard(profiles[A], profiles[B]):.3f}")
print(f"lines: p3={len(page_lines[A])}  p10={len(page_lines[B])}")

clusters = cluster_profiles(profiles, 0.5, w)
loc = {}
for ci, c in enumerate(clusters):
    for p in c:
        loc[p] = ci
ca, cb = loc[A], loc[B]
# clusters are sorted page lists; [0] is the lowest page, not the leader anchor
print(f"p3 in cluster {ca} (size {len(clusters[ca])}, first page p{clusters[ca][0]+1})  "
      f"p10 in cluster {cb} (size {len(clusters[cb])}, first page p{clusters[cb][0]+1})")
for label, page, cl in (("p3", A, ca), ("p10", B, cb)):
    first_own = clusters[cl][0]
    other = cb if cl == ca else ca
    first_other = clusters[other][0]
    print(f"  {label}: J->own first page p{first_own+1} = "
          f"{weighted_jaccard(profiles[page], profiles[first_own], w):.3f}   "
          f"J->other first page p{first_other+1} = "
          f"{weighted_jaccard(profiles[page], profiles[first_other], w):.3f}")

# what carries/kills the direct pair similarity
pa, pb = profiles[A], profiles[B]
rows = []
for t in pa.keys() | pb.keys():
    a, b = pa.get(t, 0), pb.get(t, 0)
    rows.append((w.get(t, 0.0) * (max(a, b) - min(a, b)), w.get(t, 0.0) * min(a, b), t, a, b))
rows.sort(reverse=True)
print("\nbiggest weighted DISAGREEMENTS (token, p3count, p10count, weight):")
for gap, _inter, t, a, b in rows[:12]:
    print(f"   gap={gap:.2f}  {t}  {a} vs {b}   w={w.get(t, 0):.2f}")
inter = sum(r[1] for r in rows)
union = inter + sum(r[0] for r in rows)
print(f"weighted inter={inter:.2f} union={union:.2f}")
doc.close()
