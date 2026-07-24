# This CRF has form headers in large colored text, field labels on the left,
# and technical annotations on the right. Extract field labels while carrying
# forward form names across continuation pages.

import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Try to find form name: large colored header at top of page
        form_candidate = find_form_name(lines)
        if form_candidate:
            current_form = form_candidate
        
        # Skip if this looks like a reference/table page
        if is_reference_page(lines):
            continue
        
        # Extract field labels from this page
        fields = extract_fields_from_page(lines)
        
        for field_name in fields:
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return results

def find_form_name(lines) -> str:
    """Find form/section title - large colored text near top of page"""
    for line in lines[:20]:  # Check first 20 lines
        # Look for large colored headers (size >= 11, colored background)
        if line.size >= 11 and line.non_black and line.y0 < 100:
            text = line.text.strip()
            # Skip generic headers and codes
            if text and not re.match(r'^[\d\-]+$', text) and len(text) > 3:
                if not text.startswith('Study Events'):
                    return text
    return ""

def is_reference_page(lines) -> bool:
    """Detect reference/enumeration table pages without data entry fields"""
    # Look for table structure with "Coded" and "Decode" headers
    header_texts = [line.text.strip() for line in lines[:30] if line.bold]
    if 'Coded' in header_texts and 'Decode' in header_texts:
        return True
    
    # Check for Study Events table structure
    text_sample = ' '.join([line.text for line in lines[:50]])
    if 'Study Events' in text_sample and 'Category Visit' in text_sample:
        return True
    
    return False

def extract_fields_from_page(lines) -> List[str]:
    """Extract field labels from a page"""
    fields = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        text = line.text.strip()
        
        # Skip empty, very small text, or right-side annotations
        if not text or line.size < 6.5 or line.x0 > 400:
            i += 1
            continue
        
        # Skip machine codes and technical markers
        if is_machine_code(text):
            i += 1
            continue
        
        # Check if this is a field label (left side, reasonable size)
        if is_field_label(line, lines, i):
            # Collect multi-line label
            field_text = text
            j = i + 1
            
            # Join continuation lines
            while j < len(lines):
                next_line = lines[j]
                # Same x position, similar size, close y distance
                if (abs(next_line.x0 - line.x0) < 5 and 
                    abs(next_line.size - line.size) < 2 and
                    next_line.y0 - lines[j-1].y1 < 15 and
                    next_line.x0 < 250 and
                    not is_machine_code(next_line.text.strip()) and
                    not is_answer_option(next_line.text.strip())):
                    field_text += " " + next_line.text.strip()
                    j += 1
                else:
                    break
            
            # Clean and validate field
            field_text = clean_field_name(field_text)
            if is_valid_field(field_text):
                fields.append(field_text)
            
            i = j
        else:
            i += 1
    
    return fields

def is_machine_code(text: str) -> bool:
    """Check if text is a machine code or technical annotation"""
    # Square bracket codes
    if re.match(r'^\[[\w\s_]+\]$', text):
        return True
    # SAS field names
    if 'SAS Field Name:' in text:
        return True
    # Pure codes
    if re.match(r'^[A-Z]{2,}[A-Z0-9_]*$', text) and len(text) < 15:
        return True
    return False

def is_field_label(line, lines, idx) -> bool:
    """Determine if a line is a field label"""
    text = line.text.strip()
    
    # Must be on left side
    if line.x0 > 250:
        return False
    
    # Reasonable label size
    if line.size < 7 or line.size > 11:
        return False
    
    # Skip if it's just a code
    if is_machine_code(text):
        return False
    
    # Skip column headers
    if line.bold and line.y0 < 80:
        return False
    
    # Look for input indicators nearby (next few lines)
    for j in range(idx + 1, min(idx + 5, len(lines))):
        next_text = lines[j].text.strip()
        # Check for input patterns
        if re.search(r'\[_+\]|O\s+\w+|\[_\|_\]', next_text):
            return True
        # Or if followed by answer options
        if lines[j].x0 > line.x0 + 150 and re.match(r'^O\s+', next_text):
            return True
    
    # Check if text suggests it's a question/label
    if len(text) > 15 and not text.isupper():
        # Has question-like words
        if any(word in text.lower() for word in ['date', 'time', 'performed', 'result', 'collection', 'examination']):
            return True
    
    return False

def is_answer_option(text: str) -> bool:
    """Check if text is an answer option"""
    # Radio button options
    if re.match(r'^O\s+\w', text):
        return True
    # Common option patterns
    if text in ['Yes', 'No', 'Normal', 'Abnormal', 'Unknown']:
        return True
    return False

def clean_field_name(text: str) -> str:
    """Clean up field name text"""
    # Remove machine codes in brackets
    text = re.sub(r'\[[\w\s_]+\]', '', text)
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def is_valid_field(text: str) -> bool:
    """Validate that text is a real field label"""
    if not text or len(text) < 3:
        return False
    
    # Skip pure codes
    if re.match(r'^[A-Z0-9_]+$', text):
        return False
    
    # Skip dates/numbers
    if re.match(r'^[\d\-/]+$', text):
        return False
    
    # Skip format specifications
    if text.startswith('dd-') or text.startswith('Code List:'):
        return False
    
    # Skip common non-fields
    skip_patterns = ['Format:', 'Data Type:', 'Origin:', 'Aliases:', 
                     'Description:', 'Mandatory:', 'Disallow Future']
    if any(text.startswith(p) for p in skip_patterns):
        return False
    
    return True
