"""Stage-attributed error report: WHERE in the pipeline do errors come from?

Derived post-hoc from artifacts the pipeline already writes - each document's
codegen_trail_<tag>.json plus the run's summary rows - so the loop controller
carries no reporting logic and PAST runs can be re-analyzed with this same
module. One flat event row per finding:

    doc, stage, version, severity, code, detail

  stage     stage0 | generate | revise | confirm | audit | gates | loop |
            export | mapping | driver
  severity  fatal    the document yielded nothing usable (skipped, crashed,
                     no version ever passed gates, export failed)
            blocking a parser version was rejected or a call failed; the loop
                     handled it (revision / retry) but it cost budget
            quality  review signals: audit findings, soft gate warnings,
                     partial audit replies, open issues at stop

Stage attribution comes from the trail's structure (cycle `kind`, doc status),
never from parsing prose. The finer `code` classifies known gate/warning
strings by stable prefixes/substrings with an `*_other` fallback - so a new
gate message degrades to a coarser code, never to a wrong one.

Artifacts written by write_reports (at the run root, next to the summary):
  <prefix>error_events_<tag>.csv    the flat event log (analysis-friendly)
  <prefix>error_summary_<tag>.json  counts by stage / code / severity / doc
"""
import csv
import json
import os
import time
from collections import Counter

FATAL, BLOCKING, QUALITY = "fatal", "blocking", "quality"

# cycle `kind` (run_cli_induction trail) -> pipeline stage
KIND_STAGE = {
    "generate": "generate",
    "revise_gates": "revise",
    "revise_audit": "revise",
    "confirm": "confirm",
    "confirm_extension": "confirm",
    "audit": "audit",
}

# gate problem strings (induction.gate_problems / codegen.validate_generated).
# Prefix-matched in order; first hit wins.
_PROBLEM_CODES = [
    ("The program extracted ZERO records", "gate_zero_records"),
    ("Only ", "gate_too_few_records"),
    ("Records carry no valid 1-based", "gate_no_page_numbers"),
    ("Program failed to run:", "gate_crash"),
    ("Recipe failed to execute:", "gate_crash"),
]

# gate warning strings (induction.gate_warnings). Substring-matched.
_WARNING_CODES = [
    ("form_name empty for", "warn_form_names_empty"),
    ("look like human labels", "warn_labels_not_human"),
    ("distinct form_names", "warn_form_explosion"),
    ("plausible for a document this small", "warn_low_volume_small_doc"),
    ("look like machine codes", "warn_oid_shape"),
    ("definition pages were detected", "warn_broken_join"),
]


def classify_problem(p: str) -> str:
    for prefix, code in _PROBLEM_CODES:
        if p.startswith(prefix):
            return code
    return "gate_other"


def classify_warning(w: str) -> str:
    for sub, code in _WARNING_CODES:
        if sub in w:
            return code
    return "warn_other"


def events_for_doc(doc: str, trail_obj: dict, row: dict) -> list[dict]:
    """All events for one document, from its trail + its summary row.

    trail_obj is the codegen_trail_<tag>.json object ({} when the document
    never reached the loop); row is its summary row ({} tolerated)."""
    events: list[dict] = []

    def add(stage, severity, code, detail, version=None):
        events.append({"doc": doc, "stage": stage, "version": version,
                       "severity": severity, "code": code,
                       "detail": str(detail)[:300]})

    for c in (trail_obj or {}).get("cycles", []):
        v = c.get("version")
        stage = KIND_STAGE.get(c.get("kind") or "", c.get("kind") or "loop")
        if c.get("transport_error"):
            # doc-level fatality (if any) is judged from the summary status
            # below; here the event records which call failed
            add(stage, BLOCKING, "transport_error", c["transport_error"], v)
            continue
        for p in c.get("problems") or []:
            add("gates", BLOCKING, classify_problem(p), p, v)
        for w in c.get("warnings") or []:
            add("gates", QUALITY, classify_warning(w), w, v)
        for av in c.get("audit_verdicts") or []:
            page = av.get("page")
            for key, code in (("missed", "audit_missed"),
                              ("false", "audit_false_positive"),
                              ("wrong_form", "audit_wrong_form")):
                for item in av.get(key) or []:
                    add("audit", QUALITY, code, f"p{page}: {item}", v)
        if c.get("audit_partial"):
            add("audit", QUALITY, "audit_partial_reply",
                "audit reply did not cover every sampled page", v)
        if c.get("kind") == "confirm" and c.get("outcome") == "extension_rejected":
            add("confirm", QUALITY, "confirm_extension_rejected",
                "coverage extension regressed or failed gates; kept prior program", v)

    status = (row or {}).get("status", "")
    stop = (trail_obj or {}).get("stop_reason")
    if status.startswith("skipped_"):
        add("stage0", FATAL, status,
            row.get("error", "document not processable (see clusters.json status)"))
    elif status == "needs_manual_template":
        add("loop", FATAL, "no_version_passed_gates", f"stop={stop}")
    elif status == "export_failed":
        add("export", FATAL, "export_failed", row.get("error", ""))
    elif status == "error":
        add("driver", FATAL, "unhandled_exception", row.get("error", ""))
    elif status == "ok_unaudited":
        add("audit", QUALITY, "never_page_verified",
            "audit errored; parser passed gates but was never checked against pages")
    elif status == "ok_audit_issues":
        add("loop", QUALITY, "stopped_with_open_issues",
            f"stop={stop}, open audit issues={row.get('audit_issues')}")
    return events


def mapping_events(doc: str, results: list) -> list[dict]:
    """Aggregate unmapped/abstained OID-mapping outcomes into per-reason events
    (one row per reason with a count - thousands of per-pair rows would drown
    the report). `results` are oid_mapping.MapResult objects."""
    counts = Counter((r.reason or "unspecified")
                     for r in results if r.status != "mapped")
    return [{"doc": doc, "stage": "mapping", "version": None,
             "severity": QUALITY, "code": f"mapping_{reason}",
             "detail": f"{n} pair(s) not mapped"}
            for reason, n in sorted(counts.items())]


def collect_run_events(out_dir: str, tag: str, summary: list[dict]) -> list[dict]:
    """Events for every document in a run summary (trails loaded from disk)."""
    events: list[dict] = []
    for row in summary:
        doc = row.get("doc", "")
        trail_obj = {}
        trail_path = os.path.join(out_dir, doc, f"codegen_trail_{tag}.json")
        if doc and os.path.isfile(trail_path):
            try:
                with open(trail_path, encoding="utf-8") as f:
                    trail_obj = json.load(f)
            except ValueError:
                events.append({"doc": doc, "stage": "driver", "version": None,
                               "severity": BLOCKING, "code": "corrupt_trail",
                               "detail": f"unparseable {os.path.basename(trail_path)}"})
        events.extend(events_for_doc(doc, trail_obj, row))
    return events


def write_reports(out_dir: str, tag: str, summary: list[dict],
                  events: list[dict], prefix: str = "") -> tuple[str, str]:
    """Write the event CSV + aggregate JSON at the run root; returns both paths."""
    csv_path = os.path.join(out_dir, f"{prefix}error_events_{tag}.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doc", "stage", "version",
                                          "severity", "code", "detail"])
        w.writeheader()
        w.writerows(events)

    agg = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "documents": len(summary),
        "events": len(events),
        "by_severity": dict(Counter(e["severity"] for e in events)),
        "by_stage": dict(Counter(e["stage"] for e in events)),
        "by_code": dict(Counter(e["code"] for e in events)),
        "by_doc": dict(Counter(e["doc"] for e in events)),
    }
    json_path = os.path.join(out_dir, f"{prefix}error_summary_{tag}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(agg, f, indent=1)
    return csv_path, json_path
