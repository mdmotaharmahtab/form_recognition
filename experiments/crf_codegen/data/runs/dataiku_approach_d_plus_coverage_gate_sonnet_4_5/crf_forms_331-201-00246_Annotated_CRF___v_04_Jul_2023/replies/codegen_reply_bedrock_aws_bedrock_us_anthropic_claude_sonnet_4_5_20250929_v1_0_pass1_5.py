STRATEGY:

This revision addresses the specific issues found in the audit:

1. **Form title handling**: Continue carrying forward the current form title across pages. Form titles are large (≥14pt) blue/colored text. On pages where no title appears (like cluster 3, 4 pages with only option lists), the previous form title persists.

2. **False positive elimination (structural approach)**:
   - "90 days after the last dose of IMP?- mark the selected methods below **" (page 44): This is instructional text, not a field. It lacks a red code nearby and contains "**" which marks instructions.
   - "If Yes, describe Row 10" (page 130): This is a table row label, not a field. Detect by "Row \d+" pattern combined with short text.
   - "Urea nitrogen Uric acid" (page 466): These are column headers in a lab results table, appearing at top of page in a horizontal sequence without red codes.
   - "Glycated Hemoglobin" (page 868): This is a test name in a table, not a field label. It appears in a vertical list of similar short items without red codes.

3. **Missing field recovery**:
   - "Or did you think it was possible you could have died from ____?" (page 263): This is a question field. Ensure questions ending with "?" are captured even without red codes, especially multi-line questions.
   - "Chemistry clinically significant abnormal assay # 3" (page 466): The "assay # X" pattern must be detected even when preceded by other text.

4. **Cluster 3, 4, 5 coverage** (table of contents / option list pages):
   - Cluster 5 (pages 5, 8): These are table-of-contents pages with numbered section titles in blue. These are NOT data-entry fields - they're navigation. Skip them.
   - Cluster 3 (pages 936, 939): These are reference lists (medication forms, routes) - vertical option lists. NOT fields. Skip them.
   - Cluster 4 (pages 398, 691): These show only a form title, no fields. Correctly extract nothing.

5. **Structural discriminators**:
   - Real fields: Have red codes nearby OR end with ":" or "?" and are substantial (>15 chars) OR contain "assay #" pattern
   - Table headers: Short text (<30 chars), near top of page (y0 < 250), horizontally aligned with similar items, no red codes
   - Option lists: Vertically aligned short items (same x0 ±15, uniform spacing), no colons/questions, no red codes
   - Instructions: Contain "**" markers, "mark the selected" phrases, or start with "Note:"
   - TOC entries: Numbered section titles (e.g., "3.120.") in blue, not followed by red codes

6. **Remove hardcoded string filters**: Replace literal text blocklists with structural position/style checks.

```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title: large blue text, typically size 14+
        for line in lines:
            if line.size >= 14.0 and line.non_black:
                text = line.text.strip()
                # Filter out page numbers and very short text
                # Skip TOC-style numbered entries (e.g., "3.120. Title")
                if (text and not re.match(r'^Page \d+', text) and 
                    not re.match(r'^\d+$', text) and len(text) > 5 and
                    not re.match(r'^\d+\.\d+\.', text)):
                    current_form = text
                    break
        
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
        
        # Helper: check if this is part of a horizontal sequence (table header)
        def is_horizontal_header(line, text, idx):
            # Short text, near top of page
            if len(text) > 30 or line.y0 > 250:
                return False
            
            # Look for horizontally aligned similar items
            horizontal_neighbors = []
            for other_idx, other_line in enumerate(lines):
                if other_idx == idx:
                    continue
                other_text = other_line.text.strip()
                # Similar y position (same row), different x (same line horizontally)
                if (abs(other_line.y0 - line.y0) < 5 and
                    abs(other_line.x0 - line.x0) > 30 and
                    not other_line.non_black and
                    len(other_text) > 2 and len(other_text) < 30):
                    horizontal_neighbors.append(other_line)
            
            # If we have 2+ items in a horizontal row, likely a table header
            return len(horizontal_neighbors) >= 2
        
        # Helper: check if this is part of a vertical option list
        def is_option_list_item(line, text, idx):
            # Option lists: short items, vertically aligned, evenly spaced, no field markers
            if len(text) > 40 or ':' in text or '?' in text:
                return False
            
            # Look for similar items above and below at same x position
            similar_items = []
            for offset in range(-5, 6):
                if offset == 0:
                    continue
                check_idx = idx + offset
                if 0 <= check_idx < len(lines):
                    check_line = lines[check_idx]
                    check_text = check_line.text.strip()
                    # Same x position, similar size, black text, short
                    if (abs(check_line.x0 - line.x0) < 15 and
                        abs(check_line.size - line.size) < 1.0 and
                        not check_line.non_black and
                        len(check_text) > 2 and len(check_text) < 40 and
                        not check_text.startswith('[')):
                        similar_items.append((check_idx, check_line))
            
            # If we have 3+ similar items in a column, it's likely an option list
            if len(similar_items) >= 3:
                # Check spacing is relatively uniform (suggesting a form control)
                if len(similar_items) >= 2:
                    spacings = []
                    sorted_items = sorted(similar_items, key=lambda x: x[1].y0)
                    for i in range(len(sorted_items) - 1):
                        spacing = sorted_items[i+1][1].y0 - sorted_items[i][1].y0
                        spacings.append(spacing)
                    # Uniform spacing (within 10 points)
                    if spacings and max(spacings) - min(spacings) < 15:
                        return True
            
            return False
        
        # Helper: check if text is instructional
        def is_instruction(text):
            # Instructions contain specific markers
            if '**' in text:
                return True
            if re.search(r'mark the selected|note:|select all that apply', text, re.IGNORECASE):
                return True
            return False
        
        # Helper: check if text looks like a sentence fragment
        def is_sentence_fragment(text):
            # Fragments often start with lowercase or common continuation words
            if not text:
                return True
            first_word = text.split()[0] if text.split() else ""
            # Starts with lowercase (except "pH" and similar)
            if first_word and first_word[0].islower() and first_word not in ['pH']:
                return True
            # Common continuation patterns
            if re.match(r'^(and|or|but|except|despite|similar to|associated with)', text, re.IGNORECASE):
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
            
            # Skip TOC entries (numbered like "3.120.")
            if re.match(r'^\d+\.\d+\.', text):
                i += 1
                continue
            
            # Check if this is a field label: black text, reasonable size
            if not line.non_black and 7.5 <= line.size <= 12.0:
                
                # Skip instructions
                if is_instruction(text):
                    i += 1
                    continue
                
                # Skip table headers (horizontal sequences)
                if is_horizontal_header(line, text, i):
                    i += 1
                    continue
                
                # Skip option list items (vertical sequences)
                if is_option_list_item(line, text, i):
                    i += 1
                    continue
                
                # Skip sentence fragments
                if is_sentence_fragment(text):
                    i += 1
                    continue
                
                # Check for "assay # X" fields anywhere in text - these are always valid fields
                if re.search(r'assay\s*#\s*\d+', text, re.IGNORECASE):
                    results.append({
                        "form_name": current_form,
                        "field_name": text,
                        "page": page_num
                    })
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
                    
                    # Final validation - not a fragment, not instruction
                    if (field_label and len(field_label) > 2 and
                        not re.match(r'^\d+$', field_label) and
                        not is_sentence_fragment(field_label) and
                        not is_instruction(field_label)):
                        results.append({
                            "form_name": current_form,
                            "field_name": field_label,
                            "page": page_num
                        })
                    
                    i = k
                    continue
                
                # Check for fields with colons or questions (questions/prompts)
                if text.endswith(':') or text.endswith('?') or '?' in text:
                    # Must be substantial text
                    if len(text) > 15:
                        # Look ahead to see if there's continuation
                        j = i + 1
                        continuation = []
                        while j < len(lines) and j < i + 8:
                            next_line = lines[j]
                            next_text = next_line.text.strip()
                            
                            # Stop at new field or code
                            if (next_text.startswith('[') or 
                                (next_text.endswith(':') and len(next_text) > 10)):
                                break
                            
                            # Collect continuation lines (indented or close by)
                            if (next_text and not next_line.non_black and
                                (next_line.x0 > line.x0 + 10 or 
                                 abs(next_line.x0 - line.x0) < 30) and
                                7.5 <= next_line.size <= 12.0 and
                                next_line.y0 - line.y0 < 30 and
                                not is_sentence_fragment(next_text) and
                                not is_instruction(next_text)):
                                continuation.append(next_text)
                                j += 1
                            else:
                                break
                        
                        # Build full text
                        full_text = text
                        if continuation:
                            full_text = text + ' ' + ' '.join(continuation)
                        
                        # Validate not a fragment or instruction
                        if (not is_sentence_fragment(full_text) and
                            not is_instruction(full_text)):
                            results.append({
                                "form_name": current_form,
                                "field_name": full_text.strip(),
                                "page": page_num
                            })
                        i = j if continuation else i + 1
                        continue
                
                # Check for "If Yes, describe" style fields (but not "Row X" labels)
                if (text.startswith('If ') and 
                    ('describe' in text.lower() or 'specify' in text.lower() or 'explain' in text.lower()) and
                    not re.search(r'Row\s+\d+', text)):
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