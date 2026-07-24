Looking at the sample pages, I can see they contain data-entry fields that my program is missing:

**Cluster 0 (pages 20, 25)**: These are schedule/table-of-contents pages listing visit numbers, page numbers, and page labels. These appear to be navigation/reference pages without actual data-entry fields - they just map page numbers to form names.

**Cluster 1 (pages 395, 681)**: These contain C-SSRS intensity questions with actual data-entry fields. The questions are in bold black text (e.g., "Could/can you stop thinking about killing yourself or wanting to die if you want to?", "Are there things - anyone or anything - that stopped you from wanting to die or acting on thoughts of committing suicide?"). The form name "Intensity of Ideation" and "Since Last Visit" appear at the top.

**Cluster 2 (pages 614, 893)**: These appear to be continuation pages with just headers and red machine codes - likely the tail end of forms with no additional fields.

The main issue is **Cluster 1** - my program is not detecting the form name correctly (it's looking for large blue #004c99 text, but here the form name is in regular black 10.5pt text). I need to add handling for this layout pattern.

```python
# This CRF document contains multiple layout families:
# - Family A: Title page with table of contents
# - Family B: Continuation of table of contents
# - Family C: Schedule tables with visit/page mappings
# - Family D: C-SSRS title/disclaimer page
# - Family E: C-SSRS intensity tables with Lifetime/Past 3 Month columns
# - Family F: Various simple header-only pages
# - Family G: C-SSRS "Intensity of Ideation" pages with "Since Last Visit" header
# The main data-entry fields appear on pages with form titles in large blue font (~16.5pt #004c99)
# followed by field labels in black text. We extract form_name from the blue headers and
# field_name from the question/label text, skipping machine codes in red and answer options.

import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title: large blue text (~16.5pt, #004c99 or similar blue)
        form_title = None
        for line in lines:
            if line.size >= 15.0 and line.non_black and '#004c99' in str(line):
                # This is likely a form title
                form_title = line.text.strip()
                break
        
        # Also check for C-SSRS "Intensity of Ideation" + "Since Last Visit" pattern
        # These appear as two 10.5pt black text lines at the top
        if not form_title:
            intensity_line = None
            visit_line = None
            for i, line in enumerate(lines):
                if line.y0 < 130 and line.size >= 10.0 and line.size <= 11.0 and not line.non_black:
                    text = line.text.strip()
                    if text == "Intensity of Ideation":
                        intensity_line = text
                    elif text == "Since Last Visit":
                        visit_line = text
            
            if intensity_line and visit_line:
                form_title = f"{intensity_line} - {visit_line}"
        
        if form_title:
            current_form = form_title
        
        # Now extract fields from this page
        # Fields are typically black text, not red (red is machine codes)
        # Skip lines that are clearly machine codes (in brackets) or answer options
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip red text (machine codes/annotations)
            if line.non_black and '[' in line.text:
                i += 1
                continue
            
            # Skip page numbers
            if re.match(r'Page \d+ of \d+', line.text.strip()):
                i += 1
                continue
            
            # Skip table headers and structural elements
            if line.bold and line.text.strip() in ['Visit Num', 'Visit Label', 'Page Num', 'Page Label', 
                                                     'Dynamic?', 'Description of Dynamic', 'ber',
                                                     'Lifetime', 'Past 3 Month', 'Since Last Visit',
                                                     'Intensity of Ideation', 'Sample', 'Timepoint',
                                                     'Sample Status', 'Time of', 'Barcode', 'Backup',
                                                     'Collection', 'Number']:
                i += 1
                continue
            
            # Look for field labels - typically black text that forms a question
            # Fields often start at x ~61-64 and are in regular or bold black text
            if not line.non_black and line.size >= 9.0 and line.size <= 12.0:
                text = line.text.strip()
                
                # Skip empty lines
                if not text:
                    i += 1
                    continue
                
                # Skip schedule section headers
                if text.startswith('Schedule_'):
                    i += 1
                    continue
                
                # Skip "Row X" labels (but they may indicate a field follows)
                if re.match(r'^Row \d+$', text):
                    i += 1
                    continue
                
                # Skip pure numbers or dates
                if re.match(r'^\d+$', text) or re.match(r'^\d{1,2}[A-Za-z]{3,9}\d{4}$', text):
                    i += 1
                    continue
                
                # Skip answer option patterns (single words/phrases that are likely options)
                # But be careful not to skip real field labels
                if text in ['YES', 'NO', 'Collected', 'Not', 'Scan', 'Predose', 'Postdose']:
                    i += 1
                    continue
                
                # Skip lines that look like enumeration values (in parentheses at start)
                if re.match(r'^\(\d+\)', text):
                    i += 1
                    continue
                
                # Check if this looks like a field label
                # Field labels are typically longer phrases or questions
                # For C-SSRS pages, look for bold questions
                if len(text) > 3 and not text.startswith('['):
                    # Check if next lines continue this field (wrapping)
                    field_text = text
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        # If next line is close in y position and x position, it's a continuation
                        if (not next_line.non_black and 
                            next_line.y0 - line.y1 < 20 and 
                            abs(next_line.x0 - line.x0) < 20 and
                            next_line.size >= 9.0 and next_line.size <= 12.0 and
                            not '[' in next_line.text):
                            
                            next_text = next_line.text.strip()
                            # Stop if we hit a new field marker or answer options
                            if next_text.startswith('Row ') or next_text in ['YES', 'NO'] or re.match(r'^\(\d+\)', next_text):
                                break
                            field_text += ' ' + next_text
                            j += 1
                        else:
                            break
                    
                    # Only add if we have a form name and the field looks valid
                    if current_form and len(field_text) > 5:
                        # Additional filtering: skip if it's clearly not a field
                        if not re.match(r'^[\d\s\-/]+$', field_text):
                            records.append({
                                'form_name': current_form,
                                'field_name': field_text,
                                'page': page_num
                            })
                    
                    i = j
                    continue
            
            i += 1
    
    # Deduplicate while preserving order
    seen = set()
    unique_records = []
    for rec in records:
        key = (rec['form_name'], rec['field_name'], rec['page'])
        if key not in seen:
            seen.add(key)
            unique_records.append(rec)
    
    return unique_records
```