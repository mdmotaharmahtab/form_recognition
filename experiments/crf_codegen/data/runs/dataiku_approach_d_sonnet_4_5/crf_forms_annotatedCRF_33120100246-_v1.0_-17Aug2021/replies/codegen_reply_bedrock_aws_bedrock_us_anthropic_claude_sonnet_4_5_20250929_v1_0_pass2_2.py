```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    last_form_name = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from the page
        form_name = extract_form_name(lines)
        if form_name:
            last_form_name = form_name
        else:
            form_name = last_form_name
        
        # Extract fields from this page
        page_fields = extract_fields_from_page(lines, form_name, page_num)
        results.extend(page_fields)
    
    return results

def extract_form_name(lines):
    """Extract the form/section title from the page."""
    # Look for large colored text near the top (typically form titles)
    for line in lines[:20]:
        if line.size >= 13 and line.non_black and line.y0 < 150:
            text = line.text.strip()
            # Skip if it looks like a machine code
            if not re.match(r'^\[.*\]$', text):
                return text
    return ""

def is_machine_code(text):
    """Check if text is a machine code."""
    return bool(re.match(r'^\[.*\]$', text))

def is_answer_option(text):
    """Check if text is an answer option (structural check)."""
    # Common answer options - but check context too
    simple_options = {'Yes', 'No', 'N/A', 'Met', 'Not Met', 'Positive', 'Negative'}
    return text in simple_options

def is_row_label(text):
    """Check if text is just a row label."""
    return bool(re.match(r'^Row\s+\d+$', text))

def extract_fields_from_page(lines, form_name, page_num):
    """Extract all fields from a page."""
    results = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        text = line.text.strip()
        
        # Skip machine codes
        if is_machine_code(text):
            i += 1
            continue
        
        # Skip TYPE/VISIBILITY annotations
        if text.startswith('[TYPE:') or text.startswith('[VISIBILITY:'):
            i += 1
            continue
        
        # Skip row labels
        if is_row_label(text):
            i += 1
            continue
        
        # Check if this is a field label candidate
        if is_field_label_candidate(line, lines, i):
            # Extract the full field text (may span multiple lines)
            field_text, next_i = extract_full_field_text(lines, i)
            
            if field_text and len(field_text) > 2:
                results.append({
                    'form_name': form_name,
                    'field_name': field_text,
                    'page': page_num
                })
            
            i = next_i
        else:
            i += 1
    
    return results

def is_field_label_candidate(line, lines, i):
    """Determine if a line is likely a field label."""
    text = line.text.strip()
    
    # Skip empty or very short text
    if len(text) <= 2:
        return False
    
    # Skip answer options (check position - they're typically right-aligned)
    if is_answer_option(text):
        # Answer options are typically positioned on the right side (x > 400)
        if line.x0 > 400:
            return False
    
    # Field labels are typically:
    # 1. Questions ending with ?
    if text.endswith('?'):
        # Check size is reasonable (not too large, not too small)
        if 6 <= line.size <= 11:
            return True
    
    # 2. Text with specific patterns (numbered criteria, etc.)
    if re.match(r'^\\?\d+\\.', text):
        # Numbered items like "\23." or "1."
        if 6 <= line.size <= 10:
            return True
    
    # 3. Field labels followed by machine codes
    if i + 1 < len(lines):
        next_text = lines[i+1].text.strip()
        if is_machine_code(next_text):
            # This is likely a field label
            if 6 <= line.size <= 11 and len(text) > 3:
                return True
    
    # 4. Bold text that looks like a label (but not row labels)
    if line.bold and 6 <= line.size <= 10:
        if not is_row_label(text) and len(text) > 5:
            # Check if it ends with colon or looks like a label
            if text.endswith(':') or 'abnormal' in text.lower() or 'comment' in text.lower():
                return True
    
    # 5. Specific patterns for lab results pages
    if 'clinically significant abnormal' in text.lower():
        return True
    if 'Investigator comment' in text:
        return True
    if text.startswith('Result of'):
        return True
    if 'Were there any' in text or 'Are there any' in text:
        return True
    
    return False

def extract_full_field_text(lines, start_i):
    """Extract full field text that may span multiple lines."""
    text_parts = [lines[start_i].text.strip()]
    current_line = lines[start_i]
    i = start_i + 1
    
    # Collect continuation lines
    while i < len(lines):
        next_line = lines[i]
        next_text = next_line.text.strip()
        
        # Stop at machine codes
        if is_machine_code(next_text):
            break
        
        # Stop at TYPE/VISIBILITY annotations
        if next_text.startswith('[TYPE:') or next_text.startswith('[VISIBILITY:'):
            break
        
        # Stop at answer options on the right side
        if is_answer_option(next_text) and next_line.x0 > 400:
            break
        
        # Stop at row labels
        if is_row_label(next_text):
            break
        
        # Check if this is a continuation line
        # Continuation lines are close vertically and have similar styling
        y_diff = next_line.y0 - current_line.y0
        
        # If too far apart vertically, stop
        if y_diff > 25:
            break
        
        # If it's a new section (much larger text), stop
        if next_line.size > current_line.size + 2:
            break
        
        # If it's on the left side and similar size, it's likely a continuation
        if next_line.x0 < 300 and abs(next_line.size - current_line.size) < 2:
            # Check if it's not a new field starting
            if not (next_text.endswith('?') and y_diff > 15):
                text_parts.append(next_text)
                current_line = next_line
                i += 1
            else:
                break
        else:
            break
    
    # Join all parts
    full_text = ' '.join(text_parts)
    
    # Clean up the text
    full_text = re.sub(r'\s+', ' ', full_text).strip()
    
    return full_text, i

```