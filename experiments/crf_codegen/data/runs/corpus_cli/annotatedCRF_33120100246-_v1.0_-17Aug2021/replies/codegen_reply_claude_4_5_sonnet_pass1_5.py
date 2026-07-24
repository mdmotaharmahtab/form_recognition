Looking at the issues, I need to fix several structural problems:

1. **Page 7 (Change History)**: "Manolescu" and "Giucal" are names in a table, not field labels
2. **Pages 40, 171, 301**: Wrong form attribution - need better form boundary detection
3. **Pages 46, 50**: Long horizontal lists of lab test names (not field labels) - need to detect horizontal alignment of similar short items
4. **Page 71, 136**: Long instructional text being extracted - need better instruction detection
5. **Pages 171, 440**: Missing fields - too aggressive filtering
6. **Clusters 9-12**: TOC/legend pages (0% coverage is correct - they're just links/codes)
7. **Cluster 2 (210, 374)**: Tabular PK collection forms - need better handling

The key fixes:
- Detect **horizontal lists** (lab test names, rating anchors) by multiple short items at same Y
- Better **instruction paragraph** detection by sentence structure
- Improve **form title persistence** - titles stay until a new one appears
- Fix **table cell** detection - don't extract cell values as fields
- **Remove all hardcoded text blocklists** - use structural rules only

```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        if not lines:
            continue
        
        page_num = page_idx + 1
        
        # Skip TOC/legend pages: many colored links, minimal black text
        colored_links = [ln for ln in lines if ln.non_black and ln.x0 < 500]
        black_text = [ln for ln in lines if not ln.non_black and ln.y0 > 100 and ln.size >= 7]
        
        if len(colored_links) > 15 and len(black_text) < 5:
            continue
        
        # Skip annotation-only pages (mostly red text)
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
                # Remove leading numbers
                text = re.sub(r'^\d+(\.\d+)*\s*', '', text)
                if len(text) > 10:
                    form_title = text
                    break
        
        # Update current form if new title found
        if form_title:
            current_form = form_title
        
        # Filter content lines: exclude red annotations, very small text
        content_lines = [ln for ln in lines 
                        if not ('#ff0000' in str(getattr(ln, 'color', '')).lower() or
                                'rgb(255' in str(getattr(ln, 'color', '')).lower())
                        and ln.size >= 6.5
                        and ln.y0 > 30
                        and ln.y0 < 750]
        
        # Detect horizontal lists: 3+ short items aligned at same Y within 200px span
        # These are rating anchors, lab test names, column headers, etc.
        horizontal_list_rows = set()
        for ln in content_lines:
            text = ln.text.strip()
            if 5 < len(text) < 60 and ln.x0 < 500:
                # Count items at same Y with different X positions
                same_y_items = [other for other in content_lines
                               if abs(other.y0 - ln.y0) < 5
                               and abs(other.x0 - ln.x0) > 30
                               and 5 < len(other.text.strip()) < 60]
                
                if len(same_y_items) >= 2:
                    # Check if they span horizontally (not just 2 columns)
                    x_positions = sorted([ln.x0] + [other.x0 for other in same_y_items])
                    if x_positions[-1] - x_positions[0] > 180:
                        horizontal_list_rows.add(round(ln.y0))
        
        # Detect tabular data regions: multiple short aligned items in columns
        tabular_rows = set()
        for ln in content_lines:
            text = ln.text.strip()
            if len(text) < 40 and ln.x0 < 500:
                # Count vertical neighbors in same column
                col_neighbors = [other for other in content_lines
                               if abs(other.x0 - ln.x0) < 15
                               and 10 < abs(other.y0 - ln.y0) < 50
                               and len(other.text.strip()) < 40]
                
                # Count horizontal neighbors in same row
                row_neighbors = [other for other in content_lines
                               if abs(other.y0 - ln.y0) < 5
                               and abs(other.x0 - ln.x0) > 40
                               and len(other.text.strip()) < 50]
                
                # If 2+ columns with 2+ rows = table
                if len(col_neighbors) >= 1 and len(row_neighbors) >= 1:
                    tabular_rows.add(round(ln.y0))
        
        # Detect bold/large column headers
        header_rows = set()
        for ln in content_lines:
            if (ln.bold or ln.size >= 9.5) and len(ln.text.strip()) < 50:
                neighbors = sum(1 for other in content_lines 
                              if abs(other.y0 - ln.y0) < 5 
                              and abs(other.x0 - ln.x0) > 50
                              and len(other.text.strip()) < 50)
                if neighbors >= 1:
                    header_rows.add(round(ln.y0))
        
        # Collect field candidates
        field_candidates = []
        i = 0
        
        while i < len(content_lines):
            ln = content_lines[i]
            
            # Field label criteria: black text in left area
            if not ln.non_black and ln.x0 < 380 and 7 <= ln.size <= 11:
                text = ln.text.strip()
                
                # Skip empty
                if not text:
                    i += 1
                    continue
                
                # Skip if in horizontal list (rating anchors, lab names)
                if any(abs(ln.y0 - hr) < 5 for hr in horizontal_list_rows):
                    i += 1
                    continue
                
                # Skip if in tabular row
                if any(abs(ln.y0 - tr) < 5 for tr in tabular_rows):
                    i += 1
                    continue
                
                # Skip if in header row
                if any(abs(ln.y0 - hr) < 5 for hr in header_rows):
                    i += 1
                    continue
                
                # Skip very short (< 3 chars)
                if len(text) < 3:
                    i += 1
                    continue
                
                # Skip pure numbers/dates
                if re.match(r'^(\d{1,2}[-/]\w{3,4}[-/]\d{2,4}|\d+[\.\:]\d*|\d+\.\d+\.\d+|\d+)$', text):
                    i += 1
                    continue
                
                # Skip person names (2-3 capitalized words, short)
                if re.match(r'^[A-Z][a-z]+(\s+[A-Z][a-z]+){0,2}$', text) and len(text) < 35:
                    i += 1
                    continue
                
                # Skip table structure markers like "Row N"
                if re.match(r'^Row\s+\d+$', text, re.IGNORECASE):
                    i += 1
                    continue
                
                # Detect long instruction paragraphs
                is_instruction = False
                
                # Very long single line from far left
                if len(text) > 95 and ln.x0 < 80:
                    is_instruction = True
                
                # Sentence fragments without field indicators (colon, question mark)
                elif len(text) > 50 and not text.endswith((':','?')):
                    # Check if looks like instruction prose
                    words = text.split()
                    if len(words) > 8:
                        # Many lowercase words = prose, not field label
                        lowercase_count = sum(1 for w in words[1:] if w and w[0].islower())
                        if lowercase_count > len(words) * 0.6:
                            is_instruction = True
                
                if is_instruction:
                    i += 1
                    continue
                
                # Skip very far right (answer column, unless substantial)
                if ln.x0 > 380 and len(text) < 40:
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
                        
                        # Stop at empty
                        if not next_text:
                            break
                        
                        # Stop at machine codes
                        if next_text.startswith('['):
                            break
                        
                        # Stop if moved to answer column
                        if next_ln.x0 > 380:
                            break
                        
                        # Stop at tabular/header/horizontal list rows
                        if any(abs(next_ln.y0 - tr) < 5 for tr in tabular_rows):
                            break
                        if any(abs(next_ln.y0 - hr) < 5 for hr in header_rows):
                            break
                        if any(abs(next_ln.y0 - hr) < 5 for hr in horizontal_list_rows):
                            break
                        
                        # Stop at very short answer-like fragments
                        if len(next_text) < 10 and next_ln.y0 - ln.y0 > 15:
                            break
                        
                        # Stop at new instruction paragraph
                        if len(next_text) > 95:
                            break
                        
                        label_lines.append(next_text)
                        ln = next_ln
                        j += 1
                    else:
                        break
                
                field_name = ' '.join(label_lines).strip()
                
                # Final validation
                if len(field_name) >= 3:
                    # Skip if it's just numbers
                    if re.match(r'^\d+$', field_name):
                        i = j
                        continue
                    
                    # Skip machine code patterns
                    if '[TYPE:' in field_name or '[VISIBILITY:' in field_name:
                        i = j
                        continue
                    
                    # Skip if ends with pattern indicating it's part of instruction
                    # (e.g., "position for 3 minutes")
                    if re.search(r'\s+for\s+\d+\s+(minutes?|seconds?|hours?)$', field_name):
                        i = j
                        continue
                    
                    # Skip single-word bold items that have many horizontal neighbors
                    # (likely column headers even if not caught earlier)
                    if len(field_name.split()) == 1 and (ln.bold or ln.size >= 9.5):
                        h_neighbors = sum(1 for other in content_lines
                                        if abs(other.y0 - ln.y0) < 5
                                        and abs(other.x0 - ln.x0) > 40
                                        and len(other.text.strip()) < 30)
                        if h_neighbors >= 2:
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
