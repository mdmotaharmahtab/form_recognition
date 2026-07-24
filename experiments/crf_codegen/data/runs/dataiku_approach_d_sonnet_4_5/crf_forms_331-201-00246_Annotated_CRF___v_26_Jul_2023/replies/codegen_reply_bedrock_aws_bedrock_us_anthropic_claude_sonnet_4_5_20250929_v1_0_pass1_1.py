```python
"""
This CRF document contains multiple layout families:
- Family A: Table of contents / index page
- Family B: Continuation of table of contents
- Family C: Standard form pages with a blue form title (sz=16.5, color=#004c99) at top,
           followed by field labels in black (sz=9.0) with technical annotations in red
- Family D: Similar to C but with enumeration lists (e.g., dropdown options)
- Family E: Table-based forms (e.g., C-SSRS) with column headers and row-based fields

Strategy:
1. Skip pages 1-2 (table of contents, identified by large colored section numbers)
2. For all other pages, extract the form title (large blue text, sz>=16.0, color=#004c99)
3. Extract field labels (black text, sz=9.0, not bold or selectively bold, not in red)
4. Filter out technical annotations (red text with brackets like [TYPE:...])
5. Filter out answer options (Yes/No/NA in gray #999999)
6. Filter out enumeration values that are part of dropdown lists
7. Handle multi-line field labels by joining continuation lines
"""

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip table of contents pages (pages 1-2)
        if page_num <= 2:
            continue
        
        # Find form title: large blue text (sz >= 16.0, color #004c99)
        form_name = ""
        for line in lines:
            if line.size >= 16.0 and line.non_black and '#004c99' in str(line.text):
                # Extract just the text, not technical codes
                text = line.text.strip()
                if not text.startswith('[') and not text.endswith(']'):
                    form_name = text
                    break
        
        # Extract field labels
        field_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip if it's a technical annotation (red text with brackets)
            if line.non_black and '[' in line.text:
                i += 1
                continue
            
            # Skip if it's the form title itself
            if line.size >= 16.0:
                i += 1
                continue
            
            # Skip page numbers
            if 'Page' in line.text and 'of 1085' in line.text:
                i += 1
                continue
            
            # Skip answer options (gray text with Yes/No/NA)
            if line.non_black and line.text.strip() in ['Yes', 'No', 'NA', 'N/A']:
                i += 1
                continue
            
            # Field labels are typically black, size ~9.0
            if not line.non_black and 8.5 <= line.size <= 10.0:
                text = line.text.strip()
                
                # Skip empty lines
                if not text:
                    i += 1
                    continue
                
                # Skip technical markers
                if text.startswith('[') and text.endswith(']'):
                    i += 1
                    continue
                
                # Skip section headers that are just bold labels without questions
                if line.bold and len(text) < 50 and text in ['Not of Childbearing Potential', 
                                                               'Of Childbearing Potential',
                                                               'Suicidal Behaviour']:
                    i += 1
                    continue
                
                # Skip row labels like "Row 1", "Row 2", etc.
                if text.startswith('Row ') and text[4:].strip().isdigit():
                    i += 1
                    continue
                
                # Skip table column headers
                if text in ['Sample', 'Timepoint', 'Sample Status', 'Time of', 'Barcode', 
                           'Backup', 'Collection', 'Number', 'Lifetime', 'Past 6 Month']:
                    i += 1
                    continue
                
                # Skip enumeration list items (dropdown options)
                # These typically appear at x > 300 and are indented options
                if line.x0 > 300 and not text.endswith('?') and not text.endswith(':'):
                    # Check if this looks like a list item
                    if text in ['Hematocrit', 'Hemoglobin', 'Albumin', 'Alkaline phosphatase',
                               'ALT', 'AST', 'Calcium', 'Predose', '1h postdose', '2h postdose',
                               'As per protocol', 'Adverse Event', 'Dosing error', 'Collected',
                               'Not Collected']:
                        i += 1
                        continue
                
                # Skip bullet points
                if text == '•':
                    i += 1
                    continue
                
                # This looks like a field label
                # Check if next lines are continuations (similar x position, not red)
                field_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Stop if we hit a red annotation line
                    if next_line.non_black and '[' in next_line.text:
                        break
                    # Stop if we hit another field (different x position or much larger gap)
                    if abs(next_line.x0 - line.x0) > 20:
                        break
                    if next_line.y0 - lines[j-1].y0 > 30:
                        break
                    # Stop if we hit a form title
                    if next_line.size >= 16.0:
                        break
                    # Stop if we hit answer options
                    if next_line.non_black and next_line.text.strip() in ['Yes', 'No', 'NA', 'N/A']:
                        break
                    # This is a continuation line
                    if not next_line.non_black and 8.5 <= next_line.size <= 10.0:
                        cont_text = next_line.text.strip()
                        if cont_text and not cont_text.startswith('['):
                            field_text += ' ' + cont_text
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # Clean up the field text
                field_text = field_text.strip()
                
                # Skip if it's just a technical note
                if field_text.startswith('**') or field_text.startswith('©'):
                    i = j
                    continue
                
                # Add the field
                if field_text and form_name:
                    results.append({
                        "form_name": form_name,
                        "field_name": field_text,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return results
```