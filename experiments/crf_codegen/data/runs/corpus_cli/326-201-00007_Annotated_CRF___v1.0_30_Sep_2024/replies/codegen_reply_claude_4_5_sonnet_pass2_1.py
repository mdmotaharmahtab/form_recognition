```python
# STRATEGY:
# This CRF uses a standard clinical trial form layout with:
# - "Schedule Category & Name" header identifying form families
# - Activities in bold at x~167.7 (form_name candidates)
# - Questions in bold at x~167.7 following timestamps/staff fields
# - Machine codes in brackets [CODE] are landmarks but not field_name output
# - Multi-line labels must be joined; answer options (O prefix) are not fields

import re
from typing import List, Dict, Any

def extract(pages: List[tuple]) -> List[Dict[str, Any]]:
    results = []
    
    for page_idx, lines in pages:
        if not lines:
            continue
        
        # Check if this page belongs to our layout family by looking for
        # "Schedule Category & Name:" header around y~94-100
        is_our_layout = False
        for line in lines[:20]:  # Check top of page
            if 'Schedule Category' in line.text and line.y0 < 150:
                is_our_layout = True
                break
        
        if not is_our_layout:
            continue
        
        # Extract current form name from Activity lines (bold, x~167, ends with #digit)
        current_form = ""
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Activity lines are bold, start around x=167, and end with pattern like "#1"
            # They appear after timepoint lines (dd - MMM - yyyy pattern)
            if (line.bold and 
                160 < line.x0 < 175 and
                re.search(r'#\d+\s*$', line.text)):
                # Extract form name (strip the #digit suffix and "(hidden)" if present)
                form_text = re.sub(r'\s*#\d+\s*(\(hidden\))?\s*$', '', line.text).strip()
                if form_text:
                    current_form = form_text
            
            # Questions are bold, at x~167, NOT ending with #digit, and NOT answer options
            # They follow staff initials and appear before "Answer(s):" marker
            if (line.bold and 
                160 < line.x0 < 175 and
                not re.search(r'#\d+\s*$', line.text) and
                not line.text.startswith('O ') and
                line.text not in ['Activity', 'Answer(s):', 'Comment:', 'Staff Initials:', 'Timepoint'] and
                line.size >= 9):
                
                # Start building field_name - may span multiple lines
                field_parts = [line.text]
                j = i + 1
                
                # Look ahead for continuation lines (same x position, not special markers)
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop at special markers or answer options
                    if (next_line.text in ['Staff Initials:', 'Answer(s):', 'Comment:'] or
                        next_line.text.startswith('O ') or
                        re.search(r'^\[.*\]\s*SAS:', next_line.text) or
                        next_line.y0 - line.y0 > 50):
                        break
                    
                    # Continuation line: similar x position, not too far down
                    if (160 < next_line.x0 < 175 and 
                        next_line.y0 - field_parts[-1] > 10 and
                        next_line.y0 < line.y0 + 40 and
                        not re.search(r'#\d+\s*$', next_line.text)):
                        
                        # Avoid capturing timestamp placeholders or staff fields
                        if not re.match(r'^(dd - MMM - yyyy|HH:mm|_ _)', next_line.text):
                            field_parts.append(next_line.text)
                            j += 1
                            continue
                    break
                
                # Join multi-line field into single field_name
                field_name = ' '.join(field_parts).strip()
                
                # Filter out non-question text (headers, footers, machine codes, etc.)
                if (field_name and
                    not re.match(r'^(Line #|Activity|Timepoint|Page \d+|Date Created)', field_name) and
                    not re.search(r'^\[.*\]', field_name) and
                    len(field_name) > 3):
                    
                    results.append({
                        'form_name': current_form,
                        'field_name': field_name,
                        'page': page_idx + 1
                    })
            
            i += 1
    
    return results
```
