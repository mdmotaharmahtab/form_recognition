I'll analyze the issues and rewrite the program to fix them while maintaining existing coverage.

Key problems to address:
1. **Change History tables** (pages 11-14): Extracting table cell content ("Changed By", dates, etc.) instead of column headers
2. **C-SSRS forms** (pages 109, 120, 250, 261, 683): Extracting rating scale anchors, version numbers, disclaimers, and instruction text
3. **TOC pages** (cluster 6, pages 5, 8): Blue hyperlinks being ignored correctly, but 0% coverage - these are TOC pages with no data-entry fields (correct to ignore)
4. **Over-reliance on literal blocklists**: Need structural rules instead

Let me rewrite with structural improvements:

```python
import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Sort lines by y, then x for processing
        sorted_lines = sorted(lines, key=lambda ln: (ln.y0, ln.x0))
        
        # Detect form name: large text (size >= 14), often colored or bold
        # Typically at top of page (y < 350)
        # EXCLUDE blue TOC links (#2477cc)
        form_candidates = []
        for line in sorted_lines:
            if line.y0 < 350 and line.size >= 14:
                text = line.text.strip()
                # Skip page numbers
                if re.search(r'^Page\s+\d+\s+of\s+\d+', text, re.I):
                    continue
                # Skip pure numbers (table row numbers)
                if re.match(r'^\d+(\.\d+)?\.?\s*$', text):
                    continue
                # Skip blue TOC hyperlinks
                if line.non_black and '#2477cc' in str(line.non_black).lower():
                    continue
                # Valid form title
                if len(text) > 3:
                    form_candidates.append((line.y0, text))
        
        # Pick the topmost substantial form title
        if form_candidates:
            form_candidates.sort()
            current_form = form_candidates[0][1]
        
        # DETECT PAGE LAYOUT TYPES
        
        # 1. TOC pages: many blue hyperlinks, large font
        blue_link_count = sum(1 for line in sorted_lines 
                             if line.non_black and '#2477cc' in str(line.non_black).lower() 
                             and line.size >= 14)
        is_toc_page = blue_link_count >= 10
        
        if is_toc_page:
            # TOC pages have no data-entry fields, skip extraction
            continue
        
        # 2. Detect table structure: analyze x-coordinate alignment
        # Real tables have content aligned in distinct columns
        x_positions = defaultdict(list)
        for line in sorted_lines:
            if 100 < line.y0 < 800 and line.size >= 8 and line.size < 14:
                # Round x to 20-point buckets to find columns
                x_bucket = round(line.x0 / 20) * 20
                x_positions[x_bucket].append(line)
        
        # Count distinct vertical columns with 5+ items each
        substantial_columns = sum(1 for items in x_positions.values() if len(items) >= 5)
        is_table_page = substantial_columns >= 3
        
        # 3. Detect C-SSRS style forms: look for version/disclaimer footer patterns
        has_version_footer = any(
            'version' in line.text.lower() and line.y0 > 700 and line.size < 10
            for line in sorted_lines
        )
        has_disclaimer = any(
            'disclaimer' in line.text.lower() and line.y0 > 650
            for line in sorted_lines
        )
        is_cssrs_form = has_version_footer or has_disclaimer
        
        # Extract fields using structural rules
        field_lines = []
        
        for line in sorted_lines:
            text = line.text.strip()
            
            # Skip empty
            if not text:
                continue
            
            # STRUCTURAL FILTERS
            
            # 1. Skip red annotations (technical metadata)
            if line.non_black and '#ff0000' in str(line.non_black).lower():
                continue
            
            # 2. Skip blue TOC hyperlinks (#2477cc)
            if line.non_black and '#2477cc' in str(line.non_black).lower():
                continue
            
            # 3. Skip page numbers (template marker - literal match OK)
            if re.search(r'^Page\s+\d+\s+of\s+\d+', text, re.I):
                continue
            
            # 4. Skip very large text (>= 14pt) - those are headers/titles, not fields
            if line.size >= 14:
                continue
            
            # 5. Skip very small text (< 8pt) - typically footnotes
            if line.size < 8:
                continue
            
            # 6. Skip lines at extreme page edges (page furniture)
            if line.y0 < 100 or line.y0 > 800:
                continue
            
            # 7. C-SSRS form-specific filters (structural position-based)
            if is_cssrs_form:
                # Skip footer area (version info, disclaimers) - below line 650
                if line.y0 > 650:
                    continue
                
                # Skip rating scale anchors: parenthesized numbers at start
                # Pattern: "(0)", "(1)", "(1-5)", etc.
                if re.match(r'^\([0-9\-]+\)', text):
                    continue
                
                # Skip rating scale descriptors: short phrases following anchors
                # These appear at same y-level as anchors, are NOT bold, and are short
                if not line.bold and len(text) < 50 and ',' in text:
                    # Check if looks like scale text: "Less than once a week, (2) Once a"
                    if re.search(r'\(\d+\)', text) or text.count(',') >= 2:
                        continue
            
            # 8. Skip long prose (instructions, disclaimers)
            # Multi-sentence text or very long single sentence
            if len(text) > 120:
                sentence_markers = text.count('. ') + text.count('? ') + text.count('! ')
                if sentence_markers >= 1 or (text.endswith('.') and len(text) > 100):
                    continue
            
            # 9. TABLE-SPECIFIC FILTERS
            if is_table_page:
                # On table pages, field labels are typically:
                # - Column headers: at top of table (y < median y of table content)
                # - Row headers: at leftmost column (x < 200)
                # - Bold or slightly larger than table cell content
                
                # Calculate median y of table content
                table_y_values = [ln.y0 for ln in sorted_lines if 150 < ln.y0 < 750 and 8 <= ln.size < 14]
                if table_y_values:
                    median_y = sorted(table_y_values)[len(table_y_values) // 2]
                else:
                    median_y = 400
                
                # Skip table cell content (regular text in middle/right columns, below header area)
                is_in_header_row = line.y0 < min(median_y - 100, 300)
                is_leftmost_column = line.x0 < 200
                is_emphasized = line.bold or line.size >= 11
                
                # Keep only if it's a likely label (header or emphasized)
                if not (is_in_header_row or is_leftmost_column or is_emphasized):
                    continue
                
                # Skip short entries that look like table data values
                # Pattern: 1-3 words, capitalized, no punctuation
                words = text.split()
                if len(words) <= 3 and not any(c in text for c in ['?', ':', '(', ')']):
                    # Check if all words are capitalized (likely proper nouns in table cells)
                    if all(w[0].isupper() for w in words if w and len(w) > 0):
                        # Not a label unless it has structural words
                        has_structure = any(w.lower() in ['the', 'a', 'an', 'of', 'for', 'to', 'in', 'at', 'on', 'by', 'with', 'number', 'date', 'name', 'label'] for w in words)
                        if not has_structure:
                            continue
                
                # Skip standalone dates (mm-mmm-yyyy format common in change tables)
                if re.match(r'^(\d{1,2}[\-/]\w{3}[\-/]\d{4}|\d{1,2}\w{3}\d{4})$', text, re.I):
                    continue
                
                # Skip version numbers
                if re.match(r'^\d+\.\d+(\.\d+)?$', text):
                    continue
            
            # 10. Skip answer options and checkbox values
            # Single-word gray/colored text, common option words
            if line.non_black and len(text.split()) <= 2:
                option_words = {'yes', 'no', 'x', 'n/a', 'male', 'female', 'true', 'false'}
                if text.lower() in option_words:
                    continue
            
            # 11. Skip pure bracketed text (annotations)
            if text.startswith('[') and text.endswith(']'):
                continue
            
            # 12. Skip copyright and URLs (template markers)
            if '©' in text or 'copyright' in text.lower() or 'http' in text.lower():
                continue
            
            # 13. Skip pure punctuation or enumeration
            if re.match(r'^[•\-\d.,:;()\[\]\/\s]+$', text):
                continue
            
            # 14. Skip enumeration codes (uppercase letters + digits, no spaces)
            if re.match(r'^[A-Z]{2,6}\d+$', text):
                continue
            
            # POSITIVE SELECTION: Likely field labels
            # - Black or dark text (primary content)
            # - Moderate size (8-13 pt)
            # - In main content area (y: 100-800)
            # - Has substance (length > 2)
            # - Question-like or label-like structure
            
            is_primary_text = not (line.non_black and ('#ff0000' in str(line.non_black).lower() or '#2477cc' in str(line.non_black).lower()))
            is_readable_size = 8 <= line.size <= 13
            is_main_content = 100 < line.y0 < 800
            has_substance = len(text) > 2
            
            if is_primary_text and is_readable_size and is_main_content and has_substance:
                field_lines.append(line)
        
        # Join wrapped field labels: lines close in y and similar x
        grouped_fields = []
        i = 0
        while i < len(field_lines):
            label_parts = [field_lines[i].text.strip()]
            base_x = field_lines[i].x0
            last_y = field_lines[i].y0
            j = i + 1
            
            # Look ahead for continuation lines
            while j < len(field_lines):
                dy = field_lines[j].y0 - last_y
                dx = abs(field_lines[j].x0 - base_x)
                
                # If next line is close vertically (within 25 points) and similar x (within 40)
                # it's likely a continuation
                if dy < 25 and dx < 40:
                    label_parts.append(field_lines[j].text.strip())
                    last_y = field_lines[j].y0
                    j += 1
                else:
                    break
            
            full_label = ' '.join(label_parts)
            # Clean up the label
            full_label = re.sub(r'\s+', ' ', full_label).strip()
            
            # Final validation: minimum length
            if len(full_label) > 2:
                grouped_fields.append(full_label)
            
            i = j if j > i else i + 1
        
        # Deduplicate within page
        seen = set()
        for field in grouped_fields:
            if field not in seen:
                seen.add(field)
                records.append({
                    "form_name": current_form,
                    "field_name": field,
                    "page": page_num
                })
    
    return records
```
