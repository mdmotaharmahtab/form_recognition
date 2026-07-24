Looking at the sample pages, I can see:

1. **Page 27, 48 (cluster 0)**: These ARE detailed form pages with data-entry fields. The program is currently extracting from some cluster 0 pages (37% coverage) but missing many. Looking closely, I see field labels like "Total number of aborted attempts", "If yes. describe:", "Preparatory Acts or Behavior: Have you taken any steps...", "RR", "EGTXT", "ECG Acquisition Date and Time", "Frequency", "Administration start date and time", "Administration ongoing?" - these are all legitimate data-entry fields.

2. **Page 150, 163 (cluster 1)**: These are code list/reference pages with "Coded" and "Decode" headers. These contain NO data-entry fields - just lookup tables. The program correctly skips these.

3. **Page 32, 96 (cluster 2)**: These are detailed form pages with fields. The program extracts from some (44% coverage) but is missing fields. I see legitimate fields like "Frequency", "Administration start date and time", "Administration ongoing?", and various numbered criteria with Y/N/Unspecified options.

The main issue is that the current extraction logic for `detailed_form` pages is too restrictive. It's looking for fields at x position 40-60 with specific patterns, but many fields appear at different positions or don't follow the expected pattern of having a bracketed code immediately after.

Here's the updated program:

```python
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
        
        if page_num == 1:
            continue
        
        page_type = detect_page_type(lines)
        
        if page_type == "study_events_table":
            continue
        
        elif page_type == "detailed_form":
            results.extend(extract_detailed_form(lines, page_num))
        
        elif page_type == "code_list":
            continue
    
    return results

def detect_page_type(lines):
    """Determine the type of page based on content patterns."""
    
    for line in lines[:20]:
        if "Study Events" in line.text and line.non_black:
            for l in lines[:30]:
                if "Category Visit" in l.text or ("Forms" in l.text and "Type" in l.text):
                    return "study_events_table"
    
    coded_decode = False
    for line in lines[:30]:
        if ("Coded" in line.text and "Decode" in line.text) or \
           (line.text == "Coded" and any(l.text == "Decode" for l in lines[:30])):
            coded_decode = True
            break
    if coded_decode:
        return "code_list"
    
    for line in lines[:15]:
        if line.non_black and line.size >= 10 and len(line.text.strip()) > 5:
            if "CDISC" not in line.text and "Legend" not in line.text and \
               "Study Events" not in line.text:
                return "detailed_form"
    
    return "unknown"

def extract_detailed_form(lines, page_num):
    """Extract fields from detailed CRF form pages."""
    results = []
    
    form_name = ""
    for i, line in enumerate(lines[:15]):
        if line.non_black and line.size >= 10 and len(line.text.strip()) > 5:
            if "Origin:" not in line.text and "Aliases:" not in line.text:
                form_name = line.text.strip()
                break
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Strategy: Look for field labels at x ~ 40-50 with size ~ 7-8
        # These are typically black text, not in the metadata column (x > 400)
        if 40 <= line.x0 <= 60 and 6.5 <= line.size <= 9.0 and \
           not line.non_black and line.x0 < 250:
            
            text = line.text.strip()
            
            # Skip bracketed codes
            if text.startswith("[") and text.endswith("]"):
                i += 1
                continue
            
            # Skip answer options
            if text.startswith("O "):
                i += 1
                continue
            
            # Skip metadata keywords
            if any(keyword in text for keyword in ["SAS Field Name:", "Origin:", "Aliases:", 
                                                     "Code List:", "Documentation of", "Format:", 
                                                     "Data Type:", "Odm OID", "Description:", 
                                                     "Mandatory?:", "Disallow Future Date:",
                                                     "Edit Checks:", "Formal Expression",
                                                     "Conditionally Visible", "Conditional Item:",
                                                     "Visible If Value:", "Device Parameter:",
                                                     "Units:", "SDS Var Name:", "Name:"]):
                i += 1
                continue
            
            # Skip very short text
            if len(text) < 3:
                i += 1
                continue
            
            # Skip pure numbers, dates, codes
            if re.match(r'^[\d\-:/\s]+$', text):
                i += 1
                continue
            
            # Skip page numbers and document IDs
            if re.match(r'^\d{3}-\d{3}-\d{5}$', text):
                i += 1
                continue
            
            # Check if this looks like a field label:
            # 1. Has a bracketed code nearby (within next 3 lines)
            # 2. Or has an input field marker nearby ([____], O options)
            # 3. Or contains field-like keywords
            
            has_code = False
            for j in range(i + 1, min(len(lines), i + 4)):
                next_line = lines[j]
                if 40 <= next_line.x0 <= 60 and \
                   next_line.text.strip().startswith("[") and next_line.text.strip().endswith("]") and \
                   len(next_line.text.strip()) > 2:
                    has_code = True
                    break
            
            has_input = False
            for j in range(max(0, i - 3), min(len(lines), i + 8)):
                check_line = lines[j]
                if 200 <= check_line.x0 <= 350:
                    if "[_" in check_line.text or check_line.text.strip().startswith("O "):
                        has_input = True
                        break
            
            is_field_like = any(keyword in text.lower() for keyword in [
                "date", "time", "medication", "route", "dose", "result", 
                "collection", "clinical", "significance", "question", "total",
                "number", "describe", "ongoing", "frequency", "administration",
                "acquisition", "attempt", "behavior", "exposure", "history",
                "presenting", "uncontrolled", "symptomatic", "decrease"
            ])
            
            # Extract if it looks like a field
            if has_code or has_input or is_field_like:
                field_label = text
                
                # Collect multi-line field labels
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop at bracketed code
                    if next_line.text.strip().startswith("[") and next_line.text.strip().endswith("]"):
                        break
                    
                    # Stop at answer options
                    if next_line.text.strip().startswith("O "):
                        break
                    
                    # Continue if similar position, size, not too far down, not metadata
                    if abs(next_line.x0 - line.x0) < 10 and \
                       abs(next_line.size - line.size) < 1.5 and \
                       next_line.y0 - line.y0 < 25 and \
                       not next_line.non_black and \
                       not any(kw in next_line.text for kw in ["SAS Field Name:", "Code List:", "Mandatory?:"]):
                        
                        field_label += " " + next_line.text.strip()
                        j += 1
                    else:
                        break
                
                field_label = " ".join(field_label.split())
                
                # Final validation: reasonable length, not just a code
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
