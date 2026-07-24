import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Detect Change History table pages - skip them
        has_change_history_title = any('Change History' in ln.text for ln in lines if ln.non_black and ln.size >= 12)
        if has_change_history_title:
            date_like = [ln for ln in lines if re.search(r'\d{1,2}-[A-Z][a-z]{2}-\d{4}', ln.text)]
            version_like = [ln for ln in lines if re.match(r'^\d+\.\d+\.\d+$', ln.text.strip())]
            if len(date_like) > 5 or len(version_like) > 5:
                continue
        
        # Detect blank/definition pages - only red annotations, no substantive black text
        red_annotations = [ln for ln in lines if ln.non_black and '#ff0000' in str(ln.text)]
        substantive_black = [ln for ln in lines if not ln.non_black and ln.size >= 7 and len(ln.text.strip()) > 5]
        if len(red_annotations) > 0 and len(substantive_black) < 3:
            continue
        
        # Extract form title: blue or black text, larger size (12-16pt), upper portion (y < 120)
        form_candidates = []
        for ln in lines:
            if 12 <= ln.size <= 16 and ln.y0 < 120:
                text = ln.text.strip()
                # Clean section numbering from form titles
                text = re.sub(r'^\d+\.\d+\.\s*', '', text)
                if not text.startswith('[') and len(text) > 3:
                    if not (text.isupper() and ' ' not in text and len(text) < 15):
                        form_candidates.append(text)
        
        if form_candidates:
            current_form = form_candidates[0]
        
        # Check for blue link enumeration pages (including dense ones)
        blue_field_candidates = [ln for ln in lines if ln.non_black and 
                                  ('#1d60a4' in str(ln.text) or '#2477cc' in str(ln.text)) and
                                  ln.size >= 11 and ln.y0 > 25]
        
        # Extract blue links if they look like field names (not TOC entries)
        if len(blue_field_candidates) > 10:
            # Check if these are field names vs TOC
            # TOC has very uniform vertical spacing and often dots/page numbers
            has_dots = sum(1 for ln in blue_field_candidates if '.' in ln.text and ln.text.count('.') > 3)
            
            # If not TOC-like, extract as fields
            if has_dots < len(blue_field_candidates) * 0.3:
                seen = set()
                for ln in blue_field_candidates:
                    text = ln.text.strip()
                    if len(text) > 5 and text not in seen:
                        # Remove section numbering prefix
                        text = re.sub(r'^\d+\.\d+\.\s*', '', text)
                        if text and text not in seen and not text.startswith('['):
                            results.append({
                                "form_name": current_form,
                                "field_name": text,
                                "page": page_num
                            })
                            seen.add(text)
                continue
        
        # Identify table headers (fields aligned horizontally)
        potential_headers = defaultdict(list)
        for ln in lines:
            if not ln.non_black and 7 <= ln.size <= 10 and ln.y0 > 80 and len(ln.text.strip()) > 2:
                y_bucket = int(ln.y0 / 5) * 5
                potential_headers[y_bucket].append(ln)
        
        header_rows = []
        for y_bucket, row_lines in potential_headers.items():
            if len(row_lines) >= 3:
                x_positions = sorted([ln.x0 for ln in row_lines])
                if x_positions[-1] - x_positions[0] > 200:
                    header_rows.append((y_bucket, row_lines))
        
        # Extract table headers with filtering
        if header_rows:
            seen = set()
            for y_bucket, row_lines in header_rows:
                # Check if this row contains section headers (not field names)
                row_texts = [ln.text.strip() for ln in row_lines]
                
                # Filter out pure section header rows
                section_header_markers = ['Suicidal Ideation', 'Intensity of Ideation', 
                                          'Lifetime', 'Past 3 Month', 'Sample', 'Timepoint',
                                          'Criteria', 'Status', 'Barcode']
                is_section_row = any(marker in row_texts for marker in section_header_markers)
                
                if not is_section_row:
                    for ln in sorted(row_lines, key=lambda l: l.x0):
                        text = ln.text.strip()
                        if len(text) >= 3 and not text.startswith('['):
                            # Exclude common answer options and furniture
                            if text not in ['Yes', 'No', 'N/A', 'NA', 'Date', 'Time', 'Row']:
                                # Exclude single words that repeat many times (column headers)
                                same_count = sum(1 for other in lines 
                                                if other.text.strip() == text 
                                                and not other.non_black)
                                if same_count < 5 or len(text) > 15:
                                    if text not in seen:
                                        results.append({
                                            "form_name": current_form,
                                            "field_name": text,
                                            "page": page_num
                                        })
                                        seen.add(text)
        
        # Check for table body cells (fields below headers, in columns)
        # For Chemistry/Urinalysis pages - extract field names from table cells
        table_cells = defaultdict(list)
        for ln in lines:
            if not ln.non_black and 7 <= ln.size <= 10 and ln.y0 > 120:
                x_bucket = int(ln.x0 / 40) * 40
                table_cells[x_bucket].append(ln)
        
        # Find leftmost column with many entries (likely field names)
        leftmost_cols = sorted([x for x in table_cells.keys() if 50 < x < 250])
        if leftmost_cols and len(table_cells[leftmost_cols[0]]) > 5:
            seen = set()
            for ln in table_cells[leftmost_cols[0]]:
                text = ln.text.strip()
                if len(text) >= 3 and not text.startswith('['):
                    # Exclude answer options and row labels
                    if text not in ['Yes', 'No', 'N/A', 'NA', 'Date', 'Time', 'Row', 'Met', 'Not Met']:
                        # Exclude if already extracted in headers
                        if text not in [r['field_name'] for r in results if r['page'] == page_num]:
                            # Check if this looks like a field name
                            if not (text.startswith('Row ') or text.endswith(' Row')):
                                if text not in seen:
                                    results.append({
                                        "form_name": current_form,
                                        "field_name": text,
                                        "page": page_num
                                    })
                                    seen.add(text)
        
        # Enumeration pages: many items in center column
        center_items = [ln for ln in lines if 150 < ln.x0 < 550 and 7.5 <= ln.size <= 10.5 
                        and not ln.non_black and len(ln.text.strip()) > 3]
        
        # Standard form pages: questions on left
        left_questions = [ln for ln in lines if ln.x0 < 180 and 7 <= ln.size <= 9.5 
                          and not ln.non_black and ln.y0 > 100]
        
        # Decide page type
        if len(center_items) > 8 and len(left_questions) < 5 and not header_rows:
            # Enumeration page - extract list items
            seen = set()
            for ln in center_items:
                text = ln.text.strip()
                
                if len(text) < 5 or ln.x0 > 500:
                    continue
                
                if len(text.split()) == 1 and len(text) < 12 and text[0].isupper():
                    continue
                    
                if text.isdigit() or re.match(r'^\d+[\.\)]?$', text):
                    continue
                    
                if text.startswith('['):
                    continue
                
                if len(text) > 60 and ('. ' in text or '; ' in text or text.endswith('.')):
                    continue
                
                if len(text.split()) <= 3 and ('/' in text or text.endswith(' PK')):
                    similar_x = [l for l in center_items if abs(l.x0 - ln.x0) < 20 and l.text.strip() != text]
                    if len(similar_x) < 3:
                        continue
                
                if text not in seen:
                    results.append({
                        "form_name": current_form,
                        "field_name": text,
                        "page": page_num
                    })
                    seen.add(text)
            continue
        
        # Standard form pages - extract questions
        seen_fields = set()
        i = 0
        
        while i < len(lines):
            ln = lines[i]
            text = ln.text.strip()
            
            # Structural field detection
            if not (not ln.non_black and ln.x0 < 180 and 6.5 <= ln.size <= 9.5 and ln.y0 > 100):
                i += 1
                continue
            
            if len(text) < 3:
                i += 1
                continue
            if text.startswith('['):
                i += 1
                continue
            if text.startswith('Row '):
                i += 1
                continue
            if any(marker in text for marker in ['TYPE:', 'VISIBILITY:', 'OID:', 'LAYOUT:', 'CODE:']):
                i += 1
                continue
            if ln.x0 > 450:
                i += 1
                continue
            
            # Build multi-line field
            field_parts = [text]
            j = i + 1
            
            while j < len(lines):
                next_ln = lines[j]
                next_text = next_ln.text.strip()
                
                if not next_ln.non_black and \
                   abs(next_ln.x0 - ln.x0) < 50 and \
                   next_ln.y0 - lines[j-1].y0 < 20 and \
                   abs(next_ln.size - ln.size) < 2 and \
                   not next_text.startswith('['):
                    
                    if next_ln.y0 - lines[j-1].y0 > 15 and len(next_text) > 20:
                        break
                    
                    field_parts.append(next_text)
                    j += 1
                else:
                    break
            
            field_text = ' '.join(field_parts).strip()
            
            if len(field_text) < 4:
                i = j
                continue
            
            if re.match(r'^\d+[\.\)]?$', field_text):
                i = j
                continue
            
            words = field_text.split()
            if len(words) == 1 and len(field_text) < 8 and field_text[0].isupper():
                i = j
                continue
            
            if len(field_text) > 80 and field_text.count('.') >= 2:
                i = j
                continue
            
            instruction_starters = ['Ask questions', 'If both are', 'If any answers', 'If the answer', 
                                     'Subject endorses', 'Have you', 'The following', 'Collect vital']
            if any(field_text.startswith(starter) for starter in instruction_starters):
                i = j
                continue
            
            same_text_count = sum(1 for other_ln in lines 
                                  if other_ln.text.strip() == field_text 
                                  and not other_ln.non_black 
                                  and abs(other_ln.x0 - ln.x0) < 100)
            
            if same_text_count >= 3 and len(field_text) < 15:
                i = j
                continue
            
            if field_text not in seen_fields:
                results.append({
                    "form_name": current_form,
                    "field_name": field_text,
                    "page": page_num
                })
                seen_fields.add(field_text)
            
            i = j
    
    # Deduplicate consecutive identical records
    deduplicated = []
    prev = None
    for rec in results:
        if rec != prev:
            deduplicated.append(rec)
            prev = rec
    
    return deduplicated
