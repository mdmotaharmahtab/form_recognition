import re
from typing import List, Dict, Tuple

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title: large colored text, typically size >= 15
        form_title_candidates = [
            ln for ln in lines 
            if ln.size >= 15.0 and ln.non_black
        ]
        if form_title_candidates:
            # Take the first/topmost large colored text as form title
            current_form = form_title_candidates[0].text.strip()
        
        # Skip copyright/definition pages (cluster 0)
        if is_copyright_page(lines):
            continue
        
        # Skip repeatable row instruction pages (cluster 2)
        if is_repeatable_instruction_page(lines):
            continue
        
        # Detect if this is a change history table page
        if is_change_history_table(lines):
            continue
        
        # Extract fields from this page
        fields = extract_fields_from_page(lines)
        
        for field_name in fields:
            records.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return records

def is_copyright_page(lines):
    """Detect copyright/definition pages by structural markers"""
    # Look for copyright symbol and specific y-position patterns
    for ln in lines:
        if ln.y0 > 250 and ln.y0 < 300 and '©' in ln.text:
            return True
        if 'posnerk@nyspi.columbia.edu' in ln.text:
            return True
    return False

def is_repeatable_instruction_page(lines):
    """Detect pages with just repeatable row instructions"""
    # Count content lines (excluding page numbers and titles)
    content_lines = [
        ln for ln in lines 
        if ln.size < 15 and not re.match(r'Page \d+ of \d+', ln.text.strip())
    ]
    
    # If very few content lines and one mentions repeatable row
    if len(content_lines) <= 2:
        for ln in content_lines:
            if 'Repeatable row' in ln.text or 'Add Row button' in ln.text:
                return True
    
    return False

def is_change_history_table(lines):
    """Detect change history table pages by structural patterns"""
    # Look for version number patterns (0.1, 0.1.1, etc.) in tabular layout
    version_pattern = re.compile(r'^\d+\.\d+(\.\d+)?$')
    version_count = 0
    
    # Check for multiple version numbers at similar x positions (left column)
    for ln in lines:
        if ln.x0 < 100 and version_pattern.match(ln.text.strip()):
            version_count += 1
    
    # If 5+ version numbers, likely a change history table
    if version_count >= 5:
        return True
    
    # Also check for tabular structure: many short entries at regular x positions
    left_col = [ln for ln in lines if 50 < ln.x0 < 120 and ln.size < 12]
    mid_col = [ln for ln in lines if 180 < ln.x0 < 280 and ln.size < 12]
    right_col = [ln for ln in lines if 380 < ln.x0 < 480 and ln.size < 12]
    
    # If all three columns have multiple entries, likely a table
    if len(left_col) >= 5 and len(mid_col) >= 5 and len(right_col) >= 3:
        return True
    
    return False

def extract_fields_from_page(lines):
    """Extract field labels from a page"""
    fields = []
    i = 0
    
    while i < len(lines):
        ln = lines[i]
        
        # Skip page numbers
        if re.match(r'Page \d+ of \d+', ln.text.strip()):
            i += 1
            continue
        
        # Skip form titles (large colored text)
        if ln.size >= 15.0 and ln.non_black:
            i += 1
            continue
        
        # Skip table column headers (single words at top of page, y < 150)
        if ln.y0 < 150 and len(ln.text.strip().split()) <= 2 and ln.size >= 10:
            i += 1
            continue
        
        # Candidate field: black text, size 8.5-11pt, in content area (y > 150)
        if not ln.non_black and 8.5 <= ln.size <= 11 and ln.y0 > 150:
            text = ln.text.strip()
            
            # Skip empty or very short text
            if len(text) < 3:
                i += 1
                continue
            
            # Skip version numbers (structural pattern)
            if re.match(r'^\d+\.\d+(\.\d+)?$', text):
                i += 1
                continue
            
            # Skip dates (structural pattern)
            if re.match(r'^\d+[\-/]\d+[\-/]\d+$', text):
                i += 1
                continue
            
            # Skip technical markers
            if text.startswith('[') and text.endswith(']'):
                i += 1
                continue
            
            # Skip table row labels
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip data in table columns (x position > 200 indicates column data)
            if ln.x0 > 200:
                i += 1
                continue
            
            # Check for multi-line field (continuation lines)
            field_text = text
            j = i + 1
            while j < len(lines):
                next_ln = lines[j]
                # Continuation: similar x (within 15pt), y within 25pt, same size range, black
                if (abs(next_ln.x0 - ln.x0) < 15 and 
                    next_ln.y0 - lines[j-1].y1 < 25 and 
                    not next_ln.non_black and 
                    8.5 <= next_ln.size <= 11 and
                    next_ln.x0 < 200):  # Not in table column
                    field_text += " " + next_ln.text.strip()
                    j += 1
                else:
                    break
            
            # Clean and validate
            field_text = clean_field_text(field_text)
            if is_valid_field(field_text):
                fields.append(field_text)
            
            i = j
        else:
            i += 1
    
    return fields

def clean_field_text(text):
    """Clean up field text"""
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove trailing question marks
    text = re.sub(r'\?+$', '', text)
    return text

def is_valid_field(text):
    """Validate that text is a real field label"""
    if len(text) < 3:
        return False
    
    # Skip pure numeric patterns (versions, codes)
    if re.match(r'^[\d\.\-]+$', text):
        return False
    
    # Skip single-word answers
    if text in ['Yes', 'No', 'Unknown', 'Collected']:
        return False
    
    # Skip very short single words that are likely column headers or data
    if len(text.split()) == 1 and len(text) < 8:
        return False
    
    # Must contain at least one letter
    if not re.search(r'[a-zA-Z]', text):
        return False
    
    return True
