```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from bold "Form: ..." line at y~104
        form_line = None
        for line in lines:
            if line.bold and 100 <= line.y0 <= 120 and line.text.startswith("Form:"):
                form_line = line
                break
        
        if form_line:
            # Extract form name after "Form: "
            form_text = form_line.text
            if form_text.startswith("Form:"):
                current_form = form_text[5:].strip()
        
        # Detect page type by checking for data dictionary table header
        # Family D has "Field Name Data Type" header around y~155-167
        is_dict_page = False
        for line in lines:
            if 150 <= line.y0 <= 170:
                if "Field Name Data Type" in line.text or line.text == "Field Name Data Type":
                    is_dict_page = True
                    break
        
        # Process data dictionary pages (cluster 0)
        if is_dict_page:
            # Extract field names from the data dictionary table
            # Field names appear in left column around x~110, with field codes in right column around x~410
            # Field names are followed by data type in next column
            
            field_candidates = []
            
            for line in lines:
                # Skip header/footer area
                if line.y0 < 180 or line.y0 > 680:
                    continue
                
                # Look for field codes in the right column (x~410)
                # These are uppercase identifiers (e.g., MHYN, PERES, PEDESC)
                if 405 <= line.x0 <= 415:
                    field_code = line.text.strip()
                    # Field codes are typically uppercase letters, may include numbers
                    if re.match(r'^[A-Z][A-Z0-9]{2,}$', field_code):
                        # Now look for the corresponding field name in the left column
                        # Field names appear around x~110 at similar y position
                        for name_line in lines:
                            if 105 <= name_line.x0 <= 115 and abs(name_line.y0 - line.y0) <= 5:
                                field_name = name_line.text.strip()
                                # Skip if it's a data type indicator (e.g., $1, $25, $200)
                                if not re.match(r'^\$\d+$', field_name):
                                    field_candidates.append((line.y0, field_name, field_code))
                                    break
            
            # Add fields from data dictionary
            for y, field_name, field_code in field_candidates:
                # Skip if field name is too short or looks like a code
                if len(field_name) < 2:
                    continue
                
                results.append({
                    "form_name": current_form,
                    "field_name": field_name,
                    "page": page_num
                })
            
            continue
        
        # Extract fields from Family C pages (cluster 1)
        # Fields are left-aligned questions (x~90-95) with field codes on right (x~524-527)
        # Field codes are small numbers (1-2 digits typically)
        
        # Group lines by approximate y-position to handle multi-line labels
        field_candidates = []
        
        for line in lines:
            # Skip header/footer area
            if line.y0 < 140 or line.y0 > 680:
                continue
            
            # Look for left-aligned text (potential field labels)
            if 85 <= line.x0 <= 100:
                # Check if there's a corresponding field code on the right
                # Field codes appear around x~524-527
                has_code = False
                field_code = None
                for code_line in lines:
                    if abs(code_line.y0 - line.y0) <= 5 and 520 <= code_line.x0 <= 530:
                        # Check if it's a small number (field code)
                        if re.match(r'^\d{1,3}$', code_line.text.strip()):
                            has_code = True
                            field_code = code_line.text.strip()
                            break
                
                if has_code:
                    field_candidates.append((line.y0, line.text, line.x0, field_code))
        
        # Group consecutive lines that belong to the same field (multi-line labels)
        if field_candidates:
            field_candidates.sort(key=lambda x: x[0])  # Sort by y position
            
            grouped_fields = []
            current_field_lines = []
            last_y = None
            last_code = None
            
            for y, text, x, code in field_candidates:
                # If this line is close to the previous one (within ~20 points) and has same code, it's a continuation
                if last_y is not None and (y - last_y > 20 or (last_code and code != last_code)):
                    # New field - save previous
                    if current_field_lines:
                        grouped_fields.append(current_field_lines)
                    current_field_lines = [(y, text, x, code)]
                else:
                    current_field_lines.append((y, text, x, code))
                last_y = y
                last_code = code
            
            # Don't forget the last field
            if current_field_lines:
                grouped_fields.append(current_field_lines)
            
            # Process grouped fields
            for field_lines in grouped_fields:
                # Join multi-line labels
                field_text_parts = [text for _, text, _, _ in field_lines]
                field_name = " ".join(field_text_parts).strip()
                
                # Filter out non-field text more carefully
                # Skip if it's ONLY "Yes" or "No" (but allow if part of longer text)
                if field_name in ["Yes", "No"]:
                    continue
                
                # Skip pure numbers or dates (but allow text with numbers)
                if re.match(r'^[\d\s\-/:]+$', field_name):
                    continue
                
                # Skip if too short (likely not a real field label)
                if len(field_name) < 3:
                    continue
                
                # Skip common answer options that appear alone
                # But be careful not to filter valid field labels
                if field_name in ["Category", "Objective", "Subjective"] and len(field_text_parts) == 1:
                    # Only skip if it's a single-line occurrence
                    # Multi-line or longer text should be kept
                    continue
                
                # Skip if it looks like a checkbox option pattern (single word followed by colon or equals)
                if re.match(r'^[A-Z][a-z]+\s*[:=]?\s*$', field_name) and len(field_name) < 15:
                    continue
                
                # Add the field
                results.append({
                    "form_name": current_form,
                    "field_name": field_name,
                    "page": page_num
                })
    
    return results
```