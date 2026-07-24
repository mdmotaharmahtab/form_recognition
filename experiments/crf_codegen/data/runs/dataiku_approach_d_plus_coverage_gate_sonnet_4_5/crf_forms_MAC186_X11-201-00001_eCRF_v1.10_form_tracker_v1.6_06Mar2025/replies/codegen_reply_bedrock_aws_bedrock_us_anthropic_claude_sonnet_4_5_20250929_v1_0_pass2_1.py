STRATEGY:

The document is a clinical eCRF with multiple layout families. Form titles appear in two locations: a small bold text near the top (around y=48.5, size ~7.8) and a larger title below it (around y=73.9, size ~17.4). I will use the larger title as the primary form name since it is more prominent and human-readable. When a page lacks a title, I will carry forward the most recent form name encountered. Field names are identified by their position and context: in family B they appear as bold labels on the left with bracketed numbers; in families D and E they appear in tabular layouts with column headers and row labels; in family C they show variable details with export names and types. I distinguish fields from answer options by checking if text appears in a response column (right side, often with Yes/No or numeric values) versus being a row label on the left. Answer options like "Yes/No", numeric scales (0-5), and categorical values in the rightmost columns are excluded. Machine codes (all-caps export names like "LBPERF", "HAMGENI") are not returned as field names but the human-readable labels are. Table rows listing parameters (like "Basophils", "Temperature") are fields when they have associated data entry cells. I process all pages sequentially, maintaining state for the current form name across continuation pages, and extract every recognizable field label regardless of page layout family.

```python
# Clinical eCRF extraction: handles multiple layout families with form titles
# at y~48.5 (small) and y~73.9 (large), fields in various tabular formats.
# Carries forward form names across continuation pages.

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
                # Skip machine codes and generic headers
                if not re.match(r'^[A-Z0-9_-]+$', text) and text not in ['Variable details']:
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
    
    # Family B/D/E: Forms with "Performed" questions and field labels
    if has_large_title and has_bracketed_numbers:
        fields.extend(extract_standard_form_fields(lines, page_num))
    
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

def extract_standard_form_fields(lines, page_num):
    """Extract fields from standard form layouts (families B, D)"""
    fields = []
    
    # Look for bold labels with bracketed numbers
    for i, line in enumerate(lines):
        if not line.bold:
            continue
        
        text = line.text.strip()
        
        # Skip if it's just a bracketed number
        if re.match(r'^\[\d+\]$', text):
            continue
        
        # Skip answer options (Yes/No alone, or numeric values in right column)
        if text in ['Yes', 'No'] and line.x0 > 200:
            continue
        
        # Skip column headers and table structure
        if text in ['Details', 'Position', 'Test', 'Result', 'Interpretation', 
                    'Not Done', 'Reason Not Done', 'Time Point', 'Repetition',
                    'Location', 'Parameter', 'Performed', 'Eye', 'Repeat']:
            continue
        
        # Skip machine codes (all caps with underscores)
        if re.match(r'^[A-Z0-9_]+$', text) and len(text) > 3:
            continue
        
        # Skip page headers
        if 'MAC186' in text or 'eCRF' in text:
            continue
        
        # Extract field label - may span multiple lines
        field_text = text
        
        # Remove bracketed numbers from the label
        field_text = re.sub(r'\s*\[\d+\]\s*', ' ', field_text).strip()
        
        # Check if this looks like a field label (left side, reasonable length)
        if line.x0 < 200 and len(field_text) > 2 and field_text:
            # Look ahead for continuation lines
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                # If next line is close and not bold, might be continuation
                if (not next_line.bold and 
                    abs(next_line.x0 - line.x0) < 50 and 
                    next_line.y0 - line.y0 < 15 and
                    not re.match(r'^\[\d+\]', next_line.text)):
                    continuation = next_line.text.strip()
                    if continuation and not continuation.startswith('['):
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
            # Skip headers
            if text in ['Name', 'Export Name', 'Type', 'Categories']:
                continue
            
            # Skip machine codes (all caps export names)
            if re.match(r'^[A-Z0-9_]+$', text):
                continue
            
            # Skip numeric values and simple answers
            if text.isdigit() or text in ['Yes', 'No']:
                continue
            
            # Check if there's a continuation line
            field_text = text
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if (abs(next_line.x0 - line.x0) < 20 and 
                    next_line.y0 - line.y0 < 10):
                    continuation = next_line.text.strip()
                    if continuation and not re.match(r'^[A-Z0-9_]+$', continuation):
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
            # Skip row numbers
            if text.isdigit():
                continue
            
            # Skip answer options
            if text in ['Yes', 'No', 'Positive', 'Negative']:
                continue
            
            # Skip headers
            if text in ['Test', 'Parameter', 'Details']:
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
        if line.x0 > 200 or len(text) < 3:
            continue
        
        # Skip common non-fields
        if text in ['Yes', 'No'] or text.isdigit():
            continue
        
        # Skip machine codes
        if re.match(r'^[A-Z0-9_]+$', text) and len(text) > 3:
            continue
        
        # Skip bracketed numbers alone
        if re.match(r'^\[\d+\]$', text):
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