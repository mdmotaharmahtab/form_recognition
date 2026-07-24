Looking at the sample pages:

**Page 500 & 860 (cluster 1)**: These contain data-entry fields that are being missed. Page 500 has "Actual Attempts" and "Most Lethal Attempt" as column headers for a table. Page 860 has "Chemistry clinically significant abnormal assay # 1:" followed by a list of lab test names (Albumin, Alkaline phosphatase, ALT, AST, etc.) that are checkboxes/selection fields.

**Pages 5 & 8 (cluster 5)**: These are table-of-contents pages with blue hyperlinks to form sections. These are NOT data-entry fields - they're navigation elements. Zero coverage is correct.

**Pages 936 & 939 (cluster 3)**: These show answer option lists (medication forms like "Emulsion, Gel, Graft" and routes like "Rectal, Ophthalmic, Auricular"). These are NOT field labels themselves but rather the controlled vocabulary/options. Zero coverage is correct.

**Clusters 4, 6**: Not shown, but likely similar instruction/definition pages.

I need to fix the program to capture:
1. Table column headers that are fields (like "Actual Attempts", "Most Lethal Attempt")
2. Introductory text followed by checkbox lists (like "Chemistry clinically significant abnormal assay # 1:" followed by lab test names)

```python
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
            
            # Check for table column headers at specific positions (cluster 1 pattern)
            # These are black 10.5pt text at y~124, often without red codes
            if (not line.non_black and 10.0 <= line.size <= 11.0 and 
                line.y0 < 200 and
                text not in ['Sample', 'Timepoint', 'Sample Status', 'Time of', 'Barcode', 
                            'Backup', 'Collection', 'Number', 'Lifetime', 'Past 6 Month',
                            'Suicidal Behaviour'] and
                not re.match(r'^(Yes|No|N/A|NA)$', text) and
                len(text) > 3):
                
                # Check if this looks like a column header (short, capitalized phrase)
                if (text[0].isupper() and len(text.split()) <= 4 and
                    not text.endswith(':') and
                    'Page' not in text):
                    results.append({
                        "form_name": current_form,
                        "field_name": text,
                        "page": page_num
                    })
                    i += 1
                    continue
            
            # Check for introductory field text followed by checkbox list (cluster 1 pattern)
            # e.g., "Chemistry clinically significant abnormal assay # 1:"
            if (not line.non_black and 8.5 <= line.size <= 9.5 and
                text.endswith(':') and len(text) > 10 and
                ('abnormal' in text.lower() or 'assay' in text.lower() or '#' in text)):
                
                # Look ahead for a list of items (potential checkboxes)
                j = i + 1
                list_items = []
                while j < len(lines) and j < i + 30:
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Stop if we hit another field or section
                    if (next_text.endswith(':') or next_text.startswith('[') or
                        next_line.size > 11 or next_line.y0 - lines[j-1].y0 > 30):
                        break
                    
                    # Collect items that look like checkbox options
                    if (next_text and not next_line.non_black and 
                        10.0 <= next_line.size <= 11.0 and
                        next_line.x0 > line.x0 + 200):  # Indented to the right
                        list_items.append(next_text)
                    
                    j += 1
                
                # If we found a list, treat each item as a field
                if len(list_items) >= 3:
                    for item in list_items:
                        if (item and len(item) > 2 and
                            not re.match(r'^(Yes|No|N/A|NA)$', item)):
                            results.append({
                                "form_name": current_form,
                                "field_name": item,
                                "page": page_num
                            })
                    i = j
                    continue
            
            # Original field detection logic
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