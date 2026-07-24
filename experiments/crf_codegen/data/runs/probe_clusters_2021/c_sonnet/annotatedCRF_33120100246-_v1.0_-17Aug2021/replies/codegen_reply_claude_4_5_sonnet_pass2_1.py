```python
# This CRF document contains multiple layout families:
# - Family A: Table of contents with section links
# - Family B: Continuation of table of contents
# - Family C/D: Laboratory results pages with lists of assays and investigator comments
# - Family E: Exclusion/inclusion criteria with row-based questions
# - Additional families visible in title-context pages showing various assessment forms
#
# Strategy: Extract fields based on structural patterns:
# 1. Identify form titles from large blue text (sz ~14.4, color #004c99 or similar)
# 2. Field labels are black text followed by answer options or entry space
# 3. Skip red text (technical annotations with [CODES] and TYPE specifications)
# 4. Skip table-of-contents pages (families A/B with blue hyperlinks)
# 5. For multi-line labels, join continuation lines based on y-coordinate proximity
# 6. Skip answer options (Yes/No/N/A choices) and table headers

import re

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip empty pages
        if not lines:
            continue
        
        # Detect form title: large blue text, typically sz >= 13
        form_candidates = [
            ln for ln in lines 
            if ln.size >= 13.0 and ln.non_black and ln.y0 < 200
        ]
        
        if form_candidates:
            # Pick the first substantial form title
            for candidate in form_candidates:
                text = candidate.text.strip()
                # Skip table-of-contents entries (they have numeric prefixes like "3.1.")
                if re.match(r'^\d+\.', text):
                    continue
                # Skip single-word navigation items
                if len(text) > 5 and not text.isupper():
                    current_form = text
                    break
        
        # Extract fields from black text lines
        i = 0
        while i < len(lines):
            ln = lines[i]
            
            # Skip red text (technical annotations)
            if ln.non_black and ln.size < 10:
                i += 1
                continue
            
            # Skip very small text (likely page numbers, footers)
            if ln.size < 7.5:
                i += 1
                continue
            
            # Skip rows that are just row labels
            if ln.text.strip().startswith("Row ") and len(ln.text.strip()) < 10:
                i += 1
                continue
            
            text = ln.text.strip()
            
            # Skip empty lines
            if not text:
                i += 1
                continue
            
            # Skip lines that are clearly answer options
            if text in ["Yes", "No", "N/A", "Met", "Not Met"]:
                i += 1
                continue
            
            # Skip lines that are bracketed codes
            if text.startswith("[") and text.endswith("]"):
                i += 1
                continue
            
            # Skip table headers
            if text in ["Criteria", "Met/Not Met"]:
                i += 1
                continue
            
            # Skip lines that start with technical markers
            if text.startswith("[TYPE:") or text.startswith("[VISIBILITY:"):
                i += 1
                continue
            
            # Potential field label: black text, reasonable size, left-aligned
            if not ln.non_black and ln.size >= 7.5 and ln.x0 < 100:
                # Check if this looks like a question or field label
                # Skip if it's just a list item marker like "Albumin"
                # Field labels typically end with "?" or are longer descriptive text
                
                # Accumulate multi-line labels
                label_parts = [text]
                j = i + 1
                
                # Look ahead for continuation lines
                while j < len(lines):
                    next_ln = lines[j]
                    
                    # Stop if we hit red text
                    if next_ln.non_black and next_ln.size < 10:
                        break
                    
                    # Stop if we hit answer options
                    if next_ln.text.strip() in ["Yes", "No", "N/A", "Met", "Not Met"]:
                        break
                    
                    # Stop if we hit bracketed codes
                    if next_ln.text.strip().startswith("["):
                        break
                    
                    # Continuation line: similar x position, close y position
                    if (abs(next_ln.x0 - ln.x0) < 30 and 
                        next_ln.y0 - lines[j-1].y0 < 20 and
                        not next_ln.non_black and
                        next_ln.size >= 7.5 and
                        next_ln.text.strip()):
                        label_parts.append(next_ln.text.strip())
                        j += 1
                    else:
                        break
                
                full_label = " ".join(label_parts)
                
                # Filter out non-field text
                # Skip if it's just a list of assay names without a question
                if len(full_label) < 10:
                    i = j
                    continue
                
                # Skip if it looks like instructions
                if full_label.startswith("Please go to"):
                    i = j
                    continue
                
                # Skip if it starts with "If Yes" or "If No" (follow-up instructions)
                if full_label.startswith("If Yes") or full_label.startswith("If No"):
                    i = j
                    continue
                
                # Skip explanatory text in parentheses or clarifications
                if full_label.startswith("(") or full_label.startswith("Examples"):
                    i = j
                    continue
                
                # Skip numbered exclusion/inclusion criteria text that's just the criterion number
                if re.match(r'^\\?\d+\\.?\\?$', full_label):
                    i = j
                    continue
                
                # Valid field
                if current_form:
                    records.append({
                        "form_name": current_form,
                        "field_name": full_label,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return records
```
