```python
# This CRF document has a repeating structure across all pages:
# - A "Schedule Category & Name" line at y~94 carries the form/section title
# - Activities are printed in bold at x~167.7, usually following timepoint/line metadata
# - The Activity is the field label; it may wrap across multiple lines
# - Answer lines (starting with "O" or other fill-in patterns) and technical annotations
#   ([QSORRES], etc.) sit below the Activity and are NOT field names
# Strategy: extract the form name from "Schedule Category & Name", then collect each
# Activity in bold at x~167.7 as a field_name, skipping answer options and annotations.

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
            if line.bold and 'Schedule Category & Name:' in line.text:
                # Next line or continuation should have the form name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # The form name is the non-bold text after "Schedule Category & Name:"
                    if not next_line.bold and next_line.y0 > line.y0 - 5 and next_line.y0 < line.y0 + 20:
                        form_text = next_line.text.strip()
                        # Clean up version suffixes if any
                        if form_text and not form_text.startswith('QSC'):
                            # Sometimes the schedule name is on same line after colon
                            pass
                        else:
                            current_form = form_text
                # Also check if it's on the same line after the colon
                if ':' in line.text:
                    parts = line.text.split(':', 1)
                    if len(parts) > 1 and parts[1].strip():
                        # Inline form name
                        pass
                break
        
        # Collect Activity field names
        # Activities are bold lines at x~167.7, between y~133 and y~720
        # Skip: headers (y < 120), answer options (starting with "O "), technical annotations in brackets
        activity_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Activity detection: bold, x between 160-175, y > 120, not an answer/header
            if (line.bold and 
                160 < line.x0 < 175 and 
                line.y0 > 120 and 
                line.y0 < 720 and
                not line.text.startswith('Answer(s):') and
                not line.text.startswith('Comment:') and
                not line.text.startswith('Staff Initials:') and
                not line.text.startswith('Timepoint') and
                not line.text.startswith('Activity') and
                not line.text.startswith('Line #') and
                not line.text.startswith('Barcode:')):
                
                # This is likely an activity/field label
                # Collect continuation lines (same x range, consecutive y)
                field_parts = [line.text.strip()]
                j = i + 1
                last_y = line.y1
                
                while j < len(lines):
                    next_line = lines[j]
                    # Continuation: same x area, bold, within ~15pt of last line
                    if (next_line.bold and 
                        160 < next_line.x0 < 175 and 
                        next_line.y0 - last_y < 15 and
                        not next_line.text.startswith('Answer(s):') and
                        not next_line.text.startswith('Comment:') and
                        not next_line.text.startswith('Staff Initials:') and
                        not next_line.text.startswith('Barcode:')):
                        field_parts.append(next_line.text.strip())
                        last_y = next_line.y1
                        j += 1
                    else:
                        break
                
                field_name = ' '.join(field_parts)
                
                # Filter out non-field patterns
                # Skip lines that are actually metadata or structure
                if (field_name and 
                    not re.match(r'^O\s+', field_name) and  # Answer option
                    not re.match(r'^\[.*\]', field_name) and  # Technical annotation
                    not re.match(r'^Day \d+', field_name) and  # Timepoint (sometimes bold)
                    not re.match(r'^\d+\.\d+', field_name) and  # Line numbers
                    not re.match(r'^_+\s*-\s*_+', field_name) and  # Date/time templates
                    'SAS:[Name=' not in field_name and
                    field_name not in ['Timepoint', 'Activity', 'Line #'] and
                    len(field_name) > 1):
                    
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
