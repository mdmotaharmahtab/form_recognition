Looking at the quality gate failures, I can see several issues:

1. **Page 56 & 127**: Missing fields that appear to be in a different layout pattern than what I'm currently extracting
2. **Cluster 1 (71 pages)**: 0% coverage - these are code list pages (like "CSSRS Deterrents", "DM Ethnic") which should be skipped
3. **Cluster 0 & 2**: Need better coverage

From the sample pages:
- **Page 27**: Shows fields like "Total number of aborted attempts" and "If yes, describe:" that should be extracted
- **Page 48**: Shows technical fields like "RR", "EGTXT", "ECG Acquisition Date and Time"
- **Pages 150, 163**: Code list pages (should skip - correct to have 0% coverage)
- **Pages 32, 96**: Inclusion/exclusion criteria pages with patterns like "17. Exposure to..." that need extraction

The main issues:
1. Fields are being missed because my position/size filters are too strict
2. Multi-line field labels aren't being assembled correctly in all cases
3. Some field patterns (like numbered criteria) aren't being detected

Let me rewrite the program to fix these issues:

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
        
        # Primary strategy: Left-aligned field labels (x ~ 40-50)
        if 40 <= line.x0 <= 70 and 6.5 <= line.size <= 9.0 and \
           not line.non_black and line.x0 < 280:
            
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
                                                     "Units:", "SDS Var Name:", "Name:",
                                                     "Context:"]):
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
            
            # Check if this looks like a field label
            has_code = False
            for j in range(i + 1, min(len(lines), i + 4)):
                next_line = lines[j]
                if 40 <= next_line.x0 <= 70 and \
                   next_line.text.strip().startswith("[") and next_line.text.strip().endswith("]") and \
                   len(next_line.text.strip()) > 2:
                    has_code = True
                    break
            
            has_input = False
            for j in range(max(0, i - 3), min(len(lines), i + 8)):
                check_line = lines[j]
                if 200 <= check_line.x0 <= 400:
                    if "[_" in check_line.text or check_line.text.strip().startswith("O "):
                        has_input = True
                        break
            
            is_field_like = any(keyword in text.lower() for keyword in [
                "date", "time", "medication", "route", "dose", "result", 
                "collection", "clinical", "significance", "question", "total",
                "number", "describe", "ongoing", "frequency", "administration",
                "acquisition", "attempt", "behavior", "exposure", "history",
                "presenting", "uncontrolled", "symptomatic", "decrease", "average",
                "rate", "heart", "range", "ecg", "rr", "acquisition", "qrs",
                "interval", "wave", "axis", "amplitude", "duration"
            ])
            
            # Also check for numbered criteria (e.g., "17. Exposure to...")
            is_numbered_criteria = re.match(r'^\d{1,2}\.\s+[A-Z]', text)
            
            # Extract if it looks like a field
            if has_code or has_input or is_field_like or is_numbered_criteria:
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
                    
                    # Stop at next field (similar characteristics)
                    if abs(next_line.x0 - line.x0) < 10 and \
                       abs(next_line.size - line.size) < 1.0 and \
                       next_line.y0 - line.y0 > 30:
                        break
                    
                    # Continue if similar position, size, not too far down, not metadata
                    if abs(next_line.x0 - line.x0) < 15 and \
                       abs(next_line.size - line.size) < 2.0 and \
                       next_line.y0 - lines[j-1].y0 < 30 and \
                       not next_line.non_black and \
                       next_line.x0 < 280 and \
                       not any(kw in next_line.text for kw in ["SAS Field Name:", "Code List:", 
                                                                "Mandatory?:", "Origin:", "Format:",
                                                                "Data Type:", "Description:",
                                                                "Aliases:", "Odm OID"]):
                        
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
