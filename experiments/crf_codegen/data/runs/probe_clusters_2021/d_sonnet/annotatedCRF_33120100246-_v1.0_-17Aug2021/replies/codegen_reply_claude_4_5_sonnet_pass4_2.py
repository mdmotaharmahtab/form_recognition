Looking at the sample pages, I can see three distinct layout families that contain data-entry fields but are currently missing:

1. **Cluster 1 (pages 252, 422)**: C-SSRS question pages with bold questions in the left column (x0 ~45.8) and Yes/No answers on the right. These have numbered items (3, 4, 5) with detailed suicide ideation questions and follow-up prompts like "Have you been thinking about how you might do this?" and "If Yes, describe".

2. **Cluster 2 (pages 290, 465)**: Laboratory/Urinalysis data collection forms with field codes like [LBTEST1], [LBRSN1], [LBDAT1], [LBTIM1], [LBREQ1], [SCANNER], [LBSTAT1]. These show a structured form layout with collection status fields.

3. **Cluster 3 (pages 255, 425)**: Continuation pages showing enumeration value definitions in red text (part of answer option definitions for fields on previous pages - these are field-free annotation pages).

Cluster 3 appears to be purely definitional/instructional (showing answer scale definitions), but Clusters 1 and 2 contain actual data-entry fields that need extraction.

```python
# This CRF contains multiple layout families:
# - Family A: Table of contents (page 1)
# - Family B-C: Schedule of assessments tables with visit/page listings
# - Family D: Technical annotation pages (red field codes)
# - Family E: C-SSRS title/disclaimer pages (no data fields)
# - Family F-H: C-SSRS question pages with actual fields
# - Family I: Laboratory/specimen collection forms
# Strategy: Extract from schedules (families B-C) using blue hyperlinks as page labels,
# from C-SSRS/other form pages using structural patterns (bold questions, checkboxes),
# and from lab forms using field code patterns.

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
        # Check if this is a laboratory/specimen collection form (family I)
        elif is_lab_collection_page(lines):
            results.extend(extract_lab_fields(lines, page_num))
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

def is_lab_collection_page(lines):
    """Check if this is a laboratory/specimen collection form."""
    # Look for characteristic field codes like LBTEST, LBDAT, LBTIM, LBRSN
    for line in lines[:40]:
        if re.search(r'\[LB(TEST|DAT|TIM|RSN|STAT|REQ)\d*\]', line.text):
            return True
        if 'Urinalysis' in line.text or 'Collected' in line.text:
            # Confirm with field codes nearby
            for check_line in lines[:40]:
                if '[LBTEST' in check_line.text or '[LBDAT' in check_line.text:
                    return True
    return False

def extract_lab_fields(lines, page_num):
    """Extract fields from laboratory/specimen collection forms."""
    results = []
    form_name = "Laboratory/Specimen Collection"
    
    # Find the specimen type (e.g., "Urinalysis")
    specimen_type = None
    for line in lines[:20]:
        if line.x0 < 100 and line.y0 < 100 and line.size > 7:
            text = line.text.strip()
            if text and not text.startswith('[') and len(text) > 3:
                if any(keyword in text.lower() for keyword in ['urinalysis', 'blood', 'serum', 'plasma', 'specimen']):
                    specimen_type = text
                    break
    
    if specimen_type:
        form_name = specimen_type
    
    # Extract field codes that represent data entry points
    seen_codes = set()
    for i, line in enumerate(lines):
        # Look for field codes in brackets (red text, typically)
        match = re.search(r'\[([A-Z]{2,}[A-Z0-9]*)\]', line.text)
        if match:
            code = match.group(1)
            # Skip TYPE and VISIBILITY annotations, keep actual field codes
            if code not in ['TYPE', 'VISIBILITY', 'Read-only'] and not code.startswith('TYPE:'):
                if code not in seen_codes:
                    seen_codes.add(code)
                    
                    # Try to find a descriptive label nearby (above or same row, to the left)
                    label = find_lab_field_label(lines, i, line)
                    
                    if label:
                        results.append({
                            'form_name': form_name,
                            'field_name': label,
                            'page': page_num
                        })
    
    return results

def find_lab_field_label(lines, current_idx, code_line):
    """Find a descriptive label for a lab field code."""
    # Look for column headers or row labels
    # Check lines above (within 30 pixels vertically)
    for line in lines[:current_idx]:
        if abs(line.x0 - code_line.x0) < 30 and code_line.y0 - line.y0 < 30 and code_line.y0 - line.y0 > 0:
            text = line.text.strip()
            if text and not text.startswith('[') and len(text) > 2:
                # Valid header-like text
                if not re.match(r'^(Row|TYPE|VISIBILITY)', text):
                    return text
    
    # Look for text on the same line to the left
    for line in lines:
        if line.x0 < code_line.x0 - 50 and abs(line.y0 - code_line.y0) < 5:
            text = line.text.strip()
            if text and not text.startswith('[') and len(text) > 2:
                return text
    
    # Return a generic label based on the code
    code_match = re.search(r'\[([A-Z]{2,}[A-Z0-9]*)\]', code_line.text)
    if code_match:
        return code_match.group(1)
    
    return None

def is_cssrs_question_page(lines, form_name):
    """Check if this is a C-SSRS question page."""
    # Check for C-SSRS in form name
    if 'C-SSRS' in form_name:
        for line in lines:
            if '[CSS' in line.text:
                return True
    
    # Also check for characteristic C-SSRS content patterns
    for line in lines[:50]:
        if 'suicidal ideation' in line.text.lower() or '[CSS0' in line.text:
            return True
    
    return False

def extract_cssrs_questions(lines, form_name, page_num):
    """Extract questions from C-SSRS pages."""
    results = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for bold questions at x0 ~45-46 (left column)
        if line.bold and 40 < line.x0 < 50 and line.size > 7:
            text = line.text.strip()
            
            # Skip row labels, answer options, and technical codes
            if text.startswith('Row ') or text in ['Yes', 'No']:
                i += 1
                continue
            
            if text.startswith('[') or text.startswith('('):
                i += 1
                continue
            
            # Check if this looks like a question or field label
            if len(text) > 10 or '?' in text:
                # Collect continuation lines (same column, nearby)
                full_text = text
                j = i + 1
                while j < len(lines) and j < i + 10:
                    next_line = lines[j]
                    # Same x position, close y, reasonable text
                    if (40 < next_line.x0 < 50 and 
                        next_line.y0 - lines[j-1].y0 < 20 and
                        not next_line.text.strip().startswith('[')):
                        
                        next_text = next_line.text.strip()
                        # Stop at row labels or new sections
                        if next_text.startswith('Row ') or (next_line.bold and '?' in next_text):
                            break
                        
                        if next_text and next_text not in ['Yes', 'No']:
                            full_text += ' ' + next_text
                        j += 1
                    else:
                        break
                
                # Valid question/field
                if len(full_text) > 15 or '?' in full_text:
                    results.append({
                        'form_name': form_name,
                        'field_name': full_text,
                        'page': page_num
                    })
                
                i = j
                continue
        
        # Also look for numbered items (non-bold descriptive text at left margin)
        if (40 < line.x0 < 50 and line.size > 7 and 
            re.match(r'^\d+\.', line.text.strip())):
            text = line.text.strip()
            
            # Collect full numbered item text
            full_text = text
            j = i + 1
            while j < len(lines) and j < i + 8:
                next_line = lines[j]
                if (40 < next_line.x0 < 50 and 
                    next_line.y0 - lines[j-1].y0 < 15 and
                    not next_line.text.strip().startswith('[') and
                    not next_line.text.strip().startswith('Row ')):
                    full_text += ' ' + next_line.text.strip()
                    j += 1
                else:
                    break
            
            # If substantial, treat as a field
            if len(full_text) > 20:
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
