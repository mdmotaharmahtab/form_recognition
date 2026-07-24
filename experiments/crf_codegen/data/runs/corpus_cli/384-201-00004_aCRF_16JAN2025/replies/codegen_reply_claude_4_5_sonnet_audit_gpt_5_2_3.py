Looking at the issues, I need to:

1. **Fix page 3 & 74**: Missing fields "Adverse event term" and "Body system" - these appear to be field labels I'm currently skipping
2. **Handle cluster 1 (71 pages, 0% coverage)**: These are reference/code-list tables (family B) that I'm correctly skipping
3. **Handle cluster 3 (7 pages, 0% coverage)**: These appear to be continuation pages with only metadata - correctly skipped

The main issue is that my current logic is too restrictive in identifying fields. Looking at the sample pages, I need to:
- Capture fields that don't have immediate answer options below them
- Better handle fields that appear without the structural patterns I'm currently requiring

Let me extend the program to fix these gaps:

```python
import re
from collections import namedtuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Check if this is a reference/code-list table page (family B)
        # These have "Coded" and "Decode" column headers
        is_reference_table = any(
            l.text.strip() in ["Coded", "Decode"] and l.size >= 10.0 and l.bold
            for l in lines
        )
        if is_reference_table:
            continue
        
        # Extract form name from white header bar (sz=12.0, #ffffff, near top)
        for line in lines:
            if (line.size >= 11.5 and line.size <= 13.0 and 
                line.non_black and line.y0 < 60 and
                line.x0 < 100):
                candidate = line.text.strip()
                # Skip generic markers
                if candidate and candidate not in [
                    "Study Events", "CDISC Legend", 
                    "Scheduled Activities Study Events Forms Item Groups Items Measurement Units Code Lists"
                ]:
                    current_form = candidate
                    break
        
        if not current_form:
            continue
        
        # Build index of answer options and input boxes (right column indicators)
        right_column_markers = set()
        for i, line in enumerate(lines):
            # Answer options at x~249, starting with "O "
            if (245 <= line.x0 <= 255 and line.text.strip().startswith('O ')):
                right_column_markers.add(i)
            # Input boxes at x~248-250
            elif (245 <= line.x0 <= 255 and 
                  ('[_' in line.text or line.text.strip().startswith('['))):
                right_column_markers.add(i)
        
        # Extract fields from the left column (x < 260)
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip headers, footers, page numbers
            if line.y0 < 70 or line.y0 > 800:
                i += 1
                continue
            
            # Field labels: x in range 40-55, size 7.0-8.5, not bold, black
            if not (40 <= line.x0 <= 55 and 7.0 <= line.size <= 8.5 and 
                    not line.bold and not line.non_black):
                i += 1
                continue
            
            text = line.text.strip()
            if not text:
                i += 1
                continue
            
            # Skip technical annotations (contain brackets, "SAS Field Name", codes)
            if '[' in text or ']' in text:
                i += 1
                continue
            if re.match(r'^[A-Z]{2,}$', text) and len(text) > 5:  # Long all-caps codes
                i += 1
                continue
            if text.startswith('O '):  # Answer options starting with "O "
                i += 1
                continue
            
            # Skip common non-field patterns
            skip_patterns = [
                r'^\d+\s*of\s*\d+$',  # page numbers
                r'^SAS Field Name',
                r'^Code List',
                r'^dd-MMM-yyyy',  # date format examples
                r'^\[_+\]',  # blank input boxes
                r'^https?://',
                r'^\d{3}-\d{3}-\d{5}$',  # study IDs
                r'^Format:',
                r'^Data Type:',
                r'^Origin:',
                r'^Description:',
                r'^Mandatory',
                r'^Disallow Future',
                r'^Aliases:',
                r'^Documentation of',
                r'^Verify urine',
            ]
            if any(re.search(pat, text, re.IGNORECASE) for pat in skip_patterns):
                i += 1
                continue
            
            # Check for wrapped labels (continuation on next line at same x)
            label_parts = [text]
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # Continuation: same x position, similar size, not bold, black
                if (abs(next_line.x0 - line.x0) < 5 and 
                    abs(next_line.size - line.size) < 1.0 and
                    not next_line.bold and not next_line.non_black and
                    next_line.y0 < line.y0 + 50):  # within reasonable distance
                    cont_text = next_line.text.strip()
                    if cont_text and '[' not in cont_text and not cont_text.startswith('O '):
                        label_parts.append(cont_text)
                        j += 1
                    else:
                        break
                else:
                    break
            
            full_label = ' '.join(label_parts)
            
            # Determine if this is a field label
            is_field = False
            
            # Check if next line (after any continuation) has answer option or input box
            if j in right_column_markers or (j + 1) in right_column_markers:
                is_field = True
            
            # Check if line looks like a question/label (even without immediate right-column marker)
            if not is_field:
                # Questions typically end with "?" or contain field keywords
                if ('?' in full_label or 
                    any(kw in full_label.lower() for kw in [
                        'date', 'time', 'result', 'collection', 
                        'performed', 'dose', 'route', 'medication',
                        'significance', 'reason', 'comment', 'examination',
                        'findings', 'clinical', 'abnormal', 'event',
                        'term', 'system', 'body', 'adverse', 'concomitant',
                        'therapy', 'ongoing', 'outcome', 'action', 'given',
                        'hospitalization', 'disability', 'death', 'threatening'
                    ])):
                    is_field = True
            
            # Check for short capitalized labels (like "PR", "QRS", "QT", but not long codes)
            if not is_field:
                if (len(full_label) <= 10 and 
                    full_label.isupper() and 
                    not re.match(r'^[A-Z]{6,}$', full_label)):  # Not long codes
                    is_field = True
            
            # Additional check: if this looks like a noun phrase (2-8 words, starts capitalized)
            if not is_field:
                words = full_label.split()
                if (2 <= len(words) <= 8 and 
                    full_label[0].isupper() and
                    not full_label.endswith(':') and  # Not a section header
                    len(full_label) > 3):  # Not too short
                    is_field = True
            
            # Final validation: must be reasonable length and have current form
            if is_field and len(full_label) > 1 and current_form:
                results.append({
                    "form_name": current_form,
                    "field_name": full_label,
                    "page": page_num
                })
            
            # Move past any continuation lines we processed
            i = j
    
    # Deduplicate consecutive identical records (same form, same field)
    deduplicated = []
    prev = None
    for rec in results:
        if prev is None or (rec["form_name"] != prev["form_name"] or 
                            rec["field_name"] != prev["field_name"]):
            deduplicated.append(rec)
        prev = rec
    
    return deduplicated
```
