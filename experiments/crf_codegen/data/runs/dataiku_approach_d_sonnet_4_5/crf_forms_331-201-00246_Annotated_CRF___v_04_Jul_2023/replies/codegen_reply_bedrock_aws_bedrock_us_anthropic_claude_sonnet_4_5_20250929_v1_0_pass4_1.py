```python
# This CRF document contains multiple layout families:
# - Title/TOC pages (families A, B, C) with section listings
# - Form pages with field labels and data entry areas (families D, E, F, G)
# Strategy: Extract form_name from large colored headers (sz ~16.5, color #004c99)
# and field_name from black text labels that precede data entry areas.
# Skip technical annotations in red/gray, version history tables, and page furniture.

import re
from typing import List, Dict, Tuple

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Sort lines by y, then x for processing
        sorted_lines = sorted(lines, key=lambda ln: (ln.y0, ln.x0))
        
        # Look for form title: large colored text (sz >= 15, color #004c99 or similar blue)
        for line in sorted_lines:
            if line.size >= 15.0 and line.non_black and '#004c99' in str(line):
                # This is likely a form/section title
                text = line.text.strip()
                if text and not re.match(r'^Page \d+', text):
                    current_form = text
                    break
        
        # Extract field labels
        # Field labels are typically:
        # - Black text (not red/gray which are technical annotations)
        # - Not in header/footer area (y < 780)
        # - Not page numbers or furniture
        # - Not answer options (Yes/No/X markers)
        # - Not table column headers that repeat
        
        i = 0
        while i < len(sorted_lines):
            line = sorted_lines[i]
            
            # Skip if in footer area
            if line.y0 > 780:
                i += 1
                continue
            
            # Skip if non-black (technical annotations in red/gray)
            if line.non_black:
                i += 1
                continue
            
            text = line.text.strip()
            
            # Skip empty, page numbers, and common furniture
            if not text or re.match(r'^Page \d+', text):
                i += 1
                continue
            
            # Skip version history table headers
            if text in ['Version', 'Date', 'Changed By', 'Details']:
                i += 1
                continue
            
            # Skip common answer options and markers
            if text in ['Yes', 'No', 'N/A', 'X', 'Scan', 'Collected', 'Not']:
                i += 1
                continue
            
            # Skip bullet points
            if text == '•':
                i += 1
                continue
            
            # Skip technical field codes in brackets
            if re.match(r'^\[.*\]$', text):
                i += 1
                continue
            
            # Skip table column headers that are generic
            if text in ['Record', 'Term', 'Start Date', 'End Date', 'Ongoing?', 
                       'Medication', 'Indication', 'Start time', 'ID',
                       'Procedure/Surgery Name', 'Sample', 'Timepoint', 
                       'Sample Status', 'Time of', 'Collection', 'Barcode',
                       'Backup', 'Barcode Number', 'Number']:
                i += 1
                continue
            
            # Skip copyright and reference text
            if '©' in text or 'Columbia' in text or 'CCNMD' in text:
                i += 1
                continue
            
            # Skip "Repeatable row" instructions
            if 'Repeatable row' in text or 'Add Row' in text:
                i += 1
                continue
            
            # Skip section markers that are just labels
            if text in ['Of Childbearing Potential', 'Supine', 'Standing']:
                i += 1
                continue
            
            # Check if this looks like a field label
            # Field labels are typically questions or descriptive text
            # They may span multiple lines
            
            # Look for question-like patterns or descriptive labels
            is_field = False
            
            # Pattern 1: Questions ending with ?
            if text.endswith('?'):
                is_field = True
            
            # Pattern 2: Descriptive labels (not too short, not all caps unless reasonable)
            elif len(text) > 10 and not text.isupper():
                is_field = True
            
            # Pattern 3: Labels with specific keywords
            elif any(keyword in text.lower() for keyword in 
                    ['date', 'time', 'subject', 'patient', 'status', 'method', 
                     'commit', 'transcribed', 'reason', 'placed', 'measurement']):
                is_field = True
            
            if is_field:
                # Check if next lines continue this label (wrapped text)
                full_label = text
                j = i + 1
                while j < len(sorted_lines):
                    next_line = sorted_lines[j]
                    # If next line is close in y and x, and not red, might be continuation
                    if (abs(next_line.y0 - line.y0) < 15 and 
                        not next_line.non_black and
                        not re.match(r'^\[.*\]$', next_line.text.strip())):
                        next_text = next_line.text.strip()
                        # Check if it looks like a continuation
                        if (next_text and 
                            not next_text in ['Yes', 'No', 'N/A', 'X'] and
                            len(next_text) > 2):
                            full_label += ' ' + next_text
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # Clean up the label
                full_label = ' '.join(full_label.split())
                
                # Final validation: skip if it's really just furniture
                if (full_label and 
                    len(full_label) > 3 and
                    not re.match(r'^\d+$', full_label) and
                    not re.match(r'^Row \d+$', full_label)):
                    
                    records.append({
                        "form_name": current_form,
                        "field_name": full_label,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return records
```