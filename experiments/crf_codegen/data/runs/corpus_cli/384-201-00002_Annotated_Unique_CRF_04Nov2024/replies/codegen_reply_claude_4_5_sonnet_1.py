```python
# OBSERVATIONS:
# - Family A (page 1): Title/signature page, no fields
# - Family B (page 2): Simple field layout with left-aligned questions, right-aligned numeric codes
# - Family C (~150 pages): Standard field layout similar to Family B
# - Family D (~249 pages): Data dictionary/specification pages with tabular layout
#   showing field definitions (Field Name, Data Type, Units, Values, etc.) - NOT data-entry fields
# - Form names appear in bold at y≈104 starting with "Form: "
# - Field questions in Families B/C are left-aligned starting at x≈90-95
# - Numeric codes (right-aligned x≈524-527) are technical markers, NOT field names
# - Answer options (Yes/No, rating scales) appear below questions - NOT separate fields

import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from header (bold text at y≈104 starting with "Form: ")
        form_name = ""
        for line in lines:
            if line.bold and 100 <= line.y0 <= 120 and line.text.startswith("Form: "):
                form_name = line.text[6:].strip()
                current_form = form_name
                break
        
        if not form_name and current_form:
            form_name = current_form
        
        # Detect page type by structural signature
        # Family D: Data dictionary pages have "Field Name Data Type" header around y≈155-167
        is_data_dictionary = False
        for line in lines:
            if 150 <= line.y0 <= 170 and "Field Name Data Type" in line.text:
                is_data_dictionary = True
                break
        
        # Skip data dictionary pages - they document field structure, not data-entry fields
        if is_data_dictionary:
            continue
        
        # Skip title/signature pages (Family A)
        has_signature_prompt = any("Signature Prompt" in line.text for line in lines)
        if has_signature_prompt:
            continue
        
        # Extract fields from Families B/C (standard field layout)
        # Fields are questions starting at x≈90-95, y > 140
        # Exclude answer options, page footers, and technical codes
        
        for i, line in enumerate(lines):
            # Skip header area (y < 140)
            if line.y0 < 140:
                continue
            
            # Skip footer area (y > 680)
            if line.y0 > 680:
                continue
            
            # Skip right-aligned numeric codes (x > 520)
            if line.x0 > 520:
                continue
            
            # Skip answer options (Yes/No at x≈489-493)
            if 480 <= line.x0 <= 500 and line.text.strip() in ["Yes", "No"]:
                continue
            
            # Field questions start at left margin (x≈90-110)
            if 85 <= line.x0 <= 110:
                text = line.text.strip()
                
                # Skip empty lines
                if not text:
                    continue
                
                # Skip pure numeric or code-like text
                if re.match(r'^\d+$', text):
                    continue
                
                # Skip category labels that are just single words in all caps without question mark
                if text.isupper() and len(text.split()) == 1 and '?' not in text:
                    continue
                
                # Skip known furniture patterns
                if text in ["Category", "INTENSITY OF IDEATION"]:
                    continue
                
                # Collect wrapped continuation lines (indented at x≈95-100, y close together)
                full_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Continuation: similar x position, y within ~15 points, left side
                    if 90 <= next_line.x0 <= 110 and next_line.y0 - line.y0 < 20 and next_line.x0 < 300:
                        continuation = next_line.text.strip()
                        # Stop if we hit a new field (ends with "?" or starts distinctly)
                        if continuation.endswith('?') or (continuation and continuation[0].isupper() and len(continuation) > 30):
                            break
                        full_text += " " + continuation
                        j += 1
                    else:
                        break
                
                # Final filtering: must look like a field label
                # Should be substantive text (not just numbers/codes)
                if len(full_text) > 5 and not re.match(r'^[\d\s\-:=]+$', full_text):
                    # Skip if it's mostly answer-option-like (single short word + number)
                    if not re.match(r'^\d+[=\s]', full_text):
                        results.append({
                            "form_name": form_name,
                            "field_name": full_text,
                            "page": page_num
                        })
    
    return results
```
