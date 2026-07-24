def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip table of contents pages (pages 1-2)
        if page_num <= 2:
            continue
        
        # Find form title: large blue text (sz >= 15.0, color #004c99) or large black bold text
        form_name = ""
        for line in lines:
            if line.size >= 15.0 and (line.non_black or line.bold):
                text = line.text.strip()
                # Skip technical annotations
                if text.startswith('[') or text.endswith(']'):
                    continue
                # This is likely the form title
                form_name = text
                break
        
        # If no form name found, skip this page
        if not form_name:
            continue
        
        # Detect layout type by looking for table headers
        has_table_layout = False
        table_header_y = None
        answer_column_x = None
        
        for line in lines:
            text = line.text.strip()
            # Look for table headers like "Criteria", "Met/Not Met", "Since Last Visit"
            if line.y0 < 150 and line.size >= 9.0:
                if text in ['Criteria', 'Met/Not Met', 'Since Last Visit', 'Suicidal Behaviour']:
                    has_table_layout = True
                    if table_header_y is None or line.y0 < table_header_y:
                        table_header_y = line.y0
                    # Track rightmost column position (answer options)
                    if text in ['Met/Not Met', 'Since Last Visit'] and line.x0 > 500:
                        answer_column_x = line.x0
        
        # Extract field labels
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip red technical annotations (non_black and contains brackets)
            if line.non_black and '[' in line.text:
                i += 1
                continue
            
            # Skip form title itself
            if line.size >= 15.0:
                i += 1
                continue
            
            # Skip page numbers (typically at bottom, contains "Page" and "of")
            if 'Page' in line.text and 'of' in line.text:
                i += 1
                continue
            
            # Skip gray answer options on the right side (x0 > 500)
            if line.non_black and line.x0 > 500:
                i += 1
                continue
            
            # Skip table headers themselves (already used for layout detection)
            text = line.text.strip()
            if has_table_layout and table_header_y and abs(line.y0 - table_header_y) < 5:
                i += 1
                continue
            
            # Skip "Row N" labels (these are table row markers, not field labels)
            if text.startswith('Row ') and text[4:].strip().isdigit():
                i += 1
                continue
            
            # Skip bullet points alone
            if text == '•':
                i += 1
                continue
            
            # Skip copyright and footer markers (start with ** or ©)
            if text.startswith('**') or text.startswith('©'):
                i += 1
                continue
            
            # Field labels: black text, reasonable size
            # For table layouts, accept items in left column (x0 < 400)
            # For standard layouts, accept black text with size 8.0-11.0
            is_field_candidate = False
            
            if has_table_layout:
                # In table layout, field labels are in left column, black text
                if not line.non_black and line.x0 < 400 and 8.0 <= line.size <= 11.0:
                    # Must be below table header
                    if table_header_y is None or line.y0 > table_header_y + 20:
                        is_field_candidate = True
            else:
                # Standard layout: black text, size 8.0-11.0
                if not line.non_black and 8.0 <= line.size <= 11.0:
                    is_field_candidate = True
                # Also accept slightly larger text in lists (cluster 1 - lab tests, codes)
                elif not line.non_black and 10.0 <= line.size <= 11.0 and line.x0 > 300:
                    is_field_candidate = True
            
            if is_field_candidate:
                # Skip empty lines
                if not text:
                    i += 1
                    continue
                
                # Skip technical markers
                if text.startswith('[') and text.endswith(']'):
                    i += 1
                    continue
                
                # Collect continuation lines
                field_text = text
                j = i + 1
                
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop if we hit a red annotation
                    if next_line.non_black and '[' in next_line.text:
                        break
                    
                    # Stop if we hit a form title
                    if next_line.size >= 15.0:
                        break
                    
                    # Stop if we hit page number
                    if 'Page' in next_line.text and 'of' in next_line.text:
                        break
                    
                    # Stop if we hit a "Row N" marker
                    next_text = next_line.text.strip()
                    if next_text.startswith('Row ') and next_text[4:].strip().isdigit():
                        break
                    
                    # Stop if we hit answer options (gray text on right side)
                    if next_line.non_black and next_line.x0 > 500:
                        break
                    
                    # Stop if vertical gap is too large (new field)
                    if j > i and next_line.y0 - lines[j-1].y0 > 25:
                        break
                    
                    # Check if this is a continuation line
                    if not next_line.non_black and 8.0 <= next_line.size <= 11.0:
                        cont_text = next_line.text.strip()
                        
                        # Skip empty or technical lines
                        if not cont_text or (cont_text.startswith('[') and cont_text.endswith(']')):
                            break
                        
                        # Handle bullets - include them as part of the field
                        if cont_text == '•':
                            j += 1
                            continue
                        
                        # Stop on instructional phrases that are not part of the field label
                        # These are typically at the end and start with specific patterns
                        if cont_text.startswith('If Yes,') or cont_text.startswith('If No,'):
                            break
                        if '- mark the selected' in cont_text.lower():
                            break
                        
                        # Check horizontal alignment
                        # For table layout, continuation must be in same column (x0 < 400)
                        if has_table_layout and next_line.x0 >= 400:
                            break
                        
                        # For standard layout, allow reasonable indentation
                        if not has_table_layout:
                            # Allow continuation if x0 is within 50 points or indented
                            if abs(next_line.x0 - line.x0) > 50:
                                # If significantly indented (more than 50 to the right), might be sub-item
                                if next_line.x0 > line.x0 + 50:
                                    # But if it's way to the right (>400), it's likely answer column
                                    if next_line.x0 > 400:
                                        break
                        
                        # Add continuation
                        field_text += ' ' + cont_text
                        j += 1
                    else:
                        break
                
                # Clean up the field text
                field_text = field_text.strip()
                
                # Skip if empty after cleanup
                if not field_text:
                    i = j
                    continue
                
                # Skip very short non-descriptive text
                if len(field_text) < 3:
                    i = j
                    continue
                
                # Add the field
                results.append({
                    "form_name": form_name,
                    "field_name": field_text,
                    "page": page_num
                })
                
                i = j
            else:
                i += 1
    
    return results
