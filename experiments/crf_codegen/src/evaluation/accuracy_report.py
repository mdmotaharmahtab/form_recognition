"""HTML accuracy report for the Dataiku pipeline runs.

Consumed by `accuracy_audit.py report`. Renders a standalone HTML file that
explains, for the two Dataiku runs (Claude Sonnet 4.5 and GPT 5.2), how
accurate the extraction is against a hand-checked page sample, and where each
model's mistakes and gaps are. The local CLI Sonnet run is included as a
reference baseline.
"""
from __future__ import annotations

import html
import re


# --------------------------------------------------------------- helpers

def esc(s) -> str:
    return html.escape(str(s), quote=True)


def pct(x, digits: int = 0) -> str:
    if x is None:
        return "&ndash;"
    return f"{100 * x:.{digits}f}%"


def bar(x, color: str = "#0f766e") -> str:
    if x is None:
        return "<span class='muted'>n/a</span>"
    w = max(2, round(100 * x))
    return (f"<div class='bar'><div class='bar-fill' style='width:{w}%;"
            f"background:{color}'></div><span>{pct(x)}</span></div>")


OPTION_RE = re.compile(
    r"^(o\s|\(|\d+\s*=|yes\b|no\b|normal\b|abnormal\b|not evaluable\b|"
    r"male\b|female\b|positive\b|negative\b|mild\b|moderate\b|severe\b)",
    re.I)
FOOTER_RE = re.compile(r"^\d{2}\.\d{3}\s|^page \d+|^units$|^\d+ of \d+$", re.I)


def classify_fp(s: str) -> str:
    t = s.strip()
    if FOOTER_RE.search(t):
        return "page furniture"
    if OPTION_RE.search(t) or t.endswith(")]"):
        return "answer option / enumeration"
    if (t and t[0].islower()) or t.endswith((",", ";", "/", "-")) or (
            len(t.split()) >= 4 and not t[-1] in ".?):" and t == t.lower()):
        return "text fragment"
    if len(t) > 120:
        return "instruction / guidance text"
    return "over-extraction"


def corpus_totals(per_doc: dict) -> dict:
    tot = {"truth": 0, "tp": 0, "fp": 0, "miss": 0, "docf": 0,
           "form_pages": 0, "form_ok": 0}
    for d in per_doc.values():
        s = d["score"]
        tot["truth"] += s["truth_fields"]
        tot["tp"] += s["tp"]
        tot["fp"] += s["fp"]
        tot["miss"] += s["missed"]
        tot["docf"] += s["doc_found"]
        tot["form_pages"] += s["form_pages"]
        tot["form_ok"] += s["form_ok_pages"]
    tot["precision"] = tot["tp"] / (tot["tp"] + tot["fp"]) if tot["tp"] + tot["fp"] else None
    tot["recall"] = tot["tp"] / tot["truth"] if tot["truth"] else None
    tot["recall_doc"] = (tot["tp"] + tot["docf"]) / tot["truth"] if tot["truth"] else None
    tot["form_acc"] = tot["form_ok"] / tot["form_pages"] if tot["form_pages"] else None
    return tot


def short_doc(dk: str) -> str:
    return (dk.replace("_Annotated_Unique_CRF_", " unique CRF ")
              .replace("_Annotated_CRF___", " CRF ")
              .replace("_AnnotatedCRFs_", " CRFs ")
              .replace("_", " "))


# --------------------------------------------------------------- sections

CSS = """
:root { --ink:#1c2733; --mut:#5b6b7b; --line:#dbe3ea; --card:#ffffff;
        --bg:#f4f7fa; --navy:#1f4e79; --teal:#0f766e; --red:#b3372f;
        --amber:#9a6700; --green:#1a7f37; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.55 "Segoe UI",system-ui,-apple-system,sans-serif; }
.wrap { max-width:1180px; margin:0 auto; padding:28px 32px 80px; }
h1 { font-size:26px; margin:6px 0 4px; }
h2 { font-size:20px; margin:42px 0 6px; color:var(--navy);
     border-bottom:2px solid var(--line); padding-bottom:6px; }
h3 { font-size:16px; margin:22px 0 6px; }
p  { max-width:960px; }
.sub { color:var(--mut); margin:0 0 18px; }
.muted { color:var(--mut); }
.small { font-size:13px; }
code, .mono { font-family:Consolas,Menlo,monospace; font-size:13px; }
code { background:#eef2f6; padding:1px 5px; border-radius:4px; }
.cards { display:flex; gap:14px; flex-wrap:wrap; margin:18px 0; }
.card { flex:1 1 300px; background:var(--card); border:1px solid var(--line);
        border-radius:10px; padding:16px 18px; }
.card h3 { margin:0 0 2px; font-size:15px; }
.card .who { color:var(--mut); font-size:13px; margin-bottom:10px; }
.kpis { display:flex; gap:18px; flex-wrap:wrap; }
.kpi  { min-width:86px; }
.kpi b { display:block; font-size:24px; font-weight:650; }
.kpi span { font-size:12px; color:var(--mut); }
.verdict { margin-top:10px; font-size:13.5px; border-top:1px dashed var(--line);
           padding-top:8px; }
table { border-collapse:collapse; width:100%; background:var(--card);
        border:1px solid var(--line); border-radius:8px; overflow:hidden;
        font-size:13.5px; }
th { background:var(--navy); color:#fff; text-align:left; padding:7px 10px;
     font-weight:600; }
td { padding:6px 10px; border-top:1px solid var(--line); vertical-align:top; }
tr:nth-child(even) td { background:#fafcfe; }
.bar { position:relative; background:#e8edf2; border-radius:4px; height:18px;
       min-width:110px; }
.bar-fill { height:100%; border-radius:4px; }
.bar span { position:absolute; inset:0; font-size:11.5px; line-height:18px;
            padding-left:6px; color:#132; font-weight:600; }
.tag { display:inline-block; font-size:11px; font-weight:600; padding:1px 8px;
       border-radius:10px; margin-right:6px; white-space:nowrap; }
.tag.red { background:#fdecea; color:var(--red); }
.tag.amber { background:#fff4d6; color:var(--amber); }
.tag.green { background:#e6f4ea; color:var(--green); }
.tag.gray { background:#eef2f6; color:var(--mut); }
.ex { background:#fbfcfd; border:1px solid var(--line); border-left:4px solid var(--navy);
      border-radius:6px; padding:10px 14px; margin:10px 0; font-size:13.5px; }
.ex .loc { color:var(--mut); font-size:12px; margin-bottom:4px; }
.ex ul { margin:4px 0 2px 18px; padding:0; }
.ex li { margin:1px 0; }
.fp   { color:var(--red); }
.miss { color:var(--amber); }
.ok   { color:var(--green); }
details { margin:8px 0; }
summary { cursor:pointer; font-weight:600; color:var(--navy); }
.gapcard { background:var(--card); border:1px solid var(--line);
           border-left:5px solid var(--red); border-radius:8px;
           padding:14px 18px; margin:14px 0; }
.gapcard.amber { border-left-color:var(--amber); }
.gapcard.green { border-left-color:var(--green); }
.gapcard h4 { margin:0 0 6px; font-size:15px; }
.note { background:#eef6ff; border:1px solid #cfe3f7; border-radius:8px;
        padding:12px 16px; font-size:13.5px; margin:14px 0; }
.footer { margin-top:60px; color:var(--mut); font-size:12.5px; }
"""


def kpi_card(label: str, who: str, tot: dict, verdict: str, accent: str) -> str:
    return f"""
<div class="card" style="border-top:4px solid {accent}">
  <h3>{esc(label)}</h3>
  <div class="who">{esc(who)}</div>
  <div class="kpis">
    <div class="kpi"><b>{pct(tot['precision'])}</b><span>precision</span></div>
    <div class="kpi"><b>{pct(tot['recall'])}</b><span>recall (page)</span></div>
    <div class="kpi"><b>{pct(tot['recall_doc'])}</b><span>recall (doc)</span></div>
    <div class="kpi"><b>{pct(tot['form_acc'])}</b><span>form names</span></div>
  </div>
  <div class="verdict">{verdict}</div>
</div>"""


def per_doc_table(detail: dict, order: list[str]) -> str:
    docs = sorted(next(iter(detail.values()))["per_doc"].keys())
    head = "".join(
        f"<th colspan='2'>{esc(detail[r]['run']['label'])}</th>" for r in order)
    sub = "".join("<th class='small'>recall</th><th class='small'>precision</th>"
                  for _ in order)
    rows = []
    for dk in docs:
        tds = [f"<td class='mono small'>{esc(short_doc(dk))}"
               f"<br><span class='muted'>{next(iter(detail.values()))['per_doc'][dk]['score']['truth_fields']}"
               f" truth fields on 10 sampled pages</span></td>"]
        for rn in order:
            s = detail[rn]["per_doc"][dk]["score"]
            st = detail[rn]["per_doc"][dk]["status"]
            color = "#0f766e" if rn != "gpt52-dataiku" else "#7c5cb0"
            if s["truth_fields"] and s["tp"] == 0 and s["fp"] == 0:
                tds.append(f"<td colspan='2'><span class='tag red'>no usable output"
                           f"</span> <span class='muted small'>{esc(st)}</span></td>")
            else:
                tds.append(f"<td>{bar(s['recall_page'], color)}</td>"
                           f"<td>{bar(s['precision'], '#5b8bb8')}</td>")
        rows.append(f"<tr>{''.join(tds)}</tr>")
    return (f"<table><tr><th rowspan='2'>document</th>{head}</tr>"
            f"<tr>{sub}</tr>{''.join(rows)}</table>")


def example_block(title: str, items: list[tuple[str, str]], cls: str) -> str:
    lis = "".join(f"<li class='{cls}'>{esc(a)}"
                  + (f" <span class='muted'>&larr; {esc(b)}</span>" if b else "")
                  + "</li>"
                  for a, b in items)
    return f"<div class='loc'>{esc(title)}</div><ul>{lis}</ul>"


def appendix_for_run(per_doc: dict) -> str:
    out = []
    for dk in sorted(per_doc):
        s = per_doc[dk]["score"]
        page_rows = []
        for p in s["pages"]:
            if not p["fp_list"] and not p["missed"] and p["form_correct"] is not False:
                continue
            cells = []
            if p["missed"]:
                cells.append("<b class='miss'>missed:</b> "
                             + "; ".join(esc(m) for m in p["missed"]))
            if p["fp_list"]:
                cells.append("<b class='fp'>false positives:</b> "
                             + "; ".join(esc(f) for f in p["fp_list"]))
            if p["form_correct"] is False:
                cells.append(f"<b class='fp'>form name wrong:</b> got "
                             f"&ldquo;{esc(p['modal_form'] or '(empty)')}&rdquo;, expected "
                             f"&ldquo;{esc(p['truth_form'])}&rdquo;")
            page_rows.append(f"<tr><td class='mono'>p{p['page']}</td>"
                             f"<td>{'<br>'.join(cells)}</td></tr>")
        if not page_rows:
            continue
        out.append(f"<details><summary>{esc(short_doc(dk))} "
                   f"<span class='muted small'>({s['missed']} missed, {s['fp']} false "
                   f"positives on the sample)</span></summary>"
                   f"<table><tr><th style='width:60px'>page</th><th>detail</th></tr>"
                   f"{''.join(page_rows)}</table></details>")
    return "".join(out)


# --------------------------------------------------------------- narrative

def sonnet_gap_cards(per_doc: dict) -> str:
    cards = []

    d = per_doc.get("384-201-00004_Annotated_CRF___v1.0_05_Mar_2025")
    if d and d["score"]["tp"] == 0:
        cards.append(f"""
<div class="gapcard">
 <h4>1. One document produced no output at all (the run's biggest gap)</h4>
 <p><b>384-201-00004 CRF v1.0 (05&nbsp;Mar&nbsp;2025)</b> &mdash; all five generated
 code versions extracted <b>zero records</b>, so every sampled field on this
 document is missed (0% recall, 20 truth fields). The pipeline correctly refused
 to ship it: the run is flagged <code>needs_manual_review</code> and the trail
 shows <code>stop_reason=budget</code> with &ldquo;The program extracted ZERO
 records&rdquo; on every cycle. The same document works in the other two runs
 (CLI Sonnet 95% recall, GPT&nbsp;5.2 70%), so this is a per-run induction
 failure &mdash; a rerun with a fresh seed prompt would very likely fix it.</p>
</div>""")

    cards.append("""
<div class="gapcard amber">
 <h4>2. Answer options and rating-scale anchors leak in as &ldquo;fields&rdquo;</h4>
 <p>The most common precision mistake: rows that are <i>answer choices</i>, not
 questions. Worst case in the sample is the Rave C-SSRS page, where the rating
 anchors of three real fields were emitted as 19 extra fields:</p>
 <div class="ex">
  <div class="loc">384-201-00002 unique CRF, page 341 &mdash; truth fields are only
  &ldquo;Controllability&rdquo;, &ldquo;Deterrents&rdquo;, &ldquo;Reasons for Ideation&rdquo;</div>
  <ul>
   <li class="fp">&ldquo;1 = Easily able to control&rdquo;, &ldquo;2 = Can control thoughts&rdquo; &hellip; (scale anchors)</li>
   <li class="fp">&ldquo;attention, revenge or a&rdquo;, &ldquo;how you were feeling)&rdquo; (anchor text split across lines)</li>
  </ul>
 </div>
 <p>The same pattern shows up on the Viedoc-style 2021 book, where lab analyte
 enumerations (&ldquo;Platelet count&rdquo;, &ldquo;Sodium&rdquo;, &ldquo;Urobilinogen&rdquo;&hellip;) and even
 fragments of the OID annotation dump (&ldquo;&hellip;Microscopic analysis if indicated)]&rdquo;)
 were emitted as fields &mdash; precision on that document drops to 45%.</p>
</div>""")

    cards.append("""
<div class="gapcard amber">
 <h4>3. Line-wrap fragments become fields</h4>
 <p>When a prompt wraps across lines, the generated parser sometimes emits each
 line as its own field:</p>
 <div class="ex">
  <div class="loc">annotatedCRF 2021, page 484 (C-SSRS)</div>
  <ul>
   <li class="fp">&ldquo;fall asleep and not wake up.&rdquo;</li>
   <li class="fp">&ldquo;up?&rdquo;</li>
   <li class="ok">truth: &ldquo;Have you wished you were dead or wished you could go to sleep and not wake up?&rdquo; (missed as one field)</li>
  </ul>
 </div>
</div>""")

    cards.append("""
<div class="gapcard amber">
 <h4>4. Split-line labels are missed</h4>
 <p>Labels whose text is broken across lines in the PDF text layer (the number
 lives on its own line) are skipped, e.g. the lab-review rows
 &ldquo;Hematology clinically significant abnormal assay # 3&rdquo; /
 &ldquo;&hellip;# 4&rdquo; on the 2021 book, and &ldquo;Planned Timepoint&rdquo; on vitals grids.
 These account for most of the missed fields outside the failed document.</p>
</div>""")

    cards.append("""
<div class="gapcard green">
 <h4>What works well</h4>
 <p>Form names are essentially solved where a title is printed on the page
 (47/48 sampled printed-title pages correct, including carried-forward titles).
 QSC schedule books and the ClinSpark/DrVince books score 77&ndash;100% recall with
 good precision, matching the local CLI run. Doc-level recall of 86% shows most
 &ldquo;missed&rdquo; fields on a page are found elsewhere in the export rather than
 being absent.</p>
</div>""")
    return "".join(cards)


def gpt_gap_cards(per_doc: dict) -> str:
    cards = []
    mac = per_doc.get("MAC186_X11-201-00001_eCRF_v1.10_form_tracker_v1.6_06Mar2025")
    mac_rec = pct(mac["score"]["recall_page"]) if mac else "?"
    v2021 = per_doc.get("annotatedCRF_33120100246-_v1.0_-17Aug2021")
    v2021_rec = pct(v2021["score"]["recall_page"]) if v2021 else "?"

    cards.append(f"""
<div class="gapcard">
 <h4>1. Under-extraction: whole pages come back empty</h4>
 <p>GPT&nbsp;5.2's main gap is coverage. Its parsers stop at a quality plateau
 while large parts of the document are still unparsed, so many sampled pages
 have <i>no rows at all</i>:</p>
 <ul>
  <li><b>MAC186 form tracker: {mac_rec} page recall.</b> The generated code reads
  the &ldquo;Variable details&rdquo; dictionary pages but skips most form layout pages
  &mdash; MADRS, Physical Examination, Pupillometry, C-SSRS and PD-sample pages
  returned zero rows (938 rows exported vs 6,165 by CLI Sonnet on the same
  document).</li>
  <li><b>annotatedCRF 2021 (596 pages): {v2021_rec} page recall.</b> Only 816 rows
  exported; lab-review, orthostatic-vitals and C-SSRS pages in the sample are
  empty.</li>
 </ul>
 <p>Document-level recall is high (94% across the corpus): the field <i>names</i>
 usually exist somewhere in the export (often from a twin page), but they are
 attributed to the wrong pages &mdash; a real problem if page provenance matters
 downstream.</p>
</div>""")

    cards.append("""
<div class="gapcard amber">
 <h4>2. Page furniture exported as fields on the Rave book</h4>
 <p>On <b>384-201-00002 unique CRF</b> the parser emits the footer artifact
 &ldquo;01.025 GMK (432)&rdquo; and the column header &ldquo;Units&rdquo; as fields on
 essentially every page &mdash; including 6 annotation-dictionary pages that
 contain no real fields at all (the false-positive pages in the scorecard).
 Recall on this document is still 100%, but precision drops to 66%.</p>
</div>""")

    cards.append("""
<div class="gapcard amber">
 <h4>3. Instructions and questionnaire guidance extracted as fields</h4>
 <p>On the QSC schedule books and ClinSpark C-SSRS pages, option rows and
 interviewer guidance paragraphs come back as fields, e.g. a 500-character
 C-SSRS definition paragraph (&ldquo;A potentially self-injurious act committed
 with at least some wish to die&hellip;&rdquo;) on 384-201-00004 CRF v2.0 page 44.
 These inflate the false-positive count on otherwise well-parsed pages.</p>
</div>""")

    cards.append("""
<div class="gapcard amber">
 <h4>4. Form names carry an invented study prefix</h4>
 <p>GPT&nbsp;5.2 prefixes form names with the study ID (&ldquo;S_QSC302573, 03 -
 Screening Final v1.0&rdquo; instead of the printed &ldquo;QSC302573, 03 - Screening
 Final v1.0&rdquo;). The scorer accepts this as a match, and it is cosmetic, but
 downstream joins on form name would need the same tolerance.</p>
</div>""")

    cards.append("""
<div class="gapcard green">
 <h4>What works well</h4>
 <p>Where GPT&nbsp;5.2 does parse a page, output is clean: corpus precision is 74%
 and several documents (ClinSpark aCRF 16JAN2025, Viedoc 26&nbsp;Jul&nbsp;2023) score
 95&ndash;100% precision. Form-name accuracy is perfect on the sample (47/47), and
 on the Rave book it actually achieves the highest full-document recall of the
 three runs (93% of the 915 production ground-truth pairs).</p>
</div>""")
    return "".join(cards)


# --------------------------------------------------------------- build

def build_report(detail: dict, out_path: str) -> None:
    order = ["sonnet-dataiku", "gpt52-dataiku", "sonnet-cli"]
    tots = {rn: corpus_totals(detail[rn]["per_doc"]) for rn in order}

    truth_total = sum(d["score"]["truth_fields"]
                      for d in detail["sonnet-dataiku"]["per_doc"].values())
    verdicts = {
        "sonnet-dataiku": ("Matches the local CLI run on 10 of 11 documents; one "
                           "document failed outright (zero records, flagged "
                           "needs_manual_review) and drags recall down ~8 points."),
        "gpt52-dataiku": ("Cleaner names than its raw numbers suggest, but stops "
                          "too early: whole pages return empty on two documents. "
                          "Finds fields, loses their page."),
        "sonnet-cli": ("Reference baseline (same pipeline, local Anthropic API). "
                       "Best balance of precision and recall."),
    }
    accents = {"sonnet-dataiku": "#0f766e", "gpt52-dataiku": "#7c5cb0",
               "sonnet-cli": "#5b8bb8"}
    labels = {rn: detail[rn]["run"]["label"] for rn in order}

    def rel_root(p: str) -> str:
        p = p.replace("\\", "/")
        i = p.find("experiments/")
        return p[i:] if i >= 0 else p

    roots = {rn: rel_root(detail[rn]["run"]["root"]) for rn in order}

    rave_rows = []
    for rn in order:
        rv = detail[rn]["rave"]
        if not rv:
            continue
        rave_rows.append(
            f"<tr><td>{esc(labels[rn])}</td>"
            f"<td class='mono'>{rv['extracted_pairs']:,}</td>"
            f"<td class='mono'>{rv['matched']:,} / {rv['gt_pairs']:,}</td>"
            f"<td>{bar(rv['recall'], accents[rn])}</td>"
            f"<td>{bar(rv['precision'], '#5b8bb8')}</td></tr>")

    sd = detail["sonnet-dataiku"]
    gd = detail["gpt52-dataiku"]

    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CRF extraction accuracy &mdash; Dataiku runs</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>CRF extraction accuracy &mdash; Dataiku runs</h1>
<p class="sub">Ground-truth audit of the code-generation extraction pipeline on
11 CRF documents (5 vendor formats, 2,847 pages). Two Dataiku runs are compared,
with the local CLI run as a reference baseline.</p>

<h2>1. The headline numbers</h2>
<p>We hand-checked <b>110 sampled pages</b> (10 per document, spread across
layout clusters) by reading the raw PDF text and writing down every real
data-entry field &mdash; <b>{truth_total} truth fields</b> in total. Each run's
export was then matched page by page against that truth (fuzzy matching, so
wording variants still count).</p>

<div class="cards">
{kpi_card(labels['sonnet-dataiku'], 'production model, LLM Mesh', tots['sonnet-dataiku'], verdicts['sonnet-dataiku'], accents['sonnet-dataiku'])}
{kpi_card(labels['gpt52-dataiku'], 'alternative model, LLM Mesh', tots['gpt52-dataiku'], verdicts['gpt52-dataiku'], accents['gpt52-dataiku'])}
{kpi_card(labels['sonnet-cli'], 'reference baseline, local API', tots['sonnet-cli'], verdicts['sonnet-cli'], accents['sonnet-cli'])}
</div>

<div class="note"><b>How to read the four numbers.</b>
<b>Precision</b>: of the fields the model extracted on the sampled pages, how many
are real fields. <b>Recall (page)</b>: of the real fields on those pages, how many
the model extracted <i>on that page</i>. <b>Recall (doc)</b>: same, but a miss is
forgiven if the field appears somewhere else in the document's export &mdash; the
gap between the two recalls measures wrong-page attribution, not lost content.
<b>Form names</b>: pages whose printed form title the run reproduced correctly.
Named answer slots (e.g. &ldquo;Systolic&rdquo; under a vital-signs prompt) are counted
as neither correct nor wrong.</div>

<h2>2. Results per document</h2>
<p>Each document is one vendor format/version. The pattern to notice: Sonnet's
weak spots are isolated (one failed document, one noisy C-SSRS page), while
GPT&nbsp;5.2's recall erodes broadly on the two longest, most repetitive books.</p>
{per_doc_table(detail, order)}
<p class="small muted">10 pages sampled per document, so each per-document cell
carries roughly &plusmn;10&ndash;15&nbsp;percentage points of sampling error. Corpus
totals above are the steadier signal. &ldquo;no usable output&rdquo; = the run produced
zero records for the document.</p>

<h2>3. Cross-check against production ground truth (Rave book)</h2>
<p>For <b>384-201-00002 unique CRF</b> we also have the production digitized
output (915 form+field pairs) as an independent, full-document ground truth
&mdash; no sampling involved:</p>
<table>
<tr><th>run</th><th>extracted pairs</th><th>matched</th><th>recall</th><th>precision</th></tr>
{''.join(rave_rows)}
</table>
<p class="small muted">Precision here is stricter than in the page sample: the
production file lists one row per field while the runs also export answer-slot
rows, so &ldquo;extra&rdquo; rows are penalized even when they are defensible. Use this
table for recall comparisons; use the page sample for precision.</p>

<h2>4. Claude Sonnet 4.5 (Dataiku): where it goes wrong</h2>
{sonnet_gap_cards(sd['per_doc'])}
<h3>Full mistake list (Sonnet 4.5, Dataiku)</h3>
{appendix_for_run(sd['per_doc'])}

<h2>5. GPT 5.2 (Dataiku): where it goes wrong</h2>
{gpt_gap_cards(gd['per_doc'])}
<h3>Full mistake list (GPT 5.2, Dataiku)</h3>
{appendix_for_run(gd['per_doc'])}

<h2>6. What would move the numbers</h2>
<ul>
 <li><b>Retry zero-record documents automatically.</b> The Sonnet run already
 flags them (<code>needs_manual_review</code>); one fresh induction attempt with a
 different seed page sample would likely recover the failed ClinSpark v1.0 book
 (+8 points corpus recall for the Sonnet run).</li>
 <li><b>Don't stop on a plateau while coverage is low.</b> GPT&nbsp;5.2 plateaus
 with large page ranges unparsed (MAC186, 2021 book). Making the stopping rule
 require a minimum pages-covered share before &ldquo;diminishing returns&rdquo; counts
 would directly attack its 62% &rarr; 94% page/doc recall gap.</li>
 <li><b>Filter option anchors and page furniture in the audit gates.</b> Rows
 matching &ldquo;<code>N = &hellip;</code>&rdquo; anchors, footer stamps
 (&ldquo;01.025 GMK&rdquo;), and bare column headers (&ldquo;Units&rdquo;) are the two runs'
 dominant false-positive patterns and are cheap to detect deterministically.</li>
 <li><b>Stitch wrapped labels before parsing.</b> Line-fragment fields
 (&ldquo;up?&rdquo;) and missed split-line labels (&ldquo;&hellip; abnormal assay # 3&rdquo;) share one
 root cause: parsing line-by-line instead of joining wrapped text blocks.</li>
</ul>

<h2>7. Method, in one minute</h2>
<p><b>Sample.</b> 10 pages per document, stratified over Stage-0 layout clusters
with a fixed seed &mdash; 110 pages, {truth_total} truth fields. <b>Truth.</b> A human-readable
data-entry prompt is a field; options, section headers, instructions, OID
annotations and code lists are not. Defensible extras (named answer slots such
as &ldquo;Systolic&rdquo;) are recorded and excluded from both hit and false-positive
counts. <b>Matching.</b> Names are normalized (case, punctuation) and matched
fuzzily (token-sort &ge; 80 or partial &ge; 90), one-to-one per page. Form names
are scored only on pages that print their title. <b>Artifacts.</b> Per-run Excel
scorecards (summary, page detail, record verdicts, method) sit in each run's
output folder; truth JSONs and the scorer live in
<code>experiments/recipe_prototype/accuracy_audit/</code> and
<code>experiments/recipe_prototype/scripts/accuracy_audit.py</code>.</p>

<table>
<tr><th>run</th><th>output folder</th><th>Excel scorecard</th></tr>
<tr><td>{esc(labels['sonnet-dataiku'])}</td><td class="mono small">{esc(roots['sonnet-dataiku'])}</td>
    <td class="mono small">accuracy_audit_bedrock_&hellip;_claude_sonnet_4_5_&hellip;.xlsx</td></tr>
<tr><td>{esc(labels['gpt52-dataiku'])}</td><td class="mono small">{esc(roots['gpt52-dataiku'])}</td>
    <td class="mono small">accuracy_audit_azureopenai_azure_openai_nocache_gpt_5_2.xlsx</td></tr>
<tr><td>{esc(labels['sonnet-cli'])}</td><td class="mono small">{esc(roots['sonnet-cli'])}</td>
    <td class="mono small">accuracy_audit_claude_4_5_sonnet.xlsx</td></tr>
</table>

<div class="footer">Generated by <span class="mono">scripts/accuracy_audit.py report</span>
&mdash; ground truth in <span class="mono">accuracy_audit/truth/</span>, scores in
<span class="mono">accuracy_audit/scored.json</span>.</div>
</div></body></html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
