```python
# STRUCTURE OBSERVED:
# - Large document (1085 pages) with multiple layout families
# - Form titles: Large (16.5pt) blue (#004c99) text at top of pages (family C, D, etc.)
# - Field labels: Regular 9pt black text, often followed by answer options or input areas
# - Machine codes: Red (#ff0000) text in square brackets (e.g., [RPM1], [TYPE:...])
# - Answer options: Gray (#999999) text, typically Yes/No/N/A choices, or enum values
# - Table structures: Column headers in families E, F, G with data rows below
# - Red technical annotations are structural landmarks, not output fields
# - Answer options appear inline or in lists after field labels

import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip TOC pages (families A, B) - dense with section links, no data fields
        if page_num <= 2:
            continue
        
        # Extract form title (large blue text at top, typically 16.5pt #004c99)
        for line in lines[:10]:  # Check first few lines
            if line.size >= 14 and line.non_black and line.y0 < 250:
                # Skip generic page headers and TOC-style entries
                text = line.text.strip()
                if text and not re.match(r'^(CHANGE HISTORY|SCHEDULE|PAGES|Page \d+)$', text):
                    # Check if it looks like a form title (not a machine code or table header)
                    if not re.match(r'^\[.*\]$', text) and not text in ['Sample', 'Status', 'Test', 'Result']:
                        current_form = text
                        break
        
        # Process field labels by layout family
        fields = []
        
        # Family C, D: Single column layout with labels followed by machine codes
        # Family E: Table layout with column headers
        # Family F, G: Mixed tables and text blocks
        
        # Detect table layout (families E, F, G)
        has_table_header = False
        header_y = -1
        for i, line in enumerate(lines[:20]):
            if line.text in ['Sample', 'Status', 'Test', 'Result', 'Suicidal Ideation', 'Suicidal Behaviour', 'Criteria']:
                has_table_header = True
                header_y = line.y0
                break
        
        if has_table_header:
            # Skip table structure pages - they typically have row markers but complex nested content
            # Extract only clear field-like labels that aren't table chrome
            i = 0
            while i < len(lines):
                line = lines[i]
                text = line.text.strip()
                
                # Skip machine codes, row markers, page numbers, and answer options
                if (re.match(r'^\[.*\]$', text) or 
                    re.match(r'^Row \d+$', text) or
                    re.match(r'^Page \d+', text) or
                    text in ['Yes', 'No', 'N/A', 'Met', 'Not Met', 'Positive', 'Negative', 'Not Done', 'Scan',
                             'Collected', 'Not Collected', 'Not Applicable', 'Predose', 'Lifetime', 'Past 3 Month',
                             'Past 6 Month', 'Met/Not Met', 'Since Last Visit', 'As per protocol']):
                    i += 1
                    continue
                
                # Look for substantial text that could be a field label
                # Must be black, reasonable size, and substantive
                if (line.size >= 8.5 and line.size <= 11 and not line.non_black and
                    len(text) > 15 and not text.startswith('(')):
                    
                    # Check if it's followed by answer options or machine code (indicating it's a field)
                    is_field = False
                    for j in range(i+1, min(i+8, len(lines))):
                        next_text = lines[j].text.strip()
                        if re.match(r'^\[.*\]$', next_text) or next_text in ['Yes', 'No', 'N/A', 'Positive', 'Negative', 'Not Done']:
                            is_field = True
                            break
                    
                    if is_field:
                        # Join wrapped lines
                        full_text = text
                        k = i + 1
                        while k < len(lines) and lines[k].y0 - line.y0 < 30:
                            next_line = lines[k]
                            next_text = next_line.text.strip()
                            if (not re.match(r'^\[.*\]$', next_text) and 
                                not next_text in ['Yes', 'No', 'N/A'] and
                                next_line.x0 < line.x0 + 50 and
                                next_line.size >= 8.5 and not next_line.non_black):
                                full_text += " " + next_text
                                k += 1
                            else:
                                break
                        
                        fields.append(full_text)
                
                i += 1
        
        else:
            # Single column layout (families C, D)
            i = 0
            while i < len(lines):
                line = lines[i]
                text = line.text.strip()
                
                # Skip machine codes, page numbers, form titles, subsection headers
                if (re.match(r'^\[.*\]$', text) or 
                    re.match(r'^Page \d+', text) or
                    line.size >= 14 or
                    (line.size >= 10 and line.bold and text in ['Not of Childbearing Potential', 'Of Childbearing Potential'])):
                    i += 1
                    continue
                
                # Skip standalone answer options and enum value lists
                if (text in ['Yes', 'No', 'N/A', 'As per protocol', 'Adverse Event', 'Dosing error',
                             'Dispensing error', 'Technical problems', 'Predose', '1h postdose',
                             'Albumin', 'Alkaline phosphatase', 'ALT', 'AST', 'Calcium',
                             'Hematocrit', 'Hemoglobin', 'Platelet count'] or
                    re.match(r'^\d+h postdose$', text)):
                    i += 1
                    continue
                
                # Look for field labels: black text, size 9-10pt, substantive length
                if (line.size >= 8.5 and line.size <= 11 and not line.non_black and
                    len(text) > 10 and line.x0 < 400):
                    
                    # Check if followed by machine code (strong indicator of field)
                    has_code = False
                    for j in range(i+1, min(i+5, len(lines))):
                        if re.match(r'^\[.*\]$', lines[j].text.strip()):
                            has_code = True
                            break
                    
                    # Or followed by answer options
                    has_options = False
                    for j in range(i+1, min(i+10, len(lines))):
                        if lines[j].text.strip() in ['Yes', 'No', 'N/A'] and lines[j].non_black:
                            has_options = True
                            break
                    
                    if has_code or has_options:
                        # Join wrapped continuation lines
                        full_text = text
                        k = i + 1
                        while k < len(lines) and lines[k].y0 - line.y0 < 25:
                            next_line = lines[k]
                            next_text = next_line.text.strip()
                            if (not re.match(r'^\[.*\]$', next_text) and
                                not next_text in ['Yes', 'No', 'N/A'] and
                                abs(next_line.x0 - line.x0) < 50 and
                                next_line.size >= 8.5 and not next_line.non_black and
                                len(next_text) > 5):
                                full_text += " " + next_text
                                k += 1
                            else:
                                break
                        
                        # Clean up formatting artifacts
                        full_text = re.sub(r'\s+', ' ', full_text).strip()
                        
                        # Skip if it's just a marker or instruction text without question
                        if not re.match(r'^(Row \d+|•)$', full_text) and len(full_text) > 15:
                            fields.append(full_text)
                
                i += 1
        
        # Add extracted fields to results
        for field_name in fields:
            if current_form or field_name:
                results.append({
                    "form_name": current_form,
                    "field_name": field_name,
                    "page": page_num
                })
    
    return results
```
