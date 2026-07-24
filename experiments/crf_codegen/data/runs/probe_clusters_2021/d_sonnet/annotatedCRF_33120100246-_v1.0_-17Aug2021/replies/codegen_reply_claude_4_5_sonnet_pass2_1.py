```python
# This CRF document contains multiple layout families:
# - Family A: Table of contents page (page 1)
# - Family B: Continuation of table of contents (pages 2-5)
# - Family C: Enumerated option lists for lab abnormalities (pages 46, 50, etc.)
# - Family D: Lab results review with yes/no questions and option lists (pages 51-65)
# - Family E: Inclusion/Exclusion criteria and C-SSRS forms with detailed questions (pages 84-164)
# 
# Strategy: Extract form titles from large blue text (sz ~14.4, color #004c99 or similar).
# Field labels are regular black text at smaller sizes (~7.8-9.2), often followed by
# option values or input boxes. Ignore red text (machine codes in brackets like [LBCCS1]).
# Handle multi-line labels by joining continuation lines based on y-coordinate proximity.

import re
from collections import defaultdict

def extract(pages):
    records = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form title: large blue text (size >= 13, color code starting with #)
        form_name = ""
        for line in lines:
            if line.size >= 13.0 and line.non_black and not line.text.startswith('['):
                # Clean up the text
                text = line.text.strip()
                # Skip table of contents entries (they have leading numbers like "3.1. ")
                if not re.match(r'^\d+\.', text):
                    form_name = text
                    break
        
        # Group lines by y-coordinate to identify multi-line labels
        y_groups = defaultdict(list)
        for line in lines:
            y_key = round(line.y0 / 15) * 15  # Group lines within ~15 points
            y_groups[y_key].append(line)
        
        # Process lines to extract fields
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip machine codes (red text in brackets)
            if line.non_black and line.text.startswith('['):
                i += 1
                continue
            
            # Skip page numbers and headers (very small text or top of page)
            if line.size < 7.0 or line.y0 < 40:
                i += 1
                continue
            
            # Skip form titles (already captured)
            if line.size >= 13.0 and line.non_black:
                i += 1
                continue
            
            # Skip "Row N" labels (structural markers)
            if re.match(r'^Row\s+\d+$', line.text.strip()):
                i += 1
                continue
            
            # Skip option values (they typically appear in a specific x-range on the right)
            text = line.text.strip()
            if line.x0 > 300 and text in ['Yes', 'No', 'N/A', 'Met', 'Not Met', 'Negative', 'Positive']:
                i += 1
                continue
            
            # Skip column headers in tables
            if line.bold and line.y0 < 120 and text in ['Criteria', 'Met/Not Met', 'Since Last Visit', 'Suicidal Behaviour']:
                i += 1
                continue
            
            # Check if this is a potential field label
            is_potential_field = False
            
            # 1. Questions ending with "?"
            if text.endswith('?'):
                is_potential_field = True
            
            # 2. Descriptive text with colon
            elif text.endswith(':') and len(text) > 5:
                is_potential_field = True
            
            # 3. Multi-word descriptive phrases (likely labels)
            elif len(text.split()) >= 3 and not text.startswith('\\') and line.size >= 7.5:
                is_potential_field = True
            
            # 4. Text starting with number indicators like "\1.\"
            elif re.match(r'\\\d+\.\\.+', text):
                is_potential_field = True
            
            # Skip if not a potential field
            if not is_potential_field:
                i += 1
                continue
            
            # Start building the field label (may span multiple lines)
            field_parts = [text]
            j = i + 1
            
            # Look ahead for continuation lines (within ~20 points vertically)
            while j < len(lines):
                next_line = lines[j]
                y_diff = next_line.y0 - line.y0
                
                # Stop if we've moved too far down
                if y_diff > 100:
                    break
                
                # Stop if we hit a machine code
                if next_line.non_black and next_line.text.startswith('['):
                    break
                
                # Stop if we hit option values
                if next_line.x0 > 300 and next_line.text.strip() in ['Yes', 'No', 'N/A', 'Met', 'Not Met']:
                    break
                
                # Stop if we hit a new form title
                if next_line.size >= 13.0 and next_line.non_black:
                    break
                
                # Stop if we hit a "Row N" marker
                if re.match(r'^Row\s+\d+$', next_line.text.strip()):
                    break
                
                # Check if this line continues the label
                next_text = next_line.text.strip()
                if (next_line.x0 < 300 and  # Left side of page
                    next_line.size >= 7.0 and  # Reasonable font size
                    len(next_text) > 2 and  # Not just punctuation
                    y_diff < 20 and  # Close enough vertically
                    not next_line.non_black):  # Not colored (machine code)
                    
                    # Likely a continuation line
                    field_parts.append(next_text)
                    j += 1
                else:
                    break
            
            # Join all parts into one field label
            field_label = ' '.join(field_parts)
            
            # Clean up the field label
            field_label = re.sub(r'\s+', ' ', field_label)  # Normalize whitespace
            field_label = re.sub(r'^\\\d+\\.\\', '', field_label)  # Remove leading "\1.\"
            field_label = field_label.strip()
            
            # Skip if field label is too short or looks like junk
            if len(field_label) < 5:
                i = j
                continue
            
            # Skip common non-field patterns
            skip_patterns = [
                r'^If (Yes|No)',
                r'^Total number',
                r'^describe$',
                r'^Pack Version$',
                r'^CHANGE HISTORY$',
                r'^SCHEDULE OF ASSESSMENT$',
                r'^PAGES$',
            ]
            if any(re.match(pattern, field_label, re.IGNORECASE) for pattern in skip_patterns):
                i = j
                continue
            
            # Add the record
            records.append({
                "form_name": form_name,
                "field_name": field_label,
                "page": page_num
            })
            
            i = j
    
    return records
```
