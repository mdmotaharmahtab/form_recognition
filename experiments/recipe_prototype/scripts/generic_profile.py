"""Generic structural page profile + similarity-threshold clustering.

The SHIPPED stage-0 front-end (stage0_cluster.py and the Dataiku notebook call
cluster_pages_generic). It replaced the five-signal fingerprint in common.py -
which remains available as the v1 reference for comparison probes - and is
built so a reviewer cannot call any part of it CRF-specific:

  * every line becomes one TOKEN describing pure typography/geometry -
    (x-band, size-vs-modal, bold, color, character-class). No regex for
    brackets, no "field number" notion, no named convention of any kind.
  * a page is the SET of its line tokens (presence, not counts: per-page
    count jitter is content, not template - measured in
    count_transform_sweep.py).
  * tokens are ubiquity-damped PER DOCUMENT: weight(t) = 1 - (df/n)^3.
    A token printed on every page is the document's own template chrome -
    headers, footers, boilerplate - and carries no template-discriminating
    information, so it weighs 0. Discovered from the document itself, never
    assumed. (Diagnosed on the QSC eSource book, where the 17 most-ubiquitous
    tokens - 11 of them printed on all 609 pages - carried 85-94% of every
    page's mass and fused all templates above any threshold - see
    qsc_merge_diag.py.)
  * page similarity = weighted Jaccard - the standard near-duplicate measure
    (Broder's shingling + TF-IDF-style weighting; MinHash approximates it at
    web scale, at <=1000 pages we compute it exactly, keeping determinism
    and zero dependencies).
  * clustering = best-fit leader clustering (canopy-style) in a canonical
    content-derived page order, a centroid-level merge pass, and one
    centroid-reassignment sweep. Deterministic and page-order-invariant,
    O(n*k), stdlib only.

The knob count drops from five hand-picked signals to ONE threshold (theta) -
and theta itself is NOT shipped as a constant: select_theta() picks it per
document by persistence/stability selection (cluster at a grid of sensible
values, find where the partition stops changing, take the middle of the widest
stable plateau). A fixed value would be corpus-fit by construction; a value
derived from the document being processed cannot be. The labeled page pairs in
theta_sanity_sweep.py are used only to TEST the result, never to set the knob.

Hardcoding audit: generalization_audit.py proves the properties hardcoding
would violate - word-scramble invariance (profiles bit-identical when every
word on every page is replaced), damping-exponent plateau (not a knife-edge
value, and per-document theta selection absorbs most of its effect),
cross-book mixture purity (chrome discovery adapts, no cross-contamination),
page-order invariance (canonical processing order), graceful tiny-document
degradation.
"""
from __future__ import annotations

import heapq
import math
import os
from collections import Counter, defaultdict

from common import Line, build_page_lines

# Per-cluster representative cap. Default 4 = historical behavior. Raising it
# (ECS_REPS_PER_CLUSTER) shows the model more diverse in-family samples per
# layout cluster - the "more good samples per cluster" ablation. Unset = no
# change anywhere.
_REPS_PER_CLUSTER = max(1, int(os.environ.get("ECS_REPS_PER_CLUSTER", "4")))
# Default total cluster-budget for stage-0 rep selection; ECS_MAX_REPS overrides
# it (e.g. a narrow-split ablation shrinks the generalist's owned cluster set).
_MAX_REPS = max(1, int(os.environ.get("ECS_MAX_REPS", "10")))

X_BINS = 6
# Fixed-theta fallback for component tests and probes. The shipped path is
# select_theta(): per-document stability selection over THETA_GRID. (0.40 sits
# mid-plateau on every labeled invariant we have - theta_sanity_sweep.py - but
# any fixed constant is corpus-fit by construction, hence the selector.)
DEFAULT_THETA = 0.40
# Grid endpoints are structural properties of Jaccard similarity, not tuning:
# below 0.30 "same layout" would mean sharing under a third of weighted
# structural mass (meaninglessly loose); above 0.60 it would demand a
# near-identity that per-page content jitter never allows.
THETA_GRID = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)


def _charclass(text: str) -> str:
    """Character-composition class - typography only, no domain patterns."""
    t = text.strip()
    if not t:
        return "sym"
    letters = sum(c.isalpha() for c in t)
    digits = sum(c.isdigit() for c in t)
    if letters == 0 and digits > 0:
        return "num"        # "3", "19.0", "12/04/2024"
    if letters == 0:
        return "sym"        # "____", "---", "|"
    if t.upper() == t.lower():
        # caseless scripts (CJK, Thai, Arabic, Hebrew...): "ALL CAPS" is
        # vacuously true and CJK also prints no word spaces, so the Latin
        # code heuristic below would tag EVERY text line as code and erase
        # this token dimension document-wide. Split word/prose by word count
        # where spaces exist, else by length (a short run is a label, a long
        # one a sentence; 12 chars ~ 6+ ideographs - a coarseness knob like
        # the others, not a correctness constraint).
        return "prose" if len(t.split()) >= 3 or len(t) >= 12 else "word"
    if " " not in t and (digits > 0 or t.upper() == t):
        return "code"       # "[AESEV]", "SAS_NAME", "F14" - spaceless letter+digit/caps runs
    words = len(t.split())
    if words <= 2:
        return "word"       # "Severity", "Collection Date"
    return "prose"          # full sentences / questions


def _size_rel(size: float, modal: float) -> str:
    if modal <= 0:
        return "="
    r = size / modal
    return "-" if r < 0.9 else "+" if r > 1.15 else "="


COUNT_CAP = 3  # for counts="capped" research mode


def page_profile(lines: list[Line], page_width: float, page_height: float,
                 counts: str = "presence") -> Counter:
    """Structural line tokens; the page's word-blind layout profile.

    Default is PRESENCE (which token kinds exist), not counts: measured across
    all 7 CRF books + OOD docs (count_transform_sweep.py), presence gives the
    fattest same-template stacks because per-page count jitter (3 fields vs 5)
    is content, not template. y-position is excluded for the same reason:
    vertical extent tracks content volume, not template identity - which is
    also why page_height is accepted (call-site symmetry) but unused."""
    if not lines:
        return Counter()
    sizes = Counter(round(L.size, 1) for L in lines)
    modal = sizes.most_common(1)[0][0]
    raw: Counter = Counter()
    for L in lines:
        # clamp both sides: cropbox quirks can put x0 slightly outside [0, width)
        xb = max(0, min(X_BINS - 1, int(L.x0 / max(page_width, 1) * X_BINS)))
        tok = (xb, _size_rel(L.size, modal),
               "B" if L.bold else ".", "C" if L.non_black else ".",
               _charclass(L.text))
        raw[tok] += 1
    if counts == "presence":
        return Counter(dict.fromkeys(raw, 1))
    return Counter({t: min(c, COUNT_CAP) for t, c in raw.items()})


def token_weights(profiles: dict[int, Counter]) -> dict:
    """Smooth ubiquity damping, discovered per document:

        weight(t) = 1 - (df/n)**3

    A token on every page (the document's own header/footer/boilerplate
    chrome) weighs 0; on half the pages 7/8; a rare token ~1. Nothing is
    assumed about WHAT chrome looks like - it is whatever this document
    repeats everywhere.

    Deliberately NOT classic log-IDF: log(n/df) over-rewards rare tokens,
    which on pages are content noise, and it splits same-template pages
    (measured: QSC p3/p10 and aCRF p5/p6 separated, coverage dropped on
    all 13 probe docs). The failure being corrected is ubiquity flooding
    (chrome = 85-94% of every QSC page's mass), so only ubiquity is damped;
    mid-frequency tokens - the per-template skeleton - keep full weight."""
    pages = [p for p in profiles.values() if p]
    n = len(pages)
    if not n:
        return {}
    df: Counter = Counter()
    for p in pages:
        for t in p:
            df[t] += 1
    return {t: 1.0 - (c / n) ** 3 for t, c in df.items()}


def weighted_jaccard(a: Counter, b: Counter, w: dict | None = None) -> float:
    """Jaccard over capped counts; with `w`, each token's contribution is
    scaled by its document IDF. Two non-empty pages whose entire mass is
    zero-weight chrome are structurally identical plain pages -> 1.0."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if w is None:
        inter = sum(min(a[t], b[t]) for t in a if t in b)
        union = sum(a.values()) + sum(b.values()) - inter
        return inter / union if union else 0.0
    # math.fsum: exact summation, so the result does not depend on token
    # iteration order (set order varies with per-process hash randomization)
    inter = math.fsum(w.get(t, 0.0) * min(a[t], b[t]) for t in a if t in b)
    union = math.fsum(w.get(t, 0.0) * max(a.get(t, 0), b.get(t, 0)) for t in a.keys() | b.keys())
    if union <= 1e-9:
        return 1.0
    return inter / union


def cluster_profiles(profiles: dict[int, Counter], theta: float = DEFAULT_THETA,
                     weights: dict | None = None) -> list[list[int]]:
    """Best-fit leader clustering + one leader merge pass. Returns page-index lists."""
    if weights is None:
        weights = token_weights(profiles)
    # canonical processing order - CONTENT-derived, not document order: densest
    # profile first (dense pages are the best anchors for their template),
    # ties broken by token content. Makes the partition independent of page
    # arrival order (audit T4); the page-index tie-break only orders pages
    # with bit-identical profiles, which land in one stack regardless.
    order = sorted((i for i in profiles),
                   key=lambda i: (-sum(profiles[i].values()),
                                  str(sorted((str(t), c) for t, c in profiles[i].items())),
                                  i))
    leaders: list[tuple[Counter, list[int]]] = []
    empty: list[int] = []
    for i in order:
        p = profiles[i]
        if not p:
            empty.append(i)
            continue
        best_j, best_c = 0.0, -1
        for ci, (lead, _members) in enumerate(leaders):
            j = weighted_jaccard(p, lead, weights)
            if j > best_j:
                best_j, best_c = j, ci
        if best_c >= 0 and best_j >= theta:
            leaders[best_c][1].append(i)
        else:
            leaders.append((p, [i]))

    # Merge groups on their CENTROIDS, not on anchor pages: after damping, a
    # single page's residual profile is small (a handful of weighted tokens),
    # so one noisy token can hold two halves of a template family apart, while
    # the family centroids - which average out per-page noise - are clearly
    # within theta (measured on QSC: anchor-vs-anchor 0.35, centroid-vs-
    # centroid 0.47 for the two halves of the activity-page family).
    def centroid_of(members: list[int]) -> dict:
        cent: Counter = Counter()
        for m in members:
            cent.update(profiles[m])
        k = len(members)
        return {t: v / k for t, v in cent.items()}

    groups = [members for _lead, members in leaders]
    cents = [centroid_of(m) for m in groups]
    parent = list(range(len(groups)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(groups)):
        for b in range(a + 1, len(groups)):
            if weighted_jaccard(cents[a], cents[b], weights) >= theta:
                parent[find(b)] = find(a)

    merged: dict[int, list[int]] = defaultdict(list)
    for ci, members in enumerate(groups):
        merged[find(ci)].extend(members)
    out = [sorted(v) for v in merged.values()]

    # One centroid-reassignment sweep: a page assigned while its stack was
    # still small can fit a (now fully formed) different stack better. Single
    # sweep, deterministic; a page keeps its cluster unless a strictly better
    # centroid also clears theta.
    centroids = [centroid_of(members) for members in out]
    home = {p: ci for ci, members in enumerate(out) for p in members}
    moved: dict[int, list[int]] = defaultdict(list)
    for i in sorted(home):
        p = profiles[i]
        own = home[i]
        # a singleton's own centroid is itself (J=1.0), which would pin it
        # forever; let it compete for a real stack from a clean slate
        best_j, best_c = (0.0, own) if len(out[own]) == 1 else \
            (weighted_jaccard(p, centroids[own], weights), own)
        for ci, cent in enumerate(centroids):
            if ci == own:
                continue
            j = weighted_jaccard(p, cent, weights)
            if j > best_j:
                best_j, best_c = j, ci
        moved[best_c if best_j >= theta else own].append(i)
    out = [sorted(v) for v in moved.values() if v]

    if empty:
        out.append(empty)
    return sorted(out, key=lambda c: (-len(c), c[0]))


# --------------------------------------------------------------------------- #
# Average-linkage agglomerative clustering (UPGMA) over the SAME weighted-
# Jaccard similarities - the order-independent alternative to leader
# clustering. Literature basis: hierarchical agglomerative clustering with a
# distance threshold is the standard label-free method when the cluster count
# is unknown; average linkage avoids single-link chaining (bridge pages fusing
# unrelated templates) and complete-link over-fragmentation. Leader clustering
# processes pages one at a time against first-seen anchors, so early
# assignments can never be revisited; UPGMA always merges the globally most
# similar pair, so the result has no arrival-order or anchor bias.
#
# The dendrogram does not depend on theta (theta only CUTS it), and UPGMA is
# monotone (each merge similarity <= the previous one, because updated
# similarities are convex combinations of the merged rows). select_theta()
# exploits both: build the merge sequence once, replay it per grid value.
# Identical profiles are deduplicated first - on repetitive form books this
# collapses hundreds of pages to a few dozen distinct profiles, keeping the
# O(m^2) similarity matrix tiny (m = distinct profiles, not pages).
#
# ADOPTION VERDICT (agglo_compare_probe.py, 9 CRF books + 2 OOD docs):
# 10-40x faster theta selection, but NOT better where it counts - on the QSC
# book the stability selector lands on theta=0.55 and SPLITS the labeled
# same-template pair p3/p10 that leader's centroid-merge pass keeps together,
# and unrepped-page fragmentation on the 331 books is not reduced. Leader
# stays the shipped default; "average" remains available for probes/research.
# --------------------------------------------------------------------------- #
def build_agglo_dendrogram(profiles: dict[int, Counter],
                           weights: dict | None = None) -> dict:
    """Merge sequence for average-linkage clustering of `profiles`.

    Returns {"groups": [[page, ...], ...],   # dedup groups, canonical order
             "merges": [(sim, ga, gb), ...]} # non-increasing sim, group ids
    cluster_profiles_agglo() cuts this at any theta. Deterministic: canonical
    group order (densest profile first, then token string), fsum similarities,
    ties broken on (smaller id, larger id)."""
    if weights is None:
        weights = token_weights(profiles)
    by_key: dict[str, list[int]] = defaultdict(list)
    key_prof: dict[str, Counter] = {}
    for i in sorted(profiles):
        p = profiles[i]
        if not p:
            continue  # empty pages join their own cluster at cut time
        k = str(sorted((str(t), c) for t, c in p.items()))
        by_key[k].append(i)
        key_prof[k] = p
    keys = sorted(by_key, key=lambda k: (-sum(key_prof[k].values()), k))
    groups = [sorted(by_key[k]) for k in keys]
    profs = [key_prof[k] for k in keys]
    m = len(groups)
    if m <= 1:
        return {"groups": groups, "merges": []}

    # pairwise page-level similarities between distinct profiles; within a
    # dedup group the similarity is exactly 1.0 (identical profiles), which
    # average linkage accounts for via group sizes
    sim: dict[tuple[int, int], float] = {}
    heap: list[tuple[float, int, int]] = []
    for a in range(m):
        pa = profs[a]
        for b in range(a + 1, m):
            s = weighted_jaccard(pa, profs[b], weights)
            sim[(a, b)] = s
            heap.append((-s, a, b))
    heapq.heapify(heap)

    size = {i: len(groups[i]) for i in range(m)}
    active = set(range(m))
    merges: list[tuple[float, int, int]] = []

    def cur_sim(a: int, b: int) -> float:
        return sim[(a, b) if a < b else (b, a)]

    while len(active) > 1 and heap:
        neg_s, a, b = heapq.heappop(heap)
        if a not in active or b not in active:
            continue
        s = -neg_s
        if abs(cur_sim(a, b) - s) > 1e-12:
            continue  # stale entry (one endpoint was since re-averaged)
        # merge b into a (a < b by construction of pushes)
        merges.append((s, a, b))
        active.discard(b)
        na, nb = size[a], size[b]
        for k in active:
            if k == a:
                continue
            ns = (na * cur_sim(a, k) + nb * cur_sim(b, k)) / (na + nb)
            key = (a, k) if a < k else (k, a)
            sim[key] = ns
            heapq.heappush(heap, (-ns, *key))
        size[a] = na + nb
    return {"groups": groups, "merges": merges}


def cluster_profiles_agglo(profiles: dict[int, Counter], theta: float = DEFAULT_THETA,
                           weights: dict | None = None,
                           dendrogram: dict | None = None) -> list[list[int]]:
    """Cut the average-linkage dendrogram at `theta`. Same contract as
    cluster_profiles (page-index lists, largest first; empty pages in one
    trailing cluster). Pass a prebuilt dendrogram to amortize across thetas."""
    if dendrogram is None:
        dendrogram = build_agglo_dendrogram(profiles, weights)
    groups = dendrogram["groups"]
    parent = list(range(len(groups)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for s, a, b in dendrogram["merges"]:
        if s < theta:
            break  # merges are non-increasing in s
        parent[find(b)] = find(a)
    merged: dict[int, list[int]] = defaultdict(list)
    for gi, pages in enumerate(groups):
        merged[find(gi)].extend(pages)
    out = [sorted(v) for v in merged.values()]
    empty = sorted(i for i, p in profiles.items() if not p)
    if empty:
        out.append(empty)
    return sorted(out, key=lambda c: (-len(c), c[0]))


def _rand_index(pa: dict[int, int], pb: dict[int, int]) -> float:
    """Rand index between two partitions given as page -> cluster-id maps."""
    pages = sorted(pa)
    n = len(pages)
    if n < 2:
        return 1.0
    cont: Counter = Counter((pa[p], pb[p]) for p in pages)
    sum_ij = sum(math.comb(v, 2) for v in cont.values())
    sum_a = sum(math.comb(v, 2) for v in Counter(pa[p] for p in pages).values())
    sum_b = sum(math.comb(v, 2) for v in Counter(pb[p] for p in pages).values())
    total = math.comb(n, 2)
    return (total + 2 * sum_ij - sum_a - sum_b) / total


# Two adjacent-theta partitions count as "the same" when their Rand index is
# >= this bar: on a multi-hundred-page book RI 0.97 means under ~3% of page
# PAIRS change relation - statistically identical. This is a meta-knob (it
# defines "unchanged"), not a similarity threshold on any document content.
PLATEAU_RI = 0.97


def select_theta(profiles: dict[int, Counter], weights: dict | None = None,
                 grid: tuple = THETA_GRID, return_clusters: bool = False,
                 method: str = "leader"):
    """Per-document theta by PLATEAU (persistence) SELECTION - no fixed
    constant to overfit.

    Cluster the document at every theta on the grid and mark each adjacent
    pair of grid points whose partitions are statistically identical
    (Rand index >= PLATEAU_RI). Maximal runs of marked pairs are the
    document's stable plateaus: regions where the partition reflects real
    structure in THIS document rather than the knob. Choose the middle of
    the longest plateau; on ties prefer the looser (lower-theta) one, because
    over-merge is the cheaper miss - it surfaces as a zero-record stack and
    the coverage-confirm/audit loop repairs it, while over-split silently
    spends representative slots. If no pair clears the bar (a genuinely
    unstable document), fall back to the lower end of the most-stable pair.

    Scoring runs over marked PAIRS, never single endpoints, so a saturated
    end of the grid cannot win on one lucky neighbor (a first version scored
    endpoints on their single adjacent RI and picked theta=0.60 on the QSC
    book, splitting a known template family - caught by audit T6).

    Deterministic, len(grid) clustering passes, zero labeled data. Cost note:
    on repetitive books a pass is milliseconds, but the worst case (every page
    a unique layout) is O(n^2) similarity work per pass - minutes, not ms, at
    ~1000 pages. Bounded and rare, but the cost is real on genuinely
    heterogeneous documents. Returns (theta, diagnostics), or with return_clusters=True
    (theta, diagnostics, clusters_at_theta) so the caller can reuse the
    already-computed partition instead of re-clustering."""
    if weights is None:
        weights = token_weights(profiles)
    dendro = build_agglo_dendrogram(profiles, weights) if method == "average" else None
    parts = []
    parts_clusters = []
    for th in grid:
        if method == "average":
            clusters = cluster_profiles_agglo(profiles, th, weights, dendro)
        else:
            clusters = cluster_profiles(profiles, th, weights)
        parts_clusters.append(clusters)
        parts.append({p: ci for ci, c in enumerate(clusters) for p in c})
    m = len(grid)
    adj = [_rand_index(parts[i], parts[i + 1]) for i in range(m - 1)]
    marked = [ri >= PLATEAU_RI for ri in adj]

    runs = []  # (start_pair, end_pair) inclusive, over marked pairs
    start = None
    for i, ok in enumerate(marked + [False]):
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            runs.append((start, i - 1))
            start = None
    if runs:
        # pair run s..e spans grid indices s..e+1; longest run wins,
        # ties -> lower theta
        s, e = max(runs, key=lambda r: (r[1] - r[0], -r[0]))
        chosen = (s + e + 1) // 2
    else:
        chosen = max(range(m - 1), key=lambda i: adj[i])  # lower end of best pair
    diag = {"grid": list(grid), "n_stacks": [len(set(p.values())) for p in parts],
            "adjacent_rand": [round(x, 4) for x in adj], "marked": marked,
            # lists, not tuples: this dict goes into clusters.json verbatim and
            # must round-trip through JSON unchanged
            "runs": [list(r) for r in runs], "chosen_index": chosen}
    if return_clusters:
        return grid[chosen], diag, parts_clusters[chosen]
    return grid[chosen], diag


def _diverse_reps(pages: list[int], profiles: dict[int, Counter],
                  weights: dict, k: int, radius: float | None = None,
                  k_max: int | None = None) -> list[int]:
    """Farthest-point (max-min) pick of structurally diverse pages.

    Seed = the densest weighted profile (the best anchor for the template);
    each further pick maximizes the minimum weighted-Jaccard DISTANCE to the
    already-picked set - the classic k-center greedy, which provably covers
    the cluster's structural spread far better than positional picks (a theta
    cluster is a template FAMILY, not identical pages).

    Always picks at least k (subject to candidates). With `radius` (and
    k_max), picking CONTINUES past k while some member still sits farther
    than radius from every pick: with radius = 1 - theta this is exactly
    'every member within theta of a shown rep' - need-driven growth, so a
    tight cluster spends 1 slot and a spread-out one up to k_max. Stops early
    when every remaining page is structurally identical to a pick (a
    duplicate dump would waste a prompt slot). Empty-profile pages are never
    picked (nothing to show). Deterministic: fsum sums, ties -> lower page."""
    cand = [p for p in pages if profiles.get(p)]
    if not cand or k <= 0:
        return []
    hard_cap = min(len(cand), max(k, k_max or k))

    def mass(p: int) -> float:
        return math.fsum(weights.get(t, 0.0) * c for t, c in profiles[p].items())

    seed = max(cand, key=lambda p: (mass(p), -p))
    picked = [seed]
    # min distance to picked set, maintained incrementally: O(k*n) similarity calls
    dist = {p: 1.0 - weighted_jaccard(profiles[p], profiles[seed], weights) for p in cand}
    while len(picked) < hard_cap:
        best_p, best_d = None, 1e-6  # floor: refuse near-duplicate picks
        for p in cand:
            if p in picked:
                continue
            d = dist[p]
            if d > best_d:
                best_p, best_d = p, d
        if best_p is None:
            break
        if len(picked) >= k and (radius is None or best_d <= radius):
            break  # quota met and every member already within radius of a pick
        picked.append(best_p)
        for p in cand:
            d = 1.0 - weighted_jaccard(profiles[p], profiles[best_p], weights)
            if d < dist[p]:
                dist[p] = d
    return sorted(picked)


def pick_representatives(clusters: list[list[int]], page_count: int,
                         max_reps: int = 10, coverage: float = 0.95,
                         is_blank=None, max_extra_reps: int = 0,
                         profiles: dict[int, Counter] | None = None,
                         weights: dict | None = None,
                         rep_all_content: bool = False,
                         rep_radius: float | None = None) -> dict:
    """Rep policy mirroring common.cluster_pages, applied to any partition, so
    method comparisons share identical selection logic (same positional picks
    at the defaults; the only deviation is that the total is now strictly
    capped at max_reps+max_extra_reps, where the historical code could
    overshoot by one on the boundary cluster).

    is_blank (optional page predicate): clusters made entirely of blank pages
    never receive a representative - an empty dump is a prompt slot the LLM
    cannot learn from, so blank clusters must not consume one even when slots
    remain after all content clusters. (They still count toward coverage
    accounting; blank pages need no parser.)

    max_extra_reps: adaptive budget for FRAGMENTED documents. Clusters are
    visited largest-first and rep assignment already stops once the coverage
    target is met, so the extra slots are spent only when max_reps alone
    cannot reach the target - a document with many small-to-mid layout
    families. Layouts with no representative are invisible to the LLM at
    induction time (measured: up to ~20% of pages on the most fragmented
    books); a bounded bump is the direct, format-agnostic mitigation.

    profiles/weights (optional): switch per-cluster picks from POSITIONAL
    (midpoint; +first-quartile above 50 pages) to FARTHEST-POINT DIVERSITY
    sampling with a size-scaled base count (1 + pages/100, floor 2 above 50
    pages, cap 4). A theta cluster is a template family, not identical pages:
    cluster_dispersion_probe.py measured up to ~9% of a document's pages
    sitting below its own theta against their cluster's positional rep -
    exactly the pages the LLM never saw. Diversity picks close that gap
    without touching the clustering itself.

    rep_radius (optional, needs profiles): NEED-DRIVEN growth of the per-
    cluster rep count. With rep_radius = 1 - theta, picking continues past the
    base count (up to the cap of 4) while any member still sits farther than
    the radius from every pick - i.e. until every member is within theta of a
    shown rep. Size-scaled counts alone under-serve spread-out clusters (a
    176-page cluster got 2 reps where 3+ were measurably needed) and waste
    slots on tight ones; the radius spends slots exactly where structural
    spread exists.

    rep_all_content: additionally give every non-blank cluster skipped by the
    budget pass ONE representative, recorded per cluster and in
    'all_representatives' - NOT in the budgeted 'representatives' list. This
    is the multi-pass specialists' inventory (codegen.plan_passes): pass
    planning needs a page dump for every layout family, while single-pass
    prompts keep using the budgeted list unchanged."""
    def _blank(c: list[int]) -> bool:
        return is_blank is not None and all(is_blank(p) for p in c)

    per_cluster_cap = _REPS_PER_CLUSTER

    def n_for(pages: list[int]) -> int:
        if profiles is None:
            return 2 if len(pages) > 50 else 1
        return min(per_cluster_cap,
                   max(1 + len(pages) // 100, 2 if len(pages) > 50 else 1))

    def picks_for(pages: list[int], k: int, k_max: int | None = None) -> list[int]:
        if profiles is not None:
            got = _diverse_reps(pages, profiles, weights or {}, k,
                                radius=rep_radius, k_max=k_max)
            if got:
                return got
        out = [pages[len(pages) // 2]]
        if k >= 2 and len(pages) > 50:
            out.append(pages[len(pages) // 4])
        return sorted(set(out))

    ordered = sorted(clusters, key=lambda c: (_blank(c), -len(c)))
    cap = max_reps + max_extra_reps
    out_clusters, covered, reps, extra = [], 0, [], []
    for pages in ordered:
        is_rep_cluster = (covered < coverage * page_count
                          and len(reps) < cap and not _blank(pages))
        cluster_reps: list[int] = []
        if is_rep_cluster:
            room = cap - len(reps)
            k = min(n_for(pages), room)
            slot = min(per_cluster_cap, room)
            cluster_reps = picks_for(pages, k, k_max=slot)[:slot]
            reps.extend(cluster_reps)
        elif rep_all_content and not _blank(pages):
            cluster_reps = picks_for(pages, 1)[:1]
            extra.extend(cluster_reps)
        covered += len(pages)
        out_clusters.append({"n_pages": len(pages), "pages": pages,
                             "representatives": sorted(cluster_reps)})
    for p in (0, 1):
        if p < page_count and p not in reps:
            reps.append(p)
    return {"clusters": out_clusters, "representatives": sorted(set(reps)),
            "all_representatives": sorted(set(reps) | set(extra))}


def _cluster_signature(pages: list[int], profiles: dict[int, Counter],
                       weights: dict, theta: float) -> list[str]:
    """Human-readable stand-in for the five-signal tuple: the cluster's most
    discriminative token (highest weight x member-fraction). Keeps the output
    shape a drop-in for consumers that read cluster['signature'][0] as a
    display header (stage0_cluster.py). Empty-page clusters mirror common's
    '<empty>' signature."""
    frac: Counter = Counter()
    k = 0
    for p in pages:
        prof = profiles[p]
        if not prof:
            continue
        k += 1
        for t in prof:
            frac[t] += 1
    if k == 0:
        return ["<empty>"]
    top, score = None, -1.0
    for t, c in sorted(frac.items(), key=lambda kv: str(kv[0])):
        s = weights.get(t, 0.0) * (c / k)
        if s > score:
            top, score = t, s
    return [f"top:{top}", f"leader-jaccard theta={theta}"]


def cluster_pages_generic(doc, theta: float | None = None,
                          max_reps: int | None = None, coverage: float = 0.95,
                          page_lines: dict[int, list[Line]] | None = None,
                          method: str = "leader") -> dict:
    """Drop-in shaped counterpart of common.cluster_pages using the generic
    profile. theta=None (the default) selects theta per document by stability;
    pass a float to pin it (tests/probes). method: "leader" (best-fit leader +
    merge + reassign sweep) or "average" (average-linkage agglomerative over
    the same similarities; order-independent, no anchor bias). Accepts
    pre-parsed page_lines to avoid re-reading the PDF; if supplied it MUST
    cover every page 0..doc.page_count-1 (representatives and coverage are
    computed against the full document)."""
    if max_reps is None:
        max_reps = _MAX_REPS
    if page_lines is None:
        page_lines = {i: build_page_lines(doc[i]) for i in range(doc.page_count)}
    else:
        missing = set(range(doc.page_count)) - set(page_lines)
        if missing:
            raise ValueError(f"page_lines must cover all {doc.page_count} pages; "
                             f"missing e.g. {sorted(missing)[:5]}")
    profiles = {i: page_profile(page_lines[i], doc[i].rect.width, doc[i].rect.height)
                for i in page_lines}
    weights = token_weights(profiles)
    theta_diag = None
    if theta is None:
        theta, theta_diag, clusters = select_theta(profiles, weights,
                                                   return_clusters=True, method=method)
    elif method == "average":
        clusters = cluster_profiles_agglo(profiles, theta, weights)
    else:
        clusters = cluster_profiles(profiles, theta, weights)
    # max_extra_reps=4: only fragmented documents (many small-to-mid layout
    # families) ever spend these slots - measured to cut LLM-unseen pages from
    # ~20% to ~10% on the most fragmented books, no-op everywhere else.
    # profiles/weights switch on farthest-point diversity reps (structural
    # variants inside big clusters get shown, not just the midpoint page);
    # rep_all_content inventories one rep per tail cluster for the multi-pass
    # specialist planner (codegen.plan_passes).
    res = pick_representatives(clusters, doc.page_count, max_reps, coverage,
                               is_blank=lambda p: not profiles[p],
                               max_extra_reps=4,
                               profiles=profiles, weights=weights,
                               rep_all_content=True,
                               rep_radius=1.0 - theta)
    for c in res["clusters"]:
        c["signature"] = _cluster_signature(c["pages"], profiles, weights, theta)
    res["page_lines"] = page_lines
    res["theta"] = theta
    res["cluster_method"] = method
    if theta_diag is not None:
        res["theta_selection"] = theta_diag
    return res
