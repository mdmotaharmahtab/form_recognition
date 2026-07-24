```python
# LAYOUT OBSERVATIONS:
# - Family A: Table of contents with section numbers and hyperlinked titles
# - Families B-D: Schedule tables with Visit/Page numbers and labels in columns
# - Family E: Single-field forms with questions, answer options (Yes/No/Not Applicable), and sample collection tables
# - Family F: Tobacco/substance use tables with product rows and usage status/frequency/dose fields
# - Family G: Drug screen tables with substance rows and Positive/Negative/Not Done options
# - Families H-L: C-SSRS forms with numbered questions about suicidal ideation/behavior
# - Family M: Repeatable follow-up contact forms with multiple fields
# - Family N: ICF verification and signature fields
# - All pages have machine codes in red [BRACKETS] - these are technical annotations, NOT field names
# - Form titles appear as large blue headings (sz ~14-15, color #004c99 or #1d60a4)
# - Questions/labels are black text (sz 7.8-9.2)
# - Answer options (Yes/No, enumeration values) are NOT separate fields

import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form title: large blue text, typically sz >= 13
        form_title = None
        for line in lines:
            # Look for prominent blue headings (form titles)
            if line.size >= 13.0 and line.non_black and not line.text.startswith('['):
                # Skip table of contents patterns
                if not re.match(r'^\d+(\.\d+)?\.?\s', line.text):
                    form_title = line.text.strip()
                    break
        
        # Update current form context
        if form_title:
            current_form = form_title
        
        # Skip table of contents pages (Family A)
        if any('CHANGE HISTORY' in l.text or 'SCHEDULE OF ASSESSMENT' in l.text for l in lines):
            continue
        
        # Skip schedule tables (Families B-D) - these are reference tables, not data entry
        if any('Schedule_' in l.text for l in lines):
            continue
        
        # Skip C-SSRS cover page (Family H) - just title and disclaimers
        if any('COLUMBIA-SUICIDE SEVERITY' in l.text for l in lines):
            continue
        
        # Process field-bearing pages
        fields = extract_fields(lines, current_form)
        for field_name in fields:
            records.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return records

def extract_fields(lines, form_name):
    fields = []
    i = 0
    
    # Filter to black text only (questions/labels), excluding red codes
    question_lines = []
    for line in lines:
        text = line.text.strip()
        # Skip machine codes, type annotations, visibility markers
        if text.startswith('[') or 'TYPE:' in text or 'VISIBILITY:' in text:
            continue
        # Skip answer options (these are content, not fields)
        if is_answer_option(line, lines):
            continue
        # Skip table headers and structural labels
        if is_table_header(text):
            continue
        # Skip page furniture
        if line.size < 6.0 or is_page_furniture(text):
            continue
        
        question_lines.append(line)
    
    # Group lines into questions/fields
    i = 0
    while i < len(question_lines):
        line = question_lines[i]
        text = line.text.strip()
        
        # Skip empty or very short fragments
        if len(text) < 3:
            i += 1
            continue
        
        # Skip bold structural labels like "Row N"
        if line.bold and re.match(r'^Row\s+\d+$', text):
            i += 1
            continue
        
        # Check if this is a field label/question
        if is_field_label(text):
            # Collect continuation lines (wrapping)
            full_text = text
            j = i + 1
            while j < len(question_lines):
                next_line = question_lines[j]
                next_text = next_line.text.strip()
                
                # Stop if we hit another clear field label
                if is_field_label(next_text) and not is_continuation(next_text):
                    break
                
                # Stop if next line is significantly different in style
                if abs(next_line.y0 - line.y0) > 30 and abs(next_line.x0 - line.x0) > 20:
                    break
                
                # Check if this is a continuation (same column, nearby Y)
                if abs(next_line.x0 - line.x0) < 20 and next_line.y0 - line.y0 < 20:
                    full_text += " " + next_text
                    j += 1
                else:
                    break
            
            # Clean and add field
            field_name = clean_field_name(full_text)
            if field_name and len(field_name) > 5:  # Meaningful length
                fields.append(field_name)
            
            i = j
        else:
            i += 1
    
    return deduplicate_fields(fields)

def is_answer_option(line, all_lines):
    """Check if line is an answer option (Yes/No, ratings, etc.)"""
    text = line.text.strip()
    
    # Common answer patterns
    if text in ['Yes', 'No', 'Not Applicable', 'Not Done', 'Positive', 'Negative']:
        return True
    if text in ['Current', 'Former', 'Never', 'Scan']:
        return True
    if text in ['Per Day', 'Per Week', 'Pack', 'Cigar', 'Cartridge', 'None']:
        return True
    if re.match(r'^\(\d+\)', text):  # Numbered options like (1), (2)
        return True
    if text.startswith('(') and text.endswith(')') and len(text) > 30:  # Long enumeration descriptions
        return True
    
    return False

def is_table_header(text):
    """Check if text is a table header (structural, not a field)"""
    headers = [
        'Visit', 'Visit Label', 'Visit Number', 'Page', 'Page Label', 'Page Number',
        'Dynamic?', 'Description of Dynamic', 'Sample', 'Date of Collection',
        'Time of Collection', 'Scan', 'Barcode Number', 'Actual Attempts',
        'Most Lethal Attempt', 'Type of Contact', 'Method of Contact',
        'Date of Contact/Attempt', 'Were you able to contact the Subject?'
    ]
    return text in headers or text.endswith('Label')

def is_page_furniture(text):
    """Check if text is page furniture (headers, footers, etc.)"""
    # Version numbers, dates, page references
    if re.match(r'^Version\s+\d', text):
        return True
    if re.match(r'^\d{1,2}[A-Z][a-z]{2}\d{4}$', text):  # Date like 17Aug2021
        return True
    if re.match(r'^Pack\s+Version$', text):
        return True
    if 'Disclaimer:' in text or '© 20' in text:
        return True
    
    return False

def is_field_label(text):
    """Check if text looks like a field label/question"""
    # Questions typically end with ?
    if text.endswith('?'):
        return True
    
    # Field labels with colons
    if ':' in text and len(text) < 100:
        # But not if it's just structural like "Row 1:"
        if not re.match(r'^Row\s+\d+:?$', text):
            return True
    
    # Longer descriptive text (likely a field label)
    if len(text) > 15 and not text.isupper():
        # Has some lowercase and reasonable length
        if any(c.islower() for c in text):
            return True
    
    return False

def is_continuation(text):
    """Check if text is likely a continuation of previous line"""
    # Starts with lowercase (mid-sentence)
    if text and text[0].islower():
        return True
    # Very short fragments
    if len(text) < 20 and not text.endswith('?'):
        return True
    return False

def clean_field_name(text):
    """Clean and normalize field name"""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove trailing punctuation except ?
    if text.endswith(':'):
        text = text[:-1].strip()
    
    # Remove numbered prefixes like "Row 1"
    text = re.sub(r'^Row\s+\d+\s*', '', text)
    
    # Remove question numbering like "1.", "2."
    text = re.sub(r'^\d+\.\s*', '', text)
    
    return text

def deduplicate_fields(fields):
    """Remove exact duplicates while preserving order"""
    seen = set()
    result = []
    for field in fields:
        if field not in seen:
            seen.add(field)
            result.append(field)
    return result
```
