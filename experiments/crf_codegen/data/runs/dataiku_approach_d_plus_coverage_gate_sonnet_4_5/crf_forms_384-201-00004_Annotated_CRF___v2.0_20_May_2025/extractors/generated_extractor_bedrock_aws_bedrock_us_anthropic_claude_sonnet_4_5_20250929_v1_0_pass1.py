# Clinical trial annotated CRF with form headers in white-on-color boxes,
# fields as left-aligned labels (~x=46), and technical annotations on right.
# Carry forward form names across continuation pages.

import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form name: large white text on colored background at top
        form_candidate = None
        for line in lines[:10]:  # Check first few lines
            if line.size >= 11.0 and line.size <= 13.0 and line.x0 < 100:
                # Check if it's white text (non_black flag may indicate colored background)
                # White text typically appears with specific formatting
                text = line.text.strip()
                if text and not text.startswith('384-201-') and 'Sponsor Name:' not in text and 'Protocol' not in text:
                    # Likely a form header
                    form_candidate = text
                    break
        
        if form_candidate:
            current_form = form_candidate
        
        # Extract fields: look for labels at x ≈ 40-55, size ≈ 7-8pt, black text
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field label criteria: x in left column, reasonable size, not technical annotation
            if (40 <= line.x0 <= 60 and 
                6.5 <= line.size <= 8.5 and 
                not line.non_black and
                line.text.strip()):
                
                text = line.text.strip()
                
                # Skip technical annotations (bracketed codes, SAS field names)
                if text.startswith('[') and text.endswith(']'):
                    i += 1
                    continue
                
                # Skip answer options (start with O, checkbox markers)
                if text.startswith('O ') or text.startswith('□'):
                    i += 1
                    continue
                
                # Skip pure numbers, dates, or very short fragments
                if re.match(r'^[\d\-/:.]+$', text) or len(text) < 3:
                    i += 1
                    continue
                
                # Skip common non-field patterns
                if text in ['dd-MMM-yyyy', 'dd-MMM-yyyy HH:mm:ss', 'Code List:', 'Format:', 'Data Type:']:
                    i += 1
                    continue
                
                # Check if this looks like a field label (contains question words or descriptive text)
                # Collect multi-line labels
                field_parts = [text]
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Continuation line: similar x, similar size, within reasonable y distance
                    if (40 <= next_line.x0 <= 60 and
                        abs(next_line.size - line.size) < 1.0 and
                        next_line.y0 - lines[j-1].y0 < 20 and
                        not next_line.text.strip().startswith('[') and
                        not next_line.text.strip().startswith('O ')):
                        
                        next_text = next_line.text.strip()
                        # Stop if we hit technical annotations or options
                        if next_text.startswith('[') or next_text.startswith('O ') or not next_text:
                            break
                        field_parts.append(next_text)
                        j += 1
                    else:
                        break
                
                field_name = ' '.join(field_parts)
                
                # Final validation: must be substantive text, not just codes
                if (len(field_name) > 5 and 
                    not re.match(r'^[A-Z]{2,10}$', field_name) and  # Not just uppercase code
                    not field_name.startswith('SAS Field Name:') and
                    not field_name.startswith('Odm OID')):
                    
                    results.append({
                        "form_name": current_form,
                        "field_name": field_name,
                        "page": page_num
                    })
                
                i = j if j > i + 1 else i + 1
            else:
                i += 1
    
    return results
