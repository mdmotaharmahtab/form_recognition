```python
# This CRF document has a consistent structure across all pages:
# - A "Schedule Category & Name" line near the top provides the form/section context
# - Activities are listed with bold labels (field questions) at x=167.7
# - Answer options and technical codes (SAS annotations) appear indented at x=238.7
# - We extract the bold question text as field_name, using the Schedule name as form_name
# - We skip answer options, SAS codes, Staff Initials, Comment labels, and page furniture

import re

def extract(pages):
    records = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name:" line
        form_name = ""
        for line in lines:
            if line.x0 < 100 and "Schedule Category & Name:" in line.text:
                # Find the corresponding value line
                for val_line in lines:
                    if val_line.y0 > line.y0 - 2 and val_line.y0 < line.y0 + 15 and val_line.x0 > 150:
                        form_name = val_line.text.strip()
                        break
                break
        
        # Extract field labels
        # Field labels are bold lines at x ≈ 167.7 that are questions/prompts
        # They may wrap across multiple lines
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for bold lines at x ≈ 167.7 (field label position)
            if line.bold and 160 < line.x0 < 175:
                text = line.text.strip()
                
                # Skip non-field labels
                if text in ["Activity", "Answer(s):", "Timepoint"]:
                    i += 1
                    continue
                
                # Skip SAS annotations (contain brackets and "SAS:")
                if "[" in text and "]" in text and "SAS:" in text:
                    i += 1
                    continue
                
                # Skip "Staff Initials:" and "Comment:" labels
                if text in ["Staff Initials:", "Comment:"]:
                    i += 1
                    continue
                
                # Collect wrapped lines (continuation lines at same x position, bold)
                field_parts = [text]
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Check if it's a continuation (same x, bold, close y)
                    if (next_line.bold and 
                        160 < next_line.x0 < 175 and 
                        next_line.y0 - line.y0 < 50):
                        next_text = next_line.text.strip()
                        # Stop if we hit a new field marker or special label
                        if next_text in ["Answer(s):", "Staff Initials:", "Comment:"]:
                            break
                        if "[" in next_text and "]" in next_text and "SAS:" in next_text:
                            break
                        field_parts.append(next_text)
                        j += 1
                    else:
                        break
                
                # Join wrapped parts
                field_name = " ".join(field_parts)
                
                # Filter out non-field text patterns
                # Skip if it looks like a date/time format placeholder
                if re.match(r'^[_\s:-]+$', field_name):
                    i = j if j > i + 1 else i + 1
                    continue
                
                # Skip if it's just format hints
                if field_name in ["dd - MMM - yyyy", "HH:mm"]:
                    i = j if j > i + 1 else i + 1
                    continue
                
                # Skip if empty or too short
                if len(field_name) < 3:
                    i = j if j > i + 1 else i + 1
                    continue
                
                # Skip lines that are just technical annotations
                if field_name.startswith("SAS:["):
                    i = j if j > i + 1 else i + 1
                    continue
                
                # Valid field - record it
                if field_name and form_name:
                    records.append({
                        "form_name": form_name,
                        "field_name": field_name,
                        "page": page_num
                    })
                
                i = j if j > i + 1 else i + 1
            else:
                i += 1
    
    return records
```