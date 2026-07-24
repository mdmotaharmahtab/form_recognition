```python
def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if line.text.startswith("Schedule Category & Name:"):
                # Next line should contain the form name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Extract the part after the comma (the actual form name)
                    if "," in next_line.text:
                        current_form = next_line.text.split(",", 1)[1].strip()
                    else:
                        current_form = next_line.text.strip()
                break
        
        # Extract fields from the Activity column (x≈167.7, bold)
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for bold lines in the Activity column (x≈167.7)
            if line.bold and 160 < line.x0 < 175:
                text = line.text.strip()
                
                # Skip non-field lines
                if (text in ["Timepoint", "Activity", "Answer(s):", "Comment:"] or
                    text.startswith("SAS:[") or
                    text.startswith("[") and "]" in text and "SAS:" in text or
                    text in ["dd - MMM - yyyy", "HH:mm"] or
                    "(hidden)" in text or
                    "(Activates" in text or
                    text.startswith("O ") or
                    text.startswith("[ ]") or
                    not text):
                    i += 1
                    continue
                
                # Skip section headers that end with "#1", "#2", etc.
                # These are group/section labels, not actual data-entry fields
                # Pattern: text ending with colon followed by space and #N
                if ":" in text and text.rstrip().endswith(("#1", "#2", "#3", "#4", "#5")):
                    # Check if this is a section header (ends with ": #N" pattern)
                    parts = text.rsplit(":", 1)
                    if len(parts) == 2:
                        suffix = parts[1].strip()
                        # If suffix is exactly "#N" (just the marker), it's a section header
                        if suffix in ["#1", "#2", "#3", "#4", "#5"]:
                            i += 1
                            continue
                
                # This is a potential field - collect wrapped lines
                field_parts = [text]
                j = i + 1
                
                # Look ahead for continuation lines (same x position, bold, not a new field)
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop if we hit a new section marker or different column
                    if (next_line.text.startswith("Day 0") or
                        next_line.text.startswith("_ _ -") or
                        next_line.text.startswith("dd -") or
                        next_line.text.startswith("HH:") or
                        next_line.text in ["Staff Initials:", "Answer(s):", "Comment:"] or
                        next_line.x0 < 100):
                        break
                    
                    # Continuation line: bold, similar x position, not an answer option
                    if (next_line.bold and 160 < next_line.x0 < 175 and
                        not next_line.text.startswith("O ") and
                        not next_line.text.startswith("[ ]") and
                        not next_line.text.startswith("[") and
                        "(hidden)" not in next_line.text and
                        "(Activates" not in next_line.text and
                        "SAS:[" not in next_line.text):
                        field_parts.append(next_line.text.strip())
                        j += 1
                    else:
                        break
                
                # Join the parts into a complete field name
                field_name = " ".join(field_parts)
                
                # Final validation: skip if it looks like junk or section headers
                if (field_name and
                    not field_name.startswith("SAS:[") and
                    not field_name.startswith("[") and
                    "Date Created:" not in field_name and
                    "Page " not in field_name):
                    
                    # Skip if it ends with a numbered section marker like "#1"
                    if field_name.rstrip().endswith(("#1", "#2", "#3", "#4", "#5")):
                        if ":" in field_name:
                            parts = field_name.rsplit(":", 1)
                            if len(parts) == 2:
                                suffix = parts[1].strip()
                                if suffix in ["#1", "#2", "#3", "#4", "#5"]:
                                    i = j
                                    continue
                    
                    results.append({
                        "form_name": current_form,
                        "field_name": field_name,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    # Post-process to remove non-field entries that slipped through
    filtered_results = []
    for record in results:
        field = record["field_name"]
        
        # Skip fields that are clearly explanatory text (start with lowercase after paren,
        # contain question marks in a descriptive way, or are long descriptive sentences)
        if field.startswith("(") and len(field) > 100:
            # Long parenthetical text is likely an explanation
            continue
        
        # Skip fields that look like instructions or descriptions
        # These typically start with lowercase or are sentence fragments
        if (field.startswith("(") and 
            len(field) > 50 and 
            field[1:2].islower()):
            # Parenthetical starting with lowercase is likely explanatory
            continue
        
        # Skip standalone parenthetical questions (helper text for fields)
        if (field.startswith("(") and 
            field.endswith(")") and 
            "?" in field):
            # Likely a helper question, not a field label
            continue
        
        # Skip fields that are clearly continuation text from previous field
        # (lowercase start, no colon, looks like a sentence fragment)
        if (field and 
            field[0].islower() and 
            ":" not in field and
            len(field) > 30):
            # Likely continuation/explanation text
            continue
        
        # Skip fields ending with semicolon (incomplete sentence fragments)
        if field.endswith(";"):
            continue
        
        filtered_results.append(record)
    
    return filtered_results
```