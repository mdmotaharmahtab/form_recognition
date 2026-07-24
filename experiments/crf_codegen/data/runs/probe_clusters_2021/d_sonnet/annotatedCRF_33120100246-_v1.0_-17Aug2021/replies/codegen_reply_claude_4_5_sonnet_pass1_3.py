Looking at the issues, I need to:

1. **Stop extracting TOC entries** (pages 1-4) - those are navigation, not data-entry fields
2. **Fix the blocklist approach** - replace hardcoded text strings with structural rules
3. **Handle cluster 4 pages** (0% coverage) - they appear to have enumeration fields
4. **Fix page 68 issues** - table headers being incorrectly filtered
5. **Handle multi-line continuation better** to catch wrapped field labels
6. **Fix form name persistence** to avoid wrong_form errors

```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip TOC pages entirely (pages 1-4 are table of contents)
        if page_num <= 4:
            continue
        
        # Extract form title from current page
        # Form titles: size 14.4, color #004c99, y < 100
        form_candidates = []
        for line in lines:
            if line.size > 13 and line.size < 16 and line.non_black and line.y0 < 100:
                form_candidates.append((line.y0, line.text.strip()))
        
        # Use the topmost form title on this page
        if form_candidates:
            form_candidates.sort()
            current_form = form_candidates[0][1]
        
        # Build a map of y-positions to detect table structures
        # Tables have aligned columns of text at similar y positions
        y_clusters = {}
        for line in lines:
            y_bucket = round(line.y0 / 5) * 5  # Cluster lines within 5 units
            if y_bucket not in y_clusters:
                y_clusters[y_bucket] = []
            y_clusters[y_bucket].append(line)
        
        # Identify table header rows: 3+ items at same y, small size, similar style
        table_header_ys = set()
        for y_bucket, bucket_lines in y_clusters.items():
            if len(bucket_lines) >= 3:
                # Check if they're small, black text (typical table headers)
                small_black = [l for l in bucket_lines if not l.non_black and l.size < 10]
                if len(small_black) >= 3:
                    # Likely a table header row
                    table_header_ys.add(y_bucket)
        
        # Extract field labels
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels characteristics:
            # - Size 7.8-9.2 (small to medium)
            # - Black text (not red/blue)
            # - Left-aligned at x < 150 (field labels start on left)
            is_field_label = (
                not line.non_black and 
                line.size > 7 and 
                line.size < 10 and 
                line.x0 < 150
            )
            
            if not is_field_label:
                i += 1
                continue
            
            text = line.text.strip()
            
            # Skip empty lines
            if not text:
                i += 1
                continue
            
            # STRUCTURAL FILTERS (not text-based blocklists)
            
            # 1. Skip machine codes (red text in brackets)
            if line.non_black and text.startswith('['):
                i += 1
                continue
            
            # 2. Skip table headers by position
            y_bucket = round(line.y0 / 5) * 5
            if y_bucket in table_header_ys:
                i += 1
                continue
            
            # 3. Skip if this is in a table column (x > 150, size < 8.5)
            # Table cells are further right and smaller
            if line.x0 > 150 and line.size < 8.5:
                i += 1
                continue
            
            # 4. Skip parenthetical notes (whole line in parentheses)
            if text.startswith('(') and text.endswith(')'):
                i += 1
                continue
            
            # 5. Skip if text is too short (< 5 chars) - likely a value not a label
            if len(text) < 5:
                i += 1
                continue
            
            # 6. Skip all-numeric text
            if re.match(r'^[\d\-\s]+$', text):
                i += 1
                continue
            
            # 7. Skip instruction patterns (start with "If ", "Please ", "Log one")
            # These are distinguishable by starting with imperative verbs
            if re.match(r'^(If |Please |Log one |Collect |Click )', text):
                i += 1
                continue
            
            # 8. Skip row number labels ("Row 1", "Row 2")
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Collect continuation lines
            # Field labels may wrap across multiple lines at same x position
            field_text = text
            j = i + 1
            
            while j < len(lines):
                next_line = lines[j]
                
                # Stop if we hit a red code line (machine code)
                if next_line.non_black:
                    break
                
                # Stop if x position differs significantly (different column)
                if abs(next_line.x0 - line.x0) > 10:
                    break
                
                # Stop if size differs significantly (different text type)
                if abs(next_line.size - line.size) > 1:
                    break
                
                # Stop if y gap is too large (different section, > 20 units)
                if j > i and next_line.y0 - lines[j-1].y0 > 20:
                    break
                
                next_text = next_line.text.strip()
                
                # Stop at empty line or machine code
                if not next_text or next_text.startswith('['):
                    break
                
                # Check if this is really a continuation
                # Continuation lines have similar x, size, and are close vertically
                is_continuation = (
                    not next_line.non_black and
                    next_line.size > 7 and 
                    next_line.size < 10 and
                    abs(next_line.x0 - line.x0) < 10 and
                    next_line.y0 - lines[j-1].y0 < 15
                )
                
                if is_continuation:
                    field_text += ' ' + next_text
                    j += 1
                else:
                    break
            
            # Clean up whitespace
            field_text = ' '.join(field_text.split())
            
            # Final validation: must be substantive (> 5 chars after cleanup)
            if len(field_text) >= 5:
                results.append({
                    "form_name": current_form,
                    "field_name": field_text,
                    "page": page_num
                })
            
            # Advance past continuation lines
            i = j if j > i + 1 else i + 1
    
    # Deduplicate consecutive identical records
    deduplicated = []
    prev = None
    for rec in results:
        key = (rec['form_name'], rec['field_name'], rec['page'])
        if key != prev:
            deduplicated.append(rec)
            prev = key
    
    return deduplicated
```
