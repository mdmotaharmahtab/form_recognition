"""Mechanical smoke tests for the extraction executor + gates.

Run after any pipeline change:  python smoke_test.py
Covers the failure modes the generalization review flagged:
  - generated programs may define classes, use unicodedata, return generators
  - banned imports fail loudly with a sandbox message
  - a hung program is killed (process boundary), not leaked as a zombie thread
  - previously accepted extractors still reproduce their saved outputs
"""
import csv
import glob
import os
import sys
import time

import fitz

# pipeline modules (codegen/common etc.) live in the sibling src/pipeline/ package
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from codegen import run_extractor  # noqa: E402
from common import OUT_DIR, art, art_bucket_dir, doc_key, list_root_pdfs  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
failures = []


def check(name: str, ok: bool, note: str = "") -> None:
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  ({note})" if note else ""))
    if not ok:
        failures.append(name)


def smallest_pdf() -> str:
    best, best_pages = None, 10 ** 9
    for p in list_root_pdfs():
        n = fitz.open(p).page_count
        if n < best_pages:
            best, best_pages = p, n
    return best


CLASS_PROGRAM = """
import unicodedata

class Collector:
    def __init__(self):
        self.records = []
    def add(self, form, field, page):
        self.records.append({"form_name": form, "field_name": field, "page": page})

def extract(pages):
    c = Collector()
    for pno, lines in pages:
        for L in lines[:2]:
            if L.text and unicodedata.category(L.text[0]).startswith(("L", "N")):
                c.add("smoke form", "label " + L.text[:20], pno + 1)
    return c.records
"""

GENERATOR_PROGRAM = """
def extract(pages):
    for pno, lines in pages:
        for L in lines[:1]:
            yield {"form_name": "g", "field_name": "field " + L.text[:10], "page": pno + 1}
"""

BANNED_IMPORT_PROGRAM = """
import os

def extract(pages):
    return [{"form_name": "x", "field_name": os.getcwd(), "page": 1}]
"""

HANG_PROGRAM = """
def extract(pages):
    n = 0
    while True:
        n += 1
    return []
"""


def main() -> None:
    pdf = smallest_pdf()
    print(f"capability tests on {os.path.basename(pdf)}")

    res = run_extractor(CLASS_PROGRAM, pdf)
    check("class definitions + unicodedata usable", len(res.records) > 0,
          f"{len(res.records)} records")

    res = run_extractor(GENERATOR_PROGRAM, pdf)
    check("generator extract() materialized", len(res.records) > 0,
          f"{len(res.records)} records")

    try:
        run_extractor(BANNED_IMPORT_PROGRAM, pdf)
        check("banned import rejected", False, "import os was allowed")
    except RuntimeError as e:
        check("banned import rejected", "not available in the extraction sandbox" in str(e))

    t0 = time.time()
    try:
        run_extractor(HANG_PROGRAM, pdf, timeout_s=20)
        check("hung program killed", False, "no timeout raised")
    except TimeoutError:
        check("hung program killed", time.time() - t0 < 40, f"{time.time() - t0:.0f}s wall")

    print("replaying saved accepted extractors")
    replayed = 0
    for pdf_path in list_root_pdfs():
        outdir = os.path.join(OUT_DIR, doc_key(pdf_path))
        for src_path in sorted(glob.glob(os.path.join(
                art_bucket_dir(outdir, "extractors"), "generated_extractor_*.py"))):
            tag = os.path.basename(src_path)[len("generated_extractor_"):-3]
            if "_pass" in tag:
                # specialist extractors run over the full document but their
                # saved CSVs are MASKED to the pass's layout scope (specialists
                # may legitimately emit records for foreign layouts, which the
                # harness discards) - an unmasked rerun cannot match the CSV
                continue
            csv_path = art(outdir, f"fields_codegen_{tag}.csv")
            if not os.path.exists(csv_path):
                continue
            with open(src_path, encoding="utf-8") as f:
                source = f.read()
            with open(csv_path, encoding="utf-8") as f:
                saved = sum(1 for _ in csv.DictReader(f))
            res = run_extractor(source, pdf_path)
            check(f"{doc_key(pdf_path)[:40]} [{tag}] reproduces saved output",
                  len(res.records) == saved, f"{len(res.records)} vs saved {saved}")
            replayed += 1
    if not replayed:
        print("  (no saved extractors found)")

    print(f"\n{len(failures)} failure(s)" if failures else "\nall smoke tests passed")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
