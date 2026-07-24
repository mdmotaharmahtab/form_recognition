```python
# Layout observation: This CRF has a consistent structure across most pages (pages 2-112).
# Each page has header metadata (Study/Site, Group/Visit, Schedule Category), then
# repeating blocks of activities. Each activity block contains:
# - Timepoint, Activity name (bold), Line # in a header row
# - Optional date/time fields, question text (bold), Staff Initials, Answer(s), Comment
# Strategy: Track form_name from "Schedule Category & Name" field; extract field_name
# from bold question text lines (excluding answer options and technical annotations).

import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name" line
        for i, line in enumerate(lines):
            if line.text.startswith("Schedule Category & Name:") or \
               (line.bold and "Schedule Category" in line.text):
                # Next non-bold line should contain the form name
                if i + 1 < len(lines) and not lines[i+1].bold:
                    current_form = lines[i+1].text.strip()
                break
        
        # Skip if no valid form name found
        if not current_form:
            continue
        
        # Process lines to find activity blocks and extract questions
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for Activity header lines (bold, non_black, contains "Activity")
            # or bold activity title lines (e.g., "Informed Consent: ...", "C-SSRS Baseline: ...")
            # These appear around x=167.7 and are bold
            if line.bold and 150 < line.x0 < 180 and line.y0 > 110:
                # Check if this is an activity title (not header labels like "Activity", "Answer(s):", etc.)
                text = line.text.strip()
                
                # Skip header row labels and special markers
                if text in ["Activity", "Answer(s):", "Comment:", "Staff Initials:", "Timepoint", "Line #"]:
                    i += 1
                    continue
                
                # Skip lines that look like technical codes or formatting
                if re.match(r'^[A-Z\[\]]+$', text) or text.startswith('[') or text.startswith('SAS:'):
                    i += 1
                    continue
                
                # Skip answer options (radio button patterns)
                if text.startswith('O ') or text.startswith('Yes (') or text.startswith('No ('):
                    i += 1
                    continue
                
                # Skip date/time format lines
                if re.match(r'^(dd|HH|Date|Time|Version)\s*[-_:]', text) or \
                   text in ["dd - MMM - yyyy", "HH:mm"]:
                    i += 1
                    continue
                
                # Check if this is a question/field (multi-line allowed)
                # Questions typically start around y position after date/time fields
                # and are bold, around x=167.7
                if len(text) > 2 and not text.endswith(':') and \
                   not re.match(r'^\d+\.\d+', text):  # Skip line numbers
                    
                    # Collect the field name, including continuation lines
                    field_parts = [text]
                    j = i + 1
                    
                    # Look ahead for continuation lines (same x position, bold, close y)
                    while j < len(lines):
                        next_line = lines[j]
                        # Check if this is a continuation (similar x, bold, within ~15 points y)
                        if next_line.bold and \
                           abs(next_line.x0 - line.x0) < 10 and \
                           next_line.y0 - lines[j-1].y0 < 20:
                            next_text = next_line.text.strip()
                            # Stop if we hit a new section marker
                            if next_text in ["Answer(s):", "Comment:", "Staff Initials:"] or \
                               next_text.startswith('[') or next_text.startswith('SAS:'):
                                break
                            field_parts.append(next_text)
                            j += 1
                        else:
                            break
                    
                    # Join field parts
                    field_name = " ".join(field_parts).strip()
                    
                    # Final validation: should be a meaningful question
                    if len(field_name) > 5 and \
                       not re.match(r'^\d+\.\d+\s*\(hidden\)$', field_name) and \
                       not field_name.startswith('O '):
                        results.append({
                            "form_name": current_form,
                            "field_name": field_name,
                            "page": page_num
                        })
                    
                    i = j
                    continue
            
            i += 1
    
    return results
```
