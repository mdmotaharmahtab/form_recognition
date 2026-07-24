```python
def extract(pages):
    """
    Extraction strategy for clinical CRF document:
    
    Layout observations:
    - Cluster 0 (~88 pages): Multi-column tables with column headers (Region/Body System, Result, etc.)
      and field labels in left column. Red technical codes mark field positions.
    - Cluster 1 (~85 pages): Two-column layout with questions/labels on left, answer options on right.
      Bold text marks field labels/questions.
    - Cluster 2 (~18 pages): Simple header-only pages with minimal content.
    
    Form titles appear as large blue text (size ~16.5, color #004c99) above field sections.
    Field labels are in black text, positioned in left columns.
    Column headers (e.g., "Result", "Status") are structural markers at top of tables.
    Red text contains technical annotations/codes - used as landmarks but not extracted.
    Answer options appear in right columns or as enumeration values in red annotations.
    
    Strategy:
    1. Track form titles from large blue headers
    2. For cluster 0: Extract field labels from left column, identified by adjacent red codes
    3. For cluster 1: Extract bold black questions/labels from left column
    4. For cluster 2: Extract any field labels present
    5. Skip column headers, answer options, technical annotations, and page furniture
    6. Handle multi-line label wrapping by joining continuation lines
    """
    
    import re
    from collections import defaultdict
    
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Check if this is a table of contents page
        # TOC pages have many blue hyperlinks and "Page X of 1085" pattern
        blue_links = [l for l in lines if l.non_black and 'black' not in str(l.text)]
        if len(blue_links) > 10 and any('of 1085' in l.text for l in lines):
            continue
        
        # Look for form title: large blue text (size >= 15, color blue)
        for line in lines:
            if line.size >= 15 and line.non_black and line.x0 < 150:
                text = line.text.strip()
                # Avoid technical markers
                if not text.startswith('[') and not text.endswith(']'):
                    if len(text) > 3 and not re.match(r'^\d+$', text):
                        current_form = text
                        break
        
        # Identify page layout type by examining structure
        # Count red technical codes and column headers
        red_codes = [l for l in lines if '#ff0000' in str(l.non_black) or 
                     (l.non_black and 'ff0000' in str(l.non_black))]
        
        # Check for column headers at top of page (y < 160)
        top_headers = [l for l in lines if l.y0 < 160 and l.size >= 10 and l.size <= 11 
                       and not l.non_black]
        header_texts = [l.text.strip() for l in top_headers]
        
        # Cluster 0: Multi-column table layout with red technical codes
        # Has headers like "Region/Body System", "Result", "Abnormal Findings"
        is_cluster_0 = (len(red_codes) > 10 and 
                        any(h in ['Region/Body System', 'Result', 'Abnormal Findings', 
                                  'Sample', 'Timepoint', 'Sample Status'] 
                            for h in header_texts))
        
        # Cluster 1: Two-column layout with bold questions
        # Has headers like "Intensity of Ideation", "Since Last Visit"
        is_cluster_1 = any(h in ['Intensity of Ideation', 'Since Last Visit', 
                                 'Suicidal Ideation', 'Lifetime', 'Past 3 Month']
                           for h in header_texts)
        
        # Extract fields based on layout type
        field_candidates = []
        
        if is_cluster_0:
            # Cluster 0: Look for field labels marked by red technical codes
            # Field labels are black text in left column (x < 240) adjacent to red codes
            
            # Build a map of y-positions with red codes
            red_y_positions = set()
            for line in red_codes:
                # Red codes like [PETEST], [PEDESC], [LBCAT8], etc.
                if line.text.strip().startswith('[') and line.text.strip().endswith(']'):
                    red_y_positions.add(int(line.y0 / 10) * 10)  # Group by ~10pt bands
            
            # Look for black text labels near these positions
            for line in lines:
                text = line.text.strip()
                
                if not text or line.non_black:
                    continue
                
                # Skip page numbers
                if 'Page' in text and 'of 1085' in text:
                    continue
                
                # Skip column headers (at top, specific known headers)
                if line.y0 < 160 and text in ['Region/Body System', 'Result', 
                                               'Abnormal Findings', 'Clinically Significant',
                                               'Sample', 'Timepoint', 'Sample Status',
                                               'Time of', 'Barcode', 'Backup', 'Collection',
                                               'Number']:
                    continue
                
                # Skip answer options (appear in right columns or as standalone)
                if text in ['Yes', 'No', 'Normal', 'Abnormal', 'Not Done', 'NA',
                           'Collected', 'Not Collected', 'Scan']:
                    continue
                
                # Skip row markers
                if re.match(r'^Row \d+$', text):
                    continue
                
                # Field labels are in left column (x < 240) with gray or black text
                # They appear near red code positions
                if line.x0 < 240 and line.size >= 8.5 and line.size <= 11:
                    y_band = int(line.y0 / 10) * 10
                    
                    # Check if there's a red code nearby (within 50 points vertically)
                    has_nearby_code = any(abs(y_band - red_y) < 50 for red_y in red_y_positions)
                    
                    if has_nearby_code and re.search(r'[a-zA-Z]{3,}', text):
                        # Skip copyright and footer
                        if '©' in text or 'copyright' in text.lower():
                            continue
                        
                        field_candidates.append({
                            'text': text,
                            'y': line.y0,
                            'x': line.x0,
                            'size': line.size
                        })
        
        elif is_cluster_1:
            # Cluster 1: Look for bold questions/labels in left column
            for line in lines:
                text = line.text.strip()
                
                if not text or line.non_black:
                    continue
                
                # Skip page numbers
                if 'Page' in text and 'of 1085' in text:
                    continue
                
                # Skip column headers
                if line.y0 < 160 and text in ['Intensity of Ideation', 'Since Last Visit',
                                               'Suicidal Ideation', 'Lifetime', 
                                               'Past 3 Month', 'Suicidal Behaviour']:
                    continue
                
                # Skip row markers
                if re.match(r'^Row \d+$', text):
                    continue
                
                # Skip answer options (in right column, x > 450)
                if line.x0 > 450:
                    continue
                
                # Field labels are bold black text in left column
                if line.bold and line.x0 < 400 and line.size >= 8.5 and line.size <= 12:
                    if re.search(r'[a-zA-Z]{3,}', text):
                        # Skip copyright
                        if '©' in text or 'copyright' in text.lower():
                            continue
                        
                        field_candidates.append({
                            'text': text,
                            'y': line.y0,
                            'x': line.x0,
                            'size': line.size
                        })
        
        else:
            # Cluster 2 or other: Look for any field labels
            # These pages have minimal content, extract what's available
            for line in lines:
                text = line.text.strip()
                
                if not text or line.non_black:
                    continue
                
                # Skip page numbers
                if 'Page' in text and 'of 1085' in text:
                    continue
                
                # Skip column headers
                if line.y0 < 160 and text in ['Suicidal Behaviour', 'Since Last Visit']:
                    continue
                
                # Look for field labels in left column
                if line.x0 < 400 and line.size >= 8.5 and line.size <= 12:
                    if re.search(r'[a-zA-Z]{3,}', text):
                        if '©' in text or 'copyright' in text.lower():
                            continue
                        
                        field_candidates.append({
                            'text': text,
                            'y': line.y0,
                            'x': line.x0,
                            'size': line.size
                        })
        
        # Process field candidates - merge multi-line labels
        if field_candidates:
            # Sort by y position, then x
            field_candidates.sort(key=lambda f: (f['y'], f['x']))
            
            merged_fields = []
            i = 0
            while i < len(field_candidates):
                current = field_candidates[i]
                merged_text = current['text']
                
                # Look ahead for continuation lines (within ~15 points vertically)
                j = i + 1
                while j < len(field_candidates):
                    next_field = field_candidates[j]
                    if (next_field['y'] - current['y'] < 15 and 
                        abs(next_field['x'] - current['x']) < 20):
                        # Continuation line
                        merged_text += ' ' + next_field['text']
                        j += 1
                    else:
                        break
                
                merged_fields.append(merged_text)
                i = j if j > i + 1 else i + 1
            
            # Add to results
            for field_text in merged_fields:
                field_text = field_text.strip()
                if field_text and len(field_text) > 2:
                    results.append({
                        'form_name': current_form,
                        'field_name': field_text,
                        'page': page_num
                    })
    
    return results
```