STRATEGY:

This document is an annotated CRF with a table-of-contents page, index pages, and many field-bearing pages. Field-bearing pages contain human-readable field labels (questions) in black text around size 9, with technical annotations in red text (machine codes, types, visibility rules) that must be excluded. The form_name is printed as a large colored heading (size 15-16.5, typically in blue #004c99 or #2477cc) near the top of field pages. Many pages are continuations without a reprinted title, so I will carry forward the most recent form_name across pages. I identify data-entry fields by their black text labels at y-positions that are not part of red annotation blocks, table headers, or page furniture. Answer options and table column headers appear in structured positions (e.g., aligned columns with "Sample", "Timepoint", "Sample Status") and are excluded by recognizing their repetitive layout. Red text lines containing brackets, "TYPE:", "VISIBILITY:", "Read-only", or machine codes are technical annotations, not field labels. I will join wrapped label lines by detecting continuation text at similar x-offsets and close y-spacing. Pages are not skipped based on heuristics; every page is examined, and if no clear form title is found, the last-seen title is used. The table-of-contents and index pages (families A, B) list section names but are not field pages themselves; I extract from pages that show actual field labels with entry prompts.

CODE:

```python
# Annotated CRF: form titles in large blue text, fields in black ~9pt, red annotations excluded.
# Carry forward form_name across continuation pages; join wrapped labels; skip TOC/index pages.

import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Detect form/section title: large (15-16.5pt), colored (blue), near top
        for line in lines:
            if line.size >= 15.0 and line.non_black and line.y0 < 300:
                # Exclude TOC-style entries (have leading numbers like "3.1.")
                if not re.match(r'^\d+(\.\d+)*\.?\s', line.text):
                    current_form = line.text.strip()
                    break
        
        # Skip table-of-contents and index pages (families A, B)
        # These have many blue links and "CHANGE HISTORY", "SCHEDULE", "PAGES" headers
        if any(kw in line.text for line in lines for kw in ["CHANGE HISTORY", "SCHEDULE OF ASSESSMENT"]):
            continue
        
        # Collect candidate field lines: black text, size ~8-10pt, not red annotations
        candidates = []
        for line in lines:
            # Skip red text (annotations)
            if line.non_black:
                continue
            # Skip very large text (titles already captured)
            if line.size > 12:
                continue
            # Skip page numbers
            if re.match(r'^Page \d+ of \d+$', line.text.strip()):
                continue
            # Skip lines with red annotation markers (even if black, context check)
            if re.search(r'\[.*\]', line.text):
                continue
            # Skip table headers (specific known patterns)
            if line.text.strip() in ["Sample", "Timepoint", "Sample Status", "Time of", "Barcode", "Backup", "Collection", "Number"]:
                continue
            # Skip row labels like "Row 1", "Row 2"
            if re.match(r'^Row \d+$', line.text.strip()):
                continue
            # Skip definitions/instructions (long prose at top)
            if line.y0 < 200 and len(line.text) > 100:
                continue
            # Skip copyright and attribution lines
            if "©" in line.text or "Columbia" in line.text or "reprints" in line.text.lower():
                continue
            
            # Candidate field label
            if line.size >= 8.5 and line.size <= 10.5 and not line.bold:
                candidates.append(line)
        
        # Group candidates into fields (join wrapped lines)
        fields = []
        i = 0
        while i < len(candidates):
            field_lines = [candidates[i]]
            j = i + 1
            # Join continuation lines: similar x0 (within 20pt), close y (within 20pt)
            while j < len(candidates):
                if abs(candidates[j].x0 - candidates[i].x0) < 20 and candidates[j].y0 - field_lines[-1].y0 < 20:
                    field_lines.append(candidates[j])
                    j += 1
                else:
                    break
            
            field_text = " ".join(ln.text.strip() for ln in field_lines).strip()
            
            # Filter out non-field text
            # Skip if it looks like a value or code
            if re.match(r'^[A-Z0-9]+$', field_text) and len(field_text) < 10:
                i = j
                continue
            # Skip if it's a single word that's likely a subsection label
            if len(field_text.split()) == 1 and field_text in ["Supine", "Standing", "Collected", "Not", "Predose"]:
                i = j
                continue
            # Skip enumeration values in parentheses
            if field_text.startswith("(values:") or "enumeration" in field_text.lower():
                i = j
                continue
            
            # Valid field
            if len(field_text) > 3:
                fields.append(field_text)
            
            i = j
        
        # Emit records
        for field in fields:
            results.append({
                "form_name": current_form,
                "field_name": field,
                "page": page_num
            })
    
    return results
```