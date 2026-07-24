```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Check if this is a code-list page (skip it)
        is_codelist = False
        for line in lines:
            if line.y0 < 70 and "Coded" in line.text and "Decode" in line.text:
                is_codelist = True
                break
        if is_codelist:
            continue
        
        # Extract form name from white header bar
        for line in lines:
            if (line.size >= 11.5 and line.size <= 12.5 and 
                line.non_black and line.y0 >= 30 and line.y0 <= 40 and
                line.x0 < 100 and len(line.text.strip()) > 3):
                # This is likely the form name
                text = line.text.strip()
                # Skip if it looks like metadata
                if not any(kw in text.lower() for kw in ['origin:', 'aliases:', 'mapping']):
                    current_form = text
                    break
        
        # Now extract fields
        # Fields are typically at x ~43-50, with checkboxes or input patterns following
        # But some fields may be at x ~60-80 or other positions
        # EXTENSION: Some fields may be at x ~100-150 (wider range)
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for field labels: x between 40-150 (expanded range), size 7-11, not too high on page
            if (40 <= line.x0 <= 150 and 7 <= line.size <= 11 and 
                line.y0 > 70 and not line.non_black):
                
                text = line.text.strip()
                
                # Skip if empty or too short
                if len(text) < 2:
                    i += 1
                    continue
                
                # Skip technical codes in brackets
                if text.startswith('[') and text.endswith(']'):
                    i += 1
                    continue
                
                # Skip "Code List:" lines
                if text.startswith('Code List:'):
                    i += 1
                    continue
                
                # Skip option values (lines starting with O at x~249)
                if text.startswith('O '):
                    i += 1
                    continue
                
                # Skip date/time format patterns
                if re.match(r'^\[?[_\|\[\]:\-\s]+\]?$', text):
                    i += 1
                    continue
                
                # Skip lines that are just format codes like "dd-MMM-yyyy"
                if re.match(r'^[a-zA-Z\-:]+$', text) and len(text) < 25 and '-' in text:
                    i += 1
                    continue
                
                # Check if next few lines contain checkboxes or input patterns
                # Also check the same line for checkboxes/inputs
                has_checkbox = False
                has_input = False
                
                # Check same line first
                for j in range(i, min(i+1, len(lines))):
                    same_line = lines[j]
                    # Look for checkboxes or inputs anywhere on the same line or nearby
                    for k in range(max(0, j-1), min(j+5, len(lines))):
                        next_line = lines[k]
                        # Check if y positions are close (same line or nearby)
                        if abs(next_line.y0 - line.y0) < 15:
                            if next_line.x0 > line.x0 + 10:  # To the right of the label
                                if 'O ' in next_line.text or next_line.text.strip().startswith('O '):
                                    has_checkbox = True
                                if '[_|_]' in next_line.text or '___' in next_line.text:
                                    has_input = True
                
                # Also check lines below
                for j in range(i+1, min(i+5, len(lines))):
                    next_line = lines[j]
                    if next_line.x0 > 240 and next_line.x0 < 260:
                        if next_line.text.strip().startswith('O '):
                            has_checkbox = True
                        if '[_|_]' in next_line.text or '___' in next_line.text:
                            has_input = True
                
                # EXTENSION: Also check for checkboxes at wider x ranges (e.g., x > 200)
                for j in range(i, min(i+5, len(lines))):
                    next_line = lines[j]
                    if abs(next_line.y0 - line.y0) < 20:
                        if next_line.x0 > 200:
                            if 'O ' in next_line.text or next_line.text.strip().startswith('O '):
                                has_checkbox = True
                            if '[_|_]' in next_line.text or '___' in next_line.text:
                                has_input = True
                
                # This looks like a field label if it has associated input elements
                if has_checkbox or has_input:
                    # Clean up the text
                    field_text = text
                    
                    # For numbered criteria (inclusion/exclusion), extract the full text
                    if re.match(r'^\d+\.', field_text):
                        # Collect continuation lines
                        full_text = field_text
                        for j in range(i+1, min(i+10, len(lines))):
                            next_line = lines[j]
                            if (40 <= next_line.x0 <= 150 and 
                                not next_line.text.strip().startswith('[') and
                                not next_line.text.strip().startswith('O ') and
                                next_line.y0 < line.y0 + 100):
                                # Check if it's a continuation (not a new field)
                                nt = next_line.text.strip()
                                if not re.match(r'^\d+\.', nt) and len(nt) > 0:
                                    full_text += ' ' + nt
                                else:
                                    break
                            else:
                                break
                        field_text = full_text
                    
                    # Clean up whitespace
                    field_text = ' '.join(field_text.split())
                    
                    # Skip if it looks like a code
                    if re.match(r'^[A-Z]{2,}[0-9]{3,}$', field_text):
                        i += 1
                        continue
                    
                    if current_form and len(field_text) > 2:
                        results.append({
                            "form_name": current_form,
                            "field_name": field_text,
                            "page": page_num
                        })
            
            i += 1
    
    return results
```