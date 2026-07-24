```python
# This CRF has four main layout families:
# A: Title page (no fields)
# B: Index/reference tables listing forms, codes (no data-entry fields)
# C: Form pages with complex nested field structure (medications, etc.)
# D: Form pages with simpler field structure (vitals, labs, ECG, etc.)
# Strategy: Extract form_name from white-on-blue header (sz=12.0, #ffffff).
# Fields in family D are labeled at left (x~46.5, sz=7.5), often with multi-line
# wrap. Family C has similar structure but with checkboxes/options below labels.
# Skip pages with no white header. Join wrapped label lines. Filter out option
# values, technical annotations (right column metadata), and table headers.

import re
from collections import defaultdict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from white header (sz=12.0, color=#ffffff)
        form_name = ""
        for line in lines:
            if abs(line.size - 12.0) < 0.5 and line.non_black and line.x0 < 100:
                # Check if color is white-ish (looking for #ffffff header)
                form_name = line.text.strip()
                break
        
        # Skip if no form name found (likely index/title page)
        if not form_name:
            continue
        
        # Skip known non-field pages by structural signature
        # Family B: has "Category Visit" or "Coded/Decode" table headers
        has_table_header = any(
            "Category Visit" in line.text or 
            (line.text == "Coded" and abs(line.x0 - 45.8) < 5) or
            (line.text == "Name" and line.x0 < 50 and "Forms" in [l.text for l in lines])
            for line in lines
        )
        if has_table_header:
            continue
        
        # Collect potential field labels
        # Labels are typically at x~46.5, sz~7.5, not colored, not in brackets
        # and not in the right metadata column (x > 400)
        field_labels = []
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels: left column, medium size, not metadata
            if (40 < line.x0 < 250 and 
                6.5 < line.size < 9.0 and 
                not line.non_black and
                line.text and
                not line.text.startswith('[') and
                not line.text.startswith('O ') and  # Skip option markers
                not line.text in ['Code List:', 'Documentation of all']):
                
                # Skip if it's a metadata label
                skip_terms = ['Aliases:', 'Description:', 'SAS Field Name:', 
                             'Origin:', 'Format:', 'Data Type:', 'Mandatory?:',
                             'Disallow Future Date:', 'Edit Checks:', 'Units:',
                             'Range', 'Device Parameter:', 'SDS Var Name:',
                             'Requires', 'Conditionally', 'Conditional',
                             'Default Item Value:', 'Visible If', 'Comment:',
                             'Code List', 'Formal Expression']
                if any(term in line.text for term in skip_terms):
                    i += 1
                    continue
                
                # Skip technical codes in brackets like [CMYN], [CMTRT]
                if re.match(r'^\[[A-Z_0-9]+\]$', line.text.strip()):
                    i += 1
                    continue
                
                # Skip metadata section headers (colored, bold)
                if line.non_black or (line.bold and line.size > 9):
                    i += 1
                    continue
                
                # Collect this line and potential continuation lines
                label_parts = [line.text.strip()]
                j = i + 1
                
                # Look ahead for wrapped continuation lines
                # Continuations are close in y, similar x, similar size
                while j < len(lines):
                    next_line = lines[j]
                    y_diff = next_line.y0 - lines[j-1].y0
                    
                    # Stop if too far vertically or we hit a new field marker
                    if y_diff > 20:
                        break
                    
                    # Check if it's a continuation: similar x, size, not special
                    if (40 < next_line.x0 < 250 and
                        abs(next_line.size - line.size) < 1.5 and
                        not next_line.non_black and
                        not next_line.text.startswith('[') and
                        not next_line.text.startswith('O ') and
                        y_diff < 12):
                        
                        # Skip if it's metadata
                        if any(term in next_line.text for term in skip_terms):
                            break
                        
                        label_parts.append(next_line.text.strip())
                        j += 1
                    else:
                        break
                
                # Join multi-line labels
                full_label = ' '.join(label_parts).strip()
                
                # Filter out noise
                if full_label and len(full_label) > 1:
                    # Skip pure technical patterns
                    if re.match(r'^[A-Z_0-9]+$', full_label):
                        i = j
                        continue
                    
                    # Skip checkbox option values (common patterns)
                    option_words = ['Yes', 'No', 'Unknown', 'Negative', 'Positive',
                                   'NCS', 'CS', 'Normal', 'Abnormal', 'TOPICAL',
                                   'ORAL', 'INTRAVENOUS', 'mg', 'mL', 'DROP', 'IU']
                    if full_label in option_words:
                        i = j
                        continue
                    
                    # Skip date/time format strings
                    if 'MMM' in full_label or full_label.count('_') > 3:
                        i = j
                        continue
                    
                    # Skip section dividers/headers that are too short
                    if len(full_label) < 4 and full_label.isupper():
                        i = j
                        continue
                    
                    field_labels.append(full_label)
                
                i = j
            else:
                i += 1
        
        # Deduplicate and add to results
        seen = set()
        for label in field_labels:
            key = (form_name, label)
            if key not in seen:
                seen.add(key)
                results.append({
                    "form_name": form_name,
                    "field_name": label,
                    "page": page_num
                })
    
    return results
```
