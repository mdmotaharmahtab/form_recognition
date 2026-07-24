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
        
        # Pattern 3: Cluster 2 pages - fields with different layout
        # Look for black text, size ~6-7, x position around 430-460
        # These appear to be field labels in a different section
        # Check for lines that look like field labels (not metadata)
        for i, line in enumerate(lines):
            if line.non_black:
                continue
            if not (6.0 <= line.size <= 7.5):
                continue
            if not (425 <= line.x0 <= 465):
                continue
            
            text = line.text.strip()
            
            # Skip empty or very short
            if len(text) < 2:
                continue
            
            # Skip by structural pattern: metadata labels end with colon
            if text.endswith(":"):
                continue
            
            # Skip by structural pattern: starts with common metadata prefixes
            if text.startswith("Description:") or text.startswith("Mandatory?") or text.startswith("Disallow"):
                continue
            
            # Skip by structural pattern: contains "Edit Checks:"
            if "Edit Checks:" in text:
                continue
            
            # Skip by structural pattern: "Value =" pattern
            if text.startswith("Value") and "=" in text:
                continue
            
            # Skip single letters or very short codes
            if len(text) <= 3:
                continue
            
            # This might be a field label - but be conservative
            # Only extract if it looks like a real label (has spaces or is reasonably long)
            if " " in text or len(text) >= 5:
                field_name = text
                
                results.append({
                    "form_name": form_name,
                    "field_name": field_name,
                    "page": page_num
                })
        
        # Pattern 4: Additional fields in cluster 0 pages
        # Look for fields that might be single-word labels at x ~46-47, size 7-8
        # These could be simple field names like "PR", "QRS", "QT"
        for i, line in enumerate(lines):
            if line.non_black:
                continue
            if not (7.0 <= line.size <= 8.5):
                continue
            if not (44 <= line.x0 <= 48):
                continue
            
            text = line.text.strip()
            
            # Skip empty
            if len(text) < 2:
                continue
            
            # Skip by structural position: SAS field names are in brackets
            if text.startswith("["):
                continue
            
            # Skip by structural position: answer options start with "O "
            if text.startswith("O "):
                continue
            
            # Skip by structural pattern: code references
            if text.startswith("Code List:"):
                continue
            
            # Skip by structural pattern: contains underscores (field codes)
            if "_" in text:
                continue
            
            # Skip by structural pattern: just numbers/dates
            if re.match(r'^[\d\-:\/]+$', text):
                continue
            
            # For short uppercase words (2-4 chars), these could be valid field labels
            # like "PR", "QRS", "QT" - medical abbreviations
            if 2 <= len(text) <= 4 and text.isupper() and text.isalpha():
                field_name = text
                
                results.append({
                    "form_name": form_name,
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
