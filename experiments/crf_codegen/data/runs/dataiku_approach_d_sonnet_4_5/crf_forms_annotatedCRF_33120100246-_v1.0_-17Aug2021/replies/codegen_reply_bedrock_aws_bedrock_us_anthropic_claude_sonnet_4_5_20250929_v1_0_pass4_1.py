```python
# This CRF document contains multiple layout families:
# - Family A: Table of contents (page 1)
# - Family B: Continuation of table of contents (pages 2+)
# - Family C: Schedule of Assessments tables with visit/page mappings
# - Family D: Form pages with field codes in red (technical annotations)
# - Family E: C-SSRS cover pages (disclaimer/copyright text)
# - Family F: C-SSRS question pages with actual data-entry fields
# - Family G-H: Additional C-SSRS pages
# Strategy: Extract form names from blue headers; extract field labels from black text
# that are questions/prompts (not red technical codes, not answer options).

def extract(pages):
    records = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form name: large blue text near top (sz >= 14, color #004c99 or similar blue)
        form_name = ""
        for line in lines:
            if line.y0 < 150 and line.size >= 13 and line.non_black:
                # Check if it's a blue color (heuristic: contains '4c' or '60' in hex)
                form_name = line.text.strip()
                break
        
        # Skip table of contents pages (families A, B, C)
        # These have "Schedule" or "CHANGE HISTORY" or "PAGES" as headers
        is_toc = False
        for line in lines:
            if line.y0 < 200:
                text_lower = line.text.lower()
                if any(kw in text_lower for kw in ['schedule of assessment', 'change history', 
                                                     'annotated crf', 'pack version']):
                    is_toc = True
                    break
                # Schedule tables have "Visit Number", "Page Number", "Page Label" headers
                if 'visit label' in text_lower or 'page label' in text_lower:
                    is_toc = True
                    break
        
        if is_toc:
            continue
        
        # Skip C-SSRS cover pages (family E) - they have disclaimer/copyright text
        is_cover = False
        for line in lines:
            if 'disclaimer:' in line.text.lower() or '© 2008 the research foundation' in line.text.lower():
                is_cover = True
                break
            if 'columbia-suicide severity' in line.text.lower() and line.size > 14:
                # This is the title page
                is_cover = True
                break
        
        if is_cover:
            continue
        
        # Now extract fields from remaining pages
        # Fields are black text (not red technical codes), not bold headers, 
        # typically questions or prompts
        
        # Group lines that might be multi-line fields
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip red text (technical codes like [CSS0401A], [TYPE: ...])
            if line.non_black and '[' in line.text:
                i += 1
                continue
            
            # Skip very small text (< 7 points)
            if line.size < 6.5:
                i += 1
                continue
            
            # Skip answer options (Yes/No at specific x positions, typically right side)
            if line.x0 > 350 and line.text.strip() in ['Yes', 'No', '0', '1', '2', '3', '4', '5']:
                i += 1
                continue
            
            # Skip row labels like "Row 1", "Row 2", etc.
            if line.text.strip().startswith('Row ') and line.bold:
                i += 1
                continue
            
            # Skip technical field codes in red
            if '[' in line.text and ']' in line.text:
                i += 1
                continue
            
            # Skip enumeration descriptions (answer option lists)
            if '(values:' in line.text.lower() or 'enumeration' in line.text.lower():
                i += 1
                continue
            
            # Skip "If Yes, describe" prompts that are just labels for text boxes
            if line.text.strip() == 'If Yes, describe':
                i += 1
                continue
            
            # Look for actual field labels/questions
            text = line.text.strip()
            
            # Must be substantive text (not just punctuation or numbers)
            if len(text) < 3:
                i += 1
                continue
            
            # Skip pure numeric or date-like entries
            if text.replace('/', '').replace('-', '').replace(':', '').replace('.', '').isdigit():
                i += 1
                continue
            
            # Check if this looks like a field label
            # Fields are typically questions (contain '?') or descriptive prompts
            # They are in black text, left-aligned (x0 < 200), size 7-10 points
            
            is_field = False
            
            # Questions ending with '?'
            if '?' in text and not line.non_black and line.x0 < 300:
                is_field = True
            
            # Descriptive field labels (not bold section headers)
            # These are typically at x0 < 100, size 7-9, black
            if (not line.bold and not line.non_black and 
                line.x0 < 100 and 7 <= line.size <= 10 and
                len(text) > 10 and not text.startswith('(')):
                # Exclude answer option descriptions
                if not any(opt in text for opt in ['(1)', '(2)', '(3)', '(4)', '(5)', '(0)']):
                    # Check if it's a substantive label
                    if any(c.isalpha() for c in text):
                        is_field = True
            
            # Bold questions/prompts (but not section headers)
            if (line.bold and not line.non_black and 
                line.x0 < 100 and 7 <= line.size <= 10):
                # Must be a question or have substantive content
                if '?' in text or len(text.split()) > 3:
                    # Exclude numbered section headers like "1. Active suicidal ideation..."
                    if not (text[0].isdigit() and '. ' in text[:5]):
                        is_field = True
            
            if is_field:
                # Collect continuation lines (same x position, next lines)
                field_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Check if continuation (similar x, close y, same style)
                    if (abs(next_line.x0 - line.x0) < 10 and 
                        next_line.y0 - lines[j-1].y0 < 20 and
                        not next_line.non_black and
                        next_line.bold == line.bold and
                        not '[' in next_line.text):
                        # Check it's not an answer option
                        if next_line.text.strip() not in ['Yes', 'No', 'Current', 'Former', 'Never']:
                            field_text += ' ' + next_line.text.strip()
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # Clean up field text
                field_text = ' '.join(field_text.split())
                
                # Final validation: must be substantive
                if len(field_text) > 5 and form_name:
                    records.append({
                        'form_name': form_name,
                        'field_name': field_text,
                        'page': page_num
                    })
                
                i = j
            else:
                i += 1
    
    return records
```