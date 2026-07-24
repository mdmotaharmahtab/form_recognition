def extract(pages):
    """
    Extraction strategy for clinical CRF document.
    Handles multiple page layouts while filtering non-field elements.
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
        
        for line in lines:
            text = line.text.strip()
            if not text:
                continue
                
            # Large blue headers (form names)
            if line.size >= 15.0 and line.non_black:
                if not re.match(r'^\[.*\]$', text) and not text.startswith('Row '):
                    large_blue.append(text)
            
            # Potential table headers
            elif 100 <= line.y0 <= 180 and line.size >= 9.5 and not line.non_black:
                if not re.match(r'^Page \d+', text) and not re.match(r'^\[.*\]$', text):
                    potential_headers.append((line.x0, line.y0, text))
            
            # Potential field labels (left/middle column, below headers)
            elif line.y0 > 180 and line.size >= 8.5 and not line.non_black:
                if not re.match(r'^\[.*\]$', text) and not text.startswith('Row ') and not text.startswith('Page '):
                    if len(text) > 3:
                        potential_labels.append((line.x0, line.y0, text))
        
        # Extract form name (take first large blue header)
        if large_blue:
            current_form = large_blue[0]
        
        # Process table headers
        header_groups = defaultdict(list)
        for x_pos, y_pos, text in potential_headers:
            y_key = round(y_pos / 10) * 10
            header_groups[y_key].append((x_pos, text))
        
        # Extract unique headers
        seen_headers = set()
        for y_key in sorted(header_groups.keys()):
            for x_pos, header_text in header_groups[y_key]:
                if len(header_text) > 2 and header_text not in seen_headers:
                    # Filter out radio button labels and answer options
                    # These are typically short, single-word options in right columns
                    if not is_answer_option(header_text, x_pos, potential_headers):
                        seen_headers.add(header_text)
                        results.append({
                            "form_name": current_form,
                            "field_name": header_text,
                            "page": page_num
                        })
        
        # Process field labels
        page_width = 800  # default
        if potential_labels:
            max_x = max(x for x, y, t in potential_labels)
            page_width = max_x + 100
        
        left_column_boundary = page_width * 0.6
        
        seen_labels = set()
        for x_pos, y_pos, text in potential_labels:
            # Only process left/middle column
            if x_pos < left_column_boundary:
                # Filter by length and content
                if len(text) > 5 and text not in seen_labels:
                    # Filter out answer options and non-field text
                    if not is_answer_option(text, x_pos, potential_labels):
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


def is_answer_option(text, x_pos, all_items):
    """
    Determine if text is likely an answer option rather than a field label.
    Answer options are typically:
    - Short single words (Normal, Abnormal, Yes, No)
    - Positioned in right columns or aligned with other similar options
    - Part of a horizontal series of options
    """
    
    # Single word options that are common radio button labels
    single_word_options = {
        'Normal', 'Abnormal', 'Yes', 'No', 'Done', 'Not Done',
        'Positive', 'Negative', 'Present', 'Absent', 'Male', 'Female',
        'Left', 'Right', 'Mild', 'Moderate', 'Severe'
    }
    
    if text in single_word_options:
        return True
    
    # Check if it's a short text in a right-aligned position
    # (answer options are typically right of field labels)
    if len(text.split()) <= 2 and x_pos > 400:
        # Look for other similar short texts at similar x positions
        # indicating a column of answer options
        similar_x_count = sum(1 for x, y, t in all_items 
                             if abs(x - x_pos) < 20 and len(t.split()) <= 2)
        if similar_x_count >= 2:
            return True
    
    # Check for PK-related text patterns (study-specific codes)
    # These appear as technical annotations, not field labels
    if re.search(r'\bPK\b', text) and '/' in text:
        return True
    
    return False
