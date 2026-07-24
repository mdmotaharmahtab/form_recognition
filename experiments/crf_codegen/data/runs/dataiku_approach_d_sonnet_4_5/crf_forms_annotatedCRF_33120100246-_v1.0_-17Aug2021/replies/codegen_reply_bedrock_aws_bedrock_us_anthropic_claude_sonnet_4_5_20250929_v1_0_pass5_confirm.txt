Looking at the sample pages:

**Page 549 (cluster 0)**: Contains clear data-entry fields like "Time of Vitals Measurement", "Systolic Blood Pressure (mmHg)", "Diastolic Blood Pressure (mmHg)", "Heart Rate (bpm)", etc. These are black text at size 7.8, followed by red technical codes. This is a standard field page that should be extracted.

**Page 14 (cluster 1)**: This appears to be a schedule/table of contents page with blue links (#0000ee) listing form names with numbers. This is NOT a data-entry page - it's a navigation/schedule page.

**Page 550 (cluster 2)**: Similar to page 549, contains data-entry fields like "Diastolic Blood Pressure (mmHg)", "Heart Rate (bpm)" with red technical codes. Should be extracted.

The problem is that my current program is skipping pages 549 and 550 because they have red technical codes (#ff0000) interspersed with the field labels. The program correctly identifies field labels (black text, size 7.8) but may be filtering them out or not finding a form_name.

Looking more carefully, I don't see a large blue header on page 549 in the sample, which means `form_name` would be empty and no records would be added. The issue is that the form name must be on an earlier page, and I need to carry it forward.

Let me update the program to:
1. Carry form names forward across pages
2. Better handle pages with interspersed red codes

```python
# This CRF document contains multiple layout families:
# - Family A: Table of contents with section links
# - Family B-C: Schedule/assessment tables listing visit forms
# - Family D-E: Standard field pages with field labels and technical codes
# - Family F: Repeatable row forms with column headers
# Strategy: Extract field_name from black text labels, ignoring red technical codes.
# Form names appear as large blue headers (sz ~14.4, color #004c99).
# Skip TOC pages and schedule tables; extract from field-bearing pages only.

import re

def extract(pages):
    records = []
    current_form_name = ""
    
    for page_index, lines in pages:
        page_num = page_index + 1
        
        # Identify the form name: large blue header (sz ~14.0+, color #004c99 or similar)
        form_name = ""
        for line in lines:
            if line.size >= 13.0 and line.size <= 16.0 and line.non_black:
                # Check if it's a blue header (not red technical codes)
                # Blue headers are typically #004c99 or similar
                if not re.search(r'#ff0000|#0000ee', line.text, re.IGNORECASE):
                    # Exclude TOC-like entries and schedule headers
                    if not re.match(r'^\d+\.\d+\.', line.text) and \
                       not line.text.startswith('CHANGE HISTORY') and \
                       not line.text.startswith('SCHEDULE OF ASSESSMENT') and \
                       not line.text.startswith('PAGES'):
                        form_name = line.text.strip()
                        current_form_name = form_name
                        break
        
        # If no form name found on this page, use the previous one
        if not form_name and current_form_name:
            form_name = current_form_name
        
        # Skip TOC pages (family A) - they have many blue links
        blue_link_count = sum(1 for line in lines if line.non_black and 
                              re.match(r'^\d+\.\d+\.', line.text))
        if blue_link_count > 10:
            continue
        
        # Skip schedule/assessment table pages (families B-C)
        # These have many lines with blue text (#0000ee) and are structured as tables
        blue_ee_count = sum(1 for line in lines if '#0000ee' in str(line.non_black))
        if blue_ee_count > 15:
            continue
        
        # Extract fields from field-bearing pages (families D-E-F)
        # Fields are black text labels, not red technical codes
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip red technical codes (machine codes like [VSSUVTIM], [TYPE: ...])
            if line.non_black:
                i += 1
                continue
            
            text = line.text.strip()
            
            # Skip technical codes in brackets
            if re.match(r'^\[.*\]$', text):
                i += 1
                continue
            
            # Skip page numbers, headers, footers
            if re.match(r'^\d+$', text) and line.size < 9.0:
                i += 1
                continue
            
            # Skip "Row N" labels (these are structural markers, not fields)
            if re.match(r'^Row \d+$', text, re.IGNORECASE):
                i += 1
                continue
            
            # Skip answer options (Yes/No, enumeration values)
            if text in ['Yes', 'No'] and line.x0 > 400:
                i += 1
                continue
            
            # Skip enumeration option lists (numbered options like "(1) ...", "(2) ...")
            if re.match(r'^\(\d+\)', text):
                i += 1
                continue
            
            # Skip "If Yes" prompts and similar conditional text
            if re.match(r'^If (Yes|No)', text, re.IGNORECASE):
                i += 1
                continue
            
            # Identify field labels: black text, reasonable size (7-11pt)
            if line.size >= 7.0 and line.size <= 11.0:
                # Skip empty lines
                if not text:
                    i += 1
                    continue
                
                # Skip pure descriptive text (explanations, notes)
                if len(text) > 200:
                    i += 1
                    continue
                
                # Skip very short non-descriptive text
                if len(text) < 3:
                    i += 1
                    continue
                
                # Skip pure instruction or note text
                if text.startswith('Note:') or text.startswith('Instructions:'):
                    i += 1
                    continue
                
                # Collect multi-line field labels
                field_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Continue if next line is a continuation (similar x, close y, black, not code)
                    if not next_line.non_black and \
                       abs(next_line.x0 - line.x0) < 20 and \
                       next_line.y0 - lines[j-1].y0 < 20 and \
                       not re.match(r'^\[.*\]$', next_line.text.strip()) and \
                       next_line.size >= 7.0 and next_line.size <= 11.0:
                        field_text += ' ' + next_line.text.strip()
                        j += 1
                    else:
                        break
                
                # Clean up field text
                field_text = ' '.join(field_text.split())
                
                # Add the field if we have a form name
                if form_name and field_text and len(field_text) >= 3:
                    records.append({
                        "form_name": form_name,
                        "field_name": field_text,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return records
```