Looking at the issues, I need to:

1. **Fix false fields on page 323** (C-SSRS pages): These are rating scale definitions and example text, not actual field labels
2. **Handle cluster 1 pages** (0% coverage): These are disclaimer/instruction pages that should be skipped
3. **Remove hardcoded text blocklists** and use structural rules instead
4. **Keep working extraction** for Urine Drug Screen and other forms

The key insight: C-SSRS pages have actual questions (ending with `?`) but also have numbered rating definitions with explanatory text. I need to distinguish between:
- Real questions: "Have you actually had any thoughts of killing yourself?"
- Rating definitions: "5. Active suicidal ideation with specific plan and intent Thoughts of killing oneself..."
- Example/explanatory text: phrases in quotes, continuation text

Let me rewrite with structural rules:

```python
import re

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Skip table of contents pages - many blue hyperlinks with sections
        blue_link_count = sum(1 for ln in lines if ln.non_black and '#' in str(ln.text))
        if blue_link_count > 10:
            continue
        
        # Skip disclaimer/instruction pages structurally:
        # - Have "Disclaimer:" label
        # - Dense small text (many lines with size < 8.5, length > 50)
        # - No data-entry field structure
        has_disclaimer = any('Disclaimer:' in ln.text for ln in lines)
        small_dense_lines = [ln for ln in lines if ln.size < 8.5 and len(ln.text) > 50]
        if has_disclaimer and len(small_dense_lines) > 8:
            continue
        
        # Extract form/section title: large blue header, reasonable length
        for line in lines:
            if line.size >= 13.0 and line.non_black and line.text.strip():
                text = line.text.strip()
                # Not "Row N" or machine codes
                if not re.match(r'^Row \d+$', text) and not text.startswith('['):
                    if 3 < len(text) < 100:
                        current_form = text
                        break
        
        if not current_form:
            continue
        
        # Extract fields
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip machine codes (red, in brackets)
            if text.startswith('['):
                i += 1
                continue
            
            # Skip "Row N" labels (bold, left-aligned)
            if re.match(r'^Row \d+$', text) and line.bold:
                i += 1
                continue
            
            # Skip answer options - positioned far right (x0 > 250)
            if text in ['Yes', 'No', 'Not Done', 'Positive', 'Negative'] and line.x0 > 250:
                i += 1
                continue
            
            # Identify field labels structurally:
            # - Left-aligned (x0 < 120)
            # - Readable size (7-11 points)
            # - Black or dark gray (not red machine codes)
            # - Either questions OR test/field names
            
            is_red = 'ff0000' in str(line.non_black).lower() if line.non_black else False
            
            if (not is_red and line.x0 < 120 and 7.0 <= line.size <= 11.0 and len(text) >= 3):
                
                # Collect potential multi-line field
                field_parts = [text]
                j = i + 1
                
                # Look for continuation lines
                while j < len(lines):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Stop at machine code
                    if next_text.startswith('['):
                        break
                    
                    # Stop at answer options (far right)
                    if next_text in ['Yes', 'No', 'Not Done', 'Positive', 'Negative'] and next_line.x0 > 250:
                        break
                    
                    # Stop at "Row N"
                    if re.match(r'^Row \d+$', next_text) and next_line.bold:
                        break
                    
                    # Check for continuation: similar position, close vertical gap
                    y_gap = next_line.y0 - line.y0
                    x_similar = abs(next_line.x0 - line.x0) < 40
                    next_is_red = 'ff0000' in str(next_line.non_black).lower() if next_line.non_black else False
                    
                    if (5 < y_gap < 30 and x_similar and not next_is_red and 
                        7.0 <= next_line.size <= 11.0 and len(next_text) > 2):
                        field_parts.append(next_text)
                        j += 1
                    else:
                        break
                
                full_field = ' '.join(field_parts)
                
                # Filter by structure:
                
                # 1. Skip numbered rating definitions (start with digit + period + bold or large text)
                # Example: "1. Wish to be dead" or "5. Active suicidal ideation..."
                if re.match(r'^\d+\.', full_field) and (line.bold or len(full_field) > 80):
                    i = j
                    continue
                
                # 2. Skip rating scale anchor explanations (start with parenthetical number)
                # Example: "(1) Very much improved"
                if re.match(r'^\(\d+\)', full_field):
                    i = j
                    continue
                
                # 3. Skip text in quotes (these are examples/clarifications, not fields)
                # Example: "I have thoughts but I definitely will not do anything about them"
                if full_field.startswith('"') or full_field.endswith('"'):
                    i = j
                    continue
                
                # 4. Skip very long descriptive text without question mark
                # (definitions and instructions, not field labels)
                if len(full_field) > 120 and not full_field.endswith('?'):
                    i = j
                    continue
                
                # 5. Skip lines that start lowercase or are clearly continuation text
                # (part of a definition, not a field label)
                if full_field[0].islower():
                    i = j
                    continue
                
                # 6. Valid fields are:
                # - Questions (end with ?)
                # - Short field names (test names, item labels)
                is_question = full_field.endswith('?')
                is_short_field = 5 < len(full_field) < 100
                
                if is_question or is_short_field:
                    records.append({
                        "form_name": current_form,
                        "field_name": full_field,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    # Deduplicate consecutive identical records
    deduped = []
    prev = None
    for rec in records:
        if rec != prev:
            deduped.append(rec)
            prev = rec
    
    return deduped
```
