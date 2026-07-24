```python
# LAYOUT OBSERVATION & STRATEGY:
# - Page 1 (family A): Table of contents with section numbers and hyperlinked titles
# - Pages 2+ (family B): Continuation of TOC
# - Page 62 (family C): Tobacco/substance use form with repeating data-entry sections
# - Page 138 (family D): Technical annotation text (red TYPE/enumeration specifications)
# - Page 142 (family E): C-SSRS form with question text and answer options
# Title-context pages show form headers in large blue font (sz=14.4, color #004c99)
# Strategy: Extract form_name from large blue headers; extract field questions from
# black text that precedes technical red annotations. Skip TOC, pure annotation blocks,
# and answer options. Use geometry and color to distinguish fields from furniture.

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form title: large blue text (sz>=14, color #004c99 or #1d60a4)
        form_title_candidates = [
            ln for ln in lines
            if ln.size >= 13.5 and ln.non_black and 
            ('004c99' in str(ln.__dict__.get('_color', '')) or 
             '1d60a4' in str(ln.__dict__.get('_color', '')) or
             '2477cc' in str(ln.__dict__.get('_color', '')))
        ]
        
        # Update current form if we found a title
        for candidate in form_title_candidates:
            text = candidate.text.strip()
            # Skip TOC section headers and numbered list items
            if text and not re.match(r'^\d+\.?\d*\.?\s', text) and len(text) > 3:
                # Remove leading numbers like "3.25."
                cleaned = re.sub(r'^\d+\.?\d*\.\s*', '', text)
                if cleaned and not cleaned.upper() in ['PAGES', 'CHANGE HISTORY', 'SCHEDULE OF ASSESSMENT']:
                    current_form = cleaned
                    break
        
        # Skip TOC pages (pages with many blue hyperlinks and section numbers)
        blue_link_count = sum(1 for ln in lines if ln.non_black and ln.size >= 12 and ln.size <= 14)
        if blue_link_count > 10:
            continue
        
        # Skip pages that are mostly red technical annotations
        red_annotation_count = sum(1 for ln in lines if '[TYPE:' in ln.text or '[Read-only' in ln.text)
        if red_annotation_count > 15:
            continue
        
        # Extract fields: black text questions followed by red technical markers
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty, very short, or pure technical content
            if not text or len(text) < 5:
                continue
            if text.startswith('[') or text.startswith('(TYPE:'):
                continue
            if re.match(r'^Row \d+$', text):
                continue
            if text in ['Yes', 'No', 'Current', 'Former', 'Never', 'Per Day', 'Per Week', 
                       'Pack', 'Cigar', 'Cartridge', 'None']:
                continue
            if re.match(r'^\d+$', text):
                continue
            if re.match(r'^\(\d+\)', text):
                continue
            
            # Look for question text: black, medium size, possibly bold
            is_black = not line.non_black
            is_medium_size = 7.5 <= line.size <= 10.5
            
            if is_black and is_medium_size:
                # Check if next few lines contain red technical annotation
                has_annotation = False
                for j in range(i+1, min(i+5, len(lines))):
                    next_text = lines[j].text.strip()
                    if '[TYPE:' in next_text or re.match(r'^\[.*\]$', next_text):
                        has_annotation = True
                        break
                
                # Field criteria: ends with ? or has annotation, not an answer option
                is_question = '?' in text or has_annotation
                is_description = text.endswith(':') and not text.startswith('(')
                
                # Avoid answer option text patterns
                is_option = (
                    re.match(r'^\(\d+\)\s+', text) or
                    text.startswith('\\') or
                    'Does not apply' in text or
                    'allow zero' in text
                )
                
                if (is_question or is_description) and not is_option and current_form:
                    # Join wrapped lines: look ahead for continuation
                    full_text = text
                    k = i + 1
                    while k < len(lines) and k < i + 5:
                        next_line = lines[k]
                        next_text = next_line.text.strip()
                        # Stop at annotations or new questions
                        if next_text.startswith('[') or next_text.startswith('Row '):
                            break
                        if not next_line.non_black and abs(next_line.x0 - line.x0) < 50:
                            # Continuation line
                            if next_text and len(next_text) > 2:
                                full_text += ' ' + next_text
                            k += 1
                        else:
                            break
                    
                    # Clean up and validate
                    full_text = re.sub(r'\s+', ' ', full_text).strip()
                    if len(full_text) >= 10 and not re.match(r'^[0-9\.\s]+$', full_text):
                        results.append({
                            "form_name": current_form,
                            "field_name": full_text,
                            "page": page_num
                        })
    
    # Deduplicate consecutive identical records
    deduplicated = []
    prev = None
    for rec in results:
        key = (rec['form_name'], rec['field_name'])
        if key != prev:
            deduplicated.append(rec)
            prev = key
    
    return deduplicated
```
