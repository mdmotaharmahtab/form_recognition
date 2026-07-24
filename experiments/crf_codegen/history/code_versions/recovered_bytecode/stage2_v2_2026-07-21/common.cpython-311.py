# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage2_v2_2026-07-21\common.cpython-311.pyc (Python 3.11)

'''Shared page model (Line / build_page_lines / dump_rep_page) plus the V1
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
'''
from __future__ import annotations
import hashlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass
import fitz
if not os.environ.get('ECS_BASE'):
    pass
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CRF_DIR = os.path.join(BASE, 'data', 'crf_forms')
OUT_DIR = os.path.join(BASE, 'experiments', 'recipe_prototype', 'out')
Line = <NODE:12>()

def build_page_lines(page = None):
    '''Visual lines with geometry, font size, colour and boldness.'''
    d = page.get_text('dict')
    lines = []
    for block in d.get('blocks', []):
        if block.get('type') != 0:
            continue
        for l in block.get('lines', []):
            if not l.get('spans'):
                spans = []
                text = (lambda .0: pass# WARNING: Decompyle incomplete
)(spans()).strip()
                if not text:
                    continue
            (x0, y0, x1, y1) = l['bbox']
            size = (lambda .0: pass# WARNING: Decompyle incomplete
)(spans())
            colors = sorted((lambda .0: pass# WARNING: Decompyle incomplete
)(spans()))
            bold = (lambda .0: pass# WARNING: Decompyle incomplete
)(spans())
            lines.append(Line(text, x0, y0, x1, y1, size, colors, bold))
            lines.sort(key = (lambda L: (round(L.y0, 1), L.x0)))
            return lines


def group_rows(lines = None, ytol = None):
    '''Group lines that sit on the same visual row (same y within tolerance).'''
    rows = []
    anchor = None
# WARNING: Decompyle incomplete

BRACKET_LINE = re.compile('^\\[[^\\]]+\\]')
INT_ONLY = re.compile('^\\d{1,3}(\\.\\d)?$')

def _bucket(x = None):
    if x == 0:
        pass
    elif x < 0.25:
        pass
    
    return 'hi'


def page_fingerprint(lines = None, page_width = None):
    '''Coarse layout signature built from structure only (never from page content),
    so that e.g. 900 form pages with different questions land in one cluster.

    All cutoffs below (0.25 bucket split, 10% column-presence, 10/40/90 density
    bands, 4 x-bins) are tuned coarseness knobs, not correctness constraints:
    they trade cluster count against representative-page count. Documents with
    unusual line densities may over/under-merge; the coverage-confirm and audit
    rounds are the safety net for that, not these numbers.'''
    pass
# WARNING: Decompyle incomplete


def cluster_pages(doc = None, max_reps = None, coverage = None):
    '''V1 exact-tuple clustering (reference baseline - the shipped pipeline calls
    generic_profile.cluster_pages_generic instead). Assign every page to a layout
    cluster; pick representatives from the biggest clusters until `coverage` of
    pages is represented (capped at `max_reps`).'''
    sigs = defaultdict(list)
    page_lines = { }
    for i in range(doc.page_count):
        page = doc[i]
        lines = build_page_lines(page)
        page_lines[i] = lines
        sigs[page_fingerprint(lines, page.rect.width)].append(i)
        ordered = sorted(sigs.items(), key = (lambda kv: -len(kv[1])))
        reps = []
        covered = 0
        clusters = []
        for sig, pages in ordered:
            if covered < coverage * doc.page_count:
                is_rep_cluster = len(reps) < max_reps
            cluster_reps = [
                pages[len(pages) // 2]] if is_rep_cluster else []
            if is_rep_cluster and len(pages) > 50:
                cluster_reps.append(pages[len(pages) // 4])
            reps.extend(cluster_reps)
            covered += len(pages)
            clusters.append({
                'signature': list(map(str, sig)),
                'n_pages': len(pages),
                'pages': pages,
                'representatives': sorted(cluster_reps) })
            for p in (0, 1):
                if p < doc.page_count and p not in reps:
                    reps.append(p)
                return {
                    'clusters': clusters,
                    'page_lines': page_lines,
                    'representatives': sorted(set(reps)) }


def dump_rep_page(lines = None, path = None):
    '''Structured text dump of one page - this is what recipe induction gets to see.'''
    f = open(path, 'w', encoding = 'utf-8')
    for L in lines:
        color = '#{:06x}'.format(L.colors[-1]) if L.non_black else 'black  '
        f.write(f'''x={L.x0:6.1f} y={L.y0:6.1f} sz={L.size:4.1f} {color} {'B' if L.bold else ' '} | {L.text}\n''')
        None(None, None)
        return None
        with None:
            if not None:
                pass


def list_root_pdfs():
    return (lambda .0: pass# WARNING: Decompyle incomplete
)(os.listdir(CRF_DIR)())


def doc_key(path = None):
    """Filesystem-safe per-document key. Long names get a hash suffix so two
    documents sharing a 70-char prefix cannot collide on the same output dir
    (which would silently cross-contaminate clusters.json and extraction CSVs).
    A stem with no ASCII alphanumerics at all (fully non-Latin filenames)
    sanitizes to bare underscores - every such file would collide on '_', so
    those become a hash key outright. Partially non-Latin names can still
    collide after sanitization; both batch drivers guard that with a loud
    doc_key-collision check before spending any budget."""
    stem = os.path.splitext(os.path.basename(path))[0]
    key = re.sub('[^A-Za-z0-9_.-]+', '_', stem)
    if not re.search('[A-Za-z0-9]', key):
        return 'doc_' + hashlib.sha1(stem.encode('utf-8')).hexdigest()[:12]
    if None(key) <= 70:
        return key
    return None[:61] + '_' + hashlib.sha1(stem.encode('utf-8')).hexdigest()[:8]

