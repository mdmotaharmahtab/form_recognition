# CRF extraction: multiple families with form titles in large blue text,
# fields in black, and technical codes in red. Carry form context forward.

import re
from typing import List, Dict, Tuple

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title: large blue text near top (size >= 15, color #004c99 or #2477cc)
        for line in lines:
            if line.y0 < 250 and line.size >= 15 and line.non_black:
                # Check if it's a title color (blue shades)
                text = line.text.strip()
                if text and not re.match(r'^(Page \d+|CHANGE HISTORY|SCHEDULE|PAGES|\d+\.\d+\.).*', text):
                    # Likely a form title
                    current_form = text
                    break
        
        # Extract fields from the page
        fields = extract_fields_from_page(lines, page_num)
        
        for field_name in fields:
            records.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return records

def extract_fields_from_page(lines: List, page_num: int) -> List[str]:
    fields = []
    
    # Skip page numbers and footers
    lines = [ln for ln in lines if ln.y0 < 780 and not re.match(r'^Page \d+ of \d+$', ln.text.strip())]
    
    # Check for sparse table layout (few lines, column headers near top)
    if len(lines) < 10:
        fields.extend(extract_table_headers(lines))
        if fields:
            return fields
    
    i = 0
    while i < len(lines):
        line = lines[i]
        text = line.text.strip()
        
        # Skip empty, machine codes, type annotations, disclaimers
        if not text or text.startswith('[') or text.startswith('(') and text.endswith(')'):
            i += 1
            continue
        
        # Skip headers, column labels, table structure markers
        if re.match(r'^(Visit Num|Visit Label|Page Num|Page Label|Dynamic\?|Description|Sample|Timepoint|Sample Status|Time of|Barcode|Backup|Collection|Number|Row \d+|Schedule_\w+|Log Pages|Unscheduled|Definitions of behavioral|For reprints|© \d{4}).*', text, re.IGNORECASE):
            i += 1
            continue
        
        # Skip page chrome and document structure
        if re.match(r'^(Pack Version|Paul Mostioru|\d{1,2}[A-Za-z]+\d{4}|Annotated CRF|COLUMBIA-SUICIDE|RATING SCALE|\(C-SSRS\)|Baseline/Screening|Version \d+|Posner, K\.|Disclaimer:|This scale is intended|the Columbia-Suicide).*', text):
            i += 1
            continue
        
        # Check if this is a field label (black text, reasonable size, not red/technical)
        if not line.non_black or (line.non_black and line.size >= 9 and not is_red(line)):
            # Check if it's a question or label
            if is_field_label(text, line):
                # Collect continuation lines
                field_text = text
                j = i + 1
                while j < len(lines) and is_continuation(lines[j], line):
                    field_text += " " + lines[j].text.strip()
                    j += 1
                
                # Clean and validate
                field_text = clean_field_name(field_text)
                if field_text and is_valid_field(field_text):
                    fields.append(field_text)
                
                i = j
                continue
        
        i += 1
    
    return fields

def extract_table_headers(lines: List) -> List[str]:
    """Extract column headers from sparse table layouts"""
    headers = []
    
    # Look for black text in upper portion (y0 < 200) that looks like column headers
    for line in lines:
        text = line.text.strip()
        
        # Skip empty, red annotations, page numbers
        if not text:
            continue
        if is_red(line):
            continue
        if re.match(r'^Page \d+ of \d+$', text):
            continue
        if text.startswith('(') and text.endswith(')'):
            continue
        if text.startswith('['):
            continue
            
        # Look for column header patterns in upper area
        if line.y0 < 200 and not line.non_black:
            # Common column header patterns
            if re.match(r'^(Intensity of Ideation|Since Last Visit|Lifetime|Past 3 Month|Past Month)$', text, re.IGNORECASE):
                headers.append(text)
            # General multi-word headers
            elif len(text.split()) >= 2 and len(text) > 5 and text[0].isupper():
                # Avoid common non-field text
                if not re.match(r'^(Page \d+|Visit Num|Visit Label).*', text):
                    headers.append(text)
    
    return headers

def is_red(line) -> bool:
    # Red text is typically #ff0000 or similar
    return line.non_black and line.size < 10

def is_field_label(text: str, line) -> bool:
    # Field labels are typically questions or descriptive text
    # Not just numbers, dates, or single words
    if re.match(r'^\d+$', text):
        return False
    if re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', text):
        return False
    if len(text) < 3:
        return False
    
    # Check for question patterns
    if '?' in text or text.endswith(':'):
        return True
    
    # Multi-word labels
    if len(text.split()) >= 2:
        return True
    
    # Single meaningful words with capital
    if text[0].isupper() and len(text) > 5:
        return True
    
    return False

def is_continuation(next_line, prev_line) -> bool:
    # Continuation if close in y, similar x, not a new section
    if abs(next_line.x0 - prev_line.x0) > 50:
        return False
    if next_line.y0 - prev_line.y1 > 20:
        return False
    if next_line.text.strip().startswith('['):
        return False
    if next_line.bold and not prev_line.bold:
        return False
    return True

def clean_field_name(text: str) -> str:
    # Remove technical annotations
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def is_valid_field(text: str) -> bool:
    # Filter out non-field text
    if not text:
        return False
    
    # Skip pure numbers, codes
    if re.match(r'^[\d\s\-\:\.]+$', text):
        return False
    
    # Skip single letters or very short
    if len(text) < 3:
        return False
    
    # Skip common non-fields
    skip_patterns = [
        r'^(Yes|No|Unknown|N/A|NA|Collected|Not Collected|Scan|Supine|Standing)$',
        r'^\(\d+\)',
        r'^Row \d+$',
        r'^Page \d+',
    ]
    for pattern in skip_patterns:
        if re.match(pattern, text, re.IGNORECASE):
            return False
    
    return True
