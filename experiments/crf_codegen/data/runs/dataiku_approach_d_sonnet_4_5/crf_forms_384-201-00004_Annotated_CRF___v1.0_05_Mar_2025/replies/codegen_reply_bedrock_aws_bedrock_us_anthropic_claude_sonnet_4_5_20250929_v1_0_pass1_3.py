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
        
        # Check if this is a reference/code list page
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
        
        # Extract field labels from multiple patterns:
        
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
            
            # Skip by structural position: SAS field names are in brackets
            if text.startswith("[") and "]" in text:
                continue
            
            # Skip by structural position: answer options start with "O "
            if text.startswith("O "):
                continue
            
            # Skip by structural pattern: code references have "Code List:" prefix
            if text.startswith("Code List:"):
                continue
            
            # Skip by structural pattern: all-caps with underscores (codes)
            if re.match(r'^[A-Z_0-9]+$', text) and "_" in text:
                continue
            
            # Skip by structural pattern: just numbers/dates
            if re.match(r'^[\d\-:\/]+$', text):
                continue
            
            # Skip by structural pattern: metadata labels end with colon and are short
            if text.endswith(":") and len(text) < 25 and text.count(" ") <= 2:
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
        # These are at x < 40, size 9-11, bold, black, end with colon
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
                
                results.append({
                    "form_name": "Cover Page",
                    "field_name": field_name,
                    "page": page_num
                })
        
        # Pattern 3: Fields in right column metadata area (x > 430, size ~5-6)
        # These appear on cluster 0 pages with technical annotations
        # Look for lines that are NOT metadata labels (don't match the metadata pattern)
        for i, line in enumerate(lines):
            if line.non_black:
                continue
            if not (5.0 <= line.size <= 7.0):
                continue
            if not (line.x0 > 430):
                continue
            
            text = line.text.strip()
            
            # Skip empty or very short
            if len(text) < 2:
                continue
            
            # Skip by structural pattern: metadata labels (Name:, Value, Description:, etc.)
            # These are short lines ending with colon or starting with specific patterns
            if text.endswith(":") and len(text) < 30:
                continue
            
            # Skip by structural pattern: metadata values (start with specific prefixes)
            if text.startswith("Value") or text.startswith("Description:") or text.startswith("Mandatory?") or text.startswith("Disallow Future"):
                continue
            
            # Skip by structural pattern: edit check names (contain underscores and colons)
            if ":" in text and "_" in text and text.count("_") >= 2:
                continue
            
            # Skip single letters or codes
            if len(text) <= 3 and text.isupper():
                continue
            
            # This might be a field label in the metadata area
            # But we need to be careful - most content here is NOT fields
            # Only extract if it looks like a real question/label
            # Skip this pattern for now as it's too noisy
            pass
    
    # Deduplicate consecutive identical records
    deduplicated = []
    prev = None
    for record in results:
        if record != prev:
            deduplicated.append(record)
            prev = record
    
    return deduplicated
```