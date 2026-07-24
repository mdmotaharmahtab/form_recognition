```python
import re

def extract(pages):
    records = []
    current_form_name = ""
    
    for page_index, lines in pages:
        page_num = page_index + 1
        
        # Identify the form name: large blue header (sz ~14.0+, color #004c99 or similar)
        form_name = ""
        for line in lines:
            if line.size >= 13.0 and line.size <= 16.0 and line.non_black:
                # Check if it's a blue header (not red technical codes)
                # Blue headers are typically #004c99 or similar
                if not re.search(r'#ff0000|#0000ee', line.text, re.IGNORECASE):
                    # Exclude TOC-like entries and schedule headers
                    if not re.match(r'^\d+\.\d+\.', line.text) and \
                       not line.text.startswith('CHANGE HISTORY') and \
                       not line.text.startswith('SCHEDULE OF ASSESSMENT') and \
                       not line.text.startswith('PAGES'):
                        form_name = line.text.strip()
                        current_form_name = form_name
                        break
        
        # If no form name found on this page, use the previous one
        if not form_name and current_form_name:
            form_name = current_form_name
        
        # Skip TOC pages (family A) - they have many blue links
        blue_link_count = sum(1 for line in lines if line.non_black and 
                              re.match(r'^\d+\.\d+\.', line.text))
        if blue_link_count > 10:
            continue
        
        # Skip schedule/assessment table pages (families B-C)
        # These have many lines with blue text (#0000ee) and are structured as tables
        blue_ee_count = sum(1 for line in lines if '#0000ee' in str(line.non_black))
        if blue_ee_count > 15:
            continue
        
        # Detect if this is a repeatable row form (family F) by looking for column headers
        # Column headers are typically positioned horizontally at similar y-coordinates
        # and appear near the top of the form content
        column_headers = []
        for i, line in enumerate(lines):
            text = line.text.strip()
            # Column headers are black text, medium size, positioned horizontally
            if not line.non_black and line.size >= 7.0 and line.size <= 10.0:
                # Look for typical column header patterns
                if text and len(text) > 2 and len(text) < 100:
                    # Check if there are other similar lines at similar y-coordinate
                    similar_y_lines = [l for l in lines if abs(l.y0 - line.y0) < 5 and 
                                      not l.non_black and l.size >= 7.0 and l.size <= 10.0]
                    if len(similar_y_lines) >= 3:
                        # This looks like a row of column headers
                        column_headers.append((line.y0, text, line.x0))
        
        # If we found column headers, extract them as fields
        if column_headers:
            # Group headers by y-coordinate (same row)
            header_rows = {}
            for y, text, x in column_headers:
                y_key = round(y / 5) * 5  # Group by 5-point buckets
                if y_key not in header_rows:
                    header_rows[y_key] = []
                header_rows[y_key].append((x, text))
            
            # Extract headers from the first header row found
            for y_key in sorted(header_rows.keys()):
                headers = sorted(header_rows[y_key], key=lambda h: h[0])
                for x, text in headers:
                    # Skip structural markers
                    if re.match(r'^Row \d+$', text, re.IGNORECASE):
                        continue
                    if text.startswith('(Repeatable row'):
                        continue
                    # Skip position labels that are structural, not data fields
                    if text in ['Standing', 'Supine', 'Sitting']:
                        continue
                    # Skip calculated/derived fields (not data entry)
                    if 'Difference between' in text:
                        continue
                    
                    if form_name and text:
                        records.append({
                            "form_name": form_name,
                            "field_name": text,
                            "page": page_num
                        })
                break  # Only process first header row
        
        # Extract fields from standard field-bearing pages (families D-E)
        # Fields are black text labels, not red technical codes
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip red technical codes (machine codes like [VSSUVTIM], [TYPE: ...])
            if line.non_black:
                i += 1
                continue
            
            text = line.text.strip()
            
            # Skip technical codes in brackets
            if re.match(r'^\[.*\]$', text):
                i += 1
                continue
            
            # Skip page numbers, headers, footers
            if re.match(r'^\d+$', text) and line.size < 9.0:
                i += 1
                continue
            
            # Skip "Row N" labels (these are structural markers, not fields)
            if re.match(r'^Row \d+$', text, re.IGNORECASE):
                i += 1
                continue
            
            # Skip repeatable row instructions
            if text.startswith('(Repeatable row'):
                i += 1
                continue
            
            # Skip answer options (Yes/No, enumeration values) when positioned to the right
            if text in ['Yes', 'No'] and line.x0 > 400:
                i += 1
                continue
            
            # Skip enumeration option lists (numbered options like "(1) ...", "(2) ...")
            if re.match(r'^\(\d+\)', text):
                i += 1
                continue
            
            # Skip "If Yes" prompts when they appear as standalone short text
            if re.match(r'^If (Yes|No)$', text, re.IGNORECASE):
                i += 1
                continue
            
            # Skip position labels that are structural (Standing, Supine, etc.)
            if text in ['Standing', 'Supine', 'Sitting'] and line.x0 < 200:
                i += 1
                continue
            
            # Skip calculated/derived field labels
            if 'Difference between' in text:
                i += 1
                continue
            
            # Skip contact status labels that are structural markers
            if text in ['Final Contact', 'First Failed Attempt', 'Second Failed Attempt', 
                       'Third Failed Attempt']:
                i += 1
                continue
            
            # Identify field labels: black text, reasonable size (7-11pt)
            if line.size >= 7.0 and line.size <= 11.0:
                # Skip empty lines
                if not text:
                    i += 1
                    continue
                
                # Skip pure descriptive text (explanations, notes)
                if len(text) > 200:
                    i += 1
                    continue
                
                # Skip very short non-descriptive text
                if len(text) < 3:
                    i += 1
                    continue
                
                # Skip pure instruction or note text
                if text.startswith('Note:') or text.startswith('Instructions:'):
                    i += 1
                    continue
                
                # Skip incomplete sentence fragments that end with prepositions or articles
                if re.search(r'\b(the|to|of|in|on|at|for)$', text, re.IGNORECASE):
                    i += 1
                    continue
                
                # Collect multi-line field labels
                field_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Continue if next line is a continuation (similar x, close y, black, not code)
                    if not next_line.non_black and \
                       abs(next_line.x0 - line.x0) < 20 and \
                       next_line.y0 - lines[j-1].y0 < 20 and \
                       not re.match(r'^\[.*\]$', next_line.text.strip()) and \
                       next_line.size >= 7.0 and next_line.size <= 11.0:
                        field_text += ' ' + next_line.text.strip()
                        j += 1
                    else:
                        break
                
                # Clean up field text
                field_text = ' '.join(field_text.split())
                
                # Skip if still ends with incomplete fragment
                if re.search(r'\b(the|to|of|in|on|at|for)$', field_text, re.IGNORECASE):
                    i = j
                    continue
                
                # Add the field if we have a form name
                if form_name and field_text and len(field_text) >= 3:
                    records.append({
                        "form_name": form_name,
                        "field_name": field_text,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return records
```