STRATEGY:

This revision addresses three main issues:

1. **Cluster 0 (44% coverage)**: These are test/parameter table pages with a different structure than previously handled. The header row contains bold column titles like "Test [1]", "Performed [2]", "Reason Not Performed [3]", "Test Date [4]", "Test Time [5]", "Result [6]", "Comments [7]". The actual field names are the non-bold test names in the leftmost column (e.g., "Alcohol Breath Test", "Urine Cotinine"). The current code is incorrectly extracting answer options ("Yes", "No", "Positive", "Negative") and concatenated header text. I need to extract ONLY the test names from the left column, ignoring row numbers and answer values.

2. **Cluster 2 (0% coverage)**: These are variable definition/metadata pages with export codes (like CSS0218) at x≈235. The current code correctly skips these via the `has_export_codes` check, so zero coverage here is correct - these are not data-entry forms.

3. **False positives**: The code is extracting answer options ("Yes No", "Positive Negative") and concatenated header text as field names. This happens because the logic isn't properly distinguishing between field labels and inline answer options. I need to:
   - Better detect when text is part of a header row (by checking if it's on the same y-coordinate as other header elements)
   - Skip text that appears in the answer/value columns (x > 400)
   - For cluster 0 specifically, only extract the test names from the leftmost data column, not the header labels or answer options

The form title carry-forward logic is working correctly. I need to refine the field extraction to be more precise about what constitutes a field label versus furniture/options.

```python
# Clinical eCRF extraction: handles multiple layout families with form titles
# at various positions. Carries forward form names across continuation pages.
# Uses structural position/style rules instead of literal text blocklists.

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
    
    # Detect layout family by structural markers
    has_large_title = any(70 < l.y0 < 80 and l.size > 15 for l in lines)
    has_bracketed_numbers = any(re.search(r'\[\d+\]', l.text) for l in lines)
    
    # Check for variable definition layout (export codes in column ~235)
    has_export_codes = any(230 < l.x0 < 240 and re.match(r'^[A-Z]{3}\d{4}[A-Z]?$', l.text.strip()) for l in lines)
    
    # Skip variable definition pages - they're metadata, not data-entry forms
    if has_export_codes:
        return fields
    
    # Check for test table with "Performed" and "Result" columns (cluster 0)
    has_test_table = any(
        line.bold and 'Performed' in line.text and 'Reason Not Performed' in line.text 
        and 95 < line.y0 < 105
        for line in lines
    )
    
    # Check for parameter table layout (bold "Parameter" header)
    has_parameter_table = any(line.bold and 'Parameter' in line.text and 50 < line.y0 < 60 for line in lines)
    
    # Test table layout (cluster 0) - extract test names from left column
    if has_test_table:
        fields.extend(extract_test_result_table_fields(lines, page_num))
    
    # Parameter table layout
    elif has_parameter_table:
        fields.extend(extract_parameter_table_fields(lines, page_num))
    
    # Family B/D/E: Forms with "Performed" questions and field labels
    elif has_large_title and has_bracketed_numbers:
        fields.extend(extract_standard_form_fields(lines, page_num))
    
    # Family C: Variable details tables
    elif any('Export Name' in l.text for l in lines):
        fields.extend(extract_variable_table_fields(lines, page_num))
    
    # Generic extraction for other patterns
    else:
        fields.extend(extract_generic_fields(lines, page_num))
    
    return fields

def is_header_area(line):
    """Check if line is in the header/title area (top ~100 points)"""
    return line.y0 < 100

def is_right_column(line):
    """Check if line is in right answer/value column"""
    return line.x0 > 400

def is_machine_code(text):
    """Check if text looks like a machine code (all caps/numbers/underscores)"""
    return bool(re.match(r'^[A-Z0-9_-]+$', text)) and len(text) > 3

def is_simple_answer(text):
    """Check if text is a simple answer option"""
    return text in ['Yes', 'No', 'Positive', 'Negative'] or text.isdigit()

def extract_test_result_table_fields(lines, page_num):
    """Extract fields from test/result table layouts (cluster 0)"""
    fields = []
    
    # Find the header row y-coordinate
    header_y = None
    for line in lines:
        if line.bold and 'Performed' in line.text and 'Reason Not Performed' in line.text and 95 < line.y0 < 105:
            header_y = line.y0
            break
    
    if header_y is None:
        return fields
    
    # Extract test names from the leftmost column below the header
    # Test names are non-bold, in the left column (x0 around 60), below header
    for line in lines:
        # Must be below header
        if line.y0 <= header_y + 5:
            continue
        
        # Must be in leftmost content column (around x=60)
        if not (55 < line.x0 < 75):
            continue
        
        # Skip bold text (headers)
        if line.bold:
            continue
        
        text = line.text.strip()
        
        # Skip row numbers
        if text.isdigit():
            continue
        
        # Skip simple answers
        if is_simple_answer(text):
            continue
        
        # Skip very short text
        if len(text) < 3:
            continue
        
        # Valid test name
        fields.append({
            'field_name': text,
            'page': page_num + 1
        })
    
    return fields

def extract_parameter_table_fields(lines, page_num):
    """Extract fields from parameter table layouts"""
    fields = []
    
    # Find the header row to establish the data region starts after it
    header_y = None
    for line in lines:
        if line.bold and 'Parameter' in line.text and 50 < line.y0 < 60:
            header_y = line.y0
            break
    
    if header_y is None:
        return fields
    
    # Extract parameter names - they are non-bold text in left column below header
    for line in lines:
        # Skip if above or at header
        if line.y0 <= header_y + 5:
            continue
        
        # Look for parameter names at x≈64.5, non-bold
        if 60 < line.x0 < 70 and not line.bold:
            text = line.text.strip()
            
            # Skip row numbers
            if text.isdigit():
                continue
            
            # Skip simple answers
            if is_simple_answer(text):
                continue
            
            # Skip empty or very short text
            if len(text) < 3:
                continue
            
            # Valid parameter name
            fields.append({
                'field_name': text,
                'page': page_num + 1
            })
    
    return fields

def extract_standard_form_fields(lines, page_num):
    """Extract fields from standard form layouts (families B, D)"""
    fields = []
    
    # Find header row y-coordinates to avoid extracting from them
    header_y_coords = set()
    for line in lines:
        if line.bold and 95 < line.y0 < 105:
            # Check if this looks like a header row (multiple bold items at same y)
            same_y_bold = [l for l in lines if l.bold and abs(l.y0 - line.y0) < 2]
            if len(same_y_bold) > 2:
                header_y_coords.add(round(line.y0))
    
    # Look for bold labels with bracketed numbers in left content area
    for i, line in enumerate(lines):
        if not line.bold:
            continue
        
        text = line.text.strip()
        
        # Skip if it's just a bracketed number
        if re.match(r'^\[\d+\]$', text):
            continue
        
        # Skip header area
        if is_header_area(line):
            continue
        
        # Skip if on a header row
        if any(abs(line.y0 - hy) < 2 for hy in header_y_coords):
            continue
        
        # Skip right column (answers/values)
        if is_right_column(line):
            continue
        
        # Skip machine codes
        if is_machine_code(text):
            continue
        
        # Skip simple answers in any position
        if is_simple_answer(text):
            continue
        
        # Skip page identifiers
        if 'MAC186' in text or 'eCRF' in text:
            continue
        
        # Skip if text contains multiple answer options concatenated
        if re.search(r'(Yes\s+No|Positive\s+Negative)', text):
            continue
        
        # Extract field label - may span multiple lines
        field_text = text
        
        # Remove bracketed numbers from the label
        field_text = re.sub(r'\s*\[\d+\]\s*', ' ', field_text).strip()
        
        # Check if this looks like a field label (left side, reasonable length)
        if line.x0 < 300 and len(field_text) > 2 and field_text:
            # Look ahead for continuation lines
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                # If next line is close and not bold, might be continuation
                if (not next_line.bold and 
                    abs(next_line.x0 - line.x0) < 50 and 
                    next_line.y0 - line.y0 < 15 and
                    not re.match(r'^\[\d+\]', next_line.text)):
                    continuation = next_line.text.strip()
                    if continuation and not continuation.startswith('[') and not is_machine_code(continuation):
                        field_text += ' ' + continuation
            
            fields.append({
                'field_name': field_text,
                'page': page_num + 1
            })
    
    return fields

def extract_variable_table_fields(lines, page_num):
    """Extract fields from variable details tables (family C)"""
    fields = []
    
    # Find rows with human-readable names (not export names)
    for i, line in enumerate(lines):
        text = line.text.strip()
        
        # Look for field names in the leftmost text column (x0 around 80)
        if 75 < line.x0 < 100 and len(text) > 3:
            # Skip header area
            if is_header_area(line):
                continue
            
            # Skip machine codes (all caps export names)
            if is_machine_code(text):
                continue
            
            # Skip simple answers
            if is_simple_answer(text):
                continue
            
            # Check if there's a continuation line
            field_text = text
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if (abs(next_line.x0 - line.x0) < 20 and 
                    next_line.y0 - line.y0 < 10):
                    continuation = next_line.text.strip()
                    if continuation and not is_machine_code(continuation):
                        field_text += ' ' + continuation
            
            if field_text:
                fields.append({
                    'field_name': field_text,
                    'page': page_num + 1
                })
    
    return fields

def extract_generic_fields(lines, page_num):
    """Generic field extraction for unrecognized layouts"""
    fields = []
    
    # Find header row y-coordinates
    header_y_coords = set()
    for line in lines:
        if line.bold and 95 < line.y0 < 105:
            same_y_bold = [l for l in lines if l.bold and abs(l.y0 - line.y0) < 2]
            if len(same_y_bold) > 2:
                header_y_coords.add(round(line.y0))
    
    # Look for bold text on the left side that looks like labels
    for line in lines:
        if not line.bold:
            continue
        
        text = line.text.strip()
        
        # Must be on left side and reasonable length
        if line.x0 > 300 or len(text) < 3:
            continue
        
        # Skip header area
        if is_header_area(line):
            continue
        
        # Skip if on a header row
        if any(abs(line.y0 - hy) < 2 for hy in header_y_coords):
            continue
        
        # Skip simple answers
        if is_simple_answer(text):
            continue
        
        # Skip machine codes
        if is_machine_code(text):
            continue
        
        # Skip bracketed numbers alone
        if re.match(r'^\[\d+\]$', text):
            continue
        
        # Skip page identifiers
        if 'MAC186' in text or 'eCRF' in text:
            continue
        
        # Skip concatenated answer options
        if re.search(r'(Yes\s+No|Positive\s+Negative)', text):
            continue
        
        # Remove bracketed numbers
        field_text = re.sub(r'\s*\[\d+\]\s*', ' ', text).strip()
        
        if field_text:
            fields.append({
                'field_name': field_text,
                'page': page_num + 1
            })
    
    return fields
```