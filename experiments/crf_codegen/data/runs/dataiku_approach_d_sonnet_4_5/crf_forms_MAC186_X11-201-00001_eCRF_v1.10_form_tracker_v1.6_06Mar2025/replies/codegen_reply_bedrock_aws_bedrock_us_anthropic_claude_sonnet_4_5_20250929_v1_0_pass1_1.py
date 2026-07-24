```python
"""
This CRF document has two main layout families:
1. Family C (~387 pages): "Variable details" tables with columns Name, Export Name, Type, etc.
   These are data dictionaries, NOT data-entry fields - they document the fields but are not fields themselves.
2. Family D (~336 pages): Actual CRF forms with field labels and entry markers [N].
   Field labels appear as bold text, with bracketed numbers [N] marking entry points.
   Form titles appear in large font (sz ~17.4) below a smaller bold section header.

Strategy: Extract only from Family D pages (actual forms). Identify form title by large font size (~17).
Field labels are bold text followed by bracketed numbers [N] or appearing in structured positions.
Skip answer options (Yes/No/etc. without their own [N] marker), table headers, and variable detail rows.
"""

import re
from typing import List, Dict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Identify page type by structural markers
        has_variable_details = any("Variable details" in line.text for line in lines)
        has_export_name_header = any(line.text == "Export Name" and line.bold for line in lines)
        
        # Family C: Variable details pages - skip these (they're data dictionaries, not forms)
        if has_variable_details and has_export_name_header:
            continue
        
        # Find form title: large font size (typically 17+), appears early on page
        form_name = ""
        for line in lines:
            if line.y0 > 200:  # Form titles appear in upper portion
                break
            # Large font indicates form title (not the small header at top)
            if line.size >= 15.0 and line.y0 > 60:  # Skip document ID at very top
                form_name = line.text.strip()
                break
        
        # If no large title found, try bold section header (smaller, around y=48)
        if not form_name:
            for line in lines:
                if 45 < line.y0 < 55 and line.bold and line.size >= 7.0:
                    # Skip document ID line
                    if "MAC186" not in line.text and "eCRF" not in line.text:
                        form_name = line.text.strip()
                        break
        
        # Extract fields from Family D pages (actual CRF forms)
        # Fields are identified by bracketed numbers [N] which mark entry points
        
        # Build a map of lines with bracketed numbers
        bracket_pattern = re.compile(r'^\[(\d+)\]$')
        bracket_lines = {}
        for i, line in enumerate(lines):
            match = bracket_pattern.match(line.text.strip())
            if match:
                bracket_lines[i] = int(match.group(1))
        
        # For each bracketed number, find the associated field label
        for line_idx, bracket_num in bracket_lines.items():
            line = lines[line_idx]
            
            # Look for bold text on the same line or nearby lines (field label)
            # Field labels are typically bold and appear to the left or above the bracket
            field_label = None
            
            # Check same line to the left
            for other_idx in range(line_idx - 1, max(0, line_idx - 10), -1):
                other = lines[other_idx]
                # Same or very close y position (same visual line)
                if abs(other.y0 - line.y0) < 3:
                    if other.bold and other.x0 < line.x0:
                        # Potential field label
                        text = other.text.strip()
                        # Skip answer options and common non-field text
                        if text and text not in ["Yes", "No", "Unknown", "Other"]:
                            # Skip if it looks like a column header in a table
                            if not (other.y0 < 70 and "Parameter" in text):
                                field_label = text
                                break
            
            # If not found on same line, check lines above (within reasonable distance)
            if not field_label:
                for other_idx in range(line_idx - 1, max(0, line_idx - 5), -1):
                    other = lines[other_idx]
                    # Line above (y difference 5-25 points)
                    if 5 < (line.y0 - other.y0) < 25:
                        if other.bold:
                            text = other.text.strip()
                            # Skip answer options
                            if text and text not in ["Yes", "No", "Unknown", "Other", "Normal", "Abnormal NCS", "Abnormal CS"]:
                                # Check if it's aligned or reasonably close in x
                                if abs(other.x0 - line.x0) < 200:
                                    field_label = text
                                    break
            
            # Add field if we found a valid label
            if field_label:
                # Clean up label - remove trailing colons, extra spaces
                field_label = field_label.rstrip(':').strip()
                
                # Skip if label looks like a table row number or index
                if re.match(r'^\d+$', field_label):
                    continue
                
                # Skip if label is just a bracketed number itself
                if bracket_pattern.match(field_label):
                    continue
                
                results.append({
                    "form_name": form_name,
                    "field_name": field_label,
                    "page": page_num
                })
        
        # Also handle table-style layouts where fields are in rows
        # Look for bold text followed by entry markers in structured tables
        for i, line in enumerate(lines):
            # Skip if already processed via bracket
            if i in bracket_lines:
                continue
            
            # Look for bold field labels in table rows
            if line.bold and line.size >= 7.0 and line.y0 > 90:
                text = line.text.strip()
                
                # Skip common non-field text
                skip_terms = ["Yes", "No", "Unknown", "Other", "Normal", "Abnormal", 
                              "Parameter", "Not Done", "Reason Not Done", "Interpretation",
                              "Name", "Export Name", "Type", "Max length", "Categories",
                              "Variable details", "Complete for all parameters",
                              "More rows"]
                
                if any(skip in text for skip in skip_terms):
                    continue
                
                # Skip if it's just a number (row index)
                if re.match(r'^\d+$', text):
                    continue
                
                # Skip if it's a bracketed number
                if bracket_pattern.match(text):
                    continue
                
                # Check if there's a bracket nearby on the same or next line
                has_nearby_bracket = False
                for j in range(i, min(i + 3, len(lines))):
                    if abs(lines[j].y0 - line.y0) < 15:
                        if bracket_pattern.match(lines[j].text.strip()):
                            has_nearby_bracket = True
                            break
                
                # Only add if it looks like a field label with structure
                if has_nearby_bracket and len(text) > 3:
                    results.append({
                        "form_name": form_name,
                        "field_name": text,
                        "page": page_num
                    })
    
    return results
```