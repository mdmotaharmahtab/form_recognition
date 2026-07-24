```python
# This CRF has multiple layout families:
# - Family A: title page (no fields)
# - Family B: reference tables / code lists (no data-entry fields)
# - Family C: detailed form pages with field definitions in a structured layout
# - Family D: similar detailed form pages with field definitions
# The form name appears in a white-on-color bar at y~34.8, size 12pt.
# Fields are identified by labels at x~46.5, size 7.5pt, with technical metadata on the right.
# We extract form_name from the colored header and field_name from left-column labels.

import re
from typing import List, Dict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form name: white text (size ~12pt) at y~34-36
        form_name = ""
        for line in lines:
            if 34 < line.y0 < 37 and 11.5 < line.size < 12.5:
                # Check if it's white text (common pattern for form headers)
                # or if it's a substantial title
                text = line.text.strip()
                if text and not text.startswith("384-201"):
                    form_name = text
                    break
        
        # Skip pages that are clearly reference/code list tables (Family B)
        # These have "Coded" and "Decode" column headers
        has_coded_decode = False
        for line in lines:
            if line.text.strip() in ["Coded", "Decode"] and line.bold:
                has_coded_decode = True
                break
        
        if has_coded_decode:
            continue
        
        # Skip title page (page 1) - it has no fields
        if page_num == 1:
            continue
        
        # Extract fields from the left column
        # Field labels appear at x~46.5, size ~7.5pt, not bold
        # They are followed by bracketed field codes like [FIELDNAME]
        # We look for patterns that indicate actual data-entry fields
        
        for i, line in enumerate(lines):
            x = line.x0
            y = line.y0
            size = line.size
            text = line.text.strip()
            
            # Field labels are at x~46.5, size ~7.5pt
            if 44 < x < 50 and 7.0 < size < 8.0 and text:
                # Skip technical annotations in brackets or with "SAS Field Name"
                if text.startswith("[") or "SAS Field Name" in text:
                    continue
                
                # Skip empty placeholders like [_|_|_]
                if re.match(r'^\[[\s_|]+\]$', text):
                    continue
                
                # Skip code list references
                if text.startswith("Code List:"):
                    continue
                
                # Skip option markers (O Yes, O No, etc.)
                if text.startswith("O "):
                    continue
                
                # Skip documentation/instruction text (gray color, smaller)
                if line.non_black:
                    continue
                
                # Look ahead to see if this is followed by a bracketed code
                # which indicates it's a field label
                is_field = False
                for j in range(i+1, min(i+5, len(lines))):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # If we find a bracketed code at similar x position, it's a field
                    if 44 < next_line.x0 < 50 and next_text.startswith("[") and next_text.endswith("]"):
                        # Make sure it's not a placeholder like [_|_|_]
                        if not re.match(r'^\[[\s_|]+\]$', next_text):
                            is_field = True
                            break
                    
                    # Stop if we've moved too far down or to a different section
                    if next_line.y0 - y > 30:
                        break
                
                # Also check if there are input indicators nearby (checkboxes, input fields)
                # Look for "O " options or input placeholders at x~249
                has_input = False
                for j in range(max(0, i-3), min(i+10, len(lines))):
                    check_line = lines[j]
                    check_text = check_line.text.strip()
                    
                    # Check for options or input fields at x~249
                    if 245 < check_line.x0 < 255:
                        if check_text.startswith("O ") or re.match(r'^\[[\s_|]+\]$', check_text):
                            # Make sure it's close in y-coordinate
                            if abs(check_line.y0 - y) < 50:
                                has_input = True
                                break
                
                if is_field or has_input:
                    # Clean up the field name
                    field_name = text
                    
                    # Join with next line if it appears to be a continuation
                    # (similar x position, close y position, not a bracket)
                    for j in range(i+1, min(i+3, len(lines))):
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        if (44 < next_line.x0 < 50 and 
                            next_line.y0 - y < 15 and
                            7.0 < next_line.size < 8.0 and
                            not next_text.startswith("[") and
                            not next_text.startswith("O ")):
                            field_name += " " + next_text
                            y = next_line.y0
                        else:
                            break
                    
                    # Skip if it's clearly not a field label
                    if len(field_name) > 200:
                        continue
                    
                    if field_name and form_name:
                        results.append({
                            "form_name": form_name,
                            "field_name": field_name,
                            "page": page_num
                        })
    
    return results
```