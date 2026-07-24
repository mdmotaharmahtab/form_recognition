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
    """Extract fields from simple horizontal layout (pages 34, 53, 510)"""
    fields = []
    
    # Find all bold lines in the header area with bracketed numbers
    for line in lines:
        if line.bold and line.y0 > 70 and line.y0 < 120:
            text = line.text.strip()
            
            # Extract field labels before bracketed numbers
            # Pattern: "Sample Performed  [1] Reason Not Done  [2]"
            matches = re.finditer(r'([A-Za-z][A-Za-z\s]+?)\s+\[\d+\]', text)
            
            for match in matches:
                field_label = match.group(1).strip()
                
                # Skip common answer options that appear in headers
                if field_label in ["Yes", "No", "Yes No"]:
                    continue
                
                if field_label and len(field_label) > 2:
                    fields.append({
                        "form_name": form_name,
                        "field_name": field_label,
                        "page": page_num
                    })
    
    # Also look for non-bold field labels in the body that are followed by bracketed numbers
    # These appear in the data area below the header
    max_y = max([line.y0 for line in lines]) if lines else 800
    header_threshold = 120
    
    for line in lines:
        if line.y0 > header_threshold and line.y0 < max_y * 0.9:
            text = line.text.strip()
            
            # Look for pattern: "Field Label  [number]"
            match = re.match(r'^([A-Za-z][A-Za-z\s/\-\(\)\.]+?)\s+\[\d+\]$', text)
            if match:
                field_label = match.group(1).strip()
                
                # Skip if it's too short or looks like an answer
                if len(field_label) < 3:
                    continue
                
                # Skip common answer options
                if field_label in ["Yes", "No", "Yes No", "Not Done", "Test", "Result"]:
                    continue
                
                # Skip if it starts with a number (likely a rating scale)
                if re.match(r'^\d+\s*-', field_label):
                    continue
                
                fields.append({
                    "form_name": form_name,
                    "field_name": field_label,
                    "page": page_num
                })
    
    return fields


def extract_standard_fields(lines, form_name, page_num):
    """Extract fields from standard form layout (Family B)"""
    fields = []
    
    # Find page dimensions
    max_y = max([line.y0 for line in lines]) if lines else 800
    max_x = max([line.x0 + len(line.text) * 5 for line in lines]) if lines else 600
    header_threshold = max_y * 0.15  # Top ~15% is header
    
    # Identify the main content column (left side, where field labels are)
    # vs answer columns (right side, where options/values are)
    left_column_max = max_x * 0.55  # Left 55% is field labels
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for bold field labels (not in header area, in left column)
        if line.bold and line.y0 > header_threshold and line.x0 < left_column_max:
            text = line.text.strip()
            
            # Skip if it's just a bracketed number
            if re.match(r'^\[\d+\]$', text):
                i += 1
                continue
            
            # Skip if it's a single common answer word positioned in answer area
            if len(text.split()) == 1 and line.x0 > max_x * 0.4:
                i += 1
                continue
            
            # Skip common answer options that appear as bold headers
            if text in ["Yes", "No", "Yes No", "Not Done", "Test", "Result", "Parameter"]:
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
            base_x = line.x0
            base_y = line.y0
            
            while j < len(lines):
                next_line = lines[j]
                
                # If next line is close in Y and X (continuation of same field label)
                y_diff = next_line.y0 - base_y
                x_diff = abs(next_line.x0 - base_x)
                
                if y_diff < 20 and y_diff > 0 and x_diff < 100:
                    next_text = next_line.text.strip()
                    
                    # Skip if it's bold (likely a new field)
                    if next_line.bold:
                        break
                    
                    # Skip if it's a bracketed number
                    if re.match(r'^\[\d+\]$', next_text):
                        j += 1
                        continue
                    
                    # Skip if it looks like an answer option (number dash text)
                    if re.match(r'^\d+\s*-\s*', next_text):
                        break
                    
                    # Skip if it's in the answer column area
                    if next_line.x0 > left_column_max:
                        break
                    
                    # This is a continuation
                    field_text += " " + next_text
                    base_y = next_line.y0
                    j += 1
                else:
                    break
            
            # Clean up field name
            field_text = field_text.strip()
            
            # Skip if empty or too short
            if not field_text or len(field_text) < 2:
                i += 1
                continue
            
            # Skip if it starts with a bracketed number
            if field_text.startswith("["):
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
    param_header = None
    header_y = None
    
    for line in lines:
        if line.bold and "Parameter" in line.text and line.y0 < 120:
            param_header = line
            header_y = line.y0
            break
    
    if param_header is None:
        # Fallback: look for numbered rows
        return extract_table_fields_fallback(lines, form_name, page_num)
    
    param_x = param_header.x0
    
    # Find page dimensions for column detection
    max_x = max([line.x0 + len(line.text) * 5 for line in lines]) if lines else 600
    
    # Identify column boundaries
    # Parameter column is on the left
    # Answer columns (Not Done, Reason, etc.) are on the right
    param_column_right = param_x + 200  # Parameter column extends ~200 units
    
    # Find other field labels in the header row (same Y position as Parameter)
    # These are column headers that represent fields
    header_fields = []
    for line in lines:
        if line.bold and abs(line.y0 - header_y) < 10 and line.y0 < 120:
            text = line.text.strip()
            
            # Skip "Parameter" itself
            if text == "Parameter":
                continue
            
            # Skip bracketed numbers
            if re.match(r'^\[\d+\]$', text):
                continue
            
            # Skip if it's positioned in far left (likely row numbers)
            if line.x0 < 50:
                continue
            
            # Extract field name (remove bracketed numbers if inline)
            field_text = re.sub(r'\s*\[\d+\]\s*', ' ', text).strip()
            
            # Skip common answer column headers that are not fields
            # These are positioned to the right of the parameter column
            if line.x0 > param_column_right:
                # These are answer column headers, not field names
                # Skip them unless they look like actual field labels
                if field_text in ["Not Done", "Reason Not Done", "Test", "Result", "Interpretation"]:
                    continue
            
            if field_text and len(field_text) > 1:
                header_fields.append(field_text)
    
    # Add header fields
    for field_text in header_fields:
        fields.append({
            "form_name": form_name,
            "field_name": field_text,
            "page": page_num
        })
    
    # Now extract parameter names from the data rows
    # Parameters are in the column under "Parameter" header
    for line in lines:
        # Look for text in the Parameter column (below header)
        if line.y0 > header_y + 10 and abs(line.x0 - param_x) < 40:
            text = line.text.strip()
            
            # Skip if it's a bracketed number
            if re.match(r'^\[\d+\]$', text):
                continue
            
            # Skip if it's just a row number
            if re.match(r'^\d+$', text) and len(text) <= 3:
                continue
            
            # Skip if it looks like an answer option (number dash text)
            if re.match(r'^\d+\s*-\s*', text):
                continue
            
            # Skip if it's too short
            if len(text) < 3:
                continue
            
            # Skip common answer values that might appear in parameter column
            if text in ["Not Done", "Done", "Yes", "No", "Positive", "Negative"]:
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
    
    # Find page dimensions
    max_x = max([line.x0 + len(line.text) * 5 for line in lines]) if lines else 600
    
    # Find the main data rows (numbered rows with field descriptions)
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for row numbers (small numbers at left margin)
        if line.x0 < 70 and re.match(r'^\d+$', line.text.strip()) and len(line.text.strip()) <= 3:
            row_num = line.text.strip()
            
            # Look for the field description in the same row
            # It should be slightly to the right and at similar Y position
            field_text = None
            for j in range(i + 1, min(i + 10, len(lines))):
                candidate = lines[j]
                
                # Check if it's in the same row (similar Y position)
                if abs(candidate.y0 - line.y0) < 8:
                    text = candidate.text.strip()
                    
                    # Skip if it's a bracketed number
                    if re.match(r'^\[\d+\]$', text):
                        continue
                    
                    # Skip if it looks like an answer option
                    if re.match(r'^\d+\s*-\s*', text):
                        continue
                    
                    # Skip if it's in the far right (likely a value column)
                    if candidate.x0 > max_x * 0.7:
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
                        # Check if it's a continuation
                        if (next_text and 
                            not re.match(r'^\d+$', next_text) and
                            not re.match(r'^\[\d+\]$', next_text) and
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