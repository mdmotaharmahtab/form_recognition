```python
# This CRF document contains multiple form sections with data-entry fields.
# Layout families D and E contain the main field-bearing pages with a consistent structure:
#   - A large blue form title at y~66 (size ~14.4, color #004c99)
#   - Field labels in black at x~47.8, size ~7.8
#   - Machine codes in red below labels (e.g., [LBYN3], [VISDAT])
# Family C contains repeating lab result fields with a different layout.
# Family F contains table-based PK sample collection fields.
# Strategy: Extract form_name from the blue title; extract field_name from black text
# at x~47.8 that is NOT a machine code, instruction, or answer option.

import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form title: large blue text at top (size ~14, color #004c99)
        for line in lines:
            if line.size >= 13.0 and line.non_black and '#004c99' in str(line):
                # This is likely a form title
                current_form = line.text.strip()
                break
        
        # Extract fields based on structural patterns
        fields = extract_fields_from_page(lines, current_form, page_num)
        results.extend(fields)
    
    return results

def extract_fields_from_page(lines, form_name, page_num):
    fields = []
    
    # Group lines by y-coordinate to handle multi-line labels
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip if this is a machine code (red text in brackets)
        if line.non_black and line.text.startswith('[') and line.text.endswith(']'):
            i += 1
            continue
        
        # Skip if this is a TYPE annotation or other metadata
        if line.non_black and '[TYPE:' in line.text:
            i += 1
            continue
        
        # Skip if this is VISIBILITY annotation
        if line.non_black and '[VISIBILITY:' in line.text:
            i += 1
            continue
        
        # Skip if this is a Read-only field annotation
        if line.non_black and '[Read-only' in line.text:
            i += 1
            continue
        
        # Check for field labels: black text at x < 100, size 7-10, not bold headers
        if (not line.non_black and 
            line.x0 < 100 and 
            7.0 <= line.size <= 10.5 and
            not is_junk_text(line.text)):
            
            # Check if this is a question/field label
            text = line.text.strip()
            
            # Skip table headers and column labels
            if is_table_header(text):
                i += 1
                continue
            
            # Skip answer options (Yes/No at specific x positions)
            if line.x0 > 400 and text in ['Yes', 'No']:
                i += 1
                continue
            
            # Skip enumeration values and rating scale anchors
            if is_answer_option(text):
                i += 1
                continue
            
            # Skip instructions and notes
            if is_instruction(text):
                i += 1
                continue
            
            # Collect multi-line label
            label_parts = [text]
            j = i + 1
            
            # Look ahead for continuation lines (same x position, close y)
            while j < len(lines):
                next_line = lines[j]
                
                # Stop at machine code or metadata
                if next_line.non_black:
                    break
                
                # Stop if x position changes significantly or y gap is large
                if abs(next_line.x0 - line.x0) > 5 or next_line.y0 - lines[j-1].y0 > 20:
                    break
                
                # Stop at answer options or new field
                if next_line.x0 > 400 or is_table_header(next_line.text):
                    break
                
                # Add continuation if it looks like part of the same label
                if (not next_line.non_black and 
                    7.0 <= next_line.size <= 10.5 and
                    not is_junk_text(next_line.text)):
                    label_parts.append(next_line.text.strip())
                    j += 1
                else:
                    break
            
            # Join multi-line label
            field_label = ' '.join(label_parts)
            
            # Final validation: must be a real question/field
            if field_label and len(field_label) > 2 and not is_pure_junk(field_label):
                fields.append({
                    "form_name": form_name,
                    "field_name": field_label,
                    "page": page_num
                })
            
            i = j
        else:
            i += 1
    
    return fields

def is_junk_text(text):
    """Check if text is page furniture or metadata"""
    text_lower = text.lower().strip()
    
    # Empty or very short
    if len(text_lower) < 2:
        return True
    
    # Page numbers, dates in headers
    if re.match(r'^\d+$', text_lower):
        return True
    
    # Common CRF codes/markers
    if re.match(r'^\[.*\]$', text):
        return True
    
    return False

def is_table_header(text):
    """Check if text is a table column header"""
    headers = ['Test', 'Result', 'Sample', 'Timepoint', 'Time of', 'Barcode', 
               'Backup', 'Status', 'Collection', 'Number', 'Date Dispensed',
               'Dispensed', 'Appearance', 'Bilirubin', 'Color', 'Glucose',
               'Sample Type', 'Manufacturer', 'Item #', 'Lot', 'Expiration Date',
               'Date of Sample', 'Time of Sample', 'Date of Collection']
    
    return text.strip() in headers

def is_answer_option(text):
    """Check if text is an answer option value"""
    text_stripped = text.strip()
    
    # Common answer options
    if text_stripped in ['Yes', 'No', 'Unknown', 'Not Done', 'Positive', 'Negative',
                         'Collected', 'Not Collected', 'Scan', 'Urine', 'Serum',
                         'Skip to next visit']:
        return True
    
    # Rating scale values
    if re.match(r'^\(\d+\)', text_stripped):
        return True
    
    # Enumeration items in lists
    if text_stripped in ['Dose Missed', 'Wrong dose', 'Other', 'Predose', 
                         '1h Postdose', '2h Postdose', 'Standing', 'Supine']:
        return True
    
    return False

def is_instruction(text):
    """Check if text is an instruction or note"""
    text_lower = text.lower().strip()
    
    # Instructions
    if any(phrase in text_lower for phrase in [
        'if yes then please fill',
        'please go to add-on',
        'log one line per',
        'repeatable row',
        'add row button'
    ]):
        return True
    
    # Row labels
    if re.match(r'^row \d+$', text_lower):
        return True
    
    return False

def is_pure_junk(text):
    """Final check for pure junk that slipped through"""
    text_stripped = text.strip()
    
    # Very short fragments
    if len(text_stripped) < 3:
        return True
    
    # Just punctuation or numbers
    if re.match(r'^[\d\s\.\,\-\(\)]+$', text_stripped):
        return True
    
    return False
```