Looking at the issues, I need to:

1. **Fix missing fields on pages 4, 56, 127** - These are fields being skipped by my current filters
2. **Handle cluster 1 (code list pages)** - Currently skipping these entirely, but they appear to be legitimate code list pages with no fields (0% coverage is correct)
3. **Improve cluster 2 coverage** - Pages with multiple-choice options where some fields are being missed

Let me analyze the sample pages:

- **Page 27 (cluster 0)**: Shows fields like "Total number of aborted attempts" and "If yes. describe:" - these should be extracted
- **Page 48 (cluster 0)**: Shows fields like "RR" and "EGTXT" and "ECG Acquisition Date and Time" - technical field names that should be extracted
- **Page 150, 163 (cluster 1)**: Pure code list pages (Coded/Decode tables) - correctly have 0% coverage
- **Page 32, 96 (cluster 2)**: Multiple choice fields with numbered criteria - some being extracted, others missed

The main issues:
1. My filters are too aggressive, skipping valid fields
2. Need to better handle fields that appear just above input elements
3. Need to recognize fields near radio button options (O Yes / O No patterns)

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
        
        # Primary strategy: Left-aligned field labels (x ~ 40-70)
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
            
            # Skip metadata keywords (but allow them in multi-line continuation)
            if any(text.startswith(keyword) for keyword in ["SAS Field Name:", "Origin:", "Aliases:", 
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
            
            # Skip very short text (but allow 2-3 char technical codes like "RR")
            if len(text) < 2:
                i += 1
                continue
            
            # Skip pure numbers, dates
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
            
            # Look for input fields (broader search)
            has_input = False
            for j in range(max(0, i - 3), min(len(lines), i + 10)):
                check_line = lines[j]
                if 200 <= check_line.x0 <= 450:
                    if "[_" in check_line.text or check_line.text.strip().startswith("O "):
                        has_input = True
                        break
            
            # Expanded field-like keywords
            is_field_like = any(keyword in text.lower() for keyword in [
                "date", "time", "medication", "route", "dose", "result", 
                "collection", "clinical", "significance", "question", "total",
                "number", "describe", "ongoing", "frequency", "administration",
                "acquisition", "attempt", "behavior", "exposure", "history",
                "presenting", "uncontrolled", "symptomatic", "decrease", "average",
                "rate", "heart", "range", "ecg", "rr", "qrs", "taken", "relationship",
                "interval", "wave", "axis", "amplitude", "duration", "severity",
                "action", "concomitant", "response", "given", "event", "product",
                "acquisition", "other", "what", "preparatory", "acts"
            ])
            
            # Check for numbered criteria (e.g., "17. Exposure to...")
            is_numbered_criteria = re.match(r'^\d{1,2}\.\s+[A-Z]', text)
            
            # Check for short technical field codes (2-4 uppercase letters/numbers)
            is_short_code = re.match(r'^[A-Z]{2,4}$', text) or re.match(r'^[A-Z]+\d+$', text)
            
            # Check for question-like patterns
            is_question = text.endswith("?") or text.startswith("Were ") or text.startswith("Was ") or \
                         text.startswith("Is ") or text.startswith("What ") or text.startswith("Have ")
            
            # Extract if it looks like a field
            if has_code or has_input or is_field_like or is_numbered_criteria or is_short_code or is_question:
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
                    
                    # Stop at metadata that starts a line
                    if any(next_line.text.strip().startswith(kw) for kw in ["SAS Field Name:", "Code List:", 
                                                            "Mandatory?:", "Origin:", "Format:",
                                                            "Data Type:", "Description:",
                                                            "Aliases:", "Odm OID"]):
                        break
                    
                    # Stop at next field (similar characteristics but far down)
                    if abs(next_line.x0 - line.x0) < 10 and \
                       abs(next_line.size - line.size) < 1.0 and \
                       next_line.y0 - lines[j-1].y0 > 30:
                        break
                    
                    # Continue if similar position, size, not too far down
                    if abs(next_line.x0 - line.x0) < 15 and \
                       abs(next_line.size - line.size) < 2.0 and \
                       next_line.y0 - lines[j-1].y0 < 30 and \
                       not next_line.non_black and \
                       next_line.x0 < 280:
                        
                        field_label += " " + next_line.text.strip()
                        j += 1
                    else:
                        break
                
                field_label = " ".join(field_label.split())
                
                # Final validation: reasonable length, not just a code
                if len(field_label) >= 2 and not field_label.startswith("["):
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
