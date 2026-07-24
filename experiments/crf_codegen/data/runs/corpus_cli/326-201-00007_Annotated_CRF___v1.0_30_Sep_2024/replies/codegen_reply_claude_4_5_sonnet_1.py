Looking at this CRF document, I can see:

**Layout observation:**
- The document has a consistent header structure with "Annotated CRF" title, metadata fields, and a three-column layout (Timepoint/Activity/Line #)
- Each data entry field appears as a bold text line (size 10.0, bold, starting around x=167.7) following a timepoint/date pattern
- The "Activity" column contains the field labels (form section : field description format)
- Form/section names appear in the "Schedule Category & Name" line (x=167.7, y=93.9, non-bold)
- Answer options, SAS codes in brackets, and technical annotations appear below field labels at x=238.7
- Fields may wrap across multiple lines at the same x position

**Extraction strategy:**
1. Extract form_name from "Schedule Category & Name" line and carry forward across pages
2. Identify field labels by: bold text at x≈167.7, size≈10.0, following date/time pattern, in the "Activity" column
3. Join wrapped lines (consecutive bold lines at similar x with no intervening patterns) into single field_name
4. Filter out: answer options (at x≈238.7), SAS codes (in brackets), technical annotations, "Staff Initials", "Answer(s):", "Comment:" labels, page footers, headers
5. Extract activity section from field label text (portion before the colon, if present)

```python
import re
from collections import namedtuple

def extract(pages):
    """Extract CRF fields from all pages by identifying form names and field labels."""
    
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name" line
        for i, line in enumerate(lines):
            if re.search(r'Schedule Category & Name:', line.text):
                # Next line should have the form name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Extract after the first comma if present
                    form_text = next_line.text.strip()
                    if ',' in form_text:
                        current_form = form_text.split(',', 1)[1].strip()
                    else:
                        current_form = form_text
                break
        
        # Find field labels in the Activity column
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip header/footer/chrome
            if (line.y0 < 110 or line.y0 > 735 or 
                line.text in ['Timepoint', 'Activity', 'Line #', 'Staff Initials:', 
                             'Answer(s):', 'Comment:', 'Annotated CRF'] or
                re.match(r'^(Date Created:|Page \d+|Study, Site:|Group, Visit:|Slot:)', line.text) or
                re.match(r'^(dd - MMM - yyyy|HH:mm|_ _ [:-])', line.text)):
                i += 1
                continue
            
            # Look for field labels: bold, size ~10, x position ~167
            if (line.bold and 
                9.5 <= line.size <= 10.5 and 
                160 < line.x0 < 175 and
                line.y0 > 110):
                
                # Check if this looks like a field label (contains activity pattern)
                text = line.text.strip()
                
                # Skip labels that are metadata/chrome
                if text in ['Schedule Category & Name:', ''] or text.startswith('['):
                    i += 1
                    continue
                
                # Check if it's an activity field (usually has a colon or specific pattern)
                # Activity fields start with section name, may have line numbers
                if re.search(r'#\d+$', text):  # Ends with line number reference
                    field_text = text
                    
                    # Collect wrapped continuation lines
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        # Check if next line is continuation (bold, similar x, similar size, no date pattern before it)
                        if (next_line.bold and 
                            160 < next_line.x0 < 175 and
                            9.5 <= next_line.size <= 10.5 and
                            next_line.y0 < line.y0 + 50 and
                            not re.match(r'^(Day \d+|_ _)', next_line.text) and
                            next_line.text.strip() and
                            not next_line.text.strip().startswith('[')):
                            
                            # This is a continuation
                            field_text += ' ' + next_line.text.strip()
                            j += 1
                        else:
                            break
                    
                    # Clean up the field text: remove line number suffix
                    field_text = re.sub(r'\s*#\d+(\s*\(hidden\))?\s*$', '', field_text)
                    
                    # Extract just the field description (after colon if present)
                    if ':' in field_text:
                        field_name = field_text.split(':', 1)[1].strip()
                    else:
                        field_name = field_text.strip()
                    
                    if field_name and len(field_name) > 1:
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
