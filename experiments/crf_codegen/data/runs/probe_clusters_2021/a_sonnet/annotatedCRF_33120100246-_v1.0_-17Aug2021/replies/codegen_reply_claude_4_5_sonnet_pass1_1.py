```python
# Observed layout: This CRF document has multiple families with distinct structures:
# - Family A: Table of contents page with blue hyperlinks
# - Families B-E: Enumeration/list pages (chemistry, hematology, urinalysis abnormal assays)
# - Families F-K: Standard form pages with blue 14.4pt form titles, questions with y~116.5, and field codes in red
# Strategy: Skip ToC (family A). For enumeration pages (C-E), extract the list items as fields.
# For standard forms (F-K, etc.), extract form_name from blue 14.4pt headers and field_name from questions at standard positions.

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip if no lines
        if not lines:
            continue
        
        # Detect table of contents (family A) - skip it
        # ToC has many blue links with #1d60a4 or #2477cc color
        blue_link_count = sum(1 for ln in lines if ln.non_black and '#1d60a4' in str(ln.text) or '#2477cc' in str(ln.text))
        if blue_link_count > 15:
            continue
        
        # Find form title: blue text, size ~14-15pt, y < 100, non-code text
        form_candidates = []
        for ln in lines:
            if ln.non_black and ln.size >= 13.5 and ln.size <= 15.5 and ln.y0 < 100:
                text = ln.text.strip()
                # Exclude technical annotations and codes
                if not text.startswith('[') and not text.isupper() or ' ' in text:
                    form_candidates.append(text)
        
        if form_candidates:
            current_form = form_candidates[0]
        
        # Identify page structure type
        # Check for enumeration lists (families C, D, E) - many items at x~300-450, no questions at y~116
        enum_items = [ln for ln in lines if 250 < ln.x0 < 500 and ln.size >= 8.5 and ln.size <= 10 
                      and not ln.non_black and len(ln.text.strip()) > 3]
        has_question_at_116 = any(ln.y0 >= 110 and ln.y0 <= 125 and ln.x0 < 100 for ln in lines)
        
        if len(enum_items) > 6 and not has_question_at_116:
            # Enumeration page - extract list items
            for ln in enum_items:
                text = ln.text.strip()
                # Filter out junk: answer options, codes, short fragments
                if (len(text) > 4 and 
                    not text.startswith('[') and 
                    not re.match(r'^(Yes|No|N/A|Met|Not Met|Positive|Negative|Not Done)$', text) and
                    not text.isdigit()):
                    results.append({
                        "form_name": current_form,
                        "field_name": text,
                        "page": page_num
                    })
            continue
        
        # Standard form pages (families F-K, etc.)
        # Extract questions: black text, x < 150, size 7-8.5pt, y > 100, not codes
        seen_fields = set()
        
        for i, ln in enumerate(lines):
            text = ln.text.strip()
            
            # Skip if empty, code marker, or technical annotation
            if (not text or 
                text.startswith('[') or 
                text.startswith('Row ') or
                'TYPE:' in text or
                'VISIBILITY:' in text or
                text in ['Yes', 'No', 'N/A', 'Met', 'Not Met', 'Scan', 'Collected', 'Not Collected',
                         'Positive', 'Negative', 'Not Done', 'Predose', 'Postdose']):
                continue
            
            # Field detection criteria:
            # 1. Black text (not red codes, not blue titles)
            # 2. Left-aligned (x < 150)
            # 3. Regular size (7-9pt)
            # 4. Not bold headers unless it's a substantive question
            # 5. Below form title (y > 100)
            if (not ln.non_black and 
                ln.x0 < 150 and 
                6.5 <= ln.size <= 9.5 and 
                ln.y0 > 100):
                
                # Build multi-line field by checking continuation
                field_parts = [text]
                j = i + 1
                while j < len(lines):
                    next_ln = lines[j]
                    # Continue if next line is close, left-aligned, same size, black
                    if (not next_ln.non_black and
                        abs(next_ln.x0 - ln.x0) < 50 and
                        abs(next_ln.y0 - lines[j-1].y0) < 15 and
                        abs(next_ln.size - ln.size) < 1.5 and
                        not next_ln.text.strip().startswith('[')):
                        
                        next_text = next_ln.text.strip()
                        # Stop at next field or code
                        if (next_text.startswith('[') or 
                            next_text.startswith('Row ') or
                            next_ln.y0 - lines[j-1].y0 > 25):
                            break
                        field_parts.append(next_text)
                        j += 1
                    else:
                        break
                
                field_text = ' '.join(field_parts).strip()
                
                # Quality filters:
                # - Minimum length
                # - Not just a label without substance
                # - Not page furniture
                if (len(field_text) > 8 and
                    not re.match(r'^(Test|Sample|Result|Date|Time|Item|Lot|Barcode|Status|Timepoint|Number)$', field_text, re.I) and
                    not re.match(r'^\d+\.$', field_text) and
                    field_text not in seen_fields):
                    
                    results.append({
                        "form_name": current_form,
                        "field_name": field_text,
                        "page": page_num
                    })
                    seen_fields.add(field_text)
    
    # Deduplicate consecutive identical records
    deduplicated = []
    prev = None
    for rec in results:
        if rec != prev:
            deduplicated.append(rec)
            prev = rec
    
    return deduplicated
```
