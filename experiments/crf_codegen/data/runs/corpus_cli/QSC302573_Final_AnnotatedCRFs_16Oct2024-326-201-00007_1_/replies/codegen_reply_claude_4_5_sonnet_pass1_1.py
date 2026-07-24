```python
# This CRF uses a repeating activity-block structure. Each block starts with a
# timepoint/activity header (bold text at x~167.7), followed by date/time fields,
# a question in bold at x~167.7, staff initials, and answer options. The form name
# is printed once per page in "Schedule Category & Name". We extract the question
# text (joining continuation lines) as field_name, using the schedule name as
# form_name. Answer options (lines starting with "O" or bracketed codes) are
# skipped.

import re
from typing import List, Dict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        if not lines:
            continue
        
        page_num = page_idx + 1
        
        # Extract form_name from "Schedule Category & Name:" line
        form_name = ""
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Next line should contain the actual schedule name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Extract text after the comma (e.g., "02 - Group Info/Study ICF Final v1.0")
                    match = re.search(r',\s*(.+)', next_line.text)
                    if match:
                        form_name = match.group(1).strip()
                break
        
        # Skip if no form name found (not our layout)
        if not form_name:
            continue
        
        # Find all question fields (bold text at x~167.7 that are actual questions)
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for bold questions at x~167.7
            if (line.bold and 
                167 < line.x0 < 170 and 
                line.size >= 9.5 and
                not line.text.startswith("Answer(s):") and
                not line.text.startswith("Comment:") and
                "Activity" not in line.text and
                "Timepoint" not in line.text and
                not re.match(r'^Day \d+', line.text) and
                not line.text.startswith("Staff Initials:") and
                not re.match(r'^\d+\.\d+', line.text) and  # Skip line numbers
                "SAS:" not in line.text):
                
                # Skip lines that are answer options
                if line.text.strip().startswith("O ") or line.text.strip().startswith("-"):
                    i += 1
                    continue
                
                # This is likely a question - collect continuation lines
                question_parts = [line.text.strip()]
                j = i + 1
                
                # Look ahead for continuation lines (same x position, not bold typically, or bold continuations)
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop at staff initials, answers, comments, or new timepoint
                    if (next_line.text.startswith("Staff Initials:") or
                        next_line.text.startswith("Answer(s):") or
                        next_line.text.startswith("Comment:") or
                        next_line.text.startswith("dd - MMM") or
                        next_line.text.startswith("HH:mm") or
                        re.match(r'^Day \d+', next_line.text) or
                        (next_line.bold and ":" in next_line.text and next_line.x0 < 100)):
                        break
                    
                    # Continuation at similar x position
                    if (167 < next_line.x0 < 170 and 
                        next_line.size >= 9.5 and
                        not next_line.text.startswith("O ") and
                        not next_line.text.strip().startswith("[") and
                        "SAS:" not in next_line.text):
                        question_parts.append(next_line.text.strip())
                        j += 1
                    else:
                        break
                
                # Join the question parts
                field_name = " ".join(question_parts)
                
                # Clean up common prefixes/suffixes
                field_name = re.sub(r'\s+', ' ', field_name).strip()
                
                # Skip if it looks like metadata rather than a question
                if (field_name and 
                    len(field_name) > 3 and
                    not re.match(r'^\d+\.\d+\s*\(', field_name) and
                    not field_name.endswith("#1") and  # Remove trailing activity markers
                    "Line #" not in field_name):
                    
                    # Remove trailing activity markers like "#1"
                    field_name = re.sub(r'\s*#\d+\s*$', '', field_name)
                    
                    # Skip duplicates on same page
                    dup = False
                    for r in results:
                        if r["page"] == page_num and r["field_name"] == field_name and r["form_name"] == form_name:
                            dup = True
                            break
                    
                    if not dup and field_name:
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
