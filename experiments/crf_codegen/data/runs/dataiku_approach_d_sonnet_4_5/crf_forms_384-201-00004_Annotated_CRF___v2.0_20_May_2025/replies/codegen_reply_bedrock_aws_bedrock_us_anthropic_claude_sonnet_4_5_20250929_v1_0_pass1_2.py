Looking at the sample pages, I can see that:

1. **Cluster 1 (pages 20, 175)**: These are genuinely field-free pages. Page 20 shows a table of contents/schedule listing form names. Page 175 shows a code list definition table (CSSRS Actual Lethality/Medical Damage codes and their meanings). These are reference/definition pages with no data-entry fields.

2. **Cluster 0 (pages 50, 71)**: These pages DO contain data-entry fields that my program is missing. The fields are present but my extraction logic is failing because:
   - Field labels appear at x ~46.5 with size 7.5
   - They are followed by answer options (starting with "O ") at x ~249.2
   - My program is correctly positioned to find these, but may be skipping them due to overly strict filtering

3. **Cluster 2 (pages 57, 121)**: Similar to cluster 0 - these have data-entry fields with the same layout pattern that should be captured.

Looking more carefully at page 50, I see fields like:
- "Frequency" at x=46.5, y=36.6
- "Duration" at x=46.5, y=126.5
- "Controllability" at x=46.5, y=203.8

The issue is that my program may be skipping these because they appear isolated or the continuation logic is breaking. Let me fix the extraction logic:

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
        
        # Skip if no form name found
        if not form_name:
            continue
        
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
                if len(text) < 2:
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
                
                # Skip metadata fields
                if text in ["Format:", "Data Type:", "Origin:", "Aliases:", "Description:", "Mandatory?:", "Disallow Future Date:", "Conditionally Visible", "Conditional Item:", "Visible If Value:", "SDS Var Name:", "Short Name", "Requires Role:"]:
                    i += 1
                    continue
                
                # Check if this looks like a field label
                # Field labels are questions or descriptive text
                # Single-word labels at this position are often valid field names
                
                # Valid field label if it has substance and is not a technical term
                if len(text) >= 2 and not text.startswith("Value") and not text.startswith("Name:"):
                    # Check if next line is an answer option or input field (indicates this is a field label)
                    is_field = False
                    
                    # Look ahead to see if there are answer options or input markers
                    for j in range(i + 1, min(i + 10, len(lines))):
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        # If we find answer options, this is a field
                        if next_text.startswith("O ") and 240 <= next_line.x0 <= 260:
                            is_field = True
                            break
                        
                        # If we find an input field marker
                        if "[____" in next_text or "[_]" in next_text:
                            is_field = True
                            break
                        
                        # If we find a SAS field name bracket on the next few lines
                        if next_text.startswith("[") and next_text.endswith("]") and 44 <= next_line.x0 <= 50:
                            is_field = True
                            break
                        
                        # Stop if we've gone too far
                        if next_line.y0 - line.y0 > 50:
                            break
                    
                    if is_field:
                        results.append({
                            "form_name": form_name,
                            "field_name": text,
                            "page": page_num
                        })
                
                i += 1
            else:
                i += 1
    
    return results
```