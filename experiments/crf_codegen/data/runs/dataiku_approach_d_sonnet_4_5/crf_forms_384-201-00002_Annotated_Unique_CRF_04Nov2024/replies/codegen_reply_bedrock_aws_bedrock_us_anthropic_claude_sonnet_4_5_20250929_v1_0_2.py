Looking at the issues, I can see that:

1. **Cluster 0 (249 pages)** are data dictionary pages that I'm correctly skipping - they show field metadata, not data-entry fields
2. **Cluster 1 (150 pages)** are extracting well (99% coverage)
3. **Page 4** has a missing field "Check all that apply" that needs to be captured
4. **Clusters 2 and 3** (4 pages total) need investigation

The main issue is that my current logic filters out some valid field labels. I need to be less aggressive in filtering while still avoiding answer options and codes.

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