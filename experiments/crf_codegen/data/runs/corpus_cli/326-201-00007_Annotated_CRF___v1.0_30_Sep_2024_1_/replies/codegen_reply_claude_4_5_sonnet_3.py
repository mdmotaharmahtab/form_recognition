Looking at the sample pages, I can see the structure clearly now:

1. **Form name** is on the line following "Schedule Category & Name:" at x~167.7
2. **Field names** are the bold text at x~167.7 that represent actual data entry questions
3. The key issue: I need to distinguish between:
   - Section headers (e.g., "C-SSRS Since Last Visit: 1. Wish to be Dead #1")
   - Actual field names (e.g., "1. Wish to be dead", "12 Lead Standard ECG")

The pattern I see:
- **Section headers** appear at timepoint lines (with "Day X" prefix) and end with "#N" and a line number
- **Actual fields** are the bold items that follow, often with descriptive text or instructions

Let me rewrite the extraction logic:

```python
import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if 'Schedule Category & Name:' in line.text:
                # Form name is on the next line at x~167
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if 155 < next_line.x0 < 180:
                        current_form = next_line.text.strip()
                break
        
        # Skip if no form found
        if not current_form:
            continue
        
        # Collect field names
        # Strategy: Look for bold text at x~167.7 that represents actual fields
        # Skip section headers (which have pattern ending with #N and line numbers)
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for bold text in the activity column (x~167)
            if (line.bold and 
                155 < line.x0 < 180 and 
                line.y0 > 110 and  # Below headers
                line.y0 < 750):     # Above footer
                
                # Collect the full text (may span multiple lines)
                field_parts = [line.text.strip()]
                j = i + 1
                last_y = line.y1
                
                while j < len(lines):
                    next_line = lines[j]
                    # Continuation: same x area, bold, close y
                    if (next_line.bold and 
                        155 < next_line.x0 < 180 and 
                        next_line.y0 - last_y < 16):
                        field_parts.append(next_line.text.strip())
                        last_y = next_line.y1
                        j += 1
                    else:
                        break
                
                field_name = ' '.join(field_parts)
                
                # Determine if this is a valid field
                is_valid = True
                
                # Skip column headers
                if field_name in ['Timepoint', 'Activity', 'Line #']:
                    is_valid = False
                
                # Skip section headers: they end with " #N" and have a line number nearby
                # Pattern: "Text: More Text #N" where the line also has a timepoint prefix or line number
                if re.search(r'#\d+$', field_name):
                    is_valid = False
                
                # Skip answer/comment/staff headers
                if field_name in ['Answer(s):', 'Comment:', 'Staff Initials:', 'Barcode:']:
                    is_valid = False
                
                # Skip lines that start with answer option markers
                if re.match(r'^O\s+', field_name):
                    is_valid = False
                
                # Skip pure SAS annotations
                if 'SAS:[Name=' in field_name:
                    is_valid = False
                
                # Skip date/time templates
                if re.match(r'^[_\s\-:]+$', field_name):
                    is_valid = False
                
                # Skip standalone brackets
                if re.match(r'^\[.*\]$', field_name):
                    is_valid = False
                
                # Skip very short text
                if len(field_name) <= 2:
                    is_valid = False
                
                # Add valid field
                if is_valid:
                    results.append({
                        'form_name': current_form,
                        'field_name': field_name,
                        'page': page_num
                    })
                
                i = j
            else:
                i += 1
    
    return results
```
