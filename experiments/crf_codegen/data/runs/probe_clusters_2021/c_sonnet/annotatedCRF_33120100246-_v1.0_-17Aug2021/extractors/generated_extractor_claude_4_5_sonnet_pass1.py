import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find the form title: large blue/colored text near top
        form_title = None
        for line in lines:
            # Accept both large titles AND numbered TOC-style entries (e.g., "3.137. Form Name")
            if line.non_black and line.y0 < 250 and len(line.text.strip()) > 0:
                text = line.text.strip()
                
                # TOC-style numbered entry (form title)
                if re.match(r'^\d+\.\d+\.', text):
                    # Extract the title after the number
                    match = re.match(r'^\d+\.\d+\.\s*(.+)$', text)
                    if match:
                        form_title = match.group(1).strip()
                        break
                
                # Regular large title
                elif line.size >= 13.0 and not text.startswith('['):
                    form_title = text
                    break
        
        if form_title:
            current_form = form_title
        
        # Skip pages with ONLY machine codes (no regular content)
        machine_code_lines = [l for l in lines if '[TYPE:' in l.text or '[VISIBILITY:' in l.text or (l.text.startswith('[') and ']' in l.text)]
        non_machine_lines = [l for l in lines if not l.text.startswith('[') and not '[TYPE:' in l.text and not '[VISIBILITY:' in l.text and len(l.text.strip()) > 0]
        # Pages with only machine codes and minimal black text
        if len(machine_code_lines) > 0 and len(non_machine_lines) <= 2 and not any(l.size >= 8 for l in non_machine_lines):
            continue
        
        # Identify answer option positions (Yes/No typically at x > 400)
        answer_x_positions = set()
        for line in lines:
            if line.text.strip() in ['Yes', 'No', 'Scan', 'Collected', 'Not'] and line.x0 > 350:
                answer_x_positions.add(round(line.x0 / 50) * 50)
        
        # Identify if this is a table-dense page (Schedule of Assessments style)
        small_items = [l for l in lines if l.size < 9 and len(l.text.strip()) < 25 and not l.text.startswith('[')]
        horizontal_spread = []
        for item in small_items:
            if item.x0 < 400:
                horizontal_spread.append(item.x0)
        unique_x_positions = len(set(round(x / 30) * 30 for x in horizontal_spread))
        is_table_page = unique_x_positions > 8 and len(small_items) > 15
        
        # Detect table column headers zone (top 150px on dense tables)
        # Look for items that appear to be aligned in columns
        if is_table_page:
            top_items = [l for l in lines if l.y0 < 150 and not l.text.startswith('[') and len(l.text.strip()) > 0]
            # Items in the same horizontal band (within 20px Y) at different X positions
            column_header_y_bands = {}
            for item in top_items:
                y_band = round(item.y0 / 20) * 20
                if y_band not in column_header_y_bands:
                    column_header_y_bands[y_band] = []
                column_header_y_bands[y_band].append(item.x0)
            
            # If we have bands with multiple X positions, those are likely column headers
            table_has_column_headers = any(len(set(round(x / 50) * 50 for x in xlist)) > 2 for xlist in column_header_y_bands.values())
        else:
            table_has_column_headers = False
        
        # Extract field candidates
        field_candidates = []
        
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty and machine codes
            if not text or text.startswith('[') or ']' in text and '[' in text:
                continue
            
            # Field labels: black text, left side, below title
            # Expanded size range to catch small fonts
            if (line.size <= 11.0 and 
                not line.non_black and 
                line.x0 < 150 and
                line.y0 > 100):
                
                # Structural filters:
                
                # 1. Skip if in answer option column
                in_answer_column = any(abs(line.x0 - ax) < 40 for ax in answer_x_positions)
                if in_answer_column:
                    continue
                
                # 2. Skip pure numbers or parenthetical numbers
                if re.match(r'^[\d\(\)\s]+$', text):
                    continue
                
                # 3. Skip single-character items
                if len(text) < 2:
                    continue
                
                # 4. On table-dense pages with column headers, skip items that look like headers
                if is_table_page and table_has_column_headers:
                    # Items in the top zone, very short, spread horizontally
                    if line.y0 < 150:
                        # Check if aligned with other items at similar Y but different X
                        same_y_items = [l for l in lines if abs(l.y0 - line.y0) < 10 and abs(l.x0 - line.x0) > 60]
                        if len(same_y_items) > 1 and len(text.split()) <= 3:
                            continue
                    
                    # Skip single-word items that are very short in high table zones
                    if len(text) < 20 and ' ' not in text and line.y0 < 200:
                        continue
                
                # 5. Skip common instruction starters (but allow "If not collected, reason:")
                lower_text = text.lower()
                if (lower_text.startswith('please ') or
                    lower_text.startswith('when ')):
                    continue
                
                # Allow "If..." only when it ends with colon (a field label pattern)
                if lower_text.startswith('if ') and not text.endswith(':'):
                    continue
                
                # 6. Skip if it's a unit/scale anchor (single word, far left, very small)
                if len(text.split()) == 1 and line.x0 < 55 and line.size < 8:
                    continue
                
                # 7. Skip prose fragments, but more carefully
                if (text[0].islower() and 
                    ':' not in text and 
                    '?' not in text and
                    not text.endswith(':') and
                    len(text) > 20 and
                    not text.endswith(',')):  # Allow ending with comma (might be part of list)
                    continue
                
                # Check for multi-line continuation
                should_continue = False
                if field_candidates:
                    prev = field_candidates[-1]
                    y_threshold = 18 if line.size < 8.5 else 15
                    if (abs(line.y0 - prev['y1']) < y_threshold and
                        abs(line.x0 - prev['x0']) < 35):
                        # Check if this looks like a continuation
                        next_is_code = (i + 1 < len(lines) and 
                                       (lines[i + 1].text.strip().startswith('[') or 
                                        lines[i + 1].non_black))
                        looks_like_new_field = (text[0].isupper() and 
                                              (prev['text'].endswith(':') or 
                                               prev['text'].endswith('?') or
                                               len(prev['text']) > 40))
                        if not next_is_code and not looks_like_new_field:
                            should_continue = True
                
                if should_continue:
                    field_candidates[-1]['text'] += ' ' + text
                    field_candidates[-1]['y1'] = line.y1
                else:
                    field_candidates.append({
                        'text': text,
                        'x0': line.x0,
                        'y0': line.y0,
                        'y1': line.y1,
                        'size': line.size,
                        'bold': line.bold
                    })
        
        # Add valid fields to results
        for candidate in field_candidates:
            text = candidate['text'].strip()
            
            # Skip very short text (but allow 2-char codes like "ID")
            if len(text) < 2:
                continue
            
            # Skip if it's clearly descriptive prose (very long, no question mark or colon)
            if len(text) > 120 and '?' not in text and ':' not in text:
                continue
            
            # Final structural checks
            words = text.split()
            
            # Skip obvious non-fields: lowercase start, no markers, medium-long prose
            if (len(words) > 2 and 
                text[0].islower() and 
                not any(marker in text for marker in [':', '?', '#']) and
                len(text) > 20):
                continue
            
            # Add the field
            if current_form or text:
                results.append({
                    "form_name": current_form,
                    "field_name": text,
                    "page": page_num
                })
    
    # Deduplicate consecutive identical entries
    deduplicated = []
    prev = None
    for r in results:
        if prev != (r['form_name'], r['field_name'], r['page']):
            deduplicated.append(r)
            prev = (r['form_name'], r['field_name'], r['page'])
    
    return deduplicated
