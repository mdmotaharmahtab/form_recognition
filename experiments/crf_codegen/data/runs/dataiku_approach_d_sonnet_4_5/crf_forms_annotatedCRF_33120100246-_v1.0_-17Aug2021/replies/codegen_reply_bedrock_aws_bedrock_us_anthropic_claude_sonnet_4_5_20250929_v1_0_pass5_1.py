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
    
    for page_index, lines in pages:
        page_num = page_index + 1
        
        # Identify the form name: large blue header (sz ~14.4, color #004c99)
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
                        break
        
        # Skip TOC pages (family A) - they have many blue links
        blue_link_count = sum(1 for line in lines if line.non_black and 
                              re.match(r'^\d+\.\d+\.', line.text))
        if blue_link_count > 10:
            continue
        
        # Skip schedule/assessment table pages (families B-C)
        # These have many lines with blue text (#0000ee) and numeric codes
        schedule_indicators = sum(1 for line in lines if '#0000ee' in str(line.text) or 
                                  (line.size < 9.0 and re.match(r'^\d+$', line.text.strip())))
        if schedule_indicators > 15:
            continue
        
        # Extract fields from field-bearing pages (families D-E-F)
        # Fields are black text labels, not red technical codes
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip red technical codes (machine codes like [VSSUVTIM], [TYPE: ...])
            if line.non_black or re.match(r'^\[.*\]$', line.text.strip()):
                i += 1
                continue
            
            # Skip page numbers, headers, footers
            if re.match(r'^\d+$', line.text.strip()) and line.size < 9.0:
                i += 1
                continue
            
            # Skip "Row N" labels (these are structural markers, not fields)
            if re.match(r'^Row \d+$', line.text.strip(), re.IGNORECASE):
                i += 1
                continue
            
            # Skip answer options (Yes/No, enumeration values)
            # These are typically gray (#454545) or positioned to the right
            if line.text.strip() in ['Yes', 'No'] and (line.non_black or line.x0 > 400):
                i += 1
                continue
            
            # Skip enumeration option lists (numbered options like "(1) ...", "(2) ...")
            if re.match(r'^\(\d+\)', line.text.strip()):
                i += 1
                continue
            
            # Skip "If Yes" prompts and similar conditional text
            if re.match(r'^If (Yes|No)', line.text.strip(), re.IGNORECASE):
                i += 1
                continue
            
            # Identify field labels: black text, reasonable size (7-11pt), not bold section headers
            if not line.non_black and line.size >= 7.0 and line.size <= 11.0:
                # Check if this looks like a field label
                text = line.text.strip()
                
                # Skip empty lines
                if not text:
                    i += 1
                    continue
                
                # Skip pure descriptive text (explanations, notes)
                # These typically start with lowercase or are very long
                if len(text) > 200:
                    i += 1
                    continue
                
                # Skip column headers in repeatable tables
                if line.y0 < 200 and line.x0 > 150 and \
                   text in ['Date of Contact/Attempt', 'Type of Contact', 'Method of Contact']:
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
                
                # Validate field: must be a question or label
                # Skip if it's just a number, date, or very short
                if len(field_text) < 3:
                    i = j
                    continue
                
                # Skip if it's a pure instruction or note
                if field_text.startswith('Note:') or field_text.startswith('Instructions:'):
                    i = j
                    continue
                
                # Add the field
                if form_name and field_text:
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