STRATEGY:

This revision addresses the specific extraction failures while maintaining existing coverage:

1. **Form title handling**: Continue carrying forward the current form title across pages. Prefer large titles (y~73.9, size>15), fall back to small bold titles (y~48.5), and persist the last-seen title for pages without one.

2. **Cluster 2 pages (variable definition metadata)**: These pages show export codes (like CSS0218) in column ~235 with data types in column ~390. They are NOT data-entry forms but metadata tables. The existing skip logic for `has_export_codes` should catch them, but needs refinement to check the correct x-coordinate range and ensure we're not skipping actual forms.

3. **Page 34 (MGH ATRQ) issues**:
   - Missing fields like "Taken during THIS current episode", "Minimally adequate dose", etc. are in the main content area
   - False extractions like "Yes No" and split labels ("Medication, Minimally adequate dose level, Minimal" / "dose at optional level") occur because the header row parsing is too aggressive
   - Need to extract bold labels from the left column (x<300) that are NOT in header rows, and avoid extracting concatenated answer options

4. **Page 46 (Breath Alcohol) issues**:
   - Missing "Test", "Test Date", "Test Time", "Result", "Comments" - these are column headers in a table
   - False extractions "Alcohol Breath Test", "Urine Cotinine" are test names from the leftmost column, not field labels
   - Need to recognize this as a table with column headers and extract those headers, not the row values

5. **Page 53 (Vital Signs) issues**:
   - Missing many fields like "Repetition Number", "Vital Signs Date", "Position Time", etc.
   - False extraction "Yes No" from header
   - Need better extraction of all bold labels in the content area, not just those matching specific patterns

6. **Page 512 (ECG) issues**:
   - Similar to page 53 - missing actual field labels, extracting concatenated text from headers
   - The concatenated string "Position Time ECG Time Interpretation..." suggests we're extracting a whole header row as one field

7. **Page 604 issues**:
   - Extracting concatenated header text as single fields
   - Need to split header rows more carefully when they contain multiple field labels

**Structural approach**:
- Extract column headers from table layouts (bold text at y~95-105 or y~50-60) by splitting on spacing/position
- Extract bold labels from left content area (x<300, y>110) that are NOT simple answers or machine codes
- Skip metadata pages by checking for export code pattern at x~235 AND data type keywords at x~390
- For header rows with multiple fields, split them spatially rather than just on bracketed numbers
- Avoid extracting test/row names from leftmost table columns - only extract column headers

```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_num, lines in pages:
        page_form = None
        
        # Look for form title - prefer the larger one around y=73.9
        large_title = None
        small_title = None
        
        for line in lines:
            # Large title around y=73.9, size ~17
            if 70 < line.y0 < 80 and line.size > 15:
                large_title = line.text.strip()
            # Small bold title around y=48.5
            elif 45 < line.y0 < 52 and line.bold and line.size > 7 and line.size < 9:
                text = line.text.strip()
                # Skip machine codes (all caps/numbers/underscores)
                if not re.match(r'^[A-Z0-9_-]+$', text):
                    small_title = text
        
        # Use large title if available, otherwise small title
        if large_title:
            page_form = large_title
        elif small_title:
            page_form = small_title
        
        # Update current form if we found one on this page
        if page_form:
            current_form = page_form
        
        # Extract fields based on layout patterns
        fields = extract_fields_from_page(lines, page_num)
        
        # Add form name to all extracted fields
        for field in fields:
            field['form_name'] = current_form
            results.append(field)
    
    return results

def extract_fields_from_page(lines, page_num):
    fields = []
    
    # Check for variable definition layout (export codes in column ~235 AND data types in column ~390)
    has_export_codes = False
    for line in lines:
        if 230 < line.x0 < 245 and re.match(r'^[A-Z]{3}\d{4}[A-Z]?$', line.text.strip()):
            # Check if there's a data type keyword in the same row at x~390
            for other in lines:
                if abs(other.y0 - line.y0) < 3 and 385 < other.x0 < 395:
                    if any(keyword in other.text for keyword in ['Categorical', 'Number', 'Date', 'Text', 'Time']):
                        has_export_codes = True
                        break
            if has_export_codes:
                break
    
    # Skip variable definition pages - they're metadata, not data-entry forms
    if has_export_codes:
        return fields
    
    # Check for table with column headers
    has_table_headers = any(
        line.bold and 95 < line.y0 < 110 and 
        any(keyword in line.text for keyword in ['Performed', 'Result', 'Date', 'Time', 'Test'])
        for line in lines
    )
    
    # Check for parameter table layout
    has_parameter_table = any(
        line.bold and 'Parameter' in line.text and 50 < line.y0 < 65 
        for line in lines
    )
    
    # Extract based on layout type
    if has_table_headers:
        fields.extend(extract_table_header_fields(lines, page_num))
    elif has_parameter_table:
        fields.extend(extract_parameter_table_fields(lines, page_num))
    
    # Always try to extract standard form fields (bold labels in content area)
    fields.extend(extract_standard_form_fields(lines, page_num))
    
    return fields

def extract_table_header_fields(lines, page_num):
    """Extract column headers from table layouts"""
    fields = []
    
    # Find header rows (bold text at y~95-105)
    header_lines = [l for l in lines if l.bold and 95 < l.y0 < 110]
    
    # Group by y-coordinate (same row)
    header_rows = {}
    for line in header_lines:
        y_key = round(line.y0)
        if y_key not in header_rows:
            header_rows[y_key] = []
        header_rows[y_key].append(line)
    
    # Extract headers from each row
    for y_key, row_lines in header_rows.items():
        # Sort by x position
        row_lines.sort(key=lambda l: l.x0)
        
        for line in row_lines:
            text = line.text.strip()
            
            # Skip very short text
            if len(text) < 3:
                continue
            
            # Skip simple answer options
            if text in ['Yes', 'No', 'Positive', 'Negative']:
                continue
            
            # Skip "Yes No" concatenated
            if text == 'Yes No':
                continue
            
            # Skip machine codes
            if re.match(r'^[A-Z0-9_-]+$', text) and len(text) > 3:
                continue
            
            # Check if this text contains multiple field labels concatenated
            # Split on common patterns
            if ' ' in text and len(text) > 20:
                # Try to split on multiple spaces or position changes
                parts = re.split(r'\s{2,}', text)
                for part in parts:
                    part = part.strip()
                    if len(part) >= 3 and part not in ['Yes', 'No', 'Positive', 'Negative']:
                        fields.append({
                            'field_name': part,
                            'page': page_num + 1
                        })
            else:
                # Single field label
                fields.append({
                    'field_name': text,
                    'page': page_num + 1
                })
    
    return fields

def extract_parameter_table_fields(lines, page_num):
    """Extract fields from parameter table layouts"""
    fields = []
    
    # Find the header row
    header_y = None
    for line in lines:
        if line.bold and 'Parameter' in line.text and 50 < line.y0 < 65:
            header_y = line.y0
            break
    
    if header_y is None:
        return fields
    
    # Get all bold text in the header row area
    header_lines = [l for l in lines if l.bold and abs(l.y0 - header_y) < 3]
    header_lines.sort(key=lambda l: l.x0)
    
    # Extract column headers
    for line in header_lines:
        text = line.text.strip()
        
        # Skip very short text
        if len(text) < 3:
            continue
        
        # Skip simple answers
        if text in ['Yes', 'No']:
            continue
        
        fields.append({
            'field_name': text,
            'page': page_num + 1
        })
    
    return fields

def extract_standard_form_fields(lines, page_num):
    """Extract fields from standard form layouts"""
    fields = []
    
    # Find header row y-coordinates to avoid extracting from them
    header_y_coords = set()
    for line in lines:
        if line.bold and 95 < line.y0 < 110:
            # Check if this looks like a header row
            same_y_bold = [l for l in lines if l.bold and abs(l.y0 - line.y0) < 2]
            if len(same_y_bold) >= 2:
                header_y_coords.add(round(line.y0))
    
    # Look for bold labels in content area
    for i, line in enumerate(lines):
        if not line.bold:
            continue
        
        text = line.text.strip()
        
        # Skip if it's just a bracketed number
        if re.match(r'^\[\d+\]$', text):
            continue
        
        # Skip header area (top of page)
        if line.y0 < 90:
            continue
        
        # Skip if on a header row
        if any(abs(line.y0 - hy) < 2 for hy in header_y_coords):
            continue
        
        # Must be in left content area
        if line.x0 > 350:
            continue
        
        # Skip machine codes
        if re.match(r'^[A-Z0-9_-]+$', text) and len(text) > 3:
            continue
        
        # Skip simple answers
        if text in ['Yes', 'No', 'Positive', 'Negative', 'Yes No', 'Positive Negative']:
            continue
        
        # Skip page identifiers
        if 'MAC186' in text or 'eCRF' in text:
            continue
        
        # Skip very short text
        if len(text) < 3:
            continue
        
        # Remove bracketed numbers from the label
        field_text = re.sub(r'\s*\[\d+\]\s*', ' ', text).strip()
        
        # Skip if nothing left after removing brackets
        if not field_text or len(field_text) < 3:
            continue
        
        # Check for continuation lines
        if i + 1 < len(lines):
            next_line = lines[i + 1]
            # If next line is close, not bold, and aligned, might be continuation
            if (not next_line.bold and 
                abs(next_line.x0 - line.x0) < 50 and 
                next_line.y0 - line.y0 < 15 and
                not re.match(r'^\[\d+\]', next_line.text)):
                continuation = next_line.text.strip()
                # Remove bracketed numbers from continuation
                continuation = re.sub(r'\s*\[\d+\]\s*', ' ', continuation).strip()
                if continuation and len(continuation) > 2:
                    if not re.match(r'^[A-Z0-9_-]+$', continuation):
                        field_text += ' ' + continuation
        
        fields.append({
            'field_name': field_text,
            'page': page_num + 1
        })
    
    return fields
```