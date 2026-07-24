import re
from typing import List, Dict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip if no lines
        if not lines:
            continue
        
        # Identify form title: large blue text (~14-17pt, color #004c99 or #1d60a4 or #2477cc)
        # These appear to be section/form headers
        for i, line in enumerate(lines):
            # Form title candidates: size 14-17, blue color
            if line.size >= 14.0 and line.size <= 17.5 and line.non_black:
                # Check if it's a blue color (common patterns: #004c99, #1d60a4, #2477cc)
                # These are form/section titles
                text = line.text.strip()
                # Skip if it's just a number or page reference
                if text and not re.match(r'^\d+$', text) and 'Page' not in text:
                    # Skip table of contents entries (they have section numbers like "3.1.")
                    if not re.match(r'^\d+\.\d+\.', text):
                        current_form = text
        
        # Extract field labels
        # Field labels are typically black text, size ~9pt, not in red (#ff0000)
        # Skip machine codes (in brackets like [VISDAT]), table headers, page numbers
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
            
            # Skip machine codes (red text in brackets)
            if line.non_black and '[' in text and ']' in text:
                i += 1
                continue
            
            # Skip red text (machine codes and technical annotations)
            if line.non_black and '#ff0000' in str(line.__dict__):
                i += 1
                continue
            
            # Skip gray text (appears to be pre-filled values)
            if line.non_black and '#999999' in str(line.__dict__):
                i += 1
                continue
            
            # Skip table column headers (common patterns)
            if text in ['Sample', 'Timepoint', 'Sample Status', 'Time of', 'Barcode', 
                       'Backup', 'Collection', 'Number', 'Barcode Number']:
                i += 1
                continue
            
            # Skip row labels like "Row 1", "Row 2", etc.
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip codes like INCL1, EXCL1, etc. (standalone) - these are answer options
            if re.match(r'^(INCL|EXCL)\d+$', text):
                i += 1
                continue
            
            # Skip copyright and reference text
            if '©' in text or 'Columbia' in text or 'reprints' in text:
                i += 1
                continue
            
            # Special case: eligibility criteria field
            # "If the subject did not meet eligibility criteria, please specify criterion number below."
            if (not line.non_black and line.size >= 8.0 and line.size <= 10.0 and
                'eligibility criteria' in text.lower() and 'specify' in text.lower()):
                # This is a field label for the eligibility checklist
                if current_form:
                    records.append({
                        "form_name": current_form,
                        "field_name": text,
                        "page": page_num
                    })
                i += 1
                continue
            
            # Field label candidates: black text, reasonable size (8-11pt)
            if not line.non_black and line.size >= 8.0 and line.size <= 11.5:
                # Check if this looks like a field label (ends with question mark or is descriptive)
                # Also check if next line is a machine code (indicates this is a field)
                is_field = False
                
                # Look ahead for machine code on next line(s)
                for j in range(i+1, min(i+4, len(lines))):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    if next_line.non_black and '[' in next_text and ']' in next_text:
                        is_field = True
                        break
                
                # Also consider standalone descriptive text as fields
                # (e.g., "Visit Date", "Time Placed in Position")
                if not is_field and len(text) > 3:
                    # Skip if it's part of instructions (contains "subject", "collect", etc.)
                    if not any(word in text.lower() for word in ['subject', 'collect', 'resting', 'position for', 'after']):
                        # Check if it's a reasonable field label length
                        if 5 <= len(text) <= 150:
                            is_field = True
                
                if is_field:
                    # Collect continuation lines (same x position, similar size, black)
                    full_text = text
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        # Stop at machine code
                        if next_line.non_black and '[' in next_text:
                            break
                        
                        # Continue if same x position (within tolerance) and black
                        if (not next_line.non_black and 
                            abs(next_line.x0 - line.x0) < 5 and
                            next_line.size >= 8.0 and next_line.size <= 11.5 and
                            len(next_text) > 0):
                            full_text += ' ' + next_text
                            j += 1
                        else:
                            break
                    
                    # Clean up the field name
                    full_text = full_text.strip()
                    
                    # Final validation: skip if too short or looks like furniture
                    if len(full_text) >= 5 and current_form:
                        records.append({
                            "form_name": current_form,
                            "field_name": full_text,
                            "page": page_num
                        })
                    
                    i = j
                    continue
            
            i += 1
    
    return records
