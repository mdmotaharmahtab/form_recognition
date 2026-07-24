import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Detect page type
        page_type = classify_page(lines)
        
        if page_type == "visit_separator":
            # Skip visit separator pages (just "Visit:" and day number)
            continue
        
        # Look for form title: large text (size > 15) in upper portion
        for line in lines:
            if line.size > 15 and 60 < line.y0 < 110:
                # Exclude page identifiers
                if not re.match(r'^MAC\d+_', line.text) and line.text.strip():
                    text = line.text.strip()
                    # Skip if it's just "Visit:" or a day number
                    if text not in ["Visit:", "Day"] and not re.match(r'^Day \d+$', text):
                        current_form = text
                        break
        
        # Extract fields based on page type
        if page_type == "metadata":
            fields = extract_fields_from_metadata(lines)
        else:  # data_entry
            fields = extract_fields_from_data_entry(lines)
        
        for field_name in fields:
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return results

def classify_page(lines: List) -> str:
    """Determine the page layout type."""
    # Check for visit separator: very sparse page with just "Visit:" and day
    content_lines = [l for l in lines if l.y0 > 50 and l.y0 < 800]
    if len(content_lines) <= 3:
        texts = [l.text.strip() for l in content_lines]
        if "Visit:" in texts or any(re.match(r'^Day \d+$', t) for t in texts):
            return "visit_separator"
    
    # Check for metadata page: has "Variable details" header
    for line in lines:
        if line.text.strip() == "Variable details" and line.bold:
            return "metadata"
    
    return "data_entry"

def extract_fields_from_metadata(lines: List) -> List[str]:
    """Extract field names from Variable details metadata pages."""
    fields = []
    
    # Find the "Name" column header to establish x position
    name_col_x = None
    for line in lines:
        if line.text.strip() == "Name" and line.bold:
            name_col_x = line.x0
            break
    
    if name_col_x is None:
        return fields
    
    # Extract field names from the Name column
    # They appear at similar x position to the header, are not bold, not bracketed IDs
    for line in lines:
        # Skip headers and bracketed IDs
        if line.bold or re.match(r'^\[\d+\]$', line.text.strip()):
            continue
        
        # Check if in Name column (within reasonable tolerance)
        if abs(line.x0 - name_col_x) < 15:
            text = line.text.strip()
            # Skip empty, column headers, and very short text
            if text and len(text) > 2:
                # Skip if it looks like a column header value
                if text not in ["Name", "Export Name", "Type", "Max length", "Categories"]:
                    fields.append(text)
    
    return fields

def is_answer_option(text: str, line, prev_line=None) -> bool:
    """Determine if text is an answer option rather than a field label."""
    text = text.strip()
    
    # Very short answer pairs
    if text in ["Yes No", "No Yes"]:
        return True
    
    # Very long concatenated option lists (>100 chars with multiple words)
    if len(text) > 100 and text.count(' ') > 5:
        # Check if it looks like concatenated options
        if any(keyword in text for keyword in ["American Indian", "Pacific Islander", "African American", "Not Reported"]):
            return True
    
    # If previous line was a bold field label and this is indented slightly, it's likely an option
    if prev_line and prev_line.bold and not line.bold:
        if line.x0 > prev_line.x0 + 10:  # Indented from the label
            return True
    
    return False

def extract_fields_from_data_entry(lines: List) -> List[str]:
    """Extract field labels from data-entry form pages."""
    fields = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Skip page headers and footers
        if line.y0 < 50 or line.y0 > 800:
            i += 1
            continue
        
        text = line.text.strip()
        if not text:
            i += 1
            continue
        
        # Skip bracketed IDs (they're not field labels themselves)
        if re.match(r'^\[\d+\]$', text):
            i += 1
            continue
        
        # Skip standalone row numbers at far left
        if re.match(r'^\d{1,3}$', text) and line.x0 < 50:
            i += 1
            continue
        
        # Field labels: bold, reasonable size, in left/center area
        if line.bold and 6 <= line.size <= 11 and line.x0 < 450:
            # Skip if it's a page identifier
            if re.match(r'^MAC\d+_', text):
                i += 1
                continue
            
            # Skip common structural headers that appear at specific positions
            # (top of page, very consistent y position across pages)
            if line.y0 < 70 and text in ["Variable details"]:
                i += 1
                continue
            
            # This is a field label
            field_text = text
            
            # Check for multi-line labels (continuation at similar x, close y)
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # Continuation: similar x, reasonable y gap, not a new field marker
                if (abs(next_line.x0 - line.x0) < 20 and 
                    0 < next_line.y0 - lines[j-1].y0 < 20 and
                    not re.search(r'^\[\d+\]$', next_line.text.strip())):
                    # Stop if next line is also bold (new field) or far indented (answer option)
                    if next_line.bold or next_line.x0 > line.x0 + 30:
                        break
                    field_text += " " + next_line.text.strip()
                    j += 1
                else:
                    break
            
            # Clean up: remove bracketed IDs embedded in the label
            field_text = re.sub(r'\s*\[\d+\]\s*', ' ', field_text).strip()
            
            # Final validation: must have reasonable length and not be an answer option
            if field_text and len(field_text) > 1:
                # Check if this looks like an answer option
                prev_line = lines[i-1] if i > 0 else None
                if not is_answer_option(field_text, line, prev_line):
                    fields.append(field_text)
            
            i = j if j > i + 1 else i + 1
        else:
            i += 1
    
    return fields
