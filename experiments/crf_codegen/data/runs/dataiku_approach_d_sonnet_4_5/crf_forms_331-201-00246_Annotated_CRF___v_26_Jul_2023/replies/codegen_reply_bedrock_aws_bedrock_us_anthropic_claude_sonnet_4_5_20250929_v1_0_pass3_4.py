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
        # Layout A/B: Schedule/TOC pages - have "Visit Num", "Page Num" headers
        is_schedule_page = False
        for line in lines:
            if line.bold and line.y0 < 200:
                text = line.text.strip()
                if text in ['Visit Num', 'Page Num', 'Visit Label', 'Page Label']:
                    is_schedule_page = True
                    break
        
        # Skip schedule/TOC pages - they don't have data-entry fields
        if is_schedule_page:
            continue
        
        # Layout C: Sparse continuation pages with only headers and minimal content
        # These have "Intensity of Ideation" and "Since Last Visit" headers at top
        # but no actual field content below (only red annotations)
        has_intensity_header = False
        has_since_last_visit = False
        header_count = 0
        
        for line in lines:
            text = line.text.strip()
            # Check for these specific headers at top of page
            if line.y0 < 200:
                if text == 'Intensity of Ideation':
                    has_intensity_header = True
                    header_count += 1
                if text == 'Since Last Visit':
                    has_since_last_visit = True
                    header_count += 1
        
        # If it's a sparse continuation page (both headers, minimal other content)
        if has_intensity_header and has_since_last_visit:
            # Count substantial black text lines below headers (y > 200)
            # Exclude red text, page numbers, and very short text
            content_lines = 0
            for line in lines:
                if (line.y0 > 200 and 
                    not line.non_black and 
                    not re.match(r'^Page \d+ of \d+', line.text) and
                    len(line.text.strip()) > 10):
                    content_lines += 1
            
            # If very sparse (only headers and red annotations), skip
            if content_lines < 2:
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
            
            # Skip bold headers at very top of page (y < 150)
            # These are typically column headers or section markers
            if line.y0 < 150 and line.bold:
                i += 1
                continue
            
            # Skip standalone section headers that appear at top
            # These are short, at top of page, and match specific patterns
            if line.y0 < 200:
                # Skip "Intensity of Ideation" and "Since Last Visit" headers
                if text in ['Intensity of Ideation', 'Since Last Visit']:
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
                
                # Skip "Baseline/Screening Version" type headers
                if 'Version' in text and len(text) < 40 and not '?' in text:
                    i += 1
                    continue
                
                # Skip visit/period labels (e.g., "Screen Visit 1 Day -55 to -16")
                # These contain "Visit" or "Period" and "Day" with numbers
                if (('Visit' in text or 'Period' in text) and 
                    ('Day' in text or re.search(r'Day\s+-?\d+', text))):
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
            
            # Look for field labels: left-aligned (x < 450), reasonable size
            if line.x0 < 450 and 8.0 <= line.size <= 12.0:
                # Skip if this is a bold header-like line in upper portion (y < 200)
                if line.bold and line.y0 < 200:
                    i += 1
                    continue
                
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