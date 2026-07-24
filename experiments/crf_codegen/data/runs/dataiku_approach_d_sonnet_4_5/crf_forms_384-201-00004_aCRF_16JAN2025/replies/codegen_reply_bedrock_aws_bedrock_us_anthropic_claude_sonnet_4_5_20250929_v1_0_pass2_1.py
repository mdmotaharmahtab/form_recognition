```python
# This CRF document contains multiple layout families:
# - Family A: Title/cover page with study information
# - Family B: Study Events table listing visits and forms
# - Family C: Continuation pages with technical annotations
# - Field pages: Data entry forms with field labels, input boxes, and technical metadata
# Strategy: Extract fields from pages with form headers (colored backgrounds) and field labels.
# Form names are in white text on colored backgrounds; field labels precede input boxes or radio buttons.

import re
from typing import List, Dict

def extract(pages):
    records = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip cover page (page 1)
        if page_num == 1:
            continue
        
        # Skip Study Events table pages (family B)
        # These have "Study Events" header and list forms but contain no data-entry fields
        if any(line.text == "Study Events" and line.non_black for line in lines):
            continue
        
        # Look for form name - white text on colored background at top of page
        form_name = ""
        for line in lines:
            if line.y0 < 60 and line.size >= 11 and line.non_black:
                # Check if this is a form title (not "Origin: CRF" or other metadata)
                if "Origin:" not in line.text and "Aliases:" not in line.text:
                    form_name = line.text.strip()
                    break
        
        # Extract fields from this page
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip header/footer areas
            if line.y0 < 30 or line.y0 > 800:
                i += 1
                continue
            
            # Skip technical annotations (small font on right side)
            if line.x0 > 400 and line.size < 8:
                i += 1
                continue
            
            # Skip code list headers and table headers
            if line.bold and line.non_black and line.size < 11:
                i += 1
                continue
            
            # Look for field labels - left side, reasonable font size, not in brackets
            if line.x0 < 300 and 7 <= line.size <= 11 and not line.non_black:
                text = line.text.strip()
                
                # Skip if it's a technical annotation in brackets
                if re.match(r'^\[.*\]$', text):
                    i += 1
                    continue
                
                # Skip if it's "SAS Field Name:" or similar metadata
                if "SAS Field Name:" in text or "Aliases:" in text or "Odm OID" in text:
                    i += 1
                    continue
                
                # Skip section headers with "Origin:" pattern (colored, bold)
                if i + 1 < len(lines) and "Origin:" in lines[i + 1].text:
                    i += 1
                    continue
                
                # Check if next line(s) contain input indicators or radio buttons
                has_input = False
                j = i + 1
                while j < min(i + 5, len(lines)) and lines[j].y0 - line.y0 < 50:
                    next_text = lines[j].text.strip()
                    # Look for input boxes [_|_], radio buttons O, or continuation of label
                    if re.search(r'\[_\|', next_text) or next_text.startswith('O '):
                        has_input = True
                        break
                    # Check if it's a continuation line (similar x position, close y)
                    if lines[j].x0 < 300 and abs(lines[j].x0 - line.x0) < 20 and lines[j].y0 - lines[j-1].y0 < 15:
                        # Continuation line - append to text
                        if not re.match(r'^\[.*\]$', next_text):
                            text += " " + next_text
                    j += 1
                
                # Also check if current line itself contains input indicators
                if re.search(r'\[_\|', text) or text.startswith('O '):
                    has_input = True
                
                # Extract the label part (before input indicators)
                if has_input:
                    # Remove input indicators from the label
                    label = re.sub(r'\[_\|.*?\]', '', text)
                    label = re.sub(r'O\s+\w+.*$', '', label)
                    label = label.strip()
                    
                    # Skip if label is empty or too short
                    if len(label) < 3:
                        i += 1
                        continue
                    
                    # Skip if it looks like an answer option (single word after O)
                    if re.match(r'^(Yes|No|Normal|Abnormal|Male|Female|Unknown)$', label, re.IGNORECASE):
                        i += 1
                        continue
                    
                    # Skip if it's a code list name
                    if label.startswith('Code List:'):
                        i += 1
                        continue
                    
                    records.append({
                        "form_name": form_name,
                        "field_name": label,
                        "page": page_num
                    })
            
            i += 1
    
    return records
```