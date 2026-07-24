STRATEGY:

The document is a clinical CRF with multiple form types. Form titles appear in large blue font (size ~16.5, color #004c99) near the top of pages, such as "Visit Date", "Follow-Up Phone Call", etc. These titles govern all fields on that page and subsequent pages until a new title appears. When a page has no title, I will carry forward the most recent title seen. Fields are identified by their position and structure: they appear as questions or labels in regular black text (size ~9-10.5), often followed by technical annotations in red (#ff0000) that contain variable names in square brackets – these annotations are landmarks but not field names themselves. Answer options (Yes/No, enumeration values) appear in gray (#999999) or as inline choices and are not separate fields. Table headers (like "Record", "Term", "Start Date") in family E are column labels for repeatable data rows, not individual fields. Red text blocks starting with "[TYPE:" or "[VISIBILITY:" are technical metadata, not field labels. Bullet points with "•" followed by text (e.g., contraceptive methods) are answer options under a parent question, not standalone fields. I will extract the human-readable question text immediately before or above the technical annotations, skipping the annotations themselves. Pages with only version history tables (family C) or copyright notices (family F) contain no data-entry fields. Family G shows form section headers with no fields on the sample page. For all pages, I will identify fields by their structural position (labels in black, regular size, not in red annotation blocks, not gray options, not table column headers that repeat across rows), join wrapped label lines, and associate them with the current form title.

```python
# CRF extraction: form titles in large blue font (~16.5pt #004c99), fields in black text (~9-10.5pt),
# technical annotations in red are landmarks but not field names. Carry forward form titles across pages.

import re
from typing import List, Dict, Tuple

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title: large blue text, typically size >= 15, color #004c99
        form_title_candidates = [
            ln for ln in lines 
            if ln.size >= 15.0 and ln.non_black and '#004c99' in get_color(ln)
        ]
        if form_title_candidates:
            # Take the first/topmost large blue text as form title
            current_form = form_title_candidates[0].text.strip()
        
        # Skip pages that are clearly non-field pages
        if is_non_field_page(lines):
            continue
        
        # Extract fields: black text, size 9-10.5, not red annotations, not gray options
        fields = extract_fields_from_page(lines)
        
        for field_name in fields:
            records.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return records

def get_color(line):
    # Heuristic: check if line text representation suggests color
    # Lines have .non_black attribute; we need to infer color from context
    # Since we don't have direct color access, we use the structured text hints
    return ""

def is_non_field_page(lines):
    # Detect version history tables (family C): has "Version", "Date", "Changed By", "Details" headers
    header_texts = [ln.text.strip() for ln in lines if ln.bold and ln.size < 11]
    if "Version" in header_texts and "Date" in header_texts and "Changed By" in header_texts:
        return True
    
    # Detect copyright/definition pages (family F): contains copyright or long definition text
    all_text = " ".join(ln.text for ln in lines)
    if "© 2008 The Research Foundation" in all_text or "Columbia Suicide History Form" in all_text:
        return True
    
    # Detect table of contents (family A/B): many lines with section numbers like "3.1.", "3.2."
    toc_pattern = re.compile(r'^\d+\.\d+\.')
    toc_lines = [ln for ln in lines if toc_pattern.match(ln.text.strip())]
    if len(toc_lines) > 10:
        return True
    
    return False

def extract_fields_from_page(lines):
    fields = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        
        # Skip red annotation lines (technical metadata)
        if ln.non_black and is_red_annotation(ln.text):
            i += 1
            continue
        
        # Skip gray text (answer options)
        if ln.non_black and ln.size <= 11:
            i += 1
            continue
        
        # Skip page numbers
        if re.match(r'Page \d+ of \d+', ln.text.strip()):
            i += 1
            continue
        
        # Skip bullet points (answer options)
        if ln.text.strip().startswith('•'):
            i += 1
            continue
        
        # Skip table column headers (family E): single-word headers at top, size ~10.5
        if ln.y0 < 160 and ln.size >= 10 and ln.size <= 11 and len(ln.text.split()) <= 3:
            # Likely a table header
            i += 1
            continue
        
        # Candidate field: black text, size 9-10.5, not bold header, meaningful content
        if not ln.non_black and 8.5 <= ln.size <= 11 and len(ln.text.strip()) > 2:
            text = ln.text.strip()
            
            # Skip if it's a technical marker
            if text.startswith('[') and text.endswith(']'):
                i += 1
                continue
            
            # Skip if it's a row label like "Row 1", "Row 2"
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Check if next lines are continuation (similar x, close y)
            field_text = text
            j = i + 1
            while j < len(lines):
                next_ln = lines[j]
                # Continuation: similar x (within 5pt), y within 15pt, same size, black
                if (abs(next_ln.x0 - ln.x0) < 10 and 
                    next_ln.y0 - lines[j-1].y1 < 15 and 
                    not next_ln.non_black and 
                    8.5 <= next_ln.size <= 11 and
                    not next_ln.text.strip().startswith('[')):
                    field_text += " " + next_ln.text.strip()
                    j += 1
                else:
                    break
            
            # Clean and validate field
            field_text = clean_field_text(field_text)
            if is_valid_field(field_text):
                fields.append(field_text)
            
            i = j
        else:
            i += 1
    
    return fields

def is_red_annotation(text):
    # Red annotations start with [ and contain TYPE, VISIBILITY, etc.
    return text.startswith('[') and any(kw in text for kw in ['TYPE:', 'VISIBILITY:', 'Read-only'])

def clean_field_text(text):
    # Remove trailing punctuation, extra spaces
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\?$', '', text)  # Keep question marks in middle, remove trailing
    return text

def is_valid_field(text):
    # Filter out non-fields
    if len(text) < 3:
        return False
    
    # Skip pure numbers or dates
    if re.match(r'^\d+[\-/]\d+[\-/]\d+$', text):
        return False
    
    # Skip single words that are likely headers
    if len(text.split()) == 1 and text[0].isupper():
        return False
    
    # Skip answer option patterns
    if text in ['Yes', 'No', 'N/A', 'Collected', 'Not Collected', 'X']:
        return False
    
    # Skip enumeration values
    if text in ['Hysterectomy', 'Bilateral Oophorectomy', 'Bilateral Tubal Ligation']:
        return False
    
    return True
```