```python
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
        page_type = detect_page_type(lines)
        
        # Extract fields based on structure
        if page_type == "table_with_parameters":
            # Table-based form with Parameter column (Family D, E)
            results.extend(extract_table_fields(lines, form_name, page_num))
        elif page_type == "simple_horizontal":
            # Simple horizontal layout with bold labels and bracketed numbers
            results.extend(extract_simple_horizontal_fields(lines, form_name, page_num))
        else:
            # Standard form (Family B)
            results.extend(extract_standard_fields(lines, form_name, page_num))
    
    return results


def detect_page_type(lines):
    """Detect the layout type of the page"""
    
    # Check for "Parameter" column header (table with parameters)
    for line in lines:
        if line.bold and "Parameter" in line.text and line.y0 < 120:
            return "table_with_parameters"
    
    # Check for simple horizontal layout pattern:
    # Bold labels followed by bracketed numbers in header area
    bold_labels_in_header = []
    for line in lines:
        if line.bold and line.y0 < 120 and line.y0 > 70:
            text = line.text.strip()
            # Look for pattern like "Sample Performed  [1]"
            if re.search(r'\[\d+\]', text):
                bold_labels_in_header.append(line)
    
    if len(bold_labels_in_header) >= 2:
        return "simple_horizontal"
    
    return "standard"


def extract_simple_horizontal_fields(lines, form_name, page_num):
    """Extract fields from simple horizontal layout (pages 392, 722)"""
    fields = []
    
    # Find all bold lines in the header area with bracketed numbers
    for line in lines:
        if line.bold and line.y0 > 70 and line.y0 < 120:
            text = line.text.strip()
            
            # Split by bracketed numbers to extract field labels
            # Pattern: "Sample Performed  [1] Reason Not Done  [2]"
            parts = re.split(r'\s+\[\d+\]', text)
            
            for part in parts:
                part = part.strip()
                if part and len(part) > 2:
                    # Skip if it's just a number or common non-field text
                    if not part.isdigit():
                        fields.append({
                            "form_name": form_name,
                            "field_name": part,
                            "page": page_num
                        })
    
    return fields


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
            
            # Skip section headers that are not field labels
            # Section headers often end with "Details" and are duplicated
            if text.endswith(" Details") and text.count(" ") >= 2:
                # Check if this is a section header (not a field)
                # by seeing if it's duplicated in the text
                text_base = text.replace(" Details", "")
                if text_base in text:
                    i += 1
                    continue
            
            # Extract field label - handle inline bracketed numbers
            # Pattern: "Field Label  [1]" -> extract "Field Label"
            field_text = text
            match = re.match(r'^(.+?)\s+\[\d+\]', text)
            if match:
                field_text = match.group(1).strip()
            
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
    """Extract fields from table-based forms with Parameter column (Family D, E)"""
    fields = []
    
    # Find the "Parameter" header to establish the column position
    param_x = None
    for line in lines:
        if line.bold and "Parameter" in line.text and line.y0 < 120:
            param_x = line.x0
            break
    
    if param_x is None:
        # Fallback: look for numbered rows
        return extract_table_fields_fallback(lines, form_name, page_num)
    
    # Also look for other column headers in the same row
    header_y = None
    for line in lines:
        if line.bold and "Parameter" in line.text and line.y0 < 120:
            header_y = line.y0
            break
    
    # Find other field labels in the header row
    if header_y:
        for line in lines:
            if line.bold and abs(line.y0 - header_y) < 10 and line.y0 < 120:
                text = line.text.strip()
                # Skip "Parameter" itself and bracketed numbers
                if text != "Parameter" and not re.match(r'^\[\d+\]$', text):
                    # Extract field name (remove bracketed numbers)
                    field_text = re.sub(r'\s*\[\d+\]\s*', ' ', text).strip()
                    if field_text and len(field_text) > 2:
                        fields.append({
                            "form_name": form_name,
                            "field_name": field_text,
                            "page": page_num
                        })
    
    # Now extract parameter names from the data rows
    # Parameters are in the column under "Parameter" header
    for line in lines:
        # Look for text in the Parameter column (below header)
        if line.y0 > 120 and abs(line.x0 - param_x) < 30:
            text = line.text.strip()
            
            # Skip if it's a bracketed number, row number, or answer option
            if (re.match(r'^\[\d+\]$', text) or 
                re.match(r'^\d+$', text) or
                text in ["Yes", "No"] or
                re.match(r'^\d+\s*-\s*', text)):
                continue
            
            # Skip if it's too short or looks like a value
            if len(text) < 3:
                continue
            
            # This is a parameter name (field)
            fields.append({
                "form_name": form_name,
                "field_name": text,
                "page": page_num
            })
    
    return fields


def extract_table_fields_fallback(lines, form_name, page_num):
    """Fallback extraction for table-based forms without clear Parameter column"""
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