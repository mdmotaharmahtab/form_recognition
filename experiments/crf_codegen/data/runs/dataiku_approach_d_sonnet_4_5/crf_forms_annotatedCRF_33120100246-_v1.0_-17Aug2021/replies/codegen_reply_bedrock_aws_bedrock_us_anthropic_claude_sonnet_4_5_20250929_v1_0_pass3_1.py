```python
# This CRF document contains multiple layout families with data-entry fields.
# The main patterns are:
# - Family A: Table of contents (no fields)
# - Family B: Continuation of TOC (no fields)
# - Family C: Forms with a large blue title, yes/no questions, and sample collection tables
# - Family D: Forms with large blue title and detailed questionnaires (C-SSRS, drug screens, etc.)
# - Family E: Continuation pages with test result tables
# - Family F: C-SSRS intensity/behavior pages with detailed rating scales
# Strategy: Extract form_name from large blue titles (~14pt, color #004c99), then extract
# field_name from black text questions/labels, filtering out machine codes in red/brackets.

import re
from typing import List, Dict, Tuple

def extract(pages):
    records = []
    
    for page_num, lines in pages:
        if not lines:
            continue
        
        # Find form title - large blue text (~14pt, #004c99)
        form_name = ""
        for line in lines:
            if line.size >= 13.0 and '#004c99' in str(line.non_black or ''):
                # Check if text contains color marker or is actually blue
                text = line.text.strip()
                # Skip if it's a machine code or metadata
                if not text.startswith('[') and not text.endswith(']'):
                    form_name = text
                    break
        
        # Extract fields from this page
        page_fields = extract_fields_from_page(lines, form_name, page_num)
        records.extend(page_fields)
    
    return records

def extract_fields_from_page(lines: List, form_name: str, page_num: int) -> List[Dict]:
    """Extract field labels from a page."""
    fields = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        text = line.text.strip()
        
        # Skip empty lines
        if not text:
            i += 1
            continue
        
        # Skip machine codes (red text in brackets)
        if text.startswith('[') and text.endswith(']'):
            i += 1
            continue
        
        # Skip lines that are only machine codes
        if text.startswith('[') or (line.non_black and '#ff0000' in str(line.non_black)):
            i += 1
            continue
        
        # Skip table headers and column labels that appear to be structural
        if is_table_header(text, line):
            i += 1
            continue
        
        # Skip answer options (Yes/No/etc at specific positions)
        if is_answer_option(text, line, lines, i):
            i += 1
            continue
        
        # Skip row labels like "Row 1", "Row 2", etc.
        if re.match(r'^Row\s+\d+$', text, re.IGNORECASE):
            i += 1
            continue
        
        # Skip version numbers and instructions
        if 'Version Number' in text or text.startswith('Ask questions'):
            i += 1
            continue
        
        # Check if this is a field label (black text, reasonable size, question-like)
        if is_field_label(line, text):
            # Collect multi-line field labels
            field_text = text
            j = i + 1
            
            # Look ahead for continuation lines
            while j < len(lines):
                next_line = lines[j]
                next_text = next_line.text.strip()
                
                # Stop if we hit a machine code
                if next_text.startswith('['):
                    break
                
                # Stop if we hit answer options
                if is_answer_option(next_text, next_line, lines, j):
                    break
                
                # Stop if next line is too far down or different style
                if next_line.y0 - line.y1 > 20:
                    break
                
                # Stop if it's a new field (starts at left margin and is bold/larger)
                if next_line.x0 < line.x0 + 5 and (next_line.bold or next_line.size > line.size):
                    break
                
                # Check if it's a continuation (similar x position, similar size, black text)
                if (abs(next_line.x0 - line.x0) < 30 and 
                    abs(next_line.size - line.size) < 2 and
                    not next_line.non_black and
                    not next_text.startswith('[')):
                    
                    # Append continuation
                    field_text += ' ' + next_text
                    j += 1
                else:
                    break
            
            # Clean up the field text
            field_text = clean_field_text(field_text)
            
            # Only add if it looks like a real field
            if field_text and len(field_text) > 3 and not is_junk_text(field_text):
                fields.append({
                    'form_name': form_name,
                    'field_name': field_text,
                    'page': page_num + 1
                })
            
            i = j
        else:
            i += 1
    
    return fields

def is_field_label(line, text: str) -> bool:
    """Check if a line is likely a field label."""
    # Must be black text
    if line.non_black:
        return False
    
    # Must have reasonable size (not too small, not too large)
    if line.size < 7.0 or line.size > 16.0:
        return False
    
    # Skip very short text
    if len(text) < 3:
        return False
    
    # Skip pure numbers
    if text.isdigit():
        return False
    
    # Skip if it's just punctuation
    if all(c in '.,;:!?-()[]{}' for c in text):
        return False
    
    return True

def is_table_header(text: str, line) -> bool:
    """Check if text is a table header."""
    headers = ['Sample', 'Date of Collection', 'Time of Collection', 'Barcode Number', 
               'Scan', 'Test', 'Result', 'Lifetime', 'Past 3 Month', 'Since Last Visit',
               'Suicidal Ideation', 'Intensity of Ideation']
    
    return text in headers

def is_answer_option(text: str, line, lines: List, index: int) -> bool:
    """Check if text is an answer option (Yes/No/etc)."""
    # Common answer options
    options = ['Yes', 'No', 'Not Done', 'Not Applicable', 'Positive', 'Negative', 
               'Normal', 'Abnormal', 'Scan']
    
    if text not in options:
        return False
    
    # Check if it's positioned like an answer option (right side of page or in a row)
    if line.x0 > 300:  # Right side positioning
        return True
    
    # Check if there are multiple options on the same line or nearby
    nearby_options = 0
    for other_line in lines[max(0, index-2):min(len(lines), index+3)]:
        if abs(other_line.y0 - line.y0) < 15 and other_line.text.strip() in options:
            nearby_options += 1
    
    return nearby_options >= 2

def is_junk_text(text: str) -> bool:
    """Check if text is junk/non-field content."""
    # Skip if it's just a description of answer options
    if re.match(r'^\(\d+\)', text):
        return True
    
    # Skip pure instructional text patterns
    if text.startswith('If Yes') or text.startswith('If not'):
        return False  # These are actually field labels
    
    # Skip examples in parentheses
    if text.startswith('(e.g.') or text.startswith('Examples are'):
        return True
    
    return False

def clean_field_text(text: str) -> str:
    """Clean up field text."""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove trailing punctuation that's not part of the question
    text = text.strip()
    
    return text
```