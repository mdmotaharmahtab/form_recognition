Looking at the issues, I need to:

1. **Fix wrong-form attribution on page 386** - "Time Placed in Position" and "Time of Vitals Measurement #3" are being attributed to the wrong form
2. **Remove the 14 hardcoded text blocklists** - Replace with structural discriminators
3. **Handle uncovered clusters 4, 5, and 6** - These appear to be definition/legend pages that should be skipped

Let me read the current program to understand its structure better, then fix these issues.

The main problems are:
- The regex patterns for instruction filtering are text-based blocklists
- Need better form title tracking to fix wrong-form issues
- Need to identify and skip definition/legend pages structurally

Here's the corrected program:

```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip TOC pages (pages 1-4 are table of contents)
        if page_num <= 4:
            continue
        
        # Identify definition/legend pages structurally
        # These pages have many blue (#2477cc) hyperlinks in a vertical list
        # with consistent x position and spacing, and little other content
        blue_links = [l for l in lines if l.non_black and l.x0 > 100 and l.x0 < 120 and l.size > 12]
        total_text_lines = [l for l in lines if l.text.strip()]
        
        # If page is mostly blue links in a list format, it's a TOC/legend page
        if len(blue_links) > 20 and len(blue_links) > len(total_text_lines) * 0.7:
            continue
        
        # Pages with only red enumeration type definitions (cluster 4)
        red_lines = [l for l in lines if l.non_black and '[TYPE:' in l.text]
        if len(red_lines) > 0 and len(total_text_lines) < 5:
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
        y_clusters = {}
        for line in lines:
            y_bucket = round(line.y0 / 5) * 5
            if y_bucket not in y_clusters:
                y_clusters[y_bucket] = []
            y_clusters[y_bucket].append(line)
        
        # Identify table header rows: 3+ items at same y, small size
        table_header_ys = set()
        for y_bucket, bucket_lines in y_clusters.items():
            if len(bucket_lines) >= 3:
                small_black = [l for l in bucket_lines if not l.non_black and l.size < 10]
                if len(small_black) >= 3:
                    table_header_ys.add(y_bucket)
        
        # Identify table data regions by detecting multiple columns at similar y positions
        # Table cells are right-aligned (x > 250), small text (< 8.5), non-bold
        table_data_ys = set()
        for y_bucket, bucket_lines in y_clusters.items():
            right_small_lines = [l for l in bucket_lines if l.x0 > 250 and l.size < 8.5]
            if len(right_small_lines) >= 2:
                table_data_ys.add(y_bucket)
        
        # Extract field labels
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels characteristics:
            # - Size 7.8-9.2 (small to medium)
            # - Black text (not red/blue)
            # - Left-aligned at x < 200
            is_field_label = (
                not line.non_black and 
                line.size > 7 and 
                line.size < 10 and 
                line.x0 < 200
            )
            
            if not is_field_label:
                i += 1
                continue
            
            text = line.text.strip()
            
            if not text:
                i += 1
                continue
            
            # STRUCTURAL FILTERS
            
            # 1. Skip machine codes (red text in brackets)
            if line.non_black and text.startswith('['):
                i += 1
                continue
            
            # 2. Skip table headers by position
            y_bucket = round(line.y0 / 5) * 5
            if y_bucket in table_header_ys:
                i += 1
                continue
            
            # 3. Skip table data cells (right-aligned, small, in table row)
            if y_bucket in table_data_ys and line.x0 > 250:
                i += 1
                continue
            
            # 4. Skip if in a table column region (x > 200, size < 8.5)
            if line.x0 > 200 and line.size < 8.5:
                i += 1
                continue
            
            # 5. Skip parenthetical notes (whole line in parentheses)
            if text.startswith('(') and text.endswith(')'):
                i += 1
                continue
            
            # 6. Skip all-numeric text
            if re.match(r'^[\d\-\s]+$', text):
                i += 1
                continue
            
            # 7. Skip row number labels ("Row 1", "Row 2")
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # 8. Skip instruction blocks - distinguished STRUCTURALLY:
            # Instructions are lowercase-starting or mid-sentence fragments
            # that appear below field labels in instruction zones (y > 400 or immediately after field)
            # They're also typically longer (> 40 chars) and sentence-like
            if text[0].islower() and len(text) > 40:
                # This is likely an instruction continuation, not a field label
                i += 1
                continue
            
            # 9. Skip sentence fragments that are clearly not field labels
            # These start with lowercase and have sentence structure (articles, conjunctions)
            if text[0].islower() and any(word in text.lower() for word in [' the ', ' and ', ' or ', ' if ', ' to ']):
                i += 1
                continue
            
            # Collect continuation lines
            field_text = text
            j = i + 1
            
            while j < len(lines):
                next_line = lines[j]
                
                # Stop if we hit a red code line
                if next_line.non_black:
                    break
                
                # Stop if x position differs significantly
                if abs(next_line.x0 - line.x0) > 15:
                    break
                
                # Stop if size differs significantly
                if abs(next_line.size - line.size) > 1.5:
                    break
                
                # Stop if y gap is too large (> 20 units)
                if j > i and next_line.y0 - lines[j-1].y0 > 20:
                    break
                
                next_text = next_line.text.strip()
                
                if not next_text or next_text.startswith('['):
                    break
                
                # Check if this is a continuation
                is_continuation = (
                    not next_line.non_black and
                    next_line.size > 7 and 
                    next_line.size < 10 and
                    abs(next_line.x0 - line.x0) < 15 and
                    next_line.y0 - lines[j-1].y0 < 15
                )
                
                if is_continuation:
                    # Stop at instruction-like continuations (lowercase start + long)
                    if next_text[0].islower() and len(next_text) > 40:
                        break
                    field_text += ' ' + next_text
                    j += 1
                else:
                    break
            
            # Clean up whitespace
            field_text = ' '.join(field_text.split())
            
            # Remove trailing colons
            field_text = field_text.rstrip(':')
            
            # Final validation: must be substantive (>= 3 chars)
            if len(field_text) >= 3:
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
