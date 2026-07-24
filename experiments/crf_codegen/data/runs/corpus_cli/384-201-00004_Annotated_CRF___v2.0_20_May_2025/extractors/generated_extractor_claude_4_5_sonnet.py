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
            coded_x = coded_headers[0].x0
            decode_x = decode_headers[0].x0
            header_y = coded_headers[0].y0
            
            for l in lines:
                if (l.y0 > header_y + 10 and 
                    abs(l.x0 - coded_x) < 30 and 
                    l.size >= 8 and l.size <= 10 and
                    len(l.text.strip()) > 0):
                    
                    field_name = l.text.strip()
                    
                    if re.match(r'^\d+$', field_name) or len(field_name) < 1:
                        continue
                    
                    if current_form:
                        results.append({
                            "form_name": current_form,
                            "field_name": field_name,
                            "page": page_num
                        })
            continue
        
        # Type B: Study event schedule tables - NOW EXTRACT FROM FORM COLUMN
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
        
        # Type C: Field detail pages with metadata annotations
        right_col_lines = [l for l in lines if l.x0 > 400 and l.size < 8]
        has_metadata_col = len(right_col_lines) > 10
        
        if has_metadata_col:
            i = 0
            while i < len(lines):
                line = lines[i]
                text = line.text.strip()
                
                if line.y0 < 20 or line.y0 > 800:
                    i += 1
                    continue
                
                if line.x0 > 350:
                    i += 1
                    continue
                
                if line.non_black and line.size >= 10:
                    i += 1
                    continue
                
                if re.match(r'^\[.*\]$', text):
                    i += 1
                    continue
                
                if re.match(r'^O\s+\w', text):
                    i += 1
                    continue
                
                if 'Code List:' in text:
                    i += 1
                    continue
                
                # Relaxed x-position filter: 40-350 instead of 35-300
                if (line.x0 >= 40 and line.x0 < 350 and 
                    line.size >= 6.5 and line.size <= 11 and
                    len(text) >= 3):
                    
                    if re.match(r'^[\d\-\|_]+$', text):
                        i += 1
                        continue
                    
                    if re.match(r'^dd-[A-Z]', text):
                        i += 1
                        continue
                    
                    label_parts = [text]
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        if (abs(next_line.x0 - line.x0) < 15 and 
                            next_line.y0 - lines[j-1].y0 < 20 and
                            next_line.x0 < 350 and
                            next_line.size >= 6 and next_line.size <= 11):
                            
                            if not next_text or re.match(r'^\[.*\]$', next_text):
                                break
                            
                            label_parts.append(next_text)
                            j += 1
                        else:
                            break
                    
                    full_label = ' '.join(label_parts)
                    
                    if len(full_label) < 5:
                        i = j
                        continue
                    
                    if '(archived)' in full_label.lower():
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
            # Type D: Simple pages without metadata column
            for l in lines:
                text = l.text.strip()
                
                if l.y0 < 20 or l.y0 > 800:
                    continue
                
                if l.x0 < 40 or l.x0 > 350:
                    continue
                
                if l.size < 7 or l.size > 12:
                    continue
                
                if re.match(r'^(O\s+|^\[.*\]$|^dd-|^http|^384-)', text):
                    continue
                
                if len(text) >= 5 and current_form:
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
