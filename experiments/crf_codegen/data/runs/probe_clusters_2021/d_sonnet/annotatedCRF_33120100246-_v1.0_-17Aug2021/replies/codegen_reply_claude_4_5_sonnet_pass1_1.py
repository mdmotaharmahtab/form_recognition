```python
# This CRF has a consistent layout across all pages:
# - Form titles appear at y~66 in size 14.4, color #004c99
# - Field labels appear in size 7.8 black text, left-aligned at x~47.8
# - Machine codes in red (#ff0000) follow each field - these are NOT extracted
# - Answer options appear to the right or in columns - these are NOT fields
# - Pages 1-2 are table-of-contents (colored links) - extract these as sections
# Strategy: Extract form title from each page, then extract all black 7.8pt labels
# that are actual questions (filter out instructions, codes, answer options)

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Check if this is a TOC page (pages 1-2) - extract section names
        if page_num <= 4:
            for line in lines:
                # TOC entries are in color #2477cc at size 13.1
                if line.size > 12 and line.size < 14 and line.non_black:
                    text = line.text.strip()
                    # Remove numbering like "3.1." from TOC entries
                    text = re.sub(r'^\d+\.\d+\.\s*', '', text)
                    if text and not text.startswith('CHANGE HISTORY'):
                        results.append({
                            "form_name": text,
                            "field_name": text,
                            "page": page_num
                        })
            continue
        
        # Extract form title from current page (size 14.4, color #004c99, y~66)
        for line in lines:
            if line.size > 13 and line.size < 16 and line.non_black and line.y0 < 100:
                current_form = line.text.strip()
                break
        
        # Extract field labels
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels are size 7.8, black, left-aligned at x~47
            if not line.non_black and line.size > 7 and line.size < 9 and line.x0 < 60:
                text = line.text.strip()
                
                # Skip if empty
                if not text:
                    i += 1
                    continue
                
                # Skip machine codes in brackets
                if text.startswith('[') and text.endswith(']'):
                    i += 1
                    continue
                
                # Skip if it's a partial machine code line
                if text.startswith('[') or text.endswith(']'):
                    i += 1
                    continue
                
                # Skip instructions/guidance starting with "If", "Please go to"
                if text.startswith('If ') or text.startswith('Please '):
                    i += 1
                    continue
                
                # Skip row labels like "Row 1", "Row 2"
                if re.match(r'^Row \d+$', text):
                    i += 1
                    continue
                
                # Skip table headers at specific y positions (e.g., page 68)
                if line.y0 > 740 and line.y0 < 760:
                    i += 1
                    continue
                
                # Skip section markers like "(Repeatable row added with Add Row button)"
                if text.startswith('(') and text.endswith(')'):
                    i += 1
                    continue
                
                # Skip standalone values/options
                if text in ['Yes', 'No', 'Positive', 'Negative', 'Not Done', 'Scan']:
                    i += 1
                    continue
                
                # Skip headers like "Test", "Result", "Sample", "Timepoint"
                if text in ['Test', 'Result', 'Sample', 'Timepoint', 'Status', 
                           'Time of', 'Barcode', 'Backup', 'Number', 'Collection',
                           'Appearance', 'Color']:
                    i += 1
                    continue
                
                # Collect continuation lines (next lines at similar x position, no red code)
                field_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop if we hit a red code line
                    if next_line.non_black and next_line.text.strip().startswith('['):
                        break
                    
                    # Stop if x position differs significantly or size changes
                    if abs(next_line.x0 - line.x0) > 10 or abs(next_line.size - line.size) > 1:
                        break
                    
                    # Stop if y gap is too large (different section)
                    if next_line.y0 - lines[j-1].y0 > 20:
                        break
                    
                    next_text = next_line.text.strip()
                    
                    # Stop at red code or empty line
                    if not next_text or next_text.startswith('['):
                        break
                    
                    # Continuation line - append
                    if not next_line.non_black and next_line.size > 7 and next_line.size < 9:
                        field_text += ' ' + next_text
                        j += 1
                    else:
                        break
                
                # Clean up the field text
                field_text = ' '.join(field_text.split())
                
                # Final filters for valid fields
                # Must have some substantive content (not just numbers or single words)
                if len(field_text) < 5:
                    i = j if j > i + 1 else i + 1
                    continue
                
                # Skip if it looks like a table value or answer option
                if re.match(r'^[\d\-]+$', field_text):
                    i = j if j > i + 1 else i + 1
                    continue
                
                # Skip certain instruction phrases
                skip_phrases = [
                    'Log one line per',
                    'Urinalysis clinically significant abnormal assay',
                    'Urinalysis abnormal assay',
                    'Non-Compliance reason other specify',
                    'Non-Compliance reason$',
                ]
                if any(re.search(phrase, field_text) for phrase in skip_phrases):
                    i = j if j > i + 1 else i + 1
                    continue
                
                # This is a valid field
                results.append({
                    "form_name": current_form,
                    "field_name": field_text,
                    "page": page_num
                })
                
                i = j if j > i + 1 else i + 1
            else:
                i += 1
    
    # Deduplicate consecutive identical records
    deduplicated = []
    prev = None
    for rec in results:
        key = (rec['form_name'], rec['field_name'], rec['page'])
        if key != prev:
            deduplicated.append(rec)
            prev = key
    
    return deduplicated
```
