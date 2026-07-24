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
            if is_valid_field_label(field_label):
                fields.append({
                    "form_name": form_name,
                    "field_name": field_label,
                    "page": page_num
                })
            
            i = j
        else:
            i += 1
    
    return fields

def is_valid_field_label(text):
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
                                          'Date', 'Time', 'Number', 'Type']:
        return False
    
    # Skip "Row N" patterns (table row labels)
    if re.match(r'^row\s+\d+$', text_stripped.lower()):
        return False
    
    # Skip if it looks like a rating scale anchor (just a number in parens)
    if re.match(r'^\(\d+\)$', text_stripped):
        return False
    
    return True
```