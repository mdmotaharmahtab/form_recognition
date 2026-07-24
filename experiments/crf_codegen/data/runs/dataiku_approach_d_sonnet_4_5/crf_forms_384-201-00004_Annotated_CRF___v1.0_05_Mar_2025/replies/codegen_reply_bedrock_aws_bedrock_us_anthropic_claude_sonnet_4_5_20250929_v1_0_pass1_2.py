```python
import re

def extract(pages):
    results = []
    last_form_name = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Identify form name: white text, size 11-13, y < 50
        form_name = ""
        for line in lines:
            if line.non_black and 11 <= line.size <= 13 and line.y0 < 50:
                form_name = line.text.strip()
                break
        
        # If no form name found on this page, carry forward the last one
        if form_name:
            last_form_name = form_name
        else:
            form_name = last_form_name
        
        # Check if this is a reference/code list page (Family D non-field pages)
        # These have "Coded" and "Decode" column headers at y~60, size 10-11, bold
        is_reference_table = False
        has_coded = False
        has_decode = False
        for line in lines:
            if line.bold and 50 <= line.y0 <= 70 and line.size >= 10:
                text = line.text.strip()
                if text == "Coded":
                    has_coded = True
                if text == "Decode":
                    has_decode = True
        if has_coded and has_decode:
            is_reference_table = True
        
        if is_reference_table:
            continue
        
        # Extract field labels from two different patterns:
        
        # Pattern 1: Main field labels - size 7-8, black, x 40-52
        # These are the question text
        for i, line in enumerate(lines):
            if line.non_black:
                continue
            if not (7.0 <= line.size <= 8.5):
                continue
            if not (40 <= line.x0 <= 52):
                continue
            
            text = line.text.strip()
            
            # Skip empty or very short lines
            if len(text) < 3:
                continue
            
            # Skip lines that are SAS field names (in brackets)
            if text.startswith("[") and "]" in text:
                continue
            
            # Skip lines that are answer options (start with "O ")
            if text.startswith("O "):
                continue
            
            # Skip lines that are just codes (all caps with underscores/numbers)
            if re.match(r'^[A-Z_0-9]+$', text) and "_" in text:
                continue
            
            # Skip lines that are just numbers or dates
            if re.match(r'^[\d\-:\/]+$', text):
                continue
            
            # Skip code list references
            if text.startswith("Code List:"):
                continue
            
            # Skip common metadata labels (these are at field level, not form level)
            if text in ["Comment:", "Description:", "Aliases:", "Role Restriction:", "Edit Checks:", "Mandatory?:", "Disallow Future Date:"]:
                continue
            
            # Skip lines that look like metadata values
            if text.startswith("Description:") or text.startswith("Mandatory?") or text.startswith("Disallow Future"):
                continue
            
            # This looks like a field label
            field_name = text
            
            # Check for multi-line labels (continuation at same x position)
            for j in range(i + 1, min(i + 5, len(lines))):
                next_line = lines[j]
                if next_line.non_black:
                    break
                if not (7.0 <= next_line.size <= 8.5):
                    break
                if not (40 <= next_line.x0 <= 52):
                    break
                next_text = next_line.text.strip()
                if next_text.startswith("[") or next_text.startswith("O ") or next_text.startswith("Code List:"):
                    break
                if len(next_text) < 3:
                    break
                # Continuation line
                field_name += " " + next_text
            
            # Clean up
            field_name = re.sub(r'\s+', ' ', field_name).strip()
            
            # Final validation: skip single uppercase words that look like codes
            if len(field_name.split()) == 1 and field_name.isupper() and len(field_name) < 15:
                continue
            
            results.append({
                "form_name": form_name,
                "field_name": field_name,
                "page": page_num
            })
        
        # Pattern 2: Cover page fields (page 1) - different layout
        # These are at x < 40, size 9-10, bold, black
        if page_num == 1:
            for line in lines:
                if line.non_black:
                    continue
                if not line.bold:
                    continue
                if not (9 <= line.size <= 11):
                    continue
                if line.x0 > 40:
                    continue
                
                text = line.text.strip()
                
                # Skip short lines
                if len(text) < 3:
                    continue
                
                # Skip lines that don't end with colon (not field labels)
                if not text.endswith(":"):
                    continue
                
                # Remove the colon for the field name
                field_name = text.rstrip(":")
                
                # Common cover page fields
                if field_name in ["Sponsor Name", "Protocol Number", "Protocol Title", "aCRF Version", "Prepared by", "Date"]:
                    results.append({
                        "form_name": "Cover Page",
                        "field_name": field_name,
                        "page": page_num
                    })
    
    # Deduplicate consecutive identical records
    deduplicated = []
    prev = None
    for record in results:
        if record != prev:
            deduplicated.append(record)
            prev = record
    
    return deduplicated
```