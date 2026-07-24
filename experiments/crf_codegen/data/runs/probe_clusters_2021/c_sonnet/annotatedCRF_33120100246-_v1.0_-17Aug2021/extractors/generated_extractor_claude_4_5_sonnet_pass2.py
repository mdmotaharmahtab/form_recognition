import re

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Detect form title: large blue/colored text near top of page
        form_candidates = [
            ln for ln in lines 
            if ln.size >= 13.0 and ln.non_black and ln.y0 < 200
        ]
        
        if form_candidates:
            for candidate in form_candidates:
                text = candidate.text.strip()
                # Skip TOC entries (numeric prefixes)
                if re.match(r'^\d+\.', text):
                    continue
                # Use substantial titles
                if len(text) > 5 and not text.isupper():
                    current_form = text
                    break
        
        # Extract fields
        i = 0
        while i < len(lines):
            ln = lines[i]
            
            # Skip red/colored annotations (technical metadata)
            if ln.non_black and ln.size < 10:
                i += 1
                continue
            
            # Skip tiny text (page numbers, footers)
            if ln.size < 7.5:
                i += 1
                continue
            
            text = ln.text.strip()
            
            if not text:
                i += 1
                continue
            
            # Structural filters (no literal blocklists)
            
            # Skip answer options: short text, right of x=200, or isolated single words
            if len(text) <= 10 and (ln.x0 > 200 or text in ["Yes", "No", "N/A", "Met", "Not Met"]):
                i += 1
                continue
            
            # Skip bracketed codes/technical markers
            if text.startswith("["):
                i += 1
                continue
            
            # Skip table headers: short caps at top of tables
            if len(text) < 20 and text[0].isupper() and "/" in text:
                i += 1
                continue
            
            # Skip row labels without content
            if re.match(r'^Row\s+\d+$', text, re.IGNORECASE):
                i += 1
                continue
            
            # Potential field label: black text, reasonable size, left-aligned
            if not ln.non_black and ln.size >= 7.5 and ln.x0 < 150:
                # Accumulate multi-line labels with STRICT limits
                label_parts = [text]
                j = i + 1
                max_continuations = 5  # Increased to catch wrapped field names
                continuation_count = 0
                
                while j < len(lines) and continuation_count < max_continuations:
                    next_ln = lines[j]
                    
                    # Stop at colored text
                    if next_ln.non_black and next_ln.size < 10:
                        break
                    
                    # Stop at answer options (right side of page)
                    if next_ln.x0 > 200:
                        break
                    
                    # Stop at bracketed codes
                    if next_ln.text.strip().startswith("["):
                        break
                    
                    # Stop at blank lines
                    if not next_ln.text.strip():
                        break
                    
                    # Continuation: similar x (within 30px), close y (within 15px), similar size
                    y_gap = next_ln.y0 - lines[j-1].y0
                    x_similar = abs(next_ln.x0 - ln.x0) < 30
                    size_similar = abs(next_ln.size - ln.size) < 2.0
                    
                    if (x_similar and 0 < y_gap < 15 and size_similar and
                        not next_ln.non_black and next_ln.size >= 7.5):
                        
                        next_text = next_ln.text.strip()
                        
                        # Stop at end punctuation followed by new sentence (but allow colon+newline for field names)
                        if label_parts[-1].rstrip().endswith(('.', ';')) and next_text[0].isupper():
                            break
                        
                        label_parts.append(next_text)
                        continuation_count += 1
                        j += 1
                    else:
                        break
                
                full_label = " ".join(label_parts)
                
                # Structural filters for non-fields
                
                # Skip very short fragments
                if len(full_label) < 10:
                    i = j
                    continue
                
                # Skip criterion-style text: ENHANCED filter for numbered list items
                # Matches: \1.\ or \1.\ followed by capital letter, or just digit-dot at start
                if re.match(r'^\\?\d+\\.\\?\s+[A-Z]', full_label):
                    i = j
                    continue
                
                # NEW: Skip isolated criterion numbers at line start (even without backslashes in continuation)
                if re.match(r'^\d+\.\s+[A-Z][a-z]+', full_label):
                    i = j
                    continue
                
                # Skip instructions: imperative verbs at start
                if re.match(r'^(Please|If\s+(Yes|No|any)|Go\s+to|Enter|Select|Examples?|EXCLUDE)', full_label, re.IGNORECASE):
                    i = j
                    continue
                
                # Skip conditional statements (If/When followed by clause)
                if re.match(r'^(If|When)\s+\w+.*,', full_label, re.IGNORECASE):
                    i = j
                    continue
                
                # Skip parenthetical notes (start with open paren)
                if full_label.startswith("("):
                    i = j
                    continue
                
                # Skip standalone numbers (criterion numbers without text)
                if re.match(r'^\\?\d+\\.?\\?$', full_label):
                    i = j
                    continue
                
                # Skip if it looks like body text: multiple sentences or very long
                sentence_count = full_label.count('. ') + full_label.count('; ')
                if sentence_count > 2 or len(full_label) > 200:
                    i = j
                    continue
                
                # Skip if it starts with "Row N" pattern followed by criterion text
                if re.match(r'^Row\s+\d+\s+\\?\d+\\.', full_label):
                    i = j
                    continue
                
                # Skip if it contains multiple independent clauses (long instructional text)
                comma_count = full_label.count(',')
                if comma_count >= 3 and len(full_label) > 150:
                    i = j
                    continue
                
                # NEW: Skip generic section headers (short text ending with colon, NO numbered suffix before colon)
                # But ALLOW field names with numbered suffixes like "abnormal assay # 1:"
                if (len(full_label) < 60 and full_label.rstrip().endswith(':') and j == i + 1 and
                    not re.search(r'#\s*\d+\s*:$', full_label)):
                    i = j
                    continue
                
                # Valid field
                if current_form:
                    records.append({
                        "form_name": current_form,
                        "field_name": full_label,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return records
