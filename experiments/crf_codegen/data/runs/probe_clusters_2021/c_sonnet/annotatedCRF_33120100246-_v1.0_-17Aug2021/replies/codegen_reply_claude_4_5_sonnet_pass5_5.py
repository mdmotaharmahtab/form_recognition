Looking at the feedback, I need to fix several issues:

1. **False positives**: "Actual Attempts", "Most Lethal Attempt", and the truncated "Potential Lethality..." are being extracted as fields when they're actually section headers or table column headers
2. **Low coverage**: Cluster 0 (9 pages) only has 11% coverage, and Cluster 1 (9 pages) has 0% coverage
3. **Structural issues**: The sample pages from poorly-covered clusters show different layouts that need handling

Let me analyze the sample pages:
- **Cluster 1** (pages 255, 425): These appear to be definition/legend pages with only red annotation text describing rating scales - correctly should have 0% coverage
- **Cluster 0** (pages 235, 465): These show a **table layout** with fields like "Urinalysis" and columns for "Collected", "Not Collected", "Not Applicable", "Scan". The red text shows field codes like `[LBTEST1]`, `[LBRSN1]`, etc.

The main issues:
1. Need to detect and extract table-based layouts (Cluster 0)
2. Need to better exclude section headers like "Actual Attempts", "Most Lethal Attempt"
3. The truncated "Potential Lethality: Only answer if Actual Lethality=0 Likely lethality of actual attempt if no medical damage (the following examples, while" is clearly being cut off mid-sentence - this is a long descriptive text, not a field label

```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form titles: large blue text (size >= 13)
        for ln in lines:
            if ln.size >= 13 and ln.non_black:
                text = ln.text.strip()
                text = re.sub(r'^\d+\.?\d*\.\s*', '', text)
                if text and len(text) > 5 and not re.match(r'^(PAGES?|Page \d+)$', text, re.I):
                    current_form = text
                    break
        
        # If no form found yet, try medium blue text (10-13)
        if not current_form:
            for ln in lines:
                if 10 <= ln.size < 13 and ln.non_black:
                    text = ln.text.strip()
                    text = re.sub(r'^\d+\.?\d*\.\s*', '', text)
                    if text and len(text) > 8:
                        current_form = text
                        break
        
        # Check if this is a definition/legend page (all red text, no substantial black content)
        black_content_lines = [ln for ln in lines if not ln.non_black and 7 <= ln.size <= 11 and len(ln.text.strip()) > 3]
        if len(black_content_lines) == 0:
            continue
        
        # Detect page layout type by analyzing structure
        # Table layout: has column headers at specific y-position with repeated patterns
        table_layout = False
        table_headers_y = None
        
        # Look for table column headers (words like "Collected", "Scan" at similar y-position)
        header_candidates = {}
        for ln in lines:
            text = ln.text.strip()
            # Column headers are typically medium-sized black text
            if 8 <= ln.size <= 10 and not ln.non_black:
                if text in ['Collected', 'Scan', 'Applicable']:
                    y_key = round(ln.y0 / 5) * 5  # Group by approximate y position
                    if y_key not in header_candidates:
                        header_candidates[y_key] = []
                    header_candidates[y_key].append(ln)
        
        # If we have multiple header candidates at the same y, it's likely a table
        for y_key, headers in header_candidates.items():
            if len(headers) >= 2:
                table_layout = True
                table_headers_y = y_key
                break
        
        # LAYOUT 1: Table-based forms (like Urinalysis)
        if table_layout:
            # Extract row labels (black text in leftmost column, below headers)
            for ln in lines:
                text = ln.text.strip()
                
                if not text or len(text) < 3:
                    continue
                
                # Skip red annotations
                if ln.non_black:
                    continue
                
                # Skip if too small or too large
                if not (7 <= ln.size <= 10):
                    continue
                
                # Skip column headers themselves
                if text in ['Collected', 'Not', 'Scan', 'Applicable']:
                    continue
                
                # Must be below the header row
                if table_headers_y and ln.y0 < table_headers_y + 10:
                    continue
                
                # Must be in leftmost column (x position < 150)
                if ln.x0 > 150:
                    continue
                
                # Skip obvious non-fields
                if text.startswith('(') and text.endswith(')'):
                    continue
                
                if text[0].islower():
                    continue
                
                # This looks like a row label in a table
                if current_form and text[0].isupper():
                    results.append({
                        "form_name": current_form,
                        "field_name": text,
                        "page": page_num
                    })
        
        # LAYOUT 2: Traditional vertical form layout
        else:
            i = 0
            while i < len(lines):
                line = lines[i]
                text = line.text.strip()
                
                if not text or len(text) < 3:
                    i += 1
                    continue
                
                # Skip red annotations
                if line.non_black:
                    i += 1
                    continue
                
                # Skip row markers
                if re.match(r'^Row \d+$', text, re.I):
                    i += 1
                    continue
                
                # Field detection: black text with appropriate size
                is_black = not line.non_black
                is_field_size = 7 <= line.size <= 11
                
                if not (is_black and is_field_size):
                    i += 1
                    continue
                
                # Exclude answer options (escaped numbers)
                if re.match(r'^\\[0-9]\.\\ ', text):
                    i += 1
                    continue
                
                # Exclude lowercase continuations and parentheticals
                if text[0].islower() or text.startswith('('):
                    i += 1
                    continue
                
                # Exclude single-word grid answers
                if re.match(r'^(Yes|No|Current|Former|Never|Collected|Not|Applicable|Scan)$', text):
                    i += 1
                    continue
                
                # Exclude parenthetical options
                if text.startswith('(') and text.endswith(')'):
                    i += 1
                    continue
                
                # Check field indicators
                has_colon_or_question = text.endswith(':') or '?' in text
                
                # Look ahead for evidence
                has_answer_options = False
                has_red_annotation = False
                
                for j in range(i+1, min(i+5, len(lines))):
                    next_text = lines[j].text.strip()
                    
                    if re.match(r'^\\[0-9]\.\\ ', next_text):
                        has_answer_options = True
                        break
                    
                    if lines[j].non_black and ('[' in next_text or 'TYPE:' in next_text):
                        has_red_annotation = True
                        break
                
                # Exclude answer descriptions
                is_answer_description = (
                    'e.g.' in text or
                    re.search(r'\([0-9]\)', text) or
                    (text.count(';') >= 2) or
                    text.count(',') >= 4
                )
                
                if is_answer_description:
                    i += 1
                    continue
                
                # NEW: Exclude section headers and table column headers
                # Section headers are typically:
                # - Short (< 25 chars)
                # - No colon at end
                # - No question mark
                # - Positioned differently (often centered or at specific x positions)
                is_section_header = (
                    len(text) < 25 and
                    not has_colon_or_question and
                    not has_answer_options and
                    not has_red_annotation and
                    # Section headers often appear at x positions > 40 and are isolated
                    line.x0 > 40
                )
                
                # NEW: Detect truncated multi-line descriptions
                # If text is very long (>80 chars) without ending punctuation, likely truncated
                is_truncated_description = (
                    len(text) > 80 and
                    not text.endswith(':') and
                    not text.endswith('?') and
                    not text.endswith('.')
                )
                
                if is_truncated_description:
                    i += 1
                    continue
                
                # Determine if this is a field
                is_field = (
                    (has_colon_or_question or has_answer_options or has_red_annotation) and
                    len(text) >= 5 and
                    text[0].isupper() and
                    not is_section_header
                )
                
                if is_field and current_form:
                    # Collect multi-line field labels
                    full_text = text
                    k = i + 1
                    
                    # Look ahead to collect continuation lines
                    while k < len(lines) and k < i + 4:
                        next_line = lines[k]
                        next_text = next_line.text.strip()
                        
                        if not next_text:
                            break
                        
                        if next_line.non_black:
                            break
                        
                        if re.match(r'^\\[0-9]\.\\ ', next_text):
                            break
                        
                        if next_text.startswith('(') or next_text[0].islower():
                            break
                        
                        if re.match(r'^Row \d+$', next_text, re.I):
                            break
                        
                        if next_text.endswith(':') and len(next_text) > 5:
                            break
                        
                        if re.match(r'^(Yes|No|Current|Former|Never|Collected|Not|Applicable|Scan)$', next_text):
                            break
                        
                        if 'e.g.' in next_text or re.search(r'\([0-9]\)', next_text):
                            break
                        
                        # Check if continuation
                        if abs(next_line.x0 - line.x0) < 15 and 7 <= next_line.size <= 11:
                            full_text += ' ' + next_text
                            k += 1
                        else:
                            break
                    
                    # Clean up
                    full_text = re.sub(r'\s+', ' ', full_text).strip()
                    
                    # Final validation: exclude long descriptions and ensure reasonable length
                    # Field labels should be < 100 chars typically
                    if (len(full_text) >= 5 and 
                        len(full_text) < 100 and
                        'e.g.' not in full_text and 
                        full_text.count(';') < 2 and 
                        not re.search(r'\([0-9]\).*\([0-9]\)', full_text)):
                        results.append({
                            "form_name": current_form,
                            "field_name": full_text,
                            "page": page_num
                        })
                    
                    i = k
                else:
                    i += 1
    
    # Deduplicate consecutive identical records
    deduplicated = []
    prev_key = None
    for rec in results:
        key = (rec['form_name'], rec['field_name'])
        if key != prev_key:
            deduplicated.append(rec)
            prev_key = key
    
    return deduplicated
```
