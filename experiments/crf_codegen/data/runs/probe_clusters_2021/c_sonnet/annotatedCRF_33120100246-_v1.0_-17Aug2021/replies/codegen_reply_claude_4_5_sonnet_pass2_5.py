I'll analyze the problems and fix the extraction program. The main issue is that pages 83-85 contain numbered criterion text (inclusion/exclusion criteria) that's being extracted as fields.

Let me examine the patterns in the reported false positives:

1. They start with `\1.\`, `\2.\`, etc. (escaped criterion numbers)
2. They're long, multi-sentence text (body content, not field labels)
3. They contain complex clauses and descriptive text

The current filters are catching some but missing these longer criterion paragraphs. I need to strengthen the structural filters.

```python
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
                max_continuations = 5
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
                
                # ENHANCED: Skip criterion-style text with escaped or plain numbered markers
                # Matches: \1.\ or \2.\ or 1.\ at start, optionally followed by capital letter or text
                if re.match(r'^\\?\d+\\.\\?\s*[A-Z]', full_label):
                    i = j
                    continue
                
                # Skip isolated criterion numbers at line start
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
                
                # Skip standalone numbers
                if re.match(r'^\\?\d+\\.?\\?$', full_label):
                    i = j
                    continue
                
                # ENHANCED: Skip body text - more aggressive on sentence detection
                # Count sentence endings more broadly (period, semicolon followed by space/capital)
                sentence_endings = len(re.findall(r'[.;]\s+[A-Z]', full_label))
                # Also count terminal punctuation
                if full_label.rstrip().endswith(('.', ';')):
                    sentence_endings += 1
                
                # Body text: multiple complete sentences OR very long text
                if sentence_endings >= 2 or len(full_label) > 180:
                    i = j
                    continue
                
                # Skip if it starts with "Row N" pattern followed by criterion
                if re.match(r'^Row\s+\d+\s+\\?\d+\\.', full_label):
                    i = j
                    continue
                
                # Skip long instructional text with multiple clauses
                comma_count = full_label.count(',')
                if comma_count >= 3 and len(full_label) > 150:
                    i = j
                    continue
                
                # NEW: Skip text with parenthetical abbreviations mid-sentence (common in criteria)
                # e.g., "Diagnostic and Statistical Manual (DSM)" or "Body mass index (BMI)"
                if re.search(r'\([A-Z]{2,}\)', full_label) and len(full_label) > 100:
                    i = j
                    continue
                
                # NEW: Skip text with nested subclauses (a), b), c) patterns - criterion structure)
                if re.search(r'\b[a-d]\)', full_label):
                    i = j
                    continue
                
                # NEW: Skip text containing common criterion words when length exceeds field threshold
                criterion_patterns = [
                    r'\b(determined by|inclusive|at the time of|at least)\b',
                    r'\b(subjects? (who|with|between)|male or female)\b',
                    r'\b(exclusion|inclusion|criteria?)\b',
                ]
                if len(full_label) > 120:
                    for pattern in criterion_patterns:
                        if re.search(pattern, full_label, re.IGNORECASE):
                            i = j
                            continue
                
                # Skip generic section headers (short text ending with colon, no numbered suffix)
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
```
