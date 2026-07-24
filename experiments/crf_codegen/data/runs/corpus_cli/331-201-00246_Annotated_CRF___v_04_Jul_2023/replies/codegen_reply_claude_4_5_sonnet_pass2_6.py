Looking at the issues, I need to:

1. **Add "Changed By" column** from change history tables (pages 11-12)
2. **Remove table cell data** that's being incorrectly extracted as fields
3. **Handle C-SSRS forms better** - pages 109, 110, 120, 250 are extracting junk
4. **Handle TOC pages** (cluster 6) - these are table-of-contents pages with blue hyperlinks, should extract nothing
5. **Remove all hardcoded string blocklists** and replace with structural rules

Let me rewrite the program:

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
        
        # TOC detection: page with many blue hyperlinks (#2477cc)
        blue_links = [line for line in sorted_lines if line.non_black and '#2477cc' in str(line.non_black).lower()]
        total_lines = len([line for line in sorted_lines if line.text.strip() and line.size >= 10])
        is_toc_page = len(blue_links) > 10 and total_lines > 0 and len(blue_links) / total_lines > 0.5
        
        if is_toc_page:
            # TOC pages have no data-entry fields
            continue
        
        # Detect form name: large text (size >= 14), often colored or bold
        # Typically at top of page (y < 350)
        # EXCLUDE blue TOC links and red annotations
        form_candidates = []
        for line in sorted_lines:
            if line.y0 < 350 and line.size >= 14:
                text = line.text.strip()
                # Skip page numbers
                if re.search(r'^Page\s+\d+\s+of\s+\d+', text, re.I):
                    continue
                # Skip pure numbers
                if re.match(r'^\d+(\.\d+)?\.?\s*$', text):
                    continue
                # Skip blue TOC hyperlinks
                if line.non_black and '#2477cc' in str(line.non_black).lower():
                    continue
                # Skip red annotations
                if line.non_black and '#ff0000' in str(line.non_black).lower():
                    continue
                # Valid form title
                if len(text) > 3:
                    form_candidates.append((line.y0, text))
        
        # Pick the topmost substantial form title
        if form_candidates:
            form_candidates.sort()
            current_form = form_candidates[0][1]
        
        # ANALYZE PAGE STRUCTURE
        
        # Calculate page-level metrics
        all_text_lines = [line for line in sorted_lines if line.text.strip() and line.size >= 8]
        
        if not all_text_lines:
            continue
        
        # Detect vertical columns by x-position clustering
        x_positions = defaultdict(list)
        for line in all_text_lines:
            if 100 < line.y0 < 800:
                # Round x to 30-point buckets
                x_bucket = round(line.x0 / 30) * 30
                x_positions[x_bucket].append(line)
        
        # Count substantial columns (5+ items each)
        substantial_columns = [bucket for bucket, items in x_positions.items() if len(items) >= 5]
        substantial_columns.sort()
        
        # Table detection: 3+ columns with substantial content
        is_table_page = len(substantial_columns) >= 3
        
        # Detect change history tables specifically:
        # - Has "Date" header in top area
        # - Has "Changed By" header
        # - Multiple columns
        # - Contains date-like patterns in data area
        date_headers = [line for line in sorted_lines[:30] if 'date' in line.text.lower() and line.size >= 9 and line.y0 < 400]
        changed_by_headers = [line for line in sorted_lines[:30] if 'changed' in line.text.lower() and 'by' in line.text.lower() and line.y0 < 400]
        has_dates = sum(1 for line in sorted_lines if re.search(r'\d{1,2}[-/]\w{3,}[-/]\d{4}', line.text)) >= 3
        is_change_history_table = len(date_headers) > 0 and len(changed_by_headers) > 0 and has_dates and is_table_page
        
        # C-SSRS form detection
        has_version_footer = any(
            'version' in line.text.lower() and line.y0 > 700 and line.size < 11
            for line in sorted_lines
        )
        has_disclaimer = any(
            'disclaimer' in line.text.lower() and line.y0 > 650
            for line in sorted_lines
        )
        has_cssrs_title = current_form and 'c-ssrs' in current_form.lower()
        is_cssrs_form = has_cssrs_title or has_version_footer or has_disclaimer
        
        # Extract field candidates
        field_lines = []
        
        for line in sorted_lines:
            text = line.text.strip()
            
            if not text:
                continue
            
            # UNIVERSAL FILTERS (template markers and non-content)
            
            # Skip red annotations
            if line.non_black and '#ff0000' in str(line.non_black).lower():
                continue
            
            # Skip page numbers (template marker)
            if re.search(r'^Page\s+\d+\s+of\s+\d+', text, re.I):
                continue
            
            # Skip extreme page edges (headers/footers)
            if line.y0 < 80 or line.y0 > 820:
                continue
            
            # Skip very small text (< 8pt) - footnotes
            if line.size < 8:
                continue
            
            # Skip form titles (already captured, >= 14pt)
            if line.size >= 14:
                continue
            
            # CONTEXT-SPECIFIC FILTERS
            
            # C-SSRS forms: structural position-based filtering
            if is_cssrs_form:
                # Skip footer area (version, disclaimer, copyright notices)
                if line.y0 > 650:
                    continue
                
                # Skip rating scale anchors: starts with parenthesized number
                if re.match(r'^\s*\(\d+[\d\-]*\)', text):
                    continue
                
                # Skip rating scale descriptors:
                # - Contains parenthesized numbers mid-text
                # - Multiple comma-separated phrases (scale definitions)
                if re.search(r'\(\d+\)', text) and text.count(',') >= 2:
                    continue
                
                # Skip standalone parenthetical phrases (scale anchors)
                if re.match(r'^\([^)]+\)$', text):
                    continue
                
                # Skip long prose (definitions, disclaimers)
                if len(text) > 200:
                    continue
                
                # Skip lines that are mostly lowercase and very long (prose instructions)
                if len(text) > 100:
                    lowercase_ratio = sum(1 for c in text if c.islower()) / len([c for c in text if c.isalpha()])
                    if lowercase_ratio > 0.7:
                        continue
            
            # Change history tables: extract column headers only
            if is_change_history_table:
                # Find header area: top portion before data rows
                content_y_values = [ln.y0 for ln in all_text_lines if 150 < ln.y0 < 700]
                if content_y_values:
                    # Header zone: first 100 points of content
                    min_content_y = min(content_y_values)
                    header_threshold = min_content_y + 100
                else:
                    header_threshold = 250
                
                # Only extract from header area
                if line.y0 > header_threshold:
                    continue
                
                # Headers should be:
                # - Short (< 20 chars typically)
                # - Bold or emphasized size
                # - OR single words in key columns
                is_in_header_zone = line.y0 <= header_threshold
                is_emphasized = line.bold or line.size >= 10
                is_short = len(text) < 25
                
                # Require emphasis or very short single-word
                word_count = len(text.split())
                if not is_emphasized and not (word_count <= 2 and is_short):
                    continue
                
                # Skip pure dates, version numbers, names (data cells that leaked through)
                if re.match(r'^\d{1,2}[-/]\w{3,}[-/]\d{2,4}$', text, re.I):
                    continue
                if re.match(r'^\d+\.\d+(\.\d+)?$', text):
                    continue
                # Skip person names: capitalized first+last name patterns
                if re.match(r'^[A-Z][a-z]+ [A-Z][a-z]+', text) and word_count == 2:
                    continue
                # Skip multi-word phrases that aren't question-like (data cells)
                if word_count > 3 and not any(c in text for c in ['?', ':']):
                    continue
            
            # General table pages (non-change-history)
            elif is_table_page:
                # Identify likely header area
                table_y_values = sorted([ln.y0 for ln in all_text_lines if 100 < ln.y0 < 750])
                if table_y_values:
                    median_y = table_y_values[len(table_y_values) // 2]
                    header_zone = table_y_values[0] + 120
                else:
                    median_y = 400
                    header_zone = 250
                
                is_in_header = line.y0 < header_zone
                is_leftmost = line.x0 < 200
                is_emphasized = line.bold or line.size >= 10.5
                
                # Keep headers and emphasized labels
                if not (is_in_header or is_leftmost or is_emphasized):
                    # Skip likely table data cells
                    continue
                
                # Skip standalone dates (common in table cells)
                if re.match(r'^\d{1,2}[\-/]\w{3,}[\-/]\d{2,4}$', text, re.I):
                    continue
                
                # Skip version numbers
                if re.match(r'^\d+\.\d+(\.\d+)?$', text):
                    continue
            
            # Skip long instructional prose
            if len(text) > 200:
                continue
            
            # Skip copyright, URLs
            if '©' in text or 'http' in text.lower() or '@' in text:
                continue
            
            # Skip pure bracketed annotations
            if re.match(r'^\[[^\]]+\]$', text):
                continue
            
            # Skip pure punctuation/enumeration
            if re.match(r'^[•\-\d.,:;()\[\]\/\s]+$', text):
                continue
            
            # Skip row/column labels that are just numbers or single letters
            if re.match(r'^(Row|Column|Col)?\s*[A-Z]?\d+$', text, re.I):
                continue
            
            # POSITIVE SELECTION
            # Primary content: black/dark text, readable size, main area
            is_primary_text = not line.non_black or not ('#ff0000' in str(line.non_black).lower())
            is_readable_size = 8 <= line.size <= 13.5
            is_main_content = 100 < line.y0 < (650 if is_cssrs_form else 800)
            has_substance = len(text) > 2
            
            # Additional positive signals for field labels
            has_question_mark = '?' in text
            has_colon = ':' in text and text.count(':') <= 2
            
            # For short text (< 20 chars), require stronger signals
            if len(text) < 20:
                if not (has_question_mark or has_colon or line.bold or line.size >= 10.5):
                    # Allow if in leftmost column of table (likely row header)
                    if not (is_table_page and line.x0 < 200):
                        continue
            
            if is_primary_text and is_readable_size and is_main_content and has_substance:
                field_lines.append(line)
        
        # Group wrapped field labels: lines close in y and similar x
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
                
                # Continuation if close vertically (< 25) and similar x (< 50)
                if dy < 25 and dx < 50:
                    label_parts.append(field_lines[j].text.strip())
                    last_y = field_lines[j].y0
                    j += 1
                else:
                    break
            
            full_label = ' '.join(label_parts)
            full_label = re.sub(r'\s+', ' ', full_label).strip()
            
            # Final validation
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
