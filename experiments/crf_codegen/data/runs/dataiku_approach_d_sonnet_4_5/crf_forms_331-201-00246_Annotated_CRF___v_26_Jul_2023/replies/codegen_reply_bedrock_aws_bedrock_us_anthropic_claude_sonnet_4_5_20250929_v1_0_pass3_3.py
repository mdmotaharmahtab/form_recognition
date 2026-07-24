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
        
        # Layout C: Intensity rating pages - check if this is a sparse continuation page
        # These have "Intensity of Ideation" header and "Since Last Visit" but minimal content
        has_intensity_header = False
        has_since_last_visit = False
        for line in lines:
            if 'Intensity of Ideation' in line.text and line.y0 < 200:
                has_intensity_header = True
            if 'Since Last Visit' in line.text and line.y0 < 200:
                has_since_last_visit = True
        
        # If it's an intensity page, check if it has actual content
        if has_intensity_header and has_since_last_visit:
            # Count non-header, non-red, substantial content lines
            content_lines = []
            for line in lines:
                if (line.y0 > 200 and 
                    not line.non_black and 
                    'Page' not in line.text and 
                    '[' not in line.text and
                    ']' not in line.text and
                    len(line.text.strip()) > 5):
                    content_lines.append(line)
            
            # If very sparse (only red annotations remain), skip
            if len(content_lines) < 3:
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
            
            # Skip bold headers at top of page (y < 200, bold)
            # These are typically column headers or section markers
            if line.y0 < 200 and line.bold:
                i += 1
                continue
            
            # Skip schedule section markers (start with "Schedule_")
            text = line.text.strip()
            if text.startswith('Schedule_'):
                i += 1
                continue
            
            # Skip visit/period labels that are standalone (e.g., "Screen Visit 1 Day -55 to -16")
            # These are typically at top of page, contain "Visit" or "Period", and have "Day" with numbers
            if (line.y0 < 250 and 
                ('Visit' in text or 'Period' in text) and 
                ('Day' in text or re.search(r'\d+', text))):
                i += 1
                continue
            
            # Skip version/disclaimer headers
            # These are typically short standalone lines at top of form
            if line.y0 < 250:
                # Skip "Version X/Y/Z" patterns
                if re.match(r'^Version\s+\d+/\d+/\d+', text):
                    i += 1
                    continue
                # Skip "Disclaimer:" header
                if text == 'Disclaimer:':
                    i += 1
                    continue
                # Skip "Baseline/Screening Version" type headers
                if 'Version' in text and len(text) < 40:
                    i += 1
                    continue
            
            # Skip long disclaimer/instruction paragraphs
            # These are typically very long (>100 chars) and contain specific keywords
            if (len(text) > 100 and 
                ('This scale is intended' in text or 
                 'training in its administration' in text or
                 'suggested probes' in text)):
                i += 1
                continue
            
            # Skip standalone section headers like "Intensity of Ideation"
            # These appear alone on a line, are not questions, and are typically at top
            if (line.y0 < 300 and 
                text in ['Intensity of Ideation', 'Since Last Visit'] and
                line.size >= 10.0):
                i += 1
                continue
            
            # Look for field labels: left-aligned (x < 450), reasonable size
            if line.x0 < 450 and 8.0 <= line.size <= 12.0:
                text = line.text.strip()
                
                # Skip empty or very short text
                if not text or len(text) < 3:
                    i += 1
                    continue
                
                # Skip pure numbers, dates, times
                if re.match(r'^[\d\s\-:/.]+$', text):
                    i += 1
                    continue
                
                # Skip if this is a bold header-like line in upper portion
                if line.bold and line.y0 < 250:
                    i += 1
                    continue
                
                # Check if this looks like a field label (question or label text)
                # Field labels are typically longer phrases or multi-word
                # But exclude section headers that appear standalone
                if len(text) > 10 or (len(text.split()) >= 2 and not line.bold):
                    # Additional filter: skip if it's a section header pattern
                    # (short, at top, contains specific keywords)
                    if (line.y0 < 250 and len(text) < 50 and
                        ('Intensity' in text or 'Since Last' in text or 
                         'Baseline' in text or 'Screening' in text)):
                        i += 1
                        continue
                    
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
                    
                    # Final validation: not an answer option pattern
                    if not re.match(r'^\(\d+\)', full_text):
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