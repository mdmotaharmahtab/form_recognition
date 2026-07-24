```python
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
        # Field labels appear at x~46.5, size ~7.5pt
        # They are followed by bracketed field codes like [FIELDNAME]
        
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
                # The code may appear immediately after or several lines below
                is_field = False
                for j in range(i+1, min(i+15, len(lines))):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # If we find a bracketed code at similar x position, it's a field
                    if 44 < next_line.x0 < 50 and next_text.startswith("[") and next_text.endswith("]"):
                        # Make sure it's not a placeholder like [_|_|_]
                        if not re.match(r'^\[[\s_|]+\]$', next_text):
                            # Check if it's a field code (not SAS Field Name)
                            if "SAS Field Name" not in next_text:
                                is_field = True
                                break
                    
                    # Stop if we've moved to a completely different section
                    # (different x position or too far down)
                    if next_line.x0 < 44 or next_line.x0 > 260:
                        if next_line.y0 - y > 50:
                            break
                
                # Also check if there are input indicators nearby (checkboxes, input fields)
                # Look for "O " options or input placeholders at x~249
                has_input = False
                for j in range(max(0, i-3), min(i+15, len(lines))):
                    check_line = lines[j]
                    check_text = check_line.text.strip()
                    
                    # Check for options or input fields at x~249
                    if 245 < check_line.x0 < 255:
                        if check_text.startswith("O ") or re.match(r'^\[[\s_|]+\]$', check_text):
                            # Make sure it's close in y-coordinate
                            if abs(check_line.y0 - y) < 80:
                                has_input = True
                                break
                
                if is_field or has_input:
                    # Clean up the field name
                    field_name = text
                    
                    # Join with next line if it appears to be a continuation
                    # (similar x position, close y position, not a bracket)
                    for j in range(i+1, min(i+5, len(lines))):
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        if (44 < next_line.x0 < 50 and 
                            next_line.y0 - y < 15 and
                            7.0 < next_line.size < 8.0 and
                            not next_text.startswith("[") and
                            not next_text.startswith("O ") and
                            not next_line.non_black):
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
        
        # NEW: Extract fields from the right column (metadata area)
        # These appear at x~453-456, size ~5.6pt, and are bold field codes
        # The actual field label is in the left column, but we need to extract
        # fields that only appear in the right metadata area
        
        # Look for bold field codes in the right column
        for i, line in enumerate(lines):
            x = line.x0
            y = line.y0
            size = line.size
            text = line.text.strip()
            
            # Field codes in right column: x~453-456, size ~5.6pt, bold
            if 450 < x < 460 and 5.0 < size < 6.5 and line.bold and text:
                # Skip if it's not a field code pattern (usually uppercase, no spaces)
                if not re.match(r'^[A-Z][A-Z0-9]{2,}$', text):
                    continue
                
                # Skip common metadata labels
                if text in ["Format", "Data", "Type", "Origin", "CRF", "Description", 
                            "Mandatory", "Disallow", "Future", "Date", "Yes", "No",
                            "Aliases", "Odm", "OID", "Edit", "Checks", "Name",
                            "Formal", "Expression", "Context", "Range", "Units",
                            "SDS", "Var", "Device", "Parameter", "Conditionally",
                            "Visible", "Conditional", "Item", "If", "Value"]:
                    continue
                
                # This is likely a field code - now find the corresponding label
                # Look backwards and to the left for the field label
                field_label = None
                
                # Search in the left column for a label near this y-coordinate
                for j in range(max(0, i-20), min(i+5, len(lines))):
                    check_line = lines[j]
                    check_text = check_line.text.strip()
                    check_x = check_line.x0
                    check_y = check_line.y0
                    
                    # Look for text in the left column (x~46.5)
                    if 44 < check_x < 50 and 7.0 < check_line.size < 8.0:
                        # Check if y-coordinate is close
                        if abs(check_y - y) < 100:
                            # Skip brackets and technical text
                            if (not check_text.startswith("[") and 
                                not check_text.startswith("O ") and
                                "SAS Field Name" not in check_text and
                                "Code List:" not in check_text and
                                not re.match(r'^\[[\s_|]+\]$', check_text) and
                                not check_line.non_black):
                                
                                # Build multi-line label if needed
                                label_parts = [check_text]
                                label_y = check_y
                                
                                # Look for continuation lines
                                for k in range(j+1, min(j+5, len(lines))):
                                    cont_line = lines[k]
                                    cont_text = cont_line.text.strip()
                                    
                                    if (44 < cont_line.x0 < 50 and
                                        cont_line.y0 - label_y < 15 and
                                        7.0 < cont_line.size < 8.0 and
                                        not cont_text.startswith("[") and
                                        not cont_text.startswith("O ") and
                                        not cont_line.non_black):
                                        label_parts.append(cont_text)
                                        label_y = cont_line.y0
                                    else:
                                        break
                                
                                field_label = " ".join(label_parts)
                                break
                
                # If we found a label, add it
                if field_label and form_name and len(field_label) < 200:
                    # Check if we haven't already added this field
                    already_added = False
                    for existing in results:
                        if (existing["page"] == page_num and 
                            existing["form_name"] == form_name and
                            existing["field_name"] == field_label):
                            already_added = True
                            break
                    
                    if not already_added:
                        results.append({
                            "form_name": form_name,
                            "field_name": field_label,
                            "page": page_num
                        })
    
    return results
```