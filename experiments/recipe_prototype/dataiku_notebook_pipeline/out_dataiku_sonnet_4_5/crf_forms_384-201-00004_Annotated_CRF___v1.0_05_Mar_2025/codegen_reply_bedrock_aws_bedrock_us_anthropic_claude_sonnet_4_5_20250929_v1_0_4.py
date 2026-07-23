```python
import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    seen_fields = set()  # Track (form, field) to avoid duplicates
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip cover pages
        if page_num <= 3:
            continue
        
        # Detect form name: white text (#ffffff) at sz=12 near top of page
        for line in lines:
            if line.size >= 11.5 and line.size <= 13 and '#ffffff' in str(line.non_black or ''):
                text = line.text.strip()
                # Skip technical metadata lines
                if text and not text.startswith('Origin:') and not text.startswith('Aliases:'):
                    # This is a form name
                    current_form = text
                    break
        
        # Skip code list pages (have "Coded" and "Decode" headers)
        has_coded_decode = False
        for line in lines:
            if line.text.strip() in ['Coded', 'Decode'] and line.bold:
                has_coded_decode = True
                break
        if has_coded_decode:
            continue
        
        # Skip if no form name yet
        if not current_form:
            continue
        
        # Extract fields from left column
        # Strategy: Look for descriptive text at x~46.5, sz~7.5, black text
        # that appears BEFORE technical metadata or checkbox options
        
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty or very short lines
            if not text or len(text) < 3:
                continue
            
            # Skip lines in right column (technical metadata at x>400)
            if line.x0 > 400:
                continue
            
            # Skip technical metadata patterns (even in left column)
            if any(pattern in text for pattern in [
                'Code List:', 'Format:', 'Data Type:', 'Origin:', 'Mandatory?:',
                'Disallow Future Date:', 'Description:', 'Aliases:', 'Odm OID',
                'SAS Field Name:', 'Conditional Item:', 'Visible If Value:',
                'Role Restriction:', 'Repeating:', 'Domain:', 'Default Item Value:',
                'Conditionally Visible', 'Study Event:', 'Timepoint:', 'Requires Role:',
                'Value Calculated', 'Device Parameter:', 'SDS Var Name:', 'Range (soft):',
                'Range (hard):', 'Units:', 'Short Name', 'Value Calculated via Method:'
            ]):
                continue
            
            # Skip lines that are field codes in brackets like [EG_REPEAT_Q] or [SAS Field Name: ...]
            if re.match(r'^\[[\w_\s\-:]+\]$', text):
                continue
            
            # Skip lines that are just date/time formats
            if re.match(r'^dd-MMM-yyyy', text):
                continue
            
            # Skip page numbers and document IDs
            if re.match(r'^\d+$', text) or text.startswith('384-201-'):
                continue
            
            # Skip checkbox options (lines starting with "O " at x>200)
            if text.startswith('O ') and line.x0 > 200:
                continue
            
            # Skip lines that are just input box patterns
            if re.match(r'^\[_\|_', text):
                continue
            
            # Skip colored header lines (section headers, not fields)
            if '#31708f' in str(line.non_black or '') or '#666677' in str(line.non_black or ''):
                continue
            
            # Skip gray text (often technical annotations)
            if '#808080' in str(line.non_black or ''):
                continue
            
            # Skip single character lines or just punctuation
            if len(text) <= 2 or text in ['?', '-', '|']:
                continue
            
            # Identify field labels:
            # Pattern 1: Field labels at x~46.5, sz~7.5, black text
            # These are the main data entry field labels
            is_field = False
            field_text = text
            
            # Main pattern: x between 44-50, size 7-8, black text
            if 44 <= line.x0 <= 50 and 7.0 <= line.size <= 8.5:
                # Must be black text (no color)
                if line.non_black is None or line.non_black == '':
                    # Must contain actual words (not just codes)
                    if re.search(r'[a-zA-Z]{3,}', text):
                        # Not starting with technical prefixes
                        if not text.startswith('[') and not text.startswith('?'):
                            # Should be descriptive - multiple words or substantive single phrase
                            # Exclude very short single words
                            words = text.split()
                            if len(words) >= 2 or len(text) > 10:
                                # Additional check: not just abbreviations like "PR"
                                if not (len(words) == 1 and len(text) <= 3 and text.isupper()):
                                    is_field = True
                                    field_text = text
            
            if is_field and current_form:
                # Clean up field text
                field_text = field_text.strip()
                # Remove trailing colons
                field_text = re.sub(r':$', '', field_text)
                # Remove trailing question marks
                if field_text.endswith('?'):
                    field_text = field_text[:-1].strip()
                
                # Final validation: must be substantive
                if len(field_text) >= 5 and re.search(r'[a-zA-Z]{3,}', field_text):
                    # Avoid duplicates
                    key = (current_form, field_text)
                    if key not in seen_fields:
                        seen_fields.add(key)
                        results.append({
                            "form_name": current_form,
                            "field_name": field_text,
                            "page": page_num
                        })
    
    return results
```