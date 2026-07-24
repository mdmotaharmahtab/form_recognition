```python
"""
This CRF document has several layout types:
1. Cover/approval pages (1-2) with no data fields
2. Schedule pages (11+) listing study events/timepoints - not data-entry fields
3. Main CRF form pages (55+) with field definitions in a two-column layout:
   - Left column (~x=46-250): field labels, checkboxes, input boxes
   - Right column (~x=453+): technical metadata (OID, format, data type, etc.)
4. Code list pages (180+) showing lookup tables - not data fields

Strategy:
- Identify form names from large colored headers (sz>=12, colored background)
- Extract field labels from the left column that represent actual data entry:
  * Lines with checkboxes (O prefix), date/time input patterns [_|_], or text inputs
  * Exclude technical annotations (OID, Format, Data Type, etc. in right column)
  * Exclude code list decode tables
- Track current form name across pages as state
"""

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    seen_fields = set()  # Track (form, field) to avoid duplicates within same form section
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip cover pages
        if page_num <= 3:
            continue
        
        # Detect form name: large colored text (white on colored background)
        for line in lines:
            # Form headers are sz>=12, white text (#ffffff), near left edge
            if line.size >= 12 and line.x0 < 100 and '#ffffff' in str(line.non_black or ''):
                # Check if this looks like a form title (not just metadata)
                text = line.text.strip()
                if text and not text.startswith('Aliases:') and not text.startswith('Origin:'):
                    # This is likely a form name
                    current_form = text
                    seen_fields.clear()  # New form section
                    break
        
        # Skip code list pages (have "Coded" and "Decode" headers)
        has_coded_decode = False
        for line in lines:
            if line.text.strip() in ['Coded', 'Decode'] and line.bold and line.x0 < 100:
                has_coded_decode = True
                break
        if has_coded_decode:
            continue
        
        # Extract fields from left column (x < 400)
        left_column_lines = [l for l in lines if l.x0 < 400]
        
        for i, line in enumerate(left_column_lines):
            text = line.text.strip()
            
            # Skip empty, very short, or technical lines
            if not text or len(text) < 3:
                continue
            
            # Skip technical metadata patterns
            if any(pattern in text for pattern in [
                'Code List:', 'Format:', 'Data Type:', 'Origin:', 'Mandatory?:',
                'Disallow Future Date:', 'Description:', 'Aliases:', 'Odm OID',
                'SAS Field Name:', 'Conditional Item:', 'Visible If Value:',
                'Role Restriction:', 'Repeating:', 'Domain:', 'Default Item Value:',
                'Conditionally Visible', 'Study Event:', 'Timepoint:'
            ]):
                continue
            
            # Skip lines that are just technical codes in brackets
            if re.match(r'^\[[\w_]+\]$', text):
                continue
            
            # Skip lines that look like dates/times without context
            if re.match(r'^[\d\-:]+$', text):
                continue
            
            # Skip page numbers and headers
            if re.match(r'^\d+$', text) or text.startswith('384-201-'):
                continue
            
            # Skip answer options (single letter O followed by option text)
            if re.match(r'^O\s+[A-Z]', text):
                continue
            
            # Identify actual field labels:
            # 1. Lines that end with a question or are descriptive (not in brackets)
            # 2. Lines at x ~46 that are substantive text (not checkboxes alone)
            # 3. Not starting with technical prefixes
            
            is_field = False
            field_text = text
            
            # Pattern 1: Descriptive text at field label position (x ~46)
            if 45 <= line.x0 <= 80 and line.size >= 7 and line.size <= 11:
                # Not a checkbox option line (those start with O)
                if not text.startswith('O '):
                    # Not a technical bracket
                    if not text.startswith('['):
                        # Has substantive content (not just numbers/symbols)
                        if re.search(r'[a-zA-Z]{3,}', text):
                            # Check if this looks like a question or label
                            # (contains words, possibly ends with punctuation)
                            is_field = True
            
            # Pattern 2: Lines with date/time input boxes
            if '[_|_]' in text and 'dd-MMM-yyyy' not in text:
                # Extract the label part before the input boxes
                label_match = re.match(r'^([^[]+)', text)
                if label_match:
                    field_text = label_match.group(1).strip()
                    if field_text and len(field_text) > 2:
                        is_field = True
            
            if is_field and current_form:
                # Clean up field text
                field_text = field_text.strip()
                # Remove trailing colons
                field_text = re.sub(r':$', '', field_text)
                
                # Avoid duplicates
                key = (current_form, field_text)
                if key not in seen_fields:
                    seen_fields.add(key)
                    results.append({
                        "form_name": current_form,
                        "field_name": field_text,
                        "page": page_num
                    })
    
    return results
```