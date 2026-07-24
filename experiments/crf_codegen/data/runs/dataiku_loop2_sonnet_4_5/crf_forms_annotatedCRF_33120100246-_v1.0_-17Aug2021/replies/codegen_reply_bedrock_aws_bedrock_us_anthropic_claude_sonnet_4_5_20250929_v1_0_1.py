```python
"""
This CRF document contains multiple form sections with data-entry fields.
The structure shows:
1. Form names appear as large colored headers (size ~14.4, color #004c99)
2. Field labels are regular black text (size ~7.8) followed by technical annotations in red
3. Technical codes in red (e.g., [VISDAT], [TYPE: ...]) mark field boundaries but are not extracted
4. Answer options (Yes/No/etc.) in gray (#454545) are not fields themselves
5. Multi-column layouts exist; we use x-coordinates to distinguish columns

Strategy: Identify form headers by size/color, then extract black text labels that precede
red technical markers, filtering out answer options, instructions, and page furniture.
"""

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    seen_fields = set()  # Track (form, field) to avoid duplicates within same page
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        seen_fields.clear()
        
        # First pass: identify form name on this page
        for i, line in enumerate(lines):
            # Form headers: large blue text (size ~14-15, color #004c99)
            if line.size >= 13.0 and line.size <= 16.0 and line.non_black:
                # Check if it's a form header (not a sub-section marker)
                text = line.text.strip()
                # Skip numbered list items from TOC
                if not re.match(r'^\d+\.', text):
                    current_form = text
        
        # Second pass: extract field labels
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty lines
            if not text:
                i += 1
                continue
            
            # Skip red technical annotations
            if line.non_black and '[' in text:
                i += 1
                continue
            
            # Skip answer options (gray text with common option values)
            if line.non_black and text in ['Yes', 'No', 'N/A', 'NA', 'Not Done', 
                                            'Positive', 'Negative', 'Collected', 
                                            'Not Collected', 'Not Applicable', 'Scan',
                                            'Skip to next visit', 'Skip to ET visit',
                                            'Urine', 'Serum']:
                i += 1
                continue
            
            # Skip page numbers, headers, footers
            if re.match(r'^\d+$', text):
                i += 1
                continue
            
            # Skip table column headers that are generic
            if text in ['Sample', 'Status', 'Reason not', 'Date of Collection', 
                       'Time of', 'Barcode', 'Number', 'Test', 'Result', 'done',
                       'Collection', 'Scan']:
                i += 1
                continue
            
            # Skip section markers and instructions
            if text.startswith('Row ') or text.startswith('Version Number'):
                i += 1
                continue
            
            # Skip long instructional text
            if len(text) > 150:
                i += 1
                continue
            
            # Potential field label: black text, reasonable size
            if not line.non_black and line.size >= 7.0 and line.size <= 10.0:
                # Look ahead to see if next line(s) contain red technical marker
                has_marker = False
                for j in range(i+1, min(i+5, len(lines))):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Found a technical marker in red with brackets
                    if next_line.non_black and '[' in next_text and ']' in next_text:
                        # Extract field code to check if it's a field marker
                        match = re.search(r'\[([A-Z0-9_]+)\]', next_text)
                        if match:
                            code = match.group(1)
                            # Valid field codes (not metadata like TYPE, VISIBILITY, Read-only)
                            if code not in ['TYPE', 'VISIBILITY', 'Read-only field']:
                                has_marker = True
                                break
                
                if has_marker:
                    # Clean up the field label
                    field_label = text
                    
                    # Skip if it's just a value or date
                    if re.match(r'^[\d\-/]+$', field_label):
                        i += 1
                        continue
                    
                    # Skip if it looks like a code
                    if re.match(r'^\[.*\]$', field_label):
                        i += 1
                        continue
                    
                    # Skip common non-field text
                    skip_patterns = [
                        r'^As per protocol$',
                        r'^Adverse Event$',
                        r'^Dosing error$',
                        r'^Dispensing error$',
                        r'^Technical problems$',
                        r'^Physician decision$',
                        r'^Subject/guardian decision$',
                        r'^\d+\.\d+\.',  # TOC entries
                    ]
                    
                    should_skip = False
                    for pattern in skip_patterns:
                        if re.match(pattern, field_label):
                            should_skip = True
                            break
                    
                    if should_skip:
                        i += 1
                        continue
                    
                    # Valid field - add to results if not duplicate
                    key = (current_form, field_label)
                    if key not in seen_fields:
                        results.append({
                            "form_name": current_form,
                            "field_name": field_label,
                            "page": page_num
                        })
                        seen_fields.add(key)
            
            i += 1
    
    return results
```