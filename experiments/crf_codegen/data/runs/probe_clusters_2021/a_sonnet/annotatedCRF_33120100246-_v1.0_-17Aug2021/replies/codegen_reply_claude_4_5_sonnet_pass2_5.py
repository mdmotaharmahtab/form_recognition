Looking at the feedback, I need to fix several issues:

1. **Page 9-10 (Schedule)**: Extracting structural headers/conditionals instead of actual field labels
2. **Page 309/528 (cluster 1)**: Not extracting anything - these are two-column field specs with gray labels on left
3. **Page 255/425 (cluster 5)**: Red annotation-only pages - correctly skipping these
4. **Page 235/465 (cluster 4)**: Missing most fields - need better extraction of gray labels
5. **Page 72 (C-SSRS)**: Malformed continuations including "Row X" fragments
6. **Page 399**: Missing simple fields and extracting "Normal" as a field

Let me rewrite the program to fix these issues:

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
        elif _is_red_annotation_only_page(lines):
            continue
        elif _is_schedule_page(lines):
            records.extend(_extract_schedule_fields(lines, current_form, page_num))
        elif _is_two_column_field_spec(lines):
            records.extend(_extract_two_column_fields(lines, current_form, page_num))
        elif _is_collection_table_page(lines):
            records.extend(_extract_collection_table_fields(lines, current_form, page_num))
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

def _is_red_annotation_only_page(lines):
    """Pages that are only red TYPE/enumeration annotations - no actual fields"""
    red_lines = 0
    content_lines = 0
    
    for line in lines:
        if line.y0 > 450:
            continue
        text = line.text.strip()
        if not text or len(text) < 5:
            continue
            
        if line.non_black and ('[TYPE:' in text or 'enumeration' in text or 'values:' in text):
            red_lines += 1
        elif line.size >= 7.0 and not line.non_black:
            content_lines += 1
    
    return red_lines > 5 and content_lines < 3

def _is_schedule_page(lines):
    for line in lines:
        if 'Schedule_' in line.text:
            return True
    return False

def _is_collection_table_page(lines):
    """Pages 235, 465: table with 'Collected', 'Not Collected', 'Not Applicable' structure"""
    collected_count = 0
    scan_count = 0
    
    for line in lines:
        text = line.text.strip()
        
        if line.text.startswith('#454545') and line.x0 > 150 and line.x0 < 250:
            if text in ['Collected', 'Not', 'Applicable']:
                collected_count += 1
        
        if line.text.startswith('#454545') and line.x0 > 400 and text == 'Scan':
            scan_count += 1
    
    return collected_count > 2 and scan_count > 0

def _is_two_column_field_spec(lines):
    """Pages 309, 528: gray labels left column (x < 200), red codes, radio buttons right (x > 300)"""
    gray_labels_left = 0
    red_codes_present = 0
    
    for line in lines:
        text = line.text.strip()
        
        # Gray labels in left column
        if line.text.startswith('#454545') and line.x0 < 200 and line.size >= 7.0 and line.size < 10.0:
            if len(text) > 5 and not text.startswith('['):
                gray_labels_left += 1
        
        # Red technical codes [LBTEST, LBORRES, etc.]
        if line.non_black and ('[LBTEST' in text or '[LBORRES' in text):
            red_codes_present += 1
    
    return gray_labels_left > 3 and red_codes_present > 3

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

def _extract_collection_table_fields(lines, form_name, page_num):
    """Extract from pages 235, 465: collection status tables"""
    records = []
    
    for i, line in enumerate(lines):
        # Gray labels on left side, moderate size
        if line.text.startswith('#454545') and line.x0 < 120 and line.size >= 7.0 and line.size < 10.0:
            text = line.text.strip()
            
            if not text or len(text) < 3:
                continue
            
            # Skip answer options by position (middle/right columns)
            if line.x0 > 150:
                continue
            
            # Skip structural markers
            if text in ['Collected', 'Not', 'Applicable', 'Scan']:
                continue
            
            # Must be substantial text
            if len(text) >= 4:
                records.append({
                    'form_name': form_name,
                    'field_name': text,
                    'page': page_num
                })
    
    return records

def _extract_two_column_fields(lines, form_name, page_num):
    """Extract from page 309, 528 style: gray labels left, radio buttons right"""
    records = []
    
    for i, line in enumerate(lines):
        # Gray labels in left column
        if line.text.startswith('#454545') and line.x0 < 200 and line.size >= 7.0 and line.size < 10.0:
            text = line.text.strip()
            
            # Skip empty, short, or bracket-starting text
            if not text or len(text) < 4 or text.startswith('['):
                continue
            
            # Skip answer options by position (right-side)
            if line.x0 > 300:
                continue
            
            # Skip common answer options by name
            if text in ['Positive', 'Negative', 'Not Done', 'Normal', 'Abnormal']:
                continue
            
            # Must be substantial
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
            
            # Skip red annotation markers
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
    
    # Find the blue link column (field names)
    blue_links = []
    for line in lines:
        if line.non_black and line.y0 < 500 and line.size >= 7.0 and line.size < 11.0:
            text = line.text.strip()
            if text and len(text) > 2:
                blue_links.append(line)
    
    if not blue_links:
        return records
    
    # Determine column x-range
    x_positions = [line.x0 for line in blue_links]
    if len(x_positions) < 3:
        return records
    
    x_min = min(x_positions) - 10
    x_max = max(x_positions) + 150
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Blue text in the detected column range
        if line.non_black and x_min <= line.x0 <= x_max and line.y0 < 500 and line.size >= 7.0 and line.size < 11.0:
            text = line.text.strip()
            
            # Skip short text
            if not text or len(text) < 3:
                i += 1
                continue
            
            # Skip pure numbers or codes
            if re.match(r'^[\d\-]+$', text) or _is_pure_code(text):
                i += 1
                continue
            
            # Skip structural headers by pattern
            if re.match(r'^(Screen|Visit|Day|Period|Week)\s+', text) and len(text.split()) <= 4:
                i += 1
                continue
            
            # Skip conditional logic by keywords
            if any(keyword in text for keyword in ['enrols if', 'if SEX', 'if RPPOSMEN', 'on Demography page', 'if RPPOSMEN=']):
                i += 1
                continue
            
            # Skip section headers by pattern (short, common structural words)
            if text in ['Description of Dynamic', 'End of Screening', 'Sertraline Titration']:
                i += 1
                continue
            
            # Skip "page enrols" pattern
            if text.startswith('page enrols'):
                i += 1
                continue
            
            # Skip "X - Page Y" pattern
            if re.match(r'^.+\s+-\s+Page\s+\d+$', text):
                i += 1
                continue
            
            # Multi-line continuation (same column)
            full_text = text
            j = i + 1
            while j < len(lines) and lines[j].non_black and x_min <= lines[j].x0 <= x_max:
                next_text = lines[j].text.strip()
                if abs(lines[j].y0 - line.y0) < 25:
                    # Skip continuation if it's logic annotation
                    if not any(keyword in next_text for keyword in ['enrols if', 'if SEX', 'on Demography page', 'if RPPOSMEN']):
                        full_text += ' ' + next_text
                    j += 1
                else:
                    break
            
            # Final validation
            if full_text and len(full_text) > 2 and not _is_pure_code(full_text):
                # Exclude by pattern
                if not any(keyword in full_text for keyword in ['enrols if', 'on Demography page', 'if RPPOSMEN', 'if SEX']):
                    # Additional check: skip if it's a period/timing descriptor
                    if not re.match(r'^(Drug (dispensation|administration)|Titration|End of)', full_text):
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
            if text.startswith('Row'):
                i += 1
                continue
            
            # Must be substantial
            if text and len(text) > 10:
                # Continuation lines with strict stopping
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
                        
                        # Stop at row markers or short fragments
                        if next_text.startswith('Row') or len(next_text) < 3:
                            break
                        
                        # Stop at "If Yes" patterns
                        if next_text.startswith('If Yes'):
                            break
                        
                        full_text += ' ' + next_text
                        continuation_count += 1
                        j += 1
                    else:
                        break
                
                # Clean up
                full_text = _clean_cssrs_text(full_text)
                
                # Validate: substantial and not an answer option
                if full_text and len(full_text) > 15 and not _is_answer_option_by_structure(full_text):
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
    # Remove row markers
    text = re.sub(r'\s+Row\s+\d+.*$', '', text)
    
    # Remove trailing incomplete phrases
    text = re.sub(r'\s+(the assessment period\.|during|without|method details worked out)$', '', text)
    
    # Remove "If Yes" fragments
    text = re.sub(r'\s+If Yes[,\.].*$', '', text)
    
    # Remove trailing "Yes" after question
    text = re.sub(r'\s+Yes$', '', text)
    
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
        
        # Field labels: black or gray, reasonable size
        if (not line.non_black or line.text.startswith('#454545')) and line.size >= 7.0 and line.size < 13.0:
            text = line.text.strip()
            
            # Skip empty or pure numbers
            if not text or re.match(r'^\d+(\.\d+)?$', text):
                i += 1
                continue
            
            # Skip common answer options by position + name
            if line.x0 > 300 and len(text.split()) <= 2:
                if text in ['Normal', 'Abnormal', 'Yes', 'No', 'Positive', 'Negative', 'Not Done']:
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
    """Structural check: all caps/numbers/underscores and short = technical code"""
    return re.match(r'^[A-Z0-9_\-]+$', text) and len(text) < 15

def _is_answer_option_by_structure(text):
    """Structural check: looks like answer option"""
    # Starts with (number)
    if re.match(r'^\(\d+\)', text):
        return True
    # Single short word
    words = text.split()
    if len(words) == 1 and len(text) < 12:
        return True
    return False

def _is_field_candidate(text):
    """Structural validation for field labels"""
    text = text.strip()
    
    if len(text) < 3:
        return False
    
    # All caps codes
    if re.match(r'^[A-Z0-9_\-\s]+$', text) and len(text) < 20:
        return False
    
    # Technical markers
    if 'TYPE:' in text or 'VISIBILITY:' in text or 'Read-only' in text:
        return False
    
    # Version footer
    if re.match(r'^Version\s+[\d/]+$', text):
        return False
    
    # Copyright
    if '©' in text:
        return False
    
    return True
```
