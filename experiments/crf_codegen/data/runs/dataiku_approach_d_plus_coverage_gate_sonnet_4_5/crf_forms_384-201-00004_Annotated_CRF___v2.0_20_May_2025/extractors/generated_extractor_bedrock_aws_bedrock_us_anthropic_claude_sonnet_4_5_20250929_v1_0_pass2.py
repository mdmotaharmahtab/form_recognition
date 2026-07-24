# CRF with left-side field labels (~x=46) and right-side metadata (~x=453).
# Form titles are bold colored headers with "Origin: CRF" nearby.
# Fields have input indicators: [___], O (radio), checkboxes.

import re

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip administrative/reference pages by detecting their titles
        page_text = " ".join(line.text for line in lines[:10])
        if any(skip in page_text for skip in ["aCRF Approval Form", "ELECTRONIC RECORD AND SIGNATURE DISCLOSURE"]):
            continue
        
        # Look for form/section titles: bold, colored (#31708f or similar), ~10.5pt, with "Origin: CRF" nearby
        for i, line in enumerate(lines):
            if (line.bold and line.non_black and 
                9.5 <= line.size <= 11.5 and 
                line.x0 < 100):
                # Check if "Origin: CRF" appears nearby
                nearby = lines[i:min(i+5, len(lines))]
                if any("Origin: CRF" in l.text for l in nearby):
                    # This is a form title
                    title = line.text.strip()
                    if title and not title.startswith("Aliases:"):
                        current_form = title
        
        # Extract fields: look for labels on left side with input indicators
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels typically at x ~46, size ~7.5
            if 40 <= line.x0 <= 55 and 6.5 <= line.size <= 8.5:
                text = line.text.strip()
                
                # Skip technical annotations and metadata
                if (text.startswith("[") or 
                    text.startswith("O ") or
                    "SAS Field Name" in text or
                    "Code List:" in text or
                    text in ["", "Coded", "Decode", "Name", "Order ID", "Container", "Units", "Sex"]):
                    i += 1
                    continue
                
                # Check if this is a field label by looking for input indicators nearby
                has_input = False
                field_label = text
                
                # Look ahead for input indicators
                for j in range(i, min(i+10, len(lines))):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Input indicators: brackets, radio buttons
                    if (re.search(r'\[_+\]|\[_\|_\]', next_text) or
                        (next_text.startswith("O ") and 240 <= next_line.x0 <= 260)):
                        has_input = True
                        break
                    
                    # Stop if we hit another field label or section
                    if (j > i and 40 <= next_line.x0 <= 55 and 
                        6.5 <= next_line.size <= 8.5 and
                        not next_text.startswith("[")):
                        break
                
                # Collect multi-line labels
                if has_input:
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        # Continue if same position and not a bracket/option
                        if (40 <= next_line.x0 <= 55 and 
                            6.5 <= next_line.size <= 8.5 and
                            not next_text.startswith("[") and
                            not next_text.startswith("O ") and
                            not "SAS Field Name" in next_text):
                            field_label += " " + next_text
                            j += 1
                        else:
                            break
                    
                    # Clean and validate field label
                    field_label = field_label.strip()
                    field_label = re.sub(r'\s+', ' ', field_label)
                    
                    if (field_label and 
                        len(field_label) > 2 and
                        not field_label.startswith("[") and
                        not re.match(r'^[\d\s\-:]+$', field_label)):
                        
                        records.append({
                            "form_name": current_form,
                            "field_name": field_label,
                            "page": page_num
                        })
            
            i += 1
    
    return records
