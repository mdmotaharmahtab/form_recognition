```python
# This CRF document has multiple layout families:
# - Family A: Table of contents / index pages
# - Family B: Continuation of table of contents
# - Family C: Change history tables
# - Family D: Reproductive status forms with checkboxes and technical annotations
# - Family E: Table-based data entry forms with column headers
# - Family F: Copyright/attribution text pages
# - Family G: Section title pages with "Repeatable row" notes
# 
# Strategy: Extract fields based on structural patterns:
# 1. Large colored headers (sz>=15, colored) are form titles
# 2. Black text questions/labels (sz~9-10.5) are field names
# 3. Skip technical annotations in red (#ff0000) or gray (#999999)
# 4. Skip table headers, copyright text, page numbers
# 5. Handle multi-line field labels by joining continuation lines
# 6. For table-based forms (Family E), column headers are field names

import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form title - large colored text (sz >= 15, colored, not black)
        form_title = None
        for line in lines:
            if line.size >= 15 and line.non_black and line.text.strip():
                # Skip "CHANGE HISTORY", "SCHEDULE OF ASSESSMENT", "PAGES" - these are TOC sections
                if line.text.strip() not in ["CHANGE HISTORY", "SCHEDULE OF ASSESSMENT", "PAGES"]:
                    form_title = line.text.strip()
                    break
        
        if form_title:
            current_form = form_title
        
        # Skip pages with no form context
        if not current_form:
            continue
        
        # Skip change history pages (Family C)
        has_change_history = any("Change History" in line.text for line in lines if line.size >= 15)
        if has_change_history:
            continue
        
        # Skip copyright/attribution pages (Family F)
        has_copyright = any("© 2008 The Research Foundation" in line.text for line in lines)
        if has_copyright:
            continue
        
        # Skip table of contents pages (Family A, B)
        is_toc = any(line.text == "Annotated CRF" and line.size >= 20 for line in lines)
        if is_toc:
            continue
        
        # Extract fields
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty lines
            if not text:
                i += 1
                continue
            
            # Skip page numbers
            if re.match(r'^Page \d+ of \d+$', text):
                i += 1
                continue
            
            # Skip red technical annotations (variable names, types, visibility)
            if line.non_black and '#ff0000' in str(line.non_black):
                i += 1
                continue
            
            # Skip gray text (placeholders, example values)
            if line.non_black and '#999999' in str(line.non_black):
                i += 1
                continue
            
            # Skip bullet points alone
            if text == '•':
                i += 1
                continue
            
            # Skip "Row N" labels
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip "(Repeatable row added with Add Row button)"
            if "Repeatable row" in text:
                i += 1
                continue
            
            # Skip form titles (already captured)
            if line.size >= 15 and line.non_black:
                i += 1
                continue
            
            # Handle table headers (Family E) - column headers at y~124-154
            if line.y0 >= 120 and line.y0 <= 160 and line.size >= 10:
                # This is a potential column header
                # Collect multi-line headers
                header_text = text
                j = i + 1
                while j < len(lines) and lines[j].y0 <= 160 and abs(lines[j].x0 - line.x0) < 20:
                    if lines[j].text.strip() and not re.match(r'^Page \d+ of \d+$', lines[j].text):
                        header_text += " " + lines[j].text.strip()
                    j += 1
                
                # Skip common non-field headers
                if header_text not in ["Record", "ID", "Sample"]:
                    if len(header_text) > 2:  # Avoid single letters
                        results.append({
                            "form_name": current_form,
                            "field_name": header_text,
                            "page": page_num
                        })
                i = j if j > i + 1 else i + 1
                continue
            
            # Regular field labels - black text, size 9-12, not bold headers
            if not line.non_black and line.size >= 8.5 and line.size <= 12:
                # Skip section headers (bold, larger)
                if line.bold and line.size >= 11:
                    i += 1
                    continue
                
                # Check if this looks like a question/field label
                # Must have reasonable length and not be a value
                if len(text) >= 3:
                    # Collect continuation lines (same x position, close y)
                    field_text = text
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        # Check if continuation (similar x, close y, not red)
                        if (abs(next_line.x0 - line.x0) < 10 and 
                            next_line.y0 - lines[j-1].y0 < 20 and
                            not (next_line.non_black and '#ff0000' in str(next_line.non_black)) and
                            next_line.text.strip() and
                            not re.match(r'^Page \d+ of \d+$', next_line.text)):
                            field_text += " " + next_line.text.strip()
                            j += 1
                        else:
                            break
                    
                    # Skip if it's just answer options (Yes/No, X, etc.)
                    if field_text in ["Yes", "No", "N/A", "X", "Scan"]:
                        i = j if j > i + 1 else i + 1
                        continue
                    
                    # Skip if it starts with a bullet and is very short (likely an option)
                    if field_text.startswith("•") and len(field_text) < 30:
                        i = j if j > i + 1 else i + 1
                        continue
                    
                    # Valid field
                    results.append({
                        "form_name": current_form,
                        "field_name": field_text,
                        "page": page_num
                    })
                    i = j if j > i + 1 else i + 1
                    continue
            
            i += 1
    
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for r in results:
        key = (r["form_name"], r["field_name"], r["page"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    
    return deduped
```