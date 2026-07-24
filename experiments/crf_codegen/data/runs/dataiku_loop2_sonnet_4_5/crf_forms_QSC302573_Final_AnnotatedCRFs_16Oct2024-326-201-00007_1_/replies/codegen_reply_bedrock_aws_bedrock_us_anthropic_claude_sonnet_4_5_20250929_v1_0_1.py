```python
# This CRF document has a consistent structure across all pages:
# - A "Schedule Category & Name" line identifies the form/section (e.g., "S_QSC302573, 05a - Period 1 Final v1.0")
# - Activities are marked by bold text at x=167.7 (e.g., "PK Samples: PK Plasma #6")
# - Field questions appear as bold text at x=167.7 below each activity header
# - We extract the activity name as form_name and the question text as field_name
# - We skip answer options, SAS codes, and other metadata

import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for Schedule Category & Name to update current form
        for i, line in enumerate(lines):
            if line.x0 < 100 and line.bold and "Schedule Category & Name:" in line.text:
                # Next line should contain the form name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Extract the descriptive part after the comma
                    if "," in next_line.text:
                        parts = next_line.text.split(",", 1)
                        if len(parts) > 1:
                            current_form = parts[1].strip()
                        else:
                            current_form = next_line.text.strip()
                    else:
                        current_form = next_line.text.strip()
                break
        
        # Extract activities and their questions
        # Activities are bold lines at x~167.7 that contain ":" and are followed by questions
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check if this is an activity header (bold, x~167.7, contains ":")
            if (line.bold and 
                160 < line.x0 < 175 and 
                ":" in line.text and
                not line.text.startswith("Answer") and
                not line.text.startswith("Comment") and
                not line.text.startswith("Barcode") and
                not line.text.startswith("Staff") and
                not "HH:mm" in line.text and
                not "dd - MMM - yyyy" in line.text):
                
                # This might be an activity header
                activity_name = line.text.strip()
                
                # Look ahead for question lines (bold, x~167.7, not answer/comment/etc)
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop if we hit another activity or major section
                    if (next_line.bold and 160 < next_line.x0 < 175 and 
                        ":" in next_line.text and
                        not next_line.text.startswith("Answer") and
                        not next_line.text.startswith("Comment") and
                        not next_line.text.startswith("Barcode") and
                        not next_line.text.startswith("Staff")):
                        break
                    
                    # Check if this is a question line
                    if (next_line.bold and 
                        160 < next_line.x0 < 175 and
                        not next_line.text.startswith("Answer") and
                        not next_line.text.startswith("Comment") and
                        not next_line.text.startswith("Barcode") and
                        not next_line.text.startswith("Staff") and
                        not next_line.text.startswith("O ") and
                        not next_line.non_black and
                        not re.match(r'^[A-Z]+\s*$', next_line.text) and
                        not re.match(r'^\s*_+\s*$', next_line.text) and
                        not "SAS:" in next_line.text and
                        not re.match(r'.*\[.*\].*SAS:', next_line.text) and
                        len(next_line.text) > 5):
                        
                        # This is a question
                        field_name = next_line.text.strip()
                        
                        # Skip if it looks like metadata or formatting
                        if not re.match(r'^(dd|HH|mm|yyyy|MMM)', field_name):
                            results.append({
                                "form_name": current_form,
                                "field_name": field_name,
                                "page": page_num
                            })
                    
                    j += 1
            
            i += 1
    
    return results
```