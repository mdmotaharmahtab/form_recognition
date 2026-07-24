"""Shared page model (Line / build_page_lines / dump_rep_page) plus the V1
five-signal layout fingerprint, kept as a reference baseline.

Pipeline stages:
  stage 0  - cluster pages by structural layout, pick representative pages.
             SHIPPED front-end: generic_profile.cluster_pages_generic (word-blind
             typography tokens, per-document chrome damping, weighted-Jaccard
             leader clustering, per-document theta by stability selection).
             page_fingerprint/cluster_pages below are the v1 five-signal method,
             retained for comparison probes (generic_cluster_probe, qsc_merge_diag).
  stage 1  - LLM writes a document-specific extraction program from the
             representative pages (codegen.py) and revises it in a bounded loop
  stage 2  - the accepted program replays deterministically over every page
"""
from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass

import fitz

# Repo root discovery is location-independent: walk up until the shared input
# corpus (data/crf_forms) is found. ECS_BASE env var overrides (the Dataiku
# notebook always sets it, so these repo-relative defaults only matter for
# local runs). This module now lives at <repo>/experiments/crf_codegen/src/
# pipeline/, but the walk-up keeps working if the tree is relocated.
def _discover_base() -> str:
    env = os.environ.get("ECS_BASE")
    if env:
        return env
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):
        if os.path.isdir(os.path.join(d, "data", "crf_forms")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    # fallback: five levels up (crf_codegen/src/pipeline/common.py -> repo root)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))))


BASE = _discover_base()
# The CRF corpus is the SHARED input; it stays at the repo root and is never
# duplicated into the structured project folder.
CRF_DIR = os.path.join(BASE, "data", "crf_forms")

# The structured project's own root (experiments/crf_codegen), used to anchor
# the default run-output directory.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
# ECS_OUT_DIR lets a run write its artifacts into an isolated directory (e.g. a
# side-by-side ablation) without touching the default corpus outputs; unset =
# the default corpus run root under this project's data/runs/.
OUT_DIR = os.environ.get("ECS_OUT_DIR") or os.path.join(
    PROJECT_ROOT, "data", "runs", "corpus_cli")


# --------------------------------------------------------------------------- #
# Per-document artifact layout
# --------------------------------------------------------------------------- #
# Every per-document artifact lives in a TYPE bucket under its <doc_key>/ dir,
# instead of ~90 flat files. Routing is deterministic from the filename alone
# (no tag parsing), so writers and readers stay in sync by calling art():
#
#   <doc_key>/
#     stage0/       clusters.json, rep_p*.{txt,png}, title_p*.{txt,png}
#     prompts/      codegen_prompt*.txt, induction_prompt.txt, *_confirm_prompt.txt
#     extractors/   generated_extractor_<tag>[_passN].py   (final programs)
#     fields/       fields_codegen_<tag>[_passN].csv       (extraction output)
#     trails/       codegen_trail_<tag>[_passN].json       (decision log)
#     llm_calls/    llm_calls_<tag>[_passN].jsonl          (verbatim calls)
#     timings/      timings_<tag>[_passN].json             (per-doc profile)
#     replies/      codegen_reply_<tag>_*.{py,txt}         (raw model replies)
#
# Run-root files (cli_induction_summary_*.json, cli_error_*, etc.) are NOT
# per-document and stay at the run root.
ART_BUCKETS = ("stage0", "prompts", "extractors", "fields", "trails",
               "llm_calls", "timings", "replies")


def artifact_bucket(name: str) -> str:
    """Type bucket for a per-document artifact filename ('' = run-root)."""
    if "prompt" in name:                         # any *_prompt*.txt
        return "prompts"
    if (name == "clusters.json" or name.startswith("rep_p")
            or name.startswith("title_p")):
        return "stage0"
    if name.startswith("codegen_reply"):
        return "replies"
    if name.startswith("generated_extractor"):
        return "extractors"
    if name.startswith("fields_codegen"):
        return "fields"
    if name.startswith("codegen_trail"):
        return "trails"
    if name.startswith("llm_calls"):
        return "llm_calls"
    if name.startswith("timings"):
        return "timings"
    return ""


def art(outdir: str, name: str, mkdir: bool = False) -> str:
    """Path to a per-document artifact inside its type bucket. Writers pass
    mkdir=True to create the bucket dir; readers use the default."""
    bucket = artifact_bucket(name)
    directory = os.path.join(outdir, bucket) if bucket else outdir
    if mkdir and bucket:
        os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, name)


def art_bucket_dir(outdir: str, bucket: str) -> str:
    """Directory of one artifact bucket (for listdir/glob-based discovery)."""
    return os.path.join(outdir, bucket)


@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    colors: tuple
    bold: bool

    @property
    def non_black(self) -> bool:
        return any(c != 0 for c in self.colors)


def build_page_lines(page) -> list[Line]:
    """Visual lines with geometry, font size, colour and boldness."""
    d = page.get_text("dict")
    lines: list[Line] = []
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for l in block.get("lines", []):
            spans = l.get("spans") or []
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            x0, y0, x1, y1 = l["bbox"]
            size = max(round(s.get("size", 0.0), 1) for s in spans)
            colors = tuple(sorted({s.get("color", 0) for s in spans}))
            # name substring OR the font-descriptor bold bit (flags 2**4): many
            # non-Latin/embedded fonts carry weight in the descriptor but not in
            # the name (e.g. CJK "...-W6"), which would blind .bold entirely
            bold = any("bold" in (s.get("font", "") or "").lower()
                       or (s.get("flags", 0) & 16) for s in spans)
            lines.append(Line(text, x0, y0, x1, y1, size, colors, bold))
    lines.sort(key=lambda L: (round(L.y0, 1), L.x0))
    return lines


def group_rows(lines: list[Line], ytol: float = 3.5) -> list[list[Line]]:
    """Group lines that sit on the same visual row (same y within tolerance)."""
    rows: list[list[Line]] = []
    anchor = None
    for L in lines:
        if anchor is None or L.y0 - anchor > ytol:
            rows.append([L])
            anchor = L.y0
        else:
            rows[-1].append(L)
    for r in rows:
        r.sort(key=lambda L: L.x0)
    return rows


# ---- V1 five-signal fingerprint (reference baseline; superseded in the shipped
# pipeline by generic_profile.py). HEURISTIC bucketing features, not extraction
# logic: a wrong bucket only means a layout gets split into two clusters
# (costing one extra representative page), never a wrong extraction.
# BRACKET_LINE ([...]-only lines) is a common annotation convention but not
# universal - it is one signal among five, not a requirement.
BRACKET_LINE = re.compile(r"^\[[^\]]+\]")
INT_ONLY = re.compile(r"^\d{1,3}(\.\d)?$")


def _bucket(x: float) -> str:
    return "0" if x == 0 else "lo" if x < 0.25 else "hi"


def page_fingerprint(lines: list[Line], page_width: float) -> tuple:
    """Coarse layout signature built from structure only (never from page content),
    so that e.g. 900 form pages with different questions land in one cluster.

    All cutoffs below (0.25 bucket split, 10% column-presence, 10/40/90 density
    bands, 4 x-bins) are tuned coarseness knobs, not correctness constraints:
    they trade cluster count against representative-page count. Documents with
    unusual line densities may over/under-merge; the coverage-confirm and audit
    rounds are the safety net for that, not these numbers."""
    if not lines:
        return ("<empty>",)
    n = len(lines)
    bracket = _bucket(sum(1 for L in lines if BRACKET_LINE.match(L.text)) / n)
    ints = _bucket(sum(1 for L in lines if INT_ONLY.match(L.text)) / n)
    color = _bucket(sum(1 for L in lines if L.non_black) / n)
    nbins = 4
    xhist = [0] * nbins
    for L in lines:
        xhist[min(nbins - 1, int(L.x0 / max(page_width, 1) * nbins))] += 1
    xsig = "".join("1" if c >= max(2, n * 0.10) else "0" for c in xhist)
    size_bucket = "s" if n <= 10 else "m" if n <= 40 else "l" if n <= 90 else "xl"
    return (bracket, ints, color, size_bucket, xsig)


def cluster_pages(doc, max_reps: int = 10, coverage: float = 0.95) -> dict:
    """V1 exact-tuple clustering (reference baseline - the shipped pipeline calls
    generic_profile.cluster_pages_generic instead). Assign every page to a layout
    cluster; pick representatives from the biggest clusters until `coverage` of
    pages is represented (capped at `max_reps`)."""
    sigs: dict[tuple, list[int]] = defaultdict(list)
    page_lines: dict[int, list[Line]] = {}
    for i in range(doc.page_count):
        page = doc[i]
        lines = build_page_lines(page)
        page_lines[i] = lines
        sigs[page_fingerprint(lines, page.rect.width)].append(i)

    ordered = sorted(sigs.items(), key=lambda kv: -len(kv[1]))
    clusters, covered, reps = [], 0, []
    for sig, pages in ordered:
        is_rep_cluster = covered < coverage * doc.page_count and len(reps) < max_reps
        cluster_reps = [pages[len(pages) // 2]] if is_rep_cluster else []
        if is_rep_cluster and len(pages) > 50:  # very dominant layout: show two examples
            cluster_reps.append(pages[len(pages) // 4])
        reps.extend(cluster_reps)
        covered += len(pages)
        clusters.append({
            "signature": list(map(str, sig)),
            "n_pages": len(pages),
            "pages": pages,  # full list - validation uses it to localize failures per cluster
            "representatives": sorted(cluster_reps),
        })
    # first two pages carry format identity (title, TOC) - always include as context
    for p in (0, 1):
        if p < doc.page_count and p not in reps:
            reps.append(p)
    return {"clusters": clusters, "page_lines": page_lines, "representatives": sorted(set(reps))}


def dump_rep_page(lines: list[Line], path: str) -> None:
    """Structured text dump of one page - this is what recipe induction gets to see."""
    with open(path, "w", encoding="utf-8") as f:
        for L in lines:
            color = "#{:06x}".format(L.colors[-1]) if L.non_black else "black  "
            f.write(f"x={L.x0:6.1f} y={L.y0:6.1f} sz={L.size:4.1f} {color} {'B' if L.bold else ' '} | {L.text}\n")


def pick_title_context_pages(page_lines: dict[int, list[Line]],
                             page_heights: dict[int, float] | None = None,
                             exclude=(), max_pages: int = 6) -> list[int]:
    """Select a small, word-blind TITLE-CONTEXT pack (0-based pages).

    Layout representatives optimize structural coverage, so all of them can be
    continuation pages that omit the form title. This independent channel looks
    only at repeated TOP-OF-PAGE context:

    * globally ubiquitous strings are chrome, so they carry no title identity;
    * strings recurring on at least two but fewer than 95% of pages can identify
      a form/section run without knowing any vocabulary;
    * pages are grouped by the SET of such strings they carry, then one page is
      chosen from each largest distinct group.

    The selector does not claim which line is the title. It gives the LLM pages
    where repeated header context CHANGES, so it can distinguish a human-facing
    grouping title from invariant furniture and per-field text. `exclude`
    prevents wasting prompt space on pages already shown as layout reps.
    Deterministic; no corpus strings, language assumptions, embeddings or APIs.
    """
    pages = sorted(page_lines)
    if max_pages <= 0 or len(pages) < 2:
        return []
    page_heights = page_heights or {}
    excluded = set(exclude or ())
    occurrences: dict[str, set[int]] = defaultdict(set)
    page_keys: dict[int, set[str]] = {}

    for p in pages:
        lines = page_lines.get(p) or []
        height = page_heights.get(p) or max(
            (L.y1 for L in lines), default=800.0)
        # Top 30% accommodates multi-row CRF headers while excluding activity/
        # question blocks in the body. It scales with each page, not PDF points.
        top = [L for L in lines if L.y0 <= 0.30 * max(height, 1.0)]
        keys = set()
        for L in top:
            text = re.sub(r"\s+", " ", L.text).strip()
            if not (5 <= len(text) <= 180):
                continue
            # Unicode-aware "contains a letter"; bare IDs/page numbers are poor
            # title evidence, while titles in any script remain eligible.
            if not any(ch.isalpha() for ch in text):
                continue
            key = text.casefold()
            keys.add(key)
            occurrences[key].add(p)
        page_keys[p] = keys

    n_pages = len(pages)
    useful = {
        key for key, pgs in occurrences.items()
        if len(pgs) >= 2 and len(pgs) < 0.95 * n_pages
    }
    if not useful:
        return []

    # A signature is the changing repeated header context on that page.
    groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for p in pages:
        sig = tuple(sorted(page_keys[p] & useful))
        if sig:
            groups[sig].append(p)

    # Largest runs first; ties by earliest page. Within a run, use its earliest
    # page not already shown - run starts are the most likely title announcement.
    ordered = sorted(groups.values(), key=lambda ps: (-len(ps), ps[0]))
    picks = []
    for group in ordered:
        p = next((x for x in group if x not in excluded), None)
        if p is not None:
            picks.append(p)
        if len(picks) >= max_pages:
            break
    return sorted(picks)


def list_root_pdfs() -> list[str]:
    return sorted(
        os.path.join(CRF_DIR, fn)
        for fn in os.listdir(CRF_DIR)
        if fn.lower().endswith(".pdf")
    )


def doc_key(path: str) -> str:
    """Filesystem-safe per-document key. Long names get a hash suffix so two
    documents sharing a 70-char prefix cannot collide on the same output dir
    (which would silently cross-contaminate clusters.json and extraction CSVs).
    A stem with no ASCII alphanumerics at all (fully non-Latin filenames)
    sanitizes to bare underscores - every such file would collide on '_', so
    those become a hash key outright. Partially non-Latin names can still
    collide after sanitization; both batch drivers guard that with a loud
    doc_key-collision check before spending any budget."""
    stem = os.path.splitext(os.path.basename(path))[0]
    key = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)
    if not re.search(r"[A-Za-z0-9]", key):
        return "doc_" + hashlib.sha1(stem.encode("utf-8")).hexdigest()[:12]
    if len(key) <= 70:
        return key
    return key[:61] + "_" + hashlib.sha1(stem.encode("utf-8")).hexdigest()[:8]
