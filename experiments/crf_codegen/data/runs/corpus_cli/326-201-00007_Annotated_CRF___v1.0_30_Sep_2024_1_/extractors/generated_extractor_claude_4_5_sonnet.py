import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        current_form = None
        
        # Extract form name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if 'Schedule Category & Name:' in line.text:
                # Form name is on the next line at x~167
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if 150 < next_line.x0 < 185:
                        current_form = next_line.text.strip()
                break
        
        # Skip if no form found
        if not current_form:
            continue
        
        # Define the activity column range (where field labels appear)
        ACTIVITY_COL_MIN = 150
        ACTIVITY_COL_MAX = 185
        
        # Define page content area (below headers, above footers)
        CONTENT_TOP = 110
        CONTENT_BOTTOM = 750
        
        # Collect field names
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for bold text in the activity column
            if (line.bold and 
                ACTIVITY_COL_MIN < line.x0 < ACTIVITY_COL_MAX and 
                line.y0 > CONTENT_TOP and 
                line.y0 < CONTENT_BOTTOM):
                
                # Collect the full text (may span multiple lines)
                field_parts = [line.text.strip()]
                j = i + 1
                last_y = line.y1
                
                # Continue collecting if next lines are part of the same field
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Must be in same column and close vertically
                    if not (ACTIVITY_COL_MIN < next_line.x0 < ACTIVITY_COL_MAX and 
                            next_line.y0 - last_y < 16):
                        break
                    
                    # Must be bold to continue the field label
                    if not next_line.bold:
                        break
                    
                    next_text = next_line.text.strip()
                    
                    # Stop at parenthetical notes/clarifications
                    if next_text.startswith('('):
                        break
                    
                    # Stop at conditional instructions (these are not part of the field label)
                    if re.match(r'^If\s+(yes|no|consumed|\'Yes\'|\'No\')', next_text, re.IGNORECASE):
                        break
                    
                    # Stop at imperative instructions (Update, Please, Record, Ensure, etc.)
                    # These are instructions to staff, not field labels
                    if re.match(r'^(Update|Please|Record|Ensure|Complete|Enter|Specify)\b', next_text, re.IGNORECASE):
                        break
                    
                    # Stop at lowercase list continuations (e.g., "coffee, tea")
                    # Real field labels start with capital letters
                    if next_text and next_text[0].islower():
                        break
                    
                    field_parts.append(next_text)
                    last_y = next_line.y1
                    j += 1
                
                field_name = ' '.join(field_parts)
                
                # Determine if this is a valid field using structural rules
                is_valid = True
                
                # Skip very short fragments (< 3 chars)
                if len(field_name) < 3:
                    is_valid = False
                
                # Skip if ends with a section number pattern (e.g., "Section #1")
                # These are section headers, not fields
                if re.search(r'#\d+$', field_name):
                    is_valid = False
                
                # Skip if it's just a column header pattern
                # Headers are typically single short words with colons
                if re.match(r'^[A-Z][a-z]+:?$', field_name) and len(field_name) < 15:
                    # But allow if it looks like a real question
                    if not field_name.endswith('?'):
                        is_valid = False
                
                # Skip if it's a standalone answer marker (starts with "O ")
                if re.match(r'^O\s+', field_name):
                    is_valid = False
                
                # Skip if it's purely a template pattern (underscores, dashes, colons)
                if re.match(r'^[_\-:\s]+$', field_name):
                    is_valid = False
                
                # Skip if it's purely parenthetical
                if re.match(r'^\(.*\)$', field_name):
                    is_valid = False
                
                # Skip if it's purely bracketed
                if re.match(r'^\[.*\]$', field_name):
                    is_valid = False
                
                # Skip incomplete fragments (ending with conjunctions/punctuation indicating continuation)
                # But keep complete questions
                if not field_name.endswith('?'):
                    if re.search(r'(,\s*$|\s+and$|\s+or$|:$)', field_name):
                        is_valid = False
                
                # Skip imperative instructions (these appear in the activity column but are not fields)
                # They are commands to staff, not data entry labels
                if re.match(r'^(Update|Please|Record|Ensure|Complete|Enter|Specify)\s+', field_name, re.IGNORECASE):
                    is_valid = False
                
                # Add valid field
                if is_valid and field_name:
                    results.append({
                        'form_name': current_form,
                        'field_name': field_name,
                        'page': page_num
                    })
                
                i = j
            else:
                i += 1
    
    return results
