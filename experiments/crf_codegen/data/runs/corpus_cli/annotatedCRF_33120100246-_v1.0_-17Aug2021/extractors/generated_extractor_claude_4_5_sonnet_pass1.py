import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        if not lines:
            continue
        
        page_num = page_idx + 1
        
        # Skip TOC pages: many colored links, minimal black text
        colored_links = [ln for ln in lines if ln.non_black and ln.x0 < 500]
        black_text = [ln for ln in lines if not ln.non_black and ln.y0 > 100 and ln.size >= 7]
        
        if len(colored_links) > 15 and len(black_text) < 5:
            continue
        
        # Skip annotation-only pages (red text only)
        non_red_lines = [ln for ln in lines 
                        if not ('#ff0000' in str(getattr(ln, 'color', '')).lower() or
                               'rgb(255' in str(getattr(ln, 'color', '')).lower())]
        if len(non_red_lines) < 3:
            continue
        
        # Extract form title: large colored text near top
        form_title = None
        for ln in lines:
            if ln.y0 < 100 and ln.size >= 12.5 and ln.non_black:
                text = ln.text.strip()
                text = re.sub(r'^\d+(\.\d+)*\s*', '', text)
                if len(text) > 10:
                    form_title = text
                    break
        
        if form_title:
            current_form = form_title
        
        # Filter content lines: exclude red annotations, page numbers, very small text
        content_lines = [ln for ln in lines 
                        if not ('#ff0000' in str(getattr(ln, 'color', '')).lower() or
                                'rgb(255' in str(getattr(ln, 'color', '')).lower())
                        and ln.size >= 6.5
                        and ln.y0 > 30
                        and ln.y0 < 750]
        
        # Detect tabular data regions: rows with 3+ short aligned items
        tabular_rows = set()
        for ln in content_lines:
            if len(ln.text.strip()) < 40 and ln.x0 < 500:
                # Count horizontal neighbors at same y
                neighbors = [other for other in content_lines 
                           if abs(other.y0 - ln.y0) < 5 
                           and abs(other.x0 - ln.x0) > 40
                           and len(other.text.strip()) < 50]
                if len(neighbors) >= 2:
                    tabular_rows.add(round(ln.y0))
        
        # Detect column header rows: multiple bold/similar items in horizontal alignment
        header_rows = set()
        for ln in content_lines:
            if ln.bold and ln.size >= 8 and len(ln.text.strip()) < 50:
                neighbors = sum(1 for other in content_lines 
                              if abs(other.y0 - ln.y0) < 5 
                              and abs(other.x0 - ln.x0) > 50
                              and len(other.text.strip()) < 50)
                if neighbors >= 2:
                    header_rows.add(round(ln.y0))
        
        # Collect field candidates
        field_candidates = []
        i = 0
        
        while i < len(content_lines):
            ln = content_lines[i]
            
            # Field label criteria: black text in left or label area
            if not ln.non_black and ln.x0 < 350 and 7 <= ln.size <= 11:
                text = ln.text.strip()
                
                # Skip empty
                if not text:
                    i += 1
                    continue
                
                # Skip if in a detected tabular row (like Change History table cells)
                if any(abs(ln.y0 - tr) < 5 for tr in tabular_rows):
                    i += 1
                    continue
                
                # Skip if in a detected column header row
                if any(abs(ln.y0 - hr) < 5 for hr in header_rows):
                    i += 1
                    continue
                
                # Skip very short fragments (likely table cells or answers)
                if len(text) < 3:
                    i += 1
                    continue
                
                # Skip pure numbers, dates, version numbers
                if re.match(r'^(\d{1,2}[-/]\w{3,4}[-/]\d{2,4}|\d+[\.\:]\d*|\d+\.\d+\.\d+|\d+)$', text):
                    i += 1
                    continue
                
                # Skip names (2-3 capitalized words, no punctuation at end)
                if re.match(r'^[A-Z][a-z]+(\s+[A-Z][a-z]+){1,2}$', text) and len(text) < 35:
                    i += 1
                    continue
                
                # Skip in right area unless it's substantial (likely answer options)
                if ln.x0 > 350 and len(text) < 30:
                    i += 1
                    continue
                
                # Detect instruction paragraphs: very long, sentence-like
                # They often span > 100 chars and have instruction verbs
                is_instruction = False
                if len(text) > 90:
                    # Check for instructional patterns
                    if re.match(r'^(The following|Ask about|If both|If the answer|Collect|Subject endorses|Row \d+)', text):
                        is_instruction = True
                    # Or very long continuous text from far left
                    elif ln.x0 < 70:
                        # Look ahead for continuation
                        next_lines = [content_lines[j].text.strip() 
                                     for j in range(i+1, min(i+3, len(content_lines)))
                                     if not content_lines[j].non_black 
                                     and abs(content_lines[j].x0 - ln.x0) < 40]
                        total_text = text + ' ' + ' '.join(next_lines)
                        if len(total_text) > 140:
                            is_instruction = True
                
                if is_instruction:
                    i += 1
                    continue
                
                # Skip "Row N" labels (table structure)
                if re.match(r'^Row\s+\d+$', text):
                    i += 1
                    continue
                
                # Skip partial sentence fragments ending without punctuation or colon
                # (like "position for 3 minutes" - part of instruction)
                if ln.x0 < 100 and len(text) > 15 and len(text) < 60:
                    if not (text.endswith(':') or text.endswith('?') or 
                           re.search(r'[A-Z][a-z]+\s+[A-Z]', text) or  # Has capitals (likely field name)
                           re.match(r'^[A-Z]', text)):  # Starts with capital
                        # Check if looks like fragment (all lowercase after first word)
                        words = text.split()
                        if len(words) > 2 and all(w[0].islower() for w in words[1:] if len(w) > 0):
                            i += 1
                            continue
                
                # Collect multi-line label (wrapped text)
                label_lines = [text]
                j = i + 1
                
                while j < len(content_lines):
                    next_ln = content_lines[j]
                    
                    # Continuation: similar x, close y, black, medium size
                    if (not next_ln.non_black and 
                        abs(next_ln.x0 - ln.x0) < 40 and 
                        0 < next_ln.y0 - ln.y0 < 40 and
                        7 <= next_ln.size <= 11):
                        
                        next_text = next_ln.text.strip()
                        
                        # Stop at empty or bracketed code
                        if not next_text or next_text[0] == '[':
                            break
                        
                        # Stop if moved far right (answer column)
                        if next_ln.x0 > 350:
                            break
                        
                        # Stop at tabular or header rows
                        if any(abs(next_ln.y0 - tr) < 5 for tr in tabular_rows):
                            break
                        if any(abs(next_ln.y0 - hr) < 5 for hr in header_rows):
                            break
                        
                        # Stop at short answer-like text
                        if len(next_text) < 15:
                            # Common answer patterns
                            if re.match(r'^(Yes|No|N/?A|Met|Not|Scan|Positive|Negative|Collected|done|Status|Sample)$', 
                                      next_text, re.IGNORECASE):
                                break
                        
                        # Stop at instruction continuations (very long)
                        if len(next_text) > 90:
                            break
                        
                        label_lines.append(next_text)
                        ln = next_ln
                        j += 1
                    else:
                        break
                
                field_name = ' '.join(label_lines).strip()
                
                # Final validation
                if len(field_name) >= 3:
                    # Exclude pure numbers
                    if re.match(r'^\d+$', field_name):
                        i = j
                        continue
                    
                    # Exclude machine codes
                    if re.search(r'\[TYPE:', field_name) or re.search(r'\[VISIBILITY:', field_name):
                        i = j
                        continue
                    
                    # Exclude version stamps
                    if re.match(r'^Version Number', field_name):
                        i = j
                        continue
                    
                    # Exclude intensity/description headers that span multiple words but are structural
                    if field_name in ('Intensity of Ideation', 'Description of Ideation'):
                        # Check if this is actually a standalone header vs field
                        # If no colon and in a section with many "Row N" entries, skip
                        nearby_rows = sum(1 for other in content_lines
                                        if abs(other.y0 - ln.y0) < 100
                                        and re.match(r'^Row\s+\d+', other.text.strip()))
                        if nearby_rows > 3:
                            i = j
                            continue
                    
                    # Single-word bold headers in multi-column layout
                    if len(field_name.split()) == 1 and len(field_name) < 15:
                        if ln.bold or ln.size >= 9.5:
                            # Check for horizontal siblings
                            siblings = sum(1 for other in content_lines 
                                          if abs(other.y0 - ln.y0) < 5 
                                          and abs(other.x0 - ln.x0) > 50
                                          and len(other.text.strip()) < 30)
                            if siblings >= 2:
                                i = j
                                continue
                    
                    field_candidates.append(field_name)
                
                i = j
            else:
                i += 1
        
        # Add to results with deduplication
        seen = set()
        for field_name in field_candidates:
            key = (current_form, field_name)
            if key not in seen:
                seen.add(key)
                results.append({
                    "form_name": current_form,
                    "field_name": field_name,
                    "page": page_num
                })
    
    return results
