Looking at the issues:

1. **Page 31**: Extracting "O %" which is not a field (it's a radio button option marker)
2. **Cluster 1 (71 pages, 0% covered)**: Code list pages like "CSSRS Deterrents", "DM Ethnic" - these are reference tables, not data-entry forms
3. **Cluster 3 (7 pages, 0% covered)**: Pages with only metadata annotations in the right margin

The program is mostly working well. I need to:
- Strengthen the filter to exclude "O %" patterns
- Confirm code list pages are being skipped (they should be, but let me verify the logic)
- Cluster 3 pages have no fields, so 0% coverage is correct

Let me fix the "O %" issue and ensure robust handling:

```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    processed_field_indices = set()
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Sort lines for processing
        lines_by_y = sorted(lines, key=lambda ln: (ln.y0, ln.x0))
        
        # Identify form name (white text on colored background, sz=12, y ~34-36)
        form_name_line = None
        for line in lines_by_y:
            if (line.size >= 11.5 and line.size <= 12.5 and 
                line.y0 >= 30 and line.y0 <= 40 and
                line.non_black and
                line.text.strip() and
                not line.text.startswith("Origin:")):
                form_name_line = line
                break
        
        if form_name_line:
            current_form = form_name_line.text.strip()
        
        # Skip navigation/index pages (detect by "Study Events" header or dense form lists)
        has_study_events_header = any(
            "Study Events" in ln.text and ln.non_black 
            for ln in lines_by_y[:10]
        )
        if has_study_events_header:
            continue
        
        # Skip code list pages (detect by "Coded" and "Decode" headers)
        has_codelist_headers = False
        for i, line in enumerate(lines_by_y[:20]):
            if "Coded" in line.text:
                for j in range(max(0, i-2), min(len(lines_by_y), i+3)):
                    if "Decode" in lines_by_y[j].text:
                        has_codelist_headers = True
                        break
        if has_codelist_headers:
            continue
        
        # Extract fields from form pages
        if not current_form or page_num == 1:
            continue
        
        # Reset processed indices for this page
        processed_field_indices.clear()
        
        # Identify field labels: left-side text (x < 250) that looks like questions
        for i, line in enumerate(lines_by_y):
            if i in processed_field_indices:
                continue
                
            text = line.text.strip()
            
            # Field labels are on the left side
            if line.x0 > 250 or line.x0 < 40:
                continue
            
            # Skip metadata annotations (SAS field names, format specs, etc.)
            if (re.match(r'^\[.*\]$', text) or
                text.startswith("Format:") or
                text.startswith("Data Type:") or
                text.startswith("Origin:") or
                text.startswith("Description:") or
                text.startswith("Mandatory?:") or
                text.startswith("SDS Var Name:") or
                text.startswith("Device Parameter:") or
                text.startswith("Aliases:") or
                text.startswith("Code List:") or
                text.startswith("Range") or
                text.startswith("Units:") or
                text.startswith("Disallow Future") or
                text.startswith("Requires") or
                text.startswith("Conditional") or
                text.startswith("Edit Checks:") or
                text.startswith("Visible If") or
                text.startswith("Repeating:") or
                text.startswith("Domain:") or
                text.startswith("Comment:") or
                text.startswith("Short Name") or
                re.match(r'^O\s+.*', text)):  # Radio button options (O followed by space)
                continue
            
            # Skip small font metadata
            if line.size < 7.0:
                continue
            
            # Skip section headers (colored text with technical markers)
            if line.non_black and ("Origin: CRF" in text or "Repeating:" in text):
                continue
            
            # Identify actual field labels (size ~7.5, black text, left-aligned)
            if (line.size >= 7.0 and line.size <= 8.0 and 
                not line.non_black and
                len(text) > 0 and
                not text.isdigit() and
                not re.match(r'^[\[\]_\-|:\.]+$', text)):
                
                # Build field name by joining wrapped lines
                field_parts = [text]
                last_y = line.y0
                processed_field_indices.add(i)
                
                # Look ahead for continuation lines (similar x, close y, same style)
                for j in range(i + 1, min(i + 10, len(lines_by_y))):
                    if j in processed_field_indices:
                        continue
                        
                    next_line = lines_by_y[j]
                    
                    # Stop at metadata or different structure
                    if (next_line.x0 > 250 or
                        next_line.text.strip().startswith("[") or
                        next_line.non_black or
                        next_line.size < 6.5):
                        break
                    
                    next_text = next_line.text.strip()
                    
                    # Stop at metadata keywords or radio options
                    if (next_text.startswith("Format:") or
                        next_text.startswith("Data Type:") or
                        next_text.startswith("Origin:") or
                        re.match(r'^O\s+', next_text)):
                        break
                    
                    # Check if this is a continuation line
                    y_diff = abs(next_line.y0 - last_y)
                    x_diff = abs(next_line.x0 - line.x0)
                    
                    # Accept lines that are:
                    # 1. Close in Y (within 20 points, typical line spacing)
                    # 2. Similar X position (within 30 points for slight indents)
                    # 3. Not empty
                    # 4. Look like continuation text (start with lowercase or are short)
                    if (y_diff <= 20 and x_diff < 30 and len(next_text) > 0 and
                        not next_text.startswith("[") and
                        not re.match(r'^[\d\s\-_\[\]]+$', next_text)):
                        
                        # This looks like a continuation
                        field_parts.append(next_text)
                        last_y = next_line.y0
                        processed_field_indices.add(j)
                    elif y_diff > 20:
                        # Too far away vertically, stop looking
                        break
                
                field_name = " ".join(field_parts).strip()
                
                # Filter out non-field text:
                # - Must be at least 2 chars
                # - Cannot be only digits, spaces, punctuation
                # - Cannot match radio button patterns (O followed by anything)
                # - Must have current_form set
                if (len(field_name) >= 2 and
                    not re.match(r'^[\d\s\-_\[\]]+$', field_name) and
                    not re.match(r'^O\s+', field_name) and
                    not re.match(r'^O\s*%', field_name) and
                    not re.match(r'^O\s*$', field_name) and
                    current_form):
                    results.append({
                        "form_name": current_form,
                        "field_name": field_name,
                        "page": page_num
                    })
    
    return results
```
