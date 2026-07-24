Looking at the issues, the program is only extracting "Comment" fields but missing all the actual data-entry fields on these pages. The problem is that the extraction logic is too restrictive and isn't finding the field labels that exist on pages 140, 212, and 376.

Let me analyze the patterns and rewrite the program to capture all data-entry fields while still filtering out non-fields:

```python
import re
from typing import List, Dict, Any

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Check if this page matches our layout (has "Annotated CRF" header in blue bold)
        has_header = False
        for line in lines[:10]:  # Check first few lines
            if "Annotated CRF" in line.text and line.bold and line.non_black:
                has_header = True
                break
        
        if not has_header:
            continue
        
        # Extract form name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Next line or same line should have the actual name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # The form name appears after the label, not in blue
                    if not next_line.non_black and "QSC" in next_line.text:
                        current_form = next_line.text.strip()
                        break
                # Check if it's on the same line after the label
                if "QSC" in line.text:
                    parts = line.text.split(":", 1)
                    if len(parts) > 1:
                        current_form = parts[1].strip()
                        break
        
        # Extract field names - scan for bold text that looks like field labels
        # We need to be more inclusive to catch all actual fields
        
        i = 0
        seen_fields = set()  # Avoid duplicates on same page
        
        while i < len(lines):
            line = lines[i]
            
            # Look for bold text that could be a field label
            # Exclude: very small text, very large text, known non-fields
            if (line.bold and 
                9 < line.size < 14 and
                line.text.strip()):
                
                text = line.text.strip()
                
                # Skip known furniture/headers
                if text in ("Activity", "Timepoint", "Line #", "Annotated CRF",
                           "Schedule Category & Name:", "Staff Initials:", 
                           "Answer(s):", "Date:"):
                    i += 1
                    continue
                
                # Skip system codes/annotations in brackets
                if text.startswith("[") or "SAS:[Name=" in text or text.startswith("SAS:"):
                    i += 1
                    continue
                
                # Skip pure option markers (O, X, numbers, dashes)
                if re.match(r"^[OX\d\s\-]+$", text) and len(text) < 10:
                    i += 1
                    continue
                
                # Skip standalone punctuation or very short non-meaningful text
                if len(text) < 2 or text in ("O", "X", "Y", "N", "-"):
                    i += 1
                    continue
                
                # Check if this looks like a field label
                # Field labels typically:
                # - Are questions or prompts (contain words)
                # - May end with : or ?
                # - Are not just isolated single letters or numbers
                
                is_question = ("?" in text or ":" in text)
                has_multiple_words = len(text.split()) >= 2
                looks_like_label = (is_question or has_multiple_words or 
                                   len(text) > 5)  # Longer single words could be labels
                
                if looks_like_label:
                    # Collect continuation lines
                    field_parts = [text]
                    j = i + 1
                    
                    # Look ahead for continuation lines (same formatting, nearby position)
                    while j < len(lines):
                        next_line = lines[j]
                        
                        # Check if next line is a continuation:
                        # - Bold, similar size
                        # - Close in x position (within ~50 pixels)
                        # - Close in y position (within ~20 pixels for line wraps)
                        if (next_line.bold and 
                            abs(next_line.size - line.size) < 1 and
                            abs(next_line.x0 - line.x0) < 50):
                            
                            next_text = next_line.text.strip()
                            
                            # Stop if we hit another clear field marker
                            if (next_text in ("Staff Initials:", "Comment:", "Answer(s):", "Date:") or
                                next_text.startswith("Day ")):
                                break
                            
                            # Stop if it looks like a new question
                            if (next_text.endswith("?") or next_text.endswith(":")) and len(next_text) > 10:
                                break
                            
                            # Skip bracket annotations
                            if not (next_text.startswith("[") or "SAS:" in next_text):
                                # Check if it's a reasonable continuation
                                if len(next_text) > 1 and not re.match(r"^[OX\d\s\-]+$", next_text):
                                    field_parts.append(next_text)
                            j += 1
                        else:
                            break
                    
                    # Combine all parts into field name
                    field_name = " ".join(field_parts)
                    
                    # Final validation
                    if (field_name and 
                        len(field_name) > 3 and
                        field_name not in seen_fields):
                        
                        results.append({
                            "form_name": current_form,
                            "field_name": field_name,
                            "page": page_num
                        })
                        seen_fields.add(field_name)
                    
                    i = j
                else:
                    i += 1
            else:
                i += 1
    
    return results
```
