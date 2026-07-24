```python
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
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty lines
            if not text:
                i += 1
                continue
                
            # Field labels are typically at x ~46-47, size 7.5
            if line.x0 >= 44 and line.x0 <= 50 and line.size >= 7.0 and line.size <= 8.0:
                # Skip technical annotations in brackets
                if text.startswith('[') and text.endswith(']'):
                    i += 1
                    continue
                    
                # Skip SAS field names
                if 'SAS Field Name:' in text:
                    i += 1
                    continue
                    
                # Skip answer options (lines starting with O)
                if text.startswith('O '):
                    i += 1
                    continue
                    
                # Skip code list labels
                if text.startswith('Code List:'):
                    i += 1
                    continue
                    
                # Skip documentation/instruction text (gray color)
                if line.non_black:
                    i += 1
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
                    i += 1
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
            
            # NEW: Also check for field labels that appear as standalone short phrases
            # These are at x ~46-47, size 7.5, and are followed by answer options or technical annotations
            # Examples: "given for", "Total dose", "Dose form", "Dose unit", "Frequency", "Indication", "Start date", "Stop date"
            if line.x0 >= 44 and line.x0 <= 50 and line.size >= 7.0 and line.size <= 8.0:
                # Check if this is a short field label (1-3 words, not starting with special chars)
                if (not text.startswith('[') and not text.startswith('O ') and 
                    not text.startswith('Code List:') and not 'SAS Field Name:' in text and
                    not line.non_black):
                    
                    word_count = len(text.split())
                    # Short labels (1-3 words) that are likely field names
                    if word_count >= 1 and word_count <= 3 and len(text) >= 4:
                        # Check if followed by technical annotations or answer options
                        # Look ahead to see if next few lines have brackets, options, or technical markers
                        has_technical_context = False
                        for j in range(i + 1, min(i + 5, len(lines))):
                            next_line = lines[j]
                            next_text = next_line.text.strip()
                            # Check for technical markers
                            if (next_text.startswith('[') or next_text.startswith('O ') or
                                'SAS Field Name:' in next_text or 'Code List:' in next_text or
                                next_line.x0 > 400):  # Right column technical annotations
                                has_technical_context = True
                                break
                        
                        # If it has technical context, it's likely a field label
                        if has_technical_context:
                            # Avoid duplicates and very generic terms
                            if text not in ['Yes', 'No', 'Date', 'Time', 'Name', 'Type']:
                                records.append({
                                    "form_name": form_name,
                                    "field_name": text,
                                    "page": page_num
                                })
            
            i += 1
    
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