```python
# This CRF document consists of multiple layout families with distinct structures:
# - Table of contents / navigation pages (families A, B)
# - Enumeration/checklist pages with multi-column layouts (families C, D, E)
# - Standard form pages with title, questions, and answer options (families F, G, H, I, J, K)
# Strategy: Extract form_name from the large colored title at top of form pages.
# Extract field_name from question text (not answer options, not machine codes in red).
# Skip TOC pages. Join wrapped label lines. Filter technical annotations by color.

import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        if not lines:
            continue
        
        page_num = page_idx + 1
        
        # Detect TOC pages by presence of many colored links with section numbers
        toc_pattern_count = sum(1 for ln in lines if ln.non_black and 
                                re.search(r'^\d+\.\d+\.', ln.text.strip()))
        if toc_pattern_count > 10:
            continue
        
        # Extract form title: large colored text near top (size >= 13, y < 100)
        form_title = None
        for ln in lines:
            if ln.y0 < 100 and ln.size >= 13 and ln.non_black:
                text = ln.text.strip()
                # Ignore section numbering
                text = re.sub(r'^\d+(\.\d+)*\s*', '', text)
                if text and not re.match(r'^(CHANGE HISTORY|SCHEDULE OF ASSESSMENT|PAGES)$', text):
                    form_title = text
                    break
        
        if form_title:
            current_form = form_title
        
        # Filter out red annotation lines (machine codes/technical metadata)
        field_lines = [ln for ln in lines if not (ln.non_black and '#ff0000' in str(ln.text).lower())]
        
        # Group lines into potential fields
        # A field is black text at left margin (x0 < 200), size 7-10, not bold headers
        field_candidates = []
        i = 0
        while i < len(field_lines):
            ln = field_lines[i]
            
            # Skip if: header row, answer option, page number, form title
            if ln.y0 < 105:  # Skip header area
                i += 1
                continue
            
            # Detect field label: left-aligned, black, reasonable size
            if ln.x0 < 200 and not ln.non_black and 7 <= ln.size <= 10.5:
                text = ln.text.strip()
                
                # Skip structural elements
                if not text or re.match(r'^Row \d+$', text):
                    i += 1
                    continue
                
                # Skip answer options (short, in specific positions)
                if ln.x0 > 400 and len(text) < 30 and re.match(r'^(Yes|No|N/A|Met|Not Met|Positive|Negative|Not Done)$', text):
                    i += 1
                    continue
                
                # Skip column headers
                if ln.bold and ln.y0 < 200 and re.match(r'^(Test|Result|Sample|Criteria|Met/Not Met)$', text):
                    i += 1
                    continue
                
                # Collect potential multi-line label
                label_lines = [text]
                j = i + 1
                # Look ahead for continuation lines (similar x, close y, black)
                while j < len(field_lines):
                    next_ln = field_lines[j]
                    if (abs(next_ln.x0 - ln.x0) < 30 and 
                        next_ln.y0 - ln.y0 < 50 and 
                        not next_ln.non_black and
                        7 <= next_ln.size <= 10.5):
                        next_text = next_ln.text.strip()
                        # Stop if we hit answer options or machine codes
                        if re.match(r'^(Yes|No|N/A|Met|Not Met|Scan)$', next_text):
                            break
                        if next_text and not re.match(r'^\[.*\]$', next_text):
                            label_lines.append(next_text)
                            ln = next_ln
                            j += 1
                        else:
                            break
                    else:
                        break
                
                field_name = ' '.join(label_lines).strip()
                
                # Final filtering: skip junk patterns
                if (field_name and 
                    not re.match(r'^\d+$', field_name) and
                    not re.match(r'^Row \d+$', field_name) and
                    not re.search(r'\[TYPE:', field_name) and
                    not re.search(r'\[VISIBILITY:', field_name) and
                    len(field_name) > 5):
                    
                    field_candidates.append(field_name)
                
                i = j
            else:
                i += 1
        
        # Deduplicate and add to results
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
