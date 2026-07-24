```python
import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form name: large blue header (sz >= 15, color #004c99 or similar blue)
        form_name = ""
        for line in lines:
            if line.size >= 15.0 and line.non_black and '#004c' in str(line):
                text = line.text.strip()
                if text and not re.match(r'^\d+\.', text):
                    form_name = text
                    break
        
        # If no large blue header, look for medium-sized blue headers
        if not form_name:
            for line in lines:
                if 14.0 <= line.size < 15.0 and line.non_black:
                    text = line.text.strip()
                    if text and len(text) > 3:
                        form_name = text
                        break
        
        # Detect page layout type by examining structure
        # Layout A/B: Schedule/TOC pages - have "Visit Num", "Page Num" headers in bold at top
        # These are table-of-contents pages with blue links, not data-entry forms
        is_schedule_page = False
        has_visit_num_header = False
        has_page_num_header = False
        has_dynamic_header = False
        
        for line in lines:
            if line.bold and line.y0 < 200:
                text = line.text.strip()
                if text == 'Visit Num':
                    has_visit_num_header = True
                if text == 'Page Num':
                    has_page_num_header = True
                if text == 'Dynamic?':
                    has_dynamic_header = True
        
        # If all three headers present, it's a schedule/TOC page
        if has_visit_num_header and has_page_num_header and has_dynamic_header:
            is_schedule_page = True
        
        # Skip schedule/TOC pages - they don't have data-entry fields
        if is_schedule_page:
            continue
        
        # Extract fields from the page
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip technical annotations (red text, brackets)
            if line.non_black or '[' in line.text or ']' in line.text:
                i += 1
                continue
            
            # Skip page numbers
            if re.match(r'^Page \d+ of \d+', line.text):
                i += 1
                continue
            
            text = line.text.strip()
            
            # Skip empty or very short text
            if not text or len(text) < 3:
                i += 1
                continue
            
            # Skip pure numbers, dates, times
            if re.match(r'^[\d\s\-:/.]+$', text):
                i += 1
                continue
            
            # Skip answer options that start with parenthetical numbers
            if re.match(r'^\(\d+\)', text):
                i += 1
                continue
            
            # Skip standalone section headers at very top of page (y < 150)
            # These are typically column headers like "Intensity of Ideation", "Since Last Visit"
            if line.y0 < 150:
                # Skip common column headers
                if text in ['Intensity of Ideation', 'Since Last Visit', 
                           'Visit Label', 'Page Label', 'Visit Num', 'Page Num',
                           'Dynamic?', 'Description of Dynamic']:
                    i += 1
                    continue
                
                # Skip "Version X/Y/Z" patterns
                if re.match(r'^Version\s+\d+/\d+/\d+', text):
                    i += 1
                    continue
                
                # Skip "Disclaimer:" header
                if text == 'Disclaimer:':
                    i += 1
                    continue
                
                # Skip "Baseline/Screening Version" type headers (short, no question mark)
                if 'Version' in text and len(text) < 40 and '?' not in text:
                    i += 1
                    continue
                
                # Skip visit/period labels (e.g., "Screen Visit 1 Day -55 to -16")
                # These contain "Visit" or "Period" and "Day" with numbers
                if (('Visit' in text or 'Period' in text) and 
                    ('Day' in text or re.search(r'Day\s+-?\d+', text))):
                    i += 1
                    continue
                
                # Skip short text that looks like table headers (< 20 chars, at top)
                if len(text) < 20 and line.bold:
                    i += 1
                    continue
            
            # Skip long disclaimer/instruction paragraphs
            # These are fragments of training text, typically very long
            if (len(text) > 80 and 
                ('This scale is intended' in text or 
                 'training in its administration' in text or
                 'suggested probes' in text or
                 'judgment of the individual administering' in text or
                 'depends on the judgment' in text)):
                i += 1
                continue
            
            # Skip schedule section markers (start with "Schedule_")
            if text.startswith('Schedule_'):
                i += 1
                continue
            
            # Skip row labels like "Row 6" (short, starts with "Row")
            if re.match(r'^Row\s+\d+$', text):
                i += 1
                continue
            
            # Look for field labels: left-aligned (x < 450), reasonable size
            # Field labels are typically bold and positioned on the left side
            if line.x0 < 450 and 8.0 <= line.size <= 12.0:
                # Check if this looks like a field label
                # Field labels are typically longer phrases or questions
                # Must be substantial text (not just a code or number)
                if len(text) >= 10 or (len(text.split()) >= 3 and '?' in text):
                    # Check if next few lines continue the question (wrapping)
                    full_text = text
                    j = i + 1
                    while j < len(lines) and j < i + 5:
                        next_line = lines[j]
                        # Check if continuation: similar x position, close y, not red
                        if (abs(next_line.x0 - line.x0) < 20 and 
                            next_line.y0 - lines[j-1].y0 < 20 and
                            not next_line.non_black and
                            '[' not in next_line.text):
                            next_text = next_line.text.strip()
                            # Stop if we hit answer options or technical text
                            if (next_text.startswith('(') or 
                                re.match(r'^\d+\)', next_text) or
                                next_text.startswith('[')):
                                break
                            # Append continuation
                            if next_text and len(next_text) > 2:
                                full_text += ' ' + next_text
                                j += 1
                            else:
                                break
                        else:
                            break
                    
                    # Clean up the field name
                    full_text = re.sub(r'\s+', ' ', full_text).strip()
                    
                    # Final validation: exclude patterns that are not field labels
                    # Skip answer options
                    if re.match(r'^\(\d+\)', full_text):
                        i = j
                        continue
                    
                    # Skip if it's a partial disclaimer fragment
                    if ('ideation or behavior depends' in full_text or
                        'judgment of the individual' in full_text):
                        i = j
                        continue
                    
                    # Skip section headers that appear in upper portion (y < 200)
                    # These include "Intensity of Ideation", "Deterrents", etc.
                    if line.y0 < 200:
                        # Skip single-word or very short headers
                        if len(full_text.split()) <= 2 and len(full_text) < 30:
                            i = j
                            continue
                    
                    # Valid field - add it
                    results.append({
                        "form_name": form_name,
                        "field_name": full_text,
                        "page": page_num
                    })
                    
                    i = j
                    continue
            
            i += 1
    
    return results
```