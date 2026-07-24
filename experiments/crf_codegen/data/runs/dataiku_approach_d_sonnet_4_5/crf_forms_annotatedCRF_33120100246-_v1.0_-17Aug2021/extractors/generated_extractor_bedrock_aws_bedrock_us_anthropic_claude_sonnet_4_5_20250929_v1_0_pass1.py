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
    layout_type = detect_layout_type(lines)
    
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
        # Use relative positioning: x < 200 (left half), size 7-11
        if (not line.non_black and 
            line.x0 < 200 and 
            7.0 <= line.size <= 11.0):
            
            text = line.text.strip()
            
            # Skip if empty or too short
            if len(text) < 2:
                i += 1
                continue
            
            # Skip by structural position: answer options are far right (x > 350)
            if line.x0 > 350:
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
                if next_line.x0 > 350:
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
            if is_valid_field_label(field_label, layout_type):
                fields.append({
                    "form_name": form_name,
                    "field_name": field_label,
                    "page": page_num
                })
            
            i = j
        else:
            i += 1
    
    return fields

def detect_layout_type(lines):
    """Detect the layout type of the page"""
    # Check for table-like structures (many lines at similar x positions)
    x_positions = [line.x0 for line in lines if not line.non_black and 7.0 <= line.size <= 11.0]
    
    if not x_positions:
        return "unknown"
    
    # Count lines in left column (x < 150)
    left_count = sum(1 for x in x_positions if x < 150)
    
    # Count lines in right area (x > 300)
    right_count = sum(1 for x in x_positions if x > 300)
    
    # If many lines on right, likely a table with columns
    if right_count > len(x_positions) * 0.3:
        return "table"
    
    return "form"

def is_valid_field_label(text, layout_type="form"):
    """Check if text looks like a valid field label"""
    text_stripped = text.strip()
    
    # Must have reasonable length
    if len(text_stripped) < 3:
        return False
    
    # Must contain at least one letter
    if not re.search(r'[a-zA-Z]', text_stripped):
        return False
    
    # Skip if it's just a single common word that's likely a table header
    # Use structural position instead of hardcoded list - but keep a minimal set
    # of very common generic headers that appear in many table contexts
    single_word = len(text_stripped.split()) == 1
    if single_word and text_stripped in ['Test', 'Result', 'Sample', 'Status', 
                                          'Date', 'Time', 'Number', 'Type', 'Version',
                                          'Timepoint']:
        return False
    
    # Skip "Row N" patterns (table row labels)
    if re.match(r'^row\s+\d+$', text_stripped.lower()):
        return False
    
    # Skip if it looks like a rating scale anchor (just a number in parens)
    if re.match(r'^\(\d+\)$', text_stripped):
        return False
    
    # Skip instructional text (long sentences with "please", "if", etc.)
    # These are typically longer than field labels and contain specific keywords
    if len(text_stripped) > 80:
        lower_text = text_stripped.lower()
        if any(keyword in lower_text for keyword in ['please go to', 'if yes then', 
                                                       'collect vital signs', 'after subject has']):
            return False
    
    # Skip date patterns that look like table cells
    if re.match(r'^\d{1,2}[-/]\w{3,9}[-/]\d{4}$', text_stripped, re.IGNORECASE):
        return False
    if re.match(r'^\d{1,2}\w{3,9}\d{4}$', text_stripped):
        return False
    
    # Skip if it looks like a form section reference (e.g., "AE page", "ConMed page")
    if re.search(r'\b(page|form)\b', text_stripped.lower()) and len(text_stripped.split()) <= 3:
        return False
    
    # Skip PK-related timepoint labels (these are column headers in PK tables)
    if re.search(r'\bPK\b', text_stripped) and len(text_stripped.split()) <= 4:
        return False
    
    return True
