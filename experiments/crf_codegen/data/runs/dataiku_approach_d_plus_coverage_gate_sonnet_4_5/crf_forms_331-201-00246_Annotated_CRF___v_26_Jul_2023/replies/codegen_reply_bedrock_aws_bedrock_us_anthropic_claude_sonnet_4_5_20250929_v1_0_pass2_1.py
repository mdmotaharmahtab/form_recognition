STRATEGY:

The document is a clinical CRF with multiple form sections. Form titles appear as large (16.5pt), blue (#004c99) text positioned near the top of pages (y~150-170). Field labels are black 9-10.5pt text in the leftmost column of tabular layouts or as standalone questions. I will carry forward the most recent form title across continuation pages since forms span many pages. Red text (#ff0000) contains technical annotations (machine codes like [TYPE:...], [VISIBILITY:...], field codes in brackets) which I will ignore as field names but may use as structural landmarks. Answer options appear as enumerated choices (Yes/No, Positive/Negative/Not Done) positioned to the right of field labels in the same row—these are not separate fields. Table column headers (Sample, Result, Date of Collection, etc.) repeat at y~124 and are page furniture, not fields. "Row N" labels are structural markers, not field names. I will extract fields from all pages by detecting the tabular structure (left column = field label, right columns = data entry areas) and standalone question text, filtering out the red annotations, option values, and repeated headers. Pages without a visible title will inherit the last seen form title to ensure continuity across multi-page forms.

```python
# CRF extraction: form titles in large blue text, fields in black text tables.
# Red text = technical codes (ignore as field names). Carry titles forward across pages.

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
    for line in content_lines:
        if 120 <= line.y0 <= 160 and line.size >= 10.0:
            if header_y is None:
                header_y = line.y0
            if abs(line.y0 - header_y) < 20:
                headers.append(line.text.strip())
    
    # Process lines for field extraction
    i = 0
    while i < len(content_lines):
        line = content_lines[i]
        text = line.text.strip()
        
        # Skip headers, "Row N" markers, and answer options
        if text in headers or re.match(r'^Row \d+$', text):
            i += 1
            continue
        
        # Skip common answer options (structural position check)
        if text in ['Yes', 'No', 'Normal', 'Abnormal', 'Not Done', 'NA', 'Positive', 
                    'Negative', 'Collected', 'Not Collected', 'Scan', 'Not Applicable']:
            # Only skip if positioned in right columns (x > 400)
            if line.x0 > 400:
                i += 1
                continue
        
        # Field candidates: left-aligned (x < 250), reasonable size, not bold section markers
        if line.x0 < 250 and 8.5 <= line.size <= 12.0:
            # Check if it's a question or label
            if len(text) > 3 and not text.startswith('©') and not text.startswith('**'):
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
                if full_text and not is_junk(full_text):
                    fields.append(full_text)
                continue
        
        i += 1
    
    return fields

def is_junk(text: str) -> bool:
    # Filter out common non-field patterns
    if re.match(r'^[\d\s\-/:.]+$', text):  # Pure dates/numbers
        return True
    if text.startswith('Page ') or text.startswith('©'):
        return True
    if len(text) < 3:
        return True
    # Filter enumeration descriptions that are too generic
    if text in ['Read-only field', 'TYPE: text', 'TYPE: date', 'TYPE: enumeration']:
        return True
    return False
```