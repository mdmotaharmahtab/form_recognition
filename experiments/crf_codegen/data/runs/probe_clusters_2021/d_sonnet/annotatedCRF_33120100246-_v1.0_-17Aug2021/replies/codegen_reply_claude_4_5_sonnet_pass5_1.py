```python
# This document is a clinical CRF with multiple layout families:
# - Family A: Table of contents with numbered section links
# - Families B, C: Continuation of table of contents 
# - Families D, E, F: Actual form pages with data-entry fields
# Family E/F pages have form titles in large blue font (~14pt #004c99) followed by field labels in black
# Field labels are followed by red technical codes in brackets (e.g., [VSSUVTIM]) - these are NOT field names
# Form titles appear to carry forward across multiple pages until a new title is encountered
# Strategy: Extract form title from the large blue text, then extract field labels (black text) while 
# skipping red bracketed codes, answer options, and read-only annotations

import re
from collections import namedtuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title - large blue text, typically 14+ point size
        for i, line in enumerate(lines):
            # Form titles are in blue (#004c99 or similar blue), size ~14pt, not bold
            if line.size >= 13.0 and line.non_black and not line.bold:
                # Check if this looks like a form title (not a technical code in brackets)
                text = line.text.strip()
                if text and not text.startswith('[') and not re.match(r'^\d+$', text):
                    # Avoid header/footer page numbers and other metadata
                    if not re.match(r'^(Pack Version|Annotated CRF|\d+\.?\d*|page \d+)', text, re.IGNORECASE):
                        current_form = text
                        break
        
        # Extract field labels - these are black text questions/labels
        # Skip: red text (technical codes), answer options, read-only markers, type specifications
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty lines
            if not text:
                i += 1
                continue
            
            # Skip red text (technical codes and type specifications)
            if line.non_black and '[' in text:
                i += 1
                continue
            
            # Skip lines that are just bracketed codes
            if re.match(r'^\[.*\]$', text):
                i += 1
                continue
            
            # Skip TYPE, VISIBILITY, Read-only markers
            if text.startswith('[TYPE:') or text.startswith('[VISIBILITY:') or '[Read-only field]' in text:
                i += 1
                continue
            
            # Skip answer options - these appear as standalone short options
            # Common patterns: Yes, No, Phone, Office Visit, etc.
            if line.size >= 8.5 and line.size <= 10.0 and text in ['Yes', 'No', 'Phone', 'Office Visit', 'Letter', 'Other']:
                i += 1
                continue
            
            # Skip enumeration value lists in parentheses
            if re.match(r'^\(\d+\)', text):
                i += 1
                continue
            
            # Skip row markers like "Row 1", "Row 2", etc.
            if re.match(r'^Row \d+$', text, re.IGNORECASE):
                i += 1
                continue
            
            # Skip repeatable row headers
            if '(Repeatable row added with Add Row button)' in text:
                i += 1
                continue
            
            # Skip conditional logic text (YES page enrols, etc.)
            if text.startswith('YES') or text.startswith('page enrols if'):
                i += 1
                continue
            
            # Skip section headers in blue that are structural markers (like "Standing", "Supine", etc.)
            # These are subsection markers, not field labels
            if line.non_black and line.bold and line.size >= 8.5 and line.size <= 10.0:
                i += 1
                continue
            
            # Look for field labels - black text, not bold usually, reasonable size
            # Field labels are typically questions or prompts
            if not line.non_black and line.size >= 7.0 and line.size <= 10.0:
                # Check if this looks like a field label (question or prompt)
                # Field labels often end with ? or are descriptive phrases
                
                # Skip table headers/column titles that appear on schedule pages
                if any(keyword in text for keyword in ['Visit Date', 'Control Period', 'Treatment Period', 
                                                       'Screening Period', 'Type of Contact', 'Method of Contact',
                                                       'Date of Contact']):
                    # These could be either headers or actual fields, need context
                    # If followed immediately by a red code, it's a field
                    if i + 1 < len(lines) and lines[i+1].non_black and '[' in lines[i+1].text:
                        # This is a field label
                        field_name = text
                        
                        # Check if next lines continue the label (multi-line wrapping)
                        j = i + 1
                        while j < len(lines):
                            next_line = lines[j]
                            next_text = next_line.text.strip()
                            
                            # Stop if we hit a red code
                            if next_line.non_black and '[' in next_text:
                                break
                            
                            # If it's continuation (similar x position, not too far down)
                            if (not next_line.non_black and 
                                abs(next_line.x0 - line.x0) < 20 and 
                                next_line.y0 - line.y0 < 30 and
                                next_line.size >= 7.0 and next_line.size <= 10.0 and
                                not next_text.startswith('[')):
                                field_name += ' ' + next_text
                                j += 1
                            else:
                                break
                        
                        if current_form and field_name:
                            results.append({
                                "form_name": current_form,
                                "field_name": field_name,
                                "page": page_num
                            })
                        i = j
                        continue
                
                # Regular field detection
                if text and not text.startswith('['):
                    # Look ahead to see if followed by a red technical code (confirms it's a field)
                    has_code = False
                    if i + 1 < len(lines):
                        next_line = lines[i+1]
                        if next_line.non_black and '[' in next_line.text:
                            has_code = True
                    
                    # Or if it's a question (ends with ?)
                    is_question = text.endswith('?')
                    
                    # Or if it contains field-like keywords
                    field_keywords = ['Date', 'Time', 'Number', 'Bottle', 'Total', 'Blood Pressure',
                                     'Heart Rate', 'Temperature', 'Were you', 'Has', 'Have you',
                                     'Did you', 'Was', 'If Yes', 'Specify', 'Describe', 'ICF']
                    has_keyword = any(keyword in text for keyword in field_keywords)
                    
                    if has_code or is_question or has_keyword:
                        field_name = text
                        
                        # Check for multi-line field labels
                        j = i + 1
                        while j < len(lines):
                            next_line = lines[j]
                            next_text = next_line.text.strip()
                            
                            # Stop if we hit a red code or answer option
                            if next_line.non_black:
                                break
                            if next_text in ['Yes', 'No', 'Phone', 'Office Visit', 'Letter', 'Other']:
                                break
                            
                            # Check if continuation line (similar position, close proximity)
                            if (abs(next_line.x0 - line.x0) < 20 and 
                                next_line.y0 - lines[j-1].y0 < 30 and
                                next_line.size >= 7.0 and next_line.size <= 10.0 and
                                not next_text.startswith('[') and
                                not next_text.startswith('Row ') and
                                next_text):
                                field_name += ' ' + next_text
                                j += 1
                            else:
                                break
                        
                        # Clean up the field name
                        field_name = ' '.join(field_name.split())
                        
                        # Skip if it's too short or looks like junk
                        if len(field_name) > 2 and current_form:
                            results.append({
                                "form_name": current_form,
                                "field_name": field_name,
                                "page": page_num
                            })
                        
                        i = j
                        continue
            
            i += 1
    
    return results
```
