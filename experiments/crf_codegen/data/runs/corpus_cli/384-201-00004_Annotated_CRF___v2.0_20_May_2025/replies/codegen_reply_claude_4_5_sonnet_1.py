```python
# This CRF has multiple layout families:
# - Family A/B: cover/approval pages (no fields)
# - Family C: study event schedule tables with Form column
# - Family D: detailed form pages with field specifications
# - Family E: full field detail pages with question labels and metadata
# Strategy: Extract form_name from page headers (white bg at top), field_name from
# question text. Skip reference tables, machine codes, and metadata annotations.

import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Convert to Line objects if needed
        if lines and not isinstance(lines[0], Line):
            lines = [Line(text=l.get('text', ''), x0=l.get('x0', 0), y0=l.get('y0', 0),
                         x1=l.get('x1', 0), y1=l.get('y1', 0), size=l.get('size', 0),
                         bold=l.get('bold', False), non_black=l.get('non_black', False))
                    for l in lines]
        
        if not lines:
            continue
        
        # Extract form name from page header (white background, size ~12, y < 60)
        form_candidates = [l for l in lines if l.y0 < 60 and l.size >= 11 and l.size <= 13]
        for fc in form_candidates:
            text = fc.text.strip()
            # Skip protocol numbers, sponsors, study IDs
            if re.match(r'^(DM-\d|Sponsor|Protocol|384-|Otsuka|aCRF)', text):
                continue
            if re.match(r'^\d+$', text) or 'Commercialization' in text:
                continue
            if len(text) > 10 and not re.match(r'^\d', text):
                current_form = text
                break
        
        # Identify page type by structure
        # Family A/B: approval/cover pages - skip
        if any('aCRF Approval Form' in l.text or 'By signing below' in l.text for l in lines):
            continue
        
        # Family C: schedule tables with "Study Event" and "Form" columns
        has_study_event_col = any('Study Event' in l.text and l.size >= 10 for l in lines)
        has_form_col = any(l.text == 'Form' and l.size >= 10 for l in lines)
        
        if has_study_event_col and has_form_col:
            # Skip - these are schedule/index pages, not data entry forms
            continue
        
        # Reference tables (lab panels, codelists) - have Name/Order ID/Container headers
        has_name_header = any(l.text == 'Name' and l.size >= 10 and l.y0 < 100 for l in lines)
        has_orderid_header = any('Order ID' in l.text and l.size >= 10 and l.y0 < 100 for l in lines)
        has_coded_header = any(l.text == 'Coded' and l.size >= 10 and l.y0 < 100 for l in lines)
        
        if (has_name_header and has_orderid_header) or (has_coded_header):
            # Reference table, not data entry
            continue
        
        # Family D/E: field detail pages
        # Look for field labels (left column, moderate size, not metadata)
        fields = []
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty, page numbers, URLs, headers/footers
            if not text or line.y0 > 800 or line.y0 < 15:
                i += 1
                continue
            
            # Skip machine codes in brackets like [CMYN], [SAS Field Name: ...]
            if re.match(r'^\[.*\]$', text):
                i += 1
                continue
            
            # Skip metadata lines (right column with x > 400, small size < 8)
            if line.x0 > 400 and line.size < 8:
                i += 1
                continue
            
            # Skip "Conditionally Visible", "Origin: CRF", technical annotations
            if text in ['Conditionally Visible', 'Scheduled', 'Aliases:', 'Code List:', 
                       'Description:', 'Mandatory?:', 'Format:', 'Data Type:', 'Origin: CRF',
                       'Disallow Future Date:', 'Range (soft):', 'Range (hard):',
                       'Edit Checks:', 'SDS Var Name:', 'Device Parameter:', 'Units:',
                       'Sample Path:', 'Requires Role:', 'Requires Barcode Verification',
                       'Default Item Value:', 'Conditional Item:', 'Visible If Value:',
                       'Role Restriction:']:
                i += 1
                continue
            
            # Skip lines starting with technical prefixes
            if re.match(r'^(Odm OID|CC Mapping|Form:|Study Event:|Timepoint:|Lab Panel:|Sample Path:)', text):
                i += 1
                continue
            
            # Skip answer options (radio buttons "O Yes", "O No", etc.)
            if re.match(r'^O\s+\w', text):
                i += 1
                continue
            
            # Skip form/section headers (cyan color, size 10-12, specific pattern)
            if line.non_black and line.size >= 10 and line.size <= 12:
                # These are section headers like "CM", "Electrocardiogram 2", etc.
                i += 1
                continue
            
            # Field labels: left side (x < 250), reasonable size (7-10), not bold header
            if line.x0 >= 40 and line.x0 < 250 and line.size >= 7 and line.size <= 10:
                # Check if it looks like a question/label
                # Skip if it's just a code or number
                if re.match(r'^[\d\-\|_\[\]]+$', text):
                    i += 1
                    continue
                
                # Skip date/time formats
                if re.match(r'^dd-MMM-yyyy', text):
                    i += 1
                    continue
                
                # Skip very short text unless it's a known abbreviation
                if len(text) < 3:
                    i += 1
                    continue
                
                # Collect multi-line labels (continuation lines with similar x position)
                label_parts = [text]
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Check if continuation (similar x, close y, same zone)
                    if (abs(next_line.x0 - line.x0) < 10 and 
                        next_line.y0 - lines[j-1].y0 < 15 and
                        next_line.x0 < 250 and
                        next_line.size >= 6 and next_line.size <= 10):
                        next_text = next_line.text.strip()
                        # Stop if we hit a bracket code or empty line
                        if not next_text or re.match(r'^\[.*\]$', next_text):
                            break
                        label_parts.append(next_text)
                        j += 1
                    else:
                        break
                
                full_label = ' '.join(label_parts)
                
                # Filter out non-field text
                # Skip if it looks like a comment or instruction
                if re.match(r'^(Comment:|Verify|Collect|Keep)', full_label):
                    i = j
                    continue
                
                # Skip archived forms
                if '(archived)' in full_label:
                    i = j
                    continue
                
                # Skip lab panel names appearing in isolation
                if full_label in ['CHOLESTEROL, TOTAL', 'DIRECT LDL', 'GGT', 'HDL CHOLESTEROL',
                                  'LDH, TOTAL', 'MAGNESIUM', 'TRIGLYCERIDES',
                                  'PARTIAL THROMBOPLASTIN TIME, ACTIVATED', 'PROTHROMBIN TIME - INR']:
                    i = j
                    continue
                
                # Valid field - add if form name exists and label is substantive
                if current_form and len(full_label) >= 5:
                    results.append({
                        "form_name": current_form,
                        "field_name": full_label,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for r in results:
        key = (r['form_name'], r['field_name'])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    
    return deduped
```
