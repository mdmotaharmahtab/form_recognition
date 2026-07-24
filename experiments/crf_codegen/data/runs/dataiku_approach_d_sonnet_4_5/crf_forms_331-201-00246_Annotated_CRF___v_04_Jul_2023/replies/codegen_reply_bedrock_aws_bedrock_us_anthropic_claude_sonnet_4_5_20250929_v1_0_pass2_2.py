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
        
        # Identify table headers (typically around y=120-160, black text, size >= 10)
        headers = []
        for line in lines:
            if 100 <= line.y0 <= 180 and line.size >= 9.5 and not line.non_black:
                text = line.text.strip()
                # Exclude machine codes and page numbers
                if text and not re.match(r'^Page \d+', text) and not re.match(r'^\[.*\]$', text):
                    headers.append((line.x0, line.y0, text, line.size))
        
        # Sort headers by y position first, then x position
        headers.sort(key=lambda h: (h[1], h[0]))
        
        # Group headers by y position (same row)
        header_rows = defaultdict(list)
        for x_pos, y_pos, text, size in headers:
            # Group by y position with tolerance
            y_key = round(y_pos / 10) * 10
            header_rows[y_key].append((x_pos, text))
        
        # Extract field names from headers
        for y_key in sorted(header_rows.keys()):
            row_headers = sorted(header_rows[y_key], key=lambda h: h[0])
            
            for x_pos, header_text in row_headers:
                # Multi-line headers: look for continuation below
                full_header = header_text
                for line in lines:
                    if abs(line.x0 - x_pos) < 15 and line.y0 > y_key and line.y0 < y_key + 30 and line.size >= 9.0:
                        continuation = line.text.strip()
                        if continuation and not re.match(r'^\[.*\]$', continuation) and not line.non_black:
                            full_header += " " + continuation
                
                # Add as field if it looks like a data entry column
                # Structural filter: must be substantive (length > 2)
                if full_header and len(full_header) > 2:
                    results.append({
                        "form_name": current_form,
                        "field_name": full_header,
                        "page": page_num
                    })
        
        # Extract question/test labels from left column (Family D)
        # Look for labels in left column (x < page_width * 0.6) that are not machine codes
        # Determine page width
        page_width = max([line.x0 + 100 for line in lines]) if lines else 800
        left_column_boundary = page_width * 0.6
        
        # Collect potential field labels
        potential_labels = []
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip machine codes, row markers, and technical annotations
            if re.match(r'^\[.*\]$', text):
                continue
            if text.startswith('Row ') or text.startswith('Page '):
                continue
            if line.non_black:  # Skip red/blue technical text
                continue
            
            # Look for labels in left/middle column, below header area
            if line.x0 < left_column_boundary and line.y0 > 180 and line.size >= 8.5:
                # Structural filter: substantive text (length > 5)
                # Exclude very short text that's likely answer options
                if len(text) > 5:
                    potential_labels.append((i, line, text))
        
        # Process potential labels
        for i, line, text in potential_labels:
            # Check if this is a multi-line label
            full_text = text
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                next_text = next_line.text.strip()
                
                # Stop if we hit a machine code or different column
                if re.match(r'^\[.*\]$', next_text):
                    break
                if next_line.non_black:
                    break
                if abs(next_line.x0 - line.x0) > 30:
                    break
                if next_line.y0 - line.y0 > 50:
                    break
                
                # Check if it's a continuation (similar x, close y)
                if abs(next_line.x0 - line.x0) < 30 and next_line.y0 - line.y0 < 25:
                    if next_text and len(next_text) > 3:
                        full_text += " " + next_text
                        j += 1
                else:
                    break
            
            # Add if substantive (length > 10 or contains question mark)
            if len(full_text) > 10 or '?' in full_text:
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
            
            # Skip if in header area
            if line.y0 < 180:
                continue
            
            # Check if next line is a machine code (indicates this is a field label)
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                next_text = next_line.text.strip()
                if re.match(r'^\[.*\]$', next_text) and abs(next_line.x0 - line.x0) < 30:
                    # This is a field label
                    # Structural filter: substantive length
                    if len(text) > 3:
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