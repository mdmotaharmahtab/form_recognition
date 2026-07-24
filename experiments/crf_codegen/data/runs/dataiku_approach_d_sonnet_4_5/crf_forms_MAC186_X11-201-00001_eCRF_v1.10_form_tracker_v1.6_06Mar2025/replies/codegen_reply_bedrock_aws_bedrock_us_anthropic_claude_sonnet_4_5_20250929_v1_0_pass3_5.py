Looking at the issues:

1. **Wrong form attribution on pages 25, 206**: These pages have numbered items (like "14. Genital Symptoms", "17. I felt...") that are being captured as fields, but the form_name is being set to one of those items instead of the actual form title.

2. **Empty form_name for 34% of records**: Need to carry forward the last seen form title.

3. **Cluster 1 (0% coverage)**: Dense tables with timing info and parameter names - the current logic tries to extract from x>500, but these pages show parameters at x~562 with numbers at x~44-47.

4. **Cluster 2 (50% coverage)**: Numbered questionnaire items - currently extracting some but missing others, likely due to form_name issues.

The key insight: numbered items like "14. Genital Symptoms" or "17. Experience of ecstasy" are **field labels**, not form names. The form name should be found earlier on the page and carried forward.

```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    last_form_name = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Find form name - look for large title (sz >= 16) or bold section name near top
        form_name = ""
        
        # First, try to find large title (sz >= 16, typically at y ~70-75)
        for line in lines:
            if line.size >= 16.0 and 60 < line.y0 < 100:
                form_name = line.text.strip()
                break
        
        # If no large title, look for bold section name at y ~48-52
        if not form_name:
            for line in lines:
                if line.bold and 45 < line.y0 < 55 and line.size >= 7.0:
                    text = line.text.strip()
                    # Skip the document ID line and numbered items
                    if "MAC186" not in text and "eCRF" not in text and not re.match(r'^\d+\.', text):
                        form_name = text
                        break
        
        # If we found a form name, update last_form_name
        if form_name:
            last_form_name = form_name
        else:
            # Use the last seen form name
            form_name = last_form_name
        
        # Detect if this is a reference table page (Family D)
        # These have numbered rows with medication/parameter names but no entry fields
        is_reference_table = False
        numbered_rows = 0
        for i, line in enumerate(lines):
            # Look for small numbers at left margin
            if 40 < line.x0 < 50 and line.text.strip().isdigit():
                num_text = line.text.strip()
                if num_text.isdigit():
                    num = int(num_text)
                    if 1 <= num <= 50:
                        numbered_rows += 1
        
        # If many numbered rows and no large title, likely a reference table
        if numbered_rows > 10 and not form_name:
            continue
        
        # Also check for "Variable details" header which indicates metadata pages
        for line in lines:
            if "Variable details" in line.text or "Export Name" in line.text:
                is_reference_table = True
                break
        
        if is_reference_table:
            continue
        
        # Extract fields
        # Look for bold text followed by bracketed codes [N]
        # Field labels are typically bold and have a bracketed code nearby
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip if not bold or too small
            if not line.bold or line.size < 6.0:
                i += 1
                continue
            
            # Skip common non-field text
            text = line.text.strip()
            if not text:
                i += 1
                continue
            
            # Skip if it's just a number (row numbers in tables)
            if text.isdigit():
                i += 1
                continue
            
            # Skip if it's a bracketed code itself
            if re.match(r'^\[\d+\]$', text):
                i += 1
                continue
            
            # Skip if it's a numbered item (these are handled separately below)
            if re.match(r'^\d+\.', text):
                i += 1
                continue
            
            # Check if there's a bracketed code nearby (within 5 lines, same or nearby y)
            has_bracket = False
            bracket_found = False
            
            # Look ahead for bracketed code
            for j in range(i, min(i + 5, len(lines))):
                next_line = lines[j]
                # Check if on same line or very close (within 10 points vertically)
                if abs(next_line.y0 - line.y0) < 10:
                    if re.search(r'\[\d+\]', next_line.text):
                        has_bracket = True
                        bracket_found = True
                        break
            
            if has_bracket:
                # This is a field label
                field_name = text
                
                # Check if field name continues on next lines (wrapping)
                # Look for non-bold text immediately below (within 10 points) at similar x position
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # If next line is close vertically and starts near same x, it's a continuation
                    if abs(next_line.y0 - (line.y0 + 8)) < 5 and abs(next_line.x0 - line.x0) < 20:
                        # Check if it's not a bracketed code
                        if not re.match(r'^\[\d+\]$', next_line.text.strip()):
                            field_name += " " + next_line.text.strip()
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # Clean up field name
                field_name = field_name.strip()
                
                results.append({
                    "form_name": form_name,
                    "field_name": field_name,
                    "page": page_num
                })
            
            i += 1
        
        # Special handling for questionnaire items (Cluster 2)
        # These have numbered items (e.g., "17. Experience of ecstasy") at x ~64
        # Pattern: number at x ~46, then statement at x ~64
        for i, line in enumerate(lines):
            # Look for numbered statements at x ~60-70
            if 60 < line.x0 < 70 and line.size >= 7.0:
                text = line.text.strip()
                # Check if it starts with a number followed by period (e.g., "17. ")
                if re.match(r'^\d+\.\s+', text):
                    # This is a questionnaire item
                    results.append({
                        "form_name": form_name,
                        "field_name": text,
                        "page": page_num
                    })
        
        # Special handling for Family E (dense tables with questions on right side)
        # Look for questions at x > 400 (right column)
        for line in lines:
            if line.x0 > 400 and line.size >= 7.0:
                text = line.text.strip()
                # Check if it looks like a question (contains "?" or starts with "How" or numbered question)
                if "?" in text or text.startswith("How ") or re.match(r'^\d+\.', text):
                    # This is a field
                    results.append({
                        "form_name": form_name,
                        "field_name": text,
                        "page": page_num
                    })
        
        # Special handling for Cluster 1 (dense parameter tables)
        # These have numbered rows with timing info and parameter names on the right
        # Pattern: number at x ~44-47, timing at x ~56, parameter name at x > 500
        # Look for lines at x > 500 that contain parameter names
        for line in lines:
            if line.x0 > 500 and line.size >= 6.0:
                text = line.text.strip()
                # Skip if it's just a number or empty
                if text and not text.isdigit():
                    # Check if there's a corresponding number at x ~44-50 on same y
                    has_number = False
                    for other_line in lines:
                        if 40 < other_line.x0 < 52 and abs(other_line.y0 - line.y0) < 5:
                            if other_line.text.strip().isdigit():
                                has_number = True
                                break
                    
                    if has_number:
                        # This is a field - parameter name
                        results.append({
                            "form_name": form_name,
                            "field_name": text,
                            "page": page_num
                        })
    
    return results
```