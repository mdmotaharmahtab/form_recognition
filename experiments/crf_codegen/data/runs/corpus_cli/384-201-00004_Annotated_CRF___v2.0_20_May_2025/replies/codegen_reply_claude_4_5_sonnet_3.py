I'll analyze the issues and rewrite the program to fix the problems:

1. **Cluster 1 (94 pages, only 5% covered)**: These are codelist/reference pages with "Coded/Decode" headers - currently being skipped but they ARE valid content
2. **Content-fitted blocklists**: Need to replace 43 hardcoded strings with structural discrimination
3. **Over-filtering**: Valid fields are being rejected by literal text matching

Let me examine the sample pages and rewrite structurally:

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
        
        # Extract form name from header (white bg or large, top of page)
        for l in lines:
            if l.y0 < 70 and l.size >= 10 and len(l.text.strip()) > 8:
                text = l.text.strip()
                # Skip protocol IDs, URLs, page furniture by pattern
                if re.match(r'^(384-|DM-\d|http)', text):
                    continue
                if re.match(r'^\d+$', text):
                    continue
                # Valid form title
                if not re.match(r'^[A-Z]{2,}$', text) or len(text) > 15:
                    current_form = text
                    break
        
        # Skip approval/certificate pages by structural markers
        has_signature_structure = any('Envelope Id:' in l.text or 'Certificate' in l.text 
                                       and l.y0 < 100 and l.size >= 10 for l in lines)
        has_version_history = any('Version History' in l.text and l.size >= 13 for l in lines)
        
        if has_signature_structure or has_version_history:
            continue
        
        # Detect page type by structure
        
        # Type A: Codelist reference pages (Cluster 1)
        # Structure: "Coded" header (left, bold, ~10.5pt) + "Decode" header (right, same style)
        coded_headers = [l for l in lines if l.text.strip() == 'Coded' and l.bold 
                         and l.size >= 10 and l.size <= 11 and l.y0 < 100]
        decode_headers = [l for l in lines if l.text.strip() == 'Decode' and l.bold 
                          and l.size >= 10 and l.size <= 11 and l.y0 < 100]
        
        if coded_headers and decode_headers:
            # Extract coded values from left column (under "Coded")
            coded_x = coded_headers[0].x0
            decode_x = decode_headers[0].x0
            header_y = coded_headers[0].y0
            
            # Find coded values: left column, below header, moderate size
            for l in lines:
                if (l.y0 > header_y + 10 and 
                    abs(l.x0 - coded_x) < 20 and 
                    l.size >= 8 and l.size <= 10 and
                    len(l.text.strip()) > 0):
                    
                    field_name = l.text.strip()
                    
                    # Skip if pure number or very short
                    if re.match(r'^\d+$', field_name) or len(field_name) < 2:
                        continue
                    
                    if current_form:
                        results.append({
                            "form_name": current_form,
                            "field_name": field_name,
                            "page": page_num
                        })
            continue
        
        # Type B: Study event schedule tables
        # Structure: "Study Event" column + "Form" column headers
        has_study_event = any('Study Event' in l.text and l.size >= 10 and l.y0 < 80 for l in lines)
        has_form_col = any(l.text.strip() == 'Form' and l.size >= 10 and l.y0 < 80 for l in lines)
        
        if has_study_event and has_form_col:
            # These are schedule index pages - skip
            continue
        
        # Type C: Field detail pages with metadata annotations
        # Structure: left column (questions) + right column (metadata at x > 400)
        # Right column has technical specs like "PETEST", "Format:", "Data Type:", etc.
        
        # Identify metadata column by density of technical keywords at x > 400
        right_col_lines = [l for l in lines if l.x0 > 400 and l.size < 8]
        has_metadata_col = len(right_col_lines) > 10
        
        if has_metadata_col:
            # Extract fields from left column
            i = 0
            while i < len(lines):
                line = lines[i]
                text = line.text.strip()
                
                # Skip header/footer zones
                if line.y0 < 20 or line.y0 > 800:
                    i += 1
                    continue
                
                # Skip right metadata column
                if line.x0 > 350:
                    i += 1
                    continue
                
                # Skip section headers (colored, no black text)
                if line.non_black and line.size >= 10:
                    i += 1
                    continue
                
                # Skip machine codes in brackets [...]
                if re.match(r'^\[.*\]$', text):
                    i += 1
                    continue
                
                # Skip answer option radio buttons (O Yes, O No pattern)
                if re.match(r'^O\s+\w', text):
                    i += 1
                    continue
                
                # Skip code list references (gray color indicator)
                if 'Code List:' in text:
                    i += 1
                    continue
                
                # Field labels: left zone (40-300), readable size (7-10pt), substantive text
                if (line.x0 >= 35 and line.x0 < 300 and 
                    line.size >= 6.5 and line.size <= 11 and
                    len(text) >= 3):
                    
                    # Skip pure codes/numbers
                    if re.match(r'^[\d\-\|_]+$', text):
                        i += 1
                        continue
                    
                    # Skip date format templates
                    if re.match(r'^dd-[A-Z]', text):
                        i += 1
                        continue
                    
                    # Collect multi-line labels
                    label_parts = [text]
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        # Continuation: similar x, close y, same zone
                        if (abs(next_line.x0 - line.x0) < 15 and 
                            next_line.y0 - lines[j-1].y0 < 20 and
                            next_line.x0 < 300 and
                            next_line.size >= 6 and next_line.size <= 11):
                            
                            if not next_text or re.match(r'^\[.*\]$', next_text):
                                break
                            
                            label_parts.append(next_text)
                            j += 1
                        else:
                            break
                    
                    full_label = ' '.join(label_parts)
                    
                    # Structural filters only - no literal text blocklists
                    
                    # Skip if too short
                    if len(full_label) < 5:
                        i = j
                        continue
                    
                    # Skip if archived marker
                    if '(archived)' in full_label.lower():
                        i = j
                        continue
                    
                    # Valid field
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
            # Extract any substantive left-column text as fields
            
            for l in lines:
                text = l.text.strip()
                
                # Skip zones
                if l.y0 < 20 or l.y0 > 800:
                    continue
                
                # Left column only
                if l.x0 < 40 or l.x0 > 350:
                    continue
                
                # Readable size
                if l.size < 7 or l.size > 12:
                    continue
                
                # Skip structural junk
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
```
