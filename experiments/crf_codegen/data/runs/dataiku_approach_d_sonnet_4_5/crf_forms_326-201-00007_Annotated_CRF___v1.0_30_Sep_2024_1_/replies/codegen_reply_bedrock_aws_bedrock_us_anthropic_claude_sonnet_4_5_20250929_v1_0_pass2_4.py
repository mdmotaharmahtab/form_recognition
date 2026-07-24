Looking at the problems, I can see that "Comment" is being extracted but attributed to the wrong form. The issue is that my form_name extraction logic is finding a form name, but it's not the correct one for the "Comment" field.

Let me analyze the structure:
- "Comment:" appears at x~29.9 (left side of page)
- The form name extraction looks for "Schedule Category & Name:" and takes text after a comma
- The "Comment" field is being associated with whatever form_name was last set

The problem is that "Comment" might be appearing on pages where the form_name extraction is picking up the wrong form title. I need to look more carefully at the page structure to find the correct form name for each field.

Let me rewrite to better handle form name extraction and ensure fields are matched to the correct form:

```python
def extract(pages):
    records = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form_name - look for the main title/header
        # The form name is typically a large, bold text near the top
        # or after "Schedule Category & Name:"
        form_name = ""
        
        # Strategy 1: Look for "Schedule Category & Name:" pattern
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Look for the next bold line at x~167.7 that contains a comma
                for j in range(i + 1, min(i + 10, len(lines))):
                    candidate = lines[j]
                    if candidate.x0 > 160 and candidate.x0 < 175:
                        text = candidate.text.strip()
                        if "," in text:
                            # Extract everything after the comma
                            form_name = text.split(",", 1)[1].strip()
                            break
                        elif text and not text.startswith("O "):
                            # Might be the form name without comma
                            form_name = text
                            break
                if form_name:
                    break
        
        # Strategy 2: If no form name found, look for large bold text near top
        if not form_name:
            for i, line in enumerate(lines[:20]):  # Check first 20 lines
                if (line.bold and 
                    len(line.text.strip()) > 10 and
                    "Draft" in line.text and
                    ("Period" in line.text or "Part" in line.text)):
                    form_name = line.text.strip()
                    break
        
        # Extract field labels
        skip_keywords = {"Activity", "Timepoint", "Line #", "Answer(s):"}
        
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Check for "Comment:" field (bold, at x~29.9)
            if (line.bold and 
                line.x0 > 25 and line.x0 < 35 and
                line.text.strip() == "Comment:"):
                
                # For Comment field, look for the form name on THIS page
                # Search backwards and forwards for the actual form title
                page_form_name = form_name
                
                # Look for a form title on this specific page
                # Check for bold text that looks like a form title
                for search_line in lines:
                    if (search_line.bold and
                        len(search_line.text.strip()) > 15 and
                        ("Period" in search_line.text or "Part" in search_line.text) and
                        "Draft" in search_line.text):
                        # This looks like a form title
                        page_form_name = search_line.text.strip()
                        break
                
                records.append({
                    "form_name": page_form_name,
                    "field_name": "Comment",
                    "page": page_num
                })
                i += 1
                continue
            
            # Check if this is a potential field label at x~167.7
            if (line.bold and 
                line.x0 > 160 and line.x0 < 175 and
                line.text.strip() and
                not line.text.strip().startswith("O ") and
                "[" not in line.text and
                "SAS:" not in line.text and
                line.text.strip() not in skip_keywords):
                
                # Collect field label and continuation lines
                field_parts = [line.text.strip()]
                
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop at answer section or new field
                    if (next_line.text.strip().startswith("O ") or
                        "[" in next_line.text or
                        "SAS:" in next_line.text or
                        next_line.text.strip() == "Answer(s):"):
                        break
                    
                    # Check for continuation
                    if (next_line.bold and 
                        next_line.x0 > 160 and next_line.x0 < 175 and
                        next_line.text.strip()):
                        field_parts.append(next_line.text.strip())
                        j += 1
                    else:
                        break
                
                field_name = " ".join(field_parts)
                
                # Filter out metadata and short labels
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