```python
# Layout observation:
# - Pages 1-2 have a title row ("Annotated CRF") followed by study metadata and a repeating
#   pattern of activities. Each activity has a bold line at x≈167.7 (the question/field label)
#   that may wrap across multiple lines, preceded by timepoint/line# metadata.
# - Pages 3+ (cluster starting at page 27) follow the same structure but omit some metadata rows.
# - Form names appear in "Schedule Category & Name:" as the second part after the comma.
# - Field labels are bold lines at x≈167.7; continuation lines (same x, not bold or different
#   formatting) should be joined. Lines with "[QSORRES]", "SAS:[", answer options (O prefix),
#   date/time templates, "Staff Initials:", "Answer(s):", "Comment:" are not field labels.
# Strategy: track form_name from "Schedule Category & Name:", identify activity blocks by
# bold lines at x≈167.7, join wrapped label lines, filter out answer options and metadata.

import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Next line should contain the form info
                if i + 1 < len(lines):
                    form_text = lines[i + 1].text.strip()
                    # Form name is after the comma
                    if "," in form_text:
                        current_form = form_text.split(",", 1)[1].strip()
                break
        
        # Identify activity/field blocks
        # Field labels are bold, at x≈167.7, and start an activity block
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check if this is a potential field label line
            # Bold, x coordinate around 167.7 (±10 for tolerance)
            if line.bold and 157 < line.x0 < 178:
                text = line.text.strip()
                
                # Skip known metadata/structural lines
                if any(skip in text for skip in [
                    "Timepoint", "Activity", "Line #", "Answer(s):", 
                    "Staff Initials:", "Comment:", "Annotated CRF"
                ]):
                    i += 1
                    continue
                
                # Skip lines that look like answer options (start with O)
                if text.startswith("O "):
                    i += 1
                    continue
                
                # Skip lines with SAS annotations
                if "[" in text and "]" in text and "SAS:" in text:
                    i += 1
                    continue
                
                # Skip date/time templates
                if re.match(r'^[_\s:-]+$', text) or text in ["dd - MMM - yyyy", "HH:mm"]:
                    i += 1
                    continue
                
                # Skip bare line numbers (e.g., "1.0", "2.0 (hidden)")
                if re.match(r'^\d+\.\d+(\s*\(hidden\))?$', text):
                    i += 1
                    continue
                
                # This looks like a field label - collect wrapped lines
                field_parts = [text]
                j = i + 1
                
                # Look ahead for continuation lines (same x, may not be bold)
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Continuation lines should have similar x coordinate
                    if 157 < next_line.x0 < 178:
                        next_text = next_line.text.strip()
                        
                        # Stop at structural markers
                        if any(marker in next_text for marker in [
                            "Staff Initials:", "Answer(s):", "Comment:",
                            "Timepoint", "Activity", "Line #"
                        ]):
                            break
                        
                        # Stop at SAS annotations
                        if "[" in next_text and "]" in next_text and "SAS:" in next_text:
                            break
                        
                        # Stop at answer options
                        if next_text.startswith("O "):
                            break
                        
                        # Stop at date/time templates
                        if next_text in ["dd - MMM - yyyy", "HH:mm"]:
                            break
                        
                        # Stop at blank or very short lines (likely spacing)
                        if len(next_text) < 3:
                            break
                        
                        # Stop at lines that start a new timepoint
                        if re.match(r'^Day \d+', next_text):
                            break
                        
                        # This is a continuation line
                        field_parts.append(next_text)
                        j += 1
                    else:
                        break
                
                # Join the field parts into a complete field name
                field_name = " ".join(field_parts).strip()
                
                # Final validation: must be substantial text
                if len(field_name) > 5 and not re.match(r'^\d+\.?\d*$', field_name):
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
