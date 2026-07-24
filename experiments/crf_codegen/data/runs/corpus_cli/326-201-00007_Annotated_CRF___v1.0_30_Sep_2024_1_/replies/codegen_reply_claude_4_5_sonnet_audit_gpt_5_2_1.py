```python
# LAYOUT OBSERVATION:
# This is a clinical CRF with a standard template across all pages. Each page has a header 
# showing "Schedule Category & Name" at y~93.9 sz=11 (non-bold), followed by a table-like
# structure with "Activity" labels (sz=10, bold, x~167.7) that describe data-entry fields.
# Fields span multiple lines with the question/label starting at x~167.7, y-coordinates
# increasing downward. Answer options (starting with "O") and SAS annotations are NOT fields.
# Form names persist across pages and are found in the "Schedule Category & Name" line.

import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form_name from "Schedule Category & Name:" line
        form_name = ""
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Form name is typically on the same line after the label or next line
                if i + 1 < len(lines):
                    candidate = lines[i + 1].text.strip()
                    # Check if form name is on same line (after the label)
                    parts = line.text.split("Schedule Category & Name:")
                    if len(parts) > 1 and parts[1].strip():
                        form_name = parts[1].strip()
                    elif candidate and not candidate.startswith(("Timepoint", "Activity", "Line")):
                        form_name = candidate
                break
        
        # Extract fields: look for Activity labels (bold, x~167.7, not "Activity" header itself)
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels are bold, at x~167.7, sz~10, and not in answer/annotation zones
            if (line.bold and 
                160 < line.x0 < 175 and 
                9 < line.size < 11.5 and
                line.y0 > 120):  # Below header zone
                
                # Skip structural headers
                if line.text.strip() in ("Activity", "Answer(s):", "Comment:", "Barcode:"):
                    i += 1
                    continue
                
                # Skip answer options (lines starting with "O " or "[")
                text = line.text.strip()
                if text.startswith("O ") or text.startswith("["):
                    i += 1
                    continue
                
                # Skip date/time format placeholders
                if re.match(r'^[_\s\-:]+$', text) or text in ("dd - MMM - yyyy", "HH:mm"):
                    i += 1
                    continue
                
                # Skip lines that are purely technical annotations (SAS codes)
                if text.startswith("SAS:[") or "DataType=" in text:
                    i += 1
                    continue
                
                # Potential field label - collect wrapped lines
                field_parts = [text]
                j = i + 1
                
                # Collect continuation lines (similar x position, consecutive y, bold, not answer options)
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop at answer section or next field
                    if next_line.text.strip() in ("Staff Initials:", "Answer(s):", "Comment:", "Barcode:"):
                        break
                    
                    # Stop at answer options
                    if next_line.text.strip().startswith("O "):
                        break
                    
                    # Stop at SAS annotations
                    if next_line.text.strip().startswith("[") and "SAS:" in next_line.text:
                        break
                    
                    # Continuation must be at similar x, bold, reasonably close in y
                    if (next_line.bold and 
                        160 < next_line.x0 < 175 and
                        9 < next_line.size < 11.5 and
                        next_line.y0 - lines[j-1].y0 < 20):
                        
                        cont_text = next_line.text.strip()
                        # Skip format placeholders and annotations
                        if (not re.match(r'^[_\s\-:]+$', cont_text) and
                            cont_text not in ("dd - MMM - yyyy", "HH:mm") and
                            not cont_text.startswith("[")):
                            field_parts.append(cont_text)
                        j += 1
                    else:
                        break
                
                # Join wrapped lines into complete field name
                field_name = " ".join(field_parts).strip()
                
                # Filter out non-field text
                if (field_name and 
                    not field_name.startswith("O ") and
                    not re.match(r'^[_\s\-:]+$', field_name) and
                    field_name not in ("dd - MMM - yyyy", "HH:mm") and
                    len(field_name) > 5):  # Minimum reasonable length
                    
                    results.append({
                        "form_name": form_name,
                        "field_name": field_name,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return results
```
