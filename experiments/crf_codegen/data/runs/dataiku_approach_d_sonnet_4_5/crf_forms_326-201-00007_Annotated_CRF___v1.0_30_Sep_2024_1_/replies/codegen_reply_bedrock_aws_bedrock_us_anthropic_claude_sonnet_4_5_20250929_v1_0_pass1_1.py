```python
# This CRF document has a consistent structure across all pages:
# - A "Schedule Category & Name" line at y~93.9 contains the form/section title
# - Field labels are in bold at x=167.7, typically following a timepoint/activity header
# - Answer options (starting with "O") and technical annotations (in brackets) are NOT fields
# - Multi-line field labels wrap and must be joined
# - The form name persists across continuation pages until a new one appears

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
        
        # Find field labels: bold text at x~167.7 that are questions/labels
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels are bold, at x~167.7, size 10, and not blue
            if (line.bold and 
                165 < line.x0 < 170 and 
                9.5 < line.size < 10.5 and
                not line.non_black):
                
                # Skip structural headers
                if line.text in ["Activity", "Answer(s):", "Comment:", "Barcode:"]:
                    i += 1
                    continue
                
                # Skip answer options (start with "O ")
                if line.text.startswith("O "):
                    i += 1
                    continue
                
                # Skip technical annotations in brackets
                if line.text.startswith("[") and line.text.endswith("]"):
                    i += 1
                    continue
                
                # Skip SAS annotations
                if "SAS:[Name=" in line.text:
                    i += 1
                    continue
                
                # Skip open field placeholders
                if line.text.startswith("Open Field "):
                    i += 1
                    continue
                
                # Skip date/time/number input patterns
                if re.match(r'^(Date|Time|Version|Diastolic|No of Units|Yes \(Specify\))', line.text):
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
                        
                        # Check if it's a continuation or new field
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
                
                # Filter out non-field text patterns
                if field_name and len(field_name) > 0:
                    # Skip if it looks like a pure instruction without a question
                    if not any(skip in field_name.lower() for skip in [
                        "sas:[name=", "char. max.)", "(####)", "(##.0)", "(dd-mmm-yyyy)", "(hh:mm)"
                    ]):
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