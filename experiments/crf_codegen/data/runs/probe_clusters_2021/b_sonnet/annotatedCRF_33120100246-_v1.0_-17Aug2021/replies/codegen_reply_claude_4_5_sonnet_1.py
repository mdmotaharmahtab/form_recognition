```python
# This CRF document has a multi-page table of contents (pages 1-10), then repeating
# form layouts (families D-U) representing data-entry pages. Most pages print a large
# blue form title near y=66 and field labels scattered below. Technical annotations in
# red ([TYPE: ...], machine codes) and small table headers/furniture are structural
# landmarks but NOT fields. Answer options (Yes/No/etc.) sit to the right of their
# field labels. Extract form_name from the blue title header and field_name from black
# text labels, skipping red annotations, table headers, and answer values.

import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip table-of-contents pages (families A-C, pages 1-10)
        if page_num <= 10:
            continue
        
        # Identify form title: large blue text near y=66, typically 14.4pt
        form_candidates = [ln for ln in lines if ln.y0 < 120 and ln.size >= 14 and ln.non_black]
        if form_candidates:
            current_form = form_candidates[0].text.strip()
        
        # Collect field candidates: black text, size 7-10pt, not in red annotation zone
        candidates = []
        for ln in lines:
            if ln.non_black or ln.size < 7 or ln.size > 10:
                continue
            if is_technical_annotation(ln.text):
                continue
            candidates.append(ln)
        
        # Parse by structural zones
        for ln in candidates:
            txt = ln.text.strip()
            
            # Skip furniture
            if is_furniture(txt, ln):
                continue
            
            # Skip answer options (right-aligned, short enumeration values)
            if is_answer_option(txt, ln, lines):
                continue
            
            # Valid field label
            if txt and current_form:
                records.append({
                    "form_name": current_form,
                    "field_name": txt,
                    "page": page_num
                })
    
    # Deduplicate exact repeats
    seen = set()
    unique = []
    for r in records:
        key = (r["form_name"], r["field_name"], r["page"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    
    return unique


def is_technical_annotation(text):
    """Red technical annotations: [TYPE: ...], [VISIBILITY: ...], machine codes."""
    if text.startswith('[') and text.endswith(']'):
        return True
    if re.match(r'^[A-Z]{2,}[0-9]+[A-Z]*$', text):  # e.g. CSS0401A, LBGLYC
        return True
    return False


def is_furniture(text, line):
    """Page headers, footers, column labels, table structure markers."""
    # Row markers
    if re.match(r'^Row \d+$', text):
        return True
    # Column headers (small caps or title case at top of tables)
    if line.y0 < 250 and text in ['Sample', 'Date of Collection', 'Time of Collection', 
                                   'Barcode Number', 'Scan', 'Result', 'Test', 
                                   'Timepoint', 'Sample Status', 'Criteria', 'Met/Not Met',
                                   'ID', 'Medication', 'Indication', 'Start date', 'Start time',
                                   'Visit', 'Visit Label', 'Page', 'Page Label', 'Dynamic?',
                                   'Description of Dynamic', 'Visit Number', 'Page Number',
                                   'Lifetime', 'Past 3 Month', 'Since Last Visit',
                                   'Intensity of Ideation', 'Suicidal Ideation', 'Most Lethal Attempt',
                                   'Actual Attempts', 'Most severe ideation', 'Frequency', 'Duration',
                                   'Controllability', 'Deterrents', 'Reasons for Ideation']:
        return True
    # Form section labels (repeated structure markers)
    if text in ['Schedule_TITR', 'Schedule_Screening2']:
        return True
    # Instructions/disclaimers (long prose blocks)
    if len(text) > 150 and any(kw in text.lower() for kw in ['disclaimer', 'copyright', 'contact', 'reprints']):
        return True
    # Standalone version/date stamps
    if re.match(r'^Version \d+', text) or re.match(r'^\d{1,2}[A-Z][a-z]{2}\d{4}$', text):
        return True
    return False


def is_answer_option(text, line, all_lines):
    """Answer options: Yes/No/etc. positioned to the right of a field label."""
    # Common answer values
    if text in ['Yes', 'No', 'N/A', 'Not Applicable', 'Met', 'Not Met', 
                'Positive', 'Negative', 'Not Done', 'Collected', 'Not Collected',
                'Scan', 'Skip to next visit', 'Current', 'Former', 'Never',
                'Per Day', 'Per Week', 'Pack', 'Cigar', 'Cartridge', 'None',
                'Urine', 'Serum', 'Dose Missed', 'Wrong dose', 'Other',
                'Predose', '1h Postdose', '2h Postdose', 'Male', 'Female',
                'Aerosol', 'Bar Chewable', 'Bead', 'Capsule', 'Concentrate']:
        return True
    
    # Option list items (enumerated labels in parentheses)
    if re.match(r'^\(\d+\)\s+.+', text):
        return True
    
    # Scale anchors (numeric ratings)
    if re.match(r'^\d+$', text) and len(text) == 1:
        return True
    
    return False
```
