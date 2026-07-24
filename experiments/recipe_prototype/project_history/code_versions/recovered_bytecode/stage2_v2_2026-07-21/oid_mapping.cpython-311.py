# Source Generated with Decompyle++
# File: D:\ubuntu\codes\ZS\otsuka\ECS\experiments\recipe_prototype\project_history\code_versions\recovered_bytecode\stage2_v2_2026-07-21\oid_mapping.cpython-311.pyc (Python 3.11)

'''Name -> OID mapping for non-Rave CRFs: the form-first funnel.

Annotated Rave books carry printed OIDs, so production never had a
name->OID step -- its rule matcher starts from OIDs it reads off the page
(review_table.fuzzy_match_fields). Non-Rave books yield only
(form_name, field_name), so this module reconstructs the missing OIDs
against the ecs_index library and hands them to that same downstream.

The funnel (each layer narrows, the last one judges):

  layer 1  FORM scoping    partial_ratio >= FORM_SCOPE_T (70) -- the exact
                           scorer/threshold production already uses to match
                           form names (review_table.get_standard_crf).
                           No form match -> unmapped.
  layer 2  FIELD in form   token_sort_ratio >= FIELD_T (85) against the
                           scoped rows only, best row per distinct OID ->
                           a shortlist of 1..MAX_CANDIDATES OIDs.
  layer 3  LLM ranker      EVERY shortlisted case is judged: pick one of the
                           listed OIDs or null. Single candidates are
                           confirm-or-null, not auto-accepted -- measured on
                           the Rave book, both lexical-layer errors were
                           lone candidates that passed the gate while the
                           right row was absent from the library ("Contact
                           Method" at similarity 100 from the WRONG
                           follow-up form). String scores generate
                           candidates; they never certify them.

Without an LLM (llm=None) the module runs deterministic-only: a single
candidate or a clear leader (>= MARGIN points) maps lexically, near-ties
abstain. That mode exists for offline smoke runs and A/B comparison.

Everything unresolved exits as unmapped, which is safe by design:
production writes LLM-generated rules for unmapped fields from their names
alone. The harmful failure is a *mismap* (silently attaches the wrong
form\'s library rules); every layer here is shaped to minimize that -- the
shortlist bound means the ranker can never introduce an OID, though it can
still echo a listed-but-wrong one, so mismap risk is reduced, not zero.

Inputs are pre-normalized strings (caller owns normalization); library
entries are dicts with keys: field, form (normalized), oid, and optionally
field_raw / form_raw for human-readable ranker prompts.
'''
import json
import re
from dataclasses import dataclass, field as dc_field
from rapidfuzz import fuzz
FORM_SCOPE_T = 70
FIELD_T = 85
MARGIN = 5
MAX_CANDIDATES = 5
RANKER_CHUNK = 40
MAPPED = 'mapped'
ABSTAIN = 'abstain'
UNMAPPED = 'unmapped'
MapResult = <NODE:12>()

def scope_form(form = None, lib = None):
    '''Layer 1: only library rows whose form name matches the extracted one.

    Set semantics deliberately mirror production: get_standard_crf calls
    process.extract(..., score_cutoff=70, limit=len(all_form_names)) -- ALL
    forms above the cutoff, not the single best one. Related forms
    ("Adverse Events" / "Adverse Events - Serious") therefore co-exist in
    one scope; the ranker sees each candidate\'s library form and judges.'''
    pass
# WARNING: Decompyle incomplete


def map_field(form = None, field = None, lib = None):
    """Layers 1-2, deterministic decision. Candidates are always attached so
    an LLM ranker can re-judge even lexically 'clear' picks (see map_pairs)."""
    if not form.strip() or field.strip():
        return MapResult(form, field, UNMAPPED)
    scoped = None(form, lib)
    if not scoped:
        return MapResult(form, field, UNMAPPED)
    per_oid = None
    for e in scoped:
        s = fuzz.token_sort_ratio(field, e['field'])
        if s < FIELD_T:
            continue
        key = e['oid'].upper()
        if key not in per_oid or s > per_oid[key][0]:
            per_oid[key] = (s, e)
        if not per_oid:
            return MapResult(form, field, UNMAPPED)
        ranked = (lambda .0: pass# WARNING: Decompyle incomplete
)(per_oid.values()(), key = (lambda t: t[0]), reverse = True)
        (best_s, best_e) = ranked[0]
        shortlist = ranked[:MAX_CANDIDATES]()
        if len(ranked) == 1 or best_s - ranked[1][0] >= MARGIN:
            return MapResult(form, field, MAPPED, oid = best_e['oid'], score = best_s, candidates = shortlist)
        return (lambda .0: [ (s, e['oid'], e.get('field_raw', e['field']), e.get('form_raw', e['form'])) for s, e in .0 ])(form, field, ABSTAIN, candidates = shortlist)


def build_ranker_prompt(cases = None):
    lines = [
        'You are resolving printed CRF field names to library OIDs.',
        'For each case, one or more library entries matched the printed',
        'field name by string similarity. String similarity generates these',
        'candidates but cannot certify them: a perfect label match can sit',
        'on the wrong form, and near-identical labels can be a canonical',
        'field vs its derived variant. Judge by MEANING in form context.',
        '',
        'Rules:',
        '- Reply with ONLY a JSON array: [{"case": 1, "oid": "..."}, ...]',
        '- "oid" must be exactly one of that case\'s listed OIDs, or null.',
        '- Candidates may come from DIFFERENT library forms (form matching',
        '  is fuzzy), and the printed form may not exist in the library at',
        "  all. If no candidate's library form is genuinely the printed",
        '  form, answer null -- however perfect the field label match is.',
        '- A single candidate is a question, not an answer: confirm the',
        "  library entry's field AND form genuinely mean the printed ones,",
        '  else null.',
        '- Prefer the OID representing direct entry of the printed field',
        '  over derived/computed variants, unless the label says otherwise.',
        '- When unsure, answer null. A wrong OID is worse than none: it',
        "  attaches the wrong form's validation rules.",
        '']
    for i, c in enumerate(cases, 1):
        lines.append(f'''Case {i}:''')
        lines.append(f'''  form (as printed):  {c.form}''')
        lines.append(f'''  field (as printed): {c.field}''')
        lines.append('  candidates:')
        for s, oid, label, lib_form in c.candidates:
            lines.append(f'''    - {oid}  (library label: "{label}", library form: "{lib_form}", similarity {s:.0f})''')
            return '\n'.join(lines)


def _extract_json_array(reply = None):
    """First JSON array in the reply, tolerant of prose/markdown around it.

    A greedy first-'['-to-last-']' regex would break as soon as the prose
    contains any bracket, silently unmapping a whole chunk -- so parse the
    whole reply first, then raw_decode from each '[' until a list parses."""
    
    try:
        whole = json.loads(reply)
        if isinstance(whole, list):
            return whole
    except ValueError:
        pass

    dec = json.JSONDecoder()
    for m in re.finditer('\\[', reply):
        (val, _) = dec.raw_decode(reply, m.start())
    except ValueError:
        continue
    if isinstance(val, list):
        
        return None, val


def parse_ranker_reply(reply = None, cases = None):
    """case index (1-based) -> chosen OID (canonical library casing) or None.

    Anything malformed, out-of-range, or not on the case's shortlist is
    treated as None -- the ranker can never introduce an OID."""
    arr = _extract_json_array(reply)
    out = { }
    for item in arr if isinstance(arr, list) else []:
        if not isinstance(item, dict):
            continue
        idx = int(item.get('case'))
    except (TypeError, ValueError):
        continue
    if not  <= 1, idx or 1, idx <= len(cases):
        pass
    
    continue
# WARNING: Decompyle incomplete


def rank_cases(cases = None, llm = None):
    '''Judge every candidate-bearing MapResult with the ranker.

    llm: callable prompt -> reply text (CLI locally, LLM Mesh in Dataiku).
    A case the ranker declines (or answers invalidly) becomes unmapped --
    including cases the lexical layer had marked mapped.

    All chunks are judged BEFORE any result is mutated: if the llm raises
    mid-batch, no case has changed state and the exception propagates, so a
    caller can never ship a half-ranked mixture of ranker and lexical
    verdicts (the caller decides whether to retry or fail the document).'''
    pass
# WARNING: Decompyle incomplete


def map_pairs(pairs = None, lib = None, llm = None):
    '''Run the full funnel over (form, field) pairs.

    With an llm, EVERY pair that produced candidates is judged by the
    ranker (confirm-or-null for single candidates, pick-or-null for ties).
    Without one, lexical decisions stand and near-ties stay ABSTAIN.'''
    pass
# WARNING: Decompyle incomplete

