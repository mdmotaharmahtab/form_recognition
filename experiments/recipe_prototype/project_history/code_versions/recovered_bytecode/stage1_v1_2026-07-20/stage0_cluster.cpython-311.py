# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage1_v1_2026-07-20\stage0_cluster.cpython-311.pyc (Python 3.11)

'''Stage 0: cluster every page of every CRF by layout fingerprint, save representative
page dumps (structured text) and PNGs. These representatives are the ONLY thing the
recipe-induction step (LLM in production, hand-authored in this prototype) may look at.
'''
import glob
import json
import os
import fitz
from common import OUT_DIR, cluster_pages, doc_key, dump_rep_page, list_root_pdfs

def run(path = None):
    '''Cluster one document; returns meta. Documents the pipeline cannot process
    are detected HERE, before any LLM budget is spent, and marked with a non-ok
    status in the meta (drivers must check it): encrypted PDFs, and scanned/
    image-only PDFs with no text layer (OCR is out of scope - fail loudly).'''
    key = doc_key(path)
    out = os.path.join(OUT_DIR, key)
    os.makedirs(out, exist_ok = True)
    for stale in glob.glob(os.path.join(out, 'rep_*')):
        os.remove(stale)
        doc = fitz.open(path)
        if doc.needs_pass:
            doc.close()
            meta = {
                'file': os.path.basename(path),
                'status': 'encrypted',
                'pages': 0,
                'n_clusters': 0,
                'representative_pages_1based': [],
                'clusters': [] }
            f = open(os.path.join(out, 'clusters.json'), 'w', encoding = 'utf-8')
            json.dump(meta, f, indent = 1)
            None(None, None)
        else:
            with None:
                if not None:
                    pass
    return meta
    res = cluster_pages(doc)
    clusters = res['clusters']
    page_lines = res['page_lines']
    pages_without_text = (lambda .0: pass# WARNING: Decompyle incomplete
)(page_lines.values()())
    text_layer_pct = round(100 * (doc.page_count - pages_without_text) / max(1, doc.page_count))
    rep_pages = res['representatives']
    for p in rep_pages:
        dump_rep_page(page_lines[p], os.path.join(out, f'''rep_p{p + 1}.txt'''))
        doc[p].get_pixmap(dpi = 100).save(os.path.join(out, f'''rep_p{p + 1}.png'''))
    meta = {
        'file': doc.page_count,
        'status': text_layer_pct,
        'pages': len(clusters),
        'text_layer_pct': (lambda .0: [ p + 1 for p in .0 ]),
        'n_clusters': rep_pages(),
        'representative_pages_1based': (lambda .0: [ c.items()() | {
'header': c['signature'][0] } for c in .0 ]),
        'clusters': clusters() }
    f = open(os.path.join(out, 'clusters.json'), 'w', encoding = 'utf-8')
    json.dump(meta, f, indent = 1)
    None(None, None)

if __name__ == '__main__':
    summary = []
    for path in list_root_pdfs():
        m = run(path)
        summary.append(m)
        flag = '' if m.get('status', 'ok') == 'ok' else f'''  [{m['status']} - skipping induction]'''
        print(f'''{m['file'][:60]:60s} pages={m['pages']:5d} clusters={m['n_clusters']:3d} reps={len(m['representative_pages_1based']):3d}{flag}''')
        total_pages = (lambda .0: pass# WARNING: Decompyle incomplete
)(summary())
        total_reps = (lambda .0: pass# WARNING: Decompyle incomplete
)(summary())
        print(f'''\nTOTAL pages={total_pages}  representative pages={total_reps} ({100 * total_reps / total_pages:.1f}% would go to the LLM)''')
        return None
        return None
