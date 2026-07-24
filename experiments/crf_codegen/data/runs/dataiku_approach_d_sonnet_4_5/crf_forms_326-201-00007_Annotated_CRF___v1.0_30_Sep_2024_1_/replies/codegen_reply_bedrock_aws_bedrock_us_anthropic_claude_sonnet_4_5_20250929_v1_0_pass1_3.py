```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if line.text.startswith("Schedule Category & Name:"):
                # Next line contains the form name
                if i + 1 < len(lines):
                    form_text = lines[i + 1].text.strip()
                    # Remove leading code like "QSC302573, "
                    if ", " in form_text:
                        current_form = form_text.split(", ", 1)[1]
                    else:
                        current_form = form_text
                break
        
        # Analyze page structure to identify field label column
        # Field labels are typically bold, at a consistent x position (around 167-170)
        # We need to distinguish them from:
        # 1. Section headers (also bold, but different structural role)
        # 2. Instructional text (bold but not field labels)
        # 3. Answer options (start with "O ")
        
        # Find the primary field label x-position by looking at bold text distribution
        bold_x_positions = []
        for line in lines:
            if line.bold and 9.5 < line.size < 10.5 and not line.non_black:
                bold_x_positions.append(line.x0)
        
        # Identify the field label column (most common x position in the 160-180 range)
        field_label_x = None
        if bold_x_positions:
            candidates = [x for x in bold_x_positions if 160 < x < 180]
            if candidates:
                # Use the most common x position
                from collections import Counter
                x_counts = Counter([round(x, 0) for x in candidates])
                if x_counts:
                    field_label_x = x_counts.most_common(1)[0][0]
        
        # If we couldn't identify a field label column, skip detailed extraction
        if field_label_x is None:
            continue
        
        # Process lines to extract fields
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check if this is a field label candidate
            # Must be: bold, in the field label column (±10 pixels), appropriate size, not blue
            if (line.bold and 
                abs(line.x0 - field_label_x) < 10 and 
                9.5 < line.size < 10.5 and
                not line.non_black):
                
                # Structural exclusions based on position and context:
                
                # 1. Skip standard structural headers (these appear consistently)
                if line.text in ["Activity", "Answer(s):", "Comment:", "Barcode:"]:
                    i += 1
                    continue
                
                # 2. Skip answer options (always start with "O ")
                if line.text.startswith("O "):
                    i += 1
                    continue
                
                # 3. Skip technical annotations in brackets at start
                if line.text.startswith("[") and "]" in line.text:
                    i += 1
                    continue
                
                # 4. Skip SAS annotations
                if "SAS:[Name=" in line.text:
                    i += 1
                    continue
                
                # 5. Detect section headers by structure:
                # Section headers contain "#" followed by a number at the end
                # and often have a colon separating section from subsection
                # Pattern: "Text: More Text #N" or "Text #N"
                if "#" in line.text and re.search(r'#\s*\d+\s*$', line.text):
                    # This is likely a section header, not a field
                    i += 1
                    continue
                
                # 6. Detect instructional/explanatory text that's not a field:
                # These are bold text blocks that provide context but aren't questions
                # Structural markers:
                # - Often start with verbs like "PRE-DOSE", "POST-DOSE"
                # - Contain phrases like "Difference for", "Calculation -", "To be performed"
                # - Are descriptive statements, not questions or data entry prompts
                # - Often contain parenthetical timing/method instructions
                
                # Check if line is all-caps prefix followed by descriptive text
                if re.match(r'^[A-Z\-]+ [A-Z\-]+.*:', line.text):
                    # Pattern like "PRE-DOSE - Vital Signs Difference for..."
                    i += 1
                    continue
                
                # Check for calculation/instruction indicators
                if any(indicator in line.text for indicator in [
                    "Difference for", "Difference Calculation", 
                    "To be performed", "will be withdrawn"
                ]):
                    i += 1
                    continue
                
                # Check if it starts with timing prefix and contains colon (structural marker)
                if re.match(r'^(PRE-DOSE|POST-DOSE|Predose|Postdose)\s+[^:]+:', line.text):
                    i += 1
                    continue
                
                # Collect the field label (may span multiple lines)
                field_parts = [line.text]
                j = i + 1
                
                # Look ahead for continuation lines
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Check if next line is a continuation (same column, bold, appropriate size)
                    if (next_line.bold and 
                        abs(next_line.x0 - field_label_x) < 10 and 
                        9.5 < next_line.size < 10.5 and 
                        not next_line.non_black):
                        
                        # Stop at structural markers
                        if (next_line.text in ["Answer(s):", "Comment:", "Barcode:"] or
                            next_line.text.startswith("O ") or
                            next_line.text.startswith("[") or
                            "SAS:[Name=" in next_line.text):
                            break
                        
                        # Stop at section headers
                        if "#" in next_line.text and re.search(r'#\s*\d+\s*$', next_line.text):
                            break
                        
                        # Stop at instructional blocks
                        if (re.match(r'^[A-Z\-]+ [A-Z\-]+.*:', next_line.text) or
                            any(ind in next_line.text for ind in [
                                "Difference for", "Difference Calculation",
                                "To be performed", "will be withdrawn"
                            ]) or
                            re.match(r'^(PRE-DOSE|POST-DOSE|Predose|Postdose)\s+[^:]+:', next_line.text)):
                            break
                        
                        # It's a continuation
                        field_parts.append(next_line.text)
                        j += 1
                    else:
                        break
                
                # Join the field label
                field_name = " ".join(field_parts).strip()
                
                # Final validation: skip if entire field is parenthetical instruction
                if field_name.startswith("(") and field_name.endswith(")"):
                    i = j
                    continue
                
                # Add the field
                if field_name and len(field_name) > 0:
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