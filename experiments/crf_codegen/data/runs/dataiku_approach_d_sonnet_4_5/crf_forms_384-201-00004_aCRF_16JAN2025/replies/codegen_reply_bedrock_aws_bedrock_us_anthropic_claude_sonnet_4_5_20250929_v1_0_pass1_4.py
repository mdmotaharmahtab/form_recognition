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
            if 32 < line.y0 < 38 and 11 < line.size < 13:
                text = line.text.strip()
                # White text on colored background is the form title
                if line.non_black and text and not text.startswith("384-201"):
                    form_name = text
                    break
        
        # Skip pages without a form name (title pages, reference tables)
        if not form_name:
            continue
        
        # Detect reference/code list tables (Family B) by structure:
        # They have "Coded" and "Decode" as bold column headers at y~59-60
        is_reference_table = False
        coded_header = False
        decode_header = False
        for line in lines:
            if 58 < line.y0 < 62 and line.bold:
                text = line.text.strip()
                if text == "Coded":
                    coded_header = True
                elif text == "Decode":
                    decode_header = True
        
        if coded_header and decode_header:
            is_reference_table = True
        
        if is_reference_table:
            continue
        
        # Extract fields from the left column (main data entry area)
        # Field labels appear at x~46.5, size ~7.5pt, black text
        # They are typically followed by bracketed field codes like [FIELDNAME]
        
        for i, line in enumerate(lines):
            x = line.x0
            y = line.y0
            size = line.size
            text = line.text.strip()
            
            # Field labels are in the left column at x~46.5, size ~7.5pt
            if 44 < x < 52 and 7.0 < size < 8.5 and text and not line.non_black:
                # Skip bracketed codes themselves
                if text.startswith("[") and text.endswith("]"):
                    continue
                
                # Skip option markers (radio buttons, checkboxes)
                if text.startswith("O "):
                    continue
                
                # Skip empty placeholders
                if re.match(r'^\[[\s_|]+\]$', text):
                    continue
                
                # Look ahead to see if this is followed by a bracketed field code
                # The code typically appears within the next 15 lines
                has_field_code = False
                for j in range(i+1, min(i+15, len(lines))):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Look for bracketed code at similar x position
                    if 44 < next_line.x0 < 52:
                        # Check if it's a field code pattern [FIELDNAME]
                        if next_text.startswith("[") and next_text.endswith("]"):
                            # Not an empty placeholder
                            if not re.match(r'^\[[\s_|]+\]$', next_text):
                                # Not a SAS field name annotation
                                if "SAS Field Name" not in next_text:
                                    has_field_code = True
                                    break
                    
                    # Stop if we've moved too far down or to a different column
                    if next_line.y0 - y > 60:
                        break
                
                # Also check for input indicators nearby (input fields, checkboxes)
                # These appear at x~249 (right side of left column)
                has_input_indicator = False
                for j in range(max(0, i-3), min(i+15, len(lines))):
                    check_line = lines[j]
                    check_text = check_line.text.strip()
                    
                    # Input fields or checkboxes at x~249
                    if 245 < check_line.x0 < 260:
                        # Check for option markers or input placeholders
                        if check_text.startswith("O ") or re.match(r'^\[[\s_|]+\]$', check_text):
                            # Must be close in y-coordinate
                            if abs(check_line.y0 - y) < 100:
                                has_input_indicator = True
                                break
                
                if has_field_code or has_input_indicator:
                    # Build the complete field label
                    field_name = text
                    
                    # Join with continuation lines if they exist
                    # Continuation lines have similar x position, close y, same size
                    for j in range(i+1, min(i+6, len(lines))):
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        if (44 < next_line.x0 < 52 and 
                            next_line.y0 - y < 15 and
                            7.0 < next_line.size < 8.5 and
                            not next_text.startswith("[") and
                            not next_text.startswith("O ") and
                            not next_line.non_black):
                            field_name += " " + next_text
                            y = next_line.y0
                        else:
                            break
                    
                    # Skip if it's unreasonably long (likely not a field label)
                    if len(field_name) > 250:
                        continue
                    
                    # Skip structural annotations by pattern
                    # Code List references appear as "Code List: ..." in gray
                    if field_name.startswith("Code List:"):
                        continue
                    
                    # Skip if it looks like a comment annotation (starts with "Comment:")
                    if field_name.startswith("Comment:"):
                        continue
                    
                    # Skip if it looks like a description annotation
                    if field_name.startswith("Description:"):
                        continue
                    
                    if field_name and form_name:
                        results.append({
                            "form_name": form_name,
                            "field_name": field_name,
                            "page": page_num
                        })
        
        # Extract fields from the right metadata column
        # Some fields only appear as bold codes in the right column at x~453-456
        # These need to be matched with their labels in the left column
        
        for i, line in enumerate(lines):
            x = line.x0
            y = line.y0
            size = line.size
            text = line.text.strip()
            
            # Field codes in right column: x~453-456, size ~5.6pt, bold
            if 450 < x < 460 and 5.0 < size < 6.5 and line.bold and text:
                # Check if it matches a field code pattern (uppercase, alphanumeric)
                if not re.match(r'^[A-Z][A-Z0-9]{2,}$', text):
                    continue
                
                # Skip metadata labels (structural annotations)
                # These are identified by position and context, not literal text
                # They typically appear as standalone bold words in specific positions
                
                # Look for the corresponding field label in the left column
                field_label = None
                
                # Search backwards and in the left column for a label near this y-coordinate
                for j in range(max(0, i-25), min(i+8, len(lines))):
                    check_line = lines[j]
                    check_text = check_line.text.strip()
                    check_x = check_line.x0
                    check_y = check_line.y0
                    
                    # Look for text in the left column (x~46.5)
                    if 44 < check_x < 52 and 7.0 < check_line.size < 8.5:
                        # Check if y-coordinate is reasonably close
                        if abs(check_y - y) < 120:
                            # Skip structural elements
                            if (not check_text.startswith("[") and 
                                not check_text.startswith("O ") and
                                not check_text.startswith("Code List:") and
                                not check_text.startswith("Comment:") and
                                not check_text.startswith("Description:") and
                                not re.match(r'^\[[\s_|]+\]$', check_text) and
                                not check_line.non_black):
                                
                                # Build multi-line label if needed
                                label_parts = [check_text]
                                label_y = check_y
                                
                                # Look for continuation lines
                                for k in range(j+1, min(j+6, len(lines))):
                                    cont_line = lines[k]
                                    cont_text = cont_line.text.strip()
                                    
                                    if (44 < cont_line.x0 < 52 and
                                        cont_line.y0 - label_y < 15 and
                                        7.0 < cont_line.size < 8.5 and
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
                if field_label and form_name and len(field_label) < 250:
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