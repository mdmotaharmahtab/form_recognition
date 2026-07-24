```python
import re
from typing import List, Dict

def extract(pages):
    records = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find the form name from "Schedule Category & Name:" line
        form_name = ""
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Next line should have the actual name
                if i + 1 < len(lines):
                    next_line = lines[i + 1].text
                    # Extract everything after the code (e.g., "S_QSC302573, ")
                    if ", " in next_line:
                        form_name = next_line.split(", ", 1)[1].strip()
                break
        
        # Look for "Comment:" field - but only if it's in the main content area (x > 150)
        # The "Comment:" at x~29.9 is page furniture/header, not a data field
        # Real comment fields appear in the right column with other fields
        for i, line in enumerate(lines):
            if line.text == "Comment:" and line.bold and line.x0 > 150:
                # This is a real comment field in the data area
                records.append({
                    "form_name": form_name,
                    "field_name": "Comment:",
                    "page": page_num
                })
                break
        
        # Find field questions - they are bold, at x~167.7, and are actual questions
        # We need to identify question blocks and join multi-line questions
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for bold lines at x~167.7 that could be field questions
            # Skip headers, answer options, and SAS codes
            if (line.bold and 
                160 < line.x0 < 175 and 
                line.text and
                not line.text.startswith("O ") and  # Not an answer option
                "SAS:[" not in line.text and  # Not a SAS code
                line.text not in ["Activity", "Answer(s):", "Comment:"] and  # Not headers
                not re.match(r'^Day \d+', line.text) and  # Not timepoint
                not re.match(r'^\d+\.\d+', line.text)):  # Not line numbers
                
                # This might be a field question - collect it and any continuation lines
                question_parts = [line.text]
                j = i + 1
                
                # Look ahead for continuation lines (bold, similar x position, not special markers)
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop if we hit certain markers
                    if (next_line.text in ["Staff Initials:", "Answer(s):", "Comment:"] or
                        next_line.text.startswith("O ") or
                        "SAS:[" in next_line.text or
                        next_line.text.startswith("Day ") or
                        next_line.text.startswith("_ _") or
                        next_line.text in ["dd - MMM - yyyy", "HH:mm"]):
                        break
                    
                    # If it's bold and at similar x position, it's likely a continuation
                    if next_line.bold and 160 < next_line.x0 < 175:
                        question_parts.append(next_line.text)
                        j += 1
                    else:
                        break
                
                # Join the question parts
                field_name = " ".join(question_parts).strip()
                
                # Filter out non-questions (structural elements, instructions, etc.)
                # Keep only if it looks like an actual data entry field
                if (field_name and 
                    len(field_name) > 10 and  # Reasonable length
                    not field_name.startswith("Timepoint") and
                    not field_name.startswith("Line #") and
                    not re.match(r'^\d+\.\d+\s*\(hidden\)', field_name) and
                    "(**OPERATOR TO COMPLETE**" not in field_name):
                    
                    # Additional filtering: skip if it's just a label without question content
                    # Look for question indicators or field-like patterns
                    is_field = (
                        "?" in field_name or  # Has question mark
                        field_name.startswith("Record ") or
                        field_name.startswith("Date ") or
                        field_name.startswith("Time ") or
                        field_name.startswith("What ") or
                        field_name.startswith("Has ") or
                        field_name.startswith("Did ") or
                        field_name.startswith("Does ") or
                        field_name.startswith("Is ") or
                        field_name.startswith("Was ") or
                        field_name.startswith("Were ") or
                        field_name.startswith("Confirm ") or
                        field_name.startswith("When ") or
                        "Version" in field_name or
                        "Number" in field_name or
                        "Dose" in field_name or
                        "Route" in field_name or
                        "Administration Record" in field_name
                    )
                    
                    if is_field:
                        records.append({
                            "form_name": form_name,
                            "field_name": field_name,
                            "page": page_num
                        })
                
                i = j
            else:
                i += 1
    
    return records
```