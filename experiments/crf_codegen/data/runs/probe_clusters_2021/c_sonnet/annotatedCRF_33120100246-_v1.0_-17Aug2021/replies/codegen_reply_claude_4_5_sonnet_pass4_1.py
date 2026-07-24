```python
# This CRF document contains multiple layout families:
# - Family A: Table of contents with numbered sections and hyperlinks
# - Family B: Table of contents continuation pages
# - Family C: Drug screen result forms with repeating test items (Benzodiazepines, Cannabinoids, etc.)
# - Family D: Columbia-Suicide Severity Rating Scale (C-SSRS) cover/disclaimer page
# - Family E: C-SSRS question pages with suicidal ideation assessment items
#
# Strategy:
# 1. Identify form names from large blue headers (size ~14-15, color #004c99 or #1d60a4)
# 2. Extract field labels from black text that are questions or item descriptions
# 3. Skip table of contents pages (families A & B) - identified by extensive blue hyperlink text
# 4. Skip pure instructional/disclaimer pages - identified by dense paragraph text with no field structure
# 5. For C-SSRS and drug screen forms, extract question/test labels while ignoring:
#    - Machine codes in red [brackets]
#    - Answer options (Yes/No, Positive/Negative/Not Done, rating scales)
#    - Row numbers
#    - Technical type annotations
# 6. Join wrapped label text across multiple visual lines based on coordinate proximity

import re

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip empty pages
        if not lines:
            continue
        
        # Check if this is a table of contents page (families A & B)
        # TOC pages have many blue hyperlink-style lines with numbered sections
        blue_link_count = sum(1 for ln in lines if ln.non_black and '#' in str(ln.text) and 
                              any(x in ln.text for x in ['.', 'HISTORY', 'ASSESSMENT', 'PAGES']))
        if blue_link_count > 10:
            continue
        
        # Look for form/section titles - large blue headers
        for i, line in enumerate(lines):
            if line.size >= 13.0 and line.non_black and line.text.strip():
                # Check for blue colors commonly used for section headers
                text = line.text.strip()
                # Avoid picking up "Row N" or machine codes as form names
                if not re.match(r'^Row \d+$', text) and not re.match(r'^\[.*\]$', text):
                    if len(text) > 3:  # Reasonable length for a form title
                        current_form = text
                        break
        
        # Check if this is a pure disclaimer/instruction page
        # C-SSRS disclaimer page has dense paragraph text with copyright, no data fields
        disclaimer_keywords = ['Disclaimer:', '© 20', 'reprints', 'contact', 'Research Foundation']
        if any(kw in line.text for line in lines for kw in disclaimer_keywords):
            # Check density of small text paragraphs
            small_text_lines = [ln for ln in lines if ln.size < 10 and len(ln.text) > 50]
            if len(small_text_lines) > 8:
                continue
        
        # Extract fields from this page
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip machine codes in red brackets
            if text.startswith('[') and line.non_black:
                i += 1
                continue
            
            # Skip "Row N" labels
            if re.match(r'^Row \d+$', text) and line.bold:
                i += 1
                continue
            
            # Skip answer options - Yes/No/Not Done pattern with specific spacing
            if text in ['Yes', 'No', 'Not Done', 'Positive', 'Negative'] and line.x0 > 300:
                i += 1
                continue
            
            # Skip "If Yes, describe" or "If Yes," prompts - these are sub-prompts, not fields
            if text.startswith('If Yes'):
                i += 1
                continue
            
            # Skip pure descriptive/definition paragraphs (small font, not bold, indented)
            if (line.size < 8.5 and not line.bold and line.x0 > 60 and 
                len(text) > 40 and not text.endswith('?')):
                i += 1
                continue
            
            # Identify potential field labels
            # Fields are typically:
            # - Black text (not red machine codes)
            # - Size 7-10 points
            # - Left-aligned (x0 < 100)
            # - Questions (ending with ?) or test/item names
            # - May be bold or regular
            
            is_question = text.endswith('?')
            is_test_name = (line.size >= 7.0 and line.size <= 9.0 and 
                           line.x0 < 100 and len(text) > 5 and not line.non_black)
            
            # Check if this looks like a field label
            if (not line.non_black and line.x0 < 100 and line.size >= 7.0 and 
                line.size <= 16.0 and len(text) >= 3):
                
                # Collect this line and potential continuation lines
                field_parts = [text]
                j = i + 1
                
                # Look ahead for wrapped lines (similar x position, close y position, continuing text)
                while j < len(lines):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Stop if we hit a machine code
                    if next_text.startswith('[') and next_line.non_black:
                        break
                    
                    # Stop if we hit answer options
                    if next_text in ['Yes', 'No', 'Not Done', 'Positive', 'Negative'] and next_line.x0 > 300:
                        break
                    
                    # Stop if we hit "Row N"
                    if re.match(r'^Row \d+$', next_text) and next_line.bold:
                        break
                    
                    # Check if this is a continuation line
                    y_gap = next_line.y0 - line.y0
                    x_similar = abs(next_line.x0 - line.x0) < 30
                    
                    # If it's close vertically and horizontally aligned, and similar styling
                    if (y_gap < 30 and y_gap > 5 and x_similar and 
                        not next_line.non_black and next_line.size >= 7.0 and next_line.size <= 16.0):
                        
                        # Check if it looks like continuation text (lowercase start, or continues sentence)
                        if (len(next_text) > 2 and not next_text.startswith('If Yes') and
                            not re.match(r'^\d+\.', next_text)):
                            field_parts.append(next_text)
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # Join the field parts
                full_field = ' '.join(field_parts)
                
                # Filter out non-field text
                # Skip if it's just a section number
                if re.match(r'^\d+\.$', full_field):
                    i = j
                    continue
                
                # Skip rating scale anchors (enumerated explanations)
                if re.match(r'^\(\d+\)', full_field):
                    i = j
                    continue
                
                # Skip common instruction fragments
                skip_phrases = ['describe', 'Total number of', 'Version', 'Posner', 'Mann']
                if any(phrase in full_field for phrase in skip_phrases) and not full_field.endswith('?'):
                    i = j
                    continue
                
                # Valid field: either a question or a test/item name
                if is_question or (len(full_field) > 5 and len(full_field) < 200):
                    # Ensure we have a form name
                    if current_form:
                        # Additional filter: skip if it looks like a definition paragraph
                        if not (len(full_field) > 150 and not full_field.endswith('?')):
                            records.append({
                                "form_name": current_form,
                                "field_name": full_field,
                                "page": page_num
                            })
                
                i = j
            else:
                i += 1
    
    # Deduplicate consecutive identical records (same form, field, page)
    deduped = []
    prev = None
    for rec in records:
        if rec != prev:
            deduped.append(rec)
            prev = rec
    
    return deduped
```
