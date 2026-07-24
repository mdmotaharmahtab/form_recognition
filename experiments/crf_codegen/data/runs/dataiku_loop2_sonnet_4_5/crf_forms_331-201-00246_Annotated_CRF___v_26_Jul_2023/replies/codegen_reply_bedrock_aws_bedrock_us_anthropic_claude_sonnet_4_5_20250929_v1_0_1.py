```python
# This CRF document contains multiple form sections with data-entry fields.
# Forms are identified by large blue headings (sz=16.5, color #004c99).
# Fields are questions/labels in black text (sz=9.0) followed by technical codes
# in red (color #ff0000) like [FIELDCODE] or [TYPE: ...]. We extract the black
# question text as field_name, ignoring the red codes and answer options.

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Group lines by y-coordinate to identify rows
        y_groups = defaultdict(list)
        for line in lines:
            y_groups[round(line.y0, 1)].append(line)
        
        for line in lines:
            # Detect form names: large blue headings (sz=16.5, color #004c99)
            if line.size >= 16.0 and line.non_black:
                # Check if it's a blue heading
                if not line.text.startswith('[') and line.text not in ['Supine', 'Standing']:
                    current_form = line.text.strip()
            
            # Detect field labels: black text, size ~9.0, not technical codes
            if (line.size >= 8.5 and line.size <= 10.0 and 
                not line.bold and 
                not line.non_black and
                not line.text.startswith('[')):
                
                text = line.text.strip()
                
                # Skip empty, page numbers, headers, and common non-field text
                if not text:
                    continue
                if re.match(r'^Page \d+ of \d+$', text):
                    continue
                if text in ['Criteria', 'Met/Not Met', 'Sample', 'Timepoint', 
                           'Sample Status', 'Time of Collection', 'Barcode Number',
                           'Test', 'Result', 'Status', 'Reason not done', 
                           'Date of Collection', 'Scan', 'Suicidal Ideation',
                           'Since Last Visit']:
                    continue
                
                # Skip answer options (Yes/No/Met/Not Met/etc at specific x positions)
                if line.x0 > 400 and text in ['Yes', 'No', 'Met', 'Not Met', 
                                               'Positive', 'Negative', 'Not Done',
                                               'Collected', 'Not Collected', 
                                               'Not Applicable']:
                    continue
                
                # Skip row labels like "Row 5", "Row 12", etc.
                if re.match(r'^Row \d+$', text):
                    continue
                
                # Skip technical annotations and codes
                if re.match(r'^\[.*\]$', text):
                    continue
                if re.match(r'^\(.*\)$', text):
                    continue
                
                # Skip pure dates, times, numbers
                if re.match(r'^\d{1,2}[A-Za-z]{3,9}\d{4}$', text):
                    continue
                if re.match(r'^\d+(\.\d+)?$', text):
                    continue
                
                # Skip timepoint options (predose, postdose, etc.)
                if re.match(r'^(N/A|Predose|\d+\.?\d*h postdose)$', text, re.IGNORECASE):
                    continue
                
                # Skip procedure specifications headers
                if text.startswith('Procedures Specifications:'):
                    continue
                
                # Skip descriptive instructions that are not questions
                if text.startswith('Collect vital signs after'):
                    continue
                if text.startswith('Water should not be restricted'):
                    continue
                
                # Valid field: starts with question text or criteria number
                # Criteria fields start with backslash-number pattern
                is_criteria = re.match(r'^\\?\d+\\.', text)
                
                # Questions typically end with '?' or contain 'If', 'Were', 'Date', 'Time'
                is_question = ('?' in text or 
                              text.startswith('If ') or
                              text.startswith('Were ') or
                              text.startswith('Date ') or
                              text.startswith('Time ') or
                              text.startswith('Planned '))
                
                # Check if this line is followed by a red technical code
                has_code_below = False
                for other in lines:
                    if (other.non_black and 
                        other.y0 > line.y0 and 
                        other.y0 < line.y0 + 30 and
                        abs(other.x0 - line.x0) < 50 and
                        other.text.startswith('[')):
                        has_code_below = True
                        break
                
                # Extract if it's a criteria, question, or has a code below
                if is_criteria or is_question or has_code_below:
                    # Clean up the text
                    field_text = text
                    # Remove leading numbering from criteria
                    field_text = re.sub(r'^\\?\d+\\.?\s*', '', field_text)
                    
                    if field_text and current_form:
                        results.append({
                            "form_name": current_form,
                            "field_name": field_text,
                            "page": page_num
                        })
    
    # Deduplicate consecutive identical entries
    deduplicated = []
    prev = None
    for r in results:
        key = (r['form_name'], r['field_name'])
        if key != prev:
            deduplicated.append(r)
            prev = key
    
    return deduplicated
```