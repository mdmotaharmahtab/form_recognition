```python
# This CRF document contains multiple layout families with data-entry fields.
# The extraction strategy:
# 1. Identify form names from large colored headers (size ~14.4, color #004c99)
# 2. Extract field labels as black text questions/prompts (size ~7.8-9.2)
# 3. Filter out machine codes (text in brackets with red color #ff0000)
# 4. Filter out answer options (Yes/No choices, enumeration values)
# 5. Handle multi-line labels by joining continuation lines based on y-proximity

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form name - large colored header at top of page
        form_candidates = []
        for line in lines[:20]:  # Check top portion of page
            if line.size >= 13.0 and line.non_black and line.bold:
                # Likely a form title
                text = line.text.strip()
                if text and not is_machine_code(text):
                    form_candidates.append((line.y0, text))
        
        if form_candidates:
            # Use the topmost large colored bold text as form name
            form_candidates.sort(key=lambda x: x[0])
            current_form = form_candidates[0][1]
        
        # Extract field labels
        fields = extract_fields_from_page(lines)
        
        for field_name in fields:
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return results

def extract_fields_from_page(lines):
    """Extract field labels from a single page."""
    fields = []
    
    # Group lines by approximate y-position to handle multi-line labels
    y_groups = group_lines_by_y(lines)
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip machine codes (red text in brackets)
        if is_machine_code(line.text) or line.non_black:
            i += 1
            continue
        
        # Skip if text is too small or too large
        if line.size < 6.5 or line.size > 16.0:
            i += 1
            continue
        
        # Skip common page furniture
        if is_page_furniture(line.text):
            i += 1
            continue
        
        # Check if this looks like a field label
        text = line.text.strip()
        if is_field_label(line, text):
            # Collect multi-line labels
            full_label = text
            j = i + 1
            
            # Look ahead for continuation lines (close y-proximity, similar x, similar size)
            while j < len(lines):
                next_line = lines[j]
                
                # Stop if we hit machine code or a new distinct section
                if is_machine_code(next_line.text) or next_line.non_black:
                    break
                
                # Check if this is a continuation (close y, similar x-start, similar size)
                if (next_line.y0 - lines[j-1].y0 < 15 and 
                    abs(next_line.x0 - line.x0) < 30 and
                    abs(next_line.size - line.size) < 2.0 and
                    not is_page_furniture(next_line.text)):
                    
                    next_text = next_line.text.strip()
                    # Don't continue into answer options
                    if is_answer_option(next_text):
                        break
                    
                    full_label += " " + next_text
                    j += 1
                else:
                    break
            
            # Clean and validate the full label
            full_label = clean_label(full_label)
            if full_label and not is_answer_option(full_label):
                fields.append(full_label)
            
            i = j
        else:
            i += 1
    
    return fields

def group_lines_by_y(lines):
    """Group lines by approximate y-position."""
    groups = defaultdict(list)
    for line in lines:
        y_key = int(line.y0 / 5) * 5  # Group within 5 points
        groups[y_key].append(line)
    return groups

def is_machine_code(text):
    """Check if text is a machine code/annotation."""
    text = text.strip()
    # Red bracketed codes like [LBGLYC], [TYPE: ...], etc.
    if re.match(r'^\[.*\]$', text):
        return True
    return False

def is_page_furniture(text):
    """Check if text is page furniture (headers, footers, etc)."""
    text = text.strip().lower()
    
    # Empty or very short
    if len(text) < 2:
        return True
    
    # Page numbers, versions
    if re.match(r'^\d+$', text):
        return True
    if re.match(r'^(page|version|pack)\s+', text, re.I):
        return True
    
    # Table column headers that repeat
    if text in ['sample', 'date of collection', 'time of collection', 'scan', 'barcode number',
                'yes', 'no', 'lifetime', 'past 3 month', 'since last visit', 'suicidal ideation',
                'intensity of ideation', 'suicidal behavior']:
        return True
    
    # Row markers
    if re.match(r'^row\s+\d+$', text, re.I):
        return True
    
    return False

def is_field_label(line, text):
    """Determine if a line is likely a field label."""
    # Must have meaningful text
    if len(text) < 3:
        return False
    
    # Skip if it's just formatting markers
    if text.lower() in ['b', 'row', 'if yes', 'if no']:
        return False
    
    # Field labels are typically questions or statements
    # Usually size 7.8-9.2, black text
    if line.size < 6.5 or line.size > 12.0:
        return False
    
    # Questions often end with ?
    if text.endswith('?'):
        return True
    
    # Field labels often contain certain words/patterns
    field_patterns = [
        r'\b(was|were|has|have|did|does|is|are)\b',
        r'\b(date|time|sample|collected|administered|completion)\b',
        r'\b(subject|person|patient|participant)\b',
        r'\b(describe|specify|explain|reason|total|number)\b',
    ]
    
    for pattern in field_patterns:
        if re.search(pattern, text, re.I):
            return True
    
    # Labels that start with capital letter and are sentence-like
    if text[0].isupper() and len(text.split()) > 2:
        return True
    
    return False

def is_answer_option(text):
    """Check if text is an answer option rather than a field label."""
    text = text.strip()
    
    # Common standalone answer options
    standalone_options = ['yes', 'no', 'not applicable', 'unknown', 'scan', 'na', 'n/a']
    if text.lower() in standalone_options:
        return True
    
    # Enumerated options like (1), (2), etc.
    if re.match(r'^\(\d+\)', text):
        return True
    
    # Short option-like text
    if len(text.split()) <= 2 and text.lower() in ['yes', 'no', 'maybe', 'unknown', 'not done']:
        return True
    
    return False

def clean_label(text):
    """Clean and normalize field label text."""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove trailing punctuation that got included
    text = re.sub(r'\s*[,;:]+$', '', text)
    
    return text
```
