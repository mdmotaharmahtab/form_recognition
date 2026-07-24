"""Harvest real example lines for each of the five fingerprint signals from the
CRF corpus, so documentation examples are genuine. For a handful of pages across
the three processed books (plus an OID-annotated book for bracket lines), print
the signature, per-signal counts, and sample lines in each category."""
import fitz

from common import BRACKET_LINE, INT_ONLY, build_page_lines, page_fingerprint

CASES = [
    (r"..\..\data\crf_forms\384-201-00002_Annotated Unique CRF_04Nov2024.pdf", [1, 116, 133, 231]),
    (r"..\..\data\crf_forms\QSC302573 Final AnnotatedCRFs 16Oct2024-326-201-00007 (1).pdf", [3, 10]),
    (r"..\..\data\crf_forms\MAC186_X11-201-00001_eCRF v1.10_form tracker v1.6_06Mar2025.pdf", [5, 200]),
    (r"..\..\data\crf_forms\384-201-00004_aCRF_16JAN2025.pdf", [4, 5, 6]),
]

for path, pages_1b in CASES:
    try:
        doc = fitz.open(path)
    except Exception as e:
        print(f"OPEN FAILED {path}: {e}")
        continue
    name = path.split("\\")[-1][:48]
    for p1 in pages_1b:
        if p1 > doc.page_count:
            continue
        page = doc[p1 - 1]
        lines = build_page_lines(page)
        sig = page_fingerprint(lines, page.rect.width)
        br = [L.text for L in lines if BRACKET_LINE.match(L.text)]
        ints = [L.text for L in lines if INT_ONLY.match(L.text)]
        col = [(L.text, "#{:06x}".format(L.colors[-1])) for L in lines if L.non_black]
        print(f"\n=== {name} p{p1}  n={len(lines)}  sig={sig}")
        print(f"  bracket-only {len(br)}: {br[:6]}")
        print(f"  int-only {len(ints)}: {ints[:10]}")
        print(f"  colored {len(col)}: {col[:5]}")
        print(f"  first lines: {[L.text[:38] for L in lines[:5]]}")
    doc.close()
