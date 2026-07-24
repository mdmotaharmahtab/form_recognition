"""Child-process runner for LLM-generated extraction code.

Runs as its OWN interpreter process (spawned by codegen.run_extractor) so that:
  - a hung/looping program can be killed hard on timeout (a thread cannot),
  - every run gets fresh module objects (generated code that mutates re/collections
    cannot leak state into later attempts or other documents),
  - a memory-hungry program dies with the child, not with the notebook kernel.

usage: python sandbox_runner.py <source.py> <doc.pdf>
stdout: one JSON object, either {"records": [...], "n_pages": N} or {"error": "..."}.

THREAT MODEL - read before trusting this. The namespace restriction below is a
guard against ACCIDENTAL imports/IO by generated code; it is NOT a security
boundary (CPython exec offers none - object-graph walks reach os regardless).
And "the author is our own LLM" is only half the story: the LLM's INPUT is the
PDF's own text, so a hostile document can prompt-inject the code-writing round,
and whatever gets written runs here with the calling user's privileges and
network access. The process boundary gives kill-ability and state isolation,
not privilege isolation. For untrusted input sources, run the whole pipeline
(or at least this child) in an unprivileged, network-less container.
"""
import builtins
import json
import sys
import traceback

# Modules the generated program may use: pure computation + text handling.
# unicodedata/string matter for non-Latin documents; nothing here reaches IO.
import bisect
import collections
import functools
import itertools
import math
import re
import statistics
import string
import unicodedata

_ALLOWED_MODULES = {m.__name__: m for m in (
    re, math, collections, itertools, functools, string, unicodedata, bisect,
    statistics, json)}

# A terminating-but-runaway program (e.g. a cross-product bug) can emit records
# without bound; serializing gigabytes would blow up the PARENT - the exact
# failure the process boundary exists to contain. 200k records on a 1000-page
# document is 200 fields/page: far beyond any real form book.
MAX_RECORDS = 200_000

_SAFE_BUILTIN_NAMES = [
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "complex", "delattr", "dict", "dir", "divmod",
    "enumerate", "filter", "float", "format", "frozenset", "getattr", "hasattr",
    "hash", "hex", "id", "int", "isinstance", "issubclass", "iter", "len",
    "list", "locals", "globals", "map", "max", "memoryview", "min", "next",
    "object", "oct", "ord", "pow", "range", "repr", "reversed", "round", "set",
    "setattr", "slice", "sorted", "staticmethod", "classmethod", "property",
    "str", "sum", "super", "tuple", "type", "vars", "zip", "NotImplemented",
    # class statements compile to a __build_class__ call - without it any
    # generated program that defines a class dies with NameError
    "__build_class__",
    # exception names a legitimate program may raise or CATCH; a missing name
    # here turns a valid `except MemoryError:` into a NameError at runtime
    "ArithmeticError", "AssertionError", "AttributeError", "BaseException",
    "Exception", "GeneratorExit", "IndexError", "KeyError", "LookupError",
    "MemoryError", "NameError", "NotImplementedError", "OverflowError",
    "RecursionError", "RuntimeError", "StopAsyncIteration", "StopIteration",
    "TypeError", "UnicodeDecodeError", "UnicodeEncodeError", "UnicodeError",
    "ValueError", "ZeroDivisionError",
]


def _restricted_import(name, *args, **kwargs):
    root = name.split(".")[0]
    if root in _ALLOWED_MODULES:
        # delegate to the real import machinery so dotted forms work too:
        # `from collections.abc import Iterable` needs the submodule loaded,
        # which returning the bare root object cannot provide
        return builtins.__import__(name, *args, **kwargs)
    raise ImportError(f"module {name!r} is not available in the extraction sandbox")


def _sandbox_globals() -> dict:
    safe = {n: getattr(builtins, n) for n in _SAFE_BUILTIN_NAMES}
    safe["__import__"] = _restricted_import
    safe["print"] = lambda *a, **k: None
    g = {"__builtins__": safe, "__name__": "<generated_extractor>"}
    g.update(_ALLOWED_MODULES)
    return g


def _limit_memory() -> None:
    try:  # Linux/Dataiku only; Windows has no resource module
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    _limit_memory()
    source_path, pdf_path = sys.argv[1], sys.argv[2]
    try:
        import fitz
        from common import build_page_lines

        with open(source_path, encoding="utf-8") as f:
            source = f.read()
        g = _sandbox_globals()
        exec(compile(source, "<generated_extractor>", "exec"), g)  # noqa: S102
        fn = g.get("extract")
        if not callable(fn):
            raise ValueError("generated code does not define extract(pages)")

        doc = fitz.open(pdf_path)
        if doc.needs_pass:
            raise ValueError("PDF is password-protected")
        pages = [(i, build_page_lines(doc[i])) for i in range(doc.page_count)]
        n_pages = doc.page_count
        doc.close()

        raw = fn(pages)
        if not isinstance(raw, list):
            try:  # a yield-based extract() is a legitimate program - materialize it
                raw = list(raw)
            except TypeError:
                raise ValueError(f"extract() must return a list, got {type(raw).__name__}")
        if len(raw) > MAX_RECORDS:
            raise ValueError(f"extract() returned {len(raw)} records "
                             f"(cap {MAX_RECORDS}) - runaway output")
        records = []
        for item in raw:
            if not isinstance(item, dict):
                records.append(None)  # malformed marker, judged by the parent
                continue
            try:  # page must be JSON-serializable here: a weird object (bytes,
                page = int(item.get("page"))  # ndarray) would kill json.dumps
            except (TypeError, ValueError):   # below and lose the whole verdict
                page = None
            records.append({"form_name": str(item.get("form_name") or ""),
                            "field_name": str(item.get("field_name") or ""),
                            "page": page})
        payload = {"records": records, "n_pages": n_pages}
    except Exception:  # noqa: BLE001 - everything becomes revision feedback upstream
        payload = {"error": traceback.format_exc(limit=6)}
    sys.stdout.write(json.dumps(payload))


if __name__ == "__main__":
    main()
