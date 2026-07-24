```python
def extract(pages):
    """
    Extraction strategy for clinical CRF document.
    Handles multiple page layouts while filtering non-field elements.
    Uses structural rules (position, style, column) rather than text blocklists.
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
        
        # Pre-filter lines to avoid repeated processing
        large_blue = []
        potential_headers = []
        potential_labels = []
        
        # Determine page dimensions
        if lines:
            page_width = max(line.x1 for line in lines if hasattr(line, 'x1'))
            page_height = max(line.y1 for line in lines if hasattr(line, 'y1'))
        else:
            page_width = 800
            page_height = 1000
        
        for line in lines:
            text = line.text.strip()
            if not text:
                continue
            
            # Skip bracketed codes and row indicators
            if re.match(r'^\[.*\]$', text) or text.startswith('Row '):
                continue
            
            # Large blue headers (form names)
            if line.size >= 15.0 and line.non_black:
                large_blue.append(text)
            
            # Potential table headers (upper portion of page, medium-large font)
            elif line.y0 < page_height * 0.2 and line.size >= 9.5 and not line.non_black:
                if not re.match(r'^Page \d+', text):
                    potential_headers.append((line.x0, line.y0, text, line.size))
            
            # Potential field labels (main body, readable font)
            elif line.y0 >= page_height * 0.15 and line.size >= 8.5 and not line.non_black:
                if not text.startswith('Page ') and len(text) > 3:
                    potential_labels.append((line.x0, line.y0, text, line.size))
        
        # Extract form name (take first large blue header)
        if large_blue:
            current_form = large_blue[0]
        
        # Process table headers
        header_groups = defaultdict(list)
        for x_pos, y_pos, text, size in potential_headers:
            y_key = round(y_pos / 10) * 10
            header_groups[y_key].append((x_pos, text, size))
        
        # Extract unique headers
        seen_headers = set()
        for y_key in sorted(header_groups.keys()):
            for x_pos, header_text, size in header_groups[y_key]:
                if len(header_text) > 2 and header_text not in seen_headers:
                    # Filter by structural position: headers should be in left/center columns
                    # Right-aligned short text is typically answer options
                    if not is_right_column_option(header_text, x_pos, page_width):
                        seen_headers.add(header_text)
                        results.append({
                            "form_name": current_form,
                            "field_name": header_text,
                            "page": page_num
                        })
        
        # Process field labels
        # Divide page into columns based on x-position distribution
        left_boundary = page_width * 0.55  # Left/middle columns vs right column
        
        # Group labels by approximate y-position to identify rows
        label_rows = defaultdict(list)
        for x_pos, y_pos, text, size in potential_labels:
            y_key = round(y_pos / 15) * 15
            label_rows[y_key].append((x_pos, text, size))
        
        seen_labels = set()
        for y_key in sorted(label_rows.keys()):
            row_items = label_rows[y_key]
            
            for x_pos, text, size in row_items:
                # Only process left/middle column items
                if x_pos < left_boundary:
                    # Filter by length and content
                    if len(text) > 5 and text not in seen_labels:
                        # Exclude if it's a technical annotation (appears in right portion of left column)
                        # Technical annotations like "Sertraline PK" are positioned between field label and answer area
                        if not is_technical_annotation(text, x_pos, row_items, left_boundary):
                            seen_labels.add(text)
                            results.append({
                                "form_name": current_form,
                                "field_name": text,
                                "page": page_num
                            })
    
    # Deduplicate
    seen = set()
    deduped = []
    for record in results:
        key = (record['form_name'], record['field_name'], record['page'])
        if key not in seen:
            seen.add(key)
            deduped.append(record)
    
    return deduped


def is_right_column_option(text, x_pos, page_width):
    """
    Determine if text is in the right column, likely an answer option.
    Answer options are positioned in the right portion of the page.
    """
    # Right column starts around 55-60% of page width
    right_column_start = page_width * 0.55
    
    # Short text in right column is likely an answer option
    if x_pos > right_column_start and len(text.split()) <= 2:
        return True
    
    return False


def is_technical_annotation(text, x_pos, row_items, left_boundary):
    """
    Determine if text is a technical annotation rather than a field label.
    Technical annotations (like "Sertraline PK", "Propranolol PK") are:
    - Positioned in the middle area between field labels and answer columns
    - Often contain technical abbreviations or codes
    - Shorter than typical field labels
    - Positioned to the right of the main field label in the same row
    """
    
    # Check if there's a longer text item to the left in the same row
    # (indicating this might be a secondary annotation)
    items_to_left = [t for x, t, s in row_items if x < x_pos and len(t) > len(text)]
    
    # If positioned in middle-right area of left column with items to the left
    middle_area_start = left_boundary * 0.6
    if x_pos > middle_area_start and items_to_left:
        # Technical annotations are typically shorter and contain abbreviations
        if len(text.split()) <= 3:
            # Contains technical patterns like "PK", "ID", codes with slashes
            if re.search(r'\b(PK|ID|QC)\b', text) or '/' in text:
                return True
    
    return False
```