```python
# This CRF document has multiple layout families representing different page types:
# - Table-of-contents and schedule pages (families A-E) with numbered page references
# - Data-entry form pages with fields, checkboxes, and technical annotations (family F)
# - Multi-page questionnaire forms like C-SSRS (families G-I)
# - Simple list/enumeration pages (family J)
# - Repeatable-row table pages with column headers (families K-N)
#
# Strategy: Extract form_name from large colored/bold headers (sz ~16-17, often blue #004c99).
# Extract field_name from regular black text at typical label positions, excluding:
# - Technical annotations in red (#ff0000) starting with brackets [TYPE:, [VISIBILITY:, etc.
# - Answer options (Yes/No, checkboxes) that are gray (#999999) or positioned as choices
# - Table headers that repeat across pages
# - Page numbers and furniture
# Join wrapped label lines based on proximity and indentation.

import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Sort lines by y, then x for processing
        sorted_lines = sorted(lines, key=lambda ln: (ln.y0, ln.x0))
        
        # Detect form name: large text (size >= 15), often colored blue or bold
        # Typically at top of page (y < 300)
        form_candidates = []
        for line in sorted_lines:
            if line.y0 < 300 and line.size >= 15 and line.bold:
                text = line.text.strip()
                # Skip table-of-contents entries, page numbers, generic headers
                if not re.match(r'^\d+(\.\d+)?\.?\s', text) and \
                   not re.search(r'Page\s+\d+\s+of\s+\d+', text, re.I) and \
                   not text in ['CHANGE HISTORY', 'SCHEDULE OF ASSESSMENT', 'PAGES', 
                                'Annotated CRF', 'COLUMBIA-SUICIDE SEVERITY', 
                                'RATING SCALE', '(C-SSRS)', 'Baseline/Screening Version']:
                    form_candidates.append((line.y0, text))
        
        # Pick the topmost substantial form title
        if form_candidates:
            form_candidates.sort()
            current_form = form_candidates[0][1]
        
        # Extract fields: black text, moderate size (8-11 pt typical), not red annotations
        # Exclude known non-field patterns
        field_lines = []
        for line in sorted_lines:
            text = line.text.strip()
            
            # Skip empty, page numbers, and red technical annotations
            if not text or line.non_black and '#ff0000' in str(line.non_black):
                continue
            if re.search(r'Page\s+\d+\s+of\s+\d+', text, re.I):
                continue
            if text.startswith('[') and text.endswith(']'):
                continue
            if re.match(r'^\[[\w\s:,().-]+\]$', text):
                continue
            
            # Skip answer options (Yes/No) in gray or small
            if text in ['Yes', 'No', 'X'] and (line.non_black or line.size < 10):
                continue
            
            # Skip table headers that are bold and at specific y positions
            # (repeating across pages)
            if line.bold and line.y0 < 180 and text in [
                'Visit Num', 'Visit Label', 'Page Num', 'Page Label', 'Dynamic?',
                'Description of Dynamic', 'ber', 'Start date', 'Stop date', 
                'Trial Day', 'Total Number of Tab taken', 'Were you able to contact the Subject?',
                'Date of Contact/Attempt', 'Type of Contact', 'Method of Contact',
                'Sample', 'Timepoint', 'Sample Status', 'Time of', 'Barcode', 'Backup',
                'Collection', 'Number', 'Initial contact', 'Second', 'Second contact',
                'Third contact -', 'Third contact', 'Certified letter', 
                'Certified letter confirmation', '- date', 'contact - date', 'attempt',
                'date', 'sent - date', 'sent', 'confirmation',
                'Intensity of Ideation', 'Lifetime', 'Past 3 Month', 'Row 1', 'Row 2', 
                'Row 3', 'Row 4', 'Duration'
            ]:
                continue
            
            # Skip change history table entries
            if re.match(r'^\d+(\.\d+)*$', text) or re.match(r'^\d{1,2}-[A-Z][a-z]{2}-\d{4}$', text):
                continue
            if text in ['Version', 'Date', 'Changed By', 'Details', 'Change History']:
                continue
            
            # Skip enumerated list items (INCL1, EXCL1, etc.)
            if re.match(r'^(INCL|EXCL)\d+$', text):
                continue
            
            # Skip form section markers
            if text.startswith('Schedule_') or text in ['(Repeatable row added with Add Row button)']:
                continue
            
            # Skip copyright and disclaimer text
            if 'copyright' in text.lower() or '©' in text or 'disclaimer' in text.lower():
                continue
            if 'Columbia' in text and 'Suicide' in text:
                continue
            if text.startswith('Definitions of behavioral'):
                continue
            if 'nyspi.columbia.edu' in text.lower():
                continue
            
            # Skip small procedural instructions
            if text.startswith('Collect vital signs after') or text.startswith('If the subject did not meet'):
                continue
            
            # Likely a field if: black text, moderate size, not at page edges
            if not line.non_black and 8 <= line.size <= 12 and line.y0 > 180 and line.y0 < 780:
                field_lines.append(line)
        
        # Join wrapped field labels: if lines are close in y and similar x (or continuation indent)
        grouped_fields = []
        i = 0
        while i < len(field_lines):
            label_parts = [field_lines[i].text.strip()]
            base_x = field_lines[i].x0
            last_y = field_lines[i].y0
            j = i + 1
            
            # Look ahead for continuation lines
            while j < len(field_lines):
                dy = field_lines[j].y0 - last_y
                dx = abs(field_lines[j].x0 - base_x)
                
                # If next line is close vertically (within 20 points) and similar x (within 30)
                # it's likely a continuation
                if dy < 20 and dx < 30:
                    label_parts.append(field_lines[j].text.strip())
                    last_y = field_lines[j].y0
                    j += 1
                else:
                    break
            
            full_label = ' '.join(label_parts)
            # Clean up the label
            full_label = re.sub(r'\s+', ' ', full_label).strip()
            
            # Final filters: skip very short labels (likely not real fields)
            if len(full_label) > 2 and not re.match(r'^[•\-\d]+$', full_label):
                grouped_fields.append(full_label)
            
            i = j if j > i else i + 1
        
        # Deduplicate within page
        seen = set()
        for field in grouped_fields:
            if field not in seen:
                seen.add(field)
                records.append({
                    "form_name": current_form,
                    "field_name": field,
                    "page": page_num
                })
    
    return records
```
