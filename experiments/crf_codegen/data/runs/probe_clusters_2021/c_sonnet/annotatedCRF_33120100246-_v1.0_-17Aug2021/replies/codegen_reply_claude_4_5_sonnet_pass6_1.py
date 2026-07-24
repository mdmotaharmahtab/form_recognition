```python
# This CRF document contains a table of contents (pages 1-2), schedule tables
# (pages 10, 15), and actual data-entry form pages (pages 34, 100, 135, 137,
# 140, 164, 559). The schedule tables list page numbers and page labels (form
# names) in a tabular layout. The form pages contain fields with labels in
# black text and technical annotations in red (#ff0000). Fields may wrap across
# multiple lines. The extraction strategy: (1) detect schedule table pages by
# their "Page Number" / "Page Label" column structure and build a mapping of
# page_num → form_name, (2) on form pages, extract field labels (black text,
# not red annotations), join wrapped lines, and filter out answer options and
# page furniture, (3) assign form names from the page mapping or from
# persistent bold blue headers on the form pages themselves.

import re
from collections import defaultdict

def extract(pages):
    results = []
    
    # Build page_number → form_name mapping from schedule tables
    page_to_form = {}
    for page_idx, lines in pages:
        if not lines:
            continue
        # Schedule tables have "Page Number" / "Page Label" headers and rows with
        # page numbers in black followed by labels in blue (#0000ee or #2477cc)
        has_page_label_header = any(
            'Page Label' in line.text or 'Page label' in line.text 
            for line in lines if line.bold
        )
        if has_page_label_header:
            # Extract rows: page_num (black) followed by label (blue, non_black)
            i = 0
            while i < len(lines):
                line = lines[i]
                # Look for a page number (numeric only, black, not bold)
                if (not line.non_black and not line.bold and 
                    re.match(r'^\d+$', line.text.strip())):
                    page_num = int(line.text.strip())
                    # Next line(s) may be the label (blue text)
                    label_parts = []
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        # Blue text is the label
                        if next_line.non_black and abs(next_line.x0 - line.x0) > 40:
                            label_parts.append(next_line.text.strip())
                            j += 1
                            # Check if there's a continuation on the next line
                            if j < len(lines) and lines[j].non_black and abs(lines[j].x0 - next_line.x0) < 20:
                                continue
                            else:
                                break
                        else:
                            break
                    if label_parts:
                        form_name = ' '.join(label_parts)
                        page_to_form[page_num] = form_name
                    i = j
                else:
                    i += 1
    
    # Process each page for field extraction
    current_form = ""
    for page_idx, lines in pages:
        page_num_1based = page_idx + 1
        
        if not lines:
            continue
        
        # Check if this is a TOC or schedule page (skip field extraction)
        is_toc = any('CHANGE HISTORY' in line.text or 'SCHEDULE OF ASSESSMENT' in line.text 
                     for line in lines if line.size > 13)
        is_schedule = any('Page Label' in line.text or 'Visit Label' in line.text 
                          for line in lines if line.bold)
        
        if is_toc or is_schedule:
            continue
        
        # Look for form name from page mapping
        if page_num_1based in page_to_form:
            current_form = page_to_form[page_num_1based]
        else:
            # Look for a bold blue header (size 14-15, blue color) as form title
            for line in lines:
                if (line.bold and line.non_black and line.size >= 13 and 
                    line.y0 < 200 and len(line.text.strip()) > 3):
                    current_form = line.text.strip()
                    break
        
        # Extract fields: black text that looks like questions/labels
        # Filter out: red text (annotations), answer options (Yes/No on same line),
        # technical codes in brackets, row labels, page numbers
        
        field_candidates = []
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip red text (technical annotations)
            if line.non_black and '#ff0000' in str(line.non_black):
                i += 1
                continue
            
            # Skip if it's a red annotation (detected by color)
            # Skip empty, very short text, or pure numbers
            if (not text or len(text) < 3 or re.match(r'^[\d\.\s]+$', text) or
                text.startswith('[') or text.endswith(']')):
                i += 1
                continue
            
            # Skip answer options (Yes/No on their own, rating scale numbers)
            if text in ['Yes', 'No', 'yes', 'no', 'YES', 'NO']:
                i += 1
                continue
            
            # Skip "Row N" labels
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip page furniture (Pack Version, dates, etc.)
            if line.y0 < 60 and line.size < 10:
                i += 1
                continue
            
            # Skip bold headers that are section labels (not field labels)
            if line.bold and line.size > 12:
                i += 1
                continue
            
            # Candidate field label: black text, reasonable position
            if not line.non_black and line.size >= 7 and line.size <= 10:
                # Join wrapped lines: collect following lines at similar x position
                field_parts = [text]
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Same field if: similar x, not red, close y, not a new question marker
                    if (abs(next_line.x0 - line.x0) < 30 and 
                        not (next_line.non_black and '#ff0000' in str(next_line.non_black)) and
                        next_line.y0 - lines[j-1].y0 < 20 and
                        len(next_line.text.strip()) > 0 and
                        not next_line.text.strip().startswith('[')):
                        # Check if it's a continuation (lowercase start or no question mark end)
                        if (next_line.text[0].islower() or 
                            not field_parts[-1].endswith('?')):
                            field_parts.append(next_line.text.strip())
                            j += 1
                        else:
                            break
                    else:
                        break
                
                field_text = ' '.join(field_parts)
                
                # Filter out non-question patterns
                # Skip if it contains rating scale patterns
                if re.search(r'\(\d+\)', field_text):
                    i = j
                    continue
                
                # Skip if it's describing a concept (not asking)
                if any(keyword in field_text.lower() for keyword in 
                       ['examples are', 'person has', 'when person', 'acts or preparation',
                        'overdose:', 'shooting:', 'jumping:', 'hanging:']):
                    i = j
                    continue
                
                # Valid field if it's a question or clear label
                if (field_text.endswith('?') or field_text.endswith(':') or
                    len(field_text.split()) >= 3):
                    # Remove trailing colons
                    field_text = field_text.rstrip(':')
                    if field_text and field_text not in field_candidates:
                        field_candidates.append(field_text)
                
                i = j
            else:
                i += 1
        
        # Emit records
        for field_name in field_candidates:
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num_1based
            })
    
    return results
```
