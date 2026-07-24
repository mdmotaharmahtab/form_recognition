```python
# This CRF document contains multiple layout families:
# - Family A: Table of contents / index pages
# - Family B: Continuation of table of contents
# - Family C: Schedule of assessments tables with visit/page mappings
# - Family D: C-SSRS cover/disclaimer page
# - Family E: C-SSRS question pages with intensity ratings
# - Family F: Miscellaneous field pages with column headers
# The main data-entry fields are in families E and F, with form names appearing
# as large blue headers (sz ~16.5, color #004c99). We extract field labels from
# the left column and avoid answer options/technical codes.

import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form name: large blue header (sz >= 15, color #004c99 or similar blue)
        form_name = ""
        for line in lines:
            if line.size >= 15.0 and line.non_black and '#004c' in str(line):
                # Extract form name from blue headers
                text = line.text.strip()
                if text and not re.match(r'^\d+\.', text):  # Not a numbered item
                    form_name = text
                    break
        
        # If no large blue header, look for medium-sized blue headers
        if not form_name:
            for line in lines:
                if 14.0 <= line.size < 15.0 and line.non_black:
                    text = line.text.strip()
                    if text and len(text) > 3:
                        form_name = text
                        break
        
        # Extract fields from the page
        # Look for field labels in the left column (x < 450)
        # Avoid red text (technical codes), avoid answer options
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip technical annotations (red text, brackets)
            if line.non_black or '[' in line.text or ']' in line.text:
                i += 1
                continue
            
            # Skip page numbers
            if re.match(r'^Page \d+ of \d+', line.text):
                i += 1
                continue
            
            # Skip headers/column labels that appear at top of page
            if line.y0 < 150 and line.bold and line.x0 > 400:
                i += 1
                continue
            
            # Look for field labels: left-aligned, reasonable size, not bold headers
            if line.x0 < 450 and 8.0 <= line.size <= 12.0:
                text = line.text.strip()
                
                # Skip empty, very short, or numeric-only text
                if not text or len(text) < 3:
                    i += 1
                    continue
                
                # Skip pure numbers, dates, times
                if re.match(r'^[\d\s\-:/.]+$', text):
                    i += 1
                    continue
                
                # Skip common table headers
                if text in ['Row', 'Sample', 'Timepoint', 'Sample Status', 
                           'Time of', 'Collection', 'Barcode', 'Number', 'Backup',
                           'Lifetime', 'Past 3 Month', 'Since Last Visit',
                           'Intensity of Ideation', 'Visit Num', 'Visit Label',
                           'Page Num', 'Page Label', 'Dynamic?', 'Description of Dynamic',
                           'ber', 'Were you able to contact the Subject?',
                           'Date of Contact/Attempt', 'Type of Contact',
                           'Method of Contact', 'Date of Admission in clinic',
                           'Time of Admission in clinic']:
                    i += 1
                    continue
                
                # Skip row labels like "Row 1", "Row 2", etc.
                if re.match(r'^Row \d+$', text):
                    i += 1
                    continue
                
                # Skip schedule section headers
                if text.startswith('Schedule_'):
                    i += 1
                    continue
                
                # Skip "Log Pages", "Unscheduled Visits", etc.
                if text in ['Log Pages', 'Unscheduled Visits', 'Unscheduled Pages']:
                    i += 1
                    continue
                
                # Check if this looks like a field label (question or label text)
                # Field labels are typically longer phrases, not single words
                if len(text) > 10 or (len(text.split()) >= 2 and not line.bold):
                    # Check if next few lines continue the question (wrapping)
                    full_text = text
                    j = i + 1
                    while j < len(lines) and j < i + 5:
                        next_line = lines[j]
                        # Check if continuation: similar x position, close y, not red
                        if (abs(next_line.x0 - line.x0) < 20 and 
                            next_line.y0 - lines[j-1].y0 < 20 and
                            not next_line.non_black and
                            '[' not in next_line.text):
                            next_text = next_line.text.strip()
                            # Stop if we hit answer options or technical text
                            if (next_text.startswith('(') or 
                                re.match(r'^\d+\)', next_text) or
                                next_text.startswith('[')):
                                break
                            # Append continuation
                            if next_text and len(next_text) > 2:
                                full_text += ' ' + next_text
                                j += 1
                            else:
                                break
                        else:
                            break
                    
                    # Clean up the field name
                    full_text = re.sub(r'\s+', ' ', full_text).strip()
                    
                    # Final validation: not an answer option pattern
                    if not re.match(r'^\(\d+\)', full_text):
                        results.append({
                            "form_name": form_name,
                            "field_name": full_text,
                            "page": page_num
                        })
                    
                    i = j
                    continue
            
            i += 1
    
    return results
```