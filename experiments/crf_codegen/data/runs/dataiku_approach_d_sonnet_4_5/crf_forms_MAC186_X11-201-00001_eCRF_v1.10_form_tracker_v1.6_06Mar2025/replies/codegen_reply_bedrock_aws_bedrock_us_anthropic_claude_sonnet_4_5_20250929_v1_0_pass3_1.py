```python
# This CRF document has several layout families:
# - Family A: Simple visit/section title pages (e.g., "Visit: Screening")
# - Family B: Informed Consent form with labeled fields and bracketed codes
# - Family C: Standard form pages with a large title (sz=17.4), section name (sz=7.8 bold), and labeled fields with bracketed codes
# - Family D: Tabular reference lists (medication lists, vital signs details) - NOT data-entry fields
# - Family E: Dense tabular data with time points and measurements - mixed content (some fields, some table rows)
#
# Strategy:
# 1. Extract form_name from the large title (sz >= 16) or from the bold section name at y ~48-50
# 2. Extract field_name from bold text followed by bracketed codes [N] - these are data-entry fields
# 3. Skip reference tables (Family D) which list medications/parameters without entry fields
# 4. For Family E, extract only lines with actual field labels (right side, x > 400 typically)

import re
from typing import List, Dict

def extract(pages):
    results = []
    
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
        
        # If no large title, look for bold section name at y ~48-50
        if not form_name:
            for line in lines:
                if line.bold and 45 < line.y0 < 52 and line.size >= 7.0:
                    # Skip the document ID line
                    if "MAC186" not in line.text and "eCRF" not in line.text:
                        form_name = line.text.strip()
                        break
        
        # Detect if this is a reference table page (Family D)
        # These have numbered rows with medication/parameter names but no entry fields
        # They typically have 3 columns: number, category/name, details
        # Check for pattern: small numbers (< 50) at x ~45-50, followed by text at x ~60-65
        is_reference_table = False
        numbered_rows = 0
        for i, line in enumerate(lines):
            # Look for small numbers at left margin
            if 40 < line.x0 < 50 and line.text.strip().isdigit():
                num = int(line.text.strip())
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
            if not text or text in ["Yes", "No", "Complete for all parameters", "Parameter", "Not Done", "Reason Not Done", "Interpretation"]:
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
                            # Check if it's not a choice option (Yes/No at different x)
                            if next_line.text.strip() not in ["Yes", "No"] or abs(next_line.x0 - line.x0) < 50:
                                field_name += " " + next_line.text.strip()
                                j += 1
                            else:
                                break
                        else:
                            break
                    else:
                        break
                
                # Clean up field name
                field_name = field_name.strip()
                
                # Skip if it's a section header or column header
                if field_name in ["Informed Consent", "Visit Date", "Randomisation", "Haematology", "Biochemistry", "Coagulation"]:
                    # These might be form names, not field names
                    i += 1
                    continue
                
                results.append({
                    "form_name": form_name,
                    "field_name": field_name,
                    "page": page_num
                })
            
            i += 1
        
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
    
    return results
```