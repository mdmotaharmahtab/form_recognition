STRATEGY:

This document contains clinical research forms with several distinct layout patterns across clusters. The key issues to address are:

1. **Form title handling**: Form titles appear as large blue text (#004c99 or #2477cc, size 15-18) but are sometimes absent on continuation pages. I will carry forward the last seen form title across pages until a new title is detected, ensuring all fields have a form_name even on pages without explicit titles.

2. **Field vs non-field discrimination**:
   - **Data-entry fields**: Black text labels (size 8-11) followed by red bracketed codes, OR fields with colons that introduce input areas
   - **NOT fields**: Table column headers (short capitalized phrases at top of page without red codes), individual table cell values (lab test names like "Albumin", "Platelet count"), checkbox/radio options (Yes/No/N/A), and answer choices in lists
   - **Structural discriminators**: Real fields have red annotation codes nearby (within 5 lines), or are followed by visible input space. Table headers cluster at y < 200 and lack codes. Lab test names appear in columnar layouts without codes.

3. **Cluster-specific handling**:
   - **Clusters 0, 1, 2, 7, 8**: Standard form pages with field labels + red codes - already working well
   - **Cluster 3**: Mostly blank pages with just page numbers - correctly producing zero records
   - **Cluster 4**: Pages with only form titles, no fields - should extract nothing (title-only pages)
   - **Cluster 5**: Table-of-contents style pages listing form names - these are navigation, not data-entry, so zero extraction is correct
   - **Cluster 6**: Need to investigate but likely similar to cluster 3/4

4. **Specific fixes**:
   - Remove hardcoded text blocklists; instead check for red codes structurally
   - Detect multi-line fields with asterisks or continuation patterns (e.g., "**If sexually active...")
   - Exclude lab test names by checking they appear in columnar groups without red codes
   - Better detect "If Yes, describe" style fields by looking for colon + nearby red code
   - Handle "Chemistry abnormal assay # 3 Investigator comment" style fields

5. **Coverage**: Process all pages, carrying form title forward, but only extract when actual field patterns are detected.

```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title: large blue text, typically size 15-18, color blue
        for line in lines:
            if line.size >= 14.0 and line.non_black:
                text = line.text.strip()
                # Filter out page numbers and very short text
                if (text and not re.match(r'^Page \d+', text) and 
                    not re.match(r'^\d+$', text) and len(text) > 5):
                    current_form = text
                    break
        
        # Build a map of line indices for quick lookup
        line_map = {i: line for i, line in enumerate(lines)}
        
        # Helper: check if a red bracketed code exists near this line
        def has_red_code_nearby(start_idx, max_distance=5):
            for j in range(start_idx + 1, min(start_idx + max_distance + 1, len(lines))):
                next_line = lines[j]
                next_text = next_line.text.strip()
                if next_text.startswith('[') and next_line.non_black:
                    return True
                # Stop if we hit substantial black text (another field)
                if next_text and not next_line.non_black and len(next_text) > 10:
                    break
            return False
        
        # Helper: check if this looks like a table column header
        def is_table_header(line, text):
            # Table headers: short phrases, at top of page, no red codes nearby
            if (line.y0 < 200 and len(text.split()) <= 4 and 
                text[0].isupper() and not text.endswith(':')):
                # Check it's not followed by a red code
                idx = lines.index(line)
                if not has_red_code_nearby(idx, 3):
                    return True
            return False
        
        # Helper: check if this is part of a columnar lab test list
        def is_lab_test_name(line, text, idx):
            # Lab tests appear in vertical lists, similar x-position, no red codes
            if len(text) < 30 and not text.endswith(':'):
                # Look for similar items above/below at same x position
                similar_count = 0
                for offset in [-2, -1, 1, 2]:
                    check_idx = idx + offset
                    if 0 <= check_idx < len(lines):
                        check_line = lines[check_idx]
                        check_text = check_line.text.strip()
                        if (abs(check_line.x0 - line.x0) < 10 and
                            len(check_text) > 3 and len(check_text) < 30 and
                            not check_line.non_black):
                            similar_count += 1
                
                # If multiple similar items in column, likely a table
                if similar_count >= 2 and not has_red_code_nearby(idx, 3):
                    return True
            return False
        
        # Extract fields
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty, page numbers, and bracketed annotations
            if not text or re.match(r'^Page \d+', text) or text.startswith('['):
                i += 1
                continue
            
            # Skip if this is non-black (colored) text that's not a title
            if line.non_black and line.size < 14.0:
                i += 1
                continue
            
            # Check if this is a field label: black text, reasonable size
            if not line.non_black and 7.5 <= line.size <= 12.0:
                
                # Skip obvious non-fields
                if re.match(r'^(Yes|No|N/A|NA|Row \d+)$', text):
                    i += 1
                    continue
                
                # Skip table headers
                if is_table_header(line, text):
                    i += 1
                    continue
                
                # Skip lab test names in columns
                if is_lab_test_name(line, text, i):
                    i += 1
                    continue
                
                # Check for red code nearby (primary field indicator)
                if has_red_code_nearby(i):
                    # Collect multi-line label
                    label_parts = [text]
                    k = i + 1
                    while k < len(lines) and k < i + 10:
                        next_line = lines[k]
                        next_text = next_line.text.strip()
                        
                        # Stop at bracketed code
                        if next_text.startswith('['):
                            break
                        
                        # Continue if similar position and style
                        if (next_text and not next_line.non_black and 
                            abs(next_line.x0 - line.x0) < 30 and
                            7.5 <= next_line.size <= 12.0 and
                            next_line.y0 - line.y0 < 50):
                            label_parts.append(next_text)
                            k += 1
                        else:
                            break
                    
                    field_label = ' '.join(label_parts).strip()
                    
                    # Final validation
                    if (field_label and len(field_label) > 2 and
                        not re.match(r'^\d+$', field_label)):
                        results.append({
                            "form_name": current_form,
                            "field_name": field_label,
                            "page": page_num
                        })
                    
                    i = k
                    continue
                
                # Check for fields with colons (questions/prompts)
                if text.endswith(':') or text.endswith('?'):
                    # Must be substantial text
                    if len(text) > 15:
                        # Look ahead to see if there's input space or continuation
                        j = i + 1
                        continuation = []
                        while j < len(lines) and j < i + 8:
                            next_line = lines[j]
                            next_text = next_line.text.strip()
                            
                            # Stop at new field or code
                            if (next_text.startswith('[') or 
                                (next_text.endswith(':') and len(next_text) > 10)):
                                break
                            
                            # Collect continuation lines (indented or marked with **)
                            if (next_text and not next_line.non_black and
                                (next_text.startswith('**') or 
                                 next_line.x0 > line.x0 + 10) and
                                7.5 <= next_line.size <= 12.0):
                                continuation.append(next_text)
                                j += 1
                            else:
                                break
                        
                        # If we have continuation or it's a standalone question
                        if continuation or '?' in text:
                            full_text = text
                            if continuation:
                                full_text = text + ' ' + ' '.join(continuation)
                            
                            results.append({
                                "form_name": current_form,
                                "field_name": full_text.strip(),
                                "page": page_num
                            })
                            i = j if continuation else i + 1
                            continue
                
                # Check for "If Yes, describe" style fields
                if text.startswith('If ') and ('describe' in text.lower() or 
                                                'specify' in text.lower() or
                                                'explain' in text.lower()):
                    results.append({
                        "form_name": current_form,
                        "field_name": text,
                        "page": page_num
                    })
                    i += 1
                    continue
                
                # Check for "assay # X" comment fields
                if ('assay' in text.lower() and '#' in text and 
                    ('comment' in text.lower() or 'investigator' in text.lower())):
                    results.append({
                        "form_name": current_form,
                        "field_name": text,
                        "page": page_num
                    })
                    i += 1
                    continue
            
            i += 1
    
    return results
```