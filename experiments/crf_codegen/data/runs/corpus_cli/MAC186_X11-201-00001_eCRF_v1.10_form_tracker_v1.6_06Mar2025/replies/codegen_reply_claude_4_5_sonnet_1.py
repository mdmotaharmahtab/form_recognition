```python
# This CRF has two main page types:
# 1. Form pages (families D,E,F,G,H): Large form title (sz~17.4) at y~74, bold
#    section label at y~48.5 (sz~7.8). Fields are bold labels with [N] codes.
# 2. Variable-detail pages (families C): "Variable details" table header at y~50,
#    with "Name" column containing field labels (sz~7.2, x~80.7).
# Family A is a cover page (Visit/Screening), Family B is a mixed form page.
# Strategy: Detect page type by structure, extract form_name from the large title
# or section label, then extract field labels from their respective positions.

import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Convert lines to Line objects if needed
        if lines and not isinstance(lines[0], Line):
            lines = [Line(text=ln.text, x0=ln.x0, y0=ln.y0, x1=ln.x1, y1=ln.y1,
                         size=ln.size, bold=ln.bold, non_black=ln.non_black) for ln in lines]
        
        if not lines:
            continue
        
        # Detect page type and extract
        if is_variable_details_page(lines):
            results.extend(extract_variable_details(lines, page_num))
        elif is_form_page(lines):
            results.extend(extract_form_page(lines, page_num))
    
    return results

def is_variable_details_page(lines):
    """Detect table pages with 'Variable details' header."""
    for line in lines[:10]:
        if line.y0 < 60 and 'Variable details' in line.text and line.bold:
            return True
    return False

def is_form_page(lines):
    """Detect form pages with large title or field structure."""
    # Look for large title text (sz > 15) in upper portion
    for line in lines[:15]:
        if line.y0 < 120 and line.size > 15:
            return True
    # Or bold labels with [N] pattern
    for line in lines[:30]:
        if line.bold and re.search(r'\[\d+\]', line.text):
            return True
    return False

def extract_variable_details(lines, page_num):
    """Extract from variable details table pages (family C)."""
    results = []
    form_name = ""
    
    # Find form name from section label near top (y < 50, sz~7.8, bold)
    for line in lines[:8]:
        if line.y0 < 50 and line.bold and line.size > 7 and line.size < 9:
            text = line.text.strip()
            # Skip document ID and generic headers
            if not re.match(r'^MAC186_', text) and text not in ['Variable details']:
                form_name = text
                break
    
    # Extract field names from "Name" column (x~80, sz~7.2, non-bold data rows)
    in_data = False
    for line in lines:
        # Start after header row (Name, Export Name, Type...)
        if line.y0 > 60 and 'Name' in line.text and line.bold:
            in_data = True
            continue
        
        if in_data and line.x0 > 70 and line.x0 < 120 and line.size < 8:
            text = line.text.strip()
            # Skip bracketed codes [N], Export Names (uppercase codes), and empty
            if text and not re.match(r'^\[\d+\]$', text) and not is_export_name(text):
                # Check if it's a field name (mixed case or readable text)
                if is_field_name(text):
                    results.append({
                        "form_name": form_name,
                        "field_name": text,
                        "page": page_num
                    })
    
    return results

def extract_form_page(lines, page_num):
    """Extract from form pages (families B,D,E,F,G,H)."""
    results = []
    form_name = ""
    
    # Find form name: large title (sz > 15, y~74) or section label (sz~7.8, y~48, bold)
    for line in lines[:15]:
        if line.y0 > 60 and line.y0 < 110 and line.size > 15:
            form_name = line.text.strip()
            break
        elif line.y0 > 45 and line.y0 < 55 and line.bold and line.size > 7 and line.size < 9:
            text = line.text.strip()
            if not re.match(r'^MAC186_', text):
                form_name = text
    
    # Extract field labels: bold text NOT followed by [N] on same line
    # Field labels have [N] codes on separate lines or adjacent
    field_labels = []
    for i, line in enumerate(lines):
        if line.y0 > 90 and line.bold:
            text = line.text.strip()
            
            # Skip if line contains [N] code itself
            if re.search(r'\[\d+\]', text):
                # Extract label before [N] if present
                match = re.match(r'^(.+?)\s*\[\d+\]', text)
                if match:
                    label = match.group(1).strip()
                    if is_field_label(label):
                        field_labels.append(label)
                continue
            
            # Check if this is a field label (not column header, not answer option)
            if is_field_label(text):
                # Verify [N] code exists nearby (next line or adjacent x position)
                if has_nearby_code(lines, i):
                    field_labels.append(text)
    
    # Deduplicate consecutive identical labels (wrapped text)
    prev_label = None
    for label in field_labels:
        if label != prev_label:
            results.append({
                "form_name": form_name,
                "field_name": label,
                "page": page_num
            })
            prev_label = label
    
    return results

def is_export_name(text):
    """Check if text looks like an export name (uppercase codes)."""
    # Export names are typically all-caps abbreviations
    if len(text) < 3:
        return False
    # All caps, may have numbers
    return text.isupper() and not ' ' in text

def is_field_name(text):
    """Check if text is a valid field name (not code, not junk)."""
    if len(text) < 2:
        return False
    # Skip pure codes, numbers, dates
    if re.match(r'^[A-Z0-9]+$', text):
        return False
    if re.match(r'^\d+$', text):
        return False
    if re.match(r'^\d{2}[A-Za-z]{3}\d{4}$', text):  # Date format
        return False
    # Skip column headers
    if text in ['Name', 'Export Name', 'Type', 'Max length', 'Categories', 'Variable details']:
        return False
    return True

def is_field_label(text):
    """Check if text is a field label (not header, not answer option)."""
    if len(text) < 3:
        return False
    
    # Skip document IDs
    if re.match(r'^MAC186_', text):
        return False
    
    # Skip generic table headers
    if text in ['Name', 'Export Name', 'Type', 'Max length', 'Categories', 
                'Variable details', 'Details', 'Position', 'Date', 'Time',
                'Test', 'Result', 'Interpretation', 'Parameter',
                'Not Done', 'Reason Not Done', 'Repeat', 'Eye', 'Timepoint',
                'Therapy', 'Indication', 'Start Date', 'End Date', 'Ongoing']:
        return False
    
    # Skip bare answer options (Yes/No without context)
    if text in ['Yes', 'No']:
        return False
    
    # Skip single letters/numbers
    if len(text) < 3:
        return False
    
    # Skip row numbers (just digits)
    if re.match(r'^\d+$', text):
        return False
    
    # Skip "More rows:" pattern
    if text.startswith('More rows:'):
        return False
    
    # Skip time point labels without question context
    if re.match(r'^\d+(\.\d+)?\s*(Hour|Hours|h)\s*(Post\s*Dose)?$', text, re.IGNORECASE):
        return False
    
    # Must have reasonable length
    if len(text) > 200:
        return False
    
    return True

def has_nearby_code(lines, idx):
    """Check if a [N] code exists near this line."""
    line = lines[idx]
    
    # Check next few lines (within 15 points vertically)
    for i in range(idx + 1, min(idx + 5, len(lines))):
        next_line = lines[i]
        if next_line.y0 - line.y0 > 15:
            break
        if re.search(r'\[\d+\]', next_line.text):
            return True
    
    # Check same line area (adjacent x, similar y)
    for other in lines:
        if abs(other.y0 - line.y0) < 5 and other.x0 > line.x1:
            if re.search(r'\[\d+\]', other.text):
                return True
    
    return False
```
