"""Harvest REAL numbers for docs/crf_codegen_deep_dive.html section 3 (generic
clustering): new stack layout of the Rave book, token examples from page 133,
QSC chrome-token weights, and theta-selection diagnostics for the plateau chart.
Prints one JSON blob; the doc quotes from it verbatim."""
import json
import os

import fitz

from common import CRF_DIR, build_page_lines
from generic_profile import (page_profile, select_theta, token_weights)

RAVE = os.path.join(CRF_DIR, "384-201-00002_Annotated Unique CRF_04Nov2024.pdf")
QSC = os.path.join(CRF_DIR, "QSC302573 Final AnnotatedCRFs 16Oct2024-326-201-00007 (1).pdf")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out",
                   "384-201-00002_Annotated_Unique_CRF_04Nov2024", "clusters.json")

report = {}

# ---- 1. new Rave stacks + where p133 landed --------------------------------
with open(OUT, encoding="utf-8") as f:
    meta = json.load(f)
stacks = [{"n_pages": c["n_pages"], "reps_1based": [p + 1 for p in c["representatives"]],
           "header": c["header"]} for c in meta["clusters"]]
p133_stack = next(i for i, c in enumerate(meta["clusters"]) if 132 in c["pages"])
report["rave"] = {"theta": meta["theta"], "n_clusters": meta["n_clusters"],
                  "reps_1based": meta["representative_pages_1based"],
                  "stacks": stacks, "p133_in_stack": p133_stack,
                  "p133_stack_size": meta["clusters"][p133_stack]["n_pages"],
                  "theta_selection": meta["theta_selection"]}

# ---- 2. real token examples from Rave p133 ---------------------------------
doc = fitz.open(RAVE)
page = doc[132]
lines = build_page_lines(page)
prof = page_profile(lines, page.rect.width, page.rect.height)
# recompute the per-line token the same way page_profile does
from generic_profile import X_BINS, _charclass, _size_rel
from collections import Counter
sizes = Counter(round(L.size, 1) for L in lines)
modal = sizes.most_common(1)[0][0]
examples = []
for L in lines:
    xb = min(X_BINS - 1, int(L.x0 / max(page.rect.width, 1) * X_BINS))
    tok = (xb, _size_rel(L.size, modal), "B" if L.bold else ".",
           "C" if L.non_black else ".", _charclass(L.text))
    examples.append({"text": L.text[:60], "x0": round(L.x0, 1), "size": L.size,
                     "bold": L.bold, "token": list(map(str, tok))})
report["p133"] = {"modal_size": modal, "n_lines": len(lines),
                  "n_distinct_tokens": len(prof), "examples": examples}
doc.close()

# ---- 3. QSC chrome: token weights + which p10 lines are chrome -------------
doc = fitz.open(QSC)
page_lines = {i: build_page_lines(doc[i]) for i in range(doc.page_count)}
profiles = {i: page_profile(page_lines[i], doc[i].rect.width, doc[i].rect.height)
            for i in page_lines}
w = token_weights(profiles)
n_pages = sum(1 for p in profiles.values() if p)
from collections import Counter as C2
df = C2()
for p in profiles.values():
    for t in p:
        df[t] += 1
# REPORTING cutoff only (damping itself is smooth): w<0.3 = tokens on >~88% of
# pages; make_generic_snippets.py draws the image at the stricter w<0.1
chrome = sorted(((str(t), df[t], round(w[t], 4)) for t in w if w[t] < 0.3),
                key=lambda x: x[2])
report["qsc"] = {"pages": doc.page_count, "pages_with_text": n_pages,
                 "n_tokens_total": len(w),
                 "n_chrome_tokens_w_lt_03": len(chrome),
                 "chrome_tokens": chrome[:25]}

# p10 line-level chrome flags for the image
sizes = C2(round(L.size, 1) for L in page_lines[9])
modal = sizes.most_common(1)[0][0]
p10 = []
from generic_profile import _charclass as cc, _size_rel as sr
for L in page_lines[9]:
    xb = min(X_BINS - 1, int(L.x0 / max(doc[9].rect.width, 1) * X_BINS))
    tok = (xb, sr(L.size, modal), "B" if L.bold else ".",
           "C" if L.non_black else ".", cc(L.text))
    p10.append({"text": L.text[:45], "weight": round(w.get(tok, 0.0), 3)})
report["qsc_p10_lines"] = p10

# theta selection diag for QSC (for the plateau chart)
theta_q, diag_q = select_theta(profiles)
report["qsc_theta"] = {"theta": theta_q, **diag_q}
doc.close()

print(json.dumps(report, indent=1))
