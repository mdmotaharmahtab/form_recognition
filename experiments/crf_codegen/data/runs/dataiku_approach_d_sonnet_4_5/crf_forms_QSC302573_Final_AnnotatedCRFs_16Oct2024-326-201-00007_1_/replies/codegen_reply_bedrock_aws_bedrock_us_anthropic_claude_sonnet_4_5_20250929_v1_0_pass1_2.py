```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name:" line
        form_name = ""
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Next line should contain the actual schedule name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Extract everything after the comma and code
                    match = re.search(r',\s*(.+)$', next_line.text)
                    if match:
                        form_name = match.group(1).strip()
                break
        
        # Analyze page structure to identify section headers vs actual fields
        # Section headers typically:
        # - End with "#" followed by a number (e.g., "#1", "#10")
        # - Are followed by actual field labels (questions)
        # - Have a colon in them
        
        # Build a map of lines that are section headers (not actual fields)
        section_headers = set()
        for i, line in enumerate(lines):
            if (line.bold and 
                165 <= line.x0 <= 170 and 
                line.size >= 9.5):
                text = line.text.strip()
                # Section headers end with #N pattern and contain a colon
                if re.search(r'#\d+\s*$', text) and ':' in text:
                    section_headers.add(i)
        
        # Find field labels
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels are bold, at x≈167.7
            if (line.bold and 
                165 <= line.x0 <= 170 and 
                line.size >= 9.5 and
                line.text.strip()):
                
                text = line.text.strip()
                
                # Skip if this is a section header (ends with #N)
                if i in section_headers:
                    i += 1
                    continue
                
                # Skip structural headers that don't end with #N
                if text in ["Timepoint", "Activity", "Answer(s):", "Comment:", "Staff Initials:"]:
                    i += 1
                    continue
                
                # Skip answer options (lines starting with O or checkboxes)
                if re.match(r'^O\s+', text) or text.startswith('[ ]'):
                    i += 1
                    continue
                
                # Skip SAS codes (lines with [VARNAME] pattern at start)
                if re.match(r'^\[[\w_]+\]', text):
                    i += 1
                    continue
                
                # Skip lines that are just underscores/placeholders
                if re.match(r'^[_\s\-:#\.]+$', text):
                    i += 1
                    continue
                
                # Skip lines that look like input format templates
                if re.match(r'^(dd|MMM|yyyy|HH|mm)\s*$', text):
                    i += 1
                    continue
                
                # Skip operator notes
                if text.startswith('**'):
                    i += 1
                    continue
                
                # This looks like a field label - collect continuation lines
                field_parts = [text]
                j = i + 1
                
                # Look ahead for continuation lines
                while j < len(lines):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Stop if we hit a section header
                    if j in section_headers:
                        break
                    
                    # Stop if we hit structural elements
                    if next_text in ["Staff Initials:", "Answer(s):", "Comment:", "Timepoint", "Activity"]:
                        break
                    
                    # Stop if we hit answer options
                    if re.match(r'^O\s+', next_text):
                        break
                    
                    # Stop if we hit SAS codes
                    if re.match(r'^\[[\w_]+\]', next_text):
                        break
                    
                    # Stop if we hit format templates
                    if re.match(r'^(dd|MMM|yyyy|HH|mm)\s*$', next_text):
                        break
                    
                    # Continuation line: bold, similar x position, not placeholder
                    if (next_line.bold and 
                        165 <= next_line.x0 <= 170 and
                        next_line.size >= 9.5 and
                        next_text and
                        not re.match(r'^[_\s\-:#\.]+$', next_text)):
                        field_parts.append(next_text)
                        j += 1
                    else:
                        break
                
                # Join the parts into a complete field name
                field_name = " ".join(field_parts)
                
                # Add to results
                results.append({
                    "form_name": form_name,
                    "field_name": field_name,
                    "page": page_num
                })
                
                # Move past the lines we've processed
                i = j
            else:
                i += 1
    
    return results
```