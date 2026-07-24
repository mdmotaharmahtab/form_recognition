Looking at the sample pages from cluster 0, I can see they contain **data-entry fields** that my program is currently missing:

- "Diastolic Blood Pressure (mmHg)" 
- "Heart Rate (bpm)"

These are legitimate field names (black text, size 7.8) followed by their field codes in red. My current program is incorrectly skipping these because:

1. The field names are too short (< 15 characters) - my validation requires `len(field_name) >= 15`
2. They don't contain '?', 'contact', or 'subject' - my validation requires one of these

These are valid medical measurement fields that should be extracted. Here's the corrected program:

```python
import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title: large blue text (size ~14, color #004c99 or similar blue)
        for line in lines:
            if line.size >= 13.0 and line.non_black and '#004c99' in str(line):
                # This is likely a form title
                text = line.text.strip()
                if text and not text.startswith('[') and not re.match(r'^\d+\.\d+\.', text):
                    current_form = text
                    break
        
        # Skip TOC pages (family A/B): dense with numbered blue links like "3.1. Visit Date"
        # These have many lines matching pattern: number.number. text in blue
        toc_lines = [l for l in lines if l.non_black and re.match(r'^\d+\.\d+\.', l.text.strip())]
        if len(toc_lines) > 10:
            continue
        
        # Skip metadata-only pages (family C): very few lines, mostly red field codes
        # BUT allow pages with field labels followed by codes (black label + red code pattern)
        non_code_lines = [l for l in lines if not l.text.strip().startswith('[')]
        code_lines = [l for l in lines if l.non_black and l.text.strip().startswith('[')]
        
        # If we have black text lines paired with red code lines, this is data entry
        # Skip only if truly sparse (< 3 non-code lines)
        if len(non_code_lines) < 3 and len(code_lines) < 3:
            continue
        
        # Extract fields from standard form pages
        # Field names are black text, not bold header/label style
        # Field codes in red brackets like [CSS0405C] or [TYPE: ...] are NOT field names
        # Answer options (Yes/No, checkboxes) are NOT field names
        
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty lines
            if not text:
                i += 1
                continue
            
            # Skip field codes (red text in brackets)
            if line.non_black and text.startswith('[') and text.endswith(']'):
                i += 1
                continue
            
            # Skip "Row N" labels (bold black text)
            if line.bold and re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip answer options (gray text with specific values)
            if line.non_black and text in ['Yes', 'No']:
                i += 1
                continue
            
            # Skip headers/metadata at top of page
            if line.y0 < 60 and (line.bold or line.non_black):
                i += 1
                continue
            
            # Potential field label: black text, reasonable size (7-11pt typically)
            # Not a code, not just numbers/dates
            if not line.non_black and 7.0 <= line.size <= 11.0:
                # Check if this looks like a question/field label
                # Relax length constraint for medical measurement fields
                if len(text) < 10:
                    i += 1
                    continue
                
                # Skip pure descriptions of answer options or instructions starting with parentheses
                if text.startswith('(') or text.startswith('If Yes') or text.startswith('If No'):
                    i += 1
                    continue
                
                # Skip known furniture patterns
                if text in ['Pack Version', 'Annotated CRF', 'CHANGE HISTORY', 'SCHEDULE OF ASSESSMENT', 'PAGES']:
                    i += 1
                    continue
                
                # Check if this is a multi-line field name (lines wrap/continue)
                field_parts = [text]
                j = i + 1
                
                # Look ahead for continuation lines (same x position or indented, black, similar size)
                while j < len(lines):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Stop at red field code
                    if next_line.non_black and next_text.startswith('['):
                        break
                    
                    # Stop at next question (similar formatting to current line)
                    if next_line.bold and re.match(r'^Row \d+$', next_text):
                        break
                    
                    # Stop at large gaps or significant format changes
                    if next_line.y0 - lines[j-1].y1 > 20:
                        break
                    
                    # Continuation line: black text, similar size, close vertical spacing
                    if (not next_line.non_black and 
                        7.0 <= next_line.size <= 11.0 and
                        next_line.y0 - lines[j-1].y1 < 15 and
                        len(next_text) > 3 and
                        not next_text.startswith('[')):
                        
                        # Don't absorb answer option lists
                        if next_text in ['Yes', 'No', 'Phone', 'Office Visit', 'Letter', 'Other']:
                            break
                        
                        field_parts.append(next_text)
                        j += 1
                    else:
                        break
                
                # Join multi-line field name
                field_name = ' '.join(field_parts)
                
                # Final validation: reasonable field name
                # Accept if: substantial length OR looks like medical measurement field
                # Medical fields often have units in parentheses: "(mmHg)", "(bpm)", "(kg)", etc.
                is_measurement = re.search(r'\([a-zA-Z/]+\)$', field_name)
                is_question = '?' in field_name
                is_substantial = len(field_name) >= 15
                has_key_terms = any(term in field_name.lower() for term in ['contact', 'subject', 'date', 'time', 'pressure', 'rate', 'weight', 'height', 'temperature'])
                
                # Skip pure instruction text
                if (field_name.startswith('If Yes, Total') or 
                    field_name.startswith('If Yes then please') or
                    re.match(r'^[\d\.\s]+$', field_name)):
                    i = j if j > i + 1 else i + 1
                    continue
                
                # Accept field if it meets criteria
                if is_measurement or is_question or (is_substantial and has_key_terms):
                    results.append({
                        'form_name': current_form,
                        'field_name': field_name,
                        'page': page_num
                    })
                
                i = j if j > i + 1 else i + 1
            else:
                i += 1
    
    return results
```
