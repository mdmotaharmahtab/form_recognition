```python
def extract(pages):
    records = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form name: large blue text near top (sz >= 13, color non-black, y0 < 150)
        form_name = ""
        for line in lines:
            if line.y0 < 150 and line.size >= 13 and line.non_black:
                # Blue header text
                text = line.text.strip()
                # Exclude technical annotations
                if not text.startswith('[') and not 'TYPE:' in text:
                    form_name = text
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
            # Title page with large "COLUMBIA-SUICIDE SEVERITY RATING SCALE"
            if 'columbia-suicide severity' in line.text.lower() and line.size > 14 and line.bold:
                is_cover = True
                break
        
        if is_cover:
            continue
        
        # Skip technical annotation pages (all red/gray text showing field codes)
        # These have many lines with [TYPE: ...] and field codes
        # Count red lines with technical markers
        red_tech_count = 0
        for line in lines:
            if line.non_black and ('[TYPE:' in line.text or line.text.startswith('[')):
                red_tech_count += 1
        
        # If more than 10 red technical lines, it's an annotation page
        if red_tech_count > 10:
            continue
        
        # Now extract fields from remaining pages
        # Fields are black text (not red technical codes), not bold headers, 
        # typically questions or prompts
        
        # Group lines that might be multi-line fields
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip red text (technical codes like [CSS0401A], [TYPE: ...])
            if line.non_black:
                i += 1
                continue
            
            # Skip very small text (< 6.5 points)
            if line.size < 6.5:
                i += 1
                continue
            
            # Skip answer options (Yes/No at specific x positions, typically right side)
            # These are at x > 450 typically
            if line.x0 > 450 and line.text.strip() in ['Yes', 'No', '0', '1', '2', '3', '4', '5']:
                i += 1
                continue
            
            # Skip row labels like "Row 1", "Row 2", etc.
            if line.text.strip().startswith('Row ') and line.bold:
                i += 1
                continue
            
            # Skip enumeration descriptions (answer option lists)
            # These start with \0.\, \1.\, etc. and are rating scale anchors
            text = line.text.strip()
            if text.startswith('\\') and '\\' in text[1:]:
                # This is a rating scale anchor like "\0.\ No physical damage..."
                i += 1
                continue
            
            # Skip lines that are just parenthetical examples or continuations
            # of rating scales (e.g., "sprains)", "body;", "reflexes;")
            if len(text) < 15 and (text.endswith(')') or text.endswith(';')):
                i += 1
                continue
            
            # Skip pure numeric or date-like entries
            if text.replace('/', '').replace('-', '').replace(':', '').replace('.', '').isdigit():
                i += 1
                continue
            
            # Check if this looks like a field label
            # Fields are typically questions (contain '?') or descriptive prompts
            # They are in black text, left-aligned (x0 < 300), size 7-10 points
            
            is_field = False
            
            # Questions ending with '?'
            if '?' in text and line.x0 < 300:
                is_field = True
            
            # Numbered field labels (e.g., "3. Active suicidal ideation...")
            # These are bold, start with a number followed by period
            if (line.bold and line.x0 < 100 and 7 <= line.size <= 10):
                # Check if starts with number followed by period
                if len(text) > 3 and text[0].isdigit() and text[1] == '.':
                    is_field = True
            
            # "If Yes, describe" prompts - these are field labels
            if text == 'If Yes, describe' and line.x0 < 100:
                is_field = True
            
            # Field labels like "Date of Attempt", "Actual Attempts"
            # These are bold, left-aligned, not too long
            if (line.bold and line.x0 < 100 and 7 <= line.size <= 10 and
                len(text) > 5 and len(text) < 60 and
                not text.startswith('Row ') and
                not text.startswith('\\')):
                # Must not be a rating scale description
                if not any(kw in text.lower() for kw in ['physical damage', 'lethality', 
                                                           'medical attention', 'hospitalization']):
                    is_field = True
            
            # "Potential Lethality:" field label (bold, with colon)
            if 'Potential Lethality:' in text and line.bold and line.x0 < 100:
                is_field = True
            
            # "Actual Lethality/Medical Damage:" field label (bold, with colon)
            if 'Actual Lethality' in text and 'Medical Damage' in text and line.bold and line.x0 < 100:
                is_field = True
            
            if is_field:
                # Collect continuation lines (same x position, next lines)
                field_text = text
                j = i + 1
                
                # For multi-line fields, collect continuation lines
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop at red text
                    if next_line.non_black:
                        break
                    
                    # Check if continuation (similar x, close y, same style)
                    if (abs(next_line.x0 - line.x0) < 10 and 
                        next_line.y0 - lines[j-1].y0 < 20 and
                        next_line.bold == line.bold):
                        
                        next_text = next_line.text.strip()
                        
                        # Stop at answer options
                        if next_text in ['Yes', 'No', 'Current', 'Former', 'Never']:
                            break
                        
                        # Stop at rating scale anchors
                        if next_text.startswith('\\'):
                            break
                        
                        # Stop at row labels
                        if next_text.startswith('Row '):
                            break
                        
                        # Stop at next field (starts with number and period)
                        if len(next_text) > 3 and next_text[0].isdigit() and next_text[1] == '.' and next_line.bold:
                            break
                        
                        # Add continuation
                        field_text += ' ' + next_text
                        j += 1
                    else:
                        break
                
                # Clean up field text
                field_text = ' '.join(field_text.split())
                
                # Final validation: must be substantive and not a rating anchor or instruction text
                if len(field_text) > 5 and form_name:
                    # Exclude rating scale anchors that slipped through
                    # These have patterns like "No physical damage" or "Minor physical damage"
                    if not (field_text.startswith('No physical') or 
                            field_text.startswith('Minor physical') or
                            field_text.startswith('Moderate physical') or
                            field_text.startswith('Moderately severe') or
                            field_text.startswith('Severe physical') or
                            'comatose' in field_text.lower() or
                            'third-degree burns' in field_text.lower() or
                            'extensive blood loss' in field_text.lower()):
                        
                        # Exclude long instructional text (not a field label)
                        # These are descriptions that explain the rating, not field labels
                        if not ('the following examples' in field_text.lower() and len(field_text) > 100):
                            
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