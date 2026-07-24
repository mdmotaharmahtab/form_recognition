STRATEGY:

The document is a clinical CRF with a large blue form title (size ~16.5, color #004c99) at the top of most field-bearing pages, followed by field labels in regular black text (size ~9). Fields are identified by their black text labels, often followed by red technical annotations in brackets (field codes, types, visibility) that must be excluded from output. The form title persists across multiple pages of the same form, so I will carry forward the most recently seen large blue title as the current form_name. When a page has no blue title, I use the last valid one encountered. Field labels appear as black text lines that are NOT inside brackets, NOT answer options (which appear as enumeration values in smaller gray text or inline lists), and NOT page numbers or furniture. Multi-line labels are joined by detecting continuation patterns (a label line followed by more text at similar x-position before the next bracketed code or new field). Answer options are distinguished by their position in enumeration lists or as Yes/No/N/A choices with gray color, and by appearing after TYPE declarations. Table headers and reference rows without entry cells are excluded by detecting repeating column-header patterns and rows that lack data-entry markers. I process every page in sequence, extracting fields from all pages that contain the structural markers of data-entry forms (blue titles or black field labels with red annotations), ensuring no content-bearing page is skipped.

```python
# CRF extraction: large blue titles (~16.5pt, #004c99) are form names;
# black ~9pt labels followed by red bracketed codes are fields.
# Carry form_name forward across pages; exclude bracketed codes, options, furniture.

import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title: large blue text, typically size 15-18, color #004c99 or similar blue
        for line in lines:
            if line.size >= 15.0 and line.non_black and '#004c99' in str(line):
                # This is likely a form title
                text = line.text.strip()
                if text and not re.match(r'^\d+$', text) and 'Page' not in text:
                    current_form = text
                    break
        
        # Extract fields: black text labels (size ~9) followed by red bracketed annotations
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty, page numbers, and bracketed technical annotations
            if not text or re.match(r'^Page \d+', text) or text.startswith('['):
                i += 1
                continue
            
            # Skip table headers and column labels (common patterns)
            if text in ['Sample', 'Timepoint', 'Sample Status', 'Time of', 'Barcode', 
                       'Backup', 'Collection', 'Number', 'Lifetime', 'Past 6 Month',
                       'Suicidal Behaviour']:
                i += 1
                continue
            
            # Check if this is a field label: black text, size 8-11, not bold header
            if (not line.non_black and 7.5 <= line.size <= 11.5 and 
                not text.startswith('•') and 
                not re.match(r'^Row \d+$', text)):
                
                # Look ahead for red bracketed code (field marker)
                has_field_code = False
                j = i + 1
                while j < len(lines) and j < i + 5:
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    if next_text.startswith('[') and next_line.non_black:
                        has_field_code = True
                        break
                    if next_text and not next_text.startswith('['):
                        break
                    j += 1
                
                if has_field_code:
                    # Collect multi-line label
                    label_parts = [text]
                    k = i + 1
                    while k < len(lines) and k < i + 10:
                        next_line = lines[k]
                        next_text = next_line.text.strip()
                        
                        # Stop at bracketed code or new field
                        if next_text.startswith('['):
                            break
                        
                        # Continue if similar x-position and not too far down
                        if (next_text and not next_line.non_black and 
                            abs(next_line.x0 - line.x0) < 20 and
                            7.5 <= next_line.size <= 11.5 and
                            next_line.y0 - line.y0 < 50):
                            label_parts.append(next_text)
                            k += 1
                        else:
                            break
                    
                    field_label = ' '.join(label_parts).strip()
                    
                    # Filter out answer options and non-fields
                    if (field_label and 
                        not re.match(r'^(Yes|No|N/A|NA)$', field_label) and
                        not re.match(r'^\d+$', field_label) and
                        len(field_label) > 2 and
                        'Pack Version' not in field_label and
                        'CHANGE HISTORY' not in field_label):
                        
                        results.append({
                            "form_name": current_form,
                            "field_name": field_label,
                            "page": page_num
                        })
            
            i += 1
    
    return results
```