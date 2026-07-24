```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form title: large blue/colored text at top (size >= 13, non-black)
        for line in lines:
            if line.size >= 13.0 and line.non_black:
                # This is likely a form title - carry it forward
                text = line.text.strip()
                # Skip machine codes and metadata
                if not text.startswith('[') and 'TYPE:' not in text and 'VISIBILITY:' not in text:
                    current_form = text
                    break
        
        # Extract fields based on structural patterns
        fields = extract_fields_from_page(lines, current_form, page_num)
        results.extend(fields)
    
    return results

def extract_fields_from_page(lines, form_name, page_num):
    fields = []
    
    if not lines:
        return fields
    
    # Detect page layout type
    layout_info = analyze_page_layout(lines)
    
    # Process lines sequentially
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip metadata annotations (red/colored text with technical markers)
        if line.non_black:
            text = line.text.strip()
            # Machine codes, type annotations, visibility markers
            if (text.startswith('[') or 
                'TYPE:' in text or 
                'VISIBILITY:' in text or
                'Read-only' in text):
                i += 1
                continue
        
        # Field labels: black text, left side of page, reasonable size
        # Use relative positioning based on page width
        page_width = layout_info.get('page_width', 600)
        left_boundary = page_width * 0.33  # Left third of page
        right_boundary = page_width * 0.6  # Exclude far-right column
        
        if (not line.non_black and 
            line.x0 < left_boundary and 
            7.0 <= line.size <= 11.0):
            
            text = line.text.strip()
            
            # Skip if empty or too short
            if len(text) < 2:
                i += 1
                continue
            
            # Skip by structural position: answer options are far right
            if line.x0 > right_boundary:
                i += 1
                continue
            
            # Skip pure numbers (page numbers, etc.)
            if re.match(r'^\d+$', text):
                i += 1
                continue
            
            # Skip pure punctuation/symbols
            if re.match(r'^[\d\s\.\,\-\(\)]+$', text):
                i += 1
                continue
            
            # Skip date-like patterns (table cells in change history)
            if re.match(r'^\d{1,2}[-/]\w{3}[-/]\d{4}$', text, re.IGNORECASE):
                i += 1
                continue
            if re.match(r'^\d{1,2}\w{3}\d{4}$', text):
                i += 1
                continue
            
            # Collect multi-line labels (continuation lines at similar x, close y)
            label_parts = [text]
            j = i + 1
            
            while j < len(lines):
                next_line = lines[j]
                
                # Stop at colored/metadata lines
                if next_line.non_black:
                    break
                
                # Stop if x position shifts significantly (> 10 units)
                if abs(next_line.x0 - line.x0) > 10:
                    break
                
                # Stop if y gap is too large (> 25 units)
                if j > i and next_line.y0 - lines[j-1].y0 > 25:
                    break
                
                # Stop if moved to answer column (far right)
                if next_line.x0 > right_boundary:
                    break
                
                # Stop if size changed significantly (different text class)
                if abs(next_line.size - line.size) > 2:
                    break
                
                # Add continuation line
                next_text = next_line.text.strip()
                if (not next_line.non_black and 
                    7.0 <= next_line.size <= 11.0 and
                    len(next_text) > 0):
                    label_parts.append(next_text)
                    j += 1
                else:
                    break
            
            # Join multi-line label
            field_label = ' '.join(label_parts)
            
            # Final validation: must look like a real field label
            if is_valid_field_label(field_label, layout_info):
                fields.append({
                    "form_name": form_name,
                    "field_name": field_label,
                    "page": page_num
                })
            
            i = j
        else:
            i += 1
    
    return fields

def analyze_page_layout(lines):
    """Analyze the layout structure of the page"""
    info = {}
    
    # Determine page width from rightmost text
    if lines:
        max_x = max(line.x0 + 100 for line in lines)  # Approximate right edge
        info['page_width'] = max_x
    else:
        info['page_width'] = 600
    
    # Collect x positions of black text in normal size range
    x_positions = [line.x0 for line in lines if not line.non_black and 7.0 <= line.size <= 11.0]
    
    if not x_positions:
        info['layout_type'] = "unknown"
        return info
    
    # Count lines in different horizontal zones
    left_zone = info['page_width'] * 0.25
    middle_zone = info['page_width'] * 0.5
    right_zone = info['page_width'] * 0.75
    
    left_count = sum(1 for x in x_positions if x < left_zone)
    middle_count = sum(1 for x in x_positions if left_zone <= x < middle_zone)
    right_count = sum(1 for x in x_positions if x >= middle_zone)
    
    # Determine if this is a table layout (many items in right columns)
    if right_count > len(x_positions) * 0.3:
        info['layout_type'] = "table"
    else:
        info['layout_type'] = "form"
    
    # Check for single-word lines (potential column headers)
    single_word_lines = []
    for line in lines:
        if not line.non_black and 7.0 <= line.size <= 11.0:
            text = line.text.strip()
            if len(text.split()) == 1 and len(text) > 2:
                single_word_lines.append((text, line.x0, line.y0))
    
    info['single_word_count'] = len(single_word_lines)
    
    return info

def is_valid_field_label(text, layout_info):
    """Check if text looks like a valid field label using structural criteria"""
    text_stripped = text.strip()
    
    # Must have reasonable length
    if len(text_stripped) < 3:
        return False
    
    # Must contain at least one letter
    if not re.search(r'[a-zA-Z]', text_stripped):
        return False
    
    # Structural filter: single-word items in table layouts are likely headers
    # unless they're part of a longer phrase
    word_count = len(text_stripped.split())
    if word_count == 1 and layout_info.get('layout_type') == 'table':
        # Single words in table layouts are typically column headers
        # Allow only if they're clearly field-specific (contain specific markers)
        if not any(marker in text_stripped.lower() for marker in ['?', 'date', 'time', 'performed', 'obtained']):
            return False
    
    # Skip "Row N" patterns (table row labels)
    if re.match(r'^row\s+\d+$', text_stripped.lower()):
        return False
    
    # Skip if it looks like a rating scale anchor (just a number in parens)
    if re.match(r'^\(\d+\)$', text_stripped):
        return False
    
    # Skip very long instructional text (likely instructions, not field labels)
    # Field labels are typically under 100 characters
    if len(text_stripped) > 100:
        return False
    
    # Skip date patterns that look like table cells
    if re.match(r'^\d{1,2}[-/]\w{3,9}[-/]\d{4}$', text_stripped, re.IGNORECASE):
        return False
    if re.match(r'^\d{1,2}\w{3,9}\d{4}$', text_stripped):
        return False
    
    # Skip if it looks like a form section reference (e.g., "AE page", "ConMed page")
    # These are typically 2-3 words ending with "page" or "form"
    if word_count <= 3 and re.search(r'\b(page|form)\b', text_stripped.lower()):
        return False
    
    # Skip timepoint labels that are just codes (e.g., "PK 1h", "PK 2h")
    # These are column headers in PK tables
    if word_count <= 3 and re.match(r'^[A-Z]{2,}\s+[\d\.]+h?$', text_stripped):
        return False
    
    return True
```