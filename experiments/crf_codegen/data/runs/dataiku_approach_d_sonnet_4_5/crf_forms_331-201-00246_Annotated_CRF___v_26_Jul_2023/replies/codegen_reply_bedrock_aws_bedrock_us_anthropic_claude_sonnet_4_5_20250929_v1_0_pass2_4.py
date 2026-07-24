Looking at the sample pages, I can see that all three clusters contain data-entry fields that my program is missing:

**Cluster 0** (pages 210, 421): These are multi-column table layouts with gray field labels like "Neurological", "Extremities", "Urogenital" (page 210) and "Prazosin PK", "Brexpiprazole/Sertraline PK" etc. (page 421). My current program looks for gray text near red codes, but the logic is too restrictive.

**Cluster 1** (pages 328, 785): These pages have bold field labels like "Frequency", "How many times have you had these thoughts?", "Duration", "When you have the thoughts, how long do they last?", "Controllability". My program should be extracting these but appears to be missing some.

**Cluster 2** (pages 497, 902): These are NOT field-free pages. They have column headers "Suicidal Behaviour" and "Since Last Visit" which appear to be field labels for a simple two-column form. The red text shows `[TYPE: enumeration (values: Yes, No)]` indicating there's a data-entry field here.

Let me fix the program to handle all these cases:

```python
def extract(pages):
    """
    Extraction strategy for clinical CRF document:
    
    Layout observations:
    - Cluster 0 (~88 pages): Multi-column tables with column headers (Region/Body System, Result, etc.)
      and field labels in left column. Red technical codes mark field positions.
    - Cluster 1 (~85 pages): Two-column layout with questions/labels on left, answer options on right.
      Bold text marks field labels/questions.
    - Cluster 2 (~18 pages): Simple two-column pages with minimal field labels as headers.
    
    Form titles appear as large blue text (size ~16.5, color #004c99) above field sections.
    Field labels are in black text, positioned in left columns.
    Column headers (e.g., "Result", "Status") can be structural markers OR field labels depending on context.
    Red text contains technical annotations/codes - used as landmarks but not extracted.
    Answer options appear in right columns or as enumeration values in red annotations.
    
    Strategy:
    1. Track form titles from large blue headers
    2. For cluster 0: Extract gray field labels from left column (near red codes)
    3. For cluster 1: Extract bold black questions/labels from left column
    4. For cluster 2: Extract field labels from header row (y ~124)
    5. Skip answer options (right column enumerated values), technical annotations (red), and page furniture
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
        # Count red technical codes
        red_codes = [l for l in lines if '#ff0000' in str(l.non_black) or 
                     (l.non_black and 'ff0000' in str(l.non_black))]
        
        # Check for column headers at top of page (y < 170)
        top_headers = [l for l in lines if l.y0 < 170 and l.size >= 10 and l.size <= 11 
                       and not l.non_black]
        header_texts = [l.text.strip() for l in top_headers]
        
        # Cluster 0: Multi-column table layout with red technical codes
        # Has headers like "Region/Body System", "Result", "Abnormal Findings", "Sample", "Timepoint"
        is_cluster_0 = len(red_codes) > 10
        
        # Cluster 1: Two-column layout with bold questions
        # Has headers like "Intensity of Ideation", "Since Last Visit"
        is_cluster_1 = any('Intensity of Ideation' in h or 'Since Last Visit' in h 
                           for h in header_texts)
        
        # Cluster 2: Minimal content pages with just headers and red codes
        # Has very few lines, headers at y~124, and red TYPE annotations
        is_cluster_2 = (len(lines) < 10 and len(red_codes) > 0 and 
                        any(l.y0 >= 120 and l.y0 <= 130 for l in top_headers))
        
        # Extract fields based on layout type
        field_candidates = []
        
        if is_cluster_2:
            # Cluster 2: Extract field labels from header row (y ~124)
            # These are the column headers which serve as field labels
            for line in lines:
                text = line.text.strip()
                
                if not text:
                    continue
                
                # Skip red text
                if '#ff0000' in str(line.non_black) or (line.non_black and 'ff0000' in str(line.non_black)):
                    continue
                
                # Skip page numbers
                if line.y0 > 550 and 'Page' in text and 'of 1085' in text:
                    continue
                
                # Look for headers at y ~124 (within range 120-130)
                if line.y0 >= 120 and line.y0 <= 130 and line.size >= 10 and line.size <= 11:
                    if re.search(r'[a-zA-Z]{3,}', text):
                        field_candidates.append({
                            'text': text,
                            'y': line.y0,
                            'x': line.x0,
                            'size': line.size
                        })
        
        elif is_cluster_0:
            # Cluster 0: Look for gray field labels in left column
            # Field labels are gray text (color #999999) in left column (x < 240)
            
            for line in lines:
                text = line.text.strip()
                
                if not text:
                    continue
                
                # Skip red text (technical codes)
                if '#ff0000' in str(line.non_black) or (line.non_black and 'ff0000' in str(line.non_black)):
                    continue
                
                # Skip page numbers (bottom of page, contains "Page" and "of 1085")
                if line.y0 > 550 and 'Page' in text and 'of 1085' in text:
                    continue
                
                # Skip column headers (at top, y < 170) - these are structural, not fields
                if line.y0 < 170:
                    continue
                
                # Skip row markers (pattern "Row N")
                if re.match(r'^Row \d+$', text):
                    continue
                
                # Skip answer options like "Yes", "No", "Normal", "Abnormal", "Not Done", "NA", "Collected", "Not Collected", "Scan"
                if text in ['Yes', 'No', 'Normal', 'Abnormal', 'Not Done', 'NA', 'Collected', 'Not Collected', 'Scan']:
                    continue
                
                # Field labels are gray text in left column (x < 240)
                # Gray text has non_black attribute with #999999 color
                if line.x0 < 240 and line.size >= 8.5 and line.size <= 11:
                    # Check if it's gray text
                    is_gray = '#999999' in str(line.non_black) or (line.non_black and '999999' in str(line.non_black))
                    
                    if is_gray and re.search(r'[a-zA-Z]{2,}', text):
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
                
                if not text:
                    continue
                
                # Skip red text
                if '#ff0000' in str(line.non_black) or (line.non_black and 'ff0000' in str(line.non_black)):
                    continue
                
                # Skip page numbers
                if line.y0 > 550 and 'Page' in text and 'of 1085' in text:
                    continue
                
                # Skip column headers (at top, y < 170)
                if line.y0 < 170:
                    continue
                
                # Skip row markers
                if re.match(r'^Row \d+$', text):
                    continue
                
                # Skip answer options in right column (x > 450)
                # Answer options are typically enumerated like "(1) ...", "(2) ..."
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
            # Other pages: Look for any field labels
            # These pages have minimal content, extract what's available
            for line in lines:
                text = line.text.strip()
                
                if not text:
                    continue
                
                # Skip red text
                if '#ff0000' in str(line.non_black) or (line.non_black and 'ff0000' in str(line.non_black)):
                    continue
                
                # Skip page numbers
                if line.y0 > 550 and 'Page' in text and 'of 1085' in text:
                    continue
                
                # Skip column headers (at top, y < 170)
                if line.y0 < 170:
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