```python
# This CRF has multiple layout families showing different field presentation styles:
# - Table of contents pages listing page numbers and section names
# - Schedule/table pages with visit labels and page labels in tabular format
# - Standard form pages with field labels, checkboxes, and technical annotations in red
# - C-SSRS assessment pages with numbered rows, questions, and response options
# - Repeatable row pages with column headers and field definitions
#
# Strategy: Extract field_name from human-readable labels (black text, not red annotations).
# form_name comes from prominent blue headers (font ~14pt) at top of pages.
# Skip machine codes in red/brackets, table headers, answer options, and page furniture.

import re
from collections import defaultdict

def extract(pages):
    records = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Identify form name from large blue header near top
        form_name = ""
        for line in lines[:30]:  # Check first 30 lines
            if line.size >= 13.0 and line.non_black and line.y0 < 150:
                # Remove technical suffixes that are part of page numbering
                text = line.text.strip()
                if text and not re.match(r'^\d+$', text):
                    # Clean up page number suffixes
                    text = re.sub(r'\s*-\s*Page\s+\d+$', '', text)
                    if text:
                        form_name = text
                        break
        
        # Determine page type and extract accordingly
        if _is_toc_page(lines):
            # Table of contents - skip
            continue
        elif _is_schedule_page(lines):
            # Schedule pages - extract "Page Label" entries as fields
            records.extend(_extract_schedule_fields(lines, form_name, page_num))
        elif _is_cssrs_page(lines):
            # C-SSRS assessment pages with numbered questions
            records.extend(_extract_cssrs_fields(lines, form_name, page_num))
        else:
            # Standard form pages
            records.extend(_extract_standard_fields(lines, form_name, page_num))
    
    return records

def _is_toc_page(lines):
    # TOC pages have many lines with page numbers followed by blue hyperlinks
    toc_pattern = 0
    for line in lines:
        if line.non_black and re.match(r'\d+\.\d+\.', line.text.strip()):
            toc_pattern += 1
    return toc_pattern > 10

def _is_schedule_page(lines):
    # Schedule pages have "Schedule_" prefix and columnar structure
    for line in lines:
        if line.text.startswith('Schedule_'):
            return True
    return False

def _is_cssrs_page(lines):
    # C-SSRS pages contain "COLUMBIA-SUICIDE" or distinctive C-SSRS patterns
    text_blob = ' '.join(line.text for line in lines[:50])
    return 'COLUMBIA-SUICIDE' in text_blob or 'C-SSRS' in text_blob

def _extract_schedule_fields(lines, form_name, page_num):
    # Extract from "Page Label" column entries (blue hyperlinks in schedule tables)
    records = []
    in_data_rows = False
    
    for i, line in enumerate(lines):
        # Look for blue links that are page labels
        if line.non_black and line.x0 > 250 and line.x0 < 320:
            text = line.text.strip()
            # Skip header row, column labels, and pure codes
            if text and text not in ['Page Label', 'Page', 'Number']:
                # Check if this looks like a field label (not a pure number or code)
                if not re.match(r'^[\d\-]+$', text):
                    # Multi-line labels: join continuation lines
                    full_text = text
                    j = i + 1
                    while j < len(lines) and lines[j].x0 > 250 and lines[j].x0 < 320:
                        if lines[j].non_black and abs(lines[j].y0 - line.y0) < 20:
                            full_text += ' ' + lines[j].text.strip()
                            j += 1
                        else:
                            break
                    
                    if full_text and not _is_junk_text(full_text):
                        records.append({
                            'form_name': form_name if form_name else 'Schedule of Assessment',
                            'field_name': full_text,
                            'page': page_num
                        })
    
    return records

def _extract_cssrs_fields(lines, form_name, page_num):
    # Extract questions from C-SSRS pages (bold black text, not technical annotations)
    records = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip disclaimer, copyright, and technical metadata
        if line.y0 > 400 and ('Disclaimer' in line.text or '©' in line.text or 'reprints' in line.text):
            i += 1
            continue
        
        # Look for question text: bold, black, reasonable size, not a row marker
        if line.bold and not line.non_black and line.size >= 7.0 and line.size < 18.0:
            text = line.text.strip()
            
            # Skip "Row N" markers and pure formatting
            if re.match(r'^Row\s+\d+$', text):
                i += 1
                continue
            
            # Check if this is a numbered item or question
            if text and len(text) > 10:
                # Join continuation lines
                full_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Same column, close vertical proximity, bold black
                    if (abs(next_line.x0 - line.x0) < 20 and 
                        next_line.y0 - line.y0 < 50 and
                        next_line.bold and not next_line.non_black):
                        full_text += ' ' + next_line.text.strip()
                        j += 1
                    else:
                        break
                
                # Filter out answer options and technical text
                if not _is_cssrs_answer_option(full_text) and not _is_junk_text(full_text):
                    records.append({
                        'form_name': form_name if form_name else 'C-SSRS',
                        'field_name': full_text,
                        'page': page_num
                    })
                
                i = j
                continue
        
        i += 1
    
    return records

def _is_cssrs_answer_option(text):
    # Filter out answer option text patterns
    if re.match(r'^\(\d+\)', text):  # (1), (2), etc.
        return True
    if text in ['Yes', 'No', 'Positive', 'Negative', 'Not Done']:
        return True
    return False

def _extract_standard_fields(lines, form_name, page_num):
    # Extract from standard form pages with labels and input areas
    records = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip red technical annotations (machine codes in brackets)
        if line.non_black and '[' in line.text:
            i += 1
            continue
        
        # Skip very small text
        if line.size < 6.5:
            i += 1
            continue
        
        # Look for field labels: black text, reasonable size
        if not line.non_black and line.size >= 7.0 and line.size < 13.0:
            text = line.text.strip()
            
            # Skip empty, pure numbers, and obvious non-fields
            if not text or re.match(r'^\d+(\.\d+)?$', text):
                i += 1
                continue
            
            # Skip table headers and formatting markers
            if text in ['Sample', 'Date of Collection', 'Time of Collection', 'Barcode Number',
                       'Current', 'Former', 'Never', 'Scan', 'Per Day', 'Per Week', 'Pack',
                       'Cigar', 'Cartridge', 'None', 'Yes', 'No', 'Positive', 'Negative',
                       'Not Done', 'Not Applicable', 'Row', 'If Yes, describe', 'If Yes',
                       'Actual Attempts', 'Most Lethal Attempt']:
                i += 1
                continue
            
            # Skip single-word enumeration values
            if len(text.split()) == 1 and text in ['Phone', 'Letter', 'Other']:
                i += 1
                continue
            
            # Look for question-like text or labels
            if len(text) > 15 or '?' in text or ':' in text:
                # Join continuation lines within same column
                full_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if (abs(next_line.x0 - line.x0) < 30 and 
                        next_line.y0 - line.y0 < 25 and
                        not next_line.non_black and
                        next_line.size >= 7.0):
                        next_text = next_line.text.strip()
                        # Stop if we hit a clear boundary
                        if re.match(r'^\[', next_text) or next_text in ['Yes', 'No']:
                            break
                        full_text += ' ' + next_text
                        j += 1
                    else:
                        break
                
                if not _is_junk_text(full_text):
                    records.append({
                        'form_name': form_name,
                        'field_name': full_text,
                        'page': page_num
                    })
                
                i = j
                continue
        
        i += 1
    
    return records

def _is_junk_text(text):
    # Filter out non-field text patterns
    text = text.strip()
    
    # Empty or too short
    if not text or len(text) < 3:
        return True
    
    # Pure codes or numbers
    if re.match(r'^[\[\]A-Z0-9_\-\s]+$', text) and len(text) < 20:
        return True
    
    # Technical type declarations
    if 'TYPE:' in text or 'VISIBILITY:' in text or 'Read-only' in text:
        return True
    
    # Answer options
    if text in ['Yes', 'No', 'Not Applicable', 'Not Done', 'Positive', 'Negative',
                'Current', 'Former', 'Never']:
        return True
    
    # Version numbers and dates
    if re.match(r'^Version\s+[\d/]+$', text):
        return True
    
    # Copyright and disclaimers
    if '©' in text or 'Disclaimer' in text or 'reprints' in text:
        return True
    
    return False
```
