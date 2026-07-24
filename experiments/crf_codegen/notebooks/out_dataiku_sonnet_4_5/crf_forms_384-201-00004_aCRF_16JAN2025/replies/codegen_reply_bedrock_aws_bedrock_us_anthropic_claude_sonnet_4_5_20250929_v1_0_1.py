```python
"""
This CRF document has several layout patterns:
1. Title/cover pages (pages 1-2) with study metadata - no fields to extract
2. Main form pages (pages 37+, 71+, 86+) with field labels on the left (~x=46.5, size 7.5)
   and technical annotations on the right (~x=453.5, smaller size 5.6)
3. Code list pages (pages 153+, 171+) showing lookup tables - no fields to extract

Strategy: Extract fields from pages with left-aligned labels (x ~46.5, size 7.5).
Form names appear as colored headers (size 10.5, color #31708f or white background at y~34.8).
Skip technical annotations (x>400), code lists, and answer options (radio buttons "O").
"""

import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form name headers
        for line in lines:
            # Form name in white background header at top (y < 60)
            if line.y0 < 60 and line.size >= 11 and line.size <= 13:
                # Skip title page and generic headers
                if not re.search(r'^\d{3}-\d{3}-\d{5}$', line.text) and \
                   line.text not in ['Study Events', 'CDISC Legend']:
                    current_form = line.text.strip()
            
            # Form name in colored section headers (size ~10.5, color #31708f)
            elif line.size >= 10 and line.size <= 11 and line.non_black and \
                 line.x0 < 100 and line.y0 > 60:
                # Skip table headers and code list titles
                if not re.search(r'^(Coded|Decode|Name|Forms|Type|Category)$', line.text):
                    current_form = line.text.strip()
        
        # Extract field labels
        for line in lines:
            # Field labels: left-aligned (x ~40-50), size ~7.5, not in annotation area
            if 40 <= line.x0 <= 55 and 7 <= line.size <= 8.5 and line.y0 > 60:
                text = line.text.strip()
                
                # Skip empty, technical codes, and non-field text
                if not text or len(text) < 3:
                    continue
                
                # Skip SAS field names in brackets
                if re.match(r'^\[SAS Field Name:', text):
                    continue
                
                # Skip bare field codes in brackets
                if re.match(r'^\[[A-Z0-9_]+\]$', text):
                    continue
                
                # Skip answer options (radio buttons)
                if re.match(r'^O\s+', text):
                    continue
                
                # Skip role/alias metadata
                if re.match(r'^(Aliases:|Role Restriction:|Description:)', text):
                    continue
                
                # Skip page numbers and URLs
                if re.search(r'^\d+\s+of\s+\d+$|https?://', text):
                    continue
                
                # Skip code list references
                if re.search(r'^Code List:', text):
                    continue
                
                # Clean up: remove trailing field codes in brackets
                text = re.sub(r'\s*\[[A-Z0-9_]+\]\s*$', '', text)
                
                # Must be a question or label (contains letters and reasonable length)
                if re.search(r'[a-zA-Z]', text) and len(text) >= 5:
                    # Skip if it looks like a date format or pure technical string
                    if not re.match(r'^[\[\]_\-|dMy]+$', text):
                        results.append({
                            "form_name": current_form,
                            "field_name": text,
                            "page": page_num
                        })
    
    return results
```