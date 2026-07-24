```python
# This document contains:
# 1. A cover/approval page (page 1-2) with form metadata
# 2. A study event/form schedule matrix (pages 5+) with two columns: "Study Event" and "Form"
# 3. Detailed form pages (pages 16+, 56+, 77+, 125+, 143+) with field definitions including
#    labels, field codes, data types, and metadata
# 4. Lab panel reference pages (page 229+) listing test names without data entry fields
#
# Strategy:
# - Skip cover pages (pages 1-2) - no data fields
# - Skip schedule matrix pages (recognize by "Study Event" / "Form" column headers) - these list
#   forms but contain no actual data-entry fields
# - Extract from detailed form pages: identify by cyan form headers (color #31708f) and
#   field labels in black 7.5pt text on the left, paired with metadata on the right
# - Skip lab reference pages (no data entry, just panel definitions)
# - Form names: use the most recent cyan header (domain repeating group title)
# - Field names: black 7.5pt text at x~46.5, excluding SAS field names in brackets,
#   code list values (radio options), and technical annotations

import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    seen = set()
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip cover/approval pages
        if page_num <= 2:
            continue
        
        # Check if this is a schedule matrix page (has "Study Event" and "Form" headers)
        header_texts = [ln.text for ln in lines[:20] if ln.size >= 10]
        if "Study Event" in header_texts and "Form" in header_texts:
            continue
        
        # Check if this is a lab panel reference page (has "Name", "Order ID", "Container" headers)
        if any("Order ID" in ln.text for ln in lines[:15]) and any("Container" in ln.text for ln in lines[:15]):
            continue
        
        # Update current form from cyan headers (#31708f)
        for ln in lines:
            if ln.non_black and ln.size >= 10 and ln.x0 < 100:
                # Cyan form/section headers
                txt = ln.text.strip()
                if txt and not any(skip in txt.lower() for skip in ['origin:', 'repeating:', 'domain:', 'conditionally']):
                    # Clean up form name
                    if txt and txt not in ['CM', 'Electrocardiogram 2']:
                        current_form = txt
        
        # Extract field labels: black text, size ~7.5, x~46.5, not in brackets, not radio options
        for i, ln in enumerate(lines):
            if (not ln.non_black and 
                7.0 <= ln.size <= 8.0 and 
                45 <= ln.x0 <= 48 and
                ln.text.strip()):
                
                txt = ln.text.strip()
                
                # Skip if it's a bracketed SAS field name
                if txt.startswith('[') and txt.endswith(']'):
                    continue
                
                # Skip if it's a radio option (starts with 'O ')
                if txt.startswith('O '):
                    continue
                
                # Skip code list labels
                if txt.lower().startswith('code list:'):
                    continue
                
                # Skip common non-field text
                skip_patterns = [
                    r'^\[SAS Field Name:',
                    r'^dd-MMM-yyyy',
                    r'^\d+\.\d+\s*$',
                    r'^Verify urine',
                    r'^Documentation of',
                    r'^\(\d+\)$'
                ]
                if any(re.match(pat, txt, re.I) for pat in skip_patterns):
                    continue
                
                # Check for multi-line label (next line continues)
                field_name = txt
                j = i + 1
                while j < len(lines) and j < i + 5:
                    next_ln = lines[j]
                    # Continuation: similar x position, size, not bracketed
                    if (not next_ln.non_black and
                        7.0 <= next_ln.size <= 8.0 and
                        45 <= next_ln.x0 <= 48 and
                        not next_ln.text.startswith('[') and
                        not next_ln.text.startswith('O ') and
                        next_ln.text.strip()):
                        field_name += ' ' + next_ln.text.strip()
                        j += 1
                    else:
                        break
                
                # Clean and validate field name
                field_name = ' '.join(field_name.split())
                
                # Must have some alphabetic content
                if not re.search(r'[a-zA-Z]{3,}', field_name):
                    continue
                
                # Skip if it looks like a date format or technical metadata
                if re.match(r'^[\d\s:\-\|_\[\]\.]+$', field_name):
                    continue
                
                # Valid field label found
                if current_form and field_name:
                    key = (current_form, field_name, page_num)
                    if key not in seen:
                        seen.add(key)
                        records.append({
                            "form_name": current_form,
                            "field_name": field_name,
                            "page": page_num
                        })
    
    return records
```
