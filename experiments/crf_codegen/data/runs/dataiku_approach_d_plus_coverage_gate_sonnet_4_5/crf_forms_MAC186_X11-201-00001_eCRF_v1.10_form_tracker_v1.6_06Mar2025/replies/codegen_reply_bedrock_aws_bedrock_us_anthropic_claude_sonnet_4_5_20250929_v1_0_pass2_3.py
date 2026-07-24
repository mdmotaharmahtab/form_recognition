Looking at the sample pages:

**Cluster 0 (pages 361, 525)**: These are data-entry tables with:
- Bold column headers: "Parameter [5]", "Not Done [6] Reason Not Done [7]", "Interpretation [8]"
- Rows of parameters (Basophils, Eosinophils, Hemoglobin, etc.) at x≈64.5
- These are clearly data-entry fields that need to be extracted

**Cluster 2 (pages 263, 617)**: These show:
- Export codes like CSS0218, CSS0218A in column at x≈235
- Data types like "Number (continuous)", "Categorical yes/no"
- These are variable definition/metadata pages (not data-entry forms)

The current program has logic to skip pages with export codes at x≈235, which correctly handles cluster 2. However, cluster 0 pages are being missed because:
1. They lack the large title at y=73.9
2. They lack bracketed numbers in the content (only in headers)
3. The bold text is in headers, not field labels
4. The actual parameter names are NOT bold

I need to add detection for this table layout where field names are regular (non-bold) text in the left column below bold headers.

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
    
    # Check for parameter table layout (bold "Parameter" header with non-bold parameter names below)
    has_parameter_table = any(line.bold and 'Parameter' in line.text and 50 < line.y0 < 60 for line in lines)
    
    # Family B/D/E: Forms with "Performed" questions and field labels
    if has_large_title and has_bracketed_numbers:
        fields.extend(extract_standard_form_fields(lines, page_num))
    
    # Parameter table layout (cluster 0)
    elif has_parameter_table:
        fields.extend(extract_parameter_table_fields(lines, page_num))
    
    # Family C: Variable details tables
    elif any('Export Name' in l.text for l in lines):
        fields.extend(extract_variable_table_fields(lines, page_num))
    
    # Family E: Test/parameter tables
    elif any('Test' in l.text and 'Performed' in l.text for l in lines[:20]):
        fields.extend(extract_test_table_fields(lines, page_num))
    
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

def extract_parameter_table_fields(lines, page_num):
    """Extract fields from parameter table layouts (cluster 0)"""
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

def extract_test_table_fields(lines, page_num):
    """Extract fields from test/parameter tables (family E)"""
    fields = []
    
    # Look for test/parameter names in left column
    for line in lines:
        text = line.text.strip()
        
        # Test names typically at x0 around 60-70
        if 55 < line.x0 < 75 and len(text) > 3:
            # Skip header area
            if is_header_area(line):
                continue
            
            # Skip row numbers
            if text.isdigit():
                continue
            
            # Skip simple answers
            if is_simple_answer(text):
                continue
            
            # Valid field name
            if text and not re.match(r'^\d+$', text):
                fields.append({
                    'field_name': text,
                    'page': page_num + 1
                })
    
    return fields

def extract_generic_fields(lines, page_num):
    """Generic field extraction for unrecognized layouts"""
    fields = []
    
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
        
        # Remove bracketed numbers
        field_text = re.sub(r'\s*\[\d+\]\s*', ' ', text).strip()
        
        if field_text:
            fields.append({
                'field_name': field_text,
                'page': page_num + 1
            })
    
    return fields
```