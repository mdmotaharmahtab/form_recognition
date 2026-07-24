```python
"""
This CRF document contains multiple form types with repeating layouts:
1. Main data-entry forms (pages 2, 234, 304, 409, 434, 461, 512) with form names in bold at y~48.5 and y~73.9,
   followed by field labels in bold with bracketed numbers [N] nearby
2. Variable detail pages (pages 239, 405, 464) showing metadata tables with "Name" column containing field labels
3. The document uses bracketed numbers [N] as technical markers adjacent to field labels

Strategy: Identify form names from bold headers at specific y-ranges; extract field labels as bold text
with bracketed markers nearby (excluding the markers themselves); handle both standard forms and 
variable-detail tables; track form context across pages.
"""

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    seen = set()  # Track (form, field) to avoid duplicates within same context
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Try to identify form name from headers
        # Form names appear as bold text at y~48.5 or as larger text at y~73.9
        form_candidates = []
        for line in lines:
            # Bold header around y=48-49
            if line.bold and 48 <= line.y0 <= 50 and line.size >= 7:
                text = line.text.strip()
                if text and not re.match(r'^\[?\d+\]?$', text) and 'Variable details' not in text:
                    form_candidates.append(text)
            # Larger form title around y=73-74
            elif 73 <= line.y0 <= 75 and line.size >= 15:
                text = line.text.strip()
                if text and text not in ['Visit:', 'Screening']:
                    form_candidates.append(text)
        
        if form_candidates:
            # Use the last/most specific form name found
            current_form = form_candidates[-1]
            seen.clear()  # Reset seen fields for new form
        
        # Check if this is a "Variable details" metadata page
        is_variable_page = any('Variable details' in line.text for line in lines)
        
        if is_variable_page:
            # Extract from "Name" column (x~80.7)
            # These are field definitions, extract the "Name" values
            for line in lines:
                if 75 <= line.x0 <= 85 and line.y0 > 70:
                    text = line.text.strip()
                    # Skip headers and bracketed numbers
                    if text and text != 'Name' and not re.match(r'^\[?\d+\]?$', text):
                        # Check it's not a technical export name (all caps with no spaces typically)
                        if not (text.isupper() and len(text) > 3 and ' ' not in text):
                            key = (current_form, text)
                            if key not in seen:
                                results.append({
                                    "form_name": current_form,
                                    "field_name": text,
                                    "page": page_num
                                })
                                seen.add(key)
        else:
            # Standard form page - extract bold field labels with bracketed markers
            # Build a map of y-positions to bracketed numbers
            bracket_positions = {}
            for line in lines:
                match = re.search(r'\[(\d+)\]', line.text)
                if match:
                    bracket_positions[line.y0] = True
            
            # Extract field labels
            for line in lines:
                if not line.bold or line.y0 < 70:  # Skip headers
                    continue
                
                text = line.text.strip()
                
                # Skip if empty, just a bracket, or common non-field text
                if not text:
                    continue
                if re.match(r'^[\[\]\d\s]+$', text):
                    continue
                if text in ['Yes', 'No', 'Name', 'Export Name', 'Type', 'Max length', 'Categories']:
                    continue
                
                # Remove bracketed numbers from the text
                clean_text = re.sub(r'\s*\[\d+\]\s*', ' ', text).strip()
                if not clean_text:
                    continue
                
                # Skip if it looks like a technical code (short all-caps with numbers)
                if re.match(r'^[A-Z]{3,}\d+[A-Z]?$', clean_text):
                    continue
                
                # Skip option values (single words that are likely choices)
                if clean_text in ['Negative', 'Trace', 'Small', 'Moderate', 'Large', 
                                   'Left', 'Right', 'Performed']:
                    continue
                
                # Check if there's a bracket nearby (within 5 points vertically)
                has_nearby_bracket = False
                for bracket_y in bracket_positions:
                    if abs(line.y0 - bracket_y) <= 5:
                        has_nearby_bracket = True
                        break
                
                # Also check if the line itself contains a bracket
                if '[' in text and ']' in text:
                    has_nearby_bracket = True
                
                # For standard forms, we want bold labels that have bracket markers
                # or are clearly field labels (longer descriptive text)
                if has_nearby_bracket or len(clean_text.split()) >= 2:
                    # Additional filters
                    if clean_text.lower() in ['yes', 'no']:
                        continue
                    
                    # Skip if it's just a number or date-like
                    if re.match(r'^\d+(\.\d+)?$', clean_text):
                        continue
                    
                    key = (current_form, clean_text)
                    if key not in seen:
                        results.append({
                            "form_name": current_form,
                            "field_name": clean_text,
                            "page": page_num
                        })
                        seen.add(key)
    
    return results
```