import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title: large blue text near top of page
        for line in lines:
            if line.size >= 15.0 and line.non_black and line.y0 < 300:
                # Likely a form/section title
                text = line.text.strip()
                if text and not text.startswith('[') and text not in ['CHANGE HISTORY', 'SCHEDULE OF ASSESSMENT', 'PAGES']:
                    current_form = text
                    break
        
        # Extract fields from tabular layouts and standalone questions
        fields = extract_fields_from_page(lines, page_num)
        
        for field_name in fields:
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return results

def extract_fields_from_page(lines: List, page_num: int) -> List[str]:
    fields = []
    
    # Filter out red annotation lines and page numbers
    content_lines = []
    for line in lines:
        text = line.text.strip()
        # Skip red technical annotations, page numbers, and empty lines
        if (line.non_black and '[' in text) or text.startswith('Page ') or not text:
            continue
        # Skip pure bracket content even if black
        if re.match(r'^\[.*\]$', text):
            continue
        content_lines.append(line)
    
    # Identify column headers (repeated at y~124)
    header_y = None
    headers = []
    header_lines = []
    for line in content_lines:
        if 120 <= line.y0 <= 160 and line.size >= 10.0:
            if header_y is None:
                header_y = line.y0
            if abs(line.y0 - header_y) < 20:
                headers.append(line.text.strip())
                header_lines.append(line)
    
    # Check for simple header-only table (cluster 2 pattern)
    # If we have 2+ headers at y~124 and very few other content lines, headers ARE the fields
    non_header_content = [l for l in content_lines if l not in header_lines]
    if len(headers) >= 2 and len(non_header_content) <= 2:
        # This is a header-only table where headers are the field names
        for header in headers:
            if header and not is_junk_structural(header, None):
                fields.append(header)
        return fields
    
    # Detect PK table patterns (multiple drug names + "PK" at similar positions)
    pk_pattern_lines = []
    for line in content_lines:
        text = line.text.strip()
        if re.search(r'\bPK$', text) and line.x0 > 200:
            pk_pattern_lines.append(line)
    
    # If we have multiple PK entries at similar y-coordinates, they're table elements
    is_pk_table = len(pk_pattern_lines) >= 2
    
    # Process lines for field extraction
    i = 0
    while i < len(content_lines):
        line = content_lines[i]
        text = line.text.strip()
        
        # Skip headers and "Row N" markers
        if text in headers or re.match(r'^Row \d+$', text):
            i += 1
            continue
        
        # Skip parenthetical type annotations like "(values: ...)" or fragments
        if is_parenthetical_annotation(text):
            i += 1
            continue
        
        # Skip PK table entries (drug name + PK pattern in tabular context)
        if is_pk_table and re.search(r'\bPK$', text) and line.x0 > 200:
            i += 1
            continue
        
        # Skip short right-aligned answer options (but not left-aligned short labels)
        if line.x0 > 300 and len(text) < 15 and not text.endswith('?'):
            # Likely "Abnormal, Not" or similar checkbox option
            i += 1
            continue
        
        # Skip right-column answer options (structural position check)
        if line.x0 > 400 and len(text) < 20 and not text.endswith('?'):
            # Likely an answer option in right columns
            i += 1
            continue
        
        # Field candidates: left-aligned (x < 250), reasonable size, not bold section markers
        # Relaxed minimum length to 2 characters for short valid labels like "PGx"
        if line.x0 < 250 and 8.5 <= line.size <= 12.0:
            # Check if it's a question or label
            if len(text) >= 2 and not text.startswith('©') and not text.startswith('**'):
                # Join continuation lines (same x position, close y)
                full_text = text
                j = i + 1
                while j < len(content_lines):
                    next_line = content_lines[j]
                    # Continuation: similar x, close y, not a new field
                    if (abs(next_line.x0 - line.x0) < 20 and 
                        next_line.y0 - content_lines[j-1].y0 < 20 and
                        next_line.x0 < 250):
                        full_text += " " + next_line.text.strip()
                        j += 1
                    else:
                        break
                i = j
                
                # Clean and validate
                full_text = re.sub(r'\s+', ' ', full_text).strip()
                if full_text and not is_junk_structural(full_text, line):
                    fields.append(full_text)
                continue
        
        i += 1
    
    return fields

def is_parenthetical_annotation(text: str) -> bool:
    """Detect parenthetical type annotations and broken fragments."""
    # Match patterns like "(values: ...)" or text starting with "("
    if re.match(r'^\(values:', text, re.IGNORECASE):
        return True
    # Fragments that end with comma or look incomplete
    if text.endswith(',') or text.endswith(';'):
        return True
    # Closing parenthesis fragments
    if text.endswith(')]') or text.endswith(')'):
        return True
    return False

def is_junk_structural(text: str, line) -> bool:
    """Filter out common non-field patterns based on structure, not literal matching."""
    # Pure dates/numbers
    if re.match(r'^[\d\s\-/:.]+$', text):
        return True
    # Page markers and copyright
    if text.startswith('Page ') or text.startswith('©'):
        return True
    # Very short strings (but allow 2-3 chars for valid short labels)
    if len(text) < 2:
        return True
    # Parenthetical annotations
    if is_parenthetical_annotation(text):
        return True
    # Generic type descriptions (structural pattern)
    if re.match(r'^TYPE:\s*\w+$', text, re.IGNORECASE):
        return True
    if text == 'Read-only field':
        return True
    return False
