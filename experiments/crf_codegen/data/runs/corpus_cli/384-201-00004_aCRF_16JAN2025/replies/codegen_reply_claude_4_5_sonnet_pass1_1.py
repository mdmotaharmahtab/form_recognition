```python
# This document contains multiple layout families. This program extracts from:
# 1. "Study Events" table pages (page 2 style) - forms listed in a table
# 2. Detailed CRF form pages (pages 31, 50, 100, 131) - form name in colored
#    header, field labels in left column with technical metadata in right column
# 3. Code list pages (page 146) - these are reference tables, not data-entry fields
# Strategy: Use colored header bars and geometric patterns to identify forms and fields.

import re
from typing import List, Dict, Tuple, Any

def extract(pages):
    """
    Extract form_name and field_name from CRF pages.
    Returns list of dicts with form_name, field_name, and page (1-based).
    """
    results = []
    
    for page_index, lines in pages:
        page_num = page_index + 1
        
        # Skip title page (page 1)
        if page_num == 1:
            continue
        
        # Detect page type by examining structure
        page_type = detect_page_type(lines)
        
        if page_type == "study_events_table":
            # Study Events table - forms are listed in a table, not data-entry fields
            # Skip these pages as they don't contain data-entry fields
            continue
        
        elif page_type == "detailed_form":
            # Detailed CRF form pages with field labels
            results.extend(extract_detailed_form(lines, page_num))
        
        elif page_type == "code_list":
            # Code list reference pages - not data-entry fields
            continue
    
    return results

def detect_page_type(lines):
    """Determine the type of page based on content patterns."""
    
    # Check for "Study Events" table header
    for line in lines[:20]:
        if "Study Events" in line.text and line.non_black:
            # Check if this is a table with "Name", "Forms", "Type" headers
            for l in lines[:30]:
                if "Category Visit" in l.text or ("Forms" in l.text and "Type" in l.text):
                    return "study_events_table"
    
    # Check for code list pages - "Coded" and "Decode" headers
    coded_decode = False
    for line in lines[:30]:
        if ("Coded" in line.text and "Decode" in line.text) or \
           (line.text == "Coded" and any(l.text == "Decode" for l in lines[:30])):
            coded_decode = True
            break
    if coded_decode:
        return "code_list"
    
    # Check for detailed form pages - colored header with form name
    # Look for a colored (non_black) header in first ~10 lines with substantial text
    for line in lines[:15]:
        if line.non_black and line.size >= 10 and len(line.text.strip()) > 5:
            # Exclude "CDISC Legend" and other non-form headers
            if "CDISC" not in line.text and "Legend" not in line.text and \
               "Study Events" not in line.text:
                return "detailed_form"
    
    return "unknown"

def extract_detailed_form(lines, page_num):
    """Extract fields from detailed CRF form pages."""
    results = []
    
    # Find form name from colored header in top portion
    form_name = ""
    for i, line in enumerate(lines[:15]):
        if line.non_black and line.size >= 10 and len(line.text.strip()) > 5:
            # Skip metadata lines like "Origin: CRF"
            if "Origin:" not in line.text and "Aliases:" not in line.text:
                form_name = line.text.strip()
                break
    
    # Extract field labels from left column
    # Field labels appear at x ~ 46-50, size ~7.5, followed by bracketed codes
    # They are NOT in colored text, NOT in the right metadata column (x > 400)
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for field labels:
        # - x position around 46-50 (left column)
        # - size around 7-8 (not too small, not headers)
        # - NOT colored (field labels are black)
        # - NOT in right metadata area (x > 300)
        # - NOT bracketed codes themselves
        # - NOT answer options (e.g., "O Yes", "O No", "O TOPICAL")
        
        if 40 <= line.x0 <= 60 and 7.0 <= line.size <= 9.0 and \
           not line.non_black and line.x0 < 200:
            
            text = line.text.strip()
            
            # Skip bracketed codes like "[CMYN]", "[CMTRT]"
            if text.startswith("[") and text.endswith("]"):
                i += 1
                continue
            
            # Skip answer options (start with "O ")
            if text.startswith("O "):
                i += 1
                continue
            
            # Skip SAS field names
            if "SAS Field Name:" in text:
                i += 1
                continue
            
            # Skip metadata-like lines
            if any(keyword in text for keyword in ["Origin:", "Aliases:", "Code List:", 
                                                     "Documentation of", "Format:", "Data Type:"]):
                i += 1
                continue
            
            # Skip very short text (likely not a field label)
            if len(text) < 3:
                i += 1
                continue
            
            # Skip pure numbers, dates, codes
            if re.match(r'^[\d\-:/\s]+$', text):
                i += 1
                continue
            
            # Check if next line is a bracketed code (confirms this is a field label)
            has_code = False
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line.x0 >= 40 and next_line.x0 <= 60 and \
                   next_line.text.strip().startswith("[") and next_line.text.strip().endswith("]"):
                    has_code = True
            
            # Also check if there's an input field marker nearby (like "[____]" or "O")
            has_input = False
            for j in range(max(0, i-2), min(len(lines), i+5)):
                check_line = lines[j]
                if check_line.x0 > 200 and check_line.x0 < 300:
                    if "[_" in check_line.text or check_line.text.strip().startswith("O "):
                        has_input = True
                        break
            
            # If this looks like a field label, extract it
            if has_code or has_input or \
               any(keyword in text.lower() for keyword in ["date", "time", "medication", 
                                                            "route", "dose", "result", 
                                                            "collection", "clinical", 
                                                            "significance", "question"]):
                
                # Collect multi-line field labels
                field_label = text
                
                # Look ahead for continuation lines (same x position, similar size)
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop if we hit a bracketed code
                    if next_line.text.strip().startswith("[") and next_line.text.strip().endswith("]"):
                        break
                    
                    # Continue if it's a continuation (similar x, similar size, not too far down)
                    if abs(next_line.x0 - line.x0) < 5 and \
                       abs(next_line.size - line.size) < 1.0 and \
                       next_line.y0 - line.y0 < 20 and \
                       not next_line.text.strip().startswith("O ") and \
                       not next_line.non_black:
                        
                        field_label += " " + next_line.text.strip()
                        j += 1
                    else:
                        break
                
                # Clean up field label
                field_label = " ".join(field_label.split())
                
                # Skip if it's still too short or looks like metadata
                if len(field_label) >= 5 and not field_label.startswith("["):
                    results.append({
                        "form_name": form_name,
                        "field_name": field_label,
                        "page": page_num
                    })
                
                i = j
                continue
        
        i += 1
    
    return results
```
