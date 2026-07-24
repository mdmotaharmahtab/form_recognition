```python
# This CRF document has a consistent structure across ~609 pages:
# - A "Schedule Category & Name:" line at y≈93.9 serves as the form title
# - Field labels are bold lines at x≈167.7, size 10pt, often starting after Activity headers
# - We exclude answer options (O prefix), SAS codes, date/time format hints, and "Staff Initials:", "Answer(s):", "Comment:" markers
# - Multi-line labels are joined by checking continuation at the same x-position

import re
from collections import defaultdict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form_name from "Schedule Category & Name:" line
        form_name = ""
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Next line typically has the form name
                if i + 1 < len(lines):
                    candidate = lines[i + 1].text.strip()
                    # Extract part after comma if present (e.g., "03 - Screening Final v1.0")
                    if ',' in candidate:
                        form_name = candidate.split(',', 1)[1].strip()
                    else:
                        form_name = candidate
                break
        
        # Find fields: bold lines at x≈167.7, size≈10, after "Activity" header
        # Exclude structural markers and answer options
        activity_found = False
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Track when we pass the Activity header
            if "Activity" in line.text and line.x0 > 160 and line.x0 < 180:
                activity_found = True
                i += 1
                continue
            
            # Only process lines after Activity header
            if not activity_found:
                i += 1
                continue
            
            # Check if this is a potential field label
            if (line.bold and 
                167 < line.x0 < 170 and 
                9.5 < line.size < 10.5 and
                line.text.strip()):
                
                text = line.text.strip()
                
                # Exclude structural markers and junk
                if text in ["Answer(s):", "Comment:", "Staff Initials:", "Timepoint", "Activity", "Line #"]:
                    i += 1
                    continue
                
                # Exclude answer options (lines starting with "O ")
                if text.startswith("O "):
                    i += 1
                    continue
                
                # Exclude SAS codes in brackets
                if text.startswith("[") and "]" in text and "SAS:" in text:
                    i += 1
                    continue
                
                # Exclude date/time format hints
                if re.match(r'^(dd|HH|mm|yyyy|MMM|Time|Date|Version|_)+[\s\-:._()#]+', text):
                    i += 1
                    continue
                
                # Exclude bare numbers, page furniture
                if re.match(r'^\d+(\.\d+)?\s*(\(hidden\))?$', text):
                    i += 1
                    continue
                
                if "Page" in text and "of" in text:
                    i += 1
                    continue
                
                if "Date Created:" in text:
                    i += 1
                    continue
                
                # This looks like a field label - collect multi-line continuations
                field_parts = [text]
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Continuation: same x position, bold, similar size, not a known marker
                    if (next_line.bold and 
                        167 < next_line.x0 < 170 and 
                        9.5 < next_line.size < 10.5 and
                        next_line.text.strip() and
                        next_line.text.strip() not in ["Answer(s):", "Comment:", "Staff Initials:"] and
                        not next_line.text.strip().startswith("O ") and
                        not next_line.text.strip().startswith("[")):
                        field_parts.append(next_line.text.strip())
                        j += 1
                    else:
                        break
                
                # Join the parts into one field_name
                field_name = " ".join(field_parts)
                
                # Final cleanup: remove trailing punctuation-only fragments
                field_name = re.sub(r'\s+', ' ', field_name).strip()
                
                # Skip if empty after cleanup
                if field_name and form_name:
                    results.append({
                        "form_name": form_name,
                        "field_name": field_name,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return results
```
