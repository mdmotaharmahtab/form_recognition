```python
"""
This CRF document has multiple layout patterns:
1. Table of contents pages (pages 1-2) with section listings
2. Inclusion/exclusion criteria pages with numbered criteria and Met/Not Met checkboxes
3. Sample collection tables with columns for sample info, timepoints, status, etc.
4. Assessment forms with field labels followed by technical codes in brackets
5. Vital signs and other measurement forms with timepoint selections

Strategy: Identify form names from large colored headers (sz>=15, colored text).
Extract field labels as black text questions/prompts, excluding technical codes
in brackets (e.g., [IEORRES], [TYPE:...]), answer options, and page furniture.
Use font size, color, and position to distinguish field labels from metadata.
"""

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    seen_fields = set()  # Track (form, field, page) to avoid duplicates
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip table of contents pages (pages 1-2 based on sample)
        if page_num <= 2:
            continue
        
        # Find form name: large colored headers (size >= 15, colored, not black)
        for line in lines:
            if line.size >= 15.0 and line.non_black and not line.text.startswith('['):
                # Clean up form name
                form_text = line.text.strip()
                # Skip if it looks like a section number (e.g., "3.1. Visit Date")
                if not re.match(r'^\d+\.', form_text):
                    current_form = form_text
                    break
        
        # Extract field labels
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty lines, page numbers, technical codes
            if not text:
                continue
            if re.match(r'^Page \d+ of \d+$', text):
                continue
            if text.startswith('[') and text.endswith(']'):
                continue
            if re.match(r'^\[.*\]$', text):
                continue
            
            # Skip table headers and common column labels
            if text in ['Criteria', 'Met/Not Met', 'Sample', 'Timepoint', 'Sample Status',
                       'Time of Collection', 'Barcode Number', 'Test', 'Result', 'Status',
                       'Reason not done', 'Date of Collection', 'Scan', 'Suicidal Ideation',
                       'Since Last Visit']:
                continue
            
            # Skip answer options (Yes/No/Met/Not Met/etc.)
            if text in ['Yes', 'No', 'Met', 'Not Met', 'Positive', 'Negative', 'Not Done',
                       'Collected', 'Not Collected', 'Not Applicable', 'N/A', 'Predose',
                       '1h postdose', '1.5h postdose', '2h postdose', '2.5h postdose',
                       '3h postdose', '4h postdose', '6h postdose', '8h postdose']:
                continue
            
            # Skip row labels
            if re.match(r'^Row \d+$', text):
                continue
            
            # Skip technical annotations (gray text or red text with TYPE/VISIBILITY/etc.)
            if line.non_black and ('[' in text or 'TYPE:' in text or 'VISIBILITY:' in text):
                continue
            
            # Skip scanner/barcode placeholders
            if text in ['Scan']:
                continue
            
            # Field labels are typically:
            # - Black text (not colored)
            # - Size 9-10.5 typically
            # - Not starting with backslash-number (criteria numbering)
            # - Actual questions or prompts
            
            is_field = False
            
            # Pattern 1: Questions ending with "?"
            if text.endswith('?') and not line.non_black and line.size <= 11:
                is_field = True
            
            # Pattern 2: Field prompts (not bold, black, reasonable size)
            # Exclude criteria text (starts with \d+\.)
            if (not line.non_black and 
                line.size >= 8.5 and line.size <= 11 and
                not re.match(r'^\\?\d+\\.', text) and
                not line.bold and
                len(text) > 10 and
                not text.startswith('If ') and
                'describe' not in text.lower()):
                
                # Check if it looks like a field label
                if any(keyword in text for keyword in ['Time of', 'Date of', 'Collection Date',
                                                        'Were ', 'reason:', 'Planned Timepoint',
                                                        'subject ']):
                    is_field = True
            
            # Pattern 3: Specific field patterns
            if (not line.non_black and line.size >= 8.5 and line.size <= 11):
                # Time/date fields
                if re.match(r'^(Time|Date) (of|subject)', text):
                    is_field = True
                # Collection/measurement prompts
                if re.match(r'^(Were |If not |Collection |Planned )', text):
                    is_field = True
            
            # Pattern 4: Criteria text (numbered exclusion/inclusion criteria)
            # These are field labels in this CRF
            if (not line.non_black and 
                re.match(r'^\\?\d+\\.', text) and
                line.size >= 8.5 and line.size <= 10):
                # This is a criteria item - it's a field
                # Clean up the text
                clean_text = re.sub(r'^\\?\d+\\.\\?\s*', '', text)
                if len(clean_text) > 20:  # Substantial criteria text
                    is_field = True
                    text = clean_text
            
            if is_field:
                # Clean up field name
                field_name = text.strip()
                
                # Skip if it's just a description prompt
                if field_name.startswith('If Yes, describe'):
                    continue
                
                # Create record
                key = (current_form, field_name, page_num)
                if key not in seen_fields:
                    seen_fields.add(key)
                    results.append({
                        "form_name": current_form,
                        "field_name": field_name,
                        "page": page_num
                    })
    
    return results
```