Looking at the sample pages:

**Cluster 1 (pages 150, 163)**: These are reference/code-list pages with "Coded" and "Decode" headers. They show answer option mappings, not data-entry fields. The program already skips these correctly with the `is_reference_table` check.

**Cluster 3 (pages 43, 49)**: These pages show only technical metadata in the right margin (x>450) - no actual field labels in the left column at x~46.5. These appear to be overflow/continuation pages with only annotations.

**Cluster 0 (pages 52, 80)**: These ARE form pages with fields, but the program is only getting 82% coverage. Looking at page 52 and 80, I can see actual field labels at x=46.5 like:
- "PR" (line 150.8)
- "QRS" (line 277.5) 
- "QT" (line 394.4)
- "Examination result" (line 48.7)
- "Clinical significance" (line 151.0)
- "Abnormal findings" (line 264.9)

The issue is that the current program requires `is_field = True` via heuristics (next line with "O " or keywords), but many fields have answer boxes `[_|_|_]` instead of "O " options, and some fields don't match the keyword list.

Here's the updated program:

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
        
        # Extract fields from the left column (x < 260)
        # Fields are at x~46-50, sz~7.5, not bold, not colored
        # Skip if line contains technical markers like brackets, "SAS Field Name", etc.
        
        for i, line in enumerate(lines):
            # Skip headers, footers, page numbers
            if line.y0 < 70 or line.y0 > 800:
                continue
            
            # Field labels: x in range 40-55, size 7.0-8.0, not bold, black
            if not (40 <= line.x0 <= 55 and 7.0 <= line.size <= 8.5 and 
                    not line.bold and not line.non_black):
                continue
            
            text = line.text.strip()
            if not text:
                continue
            
            # Skip technical annotations (contain brackets, "SAS Field Name", codes)
            if '[' in text or ']' in text:
                continue
            if re.match(r'^[A-Z]{2,}$', text):  # All-caps codes like "CMTRT"
                continue
            if text.startswith('O '):  # Answer options starting with "O "
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
                continue
            
            # Check if next line is an answer option or continuation
            # If next line at x~249 has "O " prefix or input box, current line is the field
            is_field = False
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                # Answer options appear at x~249
                if (245 <= next_line.x0 <= 255 and 
                    next_line.text.strip().startswith('O ')):
                    is_field = True
                # Or input boxes at x~248-250
                elif (245 <= next_line.x0 <= 255 and 
                      ('[_' in next_line.text or next_line.text.strip().startswith('['))):
                    is_field = True
            
            # Also check if current line looks like a question/label
            if not is_field:
                # Questions typically end with "?" or contain certain keywords
                # Or are short capitalized labels (like "PR", "QRS", "QT")
                if ('?' in text or 
                    any(kw in text.lower() for kw in [
                        'date', 'time', 'result', 'collection', 
                        'performed', 'dose', 'route', 'medication',
                        'significance', 'reason', 'comment', 'examination',
                        'findings', 'clinical', 'abnormal'
                    ]) or
                    (len(text) <= 10 and text.isupper())):  # Short uppercase labels
                    is_field = True
            
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
                    if cont_text and '[' not in cont_text:
                        label_parts.append(cont_text)
                        j += 1
                    else:
                        break
                else:
                    break
            
            full_label = ' '.join(label_parts)
            
            # Final validation: must look like a question/label
            if len(full_label) > 1 and is_field and current_form:
                results.append({
                    "form_name": current_form,
                    "field_name": full_label,
                    "page": page_num
                })
    
    # Deduplicate consecutive identical records (same form, same field on adjacent pages)
    deduplicated = []
    prev = None
    for rec in results:
        if prev is None or (rec["form_name"] != prev["form_name"] or 
                            rec["field_name"] != prev["field_name"]):
            deduplicated.append(rec)
        prev = rec
    
    return deduplicated
```
