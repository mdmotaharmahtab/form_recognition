```python
# This document contains clinical trial CRF pages with a specific layout:
# - Blue bold headers ("Annotated CRF") at top
# - Schedule category/name below headers
# - Activities listed with bold labels/questions at x~167.7, preceded by timepoint/date fields
# - Each activity has a Line # on right side
# Strategy: Extract activities (bold text at x~167.7) as field_name, use Schedule name as form_name.
# Skip answer options, codes in brackets, staff/comment prompts, and rating scale choices.

import re
from typing import List, Dict, Any

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Check if this page matches our layout (has "Annotated CRF" header in blue bold)
        has_header = False
        for line in lines[:10]:  # Check first few lines
            if "Annotated CRF" in line.text and line.bold and line.non_black:
                has_header = True
                break
        
        if not has_header:
            continue
        
        # Extract form name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Next line or same line should have the actual name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # The form name appears after the label, not in blue
                    if not next_line.non_black and "QSC" in next_line.text:
                        current_form = next_line.text.strip()
                        break
                # Check if it's on the same line after the label
                if "QSC" in line.text:
                    parts = line.text.split(":", 1)
                    if len(parts) > 1:
                        current_form = parts[1].strip()
                        break
        
        # Extract field names - these are bold lines around x~167
        # that are NOT headers, answers, or system annotations
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels are bold, at x position ~167, size 10, and are questions/labels
            if (line.bold and 
                160 < line.x0 < 175 and 
                9.5 < line.size < 11 and
                not line.non_black):  # Fields are black, not blue
                
                text = line.text.strip()
                
                # Skip headers, staff/comment prompts, answer labels
                if text in ("Activity", "Timepoint", "Line #", "Staff Initials:", 
                           "Comment:", "Answer(s):"):
                    i += 1
                    continue
                
                # Skip system codes/annotations in brackets
                if text.startswith("[") or "SAS:[Name=" in text:
                    i += 1
                    continue
                
                # This looks like a field label - collect continuation lines
                field_parts = [text]
                j = i + 1
                
                # Look ahead for continuation lines (same x position, bold, black)
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Continuation line criteria: bold, similar x position, not a new field
                    if (next_line.bold and 
                        160 < next_line.x0 < 175 and 
                        9.5 < next_line.size < 11 and
                        not next_line.non_black):
                        
                        next_text = next_line.text.strip()
                        
                        # Stop if we hit another field marker or prompt
                        if (next_text in ("Staff Initials:", "Comment:", "Answer(s):") or
                            next_text.startswith("Day ") or
                            re.match(r"^[A-Z][a-zA-Z\s]+:#?\d+$", next_text)):
                            break
                        
                        # Skip bracket annotations
                        if not (next_text.startswith("[") or "SAS:[Name=" in next_text):
                            field_parts.append(next_text)
                        j += 1
                    else:
                        break
                
                # Combine all parts into field name
                field_name = " ".join(field_parts)
                
                # Final validation - must be a real question/label
                if (field_name and 
                    len(field_name) > 3 and
                    not field_name.startswith("O ") and  # Not an option
                    not re.match(r"^[O\d\s\-X]+$", field_name)):  # Not just option markers
                    
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
