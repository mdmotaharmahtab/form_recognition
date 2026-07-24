# CRF extraction: form titles in large colored headers, fields as labeled entry points
# Carries form context forward; joins wrapped labels; excludes options/codes/furniture

import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip empty pages
        if not lines:
            continue
        
        # Exclude page footer (page numbers)
        lines = [ln for ln in lines if ln.y0 < 790]
        
        # Look for form title: large colored text near top (size >= 15, colored, y < 250)
        for ln in lines:
            if ln.size >= 15 and ln.non_black and ln.y0 < 250 and not re.search(r'Page \d+ of \d+', ln.text):
                # Potential form title
                txt = ln.text.strip()
                if txt and len(txt) > 3 and not re.match(r'^\d+$', txt):
                    current_form = txt
                    break
        
        # Collect field candidates: black text, size 9-11, not red, not in footer
        # Exclude technical codes in brackets, page numbers, and short numeric-only lines
        field_lines = []
        for ln in lines:
            txt = ln.text.strip()
            if not txt:
                continue
            # Skip red text (technical annotations)
            if ln.non_black and '#ff0000' in str(ln.__dict__):
                continue
            # Skip page numbers
            if re.match(r'^Page \d+ of \d+$', txt):
                continue
            # Skip pure codes in brackets
            if re.match(r'^\[.*\]$', txt):
                continue
            # Skip very short or numeric-only
            if len(txt) <= 2 or re.match(r'^\d+$', txt):
                continue
            # Skip column headers that are structural (Visit Num, Page Num, etc.)
            # REMOVED: Intensity of Ideation, Since Last Visit, etc. - these are actual field names
            if txt in ['Visit Num', 'Visit Label', 'Page Num', 'Page Label', 'Dynamic?', 
                       'Description of Dynamic', 'ber']:
                continue
            # Field candidates: reasonable size, black or bold
            if 8 <= ln.size <= 12 and ln.y0 < 750:
                field_lines.append((ln.y0, ln.x0, txt, ln.bold))
        
        # Group lines by proximity to join wrapped labels
        field_lines.sort()
        grouped = []
        i = 0
        while i < len(field_lines):
            y, x, txt, bold = field_lines[i]
            # Collect continuation lines (within 15 points vertically, similar x)
            parts = [txt]
            j = i + 1
            while j < len(field_lines):
                y2, x2, txt2, bold2 = field_lines[j]
                if y2 - y < 15 and abs(x2 - x) < 30:
                    parts.append(txt2)
                    y = y2
                    j += 1
                else:
                    break
            full_text = ' '.join(parts)
            grouped.append(full_text)
            i = j if j > i + 1 else i + 1
        
        # Filter to actual field names
        for field_text in grouped:
            # Skip if looks like answer option (starts with enumeration marker)
            if re.match(r'^\(\d+\)', field_text):
                continue
            # Skip if looks like table data or codes
            if re.match(r'^[A-Z0-9_]+$', field_text) and len(field_text) < 15:
                continue
            # Skip common non-field patterns
            if field_text in ['Row 1', 'Row 2', 'Row 3', 'Row 4', 'Row 5', 'Row 6', 
                              'Supine', 'Standing', 'Sample', 'Timepoint', 'Barcode Number',
                              'Time of Collection', 'Sample Status', 'Backup Barcode Number']:
                continue
            # Must have reasonable length
            if len(field_text) < 5:
                continue
            
            # Valid field
            records.append({
                "form_name": current_form,
                "field_name": field_text,
                "page": page_num
            })
    
    # Deduplicate exact matches on same page
    seen = set()
    unique = []
    for rec in records:
        key = (rec['form_name'], rec['field_name'], rec['page'])
        if key not in seen:
            seen.add(key)
            unique.append(rec)
    
    return unique
