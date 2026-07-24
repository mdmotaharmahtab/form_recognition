```python
# This CRF has multiple layout families:
# - Family A: table of contents page with section links
# - Family B-F: data collection pages with form titles (large blue text ~14pt)
#   and field labels in black text (~7.8-9.2pt)
# Strategy: Extract form_name from large blue (#004c99) headers; field labels
# from black text that are questions/prompts, excluding red technical codes,
# answer options, table headers, and instructional text.

import re

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form title: large blue text, typically size ~14-15pt
        for line in lines:
            if line.non_black and line.size > 13 and '#004c99' in get_color(line):
                # Form title candidate
                text = line.text.strip()
                if text and not is_code(text):
                    current_form = text
                    break
        
        # Extract fields from this page
        fields = extract_fields_from_page(lines, current_form, page_num)
        records.extend(fields)
    
    return records

def get_color(line):
    # Approximation: non_black flag indicates colored text
    # In samples, form titles are blue #004c99
    return '#004c99' if line.non_black else 'black'

def is_code(text):
    # Technical codes in brackets like [LBGLYC], [TYPE:...], [CSS0401A]
    if text.startswith('[') and text.endswith(']'):
        return True
    if text.startswith('[') and not text.endswith(']'):
        return True
    return False

def is_table_header(line, lines, line_idx):
    # Table headers: "Sample", "Date of Collection", "Test", "Result", etc.
    # They appear in clusters on the same y-coordinate
    text = line.text.strip()
    if not text:
        return False
    
    # Common header words
    header_words = ['Sample', 'Date', 'Time', 'Collection', 'Test', 'Result', 
                    'Lifetime', 'Past', 'Month', 'Since Last Visit', 'Scan',
                    'Barcode', 'Number']
    
    if any(hw in text for hw in header_words):
        # Check if other lines at similar y-coordinate
        same_row = [l for l in lines if abs(l.y0 - line.y0) < 3 and l.x0 != line.x0]
        if len(same_row) >= 1:
            return True
    return False

def is_answer_option(text):
    # Answer options: Yes, No, Normal, Abnormal, Not Done, Positive, Negative, etc.
    options = ['Yes', 'No', 'Normal', 'Abnormal', 'Not Done', 'Not Applicable',
               'Positive', 'Negative', 'Scan']
    return text.strip() in options

def is_row_marker(text):
    # "Row 1", "Row 2", etc. are structural markers
    return re.match(r'^Row\s+\d+$', text.strip())

def is_instruction_text(line):
    # Instructions: smaller text, often describing how to fill forms
    text = line.text.strip()
    if text.startswith('Ask questions') or text.startswith('The following features'):
        return True
    if 'Version Number' in text:
        return True
    return False

def extract_fields_from_page(lines, form_name, page_num):
    records = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        text = line.text.strip()
        
        # Skip empty lines
        if not text:
            i += 1
            continue
        
        # Skip codes
        if is_code(text):
            i += 1
            continue
        
        # Skip table headers
        if is_table_header(line, lines, i):
            i += 1
            continue
        
        # Skip answer options (standalone)
        if is_answer_option(text):
            i += 1
            continue
        
        # Skip row markers
        if is_row_marker(text):
            i += 1
            continue
        
        # Skip instructions
        if is_instruction_text(line):
            i += 1
            continue
        
        # Skip red text (codes and annotations)
        if line.non_black and '#ff0000' in get_color_detailed(line):
            i += 1
            continue
        
        # Candidate field label: black text, reasonable size
        if not line.non_black and 7 <= line.size <= 10:
            # Check if it's a question/label
            if is_field_label(text, line):
                # Collect continuation lines
                field_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Stop if next line is code, answer option, or different structure
                    if is_code(next_text) or is_answer_option(next_text):
                        break
                    if next_line.non_black:
                        break
                    
                    # Check if continuation: similar x position, close y, not bold header
                    if (abs(next_line.x0 - line.x0) < 20 and 
                        next_line.y0 - lines[j-1].y0 < 15 and
                        next_line.size < 13):
                        
                        # Likely continuation
                        if next_text and not is_row_marker(next_text):
                            field_text += ' ' + next_text
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # Clean and add record
                field_text = clean_field_name(field_text)
                if field_text and len(field_text) > 3:
                    records.append({
                        'form_name': form_name,
                        'field_name': field_text,
                        'page': page_num
                    })
                
                i = j
                continue
        
        i += 1
    
    return records

def get_color_detailed(line):
    # In actual implementation, we'd track color info
    # For now, use heuristic based on non_black flag
    return '#ff0000' if line.non_black else 'black'

def is_field_label(text, line):
    # Field labels are typically questions or descriptive prompts
    # Not just single words, not all caps (unless question)
    
    # Too short
    if len(text) < 4:
        return False
    
    # Looks like system body part names used as row labels
    body_parts = ['Skin and Mucosae', 'Neurological', 'Extremities',
                  'Amphetamines', 'Barbiturates', 'Benzodiazepines',
                  'Cannabinoids', 'Cocaine', 'Methadone', 'Opiates',
                  'Phencyclidine', 'Propoxyphene', 'Standing', 'Sitting']
    if text in body_parts:
        return True
    
    # Questions end with '?'
    if text.endswith('?'):
        return True
    
    # Common field label patterns
    field_patterns = ['Was', 'Did', 'Has', 'Have', 'Are', 'Is', 'If', 'Date of',
                      'Time of', 'Reason', 'Manufacturer', 'Item', 'Lot', 
                      'Expiration', 'Subject endorses', 'General non-specific',
                      'Description', 'Frequency', 'Duration', 'Controllability',
                      'Deterrents', 'Reasons', 'Total number']
    
    if any(text.startswith(p) for p in field_patterns):
        return True
    
    # Avoid version numbers, page furniture
    if 'Version Number' in text or 'Page' in text[:10]:
        return False
    
    return False

def clean_field_name(text):
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text
```
