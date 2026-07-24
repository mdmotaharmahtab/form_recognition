```python
# This CRF document has multiple layout families:
# - Family A/B: table of contents (non-data pages)
# - Family C: standard single-column forms with a large blue title at y~153, fields below
# - Family D: similar structure to C
# - Family E/F/G: multi-column tables with "Row N" labels and complex nested structures
# The form title is the large blue text (size 16.5, color #004c99) near the top.
# Fields are black text at size 9.0 that are NOT red (machine codes), NOT bold subsection
# headers when standalone, and NOT answer options or table column headers.
# Strategy: extract the blue title as form_name, then find data-entry labels by filtering
# out red annotations, option values, and structural elements using geometry and context.

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form title: large blue text (size ~16-17, color #004c99)
        form_title = None
        for line in lines:
            if line.size >= 15.5 and line.non_black and '#004c99' in str(line.text):
                # Clean up the title
                form_title = line.text.strip()
                break
        
        if form_title:
            current_form = form_title
        
        # Skip TOC pages (families A/B) - they have many colored links
        colored_count = sum(1 for line in lines if line.non_black and line.size >= 14)
        if colored_count > 10:
            continue
        
        # Process fields
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip red machine annotations (TYPE:, VISIBILITY:, field codes in brackets)
            if line.non_black and '#ff0000' in str(line.text):
                i += 1
                continue
            
            # Skip page numbers
            if 'Page' in line.text and 'of 1083' in line.text:
                i += 1
                continue
            
            # Skip the form title itself
            if line.size >= 15.5 and line.non_black:
                i += 1
                continue
            
            # Skip very small text (likely annotations)
            if line.size < 8.5:
                i += 1
                continue
            
            # Skip bold subsection headers that are NOT questions (like "Of Childbearing Potential")
            # but keep bold text that forms actual questions
            if line.bold and line.size <= 9.5:
                # Check if it's a section header (short, no question mark, all caps pattern)
                text = line.text.strip()
                if text and not text.endswith('?') and len(text.split()) <= 6:
                    # Likely a subsection header, skip
                    if not any(keyword in text.lower() for keyword in ['subject', 'were', 'was', 'did', 'does', 'has', 'have', 'is']):
                        i += 1
                        continue
            
            # Main field detection: black text, size 9-11
            if not line.non_black and 8.5 <= line.size <= 11.5 and line.text.strip():
                text = line.text.strip()
                
                # Skip machine codes in brackets
                if text.startswith('[') and text.endswith(']'):
                    i += 1
                    continue
                
                # Skip "Row N" labels
                if re.match(r'^Row\s+\d+$', text):
                    i += 1
                    continue
                
                # Skip answer options (Yes/No/NA/Positive/Negative/etc at right side)
                if line.x0 > 400 and text in ['Yes', 'No', 'N/A', 'NA', 'Positive', 'Negative', 'Not Done', 
                                               'Met', 'Not Met', 'Collected', 'Not Collected', 'Scan']:
                    i += 1
                    continue
                
                # Skip table column headers (at top, y < 170)
                if line.y0 < 170 and text in ['Sample', 'Status', 'Timepoint', 'Result', 'Test', 
                                               'Criteria', 'Met/Not Met', 'Lifetime', 'Past 3 Month',
                                               'Past 6 Month', 'Suicidal Ideation', 'Suicidal Behaviour',
                                               'Time of', 'Collection', 'Barcode', 'Number', 'Backup',
                                               'Reason not done', 'Date of Collection', 'Time of Collection',
                                               'Intensity of Ideation', 'Since Last Visit']:
                    i += 1
                    continue
                
                # Skip enumeration list items (test names, assay names in middle of page)
                if 300 < line.x0 < 400 and line.y0 > 200:
                    # These are likely option values in a list
                    i += 1
                    continue
                
                # Check if this is a multi-line field label (join continuations)
                field_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Continue if next line is close in y, similar x, black, not red annotation
                    if (not next_line.non_black and 
                        abs(next_line.x0 - line.x0) < 20 and 
                        next_line.y0 - lines[j-1].y0 < 20 and
                        8.5 <= next_line.size <= 11.5 and
                        next_line.text.strip() and
                        not next_line.text.strip().startswith('[')):
                        
                        # Check if it looks like a continuation (lowercase start or no capitals)
                        cont_text = next_line.text.strip()
                        if cont_text[0].islower() or not cont_text.startswith('Row'):
                            field_text += ' ' + cont_text
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # Final filtering: skip if too short or looks like junk
                if len(field_text) < 3:
                    i = j if j > i + 1 else i + 1
                    continue
                
                # Skip obvious non-fields
                skip_patterns = [
                    r'^\(\d+\)',  # Enumeration like "(1)", "(2)"
                    r'^•$',  # Bullet point
                    r'^\d+\.$',  # Numbered list item like "1."
                ]
                if any(re.match(pat, field_text) for pat in skip_patterns):
                    i = j if j > i + 1 else i + 1
                    continue
                
                # Skip copyright and citation text
                if '©' in field_text or 'Columbia' in field_text or 'Oquendo' in field_text:
                    i = j if j > i + 1 else i + 1
                    continue
                
                # This looks like a valid field
                results.append({
                    "form_name": current_form,
                    "field_name": field_text,
                    "page": page_num
                })
                
                i = j if j > i + 1 else i + 1
            else:
                i += 1
    
    return results
```
