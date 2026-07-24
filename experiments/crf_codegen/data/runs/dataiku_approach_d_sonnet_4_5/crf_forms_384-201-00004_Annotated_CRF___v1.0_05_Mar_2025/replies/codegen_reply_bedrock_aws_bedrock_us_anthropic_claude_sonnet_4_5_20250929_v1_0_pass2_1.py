```python
# This CRF document contains multiple layout families:
# - Family A/B: Cover/approval pages (no data fields)
# - Family C: Study event schedules listing forms and timepoints (no data entry fields)
# - Family D: Detailed form pages with field definitions, labels, and technical annotations
# Strategy: Extract fields from family D pages by identifying field labels (human-readable text)
# and their form context (colored header bars). Skip schedules/reference tables (family C).

import re
from collections import defaultdict

def extract(pages):
    records = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Identify form name from colored header bar (white text on colored background)
        form_name = None
        for line in lines:
            # Form names appear in white text (sz ~12) on colored backgrounds near top
            if line.y0 < 60 and line.size >= 11 and line.size <= 13:
                # Check for white text (common in headers)
                text = line.text.strip()
                # Skip protocol numbers and codes
                if text and not re.match(r'^[\d\-]+$', text) and 'DM-010' not in text:
                    if 'Sponsor Name:' not in text and 'Protocol Number:' not in text:
                        # This is likely the form name
                        if form_name is None or len(text) > len(form_name):
                            form_name = text
        
        # Skip pages without form names (cover pages, schedules)
        if not form_name:
            continue
            
        # Skip schedule/table pages (family C) - they have "Study Event" and "Form" column headers
        is_schedule = False
        for line in lines:
            if line.y0 < 80 and 'Study Event' in line.text and line.bold:
                is_schedule = True
                break
        if is_schedule:
            continue
            
        # Skip reference table pages (lab panels, code lists) - they have specific headers
        is_reference_table = False
        for line in lines:
            if line.y0 < 80:
                text = line.text.strip()
                if text in ['Name', 'Order ID', 'Container', 'Units', 'Sex', 'Coded', 'Decode']:
                    if line.bold:
                        is_reference_table = True
                        break
        if is_reference_table:
            continue
        
        # Extract field labels from family D pages
        # Field labels are left-aligned (x ~46-47), size ~7.5, not in brackets, not options
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty lines
            if not text:
                continue
                
            # Field labels are typically at x ~46-47, size 7.5
            if line.x0 >= 44 and line.x0 <= 50 and line.size >= 7.0 and line.size <= 8.0:
                # Skip technical annotations in brackets
                if text.startswith('[') and text.endswith(']'):
                    continue
                    
                # Skip SAS field names
                if 'SAS Field Name:' in text:
                    continue
                    
                # Skip answer options (lines starting with O)
                if text.startswith('O '):
                    continue
                    
                # Skip code list labels
                if text.startswith('Code List:'):
                    continue
                    
                # Skip documentation/instruction text (gray color)
                if line.non_black:
                    continue
                    
                # Skip numbered list items that are criteria/instructions
                if re.match(r'^\d+\.\s', text):
                    # Check if this is an inclusion/exclusion criterion
                    if 'Inclusion' in form_name or 'Exclusion' in form_name or 'Eligibility' in form_name:
                        # These are the actual field labels
                        records.append({
                            "form_name": form_name,
                            "field_name": text,
                            "page": page_num
                        })
                    continue
                
                # Valid field labels are questions or descriptive phrases
                # They should not be single words in all caps (those are codes)
                if len(text) > 3 and not (text.isupper() and ' ' not in text):
                    # Check if this looks like a field label (contains question mark or descriptive text)
                    if '?' in text or len(text.split()) >= 3:
                        # Join continuation lines if next line is also at similar x position
                        full_label = text
                        j = i + 1
                        while j < len(lines):
                            next_line = lines[j]
                            # Check if continuation (similar x, similar size, not bracket, not option)
                            if (next_line.x0 >= 44 and next_line.x0 <= 55 and 
                                next_line.size >= 6.0 and next_line.size <= 8.5 and
                                not next_line.text.strip().startswith('[') and
                                not next_line.text.strip().startswith('O ') and
                                not next_line.text.strip().startswith('Code List:') and
                                next_line.y0 - line.y0 < 50):  # Within reasonable distance
                                
                                next_text = next_line.text.strip()
                                # Stop at next field or technical marker
                                if next_text.startswith('[') or 'SAS Field Name:' in next_text:
                                    break
                                # Append continuation
                                if next_text and not next_text.startswith('O '):
                                    full_label += ' ' + next_text
                                j += 1
                            else:
                                break
                        
                        # Clean up the label
                        full_label = ' '.join(full_label.split())
                        
                        # Skip if it's just a code or very short
                        if len(full_label) > 10:
                            records.append({
                                "form_name": form_name,
                                "field_name": full_label,
                                "page": page_num
                            })
    
    # Deduplicate records
    seen = set()
    unique_records = []
    for rec in records:
        key = (rec['form_name'], rec['field_name'])
        if key not in seen:
            seen.add(key)
            unique_records.append(rec)
    
    return unique_records
```