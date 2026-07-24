# Extraction strategy:
# This CRF document has two main layout families:
# - Family C (~150 pages): Standard field pages with questions/labels on the left (x~90-95) and field codes on the right (x~524-527)
# - Family D (~249 pages): Data dictionary pages with tabular layout showing field metadata (Field Name, Data Type, Units, Values, etc.)
# Family C pages contain actual data-entry fields; Family D pages are reference tables listing field codes/values, not data-entry fields.
# Form names appear in bold at y~104 starting with "Form: ". We extract fields from Family C pages only.
# Fields are identified by their left-aligned question text (x~90-95) with corresponding field codes on the right.

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
        
        # Skip data dictionary pages
        if is_dict_page:
            continue
        
        # Extract fields from Family C pages
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
                for code_line in lines:
                    if abs(code_line.y0 - line.y0) <= 5 and 520 <= code_line.x0 <= 530:
                        # Check if it's a small number (field code)
                        if re.match(r'^\d{1,3}$', code_line.text.strip()):
                            has_code = True
                            break
                
                if has_code:
                    field_candidates.append((line.y0, line.text, line.x0))
        
        # Group consecutive lines that belong to the same field (multi-line labels)
        if field_candidates:
            field_candidates.sort(key=lambda x: x[0])  # Sort by y position
            
            grouped_fields = []
            current_field_lines = []
            last_y = None
            
            for y, text, x in field_candidates:
                # If this line is close to the previous one (within ~15 points), it's a continuation
                if last_y is not None and y - last_y > 20:
                    # New field - save previous
                    if current_field_lines:
                        grouped_fields.append(current_field_lines)
                    current_field_lines = [(y, text, x)]
                else:
                    current_field_lines.append((y, text, x))
                last_y = y
            
            # Don't forget the last field
            if current_field_lines:
                grouped_fields.append(current_field_lines)
            
            # Process grouped fields
            for field_lines in grouped_fields:
                # Join multi-line labels
                field_text_parts = [text for _, text, _ in field_lines]
                field_name = " ".join(field_text_parts).strip()
                
                # Filter out non-field text
                # Skip if it's just answer options (Yes/No patterns)
                if field_name in ["Yes", "No"]:
                    continue
                
                # Skip if it looks like a category label or section header without substance
                if field_name in ["Category", "Objective", "Subjective"]:
                    continue
                
                # Skip pure numbers or dates
                if re.match(r'^[\d\s\-/:]+$', field_name):
                    continue
                
                # Skip if too short (likely not a real field label)
                if len(field_name) < 3:
                    continue
                
                # Add the field
                results.append({
                    "form_name": current_form,
                    "field_name": field_name,
                    "page": page_num
                })
    
    return results
