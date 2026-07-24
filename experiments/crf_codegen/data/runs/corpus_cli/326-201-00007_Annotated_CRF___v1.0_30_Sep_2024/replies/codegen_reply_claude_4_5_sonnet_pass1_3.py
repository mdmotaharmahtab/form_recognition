Looking at the sample pages, I can see they contain **section headers** that my program is currently filtering out but should actually be captured as data-entry fields.

Specifically, lines like:
- "Reflexes" (page 44, line 326.1)
- "Sensory System" (page 45, line 150.4)
- "Co-ordination" (page 45, line 369.5)

These are **bold text at x≈167.7** that appear between the date/time fields and the "Staff Initials:" label. They represent the actual field names for the examination components. My current program skips these because they don't meet the `150 < line.x0 < 180` condition (they're at x0=167.7).

The pattern is:
1. Activity header with "#N" (e.g., "Neurological Examination: Reflexes #1") - correctly skipped as section header
2. Date/time entry fields
3. **The actual field name** in bold at x≈167.7 (e.g., "Reflexes") - currently missed
4. Staff Initials, Answer(s), etc.

Here's the updated program:

```python
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
            
            # NEW: Capture field names at x≈167.7 (between date/time and Staff Initials)
            # These are short bold labels like "Reflexes", "Sensory System", "Co-ordination"
            if line.bold and 165 < line.x0 < 170 and line.y0 > 110:
                text = line.text.strip()
                
                # Skip headers and special markers
                if text in ["Activity", "Answer(s):", "Comment:", "Staff Initials:", "Timepoint", "Line #"]:
                    i += 1
                    continue
                
                # Skip technical codes
                if re.match(r'^[A-Z\[\]]+$', text) or text.startswith('[') or text.startswith('SAS:'):
                    i += 1
                    continue
                
                # Skip answer options
                if text.startswith('O ') or text.startswith('Yes (') or text.startswith('No ('):
                    i += 1
                    continue
                
                # Skip date/time formats
                if re.match(r'^(dd|HH|Date|Time|Version)\s*[-_:]', text) or \
                   text in ["dd - MMM - yyyy", "HH:mm"]:
                    i += 1
                    continue
                
                # Skip section headers with "#N" pattern
                if re.search(r':\s*[A-Z][^?]+#\d+$', text):
                    i += 1
                    continue
                
                # Capture single-word or short field names (e.g., "Reflexes", "Sensory System")
                if len(text) > 2 and not text.endswith(':') and \
                   not text.startswith('(') and not text.startswith('_'):
                    results.append({
                        "form_name": current_form,
                        "field_name": text,
                        "page": page_num
                    })
                    i += 1
                    continue
            
            # EXISTING: Look for bold text at x≈150-180 (original field capture logic)
            if line.bold and 150 < line.x0 < 180 and line.y0 > 110:
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
                
                # Skip section headers
                if re.search(r':\s*[A-Z][^?]+#\d+$', text):
                    i += 1
                    continue
                
                # Skip standalone instructional text in parentheses
                if text.startswith('(') and text.endswith(')'):
                    i += 1
                    continue
                
                # Check if this is a question/field (multi-line allowed)
                if len(text) > 2 and not text.endswith(':') and \
                   not re.match(r'^\d+\.\d+', text):
                    
                    # Collect the field name, including continuation lines
                    field_parts = [text]
                    j = i + 1
                    
                    # Look ahead for continuation lines
                    while j < len(lines):
                        next_line = lines[j]
                        if next_line.bold and \
                           abs(next_line.x0 - line.x0) < 10 and \
                           next_line.y0 - lines[j-1].y0 < 20:
                            next_text = next_line.text.strip()
                            if next_text in ["Answer(s):", "Comment:", "Staff Initials:"] or \
                               next_text.startswith('[') or next_text.startswith('SAS:'):
                                break
                            field_parts.append(next_text)
                            j += 1
                        else:
                            break
                    
                    field_name = " ".join(field_parts).strip()
                    
                    # Additional filters for the joined field name
                    if re.search(r':\s*[A-Z][^?]+#\d+$', field_name):
                        i = j
                        continue
                    
                    if field_name.startswith('('):
                        i = j
                        continue
                    
                    if len(field_name) > 150 and not field_name.endswith('?'):
                        i = j
                        continue
                    
                    if re.match(r'^[A-Z][a-z]+:\s*[A-Z]\d+\s*#\d+$', field_name):
                        i = j
                        continue
                    
                    if field_name in ["Affected Body System", "Medical History: Body System #1", 
                                     "Adverse Event: Progress Notes #1"]:
                        i = j
                        continue
                    
                    if re.match(r'^C-SSRS [^:]+:\s*\d+\.', field_name) and not field_name.endswith('?'):
                        i = j
                        continue
                    
                    if len(field_name) > 100 and \
                       ('Subject endorses' in field_name or 'General non-specific' in field_name):
                        i = j
                        continue
                    
                    if len(field_name) < 15 and not field_name.endswith('?'):
                        i = j
                        continue
                    
                    # Final validation
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
