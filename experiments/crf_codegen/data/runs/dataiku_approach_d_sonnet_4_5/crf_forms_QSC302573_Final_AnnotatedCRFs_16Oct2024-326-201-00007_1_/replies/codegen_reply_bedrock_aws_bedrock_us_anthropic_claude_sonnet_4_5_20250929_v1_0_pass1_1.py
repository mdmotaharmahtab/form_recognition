```python
# This CRF document has a consistent structure across all pages:
# - A "Schedule Category & Name:" line at y≈93.9 contains the form/section title
# - Field labels are in bold at x=167.7, typically following a timepoint/activity header
# - Answer options (starting with "O" or checkboxes) and SAS codes are NOT fields
# - Multi-line labels need to be joined into single field_name values
# Strategy: Extract the schedule name as form_name, identify field labels by their
# bold formatting at x≈167.7, skip answer options and technical annotations.

import re
from typing import List, Dict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name:" line
        form_name = ""
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Next line should contain the actual schedule name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Extract everything after the comma and code
                    match = re.search(r',\s*(.+)$', next_line.text)
                    if match:
                        form_name = match.group(1).strip()
                break
        
        # Find field labels - they are bold lines at x≈167.7 that are questions/labels
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels are bold, at x≈167.7, and not in specific excluded categories
            if (line.bold and 
                165 <= line.x0 <= 170 and 
                line.size >= 9.5 and
                line.text.strip()):
                
                text = line.text.strip()
                
                # Skip structural headers
                if text in ["Timepoint", "Activity", "Answer(s):", "Comment:"]:
                    i += 1
                    continue
                
                # Skip answer options (lines starting with O or checkboxes)
                if re.match(r'^O\s+', text) or text.startswith('[ ]'):
                    i += 1
                    continue
                
                # Skip SAS codes (lines with [VARNAME] pattern)
                if re.match(r'^\[[\w_]+\]', text):
                    i += 1
                    continue
                
                # Skip lines that are just underscores/placeholders
                if re.match(r'^[_\s\-:#\.]+$', text):
                    i += 1
                    continue
                
                # Skip lines that look like input formats
                if re.match(r'^(dd|MMM|yyyy|HH|mm|Time|Date|Version|#)', text):
                    i += 1
                    continue
                
                # This looks like a field label - collect continuation lines
                field_parts = [text]
                j = i + 1
                
                # Look ahead for continuation lines (same x position, bold, not answer options)
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop if we hit a different structural element
                    if next_line.text.strip() in ["Staff Initials:", "Answer(s):", "Comment:"]:
                        break
                    
                    # Stop if we hit answer options
                    if re.match(r'^O\s+', next_line.text.strip()):
                        break
                    
                    # Stop if we hit SAS codes
                    if re.match(r'^\[[\w_]+\]', next_line.text.strip()):
                        break
                    
                    # Continuation line: bold, similar x position
                    if (next_line.bold and 
                        165 <= next_line.x0 <= 170 and
                        next_line.size >= 9.5 and
                        next_line.text.strip() and
                        not re.match(r'^[_\s\-:#\.]+$', next_line.text.strip()) and
                        not re.match(r'^(dd|MMM|yyyy|HH|mm)', next_line.text.strip())):
                        field_parts.append(next_line.text.strip())
                        j += 1
                    else:
                        break
                
                # Join the parts into a complete field name
                field_name = " ".join(field_parts)
                
                # Final validation: skip if it looks like a technical annotation
                if not re.match(r'^\*\*', field_name):  # Skip **OPERATOR notes
                    results.append({
                        "form_name": form_name,
                        "field_name": field_name,
                        "page": page_num
                    })
                
                # Move past the lines we've processed
                i = j
            else:
                i += 1
    
    return results
```