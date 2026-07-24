```python
# This CRF document has several layout families:
# - Family A: Table of contents (page 1)
# - Family B: Continuation of TOC (pages 2+)
# - Family C: Standard form pages with a blue form title at top, followed by field labels and technical annotations
# - Family D: Similar to C but with enumeration lists (dropdowns)
# - Family E: Table-based forms (C-SSRS) with columns for Lifetime/Past 6 Month
# Strategy: Extract form_name from large blue text (sz~16.5, color #004c99), field_name from black text
# that is NOT technical annotations (red text, bracketed codes, TYPE/VISIBILITY lines).

import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip TOC pages (families A and B) - they have numbered section lists, not data fields
        # TOC pages have many lines with pattern "3.XX. Title" in blue
        toc_pattern_count = sum(1 for line in lines if re.match(r'^\d+\.\d+\.', line.text.strip()) and line.non_black)
        if toc_pattern_count > 5:
            continue
        
        # Extract form name: large blue text (size ~16-17, color #004c99)
        for line in lines:
            if line.size >= 15.0 and line.non_black and '#004c99' in str(line.__dict__):
                # This is a form title
                text = line.text.strip()
                if text and not text.startswith('[') and not re.match(r'^\d+\.\d+\.', text):
                    current_form = text
                    break
        
        # Extract field names
        # Field names are black text, size ~9, NOT:
        # - Red text (technical annotations)
        # - Lines starting with '[' (machine codes)
        # - Lines containing 'TYPE:', 'VISIBILITY:', 'Read-only'
        # - Page numbers
        # - Answer options (Yes/No/NA etc. in gray #999999)
        # - Table headers that repeat (Sample, Timepoint, etc.)
        
        field_candidates = []
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip if empty
            if not text:
                i += 1
                continue
            
            # Skip red text (technical annotations)
            if line.non_black and '#ff0000' in str(line.__dict__):
                i += 1
                continue
            
            # Skip gray text (answer options)
            if line.non_black and '#999999' in str(line.__dict__):
                i += 1
                continue
            
            # Skip bracketed codes
            if text.startswith('['):
                i += 1
                continue
            
            # Skip technical keywords
            if any(kw in text for kw in ['[TYPE:', '[VISIBILITY:', 'Read-only', '[Read-only']):
                i += 1
                continue
            
            # Skip page numbers
            if re.match(r'^Page \d+ of \d+$', text):
                i += 1
                continue
            
            # Skip common table headers (structural, not fields)
            if text in ['Sample', 'Timepoint', 'Sample Status', 'Time of', 'Collection', 
                       'Barcode', 'Number', 'Backup', 'Lifetime', 'Past 6 Month',
                       'Suicidal Behaviour']:
                i += 1
                continue
            
            # Skip row labels like "Row 1", "Row 2" etc.
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip bold section headers that are just labels (like "Not of Childbearing Potential")
            # but only if they're very short and followed by actual questions
            # Actually, these ARE field groupings, but we need the actual questions
            
            # Check if this is a potential field label
            # Field labels are typically black, size 9, and are questions or statements
            if not line.non_black and line.size >= 8.0 and line.size <= 11.0:
                # Check if it's a substantive question/label
                # Skip very short text unless it's clearly a field
                if len(text) < 10 and not text.endswith('?'):
                    # Could be a fragment, check if it continues
                    pass
                
                # Collect this line and check for continuations
                field_text = text
                j = i + 1
                
                # Look ahead for continuation lines (same x position, similar size, black)
                while j < len(lines):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Stop if we hit a red line (technical annotation)
                    if next_line.non_black and '#ff0000' in str(next_line.__dict__):
                        break
                    
                    # Stop if we hit a bracketed code
                    if next_text.startswith('['):
                        break
                    
                    # Stop if y-distance is too large (new section)
                    if next_line.y0 - line.y0 > 50:
                        break
                    
                    # Check if this is a continuation (similar x, similar size, black)
                    if (not next_line.non_black and 
                        abs(next_line.x0 - line.x0) < 20 and 
                        abs(next_line.size - line.size) < 2 and
                        len(next_text) > 0 and
                        not next_text.startswith('[')):
                        field_text += ' ' + next_text
                        j += 1
                    else:
                        break
                
                # Clean up the field text
                field_text = ' '.join(field_text.split())
                
                # Filter out non-fields
                # Skip if it's just a bullet point
                if field_text == '•':
                    i = j
                    continue
                
                # Skip if it's a definition or instruction (starts with certain patterns)
                if field_text.startswith('**') or field_text.startswith('Definitions of'):
                    i = j
                    continue
                
                # Skip copyright notices
                if '©' in field_text or 'copyright' in field_text.lower():
                    i = j
                    continue
                
                # Skip if it's just a list item without a question
                if field_text in ['Vasectomy', 'Abstinence', 'Albumin', 'Alkaline phosphatase',
                                 'ALT', 'AST', 'Calcium', 'Hematocrit', 'Hemoglobin']:
                    i = j
                    continue
                
                # Accept if it's a question or substantive label
                if (len(field_text) >= 10 or field_text.endswith('?') or 
                    'Date' in field_text or 'Time' in field_text or 'Number' in field_text):
                    
                    # Additional filter: skip if it looks like an answer option
                    if not field_text in ['Yes', 'No', 'NA', 'N/A', 'Predose', 'Collected', 
                                         'Not Collected', 'As per protocol', 'Adverse Event']:
                        results.append({
                            'form_name': current_form,
                            'field_name': field_text,
                            'page': page_num
                        })
                
                i = j
            else:
                i += 1
    
    return results
```