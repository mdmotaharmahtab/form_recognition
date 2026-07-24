Looking at the failure report, I need to fix several issues:

1. **Page 1**: Extracting title/metadata text that isn't data-entry fields, and missing actual field labels like "Sponsor Name", "Protocol Number", etc.
2. **Page 4**: Extracting legend/navigation text instead of fields
3. **Page 18**: Extracting table headers and section labels as fields
4. **Page 84**: Missing specific field labels (PR, QRS, QT, QTcF) and wrong form attribution
5. **Page 169**: Extracting codelist values instead of the codelist name itself
6. **Pages 98, 105, 174, 218**: Sample pages showing Type C layouts with metadata annotations that need better handling

The key insight from pages 98/105 is that the actual field labels are in the LEFT column (x ~ 46.5, size 7.5, bold-free) like "Examination result", "Clinical significance", "Abnormal findings" - NOT the metadata identifiers in the right column.

Let me rewrite with better structural rules:

```python
import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Convert to Line objects
        converted_lines = []
        for l in lines:
            if isinstance(l, Line):
                converted_lines.append(l)
            elif isinstance(l, dict):
                converted_lines.append(Line(
                    text=l.get('text', ''),
                    x0=l.get('x0', 0),
                    y0=l.get('y0', 0),
                    x1=l.get('x1', 0),
                    y1=l.get('y1', 0),
                    size=l.get('size', 0),
                    bold=l.get('bold', False),
                    non_black=l.get('non_black', False)
                ))
            else:
                converted_lines.append(Line(
                    text=getattr(l, 'text', ''),
                    x0=getattr(l, 'x0', 0),
                    y0=getattr(l, 'y0', 0),
                    x1=getattr(l, 'x1', 0),
                    y1=getattr(l, 'y1', 0),
                    size=getattr(l, 'size', 0),
                    bold=getattr(l, 'bold', False),
                    non_black=getattr(l, 'non_black', False)
                ))
        
        lines = converted_lines
        
        if not lines:
            continue
        
        # Extract form name from header
        for l in lines:
            if l.y0 < 70 and l.size >= 10 and len(l.text.strip()) > 8:
                text = l.text.strip()
                if re.match(r'^(384-|DM-\d|http)', text):
                    continue
                if re.match(r'^\d+$', text):
                    continue
                if not re.match(r'^[A-Z]{2,}$', text) or len(text) > 15:
                    current_form = text
                    break
        
        # Skip approval/certificate pages
        has_signature_structure = any('Envelope Id:' in l.text or 'Certificate' in l.text 
                                       and l.y0 < 100 and l.size >= 10 for l in lines)
        has_version_history = any('Version History' in l.text and l.size >= 13 for l in lines)
        
        if has_signature_structure or has_version_history:
            continue
        
        # Type A: Codelist reference pages
        coded_headers = [l for l in lines if l.text.strip() == 'Coded' and l.bold 
                         and l.size >= 10 and l.size <= 11 and l.y0 < 100]
        decode_headers = [l for l in lines if l.text.strip() == 'Decode' and l.bold 
                          and l.size >= 10 and l.size <= 11 and l.y0 < 100]
        
        if coded_headers and decode_headers:
            # This is a codelist page - extract the codelist NAME, not the values
            # Look for the title above the Coded/Decode headers
            header_y = coded_headers[0].y0
            
            # Find title between y=30 and header_y
            title_candidates = [l for l in lines if l.y0 > 30 and l.y0 < header_y - 5 
                                and l.size >= 11 and not l.non_black
                                and len(l.text.strip()) > 3]
            
            if title_candidates:
                # Use the largest/highest priority title
                title_line = max(title_candidates, key=lambda x: x.size)
                field_name = title_line.text.strip()
                
                if current_form and len(field_name) > 3:
                    results.append({
                        "form_name": current_form,
                        "field_name": field_name,
                        "page": page_num
                    })
            continue
        
        # Type B: Study event schedule tables - extract from Form column
        has_study_event = any('Study Event' in l.text and l.size >= 10 and l.y0 < 80 for l in lines)
        form_col_headers = [l for l in lines if l.text.strip() == 'Form' and l.size >= 10 and l.y0 < 80]
        
        if has_study_event and form_col_headers:
            form_x = form_col_headers[0].x0
            header_y = form_col_headers[0].y0
            
            for l in lines:
                if (l.y0 > header_y + 10 and
                    abs(l.x0 - form_x) < 20 and
                    l.size >= 8 and l.size <= 10 and
                    len(l.text.strip()) > 5):
                    
                    field_name = l.text.strip()
                    
                    if current_form:
                        results.append({
                            "form_name": current_form,
                            "field_name": field_name,
                            "page": page_num
                        })
            continue
        
        # Check if this is a metadata annotation page (Type C)
        # Pages 98/105 show metadata in right column x > 450, size < 6
        right_col_metadata = [l for l in lines if l.x0 > 450 and l.size < 7 and l.size > 4]
        has_metadata_col = len(right_col_metadata) > 15
        
        if has_metadata_col:
            # Type C: Field detail pages with metadata annotations
            # Extract field LABELS from left column, not metadata identifiers
            
            i = 0
            while i < len(lines):
                line = lines[i]
                text = line.text.strip()
                
                # Skip header/footer regions
                if line.y0 < 25 or line.y0 > 800:
                    i += 1
                    continue
                
                # Skip right-column metadata
                if line.x0 > 400:
                    i += 1
                    continue
                
                # Skip non-black/colored text
                if line.non_black:
                    i += 1
                    continue
                
                # Skip bracketed identifiers [PEORRES], radio buttons, code list references
                if re.match(r'^\[.*\]$', text) or re.match(r'^O\s+', text) or 'Code List:' in text:
                    i += 1
                    continue
                
                # TARGET: Regular black text in left column, size 7-8, x around 46
                # This is where the actual field labels appear
                if (line.x0 >= 40 and line.x0 < 250 and 
                    line.size >= 6.5 and line.size <= 8.5 and
                    not line.bold and
                    len(text) >= 3):
                    
                    # Skip pure technical patterns
                    if re.match(r'^[\d\-\|_]+$', text) or re.match(r'^dd-[A-Z]', text):
                        i += 1
                        continue
                    
                    # Skip "SAS Field Name:" patterns
                    if re.match(r'^\[SAS Field Name:', text):
                        i += 1
                        continue
                    
                    # Collect multi-line labels
                    label_parts = [text]
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        # Continue if same column, similar size, close y-distance
                        if (abs(next_line.x0 - line.x0) < 15 and 
                            next_line.y0 - lines[j-1].y0 < 20 and
                            next_line.x0 < 250 and
                            next_line.size >= 6 and next_line.size <= 9 and
                            not next_line.non_black):
                            
                            if not next_text or re.match(r'^\[.*\]$', next_text):
                                break
                            
                            label_parts.append(next_text)
                            j += 1
                        else:
                            break
                    
                    full_label = ' '.join(label_parts)
                    
                    # Filter out short or archived items
                    if len(full_label) < 4 or '(archived)' in full_label.lower():
                        i = j
                        continue
                    
                    if current_form:
                        results.append({
                            "form_name": current_form,
                            "field_name": full_label,
                            "page": page_num
                        })
                    
                    i = j
                else:
                    i += 1
        else:
            # Type D: Simple form pages without metadata annotations
            # Look for field labels - regular text in left/center, avoiding headers/furniture
            
            for l in lines:
                text = l.text.strip()
                
                # Skip header/footer
                if l.y0 < 25 or l.y0 > 800:
                    continue
                
                # Main content area
                if l.x0 < 35 or l.x0 > 400:
                    continue
                
                # Reasonable label size
                if l.size < 6.5 or l.size > 13:
                    continue
                
                # Skip technical patterns
                if re.match(r'^(O\s+|^\[.*\]$|^dd-|^http|^384-|^DM-\d)', text):
                    continue
                
                # Skip pure numbers or dates
                if re.match(r'^[\d\-/]+$', text) or re.match(r'^\d+(MAR|APR|MAY|JUN)', text):
                    continue
                
                # Skip underscores (input lines)
                if re.match(r'^_+$', text):
                    continue
                
                # Skip legend/navigation keywords (structural filter, not blocklist)
                if (l.size >= 11 and l.y0 < 60 and 
                    any(keyword in text for keyword in ['Legend', 'Study Events', 'Forms', 'Activities'])):
                    continue
                
                # Skip table section headers (bold, larger, specific positions)
                if l.bold and l.size >= 10 and (l.y0 < 100 or 'Day' in text):
                    continue
                
                if len(text) >= 4 and current_form:
                    results.append({
                        "form_name": current_form,
                        "field_name": text,
                        "page": page_num
                    })
    
    # Deduplicate
    seen = set()
    deduped = []
    for r in results:
        key = (r['form_name'], r['field_name'])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    
    return deduped
```
