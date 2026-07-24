Looking at the issues:

1. **Degenerate form grouping**: I'm extracting field-level text as form names instead of the shared form/section title
2. **Low form persistence**: Only 16% of records share a form_name on multi-field pages
3. **Hardcoded filters**: I'm using literal text blocklists instead of structural discriminators

From the sample pages, I can see two distinct layouts:

**Cluster 0 (schedule pages)**: Three-column table with Study Event | Timepoint | Form. The "Form" column contains form names that should be extracted.

**Cluster 1 (detailed field pages)**: Form title at top, then field labels with technical annotations on the right. I need to extract the form title ONCE and associate all fields with it.

The key insight: On cluster 1 pages, I was extracting field labels as form names. I need to find the TRUE form title (large, prominent text near top) and reuse it for all fields on that page.

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
        
        # Strategy 2: Detailed field annotation pages (cluster 1)
        # Find THE form title (shared across all fields)
        
        form_title = None
        
        # Look for protocol number pattern first to skip it
        protocol_y = None
        for ln in lines[:20]:
            if re.match(r'^\d{3}-\d{3}-\d{5}$', ln.text.strip()):
                protocol_y = ln.y0
                break
        
        # Find form title: large prominent text near top
        for ln in lines[:80]:
            if protocol_y and abs(ln.y0 - protocol_y) < 10:
                continue
            
            if ln.size < 8:
                continue
            
            candidate = ln.text.strip()
            
            if len(candidate) < 4:
                continue
            
            # Skip protocol numbers
            if re.match(r'^\d{3}-\d{3}-\d{5}$', candidate):
                continue
            
            # Skip URLs
            if 'clinspark' in candidate.lower():
                continue
            
            # Large colored text - likely form title
            if ln.size >= 10 and ln.non_black:
                form_title = candidate
                break
            
            # Large bold text - likely form title
            if ln.size >= 10 and ln.bold:
                # Skip if it looks like a metadata label (ends with colon)
                if candidate.endswith(':'):
                    continue
                form_title = candidate
                break
        
        # If no large title found, look for medium-sized colored text
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
        
        # Extract fields for this form
        # Fields have: field code (small bold text on right) + field label (medium text on left)
        
        field_labels = []
        
        for i, ln in enumerate(lines):
            # Field codes: small bold text on right side
            if ln.bold and 5 <= ln.size <= 6.5 and ln.x0 > 400:
                code = ln.text.strip()
                
                # Field codes are uppercase alphanumeric
                if not re.match(r'^[A-Z]{2,}[A-Z0-9_]+$', code):
                    continue
                
                # Find associated field label on left side
                label = None
                
                search_start = max(0, i - 40)
                search_end = min(len(lines), i + 40)
                
                for j in range(search_start, search_end):
                    cand_ln = lines[j]
                    
                    # Field labels: left side, medium size, not bold
                    if not (30 < cand_ln.x0 < 200 and 6.5 <= cand_ln.size <= 9 and not cand_ln.bold):
                        continue
                    
                    cand_text = cand_ln.text.strip()
                    
                    if len(cand_text) < 5:
                        continue
                    
                    # Skip bracketed text (field codes or technical annotations)
                    if cand_text.startswith('[') and cand_text.endswith(']'):
                        continue
                    
                    # Skip radio button options (O followed by space/text)
                    if re.match(r'^O\s', cand_text):
                        continue
                    
                    # Skip metadata labels (ends with colon)
                    if cand_text.endswith(':'):
                        continue
                    
                    # Skip short uppercase text (likely codes)
                    if cand_text.isupper() and len(cand_text) < 10:
                        continue
                    
                    # Skip numbered list items that are just the number
                    if re.match(r'^\d+\.$', cand_text):
                        continue
                    
                    label = cand_text
                    break
                
                if label:
                    field_labels.append(label)
        
        # Also look for numbered criteria without explicit field codes
        # These appear as numbered items on the left (e.g., "1. Criterion text...")
        for i, ln in enumerate(lines):
            # Look for numbered items on left side
            if 30 < ln.x0 < 200 and 6.5 <= ln.size <= 8.5 and not ln.bold:
                text = ln.text.strip()
                
                # Numbered criterion (starts with digit followed by period)
                match = re.match(r'^(\d+)\.\s+(.+)', text)
                if match:
                    criterion_text = text
                    
                    # Collect continuation lines
                    for j in range(i + 1, min(len(lines), i + 20)):
                        next_ln = lines[j]
                        
                        # Same column, similar size, not bold
                        if (abs(next_ln.x0 - ln.x0) < 20 and 
                            6.5 <= next_ln.size <= 8.5 and 
                            not next_ln.bold):
                            
                            next_text = next_ln.text.strip()
                            
                            # Stop if we hit another numbered item
                            if re.match(r'^\d+\.\s+', next_text):
                                break
                            
                            # Stop if bracketed text (field code)
                            if next_text.startswith('[') and next_text.endswith(']'):
                                break
                            
                            # Stop if radio option
                            if re.match(r'^O\s', next_text):
                                break
                            
                            # Continuation line
                            if len(next_text) > 0 and not next_text.endswith(':'):
                                criterion_text += ' ' + next_text
                        else:
                            break
                    
                    # Only add if we haven't already captured this via field code
                    if criterion_text not in field_labels:
                        field_labels.append(criterion_text)
        
        # Emit records
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
