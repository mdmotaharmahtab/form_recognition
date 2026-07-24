I'll analyze the issues and fix the extraction program. The main problems are:

1. Capturing continuation lines that are actually parenthetical notes or qualifiers (not separate fields)
2. Capturing wrapped text that isn't part of the field label itself
3. Need better logic to distinguish actual field labels from explanatory text

Let me examine the structure more carefully and rewrite:

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
                
                # Only continue if next line is also bold, same column, and close
                while j < len(lines):
                    next_line = lines[j]
                    # Strict continuation: same x area, bold, close y, not starting with parenthesis
                    if (next_line.bold and 
                        155 < next_line.x0 < 180 and 
                        next_line.y0 - last_y < 16 and
                        not next_line.text.strip().startswith('(')):
                        
                        # Stop if we hit a known field separator pattern
                        next_text = next_line.text.strip()
                        
                        # Stop at parenthetical notes
                        if next_text.startswith('('):
                            break
                        
                        # Stop at "If yes/no" patterns (conditional instructions)
                        if re.match(r'^If\s+(yes|no|consumed|\'Yes\'|\'No\')', next_text, re.IGNORECASE):
                            break
                        
                        # Stop at explicit instructions (Update, Please, Record, etc.)
                        if re.match(r'^(Update|Please|Record|Ensure)\s+', next_text, re.IGNORECASE):
                            break
                        
                        # Stop at list items within questions (e.g., "coffee, tea...")
                        # These typically don't start with capital letter or are short fragments
                        if j > i + 1 and next_text and not next_text[0].isupper() and len(next_text) < 100:
                            # Check if this looks like a list continuation
                            if ',' in next_text or next_text.endswith('and'):
                                break
                        
                        # Stop at measurement units or technical notes
                        if re.match(r'^[\(\[]', next_text):
                            break
                        
                        field_parts.append(next_text)
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
                
                # Skip fields that are purely parenthetical notes
                if re.match(r'^\(.*\)$', field_name):
                    is_valid = False
                
                # Skip fields that are just fragments ending with common list patterns
                if field_name.endswith('?'):
                    # Valid question - keep it
                    pass
                elif field_name.endswith((':','and','or')) or re.search(r',\s*$', field_name):
                    # Fragment - skip
                    is_valid = False
                
                # Skip standalone technical fragments
                if re.match(r'^[a-z][a-z\s,]*$', field_name) and not field_name.endswith('?'):
                    is_valid = False
                
                # Skip measurement specifications without context
                if re.match(r'^\(.*minutes.*\)$', field_name, re.IGNORECASE):
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
