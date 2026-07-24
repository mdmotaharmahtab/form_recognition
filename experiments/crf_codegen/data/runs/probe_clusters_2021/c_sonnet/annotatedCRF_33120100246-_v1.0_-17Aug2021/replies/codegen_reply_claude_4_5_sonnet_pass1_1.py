```python
# This CRF document has multiple layout families (A-F) representing:
# - Family A: Table of contents (no fields to extract)
# - Families B-E: Standard form pages with a large blue title (sz~14.4, color #004c99)
#   followed by field labels (sz~7.8, black) with Yes/No options or other inputs
# - Family F: Complex table layouts with samples/timepoints and repeated rows
# Strategy: Extract the blue title as form_name, then capture field labels (black text
# at x~47.8 that is NOT a machine code in brackets, not an instruction/note, and not
# answer options). Use structural patterns to filter junk and handle multi-line wrapping.

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find the form title: large blue text (sz >= 13, color #004c99 or #1d60a4)
        # near top of page, typically at y < 150
        form_title = None
        for line in lines:
            if (line.size >= 13.0 and 
                line.non_black and 
                line.y0 < 200 and
                not line.text.startswith('[') and
                len(line.text.strip()) > 0):
                # Check if it's a section title pattern (not a TOC entry)
                if not re.match(r'^\d+\.\d+\.', line.text.strip()):
                    form_title = line.text.strip()
                    break
        
        if form_title:
            current_form = form_title
        
        # Skip TOC pages (family A) - they have many numbered entries with dots
        toc_pattern_count = sum(1 for l in lines if re.match(r'^\d+\.\d+\.', l.text.strip()))
        if toc_pattern_count > 5:
            continue
        
        # Extract field labels: small black text at left margin (x < 100)
        # Group lines by y-coordinate to handle multi-line labels
        field_candidates = []
        
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty, machine codes, and metadata
            if not text or text.startswith('[') or text.endswith(']'):
                continue
            
            # Field labels are typically:
            # - Small font (sz <= 10)
            # - Black text
            # - Left-aligned (x0 < 100)
            # - Not answer options (Yes/No at x > 400)
            if (line.size <= 10.5 and 
                not line.non_black and 
                line.x0 < 100 and
                line.y0 > 100):  # Below the title area
                
                # Filter out common junk patterns
                if re.match(r'^[(\d\)]+$', text):  # Pure numbers or (1), (2), etc.
                    continue
                if text in ['Yes', 'No', 'Scan', 'Collected', 'Not', 'Row', 'PK']:
                    continue
                if re.match(r'^Row \d+$', text):
                    continue
                if text.startswith('If Yes') or text.startswith('If not'):
                    continue
                if text.startswith('Please go to'):
                    continue
                if 'Add-On Forms' in text:
                    continue
                    
                # Skip pure technical annotations
                if re.match(r'^\([0-5]\)', text):  # Rating scale anchors
                    continue
                if text.startswith('TYPE:') or text.startswith('VISIBILITY:'):
                    continue
                
                # Skip table headers in specific positions
                if line.y0 < 400 and text in ['Sample', 'Timepoint', 'Status', 'Time of', 
                                               'Barcode', 'Backup', 'Collection', 'Number',
                                               'Test', 'Result', 'Date Dispensed', 'Dispensed']:
                    continue
                
                # Check if this is a continuation of the previous line (multi-line label)
                if (field_candidates and 
                    abs(line.y0 - field_candidates[-1]['y1']) < 15 and
                    abs(line.x0 - field_candidates[-1]['x0']) < 30):
                    # Append to previous field
                    field_candidates[-1]['text'] += ' ' + text
                    field_candidates[-1]['y1'] = line.y1
                else:
                    # New field
                    field_candidates.append({
                        'text': text,
                        'x0': line.x0,
                        'y0': line.y0,
                        'y1': line.y1,
                        'size': line.size,
                        'bold': line.bold
                    })
        
        # Post-process and filter field candidates
        for candidate in field_candidates:
            text = candidate['text'].strip()
            
            # Skip very short fragments (likely not real fields)
            if len(text) < 3:
                continue
            
            # Skip if it looks like a table column header pattern
            if text in ['Date of Collection', 'Date Dispensed', 'Bottle Number(s)',
                       'Number of', 'bottles Dispensed', 'Capsules Dispensed']:
                continue
            
            # Skip descriptions/instructions (typically longer and descriptive)
            if (text.startswith('Person has') or 
                text.startswith('When person') or
                text.startswith('Acts or preparation')):
                continue
            
            # Skip if it's just a unit or category label without a question
            if text in ['Appearance', 'Bilirubin', 'Color', 'Glucose', 'Ketones',
                       'Leucocytes', 'Nitrites', 'pH', 'Protein', 'Cotinine'] and candidate['y0'] < 400:
                # These might be column headers in a table, not field labels
                # Only skip if they appear in table context (near other similar short items)
                continue
            
            # Valid field - add to results
            if current_form or text:  # Only add if we have some context
                results.append({
                    "form_name": current_form,
                    "field_name": text,
                    "page": page_num
                })
    
    # Deduplicate consecutive identical entries (but keep legitimate repeats across pages)
    deduplicated = []
    prev = None
    for r in results:
        if prev != (r['form_name'], r['field_name'], r['page']):
            deduplicated.append(r)
            prev = (r['form_name'], r['field_name'], r['page'])
    
    return deduplicated
```
