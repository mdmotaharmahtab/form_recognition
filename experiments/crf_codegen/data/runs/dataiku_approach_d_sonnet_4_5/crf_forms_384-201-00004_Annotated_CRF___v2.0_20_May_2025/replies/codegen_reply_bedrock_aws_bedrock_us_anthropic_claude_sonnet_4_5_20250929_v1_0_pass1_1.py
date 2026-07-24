```python
# This CRF has multiple layout families:
# - Family A: Cover/approval pages (no data fields)
# - Family B: Study event schedules listing forms (form names in column)
# - Family C: Detailed form pages with field definitions and metadata
# - Family D: Long form pages with extensive field details
# Strategy: Extract form names from white-on-color headers (sz=12.0 #ffffff).
# Extract field labels from CRF origin sections, ignoring technical metadata.

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form name: white text on color background, size 12.0
        form_name = ""
        for line in lines:
            if line.size == 12.0 and line.text and not line.text.strip() == "":
                # Check if this is a white text header (form title)
                # White text appears as #ffffff in the samples
                # We look for large white text near top of page
                if line.y0 < 100:  # Near top of page
                    # Check if it's not a small label or code
                    text = line.text.strip()
                    # Skip protocol numbers, dates, page numbers
                    if not text.startswith("384-") and "Page" not in text and "page" not in text.lower():
                        if len(text) > 5:  # Substantial text
                            form_name = text
                            break
        
        # Extract field labels from the page
        # Field labels appear at x ~46.5, size 7.5, followed by answer options or input fields
        # They are NOT in color (non_black=False) and are regular weight
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for field labels: x around 46-47, size 7.5, black text
            if 44 <= line.x0 <= 50 and 7.0 <= line.size <= 8.0 and not line.non_black:
                text = line.text.strip()
                
                # Skip if it's a SAS field name marker
                if text.startswith("[") and text.endswith("]"):
                    i += 1
                    continue
                
                # Skip if it's empty or very short
                if len(text) < 3:
                    i += 1
                    continue
                
                # Skip technical annotations
                if "SAS Field Name:" in text or "Odm OID" in text:
                    i += 1
                    continue
                
                # Skip answer options (they start with "O ")
                if text.startswith("O "):
                    i += 1
                    continue
                
                # Skip code list references
                if "Code List:" in text:
                    i += 1
                    continue
                
                # Check if this looks like a field label
                # Field labels are questions or descriptive text
                # They may wrap across multiple lines
                
                # Collect potential continuation lines
                field_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Check if next line is a continuation (similar x, similar size)
                    if 44 <= next_line.x0 <= 50 and 7.0 <= next_line.size <= 8.0:
                        next_text = next_line.text.strip()
                        # Stop if we hit a bracket marker or answer option
                        if next_text.startswith("[") or next_text.startswith("O "):
                            break
                        # Stop if it's a new field (starts with capital or number)
                        if j > i + 1 and len(next_text) > 0:
                            # Check if this is likely a new field vs continuation
                            if next_line.y0 - lines[j-1].y0 > 15:  # Large gap
                                break
                        field_text += " " + next_text
                        j += 1
                    else:
                        break
                
                # Clean up the field text
                field_text = field_text.strip()
                
                # Skip if it's just a bracket reference
                if field_text.startswith("[") and field_text.endswith("]"):
                    i = j
                    continue
                
                # Skip if it's a technical field
                if any(skip in field_text for skip in ["SAS Field Name:", "Aliases:", "Description:", "Format:", "Data Type:"]):
                    i = j
                    continue
                
                # Valid field label if it has substance
                if len(field_text) > 5 and form_name:
                    results.append({
                        "form_name": form_name,
                        "field_name": field_text,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return results
```