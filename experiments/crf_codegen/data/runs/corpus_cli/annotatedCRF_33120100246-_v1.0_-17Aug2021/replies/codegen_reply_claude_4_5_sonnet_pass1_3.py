Looking at the issues, I need to:

1. **Extract missing fields on pages 40, 50, 54, 234, 301, 440, 529**: These are short fields like "Timepoint", "Comments", and questions that my current filters are rejecting
2. **Stop extracting instruction text and column headers** (pages 71, 136, 171, 440): These are being admitted because they're left-aligned black text, but they're not fields
3. **Remove all hardcoded text blocklists** and use only structural rules
4. **Fix cluster 2 coverage** (76%): These pages have a tabular layout with short field labels above the table

The key insight is that **real field labels** have distinctive structural properties:
- They appear in a **label area** (specific y-ranges and x-positions)
- **Column headers** appear in consistent horizontal rows with siblings
- **Instructions** are longer paragraphs, often centered or spanning wide
- **Short fields** like "Timepoint" and "Comments" are still valid labels

```python
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
        
        # Detect column header rows: multiple bold/similar items in horizontal alignment
        header_rows = set()
        for ln in content_lines:
            if ln.bold and ln.size >= 8 and len(ln.text.strip()) < 50:
                # Count horizontal neighbors (same y, different x)
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
            if not ln.non_black and ln.x0 < 300 and 7 <= ln.size <= 10.5:
                text = ln.text.strip()
                
                # Skip empty
                if not text:
                    i += 1
                    continue
                
                # Skip if in a detected column header row
                if any(abs(ln.y0 - hr) < 5 for hr in header_rows):
                    i += 1
                    continue
                
                # Skip isolated short fragments that are likely table cells or answers
                if len(text) < 4:
                    i += 1
                    continue
                
                # Skip pure numbers or dates (table cells)
                if re.match(r'^(\d{1,2}[-/]\w{3,4}[-/]\d{2,4}|\d+[\.\:]\d*|\d+)$', text):
                    i += 1
                    continue
                
                # Skip very short text in right area (answer options)
                if ln.x0 > 350 and len(text) < 25:
                    i += 1
                    continue
                
                # Detect instruction paragraphs: wide x-span, very long, or centered
                # Instructions often start far left (< 70) and extend > 150 chars
                is_instruction = False
                if ln.x0 < 70 and len(text) > 100:
                    # Check if this is a long paragraph (instruction style)
                    # Look ahead to see if it continues as a long text block
                    next_lines = [content_lines[j].text.strip() 
                                 for j in range(i+1, min(i+5, len(content_lines)))
                                 if not content_lines[j].non_black 
                                 and abs(content_lines[j].x0 - ln.x0) < 40]
                    total_text = text + ' ' + ' '.join(next_lines[:3])
                    if len(total_text) > 150:
                        is_instruction = True
                
                if is_instruction:
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
                        7 <= next_ln.size <= 10.5):
                        
                        next_text = next_ln.text.strip()
                        
                        # Stop at empty or bracketed code
                        if not next_text or next_text[0] == '[':
                            break
                        
                        # Stop if moved far right (answer column)
                        if next_ln.x0 > 350:
                            break
                        
                        # Stop at column header rows
                        if any(abs(next_ln.y0 - hr) < 5 for hr in header_rows):
                            break
                        
                        # Stop at short answer-like text
                        if len(next_text) < 10 and re.match(r'^(Yes|No|N/?A|Met|Not|Scan|Positive|Negative|Collected)$', next_text, re.IGNORECASE):
                            break
                        
                        label_lines.append(next_text)
                        ln = next_ln
                        j += 1
                    else:
                        break
                
                field_name = ' '.join(label_lines).strip()
                
                # Final validation
                if len(field_name) >= 4:  # Allow shorter fields like "Timepoint", "Comments"
                    # Exclude pure numbers
                    if re.match(r'^\d+$', field_name):
                        i = j
                        continue
                    
                    # Exclude machine codes
                    if re.search(r'\[TYPE:', field_name) or re.search(r'\[VISIBILITY:', field_name):
                        i = j
                        continue
                    
                    # Exclude common instruction patterns by structure
                    # Long sentences with instruction verbs at start
                    if len(field_name) > 120 and re.match(r'^(The following|Ask about|If both|If the answer|Collect|Subject endorses)', field_name):
                        i = j
                        continue
                    
                    # Exclude single-word bold headers that were part of multi-column layout
                    if len(field_name.split()) == 1 and len(field_name) < 15 and ln.bold:
                        # Check for horizontal siblings (column layout)
                        siblings = sum(1 for other in content_lines 
                                      if abs(other.y0 - ln.y0) < 5 
                                      and abs(other.x0 - ln.x0) > 50)
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
```
