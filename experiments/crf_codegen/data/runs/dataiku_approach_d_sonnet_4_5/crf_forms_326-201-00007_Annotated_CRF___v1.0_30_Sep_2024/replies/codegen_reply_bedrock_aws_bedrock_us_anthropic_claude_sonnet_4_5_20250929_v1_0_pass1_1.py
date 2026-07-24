```python
# This CRF document has a consistent structure across all pages:
# - A "Schedule Category & Name" line at y≈93.9 contains the form/section title
# - Fields are identified by bold text at x≈167.7 (Activity column) that is NOT:
#   * Answer options (lines starting with "O " or "[ ]" at x≈238.7)
#   * Technical annotations (lines containing "SAS:[" or "(hidden)" or "(Activates")
#   * Date/time format hints (lines like "dd - MMM - yyyy")
#   * Staff/Comment labels (blue text at x≈30.9 or x≈29.9)
# - The form name persists across pages until a new one appears

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
                
                # Final validation: skip if it looks like junk
                if (field_name and
                    not field_name.startswith("SAS:[") and
                    not field_name.startswith("[") and
                    "Date Created:" not in field_name and
                    "Page " not in field_name):
                    
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