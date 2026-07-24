STRATEGY:

The document is a clinical CRF with a clear structural pattern. Form/section titles appear as large (16.5pt), blue (#004c99) text near the top of pages (y~150-160). These titles persist across multiple pages, so I will track the most recent title and carry it forward when a page lacks one. Field labels are regular black text (9pt) positioned at consistent left margins (x~64), followed by technical annotations in red (#ff0000) that contain machine codes in square brackets—these annotations are landmarks but not field names. Answer options appear as smaller gray text (#999999) in columns to the right (x>400) and must be excluded. The table of contents (pages 1-2) lists section names in blue but contains no data-entry fields. Multi-column layouts like page 130 require x-coordinate separation to maintain proper field grouping. I will extract fields by identifying black text labels at the standard left margin, filtering out red technical codes, page numbers, and right-positioned option values. Pages without recognizable structure will be processed through a tolerant handler that looks for any potential field labels. Subsection headers in bold (e.g., "Not of Childbearing Potential") are contextual labels, not individual fields, but the questions beneath them are fields. I will join wrapped label lines by detecting continuation text at similar x-positions before the next technical annotation or field.

```python
# CRF extraction: form titles in large blue text, fields as black labels,
# red annotations are structural markers, gray text on right are options.
# Carry forward form titles across continuation pages.

import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip table of contents pages (pages 1-2 based on samples)
        if page_num <= 2:
            # Check if this is TOC by looking for "PAGES" or "SCHEDULE"
            has_toc_marker = any("SCHEDULE OF ASSESSMENT" in line.text or 
                                line.text == "PAGES" for line in lines)
            if has_toc_marker:
                continue
        
        # Look for form title: large (>14pt), blue, near top of page
        for line in lines:
            if line.size >= 15.0 and line.non_black and line.y0 < 250:
                # Potential form title - check if it's substantive
                text = line.text.strip()
                if text and not text.startswith('[') and len(text) > 3:
                    # Exclude page numbers and short codes
                    if not re.match(r'^Page \d+', text) and not re.match(r'^\d+$', text):
                        current_form = text
                        break
        
        # Extract fields from this page
        page_fields = extract_fields_from_page(lines, page_num)
        
        # Assign current form name to all fields
        for field in page_fields:
            field['form_name'] = current_form
            results.append(field)
    
    return results


def extract_fields_from_page(lines: List, page_num: int) -> List[Dict]:
    fields = []
    
    # Filter lines to identify field labels
    # Field labels: black text, left-aligned (x < 100), size ~9pt, not red annotations
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip red annotation lines (technical codes)
        if line.non_black and '[' in line.text:
            i += 1
            continue
        
        # Skip page numbers
        if re.match(r'^Page \d+ of \d+$', line.text.strip()):
            i += 1
            continue
        
        # Skip very small or very large text (likely not field labels)
        if line.size < 7 or line.size > 12:
            i += 1
            continue
        
        # Check if this is a potential field label
        # Left-aligned, black text, reasonable size
        if line.x0 < 120 and not line.non_black:
            text = line.text.strip()
            
            # Skip empty, very short, or pure punctuation
            if not text or len(text) < 3 or text in ['•', '-']:
                i += 1
                continue
            
            # Skip row markers and technical labels
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip bold section headers that are just context (not questions)
            # These are typically short and followed by actual questions
            if line.bold and len(text) < 50 and not text.endswith('?'):
                # Check if next non-red line is also a potential field
                next_idx = i + 1
                while next_idx < len(lines) and lines[next_idx].non_black and '[' in lines[next_idx].text:
                    next_idx += 1
                if next_idx < len(lines) and lines[next_idx].x0 < 120:
                    # This bold text is likely a subsection header, skip it
                    i += 1
                    continue
            
            # Skip answer options (right-aligned, often gray)
            if line.x0 > 400:
                i += 1
                continue
            
            # Skip common option words appearing on left (structural check)
            if text in ['Yes', 'No', 'N/A', 'NA']:
                i += 1
                continue
            
            # Collect wrapped lines for this field
            field_text = text
            j = i + 1
            
            # Look ahead for continuation lines
            while j < len(lines):
                next_line = lines[j]
                
                # Stop at red annotation (marks end of field label)
                if next_line.non_black and '[' in next_line.text:
                    break
                
                # Stop at next field (similar x position, black, similar size)
                if (next_line.x0 < 120 and not next_line.non_black and 
                    abs(next_line.size - line.size) < 2 and 
                    next_line.y0 - lines[j-1].y0 > 20):
                    break
                
                # Stop at answer options (right side)
                if next_line.x0 > 400:
                    break
                
                # Continuation line: similar x, close y, black text
                if (abs(next_line.x0 - line.x0) < 30 and 
                    next_line.y0 - lines[j-1].y0 < 20 and 
                    not next_line.non_black):
                    cont_text = next_line.text.strip()
                    if cont_text and not cont_text.startswith('['):
                        field_text += ' ' + cont_text
                    j += 1
                else:
                    break
            
            # Clean up field text
            field_text = ' '.join(field_text.split())
            
            # Final validation: exclude pure numbers, dates, and very generic text
            if (field_text and 
                not re.match(r'^\d+$', field_text) and
                not re.match(r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$', field_text) and
                len(field_text) > 5):
                
                fields.append({
                    'form_name': '',
                    'field_name': field_text,
                    'page': page_num
                })
            
            i = j
        else:
            i += 1
    
    return fields
```