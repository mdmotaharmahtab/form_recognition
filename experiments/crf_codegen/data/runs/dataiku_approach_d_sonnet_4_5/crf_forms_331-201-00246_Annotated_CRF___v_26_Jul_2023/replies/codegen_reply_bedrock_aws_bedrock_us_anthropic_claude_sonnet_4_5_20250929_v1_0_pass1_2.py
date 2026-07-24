```python
def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip table of contents pages (pages 1-2)
        if page_num <= 2:
            continue
        
        # Find form title: large blue text (sz >= 15.0, color #004c99)
        form_name = ""
        for line in lines:
            if line.size >= 15.0 and line.non_black:
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
            
            # Skip gray answer options (non_black, small text, typical answer values)
            if line.non_black and line.size < 12.0:
                text = line.text.strip()
                if text in ['Yes', 'No', 'NA', 'N/A', 'Met', 'Not Met']:
                    i += 1
                    continue
            
            # Field labels are black text, size typically 9.0-10.5
            if not line.non_black and 8.0 <= line.size <= 11.0:
                text = line.text.strip()
                
                # Skip empty lines
                if not text:
                    i += 1
                    continue
                
                # Skip technical markers
                if text.startswith('[') and text.endswith(']'):
                    i += 1
                    continue
                
                # Skip bullet points
                if text == '•':
                    i += 1
                    continue
                
                # Skip "Row N" labels (these are table row markers, not field labels)
                if text.startswith('Row ') and len(text) < 10:
                    i += 1
                    continue
                
                # Skip copyright and footer markers
                if text.startswith('**') or text.startswith('©'):
                    i += 1
                    continue
                
                # Check if this is positioned in the right column (answer options area)
                # Answer options typically appear at x > 450
                if line.x0 > 450:
                    i += 1
                    continue
                
                # Check if this is a table header in a multi-column layout
                # Headers are typically at the top and aligned with columns
                # Skip if y position is very close to form title (within ~50 points)
                if line.y0 < 200:
                    # Could be a column header - check if it's short and at specific x positions
                    if len(text) < 30 and line.x0 > 300:
                        i += 1
                        continue
                
                # This looks like a field label
                # Collect continuation lines (same x position, similar spacing)
                field_text = text
                j = i + 1
                
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop if we hit a red annotation
                    if next_line.non_black and '[' in next_line.text:
                        break
                    
                    # Stop if we hit another field at a different x position
                    # Allow some tolerance for wrapping
                    if abs(next_line.x0 - line.x0) > 30:
                        break
                    
                    # Stop if vertical gap is too large (new field)
                    if j > i and next_line.y0 - lines[j-1].y0 > 25:
                        break
                    
                    # Stop if we hit a form title
                    if next_line.size >= 15.0:
                        break
                    
                    # Stop if we hit answer options (gray text on right side)
                    if next_line.non_black and next_line.x0 > 450:
                        break
                    
                    # Stop if we hit page number
                    if 'Page' in next_line.text and 'of' in next_line.text:
                        break
                    
                    # Check if this is a continuation line
                    if not next_line.non_black and 8.0 <= next_line.size <= 11.0:
                        cont_text = next_line.text.strip()
                        
                        # Skip empty or technical lines
                        if not cont_text or (cont_text.startswith('[') and cont_text.endswith(']')):
                            break
                        
                        # Skip bullets
                        if cont_text == '•':
                            j += 1
                            continue
                        
                        # Skip if this looks like a new field (starts with number or capital letter pattern)
                        # But allow continuation of numbered lists within a field
                        if cont_text.startswith('Row '):
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
                
                # Skip if it's just a section marker or very short non-question text
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
```