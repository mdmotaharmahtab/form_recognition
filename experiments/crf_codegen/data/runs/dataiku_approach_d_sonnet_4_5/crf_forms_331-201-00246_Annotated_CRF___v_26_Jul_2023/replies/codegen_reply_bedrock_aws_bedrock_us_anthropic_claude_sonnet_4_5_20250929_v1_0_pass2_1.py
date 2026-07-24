```python
def extract(pages):
    """
    Extraction strategy for clinical CRF document:
    
    Layout observations:
    - Family A: Table of contents with section links (page 1)
    - Family B: Continuation of table of contents (page 2)
    - Family C: Multi-column tables with column headers and data fields (~88 pages)
    - Family D: Two-column layout with test/question labels and result columns (~85 pages)
    - Family E: Simple table headers only, minimal content (~18 pages)
    
    Form titles appear as large blue text (size ~16.5, color #004c99) above field sections.
    Field labels are in black text at size ~9-10.5, positioned in left columns.
    Column headers (e.g., "Result", "Status") are structural markers, not fields.
    Red text contains technical annotations/codes - used as landmarks but not extracted.
    
    Strategy:
    1. Track form titles from large blue headers
    2. Extract field labels from left-aligned black text in data entry areas
    3. Skip table-of-contents pages, column headers, and technical annotations
    4. Handle multi-line label wrapping by joining continuation lines
    """
    
    import re
    from collections import defaultdict
    
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Check if this is a table of contents page (families A, B)
        # TOC pages have many blue hyperlinks and "Page X of 1085" pattern
        blue_links = [l for l in lines if l.non_black and 'black' not in str(l.text)]
        if len(blue_links) > 10 and any('of 1085' in l.text for l in lines):
            # Skip TOC pages
            continue
        
        # Look for form title: large blue text (size >= 15, color #004c99 or similar blue)
        for line in lines:
            if line.size >= 15 and line.non_black and line.x0 < 150:
                # Check if it's a blue title (not red annotations)
                text = line.text.strip()
                # Avoid technical markers
                if not text.startswith('[') and not text.endswith(']'):
                    if len(text) > 3 and not re.match(r'^\d+$', text):
                        current_form = text
                        break
        
        # Extract fields from the page
        # Group lines by vertical position to handle multi-line labels
        field_candidates = []
        
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty, page numbers, technical annotations
            if not text:
                continue
            if 'Page' in text and 'of 1085' in text:
                continue
            if text.startswith('[') or text.endswith(']'):
                continue
            if re.match(r'^\[\w+', text):  # Technical codes
                continue
            
            # Skip column headers (appear at top of tables, size ~10.5)
            if line.y0 < 160 and line.size >= 10 and line.size <= 11:
                # Common headers to skip
                if text in ['Region/Body System', 'Result', 'Abnormal Findings', 
                           'Clinically Significant', 'Sample', 'Status', 'Reason not done',
                           'Date of Collection', 'Time of Collection', 'Scan', 
                           'Barcode Number', 'Test', 'Timepoint', 'Sample Status',
                           'Time of', 'Barcode', 'Backup', 'Collection', 'Number',
                           'Suicidal Ideation', 'Lifetime', 'Past 3 Month', 
                           'Since Last Visit', 'Intensity of Ideation',
                           'Suicidal Behaviour', 'Start date', 'Stop date', 'Trial Day',
                           'Total Number of Tab taken', 'Date Dispensed']:
                    continue
            
            # Skip answer options (Yes/No/etc at specific positions)
            if text in ['Yes', 'No', 'Normal', 'Abnormal', 'Not Done', 'NA', 
                       'Positive', 'Negative', 'Not Applicable', 'Collected',
                       'Not Collected', 'Scan']:
                # These appear as options in result columns (x > 350)
                if line.x0 > 350:
                    continue
            
            # Skip row markers
            if re.match(r'^Row \d+$', text):
                continue
            
            # Skip pure numeric or date-like content
            if re.match(r'^[\d\s\-/:]+$', text):
                continue
            
            # Field labels are typically:
            # - Black text (not colored)
            # - Size 9-11 points
            # - Left-aligned (x0 < 400 for main labels)
            # - Not bold headers in some cases, but can be bold questions
            
            if not line.non_black and line.size >= 8.5 and line.size <= 12:
                # Left column fields
                if line.x0 < 400:
                    # Check if it's a real question/label
                    # Must have some alphabetic content
                    if re.search(r'[a-zA-Z]{3,}', text):
                        # Skip copyright and footer text
                        if '©' in text or 'copyright' in text.lower():
                            continue
                        if 'Research Foundation' in text:
                            continue
                        
                        # Skip instructional text that's too long and descriptive
                        # Real labels are typically questions or short descriptors
                        if len(text) > 200:
                            continue
                        
                        # Skip "If Yes, describe" type prompts that are sub-labels
                        if text.startswith('If ') and len(text) < 30:
                            continue
                        
                        field_candidates.append({
                            'text': text,
                            'y': line.y0,
                            'x': line.x0,
                            'bold': line.bold,
                            'size': line.size
                        })
        
        # Process field candidates - merge multi-line labels
        if field_candidates:
            # Sort by y position
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
                # Final cleanup
                field_text = field_text.strip()
                if field_text and len(field_text) > 2:
                    results.append({
                        'form_name': current_form,
                        'field_name': field_text,
                        'page': page_num
                    })
    
    return results
```