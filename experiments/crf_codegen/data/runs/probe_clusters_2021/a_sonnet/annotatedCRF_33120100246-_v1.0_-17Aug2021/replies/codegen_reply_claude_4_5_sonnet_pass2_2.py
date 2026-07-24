I need to analyze the coverage gaps and fix the issues identified. Let me examine the poorly-covered clusters to understand what's missing.

Looking at the metrics and sample pages:
1. **Clusters 1, 4, 5** (29 pages total, 0% covered) - These appear to be field definition/specification pages with test names, types, and enumerations in red annotations
2. **Form names missing** (41% empty) - Need better form name extraction and persistence
3. **Hardcoded blocklists** - Need to replace with structural discriminators

The sample pages from clusters 1, 4, 5 show pages listing field specifications (like "Benzodiazepines", "Urinalysis") with technical metadata. These ARE actual field names - the black/gray test names are the human-readable labels, not the red annotations.

Let me rewrite the program to:
1. Extract field names from these specification pages (black/gray labels like "Benzodiazepines", "Urinalysis")
2. Carry forward form names across pages
3. Remove hardcoded string blocklists and use structural filters only

```python
import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""  # Carry form name forward across pages
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Try to find form name from large blue header
        form_name = ""
        for line in lines[:30]:
            if line.size >= 13.0 and line.non_black and line.y0 < 150:
                text = line.text.strip()
                if text and not re.match(r'^\d+$', text):
                    text = re.sub(r'\s*-\s*Page\s+\d+$', '', text)
                    if text and len(text) > 3:
                        form_name = text
                        break
        
        # Update current form if found, otherwise use previous
        if form_name:
            current_form = form_name
        elif not current_form:
            current_form = "Clinical Research Form"
        
        # Determine page type and extract
        if _is_toc_page(lines):
            continue
        elif _is_schedule_page(lines):
            records.extend(_extract_schedule_fields(lines, current_form, page_num))
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

def _is_field_spec_page(lines):
    # Pages with many red TYPE/VISIBILITY annotations and field specifications
    red_annotation_count = 0
    for line in lines:
        text = line.text.strip()
        if line.non_black and ('[TYPE:' in text or '[VISIBILITY:' in text or '[Read-only' in text):
            red_annotation_count += 1
    return red_annotation_count > 5

def _is_cssrs_page(lines):
    text_blob = ' '.join(line.text for line in lines[:50])
    return 'COLUMBIA-SUICIDE' in text_blob or 'C-SSRS' in text_blob

def _extract_field_spec_fields(lines, form_name, page_num):
    # Extract field names from specification pages
    # Pattern: black/gray field labels followed by red annotations
    records = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for field labels: black or dark gray (#454545), reasonable size, left-aligned
        if (not line.non_black or line.text.startswith('#454545')) and line.size >= 7.0 and line.size < 11.0:
            text = line.text.strip()
            
            # Skip if empty or pure formatting
            if not text or len(text) < 3:
                i += 1
                continue
            
            # Skip if starts with bracket (it's a technical annotation)
            if text.startswith('['):
                i += 1
                continue
            
            # Skip if it's a technical type/visibility marker
            if any(marker in text for marker in ['TYPE:', 'VISIBILITY:', 'Read-only', 'enumeration', 'values:']):
                i += 1
                continue
            
            # Check if next few lines contain red TYPE/field annotations (signature of field spec)
            has_red_annotation = False
            for j in range(i+1, min(i+10, len(lines))):
                next_text = lines[j].text.strip()
                if lines[j].non_black and ('[TYPE:' in next_text or '[LBTEST' in next_text or '[LBORRES' in next_text):
                    has_red_annotation = True
                    break
            
            # This is a field label if followed by technical annotations
            if has_red_annotation:
                # Clean the text
                field_text = text
                
                # Multi-line label check (continuation on next line, same column)
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
    records = []
    
    for i, line in enumerate(lines):
        # Page Label column: blue links, x position 250-350
        if line.non_black and line.x0 > 240 and line.x0 < 350:
            text = line.text.strip()
            
            # Skip headers and pure numbers
            if not text or text in ['Page Label', 'Page', 'Number'] or re.match(r'^[\d\-]+$', text):
                continue
            
            # Multi-line continuation
            full_text = text
            j = i + 1
            while j < len(lines) and lines[j].x0 > 240 and lines[j].x0 < 350:
                if lines[j].non_black and abs(lines[j].y0 - line.y0) < 20:
                    full_text += ' ' + lines[j].text.strip()
                    j += 1
                else:
                    break
            
            if full_text and len(full_text) > 2 and not _is_pure_code(full_text):
                records.append({
                    'form_name': form_name,
                    'field_name': full_text,
                    'page': page_num
                })
    
    return records

def _extract_cssrs_fields(lines, form_name, page_num):
    records = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip footer area
        if line.y0 > 400:
            i += 1
            continue
        
        # Questions: bold black text, decent size
        if line.bold and not line.non_black and line.size >= 7.0 and line.size < 18.0:
            text = line.text.strip()
            
            # Skip row markers
            if re.match(r'^Row\s+\d+$', text):
                i += 1
                continue
            
            # Must be substantial text
            if text and len(text) > 10:
                # Continuation lines
                full_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if (abs(next_line.x0 - line.x0) < 20 and 
                        next_line.y0 - line.y0 < 50 and
                        next_line.bold and not next_line.non_black):
                        full_text += ' ' + next_line.text.strip()
                        j += 1
                    else:
                        break
                
                # Filter by structure: not an answer option pattern
                if not _is_answer_option_structure(full_text):
                    records.append({
                        'form_name': form_name,
                        'field_name': full_text,
                        'page': page_num
                    })
                
                i = j
                continue
        
        i += 1
    
    return records

def _extract_standard_fields(lines, form_name, page_num):
    records = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip red annotations (technical codes)
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
            
            # Skip by structural position: answer options are typically right-aligned clusters
            if line.x0 > 300 and len(text.split()) <= 2:
                i += 1
                continue
            
            # Must be substantial or have question markers
            if len(text) > 15 or '?' in text or ':' in text:
                # Continuation lines
                full_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if (abs(next_line.x0 - line.x0) < 30 and 
                        next_line.y0 - line.y0 < 25 and
                        not next_line.non_black and
                        next_line.size >= 7.0):
                        next_text = next_line.text.strip()
                        # Stop at obvious boundaries
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
    # Check if text looks like a pure machine code
    return re.match(r'^[A-Z0-9_\-]+$', text) and len(text) < 15

def _is_answer_option_structure(text):
    # Structural check for answer options: starts with (N) or very short single word
    if re.match(r'^\(\d+\)', text):
        return True
    words = text.split()
    if len(words) == 1 and len(text) < 12:
        return True
    return False

def _is_field_candidate(text):
    # Structural validation for field candidates
    text = text.strip()
    
    # Minimum length
    if len(text) < 3:
        return False
    
    # Pure codes (all caps/numbers/underscores, short)
    if re.match(r'^[A-Z0-9_\-\s]+$', text) and len(text) < 20:
        return False
    
    # Contains technical markers
    if 'TYPE:' in text or 'VISIBILITY:' in text or 'Read-only' in text:
        return False
    
    # Version numbers
    if re.match(r'^Version\s+[\d/]+$', text):
        return False
    
    # Copyright symbols
    if '©' in text:
        return False
    
    return True
```
