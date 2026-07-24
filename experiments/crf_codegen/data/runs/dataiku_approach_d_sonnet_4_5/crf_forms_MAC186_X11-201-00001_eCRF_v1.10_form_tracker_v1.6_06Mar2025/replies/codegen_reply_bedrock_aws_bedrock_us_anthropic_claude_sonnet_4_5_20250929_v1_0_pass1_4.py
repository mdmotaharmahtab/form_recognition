```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Identify page type by structural markers
        
        # Family C: Variable details pages (data dictionaries)
        # These have "Variable details" header and column headers like "Export Name", "Type", etc.
        has_variable_details = any("Variable details" in line.text for line in lines)
        
        # Family C detection: Look for the characteristic column structure
        is_family_c = False
        if has_variable_details:
            # Check for multiple column headers in the expected y-range
            col_headers = [line for line in lines if 60 < line.y0 < 75 and line.bold]
            col_header_texts = [line.text for line in col_headers]
            if any("Export Name" in text for text in col_header_texts) and \
               any("Type" in text for text in col_header_texts):
                is_family_c = True
        
        # For Family C pages, extract fields from the data dictionary
        if is_family_c:
            # Find form name from the document header (top of page)
            form_name = ""
            for line in lines:
                # Look for the document ID line at the very top
                if line.y0 < 45 and "MAC186" in line.text:
                    # Extract form name from the document ID
                    # Format: MAC186_X11_201_00001_eCRF_v1_10_form_tracker_v1_6_06Mar2025
                    # We need to parse this to get a meaningful form name
                    # The form name is embedded in the ID
                    text = line.text
                    # Try to extract a meaningful name from the ID
                    # Look for patterns like "form_tracker" or other identifiers
                    parts = text.split('_')
                    for i, part in enumerate(parts):
                        if part == "form":
                            # Next part might be the form name
                            if i + 1 < len(parts):
                                form_name = parts[i+1].replace('_', ' ').title()
                                break
                    break
            
            # If we couldn't extract from ID, use a generic name
            if not form_name:
                form_name = "Data Dictionary"
            
            # Extract field names from the "Name" column
            # The Name column is the first data column after the bracket numbers
            # Look for lines with bracketed numbers [N] and extract the Name field
            bracket_pattern = re.compile(r'^\[(\d+)\]$')
            
            for i, line in enumerate(lines):
                match = bracket_pattern.match(line.text.strip())
                if match and line.y0 > 70:  # Skip header area
                    # The Name field is typically the next text element to the right
                    # Look for the field in the Name column (x position around 80-230)
                    for j in range(i + 1, min(i + 10, len(lines))):
                        other = lines[j]
                        # Same y position (same row)
                        if abs(other.y0 - line.y0) < 2:
                            # In the Name column (first column after bracket)
                            if 70 < other.x0 < 240:
                                field_label = other.text.strip()
                                if field_label and len(field_label) > 2:
                                    # Skip if it's an export name (all caps with underscores)
                                    if not (field_label.isupper() and '_' in field_label):
                                        results.append({
                                            "form_name": form_name,
                                            "field_name": field_label,
                                            "page": page_num
                                        })
                                        break
            continue
        
        # Family E: Simple visit divider pages (just "Visit:" and day number)
        # These have very few lines, large font, centered text
        if len(lines) < 10:
            has_visit = any("Visit:" in line.text and line.size > 15 for line in lines)
            has_day = any(re.match(r'Day \d+', line.text) and line.size > 15 for line in lines)
            if has_visit and has_day:
                # This is just a divider page, skip it
                continue
        
        # Family D: Actual CRF forms with field labels and entry markers [N]
        
        # Find form title for Family D pages
        form_name = ""
        for line in lines:
            # Form titles appear after the document header (y > 60) but not too far down
            if line.y0 > 250:
                break
            # Large font indicates form title
            if line.size >= 15.0 and line.y0 > 60:
                # Skip document ID at very top
                if "MAC186" not in line.text and "eCRF" not in line.text:
                    form_name = line.text.strip()
                    break
        
        # If no large title found, try bold section header
        if not form_name:
            for line in lines:
                if 45 < line.y0 < 60 and line.bold and line.size >= 7.0:
                    # Skip document ID line
                    if "MAC186" not in line.text and "eCRF" not in line.text and "Variable details" not in line.text:
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
            
            # Look for field label: typically bold text near the bracket
            field_label = None
            
            # Strategy 1: Check same horizontal line to the right (for checkboxes)
            # Some fields have the bracket on the left and the label on the right
            for other_idx in range(line_idx + 1, min(len(lines), line_idx + 15)):
                other = lines[other_idx]
                # Same or very close y position (same visual line)
                if abs(other.y0 - line.y0) < 3:
                    if other.bold and other.x0 > line.x0:
                        text = other.text.strip()
                        if text and len(text) > 0:
                            # Skip if it's in the header area
                            if other.y0 < 65:
                                continue
                            # Skip if it's just a number
                            if re.match(r'^\d+$', text):
                                continue
                            # Skip if it's another bracket
                            if bracket_pattern.match(text):
                                continue
                            # This could be a checkbox-style field
                            field_label = text
                            break
            
            # Strategy 2: Check same horizontal line to the left
            if not field_label:
                for other_idx in range(line_idx - 1, max(0, line_idx - 15), -1):
                    other = lines[other_idx]
                    # Same or very close y position (same visual line)
                    if abs(other.y0 - line.y0) < 3:
                        if other.bold and other.x0 < line.x0:
                            text = other.text.strip()
                            if text and len(text) > 0:
                                # Skip if it's in the header area
                                if other.y0 < 65:
                                    continue
                                # Skip if it's a single-word answer option positioned far right
                                if len(text.split()) == 1 and other.x0 > 400:
                                    continue
                                # Skip if it's just a number
                                if re.match(r'^\d+$', text):
                                    continue
                                field_label = text
                                break
            
            # Strategy 3: Check lines above (within reasonable distance)
            if not field_label:
                for other_idx in range(line_idx - 1, max(0, line_idx - 8), -1):
                    other = lines[other_idx]
                    # Line above (y difference 3-30 points)
                    if 3 < (line.y0 - other.y0) < 30:
                        if other.bold:
                            text = other.text.strip()
                            if text and len(text) > 0:
                                # Skip header area
                                if other.y0 < 65:
                                    continue
                                # Skip single-word items far right (likely answer options)
                                if len(text.split()) == 1 and other.x0 > 400:
                                    continue
                                # Skip numbers
                                if re.match(r'^\d+$', text):
                                    continue
                                # Check if it's reasonably aligned or close in x
                                if abs(other.x0 - line.x0) < 250:
                                    field_label = text
                                    break
            
            # Add field if we found a valid label
            if field_label:
                # Clean up label - remove trailing colons, extra spaces
                field_label = field_label.rstrip(':').strip()
                
                # Skip if label is just a bracketed number itself
                if bracket_pattern.match(field_label):
                    continue
                
                # Skip very short labels that are likely not real field names
                if len(field_label) < 2:
                    continue
                
                # Skip common answer options that might be mistaken for labels
                if field_label in ["Yes", "No"]:
                    continue
                
                results.append({
                    "form_name": form_name,
                    "field_name": field_label,
                    "page": page_num
                })
        
        # Also handle fields that may not have been caught by bracket-first approach
        # Look for bold text that appears to be field labels in structured positions
        for i, line in enumerate(lines):
            # Skip if already processed via bracket
            if i in bracket_lines:
                continue
            
            # Look for bold field labels
            if line.bold and line.size >= 7.0 and line.y0 > 70:
                text = line.text.strip()
                
                # Skip structural elements by position and characteristics
                # Skip header area
                if line.y0 < 65:
                    continue
                
                # Skip if it's just a number (row index)
                if re.match(r'^\d+$', text):
                    continue
                
                # Skip if it's a bracketed number
                if bracket_pattern.match(text):
                    continue
                
                # Skip very short text
                if len(text) < 3:
                    continue
                
                # Skip single-word items positioned far right (likely answer options)
                if len(text.split()) == 1 and line.x0 > 400:
                    continue
                
                # Skip common answer options
                if text in ["Yes", "No"]:
                    continue
                
                # Check if there's a bracket nearby (indicating this is a field)
                has_nearby_bracket = False
                for j in range(i, min(i + 5, len(lines))):
                    if abs(lines[j].y0 - line.y0) < 20:
                        if bracket_pattern.match(lines[j].text.strip()):
                            has_nearby_bracket = True
                            break
                
                # Only add if it looks like a field label with a bracket marker
                if has_nearby_bracket:
                    # Check if we already added this field (avoid duplicates)
                    already_added = False
                    for result in results:
                        if result["page"] == page_num and result["field_name"] == text:
                            already_added = True
                            break
                    
                    if not already_added:
                        results.append({
                            "form_name": form_name,
                            "field_name": text,
                            "page": page_num
                        })
    
    return results
```