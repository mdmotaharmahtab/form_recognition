Looking at the metrics, my program extracted ZERO records. The sample pages show the actual structure I need to handle:

**Key observations:**
1. Form titles are blue (#004c99), size ~16.5, like "Height and Weight", "FSH Blood Sample"
2. Field labels are black, size 9.0, left-aligned (x ≈ 64)
3. Machine codes are red (#ff0000) in brackets like [VSPERF], [TYPE: ...], [VISIBILITY: ...]
4. Answer options are gray (#999999) and right-aligned (x > 500)
5. Some pages have table-like layouts with labels in different positions

The main issue: my filters were too aggressive and rejected all valid fields. I need to:
- Trust black text at x ≈ 64 as field labels
- Stop over-filtering based on position
- Handle both form-style and table-style layouts

```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form title: blue text (#004c99), size >= 15
        for line in lines:
            if (line.size >= 15.0 and 
                line.non_black and 
                '#004c99' in str(line.text).lower()):
                form_title = line.text.strip()
                # Remove " - Page N" suffixes
                form_title = re.sub(r'\s*-\s*Page\s+\d+\s*$', '', form_title)
                if form_title and len(form_title) > 2:
                    current_form = form_title
                break
        
        # Skip if no form context
        if not current_form:
            continue
        
        # Process fields
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip red machine codes
            if line.non_black and '#ff0000' in str(line.text).lower():
                i += 1
                continue
            
            # Skip gray answer options (right side, often x > 450)
            if line.non_black and '#999999' in str(line.text).lower():
                i += 1
                continue
            
            # Skip page numbers at bottom
            if line.y0 > 750:
                i += 1
                continue
            
            # Skip form title itself
            if line.size >= 15.0:
                i += 1
                continue
            
            # Main field detection: black text, reasonable size
            if not line.non_black and line.size >= 8.0 and line.text.strip():
                text = line.text.strip()
                
                # Skip machine codes in brackets
                if text.startswith('[') and text.endswith(']'):
                    i += 1
                    continue
                
                # Skip very short text (likely junk)
                if len(text) < 3:
                    i += 1
                    continue
                
                # Skip pure punctuation or numbers
                if re.match(r'^[\(\d\)•\.\-\s]+$', text):
                    i += 1
                    continue
                
                # Skip "Page N of M"
                if re.match(r'^Page\s+\d+\s+of\s+\d+', text, re.IGNORECASE):
                    i += 1
                    continue
                
                # Skip copyright symbols
                if '©' in text:
                    i += 1
                    continue
                
                # Field labels are typically:
                # - Left-aligned (x < 100 for main labels)
                # - OR in table headers (but not pure column headers like "Criteria" alone)
                # - Questions, prompts, field names
                
                # Check if this looks like a substantive field label
                is_likely_field = False
                
                # Left-aligned text is likely a field label
                if line.x0 < 100:
                    # Skip single-word column headers (like "Criteria", "Met/Not Met")
                    if len(text.split()) == 1 and line.y0 < 150:
                        i += 1
                        continue
                    is_likely_field = True
                
                # Table-style labels (centered or mid-page)
                # These appear in cluster 1 pages (chemistry assays, etc.)
                elif 250 < line.x0 < 450 and line.size >= 9.0:
                    # Multi-word labels in table layouts
                    if len(text.split()) >= 2 or len(text) > 8:
                        is_likely_field = True
                
                if not is_likely_field:
                    i += 1
                    continue
                
                # Check for multi-line field labels
                field_text = text
                j = i + 1
                
                # Continuation logic for left-aligned fields
                if line.x0 < 100:
                    while j < len(lines):
                        next_line = lines[j]
                        
                        # Continue if:
                        # - Black text
                        # - Close in y (within 20 units)
                        # - Similar x alignment (within 50 units to allow indents)
                        # - Not a machine code
                        if (not next_line.non_black and 
                            next_line.y0 - lines[j-1].y0 < 25 and
                            abs(next_line.x0 - line.x0) < 60 and 
                            next_line.size >= 8.0 and
                            next_line.text.strip() and
                            not next_line.text.strip().startswith('[')):
                            
                            cont_text = next_line.text.strip()
                            
                            # Stop if it looks like a new field (bold "Row N" markers)
                            if re.match(r'^Row\s+\d+$', cont_text, re.IGNORECASE):
                                break
                            
                            # Stop if next line is far down (new section)
                            if next_line.y0 - lines[j-1].y0 > 18:
                                # Only continue if this looks like a natural continuation
                                if not (cont_text[0].islower() or 
                                       field_text.endswith((',', ':', 'or', 'and', 'of', 'the', 'to', 'a', 'an', 'within', 'prior'))):
                                    break
                            
                            field_text += ' ' + cont_text
                            j += 1
                        else:
                            break
                
                # Final cleanup
                field_text = field_text.strip()
                
                # Skip if empty after processing
                if len(field_text) < 3:
                    i = j if j > i + 1 else i + 1
                    continue
                
                # Skip pure "Row N" labels
                if re.match(r'^Row\s+\d+$', field_text, re.IGNORECASE):
                    i = j if j > i + 1 else i + 1
                    continue
                
                # Skip if it's just a number or enumeration
                if re.match(r'^[\d\.\)]+$', field_text):
                    i = j if j > i + 1 else i + 1
                    continue
                
                # This is a valid field
                results.append({
                    "form_name": current_form,
                    "field_name": field_text,
                    "page": page_num
                })
                
                i = j if j > i + 1 else i + 1
            else:
                i += 1
    
    return results
```
