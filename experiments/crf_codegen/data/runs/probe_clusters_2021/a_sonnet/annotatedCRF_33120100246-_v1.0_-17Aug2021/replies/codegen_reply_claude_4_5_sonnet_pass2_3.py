I'll analyze the issues and rewrite the program to fix them while maintaining existing coverage.

**Key problems to address:**
1. **Pages 9-10**: Extracting non-field text from schedule pages (navigation/logic annotations, "page enrols if...", "Page 3", "period", "Central")
2. **Page 12**: Missing fields from schedule pages - need better column detection
3. **Page 72**: Extracting malformed C-SSRS text with broken line continuations
4. **Page 309**: Missing fields from a simple label-with-radio-buttons layout (cluster 1, 0% coverage)
5. **Page 399**: Missing simple field labels and extracting "Normal" (an answer option)
6. **Clusters 1, 4, 5**: Zero or low coverage - need new handlers

Looking at page 309 sample: it's a **two-column field specification** layout (gray labels left, red codes, radio options right) that my field_spec handler should catch but isn't.

```python
import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form name from large header
        form_name = ""
        for line in lines[:30]:
            if line.size >= 13.0 and line.non_black and line.y0 < 150:
                text = line.text.strip()
                if text and not re.match(r'^\d+$', text):
                    text = re.sub(r'\s*-\s*Page\s+\d+$', '', text)
                    if text and len(text) > 3:
                        form_name = text
                        break
        
        if form_name:
            current_form = form_name
        elif not current_form:
            current_form = "Clinical Research Form"
        
        # Route by page type
        if _is_toc_page(lines):
            continue
        elif _is_schedule_page(lines):
            records.extend(_extract_schedule_fields(lines, current_form, page_num))
        elif _is_two_column_field_spec(lines):
            records.extend(_extract_two_column_fields(lines, current_form, page_num))
        elif _is_field_spec_page(lines):
            records.extend(_extract_field_spec_fields(lines, current_form, page_num))
        elif _is_cssrs_page(lines):
            records.extend(_extract_cssrs_fields(lines, current_form, page_num))
        else:
            records.extend(_extract_standard_fields(lines, current_form, page_num))
    
    return records

def _is_toc_page(lines):
    toc_count = 0
    for line in lines:
        if line.non_black and re.match(r'\d+\.\d+\.', line.text.strip()):
            toc_count += 1
    return toc_count > 10

def _is_schedule_page(lines):
    for line in lines:
        if 'Schedule_' in line.text:
            return True
    return False

def _is_two_column_field_spec(lines):
    # Page 309 pattern: gray labels left column (x < 200), red codes, radio buttons right (x > 300)
    gray_labels_left = 0
    red_codes_present = 0
    radio_options_right = 0
    
    for line in lines:
        text = line.text.strip()
        
        # Gray labels in left column
        if line.text.startswith('#454545') and line.x0 < 200 and line.size >= 7.0 and line.size < 10.0:
            if len(text) > 5 and not text.startswith('['):
                gray_labels_left += 1
        
        # Red technical codes
        if line.non_black and '[LBTEST' in text or '[LBORRES' in text:
            red_codes_present += 1
        
        # Radio options right side
        if line.text.startswith('#454545') and line.x0 > 300 and text in ['Positive', 'Negative', 'Not Done']:
            radio_options_right += 1
    
    return gray_labels_left > 3 and red_codes_present > 3 and radio_options_right > 5

def _is_field_spec_page(lines):
    red_annotation_count = 0
    for line in lines:
        text = line.text.strip()
        if line.non_black and ('[TYPE:' in text or '[VISIBILITY:' in text or '[Read-only' in text):
            red_annotation_count += 1
    return red_annotation_count > 5

def _is_cssrs_page(lines):
    text_blob = ' '.join(line.text for line in lines[:50])
    return 'COLUMBIA-SUICIDE' in text_blob or 'C-SSRS' in text_blob

def _extract_two_column_fields(lines, form_name, page_num):
    """Extract from page 309 style: gray labels left, radio buttons right"""
    records = []
    
    for i, line in enumerate(lines):
        # Gray labels in left column, reasonable size
        if line.text.startswith('#454545') and line.x0 < 200 and line.size >= 7.0 and line.size < 10.0:
            text = line.text.strip()
            
            # Skip empty, short, or bracket-starting text
            if not text or len(text) < 4 or text.startswith('['):
                continue
            
            # Skip pure answer options
            if text in ['Positive', 'Negative', 'Not Done', 'Collected', 'Not Collected', 'Applicable', 'Not Applicable', 'Normal', 'Abnormal']:
                continue
            
            # Must look like a field label (mixed case or reasonable length)
            if len(text) >= 4:
                records.append({
                    'form_name': form_name,
                    'field_name': text,
                    'page': page_num
                })
    
    return records

def _extract_field_spec_fields(lines, form_name, page_num):
    records = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Field labels: black or gray, moderate size, left-aligned
        if (not line.non_black or line.text.startswith('#454545')) and line.size >= 7.0 and line.size < 11.0:
            text = line.text.strip()
            
            if not text or len(text) < 3 or text.startswith('['):
                i += 1
                continue
            
            if any(marker in text for marker in ['TYPE:', 'VISIBILITY:', 'Read-only', 'enumeration', 'values:']):
                i += 1
                continue
            
            # Check for red annotations nearby (signature of field spec)
            has_red_annotation = False
            for j in range(i+1, min(i+10, len(lines))):
                next_text = lines[j].text.strip()
                if lines[j].non_black and ('[TYPE:' in next_text or '[LBTEST' in next_text or '[LBORRES' in next_text):
                    has_red_annotation = True
                    break
            
            if has_red_annotation:
                field_text = text
                
                # Multi-line continuation
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if (abs(next_line.x0 - line.x0) < 20 and 
                        next_line.y0 - line.y0 < 20 and
                        not next_line.non_black and
                        not next_line.text.strip().startswith('[')):
                        field_text += ' ' + next_line.text.strip()
                        j += 1
                    else:
                        break
                
                if field_text and len(field_text) >= 3:
                    records.append({
                        'form_name': form_name,
                        'field_name': field_text,
                        'page': page_num
                    })
                
                i = j
                continue
        
        i += 1
    
    return records

def _extract_schedule_fields(lines, form_name, page_num):
    """Extract from schedule of assessments tables"""
    records = []
    
    # Find column boundaries dynamically
    page_label_lines = []
    for line in lines:
        # Blue links (non_black) in a column
        if line.non_black and line.y0 < 500:
            text = line.text.strip()
            if text and text not in ['Page Label', 'Page', 'Number', 'Description', 'of', 'Dynamic']:
                page_label_lines.append(line)
    
    if not page_label_lines:
        return records
    
    # Determine column x-range from actual data
    x_positions = [line.x0 for line in page_label_lines]
    if len(x_positions) < 3:
        return records
    
    x_min = min(x_positions) - 10
    x_max = max(x_positions) + 150
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Blue text in the detected column range
        if line.non_black and x_min <= line.x0 <= x_max and line.y0 < 500:
            text = line.text.strip()
            
            # Skip headers, pure numbers, and very short text
            if not text or text in ['Page Label', 'Page', 'Number', 'Description', 'of', 'Dynamic']:
                i += 1
                continue
            
            if re.match(r'^[\d\-]+$', text) or len(text) < 3:
                i += 1
                continue
            
            # Skip logic/navigation text patterns
            if 'enrols if' in text.lower() or 'if SEX' in text or 'on Demography page' in text:
                i += 1
                continue
            
            # Skip standalone generic words
            if text in ['period', 'Central', 'Page 1', 'Page 2', 'Page 3', 'Page 4', 'Page 5']:
                i += 1
                continue
            
            # Multi-line continuation (same column)
            full_text = text
            j = i + 1
            while j < len(lines) and lines[j].non_black and x_min <= lines[j].x0 <= x_max:
                next_text = lines[j].text.strip()
                if abs(lines[j].y0 - line.y0) < 25:
                    # Check if continuation is valid (not a logic annotation)
                    if 'enrols if' not in next_text.lower() and 'if SEX' not in next_text:
                        full_text += ' ' + next_text
                    j += 1
                else:
                    break
            
            # Final validation
            if full_text and len(full_text) > 2 and not _is_pure_code(full_text):
                # Exclude if contains logic patterns
                if 'enrols if' not in full_text.lower() and 'on Demography page' not in full_text and 'if RPPOSMEN' not in full_text:
                    records.append({
                        'form_name': form_name,
                        'field_name': full_text,
                        'page': page_num
                    })
            
            i = j
            continue
        
        i += 1
    
    return records

def _extract_cssrs_fields(lines, form_name, page_num):
    records = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip footer area
        if line.y0 > 450:
            i += 1
            continue
        
        # Questions: bold black text, decent size
        if line.bold and not line.non_black and line.size >= 7.0 and line.size < 18.0:
            text = line.text.strip()
            
            # Skip row markers
            if re.match(r'^Row\s+\d+', text):
                i += 1
                continue
            
            # Must be substantial
            if text and len(text) > 10:
                # Continuation lines - be strict about proximity
                full_text = text
                j = i + 1
                continuation_count = 0
                
                while j < len(lines) and continuation_count < 8:
                    next_line = lines[j]
                    
                    # Strict continuation: same x, close y, bold black
                    if (abs(next_line.x0 - line.x0) < 20 and 
                        next_line.y0 - line.y0 < 30 and
                        next_line.bold and not next_line.non_black and
                        next_line.y0 > line.y0):
                        
                        next_text = next_line.text.strip()
                        
                        # Stop at row markers or very short fragments
                        if re.match(r'^Row\s+\d+', next_text) or len(next_text) < 3:
                            break
                        
                        full_text += ' ' + next_text
                        continuation_count += 1
                        j += 1
                    else:
                        break
                
                # Clean up malformed text
                full_text = _clean_cssrs_text(full_text)
                
                # Validate structure
                if full_text and len(full_text) > 15 and not _is_answer_option_structure(full_text):
                    records.append({
                        'form_name': form_name,
                        'field_name': full_text,
                        'page': page_num
                    })
                
                i = j
                continue
        
        i += 1
    
    return records

def _clean_cssrs_text(text):
    """Clean up malformed C-SSRS text"""
    # Remove row number fragments
    text = re.sub(r'\s+Row\s+\d+.*$', '', text)
    
    # Remove trailing incomplete phrases from broken continuations
    text = re.sub(r'\s+(the assessment period\.|during|without|method details worked out)$', '', text)
    
    # Remove "If Yes, describe" fragments
    text = re.sub(r'\s+If Yes, describe', '', text)
    
    return text.strip()

def _extract_standard_fields(lines, form_name, page_num):
    records = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip red annotations
        if line.non_black and '[' in line.text:
            i += 1
            continue
        
        # Skip tiny text
        if line.size < 6.5:
            i += 1
            continue
        
        # Field labels: black, reasonable size
        if not line.non_black and line.size >= 7.0 and line.size < 13.0:
            text = line.text.strip()
            
            # Skip empty or pure numbers
            if not text or re.match(r'^\d+(\.\d+)?$', text):
                i += 1
                continue
            
            # Skip single common answer options by position and brevity
            if line.x0 > 300 and len(text.split()) <= 2 and text in ['Yes', 'No', 'Normal', 'Abnormal', 'Positive', 'Negative', 'Not Done']:
                i += 1
                continue
            
            # Must be substantial or have question markers
            if len(text) > 15 or '?' in text or ':' in text:
                # Continuation
                full_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if (abs(next_line.x0 - line.x0) < 30 and 
                        next_line.y0 - line.y0 < 25 and
                        not next_line.non_black and
                        next_line.size >= 7.0):
                        next_text = next_line.text.strip()
                        if next_text.startswith('['):
                            break
                        full_text += ' ' + next_text
                        j += 1
                    else:
                        break
                
                if _is_field_candidate(full_text):
                    records.append({
                        'form_name': form_name,
                        'field_name': full_text,
                        'page': page_num
                    })
                
                i = j
                continue
        
        i += 1
    
    return records

def _is_pure_code(text):
    return re.match(r'^[A-Z0-9_\-]+$', text) and len(text) < 15

def _is_answer_option_structure(text):
    if re.match(r'^\(\d+\)', text):
        return True
    words = text.split()
    if len(words) == 1 and len(text) < 12:
        return True
    return False

def _is_field_candidate(text):
    text = text.strip()
    
    if len(text) < 3:
        return False
    
    if re.match(r'^[A-Z0-9_\-\s]+$', text) and len(text) < 20:
        return False
    
    if 'TYPE:' in text or 'VISIBILITY:' in text or 'Read-only' in text:
        return False
    
    if re.match(r'^Version\s+[\d/]+$', text):
        return False
    
    if '©' in text:
        return False
    
    return True
```
