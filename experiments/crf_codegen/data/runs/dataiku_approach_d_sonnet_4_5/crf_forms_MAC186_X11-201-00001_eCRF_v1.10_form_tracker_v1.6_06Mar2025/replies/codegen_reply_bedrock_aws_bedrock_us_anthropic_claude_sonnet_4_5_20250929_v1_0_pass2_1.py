```python
# This CRF document has multiple layout families:
# - Family A: Simple visit/screening title pages (no fields)
# - Family B: Standard form pages with labeled fields and Yes/No options
# - Family C: Variable details / data dictionary pages (not data-entry fields)
# - Family D: Complex multi-column table forms with repeated measurements
# - Family E: Simple table forms with test/parameter lists
# Strategy: Extract form_name from large title text (sz ~17-18), field_name from
# bold labels. Skip variable detail pages (technical metadata). Handle table rows
# as individual fields when they represent data entry points.

import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip empty pages
        if not lines:
            continue
        
        # Find form name - look for large text (size ~17-18)
        form_name = ""
        for line in lines:
            if line.size >= 16.0 and line.size <= 18.5:
                # Skip if it's just "Visit:" or "Screening" alone
                text = line.text.strip()
                if text and text not in ["Visit:", "Screening"]:
                    form_name = text
                    break
        
        # Check if this is a "Variable details" page (metadata, not fields)
        is_variable_details = False
        for line in lines:
            if "Variable details" in line.text and line.bold:
                is_variable_details = True
                break
        
        if is_variable_details:
            continue
        
        # Detect page type by structure
        # Family B: Standard form with bold field labels
        # Family D/E: Table-based forms
        
        # Check for table headers that indicate this is a data table
        has_table_structure = False
        for line in lines:
            if line.bold and ("[" in line.text or "Parameter" in line.text or "Test" in line.text):
                if line.y0 < 250:  # Header area
                    has_table_structure = True
                    break
        
        # Extract fields based on structure
        if has_table_structure:
            # Table-based form (Family D, E)
            results.extend(extract_table_fields(lines, form_name, page_num))
        else:
            # Standard form (Family B)
            results.extend(extract_standard_fields(lines, form_name, page_num))
    
    return results


def extract_standard_fields(lines, form_name, page_num):
    """Extract fields from standard form layout (Family B)"""
    fields = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for bold field labels (not in header area, not just numbers)
        if line.bold and line.y0 > 90:
            text = line.text.strip()
            
            # Skip if it's just a bracketed number or "Yes"/"No"
            if re.match(r'^\[\d+\]$', text) or text in ["Yes", "No"]:
                i += 1
                continue
            
            # Skip if it's a column header pattern
            if "Export Name" in text or "Type" in text or "Max length" in text:
                i += 1
                continue
            
            # This looks like a field label
            field_text = text
            
            # Check if next lines continue the label (wrapping)
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # If next line is close in Y and not bold, might be continuation
                if (next_line.y0 - line.y0 < 15 and 
                    not next_line.bold and 
                    next_line.x0 > line.x0 - 20 and
                    next_line.x0 < line.x0 + 100):
                    # Check if it's not an answer option
                    if not re.match(r'^\d+\s*-\s*', next_line.text):
                        field_text += " " + next_line.text.strip()
                        j += 1
                    else:
                        break
                else:
                    break
            
            # Clean up field name
            field_text = field_text.strip()
            
            # Skip if empty or looks like metadata
            if not field_text or field_text.startswith("["):
                i += 1
                continue
            
            fields.append({
                "form_name": form_name,
                "field_name": field_text,
                "page": page_num
            })
            
            i = j
        else:
            i += 1
    
    return fields


def extract_table_fields(lines, form_name, page_num):
    """Extract fields from table-based forms (Family D, E)"""
    fields = []
    
    # Find the main data rows (numbered rows with field descriptions)
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for row numbers (small numbers at left margin)
        if line.x0 < 70 and re.match(r'^\d+$', line.text.strip()):
            row_num = line.text.strip()
            
            # Look for the field description in the same row
            # It should be slightly to the right and at similar Y position
            field_text = None
            for j in range(i + 1, min(i + 10, len(lines))):
                candidate = lines[j]
                
                # Check if it's in the same row (similar Y position)
                if abs(candidate.y0 - line.y0) < 8:
                    text = candidate.text.strip()
                    
                    # Skip if it's a bracketed number, Yes/No, or looks like data
                    if (re.match(r'^\[\d+\]$', text) or 
                        text in ["Yes", "No"] or
                        re.match(r'^\d+\s*-\s*', text)):
                        continue
                    
                    # Skip if it's in the far right (likely a value column)
                    if candidate.x0 > 550:
                        continue
                    
                    # This looks like a field label
                    if len(text) > 2 and not text.isdigit():
                        field_text = text
                        break
            
            if field_text:
                # Check for continuation lines
                base_y = line.y0
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # If within same row area and left-aligned with field text
                    if (abs(next_line.y0 - base_y) < 20 and
                        next_line.x0 > 50 and next_line.x0 < 150):
                        next_text = next_line.text.strip()
                        # Check if it's a continuation (not a number, not Yes/No)
                        if (next_text and 
                            not re.match(r'^\d+$', next_text) and
                            not re.match(r'^\[\d+\]$', next_text) and
                            next_text not in ["Yes", "No"] and
                            not re.match(r'^\d+\s*-\s*', next_text)):
                            field_text += " " + next_text
                        j += 1
                    else:
                        break
                
                # Clean and add field
                field_text = field_text.strip()
                if field_text and len(field_text) > 2:
                    fields.append({
                        "form_name": form_name,
                        "field_name": field_text,
                        "page": page_num
                    })
        
        i += 1
    
    return fields
```