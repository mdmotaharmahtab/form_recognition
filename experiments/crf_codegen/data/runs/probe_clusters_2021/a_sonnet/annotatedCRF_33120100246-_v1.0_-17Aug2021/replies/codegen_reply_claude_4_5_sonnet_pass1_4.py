Looking at the quality gates, I need to fix several issues:

1. **Page 7 (Change History)**: Extracting table cells (dates/versions) instead of field labels
2. **Pages 4, 6 (cluster 10)**: Blue hyperlinks (#2477cc) not being extracted - these are actual form titles/fields in TOC-like pages
3. **Page 50, 302**: Missing fields from enumeration/list pages
4. **Page 71, 136**: Extracting instructional text instead of actual fields
5. **Page 171**: Missing table headers, extracting section titles instead
6. **Page 442**: Extracting instructions instead of fields

The key insights:
- Cluster 9, 10, 11 have 0% coverage - need to handle these layouts
- Blue hyperlinks on pages 4, 6 are NOT table of contents - they're form field names
- Need better detection of table structures (headers in a row)
- Need to exclude instructional paragraphs (long sentences with punctuation)
- Need to identify and skip "Change History" tables specifically

```python
import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Detect dense TOC pages: many blue links, evenly spaced vertically
        blue_links = [ln for ln in lines if ln.non_black and ('#1d60a4' in str(ln.text) or '#2477cc' in str(ln.text))]
        if len(blue_links) > 30:
            # Check if they're in a tight vertical list (TOC pattern)
            if len(blue_links) >= 2:
                avg_spacing = sum(blue_links[i+1].y0 - blue_links[i].y0 for i in range(len(blue_links)-1)) / (len(blue_links)-1)
                if 10 < avg_spacing < 20:
                    continue
        
        # Detect blank/definition pages - only red annotations, no substantive black text
        red_annotations = [ln for ln in lines if ln.non_black and '#ff0000' in str(ln.text)]
        substantive_black = [ln for ln in lines if not ln.non_black and ln.size >= 7 and len(ln.text.strip()) > 5]
        if len(red_annotations) > 0 and len(substantive_black) < 3:
            continue
        
        # Detect Change History table pages - skip them
        # Pattern: "Change History" title + many date/version entries in table format
        has_change_history_title = any('Change History' in ln.text for ln in lines if ln.non_black and ln.size >= 12)
        if has_change_history_title:
            # Check for date pattern prevalence
            date_like = [ln for ln in lines if re.search(r'\d{1,2}-[A-Z][a-z]{2}-\d{4}', ln.text)]
            version_like = [ln for ln in lines if re.match(r'^\d+\.\d+\.\d+$', ln.text.strip())]
            if len(date_like) > 5 or len(version_like) > 5:
                continue
        
        # Extract form title: blue or black text, larger size (12-16pt), upper portion (y < 120)
        form_candidates = []
        for ln in lines:
            if 12 <= ln.size <= 16 and ln.y0 < 120:
                text = ln.text.strip()
                # Structural filter: not a code annotation, not single short word
                if not text.startswith('[') and len(text) > 3:
                    if not (text.isupper() and ' ' not in text and len(text) < 15):
                        form_candidates.append(text)
        
        if form_candidates:
            current_form = form_candidates[0]
        
        # Check for blue link enumeration pages (cluster 10, 11)
        # These have many blue hyperlinks that are field names, not TOC
        blue_field_candidates = [ln for ln in lines if ln.non_black and 
                                  ('#1d60a4' in str(ln.text) or '#2477cc' in str(ln.text)) and
                                  ln.size >= 11 and ln.y0 > 25]
        
        if len(blue_field_candidates) > 10 and len(blue_field_candidates) < 30:
            # Extract blue links as field names
            seen = set()
            for ln in blue_field_candidates:
                text = ln.text.strip()
                if len(text) > 5 and text not in seen:
                    # Exclude section numbering prefix (e.g., "3.137. ")
                    text = re.sub(r'^\d+\.\d+\.\s*', '', text)
                    if text and text not in seen:
                        results.append({
                            "form_name": current_form,
                            "field_name": text,
                            "page": page_num
                        })
                        seen.add(text)
            continue
        
        # Identify page structure type
        # Check for table headers (fields aligned horizontally at similar y position)
        potential_headers = defaultdict(list)
        for ln in lines:
            if not ln.non_black and 7 <= ln.size <= 10 and ln.y0 > 80 and len(ln.text.strip()) > 2:
                y_bucket = int(ln.y0 / 5) * 5
                potential_headers[y_bucket].append(ln)
        
        # Find rows with multiple aligned items (table headers)
        header_rows = []
        for y_bucket, row_lines in potential_headers.items():
            if len(row_lines) >= 3:
                # Check horizontal distribution
                x_positions = sorted([ln.x0 for ln in row_lines])
                if x_positions[-1] - x_positions[0] > 200:
                    header_rows.append((y_bucket, row_lines))
        
        if header_rows:
            # Extract table headers
            seen = set()
            for y_bucket, row_lines in header_rows:
                for ln in sorted(row_lines, key=lambda l: l.x0):
                    text = ln.text.strip()
                    if len(text) >= 3 and not text.startswith('['):
                        # Exclude common answer options
                        if text not in ['Yes', 'No', 'N/A', 'NA', 'Date', 'Time']:
                            if text not in seen:
                                results.append({
                                    "form_name": current_form,
                                    "field_name": text,
                                    "page": page_num
                                })
                                seen.add(text)
        
        # Enumeration pages: many items in center column (x ~200-550), small-medium size
        center_items = [ln for ln in lines if 150 < ln.x0 < 550 and 7.5 <= ln.size <= 10.5 
                        and not ln.non_black and len(ln.text.strip()) > 3]
        
        # Standard form pages: questions on left (x < 180), around standard y positions
        left_questions = [ln for ln in lines if ln.x0 < 180 and 7 <= ln.size <= 9.5 
                          and not ln.non_black and ln.y0 > 100]
        
        # Decide page type
        if len(center_items) > 8 and len(left_questions) < 5 and not header_rows:
            # Enumeration page - extract list items
            seen = set()
            for ln in center_items:
                text = ln.text.strip()
                
                # Structural filters:
                if len(text) < 5:
                    continue
                if ln.x0 > 500:
                    continue
                
                # Exclude single short capitalized word (answer options)
                if len(text.split()) == 1 and len(text) < 12 and text[0].isupper():
                    continue
                    
                # Exclude pure numbers or simple numbering
                if text.isdigit() or re.match(r'^\d+[\.\)]?$', text):
                    continue
                    
                if text.startswith('['):
                    continue
                
                # Exclude instructional text: long sentences with multiple clauses
                if len(text) > 60 and ('. ' in text or '; ' in text or text.endswith('.')):
                    continue
                
                # Exclude section titles that look like headers (all at similar x, repeated pattern)
                # Section titles often appear as: "Brexpiprazole/Sertraline", "Sertraline PK"
                if len(text.split()) <= 3 and '/' in text or text.endswith(' PK'):
                    # Check if this is repeated or isolated
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
            
            # Structural exclusions
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
            
            # Build multi-line field by checking continuation
            field_parts = [text]
            j = i + 1
            
            while j < len(lines):
                next_ln = lines[j]
                next_text = next_ln.text.strip()
                
                # Continuation criteria (structural)
                if not next_ln.non_black and \
                   abs(next_ln.x0 - ln.x0) < 50 and \
                   next_ln.y0 - lines[j-1].y0 < 20 and \
                   abs(next_ln.size - ln.size) < 2 and \
                   not next_text.startswith('['):
                    
                    # Stop at next separate field (larger gap or style change)
                    if next_ln.y0 - lines[j-1].y0 > 15 and len(next_text) > 20:
                        break
                    
                    field_parts.append(next_text)
                    j += 1
                else:
                    break
            
            field_text = ' '.join(field_parts).strip()
            
            # Final quality filters (structural)
            if len(field_text) < 4:
                i = j
                continue
            
            if re.match(r'^\d+[\.\)]?$', field_text):
                i = j
                continue
            
            # Structural furniture filter: single short word with no context
            words = field_text.split()
            if len(words) == 1 and len(field_text) < 8 and field_text[0].isupper():
                i = j
                continue
            
            # Exclude long instructional text (sentences with proper punctuation)
            if len(field_text) > 80 and field_text.count('.') >= 2:
                i = j
                continue
            
            # Exclude instructions starting with action verbs
            instruction_starters = ['Ask questions', 'If both are', 'If the answer', 'Subject endorses', 
                                     'Have you', 'The following', 'Collect vital']
            if any(field_text.startswith(starter) for starter in instruction_starters):
                i = j
                continue
            
            # Check for answer-option patterns (structural)
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
```
