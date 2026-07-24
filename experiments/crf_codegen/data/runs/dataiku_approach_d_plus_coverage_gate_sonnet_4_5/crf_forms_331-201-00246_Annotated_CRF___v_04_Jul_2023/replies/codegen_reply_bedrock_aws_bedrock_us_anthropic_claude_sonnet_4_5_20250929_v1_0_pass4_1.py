STRATEGY:

The document is a clinical CRF with multiple form sections, each spanning many pages. Form titles appear as large (16.5pt), colored (#004c99) text near the top of pages, such as "Visit Date", "Triplicate Orthostatic BP and HR - Central", "Follow-Up Phone Call". I will carry forward the most recent form title across subsequent pages until a new title is encountered, since forms span multiple continuation pages. Field labels are regular black text (9-10.5pt) positioned at the left margin or indented, often followed by technical annotations in red or gray that I will ignore. I distinguish fields from answer options by position: options appear inline to the right of a question (e.g., "Yes/No" at x>450) or as bulleted lists under a parent question, while field labels are left-aligned prompts. Table headers (e.g., "Record", "Term", "Start Date") in family E are column labels for repeatable data rows and are fields themselves. Red text in square brackets (e.g., [TYPE:], [VISIBILITY:]) are technical codes, not field names. I will skip pages that are purely version-history tables (family C) or copyright notices (family F) by detecting their structural patterns (table headers "Version/Date/Changed By" or copyright symbols), but I will not skip pages based on single cues—any page with potential field text will be processed. Multi-line labels (wrapping across y-coordinates with similar x-positions) will be joined into one field_name. Bullet points and checkboxes (e.g., "• Vasectomy") under a parent question are answer options, not separate fields.

```python
# CRF extraction: form titles in large colored text, fields as left-aligned labels,
# carry forward titles across pages, skip version tables and copyright pages structurally.

import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip version history pages (family C): detect table with Version/Date/Changed By headers
        if any(l.text.strip() == "Change History" and l.size > 15 for l in lines):
            continue
        header_texts = [l.text.strip() for l in lines[:10]]
        if "Version" in header_texts and "Date" in header_texts and "Changed By" in header_texts:
            continue
        
        # Skip copyright/footer pages (family F): detect copyright symbol or specific text
        page_text = " ".join(l.text for l in lines)
        if "© 2008 The Research Foundation for Mental Hygiene" in page_text:
            continue
        
        # Detect form title: large (>=15pt), colored (#004c99 or similar blue), near top
        for line in lines:
            if line.size >= 15 and line.non_black and line.y0 < 300:
                # Check if it's a blue title (not red annotations)
                text = line.text.strip()
                if text and not text.startswith("[") and len(text) > 2:
                    # Likely a form title
                    current_form = text
                    break
        
        # Collect potential field labels: black text, size 9-10.5, left-aligned or indented
        # Exclude: red text (annotations), gray text (placeholders), bullet points, page numbers
        field_candidates = []
        for i, line in enumerate(lines):
            text = line.text.strip()
            if not text or line.non_black:
                continue
            if line.size < 8 or line.size > 12:
                continue
            # Skip page numbers at bottom
            if line.y0 > 790 and "Page" in text and "of" in text:
                continue
            # Skip red annotations in square brackets
            if text.startswith("[") and text.endswith("]"):
                continue
            # Skip bullet points (lines starting with •)
            if text.startswith("•"):
                continue
            # Skip table headers that are just column labels (detect by position and context)
            # Family E has headers like "Record", "Term", "Start Date" - these ARE fields
            # But we need to distinguish from answer options like "Yes", "No", "X"
            # Answer options are typically short, right-aligned (x > 450), or under a question
            if line.x0 > 450 and len(text) <= 10 and text in ["Yes", "No", "N/A", "X", "Scan"]:
                continue
            # Skip very short standalone text that looks like codes
            if len(text) <= 3 and not line.bold:
                continue
            
            # Check if this is a continuation of previous line (multi-line label)
            if field_candidates and abs(line.x0 - field_candidates[-1]["x0"]) < 20 and line.y0 - field_candidates[-1]["y1"] < 20:
                # Continuation line
                field_candidates[-1]["text"] += " " + text
                field_candidates[-1]["y1"] = line.y1
            else:
                # New field candidate
                field_candidates.append({
                    "text": text,
                    "x0": line.x0,
                    "y0": line.y0,
                    "y1": line.y1,
                    "bold": line.bold
                })
        
        # Filter out non-fields: answer options, table data, furniture
        for cand in field_candidates:
            text = cand["text"]
            # Skip if it's a known non-field pattern
            if re.match(r"^(Row \d+|Record|Sample|ID|Initial contact|Second|Third|Certified)$", text):
                # These are table headers or row labels in family E - actually fields
                pass
            # Skip if it's just a date or number
            if re.match(r"^\d{1,2}[-/]\w{3}[-/]\d{4}$", text) or re.match(r"^\d+\.\d+$", text):
                continue
            # Skip if it's a version number or similar
            if re.match(r"^(Version|Date|Changed By|Details)$", text):
                continue
            # Skip if it's part of instructions (heuristic: very long text)
            if len(text) > 200:
                continue
            
            # Valid field
            records.append({
                "form_name": current_form,
                "field_name": text,
                "page": page_num
            })
    
    # Deduplicate exact duplicates (same form, field, page)
    seen = set()
    unique_records = []
    for rec in records:
        key = (rec["form_name"], rec["field_name"], rec["page"])
        if key not in seen:
            seen.add(key)
            unique_records.append(rec)
    
    return unique_records
```