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

def is_dropdown_value(line, lines, i):
    """Check if this is a dropdown value (not a field label)."""
    text = line.text.strip()
    
    # Check if followed by machine code (field labels are, dropdown values aren't)
    if i + 1 < len(lines):
        next_text = lines[i+1].text.strip()
        if is_machine_code(next_text):
            return False  # This is a field label
    
    # Check if it's a single word/short phrase that looks like a value
    # Common dropdown values: test names, medication names, etc.
    if len(text.split()) <= 3 and not text.endswith('?') and not text.endswith(':'):
        # Check if there are similar items nearby (suggesting a list of values)
        similar_count = 0
        for j in range(max(0, i-3), min(len(lines), i+4)):
            if j != i:
                other_text = lines[j].text.strip()
                # Similar styling and position
                if (abs(lines[j].x0 - line.x0) < 20 and 
                    abs(lines[j].size - line.size) < 1 and
                    len(other_text.split()) <= 3):
                    similar_count += 1
        
        # If there are multiple similar items, this is likely a dropdown list
        if similar_count >= 2:
            return True
    
    return False

def is_long_prose_text(line, lines, i):
    """Check if this is long prose text (like inclusion/exclusion criteria)."""
    text = line.text.strip()
    
    # Long prose is characterized by:
    # 1. Multiple sentences or very long text
    # 2. Often starts with lowercase (continuation)
    # 3. Contains multiple clauses
    
    # Check if this is part of a long paragraph
    if len(text) > 100:
        # Very long single line - likely prose
        return True
    
    # Check if surrounded by similar long lines (paragraph)
    long_neighbors = 0
    for j in range(max(0, i-2), min(len(lines), i+3)):
        if j != i:
            other_text = lines[j].text.strip()
            if len(other_text) > 80:
                long_neighbors += 1
    
    if long_neighbors >= 2 and len(text) > 60:
        return True
    
    # Check if starts with lowercase (continuation of prose)
    if text and text[0].islower() and len(text) > 50:
        return True
    
    return False

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
        
        # Skip dropdown values
        if is_dropdown_value(line, lines, i):
            i += 1
            continue
        
        # Skip long prose text
        if is_long_prose_text(line, lines, i):
            i += 1
            continue
        
        # Check if this is a field label candidate
        if is_field_label_candidate(line, lines, i):
            # Extract the full field text (may span multiple lines)
            field_text, next_i = extract_full_field_text(lines, i)
            
            if field_text and len(field_text) > 2:
                # Additional validation: skip if it looks like a value or prose
                if not looks_like_dropdown_value(field_text) and not looks_like_prose(field_text):
                    results.append({
                        'form_name': form_name,
                        'field_name': field_text,
                        'page': page_num
                    })
            
            i = next_i
        else:
            i += 1
    
    return results

def looks_like_dropdown_value(text):
    """Check if extracted text looks like a dropdown value rather than a field label."""
    # Dropdown values are typically:
    # - Short (1-3 words)
    # - Don't end with question marks or colons
    # - Are specific values like test names, drug names, etc.
    
    words = text.split()
    
    # Specific patterns that indicate dropdown values
    # "Uric acid" is a test name, not a field label
    if len(words) <= 2 and not text.endswith('?') and not text.endswith(':'):
        # Check if it's a simple noun phrase without field-like keywords
        field_keywords = ['clinically', 'abnormal', 'comment', 'were', 'are', 'any', 
                         'additional', 'result', 'investigator', 'significant', 'has',
                         'have', 'describe', 'if', 'yes', 'no', 'diagnosis', 'determined',
                         'criteria', 'considered', 'judgment', 'ability', 'provide']
        
        if not any(keyword in text.lower() for keyword in field_keywords):
            # Check if all words are capitalized (typical of test/drug names)
            if all(word[0].isupper() for word in words if word and word[0].isalpha()):
                return True
    
    # Check for specific patterns like "c) Vital signs" which is part of a list, not a field
    if re.match(r'^[a-z]\)\s+', text):
        # This is a list item marker, likely part of prose
        return True
    
    # Check for fragments that look like partial sentences
    # "dose of IMP." or "hypotension which is defined as a decrease of"
    if text.endswith(' of') or text.endswith(' as') or text.endswith(' a'):
        # Incomplete sentence fragment
        return True
    
    return False

def looks_like_prose(text):
    """Check if extracted text looks like prose rather than a field label."""
    # Prose is characterized by:
    # - Very long text (> 150 chars)
    # - Multiple clauses with commas
    # - Contains phrases like "including", "such as", "defined as"
    
    if len(text) > 150:
        return True
    
    # Count commas and semicolons (prose has many)
    punctuation_count = text.count(',') + text.count(';')
    if punctuation_count >= 3 and len(text) > 100:
        return True
    
    # Check for prose indicators
    prose_indicators = ['including', 'such as', 'defined as', 'this includes', 
                       'for example', 'e.g.', 'i.e.', 'which is']
    if any(indicator in text.lower() for indicator in prose_indicators) and len(text) > 80:
        return True
    
    return False

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
    # Match patterns like "\1.\", "\2.\", "1.", "2.", etc.
    if re.match(r'^\\?\d+\\.', text):
        # Numbered items like "\23." or "1."
        if 6 <= line.size <= 10:
            # Check if this is a substantial field (not just a list marker)
            # Real fields have more content after the number
            content_after_number = re.sub(r'^\\?\d+\\.?\s*', '', text)
            if len(content_after_number) > 10:
                return True
    
    # 3. Field labels followed by machine codes
    if i + 1 < len(lines):
        next_text = lines[i+1].text.strip()
        if is_machine_code(next_text):
            # This is likely a field label
            if 6 <= line.size <= 11 and len(text) > 3:
                # Additional check: not a simple test name
                if not (len(text.split()) <= 2 and text[0].isupper() and 
                       not any(kw in text.lower() for kw in ['clinically', 'abnormal', 'comment', 'result'])):
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
    
    # 6. Patterns for suicide assessment questions
    if text.startswith('Has there been') or text.startswith('Have you'):
        if text.endswith('?') and len(text) > 20:
            return True
    
    # 7. "If Yes, describe" pattern
    if text == 'If Yes, describe':
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
                # Don't continue if next line looks like a new numbered item
                if not re.match(r'^\\?\d+\\.', next_text):
                    text_parts.append(next_text)
                    current_line = next_line
                    i += 1
                else:
                    break
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