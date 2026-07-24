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
            if line.size >= 13.0 and line.non_black and '#004c99' in str(line.non_black):
                text = line.text.strip()
                # Skip if it's a machine code
                if not (text.startswith('[') and text.endswith(']')):
                    form_name = text
                    break
        
        # Extract fields from this page (even if no form_name found)
        page_fields = extract_fields_from_page(lines, form_name, page_num)
        records.extend(page_fields)
    
    return records

def extract_fields_from_page(lines: List, form_name: str, page_num: int) -> List[Dict]:
    """Extract field labels from a page."""
    fields = []
    
    # Analyze page structure
    page_width = max((line.x1 for line in lines if line.text.strip()), default=612)
    page_height = max((line.y1 for line in lines if line.text.strip()), default=792)
    
    # Find left margin (where main content starts)
    left_margin = min((line.x0 for line in lines if line.text.strip() and not line.text.strip().startswith('[')), default=45)
    
    # Identify machine code lines (red text in brackets)
    machine_code_lines = set()
    for idx, line in enumerate(lines):
        text = line.text.strip()
        if (text.startswith('[') and text.endswith(']')) or \
           (line.non_black and '#ff0000' in str(line.non_black)):
            machine_code_lines.add(idx)
    
    # Identify answer option positions (right side of page, specific words)
    # These are positioned in columns on the right side
    answer_option_x_positions = []
    answer_keywords = {'Positive', 'Negative', 'Not Done', 'Yes', 'No', 'Normal', 'Abnormal', 'Not Applicable'}
    for line in lines:
        text = line.text.strip()
        if text in answer_keywords and line.x0 > page_width * 0.45:
            answer_option_x_positions.append(line.x0)
    
    # Identify field labels that are positioned to the left with answer options to their right
    # These are typically drug names, body system names, etc.
    left_column_labels = []
    for idx, line in enumerate(lines):
        text = line.text.strip()
        if idx in machine_code_lines or not text:
            continue
        
        # Check if this is a left-aligned label with answer options to its right
        if line.x0 < page_width * 0.3 and line.size >= 7.0 and line.size <= 10.0:
            # Look for answer options on the same or nearby y-coordinate
            has_answer_options_right = False
            for other_line in lines:
                other_text = other_line.text.strip()
                # Check if answer option is to the right and at similar y position
                if other_text in answer_keywords and \
                   other_line.x0 > page_width * 0.45 and \
                   abs(other_line.y0 - line.y0) < 10:
                    has_answer_options_right = True
                    break
            
            if has_answer_options_right:
                left_column_labels.append((idx, text))
    
    # Process lines
    i = 0
    while i < len(lines):
        line = lines[i]
        text = line.text.strip()
        
        # Skip empty lines
        if not text:
            i += 1
            continue
        
        # Skip machine codes
        if i in machine_code_lines:
            i += 1
            continue
        
        # Check if this is a left-column label (e.g., drug names, body systems)
        is_left_column = any(idx == i for idx, _ in left_column_labels)
        if is_left_column:
            field_text = clean_field_text(text)
            if is_valid_field(field_text):
                fields.append({
                    'form_name': form_name,
                    'field_name': field_text,
                    'page': page_num + 1
                })
            i += 1
            continue
        
        # Skip if it's an answer option (structural check)
        if is_answer_option_structural(line, text, page_width, answer_option_x_positions):
            i += 1
            continue
        
        # Check if this is a field label
        if is_field_label(line, text, left_margin, page_width):
            # Collect multi-line field labels
            field_text = text
            j = i + 1
            
            # Look ahead for continuation lines
            while j < len(lines):
                if j in machine_code_lines:
                    j += 1
                    continue
                    
                next_line = lines[j]
                next_text = next_line.text.strip()
                
                if not next_text:
                    j += 1
                    continue
                
                # Stop if we hit an answer option
                if is_answer_option_structural(next_line, next_text, page_width, answer_option_x_positions):
                    break
                
                # Stop if next line is too far down
                if next_line.y0 - line.y1 > 20:
                    break
                
                # Stop if it's a new field (starts at left margin and different style)
                if abs(next_line.x0 - left_margin) < 10 and \
                   (next_line.bold or next_line.size > line.size + 1):
                    break
                
                # Check if it's a continuation
                if is_continuation(line, next_line, left_margin):
                    field_text += ' ' + next_text
                    j += 1
                else:
                    break
            
            # Clean up the field text
            field_text = clean_field_text(field_text)
            
            # Only add if it looks like a real field
            if is_valid_field(field_text):
                fields.append({
                    'form_name': form_name,
                    'field_name': field_text,
                    'page': page_num + 1
                })
            
            i = j
        else:
            i += 1
    
    return fields

def is_field_label(line, text: str, left_margin: float, page_width: float) -> bool:
    """Check if a line is likely a field label using structural criteria."""
    # Must be black text (or dark gray #454545)
    if line.non_black:
        color = str(line.non_black).lower()
        if '#454545' not in color:
            return False
    
    # Must have reasonable size (not too small, not too large)
    if line.size < 6.5 or line.size > 16.0:
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
    
    # Must start in the left portion of the page (not answer options on right)
    if line.x0 > page_width * 0.55:
        return False
    
    return True

def is_answer_option_structural(line, text: str, page_width: float, known_positions: List[float]) -> bool:
    """Check if text is an answer option using structural position."""
    # Common answer option words
    answer_keywords = {'Positive', 'Negative', 'Not Done', 'Yes', 'No', 'Normal', 
                      'Abnormal', 'Not Applicable', 'Scan'}
    
    if text not in answer_keywords:
        return False
    
    # Check if positioned on the right side of the page (in answer columns)
    # Answer options are typically in the right 55% of the page
    if line.x0 > page_width * 0.45:
        return True
    
    # Check if at a known answer option x-position
    for pos in known_positions:
        if abs(line.x0 - pos) < 20:
            return True
    
    return False

def is_continuation(prev_line, next_line, left_margin: float) -> bool:
    """Check if next_line is a continuation of prev_line."""
    # Similar x position (within 30 points or indented slightly)
    x_diff = abs(next_line.x0 - prev_line.x0)
    if x_diff > 50:
        return False
    
    # Similar size (within 2 points)
    if abs(next_line.size - prev_line.size) > 2:
        return False
    
    # Must be black or dark gray text
    if next_line.non_black:
        color = str(next_line.non_black).lower()
        if '#454545' not in color:
            return False
    
    # Not a machine code
    if next_line.text.strip().startswith('['):
        return False
    
    return True

def is_valid_field(text: str) -> bool:
    """Check if cleaned text is a valid field label."""
    if not text or len(text) < 3:
        return False
    
    # Skip if it's just a number
    if text.isdigit():
        return False
    
    # Skip if it's just punctuation
    if all(c in '.,;:!?-()[]{}' for c in text):
        return False
    
    # Skip common structural patterns (not specific text)
    # These are generic patterns that indicate non-field content
    if re.match(r'^Row\s+\d+$', text, re.IGNORECASE):
        return False
    
    if re.match(r'^\(\d+\)$', text):
        return False
    
    # Skip very long text that looks like instructions or descriptions
    # Field labels are typically concise (under 200 characters)
    if len(text) > 200:
        return False
    
    return True

def clean_field_text(text: str) -> str:
    """Clean up field text."""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Strip leading/trailing whitespace
    text = text.strip()
    
    return text
