Looking at the feedback, I need to fix the fundamental issue: I'm extracting field labels as form names instead of finding the actual form title that groups multiple fields.

Let me analyze the sample pages:
- **Cluster 0 (schedule pages)**: These are table-of-contents style pages with Study Event | Timepoint | Form columns. The forms listed here ARE the form names (not field names).
- **Cluster 1 (field definition pages)**: These show individual field annotations with radio buttons (O N/A, O Yes, O No). The form name should be extracted from a shared title at the top of the page, and the numbered criteria are the actual field names.

The key insight: on cluster 1 pages, I need to find the FORM TITLE (which appears once and groups many fields), not treat each field label as its own form.

```python
import re

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Strategy 1: Schedule/TOC pages (cluster 0)
        # Three-column layout: Study Event | Timepoint | Form
        
        form_column_x = None
        header_y = None
        
        for i, ln in enumerate(lines):
            text = ln.text.strip()
            if text == "Form" and ln.bold and ln.size >= 7:
                form_column_x = ln.x0
                header_y = ln.y0
                break
        
        if form_column_x is not None:
            seen_forms_on_page = set()
            
            for ln in lines:
                if ln.y0 <= header_y + 5:
                    continue
                
                if abs(ln.x0 - form_column_x) < 50:
                    if 8 <= ln.size <= 10 and not ln.bold and not ln.non_black:
                        form_name = ln.text.strip()
                        
                        if len(form_name) < 3:
                            continue
                        
                        if re.match(r'^\d+$', form_name):
                            continue
                        
                        if re.match(r'^\d{3}-\d{3}-\d{5}$', form_name):
                            continue
                        
                        if re.match(r'^[-*\d:()]+$', form_name):
                            continue
                        
                        if re.match(r'^Day\s+[-\d]+$', form_name, re.IGNORECASE):
                            continue
                        
                        if form_name not in seen_forms_on_page:
                            seen_forms_on_page.add(form_name)
                            results.append({
                                "form_name": form_name,
                                "field_name": form_name,
                                "page": page_num
                            })
            
            if seen_forms_on_page:
                continue
        
        # Strategy 2: Field annotation pages (cluster 1)
        # Pattern: Radio button options (O N/A, O Yes, O No) on left + field codes on right
        
        # Look for radio button pattern - characteristic of field annotation pages
        has_radio_buttons = False
        for ln in lines:
            if ln.x0 > 200 and ln.x0 < 300 and re.match(r'^O\s+(N/A|Yes|No|Unspecified)$', ln.text.strip()):
                has_radio_buttons = True
                break
        
        if has_radio_buttons:
            # Find form title: Look for largest colored or bold text near top
            # Skip protocol number pattern
            form_title = None
            protocol_y = None
            
            for ln in lines[:30]:
                if re.match(r'^\d{3}-\d{3}-\d{5}$', ln.text.strip()):
                    protocol_y = ln.y0
                    break
            
            # Find prominent title
            for ln in lines[:80]:
                if protocol_y and abs(ln.y0 - protocol_y) < 15:
                    continue
                
                candidate = ln.text.strip()
                
                if len(candidate) < 5:
                    continue
                
                # Skip protocol numbers
                if re.match(r'^\d{3}-\d{3}-\d{5}$', candidate):
                    continue
                
                # Skip field codes in brackets
                if candidate.startswith('[') and candidate.endswith(']'):
                    continue
                
                # Skip radio options
                if re.match(r'^O\s+', candidate):
                    continue
                
                # Skip "SAS Field Name:" patterns
                if 'SAS Field Name' in candidate:
                    continue
                
                # Large colored text near top = form title
                if ln.size >= 10 and ln.non_black:
                    form_title = candidate
                    break
                
                # Large bold text near top = form title
                if ln.size >= 10 and ln.bold and not candidate.endswith(':'):
                    form_title = candidate
                    break
            
            # Fallback: medium colored text
            if not form_title:
                for ln in lines[:80]:
                    if protocol_y and abs(ln.y0 - protocol_y) < 15:
                        continue
                    
                    if ln.non_black and ln.size >= 8:
                        candidate = ln.text.strip()
                        if (len(candidate) > 5 and 
                            not re.match(r'^\d{3}-\d{3}-\d{5}$', candidate) and
                            not candidate.startswith('[') and
                            'clinspark' not in candidate.lower()):
                            form_title = candidate
                            break
            
            if not form_title:
                continue
            
            # Extract field labels: numbered criteria on left side
            field_labels = []
            
            i = 0
            while i < len(lines):
                ln = lines[i]
                
                # Look for numbered items on left side (field labels)
                if 30 < ln.x0 < 100 and 6.5 <= ln.size <= 8.5 and not ln.bold:
                    text = ln.text.strip()
                    
                    # Must start with number followed by period
                    match = re.match(r'^(\d+)\.\s+(.+)', text)
                    if match:
                        # This is a field label - collect full text across lines
                        field_text = text
                        
                        # Look ahead for continuation lines
                        j = i + 1
                        while j < len(lines):
                            next_ln = lines[j]
                            
                            # Same column area, similar size, not bold
                            if (abs(next_ln.x0 - ln.x0) < 30 and 
                                6.5 <= next_ln.size <= 8.5 and 
                                not next_ln.bold):
                                
                                next_text = next_ln.text.strip()
                                
                                # Stop conditions
                                if re.match(r'^\d+\.\s+', next_text):  # Next numbered item
                                    break
                                if next_text.startswith('['):  # Field code
                                    break
                                if re.match(r'^O\s+', next_text):  # Radio button
                                    break
                                if len(next_text) == 0:  # Empty
                                    j += 1
                                    continue
                                
                                # Continuation line
                                field_text += ' ' + next_text
                                j += 1
                            else:
                                break
                        
                        field_labels.append(field_text)
                        i = j
                        continue
                
                i += 1
            
            # Emit records
            for label in field_labels:
                results.append({
                    "form_name": form_title,
                    "field_name": label,
                    "page": page_num
                })
            
            if field_labels:
                continue
        
        # Strategy 3: Detailed field pages with field codes (old cluster 1 logic)
        # These have field codes on right (bold, small) and labels on left
        
        # Find form title
        form_title = None
        protocol_y = None
        
        for ln in lines[:20]:
            if re.match(r'^\d{3}-\d{3}-\d{5}$', ln.text.strip()):
                protocol_y = ln.y0
                break
        
        for ln in lines[:80]:
            if protocol_y and abs(ln.y0 - protocol_y) < 10:
                continue
            
            if ln.size < 8:
                continue
            
            candidate = ln.text.strip()
            
            if len(candidate) < 4:
                continue
            
            if re.match(r'^\d{3}-\d{3}-\d{5}$', candidate):
                continue
            
            if 'clinspark' in candidate.lower():
                continue
            
            if ln.size >= 10 and ln.non_black:
                form_title = candidate
                break
            
            if ln.size >= 10 and ln.bold:
                if candidate.endswith(':'):
                    continue
                form_title = candidate
                break
        
        if not form_title:
            for ln in lines[:80]:
                if protocol_y and abs(ln.y0 - protocol_y) < 10:
                    continue
                
                if ln.non_black and ln.size >= 8:
                    candidate = ln.text.strip()
                    if len(candidate) > 4 and not re.match(r'^\d{3}-\d{3}-\d{5}$', candidate):
                        form_title = candidate
                        break
        
        if not form_title:
            continue
        
        field_labels = []
        
        for i, ln in enumerate(lines):
            # Field codes: small bold text on right side
            if ln.bold and 5 <= ln.size <= 6.5 and ln.x0 > 400:
                code = ln.text.strip()
                
                if not re.match(r'^[A-Z]{2,}[A-Z0-9_]+$', code):
                    continue
                
                # Find associated field label on left
                label = None
                
                search_start = max(0, i - 40)
                search_end = min(len(lines), i + 40)
                
                for j in range(search_start, search_end):
                    cand_ln = lines[j]
                    
                    if not (30 < cand_ln.x0 < 200 and 6.5 <= cand_ln.size <= 9 and not cand_ln.bold):
                        continue
                    
                    cand_text = cand_ln.text.strip()
                    
                    if len(cand_text) < 5:
                        continue
                    
                    if cand_text.startswith('[') and cand_text.endswith(']'):
                        continue
                    
                    if re.match(r'^O\s', cand_text):
                        continue
                    
                    if cand_text.endswith(':'):
                        continue
                    
                    if cand_text.isupper() and len(cand_text) < 10:
                        continue
                    
                    if re.match(r'^\d+\.$', cand_text):
                        continue
                    
                    label = cand_text
                    break
                
                if label:
                    field_labels.append(label)
        
        for label in field_labels:
            results.append({
                "form_name": form_title,
                "field_name": label,
                "page": page_num
            })
    
    # Deduplicate
    seen = set()
    deduplicated = []
    for rec in results:
        key = (rec["form_name"], rec["field_name"], rec["page"])
        if key not in seen:
            seen.add(key)
            deduplicated.append(rec)
    
    return deduplicated
```
