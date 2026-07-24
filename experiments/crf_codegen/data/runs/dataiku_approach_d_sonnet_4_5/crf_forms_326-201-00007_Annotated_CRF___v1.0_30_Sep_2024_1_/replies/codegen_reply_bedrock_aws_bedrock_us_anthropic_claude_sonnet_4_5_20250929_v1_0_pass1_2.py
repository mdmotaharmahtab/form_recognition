```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if line.text.startswith("Schedule Category & Name:"):
                # Next line contains the form name
                if i + 1 < len(lines):
                    form_text = lines[i + 1].text.strip()
                    # Remove leading code like "QSC302573, "
                    if ", " in form_text:
                        current_form = form_text.split(", ", 1)[1]
                    else:
                        current_form = form_text
                break
        
        # Build a map of y-coordinates to detect section headers
        # Section headers appear at x~93 (left margin), bold, and are followed by fields
        section_headers_y = set()
        for line in lines:
            # Section headers: bold, left-aligned (x < 100), size ~10
            if (line.bold and line.x0 < 100 and 9.5 < line.size < 10.5 and 
                not line.non_black and ":" in line.text and "#" in line.text):
                section_headers_y.add(round(line.y0, 1))
        
        # Find field labels: bold text at x~167.7 that are questions/labels
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels are bold, at x~167.7, size 10, and not blue
            if (line.bold and 
                165 < line.x0 < 170 and 
                9.5 < line.size < 10.5 and
                not line.non_black):
                
                # Skip if this line is actually a section header (contains "#" and ":")
                # These appear at the same x position but are structural markers
                if "#" in line.text and ":" in line.text:
                    # Check if it matches the pattern "Section Name: Subsection #N"
                    # or "Section: Subsection Name #N"
                    if re.search(r'#\d+\s*$', line.text):
                        i += 1
                        continue
                
                # Skip standard structural headers
                if line.text in ["Activity", "Answer(s):", "Comment:", "Barcode:"]:
                    i += 1
                    continue
                
                # Skip answer options (start with "O ")
                if line.text.startswith("O "):
                    i += 1
                    continue
                
                # Skip technical annotations in brackets at start of line
                if line.text.startswith("[") and "]" in line.text:
                    i += 1
                    continue
                
                # Skip SAS annotations
                if "SAS:[Name=" in line.text:
                    i += 1
                    continue
                
                # Skip open field placeholders that are just input format indicators
                if re.match(r'^Open Field \(', line.text):
                    i += 1
                    continue
                
                # Skip pure input format indicators (no question text)
                # These are lines that ONLY contain format specs like dates, times, numbers
                if re.match(r'^(Date|Time|Version|Diastolic|No of Units|Yes \(Specify\))\s*$', line.text):
                    i += 1
                    continue
                
                # Skip lines that are only parenthetical notes/instructions
                # (starting with "(" and containing only technical info)
                if line.text.startswith("(") and line.text.endswith(")"):
                    # Check if it's a pure instruction without question context
                    if any(pattern in line.text.lower() for pattern in [
                        "supine for at least", "version must be checked", 
                        "if 'yes' exclude", "ecg"
                    ]):
                        i += 1
                        continue
                
                # This is a potential field label - collect continuation lines
                field_parts = [line.text]
                j = i + 1
                
                # Look ahead for continuation lines (same x position, bold, not answer options)
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop at next field or structural element
                    if (next_line.bold and 165 < next_line.x0 < 170 and 
                        9.5 < next_line.size < 10.5 and not next_line.non_black):
                        
                        # Check if it's a section header (has # and ends with number)
                        if "#" in next_line.text and re.search(r'#\d+\s*$', next_line.text):
                            break
                        
                        # Check if it's a structural marker
                        if (next_line.text in ["Answer(s):", "Comment:", "Barcode:"] or
                            next_line.text.startswith("O ") or
                            next_line.text.startswith("[") or
                            "SAS:[Name=" in next_line.text):
                            break
                        
                        # It's a continuation line
                        field_parts.append(next_line.text)
                        j += 1
                    else:
                        break
                
                # Join the field label parts
                field_name = " ".join(field_parts).strip()
                
                # Final validation: must look like a real field
                # Real fields typically:
                # 1. Are questions (contain "?" or imperative verbs)
                # 2. Or are noun phrases requesting data entry
                # 3. Are not pure parenthetical instructions
                
                # Skip if the entire field is just a parenthetical note
                if field_name.startswith("(") and field_name.endswith(")"):
                    i = j
                    continue
                
                # Skip if it's just a format indicator with no question
                if re.match(r'^(Date|Time|Version|Diastolic|No of Units)\s*$', field_name):
                    i = j
                    continue
                
                # Add the field
                if field_name and len(field_name) > 0:
                    results.append({
                        "form_name": current_form,
                        "field_name": field_name,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return results
```