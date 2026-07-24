STRATEGY:

The document is a clinical CRF with multiple layout families. Form/section titles appear in large colored fonts (size ~16.5, color #004c99) at the top of pages, such as "Visit Date" or "Triplicate Orthostatic BP and HR - Central". These titles govern multiple pages, so I will carry forward the most recent title across continuation pages that lack one. Field labels are printed in regular black text (size ~9-10.5) and are followed by technical annotations in red (#ff0000) containing machine codes in square brackets like [VISDAT] or [TYPE: ...]. I will extract the black text labels as field_name and ignore the red annotations. Answer options and table column headers (e.g., "Collected", "Not Collected", "Sample", "Timepoint") appear in specific table layouts and are distinguishable by their position in header rows or as enumeration values within red technical text. I will skip these by recognizing their structural context: column headers sit at consistent y-positions in table bands, and options are embedded in red TYPE/enumeration annotations. Reference tables (like the inclusion/exclusion criteria codes INCL1-EXCL16 on page 168) that list codes without accompanying entry fields are not data-entry fields; I identify these by the absence of question text and presence only of code labels. Multi-line field labels will be joined by detecting continuation lines at similar x-positions. Pages with no recognizable title or fields (e.g., table of contents pages) will yield no records, but I will not skip pages based on heuristics—every page is examined. The form_name is the last seen large colored title; field_name is the black label text preceding red annotations.

```python
# CRF extraction: form titles in large colored fonts (~16.5pt, #004c99),
# field labels in black text (~9-10.5pt), red text is technical annotations to skip.
# Carry forward form titles across pages; join multi-line labels.

import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form/section title: large colored text (size >= 15, non-black)
        for line in lines:
            if line.size >= 15.0 and line.non_black and not line.text.startswith('['):
                # Potential form title
                text = line.text.strip()
                # Skip table of contents entries (they have numbers like "3.1.")
                if not re.match(r'^\d+(\.\d+)*\.?\s', text):
                    current_form = text
                    break
        
        # Extract field labels: black text, size 9-10.5, not in brackets, not page numbers
        field_candidates = []
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty, red text, brackets, page numbers
            if not text or line.non_black or text.startswith('[') or re.match(r'^Page \d+ of \d+$', text):
                continue
            
            # Skip very large text (titles) and very small text
            if line.size < 8.5 or line.size > 11.0:
                continue
            
            # Skip table column headers by position (top area, y < 170)
            if line.y0 < 170 and re.search(r'^(Sample|Timepoint|Sample Status|Time of|Barcode|Backup|Collection|Number)$', text):
                continue
            
            # Skip answer options: single words like "Collected", "Not", "Predose", "Scan"
            if re.match(r'^(Collected|Not|Scan|Predose|Postdose|Yes|No|Unknown)$', text, re.IGNORECASE):
                continue
            
            # Skip inclusion/exclusion codes without question text (INCL1, EXCL1, etc.)
            if re.match(r'^(INCL|EXCL)\d+$', text):
                continue
            
            # Skip row labels like "Row 1", "Row 2"
            if re.match(r'^Row \d+$', text, re.IGNORECASE):
                continue
            
            # Skip definitions and copyright notices
            if 'Columbia' in text or '©' in text or 'reprints' in text.lower():
                continue
            
            # Check if this is a field label (not followed immediately by another label at same x)
            # Look ahead for red annotation or next field
            is_field = False
            next_line_idx = i + 1
            if next_line_idx < len(lines):
                next_line = lines[next_line_idx]
                # If next line is red and close in y, this is likely a field
                if next_line.non_black and abs(next_line.y0 - line.y0) < 30:
                    is_field = True
            else:
                # Last line on page, might be a field
                is_field = True
            
            # Also accept lines that look like questions (contain "?", "Date", "Time", etc.)
            if re.search(r'(Date|Time|Status|Number|Sample|Subject|Visit|\?)', text, re.IGNORECASE):
                is_field = True
            
            if is_field and len(text) > 2:
                field_candidates.append((line.x0, line.y0, text))
        
        # Group multi-line labels by proximity
        grouped_fields = []
        i = 0
        while i < len(field_candidates):
            x, y, text = field_candidates[i]
            combined = text
            j = i + 1
            # Look for continuation lines: similar x (within 20 points), close y (within 20 points)
            while j < len(field_candidates):
                x2, y2, text2 = field_candidates[j]
                if abs(x2 - x) < 20 and abs(y2 - y) < 20:
                    combined += " " + text2
                    y = y2
                    j += 1
                else:
                    break
            grouped_fields.append(combined)
            i = j if j > i + 1 else i + 1
        
        # Emit records
        for field_name in grouped_fields:
            # Final filtering: skip very short or generic text
            if len(field_name) < 3:
                continue
            # Skip pure numbers or dates
            if re.match(r'^\d+(\.\d+)?$', field_name):
                continue
            
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return results
```