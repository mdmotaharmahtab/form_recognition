```python
# This CRF document has two main structural patterns:
# 1. Family C/D: Field-bearing pages with form titles at top (y~35, size 12, white text)
#    and field labels in the body (size 7.5, black, left-aligned ~x=46).
# 2. Family D also includes reference tables (units, code lists) with no data-entry fields.
# Strategy: Extract form_name from the white title line at top; extract field_name from
# black size 7.5 lines at x~46 that are questions (not SAS codes, not answer options).
# Filter out reference tables by detecting their column-header structure.

import re
from collections import defaultdict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Identify form name: white text, size 12, y~35
        form_name = ""
        for line in lines:
            if line.non_black and 11.5 <= line.size <= 12.5 and 30 <= line.y0 <= 40:
                form_name = line.text.strip()
                break
        
        # Check if this is a reference table page (Family D non-field pages)
        # These have column headers like "Name", "Symbol", "Coded", "Decode" at y~60
        is_reference_table = False
        header_count = 0
        for line in lines:
            if line.bold and 55 <= line.y0 <= 65 and line.size >= 10:
                text = line.text.strip()
                if text in ["Name", "Symbol", "Coded", "Decode", "Order ID", "Container", "Units", "Sex"]:
                    header_count += 1
        if header_count >= 2:
            is_reference_table = True
        
        if is_reference_table:
            continue
        
        # Extract field labels: size ~7.5, black, x~46, not in brackets, not answer options
        for line in lines:
            if line.non_black:
                continue
            if not (7.0 <= line.size <= 8.0):
                continue
            if not (40 <= line.x0 <= 50):
                continue
            
            text = line.text.strip()
            
            # Skip empty or very short lines
            if len(text) < 3:
                continue
            
            # Skip lines that are SAS field names (in brackets)
            if text.startswith("[") and text.endswith("]"):
                continue
            
            # Skip lines that are answer options (start with "O ")
            if text.startswith("O "):
                continue
            
            # Skip lines that are just codes or technical annotations
            if re.match(r'^[A-Z_]+\d*$', text):
                continue
            
            # Skip lines that are just numbers or dates
            if re.match(r'^[\d\-:]+$', text):
                continue
            
            # Skip common non-field patterns
            if text in ["Comment:", "Description:", "Aliases:", "Role Restriction:", "Edit Checks:"]:
                continue
            
            # Skip lines that look like code list references
            if text.startswith("Code List:"):
                continue
            
            # This looks like a field label
            field_name = text
            
            # Check if this is a multi-line label by looking at the next few lines
            # Multi-line labels continue at the same x position without intervening fields
            idx = lines.index(line)
            for i in range(idx + 1, min(idx + 5, len(lines))):
                next_line = lines[i]
                if next_line.non_black:
                    break
                if not (7.0 <= next_line.size <= 8.0):
                    break
                if not (40 <= next_line.x0 <= 50):
                    break
                next_text = next_line.text.strip()
                if next_text.startswith("[") or next_text.startswith("O "):
                    break
                if len(next_text) < 3:
                    break
                # This looks like a continuation
                field_name += " " + next_text
            
            # Clean up the field name
            field_name = re.sub(r'\s+', ' ', field_name).strip()
            
            # Final validation: field names should be questions or labels
            # Skip if it's just a single word that looks like a code
            if len(field_name.split()) == 1 and field_name.isupper():
                continue
            
            results.append({
                "form_name": form_name,
                "field_name": field_name,
                "page": page_num
            })
    
    # Deduplicate consecutive identical records (multi-line labels)
    deduplicated = []
    prev = None
    for record in results:
        if record != prev:
            deduplicated.append(record)
            prev = record
    
    return deduplicated
```