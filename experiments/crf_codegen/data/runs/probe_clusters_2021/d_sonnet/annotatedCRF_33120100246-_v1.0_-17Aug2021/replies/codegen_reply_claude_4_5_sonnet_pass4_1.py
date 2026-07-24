```python
# This CRF contains multiple layout families:
# - Family A: Table of contents (page 1)
# - Family B-C: Schedule of assessments tables with visit/page listings
# - Family D: Technical annotation pages (red field codes)
# - Family E: C-SSRS title/disclaimer pages (no data fields)
# - Family F-H: C-SSRS question pages with actual fields
# Strategy: Extract from schedules (families B-C) using blue hyperlinks as page labels,
# and from C-SSRS/other form pages using structural patterns (bold questions, checkboxes).

import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Try to find form title at top (blue or large font)
        form_name = find_form_title(lines)
        
        # Check if this is a Schedule of Assessments page (families B-C)
        if is_schedule_page(lines):
            results.extend(extract_schedule_fields(lines, page_num))
        # Check if this is a C-SSRS question page (families F-H)
        elif is_cssrs_question_page(lines, form_name):
            results.extend(extract_cssrs_questions(lines, form_name, page_num))
        # Check if this is a generic form page with questions
        elif form_name:
            results.extend(extract_generic_fields(lines, form_name, page_num))
    
    return results

def find_form_title(lines):
    """Find the form/section title, typically at top in blue or large font."""
    for line in lines[:15]:  # Check first 15 lines
        # Large blue headers (sz >= 13)
        if line.non_black and line.size >= 13 and line.y0 < 150:
            text = line.text.strip()
            # Skip generic headers
            if text and not re.match(r'^(Schedule|CHANGE HISTORY|PAGES|Row \d+)$', text):
                return text
    return ""

def is_schedule_page(lines):
    """Check if this is a Schedule of Assessments table page."""
    for line in lines[:30]:
        if 'Schedule of Assessments' in line.text or 'Schedule_' in line.text:
            return True
    return False

def extract_schedule_fields(lines, page_num):
    """Extract page labels from schedule tables (blue hyperlinks)."""
    results = []
    
    for i, line in enumerate(lines):
        # Blue hyperlinks around x=276 are page labels
        if line.non_black and 250 < line.x0 < 300 and line.size < 10:
            text = line.text.strip()
            # Skip headers and technical markers
            if text and text not in ['Page Label', 'Page', 'Number'] and not text.startswith('['):
                # Check for continuation on next line
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if next_line.non_black and 250 < next_line.x0 < 300 and abs(next_line.y0 - line.y0) < 15:
                        text += ' ' + next_line.text.strip()
                
                results.append({
                    'form_name': 'Schedule of Assessments',
                    'field_name': text,
                    'page': page_num
                })
    
    return results

def is_cssrs_question_page(lines, form_name):
    """Check if this is a C-SSRS question page."""
    return 'C-SSRS' in form_name and any('[CSS' in line.text for line in lines)

def extract_cssrs_questions(lines, form_name, page_num):
    """Extract questions from C-SSRS pages."""
    results = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Bold questions or numbered items (not rows)
        if line.bold and line.size > 7 and not line.text.strip().startswith('Row'):
            text = line.text.strip()
            
            # Skip technical codes, headers, section labels
            if text and not text.startswith('[') and not text.startswith('(') and len(text) > 3:
                # Skip answer options (Yes/No at right side)
                if text in ['Yes', 'No'] and line.x0 > 400:
                    i += 1
                    continue
                
                # Skip enumeration values
                if re.match(r'^\(\d+\)', text):
                    i += 1
                    continue
                
                # Collect continuation lines
                full_text = text
                j = i + 1
                while j < len(lines) and j < i + 5:
                    next_line = lines[j]
                    # Same column, close y, bold, not a code
                    if (next_line.bold and abs(next_line.x0 - line.x0) < 20 and 
                        next_line.y0 - lines[j-1].y0 < 20 and 
                        not next_line.text.strip().startswith('[')):
                        full_text += ' ' + next_line.text.strip()
                        j += 1
                    else:
                        break
                
                # Valid question length check
                if len(full_text) > 10 and '?' in full_text or len(full_text.split()) > 3:
                    results.append({
                        'form_name': form_name,
                        'field_name': full_text,
                        'page': page_num
                    })
                
                i = j
                continue
        
        i += 1
    
    return results

def extract_generic_fields(lines, form_name, page_num):
    """Extract fields from generic form pages."""
    results = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Questions typically in left area, reasonable size, may be bold
        if line.x0 < 200 and 7 < line.size < 11:
            text = line.text.strip()
            
            # Skip technical annotations, row labels, headers
            if (text and not text.startswith('[') and not text.startswith('(') and 
                not re.match(r'^Row \d+$', text) and text not in ['Yes', 'No']):
                
                # Collect continuation lines
                full_text = text
                j = i + 1
                while j < len(lines) and j < i + 5:
                    next_line = lines[j]
                    if (abs(next_line.x0 - line.x0) < 30 and 
                        next_line.y0 - lines[j-1].y0 < 20 and 
                        next_line.x0 < 200 and
                        not next_line.text.strip().startswith('[')):
                        full_text += ' ' + next_line.text.strip()
                        j += 1
                    else:
                        break
                
                # Must be substantial text
                if len(full_text.split()) >= 3 or '?' in full_text:
                    results.append({
                        'form_name': form_name,
                        'field_name': full_text,
                        'page': page_num
                    })
                
                i = j
                continue
        
        i += 1
    
    return results
```
