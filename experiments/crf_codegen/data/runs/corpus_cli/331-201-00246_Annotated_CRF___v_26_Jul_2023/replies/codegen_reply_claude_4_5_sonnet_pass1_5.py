Looking at the problems, I need to address several key issues:

1. **Cluster 3 & 5 pages (table-based forms)**: Pages 460, 859, 938, 941 show table headers as column labels that are actual data-entry fields
2. **Missing fields on various pages**: Need to be less aggressive in filtering
3. **False positives**: Long descriptive text and rating scale definitions are being extracted

Let me analyze the patterns:

- **Cluster 3 (460, 859)**: Table headers like "Sample", "Status", "Reason not done" are field labels, with machine codes below
- **Cluster 5 (938, 941)**: Simple vertical lists of answer options - these are NOT fields (0% coverage is correct)
- **Page 562, 937 (Cluster 1)**: Vertical lists at x~333-442, likely answer options (correctly not extracted)
- **False positives**: Multi-sentence descriptive text with semicolons, rating scale definitions starting with numbers

```python
import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Skip TOC pages (first 2 pages only)
        if page_num <= 2:
            continue
        
        # Extract form title: large blue/colored text at top of page
        for line in lines[:15]:
            if line.size >= 14 and line.non_black and line.y0 < 250:
                text = line.text.strip()
                # Form titles are substantial, not machine codes
                if text and len(text) > 3 and not re.match(r'^\[.*\]$', text):
                    # Exclude page headers and continuation markers
                    if not re.match(r'^(CHANGE HISTORY|SCHEDULE|Page \d+)', text):
                        # Exclude "- Page N" continuations
                        if not re.match(r'^.* - Page \d+$', text):
                            current_form = text
                            break
        
        # Identify structural elements
        machine_codes = set()
        
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Machine codes: red/colored text in brackets
            if re.match(r'^\[.*\]$', text) and line.non_black:
                machine_codes.add(i)
        
        # Detect table header rows: black text at top, with machine codes below
        # Pattern: horizontal row of labels (y < 200, similar y), followed by machine codes
        table_headers = []
        for i, line in enumerate(lines):
            if (not line.non_black and 
                line.y0 < 200 and 
                8 <= line.size <= 12 and
                line.x0 > 50):
                
                # Check if machine codes appear below this line
                has_codes_below = False
                for j in range(i+1, min(i+10, len(lines))):
                    if j in machine_codes:
                        other = lines[j]
                        # Code is roughly aligned below this header
                        if abs(other.x0 - line.x0) < 100 and other.y0 > line.y0:
                            has_codes_below = True
                            break
                
                if has_codes_below:
                    # Check if this is part of a horizontal header row
                    same_row = [i]
                    for j, other in enumerate(lines):
                        if (j != i and 
                            abs(other.y0 - line.y0) < 5 and
                            not other.non_black and
                            8 <= other.size <= 12):
                            same_row.append(j)
                    
                    # If multiple items on same row, it's a table header
                    if len(same_row) >= 3:
                        for idx in same_row:
                            table_headers.append(idx)
        
        # Identify answer option zones: far right, short text, in vertical list
        answer_option_indices = set()
        for i, line in enumerate(lines):
            text = line.text.strip()
            # Answer options: x > 320, short, not questions
            if len(text) <= 50 and line.x0 > 320 and not line.non_black and 8 <= line.size <= 12:
                # Check if part of vertical list at this x position
                same_column = 0
                for j, other in enumerate(lines):
                    if j != i and abs(other.x0 - line.x0) < 20 and not other.non_black:
                        same_column += 1
                
                # Strong vertical list = answer options
                if same_column >= 4:
                    answer_option_indices.add(i)
        
        # Detect pages that are pure answer option lists
        # These have many short items in vertical columns
        right_aligned_items = 0
        for line in lines:
            if line.x0 > 400 and 50 < line.y0 < 750 and 8 <= line.size <= 11:
                right_aligned_items += 1
        
        # If page is dominated by right-aligned options, skip it
        if right_aligned_items > 15 and len(lines) < 30:
            continue
        
        # Identify rating scale anchors: numbered descriptions in sequence
        rating_anchor_indices = set()
        for i, line in enumerate(lines):
            text = line.text.strip()
            # Pattern: starts with number/backslash-number and has description
            if re.match(r'^[\\]?[0-9][\.\)\\]?\s+\w+', text) and len(text) > 15:
                # Must have descriptive content (not just labels)
                # Rating scales have longer explanatory text
                if len(text) > 40:
                    # Check if part of numbered sequence
                    nearby_numbered = 0
                    for j in range(max(0, i-3), min(len(lines), i+4)):
                        if j != i:
                            other_text = lines[j].text.strip()
                            if re.match(r'^[\\]?[0-9][\.\)\\]?\s+\w+', other_text):
                                nearby_numbered += 1
                    if nearby_numbered >= 1:
                        rating_anchor_indices.add(i)
        
        fields = []
        
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip machine codes
            if i in machine_codes:
                i += 1
                continue
            
            # Skip page numbers
            if re.match(r'^Page \d+ of \d+$', text) and line.y0 > 750:
                i += 1
                continue
            
            # Skip form titles (already extracted)
            if line.size >= 14 and line.y0 < 250:
                i += 1
                continue
            
            # Extract table headers as fields
            if i in table_headers:
                field_text = text
                # Clean up
                if len(field_text) >= 3 and not re.match(r'^[(\d\.)]+$', field_text):
                    fields.append(field_text)
                i += 1
                continue
            
            # Skip answer options (structural)
            if i in answer_option_indices:
                i += 1
                continue
            
            # Skip rating anchors (structural)
            if i in rating_anchor_indices:
                i += 1
                continue
            
            # Field label identification
            is_black = not line.non_black
            is_field_size = 8 <= line.size <= 12
            is_in_content_area = 50 < line.x0 < 520 and 100 < line.y0 < 800
            
            if is_black and is_field_size and is_in_content_area:
                # Skip very long text (likely instructions/descriptions)
                if len(text) > 200:
                    i += 1
                    continue
                
                # Skip bare numbering
                if re.match(r'^[\d\.\)]+\s*$', text):
                    i += 1
                    continue
                
                # Skip "Row N" labels (table row labels, not fields)
                if re.match(r'^Row \d+$', text):
                    i += 1
                    continue
                
                # Structural detection: is this a field label?
                is_left_aligned = line.x0 < 280
                is_question_or_prompt = text.endswith('?') or text.endswith(':')
                
                # Machine code nearby = strong field signal
                has_machine_code_nearby = False
                for j in range(i+1, min(i+5, len(lines))):
                    if j in machine_codes:
                        has_machine_code_nearby = True
                        break
                
                # Part of vertical list at left column
                is_in_vertical_list = False
                similar_items = 0
                for j in range(max(0, i-4), min(len(lines), i+5)):
                    if j != i:
                        other = lines[j]
                        if (abs(other.x0 - line.x0) < 25 and
                            not other.non_black and
                            8 <= other.size <= 12 and
                            len(other.text.strip()) > 3):
                            similar_items += 1
                
                if similar_items >= 2:
                    is_in_vertical_list = True
                
                # Check if surrounded by answer options (likely not a field)
                surrounded_by_options = False
                option_count = 0
                for j in range(max(0, i-3), min(len(lines), i+8)):
                    if j in answer_option_indices:
                        option_count += 1
                if option_count >= 3 and not has_machine_code_nearby:
                    surrounded_by_options = True
                
                # Bold section headers with many following items are not fields
                if line.bold and len(text) < 60 and line.size >= 10:
                    nearby_fields = 0
                    for j in range(i+1, min(i+8, len(lines))):
                        next_text = lines[j].text.strip()
                        if len(next_text) > 5 and not lines[j].non_black:
                            nearby_fields += 1
                    
                    if nearby_fields >= 4:
                        same_indent = 0
                        for j in range(i+1, min(i+8, len(lines))):
                            if abs(lines[j].x0 - line.x0) < 30:
                                same_indent += 1
                        if same_indent >= 3:
                            i += 1
                            continue
                
                # Exclude multi-sentence descriptive paragraphs
                # These have multiple clauses with semicolons or many commas
                if len(text) > 100:
                    # Complex sentence structure = description not field
                    if text.count(';') >= 2 or (text.count(',') >= 3 and not text.endswith('?')):
                        i += 1
                        continue
                    
                    # Parenthetical explanations = description
                    if text.count('(') >= 2 and text.count(')') >= 2:
                        i += 1
                        continue
                
                # Decide if this is a field label
                is_likely_field = False
                
                if has_machine_code_nearby:
                    is_likely_field = True
                elif is_question_or_prompt and is_left_aligned:
                    is_likely_field = True
                elif is_in_vertical_list and is_left_aligned and len(text) >= 5:
                    # Exclude if part of answer option structure
                    if not surrounded_by_options:
                        is_likely_field = True
                
                # Additional structural filters
                # If at far right (x > 400), likely answer option not field
                if line.x0 > 400:
                    is_likely_field = False
                
                # If very small font (< 8.5), likely footnote/annotation
                if line.size < 8.5:
                    is_likely_field = False
                
                if is_likely_field:
                    # Join wrapped continuation lines
                    full_text = text
                    k = i + 1
                    while k < len(lines):
                        next_line = lines[k]
                        next_text = next_line.text.strip()
                        
                        # Stop at machine code
                        if k in machine_codes:
                            break
                        
                        # Stop at answer options
                        if k in answer_option_indices:
                            break
                        
                        # Stop at rating anchors
                        if k in rating_anchor_indices:
                            break
                        
                        # Stop at table headers
                        if k in table_headers:
                            break
                        
                        # Stop at new field (same pattern as current)
                        if (not next_line.non_black and
                            8 <= next_line.size <= 12 and
                            abs(next_line.x0 - line.x0) < 25 and
                            len(next_text) > 10 and
                            (next_text.endswith('?') or next_text.endswith(':'))):
                            break
                        
                        # Continuation: close y, similar x, black, similar size
                        y_dist = next_line.y0 - lines[k-1].y0
                        x_aligned = abs(next_line.x0 - line.x0) < 60
                        is_continuation = (not next_line.non_black and
                                          7.5 <= next_line.size <= 12.5 and
                                          y_dist < 18 and
                                          x_aligned and
                                          len(next_text) > 3)
                        
                        if is_continuation:
                            # Don't continue if next line starts with number (new item)
                            if not re.match(r'^[\\]?[0-9][\.\)\\]', next_text):
                                full_text += " " + next_text
                                k += 1
                            else:
                                break
                        else:
                            break
                    
                    # Clean up
                    full_text = re.sub(r'\s+', ' ', full_text).strip()
                    
                    # Final validation
                    if len(full_text) >= 3 and not re.match(r'^[(\d\.)]+$', full_text):
                        # Exclude very long descriptive text (> 250 chars)
                        if len(full_text) <= 250:
                            # Exclude if looks like rating scale description
                            # These start with \number and have long explanatory clauses
                            if re.match(r'^[\\][0-9][\.\)\\]', full_text) and len(full_text) > 80:
                                i = k
                                continue
                            
                            fields.append(full_text)
                    
                    i = k
                    continue
            
            i += 1
        
        # Add extracted fields to results
        for field_name in fields:
            if current_form or field_name:
                results.append({
                    "form_name": current_form,
                    "field_name": field_name,
                    "page": page_num
                })
    
    return results
```
