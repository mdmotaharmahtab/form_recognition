def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form name: white text on color background, size 12.0
        form_name = ""
        for line in lines:
            if line.size == 12.0 and line.text and not line.text.strip() == "":
                if line.y0 < 100:  # Near top of page
                    text = line.text.strip()
                    # Skip protocol numbers, dates, page numbers
                    if not text.startswith("384-") and "Page" not in text and "page" not in text.lower():
                        if len(text) > 5:  # Substantial text
                            form_name = text
                            break
        
        # Skip if no form name found
        if not form_name:
            continue
        
        # Extract field labels from the page
        # Field labels appear at x ~46.5, size 7.5, followed by answer options or input fields
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for field labels: x around 46-47, size 7.5, black text
            if 44 <= line.x0 <= 50 and 7.0 <= line.size <= 8.0 and not line.non_black:
                text = line.text.strip()
                
                # Skip if it's a SAS field name marker (starts with [ and ends with ])
                if text.startswith("[") and text.endswith("]"):
                    i += 1
                    continue
                
                # Skip if it's empty or very short
                if len(text) < 2:
                    i += 1
                    continue
                
                # Skip answer options (they start with "O ")
                if text.startswith("O "):
                    i += 1
                    continue
                
                # Skip metadata fields by structural position:
                # Metadata appears in the right column (x > 450)
                # We're looking at left column fields only (x ~46)
                
                # Check if this looks like a field label by looking ahead
                is_field = False
                
                # Look ahead to see if there are answer options or input markers
                for j in range(i + 1, min(i + 15, len(lines))):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # If we find answer options in the middle column, this is a field
                    if next_text.startswith("O ") and 240 <= next_line.x0 <= 260:
                        is_field = True
                        break
                    
                    # If we find an input field marker
                    if "[____" in next_text or "[_]" in next_text:
                        is_field = True
                        break
                    
                    # If we find a SAS field name bracket on the next few lines at same x position
                    if next_text.startswith("[") and next_text.endswith("]") and 44 <= next_line.x0 <= 50:
                        is_field = True
                        break
                    
                    # Stop if we've gone too far vertically
                    if next_line.y0 - line.y0 > 60:
                        break
                
                if is_field:
                    results.append({
                        "form_name": form_name,
                        "field_name": text,
                        "page": page_num
                    })
            
            i += 1
    
    return results
