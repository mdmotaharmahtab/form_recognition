```python
def extract(pages):
    """
    Extraction strategy for clinical CRF document:
    - Family A: Title page (no fields)
    - Family B: Table of contents (no fields)
    - Family C: Table-based forms with column headers and data entry rows
    - Family D: Two-column forms with test/question labels and result columns
    - Family E: Simple table headers only (minimal content)
    
    Form names are extracted from large blue headers (size ~16.5, color #004c99 or similar).
    Field names are extracted from column headers and row labels, excluding machine codes,
    answer options, and technical annotations (red text, bracketed codes).
    """
    
    import re
    from collections import defaultdict
    
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip title page and TOC pages
        if page_num <= 10:
            continue
        
        # Extract form name from large blue headers
        for line in lines:
            # Look for form titles: large size (~16.5), blue color
            if line.size >= 15.0 and line.non_black and line.text.strip():
                text = line.text.strip()
                # Exclude machine codes and technical annotations
                if not re.match(r'^\[.*\]$', text) and not text.startswith('Row '):
                    current_form = text
                    break
        
        # Identify layout family by structure
        # Family C/D/E: Table-based forms with column headers around y=124
        headers = []
        for line in lines:
            if 120 <= line.y0 <= 160 and line.size >= 10.0 and not line.non_black:
                text = line.text.strip()
                # Exclude machine codes and page numbers
                if text and not re.match(r'^Page \d+', text) and not re.match(r'^\[.*\]$', text):
                    headers.append((line.x0, text))
        
        # Sort headers by x position
        headers.sort(key=lambda h: h[0])
        
        # Extract field names from headers
        for x_pos, header_text in headers:
            # Skip common non-field headers
            if header_text in ['Result', 'Status', 'Scan']:
                continue
            
            # Multi-line headers: look for continuation
            full_header = header_text
            for line in lines:
                if abs(line.x0 - x_pos) < 10 and 160 < line.y0 < 180 and line.size >= 10.0:
                    continuation = line.text.strip()
                    if continuation and not re.match(r'^\[.*\]$', continuation):
                        full_header += " " + continuation
            
            # Add as field if it looks like a data entry column
            if full_header and len(full_header) > 2:
                results.append({
                    "form_name": current_form,
                    "field_name": full_header,
                    "page": page_num
                })
        
        # Family D: Extract question/test labels from left column
        # Look for labels in left column (x < 400) that are not machine codes
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip machine codes, row markers, and technical annotations
            if re.match(r'^\[.*\]$', text):
                continue
            if text.startswith('Row ') or text.startswith('Page '):
                continue
            if line.non_black:  # Skip red technical text
                continue
            
            # Look for question/test labels in left column
            if line.x0 < 400 and line.size >= 9.0:
                # Check if this is a substantive label (not an answer option)
                if len(text) > 10 and not text in ['Yes', 'No', 'Positive', 'Negative', 'Not Done', 
                                                     'Normal', 'Abnormal', 'Not Applicable', 'NA',
                                                     'Collected', 'Not Collected']:
                    # Check if it's a question (contains question mark or is descriptive)
                    if '?' in text or len(text.split()) > 3:
                        # Join with next line if it's a continuation
                        full_text = text
                        if i + 1 < len(lines):
                            next_line = lines[i + 1]
                            if abs(next_line.x0 - line.x0) < 20 and next_line.y0 - line.y0 < 20:
                                next_text = next_line.text.strip()
                                if next_text and not re.match(r'^\[.*\]$', next_text) and not next_line.non_black:
                                    full_text += " " + next_text
                        
                        results.append({
                            "form_name": current_form,
                            "field_name": full_text,
                            "page": page_num
                        })
        
        # Extract standalone field labels (not in tables)
        # Look for labels followed by machine codes
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip if already processed or is machine code
            if not text or re.match(r'^\[.*\]$', text) or line.non_black:
                continue
            
            # Check if next line is a machine code (indicates this is a field label)
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                next_text = next_line.text.strip()
                if re.match(r'^\[.*\]$', next_text) and abs(next_line.x0 - line.x0) < 20:
                    # This is a field label
                    if len(text) > 3 and text not in ['Yes', 'No', 'Normal', 'Abnormal']:
                        results.append({
                            "form_name": current_form,
                            "field_name": text,
                            "page": page_num
                        })
    
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for record in results:
        key = (record['form_name'], record['field_name'], record['page'])
        if key not in seen:
            seen.add(key)
            deduped.append(record)
    
    return deduped
```