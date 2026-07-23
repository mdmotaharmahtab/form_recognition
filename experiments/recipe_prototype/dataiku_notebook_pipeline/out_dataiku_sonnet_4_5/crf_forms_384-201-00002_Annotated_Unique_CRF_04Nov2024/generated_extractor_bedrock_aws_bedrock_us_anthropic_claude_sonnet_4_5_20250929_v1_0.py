# This CRF document has two main page layouts:
# 1. Regular form pages with "Form: <name>" header and field questions left-aligned at x=90-95
#    with numeric codes right-aligned near x=527
# 2. Data dictionary pages with tabular layout showing field metadata (Field Name, Data Type, etc.)
# Strategy: Extract form name from "Form: " line; capture field questions (left column, x<400)
# excluding answer options, page footers, and technical codes. Skip data dictionary pages.

import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Check if this is a data dictionary page (has "Field Name Data Type" header)
        is_data_dict = any(
            "Field Name Data Type" in line.text or 
            ("Field Name" in line.text and "Data Type" in line.text and line.y0 < 200)
            for line in lines
        )
        
        if is_data_dict:
            continue
        
        # Extract form name from "Form: " line
        for line in lines:
            if line.text.startswith("Form: ") and line.bold and line.y0 < 150:
                current_form = line.text[6:].strip()
                break
        
        # Extract field questions
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty lines, headers, footers, page numbers
            if not text:
                continue
            if line.y0 < 140:  # Skip header area
                continue
            if line.y0 > 680:  # Skip footer area
                continue
            
            # Skip lines that are just numeric codes (right side, near x=527)
            if line.x0 > 500 and re.match(r'^\d+$', text):
                continue
            
            # Skip answer options (right side or indented, common patterns)
            if line.x0 > 400:
                # These are typically answer choices or codes
                if re.match(r'^\d+=', text):  # "1=Absent", "2=Minimal"
                    continue
                if text in ['Yes', 'No']:
                    continue
                if re.match(r'^\d+\s*$', text):  # Just numbers
                    continue
                # Skip common answer patterns
                if any(pattern in text for pattern in ['=Absent', '=Minimal', '=Mild', '=Moderate', '=Severe', '=Extreme']):
                    continue
            
            # Skip signature prompts and instructions
            if 'password' in text.lower() or 'signature' in text.lower():
                continue
            if text.startswith('Signature Prompt:'):
                continue
            
            # Skip table headers
            if text in ['Units', 'Values', 'Pre-Filled', 'Include', 'Field OID', 'Category']:
                continue
            
            # Skip technical field codes (e.g., "LBCAT", "LBPERF", "$25")
            if re.match(r'^[A-Z_]+$', text) and len(text) < 20:
                continue
            if re.match(r'^\$\d+$', text):
                continue
            if re.match(r'^dd MMM$', text) or text == 'yyyy':
                continue
            
            # Skip lines that look like data values or codes
            if re.match(r'^[A-Z\s]+=', text):  # "CHEMISTRY =", "Y = Yes"
                continue
            if text.startswith('Fixed Unit:'):
                continue
            
            # Field questions are left-aligned (x < 400) and are descriptive text
            if line.x0 >= 90 and line.x0 < 400:
                # Must contain letters and be reasonably long
                if not re.search(r'[a-zA-Z]', text):
                    continue
                if len(text) < 5:
                    continue
                
                # Skip if it's just a continuation of values/codes
                if text.startswith('=') or text.endswith('='):
                    continue
                
                # Skip common non-field patterns
                if text in ['PANSS']:
                    continue
                if re.match(r'^\d+\s*$', text):
                    continue
                
                # Skip lines that are part of multi-line instructions
                if i > 0 and lines[i-1].x0 > 80 and lines[i-1].x0 < 100:
                    prev_text = lines[i-1].text.strip()
                    if 'Manual' in prev_text or 'Published' in prev_text:
                        continue
                
                # This looks like a field question
                results.append({
                    "form_name": current_form,
                    "field_name": text,
                    "page": page_num
                })
    
    return results
