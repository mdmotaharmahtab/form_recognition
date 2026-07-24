"""Why did the ORIGINAL generic profile over-merge the QSC eSource book
(2 stacks at theta=0.5 where the five-signal front found 20)?

This diagnostic deliberately replays the original algorithm - capped counts,
UNWEIGHTED Jaccard, no reassignment sweep - so the diagnosed failure stays
reproducible after the fixes (the live module now defaults to presence tokens
+ ubiquity damping + reassignment, precisely because of what this shows).

Tests three hypotheses:
  H1 chaining   - the leader merge pass is single-linkage (union-find over
                  J>=theta pairs), so A~B, B~C fuses A,C even when J(A,C)<theta
  H2 chrome     - the eSource template prints the same header/footer lines on
                  every page; those identical tokens are shared mass on EVERY
                  pair, lifting all similarities above theta  [confirmed]
  H3 density    - COUNT_CAP=3 erased the line-count dimension the five-signal
                  kept as its s/m/l/xl bucket
"""
import os
from collections import Counter, defaultdict

import fitz

from common import build_page_lines, page_fingerprint
from generic_profile import page_profile, weighted_jaccard

PATH = os.path.join("..", "..", "data", "crf_forms",
                    "QSC302573 Final AnnotatedCRFs 16Oct2024-326-201-00007 (1).pdf")

doc = fitz.open(PATH)
n = doc.page_count
page_lines = {i: build_page_lines(doc[i]) for i in range(n)}
# counts="capped" = the original profile this script diagnosed
profiles = {i: page_profile(page_lines[i], doc[i].rect.width, doc[i].rect.height,
                            counts="capped")
            for i in range(n)}

# ---- reference: five-signal stacks --------------------------------------
sigs = defaultdict(list)
for i, lines in page_lines.items():
    sigs[page_fingerprint(lines, doc[i].rect.width)].append(i)
stacks = sorted(sigs.items(), key=lambda kv: -len(kv[1]))[:10]
reps = [pages[len(pages) // 2] for _sig, pages in stacks]
print(f"five-signal: {len(sigs)} stacks; top10 sizes = {[len(p) for _s, p in stacks]}")
print(f"rep pages (1-based): {[r + 1 for r in reps]}")
print(f"line counts of reps: {[len(page_lines[r]) for r in reps]}")

# ---- H2: how much of each page is document-wide chrome? ------------------
page_count_with_token = Counter()
for p in profiles.values():
    for t in p:
        page_count_with_token[t] += 1
chrome = {t for t, c in page_count_with_token.items() if c >= 0.8 * n}
print(f"\nH2 chrome: {len(chrome)} tokens appear on >=80% of pages")
share = []
for i in range(0, n, 25):
    p = profiles[i]
    tot = sum(p.values())
    share.append(sum(c for t, c in p.items() if t in chrome) / max(tot, 1))
print(f"   chrome share of page mass: min={min(share):.2f} median={sorted(share)[len(share)//2]:.2f} max={max(share):.2f}")

# ---- Jaccard matrix between five-signal reps ------------------------------
print("\nJaccard between five-signal stack reps (generic profile):")
print("        " + "".join(f" p{r+1:<5}" for r in reps))
for a in reps:
    row = "".join(f" {weighted_jaccard(profiles[a], profiles[b]):.2f}  " for b in reps)
    print(f"  p{a+1:<5}{row}")

# same matrix with chrome tokens removed
print("\nSame matrix, chrome tokens removed:")
strip = {i: Counter({t: c for t, c in profiles[i].items() if t not in chrome}) for i in reps}
for a in reps:
    row = "".join(f" {weighted_jaccard(strip[a], strip[b]):.2f}  " for b in reps)
    print(f"  p{a+1:<5}{row}")

# ---- H1: leader clustering with vs without the merge pass ----------------
# frozen replica of the ORIGINAL clustering (unweighted, no reassignment)
orig_theta = 0.5
leaders = []
for i in sorted(profiles):
    p = profiles[i]
    if not p:
        continue
    best_j, best_c = 0.0, -1
    for ci, (lead, _m) in enumerate(leaders):
        j = weighted_jaccard(p, lead)
        if j > best_j:
            best_j, best_c = j, ci
    if best_c >= 0 and best_j >= orig_theta:
        leaders[best_c][1].append(i)
    else:
        leaders.append((p, [i]))
sizes_nomerge = sorted((len(m) for _l, m in leaders), reverse=True)
parent = list(range(len(leaders)))


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


for a in range(len(leaders)):
    for b in range(a + 1, len(leaders)):
        if weighted_jaccard(leaders[a][0], leaders[b][0]) >= orig_theta:
            parent[find(b)] = find(a)
merged = defaultdict(list)
for ci, (_l, m) in enumerate(leaders):
    merged[find(ci)].extend(m)
sizes_merged = sorted((len(v) for v in merged.values()), reverse=True)
print(f"\nH1 chaining: leaders BEFORE merge pass: {len(leaders)} stacks, top={sizes_nomerge[:8]}")
print(f"             AFTER  merge pass:          {len(merged)} stacks, top={sizes_merged[:8]}")

# ---- worst confusable pair: what tokens do they share? --------------------
pairs = [(a, b) for ai, a in enumerate(reps) for b in reps[ai + 1:]]
worst = max(pairs, key=lambda ab: weighted_jaccard(profiles[ab[0]], profiles[ab[1]]))
a, b = worst
pa, pb = profiles[a], profiles[b]
print(f"\nmost-confused rep pair: p{a+1} vs p{b+1}  J={weighted_jaccard(pa, pb):.2f}")
shared = sorted(((min(pa[t], pb[t]), t) for t in pa if t in pb), reverse=True)[:12]
print("  top shared tokens (mass, token, chrome?):")
for m, t in shared:
    print(f"    {m}  {t}  {'CHROME' if t in chrome else ''}")
only_a = sorted(((c, t) for t, c in pa.items() if t not in pb), reverse=True)[:6]
only_b = sorted(((c, t) for t, c in pb.items() if t not in pa), reverse=True)[:6]
print(f"  only p{a+1}: {only_a}")
print(f"  only p{b+1}: {only_b}")
doc.close()
