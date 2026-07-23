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

# repo root = two levels above this file; ECS_BASE env var overrides (the Dataiku
# notebook does not use these paths at all - it reads from managed folders)
BASE = os.environ.get("ECS_BASE") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CRF_DIR = os.path.join(BASE, "data", "crf_forms")
OUT_DIR = os.path.join(BASE, "experiments", "recipe_prototype", "out")


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
