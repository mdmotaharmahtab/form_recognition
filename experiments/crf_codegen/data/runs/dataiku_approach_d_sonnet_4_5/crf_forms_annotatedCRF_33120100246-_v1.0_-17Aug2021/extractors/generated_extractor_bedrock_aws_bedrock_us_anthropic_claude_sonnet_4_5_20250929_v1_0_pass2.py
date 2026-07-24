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
    if len(text.split()) <= 3 and not text.endswith('?') and not text.endswith(':'):
        # Check if there are similar items nearby (suggesting a list of values)
        similar_count = 0
        for j in range(max(0, i-3), min(len(lines), i+4)):
            if j != i:
                other_text = lines[j].text.strip()
                if (abs(lines[j].x0 - line.x0) < 20 and 
                    abs(lines[j].size - line.size) < 1 and
                    len(other_text.split()) <= 3):
                    similar_count += 1
        
        if similar_count >= 2:
            return True
    
    return False

def is_prose_fragment(text):
    """Check if text is a prose fragment (incomplete sentence from middle of paragraph)."""
    # Prose fragments are characterized by:
    # 1. Starting with lowercase
    # 2. Ending with prepositions or conjunctions
    # 3. Being part of a longer sentence
    
    if not text:
        return False
    
    # Starts with lowercase (continuation)
    if text[0].islower():
        return True
    
    # Ends with preposition/conjunction/article (incomplete)
    ending_words = text.split()[-1:] if text.split() else []
    if ending_words:
        last_word = ending_words[0].lower().rstrip('.,;:')
        incomplete_endings = {'of', 'as', 'a', 'an', 'the', 'and', 'or', 'but', 'in', 
                             'on', 'at', 'to', 'for', 'with', 'by', 'from', 'which', 'that'}
        if last_word in incomplete_endings:
            return True
    
    # Very short fragments that don't look like complete fields
    if len(text) < 20 and not text.endswith('?') and not text.endswith(':'):
        # Check if it contains field-like keywords
        field_keywords = ['describe', 'comment', 'result', 'date', 'time', 'specify']
        if not any(kw in text.lower() for kw in field_keywords):
            # Likely a fragment
            if text[0].isupper() and len(text.split()) <= 4:
                # Could be "Overdose:" or similar - check if ends with colon
                if not text.endswith(':'):
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
        
        # Check if this is a field label candidate
        if is_field_label_candidate(line, lines, i):
            # Extract the full field text (may span multiple lines)
            field_text, next_i = extract_full_field_text(lines, i)
            
            if field_text and len(field_text) > 2:
                # Additional validation: skip if it's a prose fragment
                if not is_prose_fragment(field_text):
                    # Skip if it looks like a dropdown value
                    if not looks_like_dropdown_value(field_text):
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
    words = text.split()
    
    # Specific patterns that indicate dropdown values
    if len(words) <= 2 and not text.endswith('?') and not text.endswith(':'):
        field_keywords = ['clinically', 'abnormal', 'comment', 'were', 'are', 'any', 
                         'additional', 'result', 'investigator', 'significant', 'has',
                         'have', 'describe', 'if', 'yes', 'no', 'diagnosis', 'determined',
                         'criteria', 'considered', 'judgment', 'ability', 'provide']
        
        if not any(keyword in text.lower() for keyword in field_keywords):
            if all(word[0].isupper() for word in words if word and word[0].isalpha()):
                return True
    
    # Check for specific patterns like "c) Vital signs" which is part of a list, not a field
    if re.match(r'^[a-z]\)\s+', text):
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
        if line.x0 > 400:
            return False
    
    # Field labels are typically:
    # 1. Questions ending with ?
    if text.endswith('?'):
        if 6 <= line.size <= 11:
            return True
    
    # 2. Numbered criteria fields like "\1.\", "\2.\", etc.
    # These are FIELDS, not prose, when they're structured inclusion/exclusion criteria
    if re.match(r'^\\?\d+\\.\\?\s*', text):
        # Extract content after the number
        content = re.sub(r'^\\?\d+\\.\\?\s*', '', text)
        
        # This is a field if:
        # - It's substantial (not just a list marker)
        # - It's formatted as a criterion (starts with capital, ends with punctuation)
        if len(content) > 15:
            # Check if it looks like a complete criterion
            # Criteria typically start with capital and contain complete thoughts
            if content[0].isupper():
                # Not a prose fragment (doesn't start with lowercase or end with preposition)
                if not is_prose_fragment(content):
                    return True
    
    # 3. Field labels followed by machine codes
    if i + 1 < len(lines):
        next_text = lines[i+1].text.strip()
        if is_machine_code(next_text):
            if 6 <= line.size <= 11 and len(text) > 3:
                if not (len(text.split()) <= 2 and text[0].isupper() and 
                       not any(kw in text.lower() for kw in ['clinically', 'abnormal', 'comment', 'result'])):
                    return True
    
    # 4. Bold text that looks like a label
    if line.bold and 6 <= line.size <= 10:
        if not is_row_label(text) and len(text) > 5:
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
    
    # 7. "If Yes, describe" pattern - this is a field!
    if text == 'If Yes, describe':
        return True
    
    # 8. Fields that start with "Ability to" or "Diagnosis of" (inclusion criteria)
    if text.startswith('Ability to') or text.startswith('Diagnosis of'):
        if len(text) > 20:
            return True
    
    # 9. Fields starting with common criterion patterns
    criterion_starts = ['Male or female', 'Body mass index', 'In good health', 
                       'Females who', 'Heterosexually active', 'Subjects with']
    if any(text.startswith(start) for start in criterion_starts):
        if len(text) > 20:
            return True
    
    return False

def extract_full_field_text(lines, start_i):
    """Extract full field text that may span multiple lines."""
    text_parts = [lines[start_i].text.strip()]
    current_line = lines[start_i]
    i = start_i + 1
    
    # For numbered criteria, we need to collect until we hit the next numbered item
    # or a clear break
    is_numbered_criterion = bool(re.match(r'^\\?\d+\\.\\?\s*', text_parts[0]))
    
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
        
        # Stop at next numbered criterion
        if is_numbered_criterion and re.match(r'^\\?\d+\\.\\?\s*', next_text):
            break
        
        # Check if this is a continuation line
        y_diff = next_line.y0 - current_line.y0
        
        # If too far apart vertically, stop
        if y_diff > 25:
            break
        
        # If it's a new section (much larger text), stop
        if next_line.size > current_line.size + 2:
            break
        
        # For numbered criteria, be more aggressive about collecting continuation
        if is_numbered_criterion:
            # Continue if it's on the left side and similar size
            if next_line.x0 < 400 and abs(next_line.size - current_line.size) < 2:
                # Don't continue if it's a new question
                if not (next_text.endswith('?') and y_diff > 15):
                    text_parts.append(next_text)
                    current_line = next_line
                    i += 1
                else:
                    break
            else:
                break
        else:
            # Original logic for non-numbered fields
            if next_line.x0 < 300 and abs(next_line.size - current_line.size) < 2:
                if not (next_text.endswith('?') and y_diff > 15):
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
