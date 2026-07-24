# Clinical CRF extraction: form titles appear at y≈48 (small) and y≈74 (large, primary).
# Fields are labels/questions, often bold, with bracketed codes. Carry form title forward.
# Skip metadata "Variable details" pages. Join multi-line labels. Distinguish fields from options/tables.

import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip metadata "Variable details" pages
        if any("Variable details" in line.text for line in lines[:10]):
            continue
        
        # Look for form title: large size ~17 near y≈74, or bold size ~7.8 near y≈48
        form_title_large = None
        form_title_small = None
        
        for line in lines[:15]:
            if 16 <= line.size <= 18 and 70 <= line.y0 <= 80:
                form_title_large = line.text.strip()
            elif line.bold and 7 <= line.size <= 8.5 and 45 <= line.y0 <= 52:
                # Exclude generic headers
                if line.text.strip() and "MAC186" not in line.text and "eCRF" not in line.text:
                    form_title_small = line.text.strip()
        
        # Update current form (prefer large title)
        if form_title_large:
            current_form = form_title_large
        elif form_title_small and not current_form:
            current_form = form_title_small
        
        # Extract fields
        fields = extract_fields_from_page(lines, page_num)
        
        for field_name in fields:
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return results

def extract_fields_from_page(lines, page_num):
    fields = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        text = line.text.strip()
        
        # Skip empty, page headers, or very short lines
        if not text or len(text) < 3 or "MAC186" in text or "eCRF" in text:
            i += 1
            continue
        
        # Skip answer options (Yes/No pairs at specific x-positions)
        if text in ["Yes", "No"] and 210 <= line.x0 <= 230:
            i += 1
            continue
        
        # Skip numeric-only lines (row numbers in tables)
        if re.match(r'^\d+$', text):
            i += 1
            continue
        
        # Skip single digits or bracketed codes alone
        if re.match(r'^\[\d+\]$', text) or (len(text) == 1 and text.isdigit()):
            i += 1
            continue
        
        # Skip column headers in tables
        if text in ["Parameter", "Not Done", "Reason Not Done", "Interpretation", 
                    "Name", "Export Name", "Type", "Max length", "Categories",
                    "Vital Signs Details"]:
            i += 1
            continue
        
        # Detect field labels: bold text with reasonable length, or questions
        is_field = False
        
        # Bold labels with bracketed codes nearby
        if line.bold and 7 <= line.size <= 8.5 and len(text) > 5:
            # Check if next few lines have bracketed code
            has_code = False
            for j in range(i, min(i+3, len(lines))):
                if re.search(r'\[\d+\]', lines[j].text):
                    has_code = True
                    break
            if has_code:
                is_field = True
        
        # Questions or longer descriptive text (likely fields)
        if len(text) > 15 and not text.startswith("Complete for"):
            # Exclude table content rows (medication names with dosages)
            if not (re.search(r'\d+mg', text) and line.x0 > 250):
                is_field = True
        
        # Time-point labels in family E (e.g., "0.25 Hours Post Dose")
        if re.search(r'(Hours?|Minutes?) Post Dose', text, re.IGNORECASE):
            # Check if this is a repeating time-point row (not a field)
            # If x0 < 100 and size < 6, likely table row
            if line.x0 > 50 and line.size >= 6:
                is_field = True
        
        if is_field:
            # Join multi-line labels
            field_text = text
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # Continuation: similar x-position, no bracketed code, reasonable y-gap
                if (abs(next_line.x0 - line.x0) < 30 and 
                    not re.match(r'^\[\d+\]', next_line.text.strip()) and
                    next_line.y0 - lines[j-1].y0 < 20 and
                    len(next_line.text.strip()) > 3 and
                    not next_line.text.strip() in ["Yes", "No"]):
                    field_text += " " + next_line.text.strip()
                    j += 1
                else:
                    break
            
            # Clean up field text
            field_text = re.sub(r'\s+', ' ', field_text).strip()
            # Remove trailing bracketed codes
            field_text = re.sub(r'\s*\[\d+\]\s*$', '', field_text)
            
            if field_text and len(field_text) > 3:
                fields.append(field_text)
            
            i = j
        else:
            i += 1
    
    return fields
