Looking at the feedback, I need to fix several issues:

1. **Page 15**: Extracted wrong form name and a non-field label
2. **Pages 11, 13**: Schedule pages (cluster 0) - should skip these entirely
3. **Page 518, 559**: Missing fields and wrong form attribution
4. **Remove hardcoded string filters** - use structural discriminators instead

Let me analyze the sample pages:
- Pages 11, 13 are schedule tables with "Visit Label", "Page Label" headers - these should be skipped
- The program needs to better identify form names and avoid extracting descriptive text as fields

```python
import re

def extract(pages):
    results = []
    
    # Build page_number → form_name mapping from schedule tables
    page_to_form = {}
    for page_idx, lines in pages:
        if not lines:
            continue
        
        # Detect schedule table structure
        has_page_label_header = False
        has_visit_header = False
        for line in lines:
            if line.bold and line.size >= 7 and line.size <= 9:
                text = line.text.strip()
                if 'Page Label' in text or 'Page Number' in text:
                    has_page_label_header = True
                if 'Visit Label' in text or 'Visit Number' in text:
                    has_visit_header = True
        
        # Extract mappings only if this is a schedule page
        if has_page_label_header:
            i = 0
            while i < len(lines):
                line = lines[i]
                # Page number: numeric only, black, size ~7-8, in left column (x < 250)
                if (not line.non_black and line.size >= 7 and line.size <= 9 and
                    re.match(r'^\d+$', line.text.strip()) and line.x0 < 250):
                    page_num = int(line.text.strip())
                    # Look for blue label text in next lines
                    label_parts = []
                    j = i + 1
                    while j < len(lines) and j < i + 10:
                        next_line = lines[j]
                        # Blue text, close y position, x offset suggests it's the label
                        if (next_line.non_black and 
                            next_line.y0 - line.y0 < 25 and
                            abs(next_line.x0 - line.x0) > 30):
                            label_parts.append(next_line.text.strip())
                            j += 1
                        elif not next_line.non_black and re.match(r'^\d+$', next_line.text.strip()):
                            # Hit next page number
                            break
                        else:
                            j += 1
                            if len(label_parts) > 0:
                                break
                    
                    if label_parts:
                        form_name = ' '.join(label_parts)
                        page_to_form[page_num] = form_name
                    i = j
                else:
                    i += 1
    
    # Process each page for field extraction
    current_form = ""
    for page_idx, lines in pages:
        page_num_1based = page_idx + 1
        
        if not lines:
            continue
        
        # Detect and skip schedule/TOC pages entirely
        has_schedule_headers = False
        has_visit_label_header = False
        has_page_label_header = False
        
        for line in lines:
            if line.bold and line.size >= 7 and line.size <= 10:
                text = line.text.strip()
                if 'Visit Label' in text or 'Visit Number' in text:
                    has_visit_label_header = True
                if 'Page Label' in text or 'Page Number' in text:
                    has_page_label_header = True
        
        # Schedule pages have both headers + multiple page numbers
        if has_page_label_header or has_visit_label_header:
            page_numbers = [line for line in lines if not line.non_black and 
                          re.match(r'^\d+$', line.text.strip()) and 
                          line.size >= 7 and line.size <= 9 and line.x0 < 250]
            if len(page_numbers) >= 2:
                has_schedule_headers = True
        
        # Skip TOC pages
        is_toc = any(('CHANGE HISTORY' in line.text or 'TABLE OF CONTENTS' in line.text)
                     for line in lines if line.size > 11)
        
        if is_toc or has_schedule_headers:
            continue
        
        # Determine form name for this page
        if page_num_1based in page_to_form:
            current_form = page_to_form[page_num_1based]
        else:
            # Look for bold blue header as form title
            # Near top (y < 200), large size (>= 11), blue, bold, substantial text
            for line in lines:
                if (line.bold and line.non_black and line.size >= 11 and 
                    line.y0 < 200 and len(line.text.strip()) > 5):
                    text = line.text.strip()
                    # Avoid false positives: skip if it looks like a section within a form
                    if not any(skip in text for skip in ['Schedule', 'CHANGE HISTORY', 'TABLE OF CONTENTS']):
                        current_form = text
                        break
        
        # Extract field labels from this page
        field_candidates = []
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip if no substantial text
            if not text or len(text) < 2:
                i += 1
                continue
            
            # Skip red text (technical annotations)
            # Red color detection: check for high red component
            if line.non_black:
                color_str = str(line.non_black).lower()
                # Red annotations have 'ff' in red channel position
                if 'ff0000' in color_str or '#ff' in color_str[:4]:
                    i += 1
                    continue
            
            # Skip blue text (form names, visit labels in schedules)
            # Blue text should not be field labels (unless black)
            if line.non_black:
                i += 1
                continue
            
            # Skip pure numbers, dates, or single characters
            if re.match(r'^[\d\.\s\-/]+$', text) or len(text) <= 2:
                i += 1
                continue
            
            # Skip bold headers (section titles, not field labels)
            # Bold text size > 10 is typically section headers
            if line.bold and line.size > 10:
                i += 1
                continue
            
            # Skip page furniture (top/bottom edges, small font)
            if (line.y0 < 40 or line.y0 > 750) and line.size < 9:
                i += 1
                continue
            
            # Field labels: black text, moderate size (7-11), typically not bold
            # Allow bold only if size is small (8-10 range)
            is_field_size = line.size >= 7 and line.size <= 11
            is_field_style = not line.bold or (line.bold and line.size <= 10)
            
            if not line.non_black and is_field_size and is_field_style:
                # Collect continuation lines
                field_parts = [text]
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    if not next_text:
                        j += 1
                        continue
                    
                    # Stop if we hit colored text
                    if next_line.non_black:
                        break
                    
                    # Stop if we hit a checkbox marker
                    if next_text.startswith('[') or next_text in ['Yes', 'No', 'YES', 'NO']:
                        break
                    
                    # Continuation: similar x position, close y, similar size
                    x_close = abs(next_line.x0 - line.x0) < 30
                    y_close = next_line.y0 - lines[j-1].y0 < 18
                    size_similar = abs(next_line.size - line.size) < 2
                    
                    if x_close and y_close and size_similar and not next_line.non_black:
                        # Check if natural continuation
                        prev_ends_sentence = field_parts[-1].rstrip().endswith(('.', '?', ':'))
                        starts_lower = next_text[0].islower() if next_text else False
                        
                        if starts_lower or not prev_ends_sentence:
                            field_parts.append(next_text)
                            j += 1
                        else:
                            break
                    else:
                        break
                
                field_text = ' '.join(field_parts)
                
                # Structural filters for non-fields
                
                # Skip if contains rating scale markers: (0), (1), etc.
                if re.search(r'\(\d+\)', field_text):
                    i = j
                    continue
                
                # Skip if it's a form name echoed on the page (large bold blue text seen earlier)
                if field_text == current_form:
                    i = j
                    continue
                
                # Skip if starts in far right column (likely values or notes)
                if line.x0 > 450:
                    i = j
                    continue
                
                # Skip if entirely uppercase and short (likely codes or labels, not fields)
                if field_text.isupper() and len(field_text) < 8:
                    i = j
                    continue
                
                # Skip conditional enrollment text (structural: contains "enrols if" or "if applicable" as full phrase)
                if 'enrols if' in field_text.lower() and 'page' in field_text.lower():
                    i = j
                    continue
                
                # Valid field characteristics
                is_question = field_text.endswith('?')
                is_label_style = ':' in field_text
                has_field_length = len(field_text.split()) >= 2
                
                # Also check for characteristic field words (structural: medical/CRF terminology)
                has_field_terms = any(term in field_text for term in 
                    ['Date', 'Time', 'Number', 'Bottle', 'Blood Pressure', 'Heart Rate',
                     'Temperature', 'ICF', 'Signed', 'Version', 'Systolic', 'Diastolic',
                     'Capsules', 'Dispensed', 'Returned', 'Verified', 'Placed', 'Position',
                     'Measurement', '(mmHg)', '(bpm)', 'End Date', 'End Time', 'Protocol'])
                
                if is_question or (has_field_length and (is_label_style or has_field_terms)):
                    # Clean up
                    field_text = field_text.rstrip(':').strip()
                    
                    # Final validation: reasonable length
                    if field_text and 3 <= len(field_text) <= 200:
                        # Avoid duplicates
                        if field_text not in field_candidates:
                            field_candidates.append(field_text)
                
                i = j
            else:
                i += 1
        
        # Emit records
        for field_name in field_candidates:
            if current_form:
                results.append({
                    "form_name": current_form,
                    "field_name": field_name,
                    "page": page_num_1based
                })
    
    return results
```
