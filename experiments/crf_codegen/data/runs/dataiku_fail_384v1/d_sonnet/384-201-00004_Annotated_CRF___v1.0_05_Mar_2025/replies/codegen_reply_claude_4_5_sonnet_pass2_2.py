Looking at the feedback, I need to fix several issues:

1. **Degenerate form grouping**: I'm extracting field labels as form names instead of the actual form title that groups multiple fields
2. **Form persistence**: Only 17% of records share a form_name on the same page, indicating I'm not properly detecting the shared form title
3. **Hardcoded filters**: I'm using too many literal string matches instead of structural discrimination

Let me analyze the sample pages:

- **Pages 12, 14**: These are schedule/table pages (cluster 0) with "Study Event", "Timepoint", and "Form" columns. The forms listed here are titles like "Vital Signs Position", "ECG (RScribe)", etc.
- **Pages 120, 122**: These are detailed field annotation pages (cluster 1) with individual fields like "EXC005", "EXC006", etc. The form title should be at the top of the page (likely "Exclusion Criteria" or similar).

The key insight: I need to find the **shared form title** that groups multiple fields, not extract individual field labels as form names.

```python
import re

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Strategy 1: Schedule/TOC pages (cluster 0)
        # These have columnar layout with "Study Event", "Timepoint", "Form" headers
        # Extract form names from the "Form" column - these ARE the form titles
        
        # Look for the Form column header
        form_column_x = None
        header_y = None
        
        for i, ln in enumerate(lines):
            if ln.text.strip() == "Form" and ln.bold and ln.size >= 7:
                form_column_x = ln.x0
                header_y = ln.y0
                break
        
        if form_column_x is not None:
            # Extract form names from the Form column
            # Forms appear below the header, aligned near form_column_x
            for ln in lines:
                # Skip headers and annotations
                if ln.bold or ln.y0 <= header_y + 10:
                    continue
                # Check if this line is in the Form column (within 40pts)
                if abs(ln.x0 - form_column_x) < 40:
                    # Check vertical alignment: should be size 9pt, black text
                    if 8.5 <= ln.size <= 9.5 and not ln.non_black:
                        form_name = ln.text.strip()
                        # Filter structural junk: very short, all digits, protocol numbers
                        if len(form_name) < 3:
                            continue
                        if re.match(r'^\d+$', form_name):
                            continue
                        if re.match(r'^\d{3}-\d{3}-\d{5}$', form_name):
                            continue
                        # Skip time patterns
                        if re.match(r'^[-\d:*()]+$', form_name):
                            continue
                        # Skip day patterns
                        if re.match(r'^Day\s+[-\d]+$', form_name):
                            continue
                        
                        # This is a form title - emit one record per form
                        results.append({
                            "form_name": form_name,
                            "field_name": form_name,
                            "page": page_num
                        })
            continue
        
        # Strategy 2: Detailed field annotation pages (cluster 1)
        # These have a form title at the top and multiple fields with codes like EXC001, EXC002
        
        # Find the form title: typically large bold text near the top, or colored banner
        form_title = None
        
        # Look for colored banner or large text in the first 50 lines
        for ln in lines[:50]:
            # Large colored text (banner)
            if ln.size >= 11 and ln.non_black:
                candidate = ln.text.strip()
                # Skip protocol numbers and URL
                if re.match(r'^\d{3}-\d{3}-\d{5}$', candidate):
                    continue
                if 'clinspark.com' in candidate.lower():
                    continue
                if candidate and len(candidate) > 3:
                    form_title = candidate
                    break
            
            # Large bold black text
            if ln.size >= 10 and ln.bold and not ln.non_black:
                candidate = ln.text.strip()
                if re.match(r'^\d{3}-\d{3}-\d{5}$', candidate):
                    continue
                if candidate and len(candidate) > 5:
                    # Skip if it looks like a technical annotation
                    if not re.match(r'^(Origin|Repeating|Domain|Conditionally|Format|Data Type)', candidate):
                        form_title = candidate
                        break
        
        # If no obvious title, try to infer from field codes (e.g., EXC -> Exclusion Criteria)
        if not form_title:
            # Look for field code pattern to infer form
            for ln in lines[:100]:
                if ln.bold and 5 <= ln.size <= 6.5:
                    code = ln.text.strip()
                    # Check for common prefixes
                    if re.match(r'^(INC|EXC|DM|VS|EG|LB|CM|AE)\d{3}', code):
                        prefix = re.match(r'^([A-Z]+)', code).group(1)
                        # Map common prefixes to form names
                        prefix_map = {
                            'INC': 'Inclusion Criteria',
                            'EXC': 'Exclusion Criteria',
                            'DM': 'Demographics',
                            'VS': 'Vital Signs',
                            'EG': 'ECG',
                            'LB': 'Laboratory',
                            'CM': 'Concomitant Medications',
                            'AE': 'Adverse Events'
                        }
                        if prefix in prefix_map:
                            form_title = prefix_map[prefix]
                            break
        
        if not form_title:
            # No recognizable form structure on this page
            continue
        
        # Extract fields from this form
        # Fields are identified by:
        # - A bold field code (5-6pt) on the right side (x > 400)
        # - A field label on the left side (x < 100), size 7-8pt
        
        field_labels = []
        
        for i, ln in enumerate(lines):
            # Look for field codes: bold, small (5-6.5pt), right side (x > 400)
            if ln.bold and 5 <= ln.size <= 6.5 and ln.x0 > 400:
                code = ln.text.strip()
                # Field codes are alphanumeric uppercase, e.g., EXC005, INC001
                if re.match(r'^[A-Z]{2,}[A-Z0-9]+$', code):
                    # Find the field label: look in nearby lines
                    # Labels are on the left (x < 100), size 7-8pt, not bold
                    label = None
                    
                    # Search window: 30 lines before and after the code
                    for j in range(max(0, i-30), min(len(lines), i+30)):
                        cand_ln = lines[j]
                        # Label criteria: left side, medium size, not bold
                        if 40 < cand_ln.x0 < 100 and 7 <= cand_ln.size <= 8.5 and not cand_ln.bold:
                            cand_text = cand_ln.text.strip()
                            
                            # Skip structural junk:
                            # - Bracketed codes like [EXC005]
                            if re.match(r'^\[.*\]$', cand_text):
                                continue
                            # - Radio button options
                            if cand_text in ['O Yes', 'O No', 'O N/A', 'O Unspecified']:
                                continue
                            # - Technical metadata lines
                            if re.match(r'^(Code List:|SAS Field Name:|Format:|Data Type:|Origin:|Description:|Mandatory\?:|Disallow)', cand_text):
                                continue
                            # - Very short
                            if len(cand_text) < 5:
                                continue
                            
                            # This looks like a field label
                            label = cand_text
                            break
                    
                    if label:
                        field_labels.append(label)
        
        # Emit one record per field for this form
        for label in field_labels:
            results.append({
                "form_name": form_title,
                "field_name": label,
                "page": page_num
            })
    
    # Deduplicate results
    seen = set()
    deduplicated = []
    for rec in results:
        key = (rec["form_name"], rec["field_name"], rec["page"])
        if key not in seen:
            seen.add(key)
            deduplicated.append(rec)
    
    return deduplicated
```
