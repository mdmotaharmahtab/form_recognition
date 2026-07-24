```python
import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    seen_fields = set()  # Track (form, field) to avoid duplicates within same page
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        seen_fields.clear()
        
        # First pass: identify form name on this page
        for i, line in enumerate(lines):
            # Form headers: large blue text (size ~14-15, color #004c99)
            if line.size >= 13.0 and line.size <= 16.0 and line.non_black:
                # Check if it's a form header (not a sub-section marker)
                text = line.text.strip()
                # Skip numbered list items from TOC
                if not re.match(r'^\d+\.', text):
                    current_form = text
        
        # Second pass: extract field labels
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty lines
            if not text:
                i += 1
                continue
            
            # Skip red technical annotations
            if line.non_black and '[' in text:
                i += 1
                continue
            
            # Skip answer options (gray text with common option values)
            # These are typically small gray text that are radio/checkbox options
            answer_options = [
                'Yes', 'No', 'N/A', 'NA', 'Not Done', 
                'Positive', 'Negative', 'Collected', 
                'Not Collected', 'Not Applicable', 'Scan',
                'Skip to next visit', 'Skip to ET visit',
                'Urine', 'Serum', 'Applicable',
                'Amphetamines', 'Barbiturates', 'Benzodiazepines',
                'Cannabinoids', 'Cocaine', 'Opiates', 'Phencyclidine',
                'Methadone', 'Tricyclic Antidepressants',
                'Hematology', 'Chemistry', 'Urinalysis',
                'on', 'off'
            ]
            
            # Only skip answer options if they're small gray text (size < 8.5)
            if line.non_black and text in answer_options and line.size < 8.5:
                i += 1
                continue
            
            # Skip if text contains "(values:" or "(+1 more)" - these are value hints
            if '(values:' in text or '(+1 more)' in text or 'hour, minutes)' in text:
                i += 1
                continue
            
            # Skip page numbers, headers, footers
            if re.match(r'^\d+$', text):
                i += 1
                continue
            
            # Skip section markers and instructions
            if text.startswith('Row ') or text.startswith('Version Number'):
                i += 1
                continue
            
            # Skip long instructional text
            if len(text) > 150:
                i += 1
                continue
            
            # Potential field label: black or gray text, reasonable size
            # Accept both black and non-black (gray) text as potential field labels
            if line.size >= 7.0 and line.size <= 10.0:
                # Look ahead to see if next line(s) contain red technical marker
                has_marker = False
                for j in range(i+1, min(i+5, len(lines))):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Found a technical marker in red with brackets
                    if next_line.non_black and '[' in next_text and ']' in next_text:
                        # Extract field code to check if it's a field marker
                        match = re.search(r'\[([A-Z0-9_]+)\]', next_text)
                        if match:
                            code = match.group(1)
                            # Valid field codes (not metadata like TYPE, VISIBILITY, Read-only)
                            if code not in ['TYPE', 'VISIBILITY', 'Read-only field']:
                                has_marker = True
                                break
                
                if has_marker:
                    # Clean up the field label
                    field_label = text
                    
                    # Skip if it's just a value or date
                    if re.match(r'^[\d\-/]+$', field_label):
                        i += 1
                        continue
                    
                    # Skip if it looks like a code
                    if re.match(r'^\[.*\]$', field_label):
                        i += 1
                        continue
                    
                    # Skip common non-field text
                    skip_patterns = [
                        r'^As per protocol$',
                        r'^Adverse Event$',
                        r'^Dosing error$',
                        r'^Dispensing error$',
                        r'^Technical problems$',
                        r'^Physician decision$',
                        r'^Subject/guardian decision$',
                        r'^\d+\.\d+\.',  # TOC entries
                    ]
                    
                    should_skip = False
                    for pattern in skip_patterns:
                        if re.match(pattern, field_label, re.IGNORECASE):
                            should_skip = True
                            break
                    
                    if should_skip:
                        i += 1
                        continue
                    
                    # Valid field - add to results if not duplicate
                    key = (current_form, field_label)
                    if key not in seen_fields:
                        results.append({
                            "form_name": current_form,
                            "field_name": field_label,
                            "page": page_num
                        })
                        seen_fields.add(key)
                else:
                    # No marker found - check if this is a table header that should be extracted
                    # Table headers in gray that are actual field labels (not generic column headers)
                    # These appear in structured tables without immediate red markers
                    
                    # Check if this could be a table column header that's a field
                    table_field_candidates = [
                        'Sample', 'Status', 'Reason not done', 'Date of Collection',
                        'Time of Collection', 'Barcode Number', 'Test', 'Result',
                        'Reason', 'Scan'
                    ]
                    
                    # For table headers, check if they appear in a table context
                    # Look for nearby similar-sized text that suggests a table structure
                    if text in table_field_candidates:
                        # Check if there are other lines at similar y-coordinate (table row)
                        is_table_header = False
                        for j in range(max(0, i-3), min(i+3, len(lines))):
                            if j != i:
                                other_line = lines[j]
                                # Similar y-coordinate and size suggests table structure
                                if abs(other_line.y0 - line.y0) < 2 and abs(other_line.size - line.size) < 1:
                                    is_table_header = True
                                    break
                        
                        if is_table_header:
                            key = (current_form, text)
                            if key not in seen_fields:
                                results.append({
                                    "form_name": current_form,
                                    "field_name": text,
                                    "page": page_num
                                })
                                seen_fields.add(key)
                    
                    # Also check for fields ending with "(optional)" - these are still fields
                    if text.endswith('(optional)'):
                        # Remove the (optional) suffix for the field name
                        field_label = text.replace('(optional)', '').strip()
                        key = (current_form, field_label)
                        if key not in seen_fields:
                            results.append({
                                "form_name": current_form,
                                "field_name": field_label,
                                "page": page_num
                            })
                            seen_fields.add(key)
            
            i += 1
    
    return results
```