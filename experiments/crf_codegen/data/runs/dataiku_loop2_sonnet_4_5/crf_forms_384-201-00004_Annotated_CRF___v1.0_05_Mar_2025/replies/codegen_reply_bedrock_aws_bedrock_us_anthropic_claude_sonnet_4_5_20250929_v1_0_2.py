```python
"""
This CRF document has several layout types:
1. Cover/approval pages (1-2) with no data fields
2. Schedule pages (11+) listing study events/timepoints - not data-entry fields
3. Main CRF form pages (55+) with field definitions in a two-column layout:
   - Left column (~x=46-250): field labels, checkboxes, input boxes
   - Right column (~x=453+): technical metadata (OID, format, data type, etc.)
4. Code list pages (180+) showing lookup tables - not data fields

Key observations from sample pages:
- Form names are in white text (#ffffff) on colored background, sz=12, at top of page
- Field labels are at x~46.5, sz=7.5, black text
- Checkboxes are marked with "O" followed by option text at x~232-249
- Input boxes shown as [_|_|_] patterns
- Technical metadata is in right column at x~415-453
- Field identifiers in brackets like [EG_REPEAT_Q], [SAS Field Name: EGRPT]
- Code list pages have "Coded" and "Decode" headers

Strategy:
- Extract form name from white text headers (sz=12, #ffffff)
- Extract field labels from left column (x~46.5, sz=7.5, black)
- Look for descriptive text that precedes checkboxes or input boxes
- Skip technical metadata lines (right column x>400)
- Skip code list pages
- Skip lines that are just field codes in brackets
"""

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    seen_fields = set()  # Track (form, field) to avoid duplicates
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip cover pages
        if page_num <= 3:
            continue
        
        # Detect form name: white text (#ffffff) at sz=12 near top of page
        for line in lines:
            if line.size >= 11.5 and line.size <= 13 and '#ffffff' in str(line.non_black or ''):
                text = line.text.strip()
                # Skip technical metadata lines
                if text and not text.startswith('Origin:') and not text.startswith('Aliases:'):
                    # This is a form name
                    current_form = text
                    seen_fields.clear()  # New form section
                    break
        
        # Skip code list pages (have "Coded" and "Decode" headers)
        has_coded_decode = False
        for line in lines:
            if line.text.strip() in ['Coded', 'Decode'] and line.bold:
                has_coded_decode = True
                break
        if has_coded_decode:
            continue
        
        # Extract fields from left column
        # Look for field labels at x~46.5, sz~7.5, black text
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty or very short lines
            if not text or len(text) < 3:
                continue
            
            # Skip lines in right column (technical metadata)
            if line.x0 > 400:
                continue
            
            # Skip technical metadata patterns
            if any(pattern in text for pattern in [
                'Code List:', 'Format:', 'Data Type:', 'Origin:', 'Mandatory?:',
                'Disallow Future Date:', 'Description:', 'Aliases:', 'Odm OID',
                'SAS Field Name:', 'Conditional Item:', 'Visible If Value:',
                'Role Restriction:', 'Repeating:', 'Domain:', 'Default Item Value:',
                'Conditionally Visible', 'Study Event:', 'Timepoint:', 'Requires Role:',
                'Value Calculated', 'Device Parameter:', 'SDS Var Name:', 'Range (soft):',
                'Range (hard):', 'Units:', 'Short Name'
            ]):
                continue
            
            # Skip lines that are field codes in brackets
            if re.match(r'^\[[\w_\s\-]+\]$', text):
                continue
            
            # Skip lines that are just date/time formats
            if re.match(r'^dd-MMM-yyyy', text):
                continue
            
            # Skip page numbers and document IDs
            if re.match(r'^\d+$', text) or text.startswith('384-201-'):
                continue
            
            # Skip checkbox options (lines starting with "O " at x~232-249)
            if text.startswith('O ') and line.x0 > 200:
                continue
            
            # Skip lines that are just input box patterns
            if re.match(r'^\[_\|_', text):
                continue
            
            # Skip colored header lines (these are section headers, not fields)
            if '#31708f' in str(line.non_black or '') or '#666677' in str(line.non_black or ''):
                continue
            
            # Identify field labels:
            # - At x position ~46.5 (left column)
            # - Size ~7.5 (field label size)
            # - Black text
            # - Contains substantive text (not just symbols)
            # - Not a technical annotation
            
            is_field = False
            field_text = text
            
            # Pattern 1: Field labels at x~46.5, sz~7.5, black
            if 44 <= line.x0 <= 50 and 7.0 <= line.size <= 8.0 and line.non_black is None:
                # Must contain actual words (not just codes)
                if re.search(r'[a-zA-Z]{3,}', text):
                    # Not starting with technical prefixes
                    if not text.startswith('[') and not text.startswith('?'):
                        # Check if this looks like a question or descriptive label
                        # Should have multiple words or end with question mark
                        if ' ' in text or text.endswith('?') or len(text) > 15:
                            is_field = True
                            field_text = text
            
            # Pattern 2: Lines with date/time input boxes that have a label
            if '[_|_]' in text and line.x0 < 100:
                # Extract the label part before the input boxes
                label_match = re.match(r'^([^[]+)', text)
                if label_match:
                    potential_label = label_match.group(1).strip()
                    # Must be substantive (not just "Date" or single word)
                    if potential_label and len(potential_label) > 5 and ' ' in potential_label:
                        is_field = True
                        field_text = potential_label
            
            if is_field and current_form:
                # Clean up field text
                field_text = field_text.strip()
                # Remove trailing colons
                field_text = re.sub(r':$', '', field_text)
                # Remove trailing question marks (keep them in middle of text)
                if field_text.endswith('?'):
                    field_text = field_text[:-1].strip()
                
                # Final validation: must be substantive
                if len(field_text) >= 5 and re.search(r'[a-zA-Z]{3,}', field_text):
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