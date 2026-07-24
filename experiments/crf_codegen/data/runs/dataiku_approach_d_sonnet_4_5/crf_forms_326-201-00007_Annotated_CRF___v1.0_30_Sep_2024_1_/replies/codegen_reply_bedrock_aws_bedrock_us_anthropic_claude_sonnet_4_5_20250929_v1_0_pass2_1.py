```python
# This CRF document has a consistent structure across all pages:
# - A "Schedule Category & Name" line at y~93.9 provides the form_name context
# - Activities are listed with bold labels at x=167.7, followed by answer options
# - Field labels are bold text at x=167.7 that are NOT answer options (which start with "O ")
# - Answer options and technical annotations (e.g., [QSORRES] SAS:...) are NOT fields
# Strategy: Extract form_name from "Schedule Category & Name", then extract bold
# labels at x=167.7 that represent questions/fields, filtering out answer options.

def extract(pages):
    records = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form_name from "Schedule Category & Name:" line
        form_name = ""
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # The form name is on the same line or next line at x~167.7
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if next_line.x0 > 160 and next_line.x0 < 175:
                        # Extract everything after the comma (the actual form name)
                        text = next_line.text
                        if "," in text:
                            form_name = text.split(",", 1)[1].strip()
                        else:
                            form_name = text.strip()
                break
        
        # Extract field labels
        # Field labels are bold lines at x~167.7 that are NOT:
        # - Answer options (start with "O ")
        # - Technical annotations (contain "[" and "SAS:")
        # - Column headers ("Activity", "Answer(s):", "Barcode:", "Comment:")
        # - Empty or very short
        
        skip_keywords = {"Activity", "Answer(s):", "Barcode:", "Comment:", "Timepoint", "Line #"}
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check if this is a potential field label
            if (line.bold and 
                line.x0 > 160 and line.x0 < 175 and
                line.text.strip() and
                not line.text.strip().startswith("O ") and
                "[" not in line.text and
                "SAS:" not in line.text and
                line.text.strip() not in skip_keywords):
                
                # This looks like a field label - collect it and any continuation lines
                field_parts = [line.text.strip()]
                
                # Look ahead for continuation lines (same x position, bold, not answer options)
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop if we hit an answer section, comment, or new activity
                    if (next_line.text.strip() in skip_keywords or
                        next_line.text.strip().startswith("O ") or
                        "[" in next_line.text or
                        "SAS:" in next_line.text):
                        break
                    
                    # Check if this is a continuation (similar x position, bold)
                    if (next_line.bold and 
                        next_line.x0 > 160 and next_line.x0 < 175 and
                        next_line.text.strip()):
                        field_parts.append(next_line.text.strip())
                        j += 1
                    else:
                        break
                
                # Join the parts into a complete field name
                field_name = " ".join(field_parts)
                
                # Additional filtering: skip if it looks like metadata
                if (field_name and 
                    len(field_name) > 3 and
                    not field_name.startswith("Day ") and
                    "Date Created:" not in field_name and
                    "Page " not in field_name):
                    
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