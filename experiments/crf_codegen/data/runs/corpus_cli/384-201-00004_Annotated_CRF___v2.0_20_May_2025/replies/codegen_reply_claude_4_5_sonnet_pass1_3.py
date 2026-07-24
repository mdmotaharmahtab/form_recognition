Looking at the issues, I need to:

1. **Cluster 1 pages (0% coverage)**: These are reference/navigation pages with blue links and code list tables - correctly skipped
2. **Missing fields on pages 25, 56, 92**: Need to capture fields I'm currently filtering out
3. **Wrong form attribution on pages 77, 92**: Form name tracking is picking up wrong cyan headers

Let me analyze the sample pages:
- Page 20 (cluster 1): Blue navigation links - should stay skipped ✓
- Page 175 (cluster 1): Code list decode table - should stay skipped ✓
- Pages 48, 140 (cluster 0): Field definition pages - need better extraction

The main issues:
1. Form name is being set to field labels like "CM Details", "Electrocardiogram 2"
2. Missing continuation lines or being too strict on filters
3. Need to better distinguish between form headers and field-level section headers

```python
import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    seen = set()
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip cover/approval pages
        if page_num <= 2:
            continue
        
        # Check if this is a schedule matrix page (has "Study Event" and "Form" headers)
        header_texts = [ln.text for ln in lines[:20] if ln.size >= 10]
        if "Study Event" in header_texts and "Form" in header_texts:
            continue
        
        # Check if this is a lab panel reference page
        if any("Order ID" in ln.text for ln in lines[:15]) and any("Container" in ln.text for ln in lines[:15]):
            continue
        
        # Skip cluster 1 pages: blue link lists (schedule/form mapping pages)
        blue_links = [ln for ln in lines if ln.non_black and ln.text.strip() and 7 <= ln.size <= 10]
        if len(blue_links) > 10:
            continue
        
        # Skip pages with code list decode tables (cluster 1 reference pages)
        if any("Decode" in ln.text and ln.size >= 10 for ln in lines[:10]):
            if any("Coded" in ln.text and ln.size >= 10 for ln in lines[:10]):
                continue
        
        # Update current form from large white-on-color headers at top of page
        # These are the true form headers (size 12, white text, near top)
        for ln in lines[:15]:  # Only check top of page
            if ln.non_black and ln.size >= 11 and ln.x0 < 150 and ln.y0 < 100:
                txt = ln.text.strip()
                # Must be substantial, not metadata
                if (txt and len(txt) > 3 and 
                    'Origin:' not in txt and 
                    'Repeating:' not in txt and
                    'Domain:' not in txt):
                    current_form = txt
                    break
        
        # Extract field labels: black text, size ~7.5, x~46.5
        for i, ln in enumerate(lines):
            if (not ln.non_black and 
                7.0 <= ln.size <= 8.0 and 
                44 <= ln.x0 <= 52 and
                ln.text.strip()):
                
                txt = ln.text.strip()
                
                # Skip if it's a bracketed SAS field name
                if txt.startswith('[') and txt.endswith(']'):
                    continue
                
                # Skip if it's a radio option (starts with 'O ')
                if txt.startswith('O '):
                    continue
                
                # Skip code list labels
                if txt.lower().startswith('code list:'):
                    continue
                
                # Skip common non-field text patterns
                skip_patterns = [
                    r'^\[SAS Field Name:',
                    r'^dd-MMM-yyyy',
                    r'^\d+\.\d+\s*$',
                    r'^Verify urine',
                    r'^Documentation of',
                    r'^\(\d+\)$',
                    r'^event\?$',
                    r'^\[QSDTC\]$',
                    r'^\[\w+\]$',  # Any single bracketed code
                ]
                if any(re.match(pat, txt, re.I) for pat in skip_patterns):
                    continue
                
                # Check for multi-line label (next line continues)
                field_name = txt
                j = i + 1
                continuation_count = 0
                while j < len(lines) and continuation_count < 8:
                    next_ln = lines[j]
                    # Continuation: similar x position, size, not bracketed, not option
                    if (not next_ln.non_black and
                        7.0 <= next_ln.size <= 8.0 and
                        44 <= next_ln.x0 <= 52 and
                        not next_ln.text.startswith('[') and
                        not next_ln.text.startswith('O ') and
                        next_ln.text.strip()):
                        continuation_text = next_ln.text.strip()
                        # Stop if we hit another [FIELD] marker
                        if continuation_text.startswith('[') and continuation_text.endswith(']'):
                            break
                        field_name += ' ' + continuation_text
                        continuation_count += 1
                        j += 1
                    else:
                        break
                
                # Clean and validate field name
                field_name = ' '.join(field_name.split())
                
                # Must have some alphabetic content (even just 2 chars like "PR", "QT")
                if not re.search(r'[a-zA-Z]{2,}', field_name):
                    continue
                
                # Skip if it looks like a date format or technical metadata
                if re.match(r'^[\d\s:\-\|_\[\]\.]+$', field_name):
                    continue
                
                # Skip very long text that looks like help text (likely misidentified)
                if len(field_name) > 200:
                    continue
                
                # Valid field label found
                if current_form and field_name:
                    key = (current_form, field_name, page_num)
                    if key not in seen:
                        seen.add(key)
                        records.append({
                            "form_name": current_form,
                            "field_name": field_name,
                            "page": page_num
                        })
    
    return records
```
