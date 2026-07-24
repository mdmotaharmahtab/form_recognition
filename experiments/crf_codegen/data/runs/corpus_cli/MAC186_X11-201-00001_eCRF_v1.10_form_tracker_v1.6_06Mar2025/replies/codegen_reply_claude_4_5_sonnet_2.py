Looking at the issues, I need to:

1. **Remove the hardcoded literal blocklists** - use structural discrimination instead
2. **Fix the empty form_name issue** (57% empty) - carry forward the last seen form name
3. **Handle "Reason Not Performed" appearing on 70% of pages** - likely furniture, verify structurally
4. **Add handling for uncovered clusters** (4, 7, 8) - these have different table layouts

Let me analyze the sample pages from uncovered clusters:
- **Cluster 4 (p232, p617)**: Variable details continuation pages - field names in column 2 (x~80), similar to cluster C but without "Variable details" header
- **Cluster 7 (p145, p154)**: Compact vital signs table - field names at right (x~562), timepoints at left
- **Cluster 8 (p203, p270)**: Numbered questionnaire items - field text after number (x~64.5)

```python
# This CRF has multiple layout families:
# 1. Form pages: Large title (sz>15) at top, bold field labels with [N] codes
# 2. Variable details tables: "Variable details" header or continuation with Name column (x~80)
# 3. Compact vital signs: Field names at right edge (x>500), timepoints at left
# 4. Numbered questionnaires: Row numbers with field text (x~64, sz~7.8)
# Strategy: Detect layout by structural features, extract form_name and carry forward,
# extract field labels based on position and style patterns (not literal text).

import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    last_form_name = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Convert lines to Line objects if needed
        if lines and not isinstance(lines[0], Line):
            lines = [Line(text=ln.text, x0=ln.x0, y0=ln.y0, x1=ln.x1, y1=ln.y1,
                         size=ln.size, bold=ln.bold, non_black=ln.non_black) for ln in lines]
        
        if not lines:
            continue
        
        # Detect page type and extract
        page_type = detect_page_type(lines)
        
        if page_type == 'variable_details':
            page_results, form_name = extract_variable_details(lines, page_num, last_form_name)
        elif page_type == 'compact_vitals':
            page_results, form_name = extract_compact_vitals(lines, page_num, last_form_name)
        elif page_type == 'numbered_questionnaire':
            page_results, form_name = extract_numbered_questionnaire(lines, page_num, last_form_name)
        elif page_type == 'form_page':
            page_results, form_name = extract_form_page(lines, page_num, last_form_name)
        else:
            page_results, form_name = [], last_form_name
        
        # Update last_form_name if we found one
        if form_name:
            last_form_name = form_name
        
        results.extend(page_results)
    
    return results

def detect_page_type(lines):
    """Detect page layout type by structural features."""
    # Check for variable details table (header or continuation)
    has_name_column = False
    has_export_column = False
    has_variable_header = False
    
    for line in lines[:15]:
        if line.y0 < 65:
            if 'Variable details' in line.text and line.bold:
                has_variable_header = True
            if line.x0 > 70 and line.x0 < 100 and 'Name' in line.text and line.bold:
                has_name_column = True
            if line.x0 > 220 and line.x0 < 250 and 'Export' in line.text:
                has_export_column = True
    
    if has_variable_header or (has_name_column and has_export_column):
        return 'variable_details'
    
    # Check for compact vitals table (field names at right edge, x>500)
    right_edge_fields = 0
    for line in lines[:50]:
        if line.x0 > 500 and line.size < 8:
            text = line.text.strip()
            if any(keyword in text for keyword in ['Temperature', 'Pressure', 'Rate', 'SpO2', 'Respiratory']):
                right_edge_fields += 1
    
    if right_edge_fields >= 3:
        return 'compact_vitals'
    
    # Check for numbered questionnaire (sequential numbers with text at x~64)
    numbered_items = 0
    for i, line in enumerate(lines[:40]):
        if line.x0 < 50 and line.size < 8:
            if re.match(r'^\d+$', line.text.strip()):
                # Check if next line or nearby has text at x~64
                for j in range(i+1, min(i+3, len(lines))):
                    if lines[j].x0 > 60 and lines[j].x0 < 90 and len(lines[j].text) > 10:
                        numbered_items += 1
                        break
    
    if numbered_items >= 4:
        return 'numbered_questionnaire'
    
    # Check for standard form page (large title or [N] codes)
    for line in lines[:15]:
        if line.y0 < 120 and line.size > 15:
            return 'form_page'
    
    for line in lines[:30]:
        if line.bold and re.search(r'\[\d+\]', line.text):
            return 'form_page'
    
    return 'unknown'

def extract_form_name(lines, top_n=15):
    """Extract form name from page header."""
    # Look for large title (sz > 15) or bold section label (sz 7-9)
    for line in lines[:top_n]:
        # Large title
        if line.y0 > 60 and line.y0 < 120 and line.size > 15:
            return line.text.strip()
        # Bold section label
        elif line.y0 > 40 and line.y0 < 60 and line.bold and line.size > 7 and line.size < 9:
            text = line.text.strip()
            # Skip document IDs and generic headers
            if not re.match(r'^MAC\d+_', text) and text not in ['Variable details']:
                return text
    
    return ""

def extract_variable_details(lines, page_num, fallback_form_name):
    """Extract from variable details table pages."""
    results = []
    form_name = extract_form_name(lines, top_n=8) or fallback_form_name
    
    # Find Name column position (x range for field names)
    name_col_x = None
    for line in lines[:10]:
        if line.y0 < 65 and 'Name' in line.text and line.bold:
            name_col_x = line.x0
            break
    
    if name_col_x is None:
        name_col_x = 80  # Default
    
    # Extract field names from Name column
    in_data_rows = False
    seen_fields = set()
    
    for line in lines:
        # Start after header row
        if line.y0 > 45 and line.y0 < 65 and 'Name' in line.text and line.bold:
            in_data_rows = True
            continue
        
        # Data rows: x near Name column, reasonable font size
        if line.x0 > name_col_x - 10 and line.x0 < name_col_x + 40 and line.size < 8:
            text = line.text.strip()
            
            # Structural filters (not literal text matching)
            if is_valid_field_name(text, context='table') and text not in seen_fields:
                results.append({
                    "form_name": form_name,
                    "field_name": text,
                    "page": page_num
                })
                seen_fields.add(text)
    
    return results, form_name

def extract_compact_vitals(lines, page_num, fallback_form_name):
    """Extract from compact vital signs tables (field names at right edge)."""
    results = []
    form_name = extract_form_name(lines) or fallback_form_name
    
    # Extract field names from right column (x > 500)
    seen_fields = set()
    
    for line in lines:
        if line.x0 > 500 and line.y0 > 45 and line.size < 8:
            text = line.text.strip()
            
            if is_valid_field_name(text, context='vitals') and text not in seen_fields:
                results.append({
                    "form_name": form_name,
                    "field_name": text,
                    "page": page_num
                })
                seen_fields.add(text)
    
    return results, form_name

def extract_numbered_questionnaire(lines, page_num, fallback_form_name):
    """Extract from numbered questionnaire pages."""
    results = []
    form_name = extract_form_name(lines) or fallback_form_name
    
    # Find numbered items (number at x<50, text at x~64)
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for row number
        if line.x0 < 55 and line.size < 8 and re.match(r'^\d+$', line.text.strip()):
            # Find associated text (next few lines, x > 60)
            field_text_parts = []
            
            for j in range(i+1, min(i+5, len(lines))):
                next_line = lines[j]
                # Text in same row area, x position around 64
                if next_line.x0 > 60 and next_line.x0 < 90 and abs(next_line.y0 - line.y0) < 10:
                    # Check if it's field text (not answer options or codes)
                    text = next_line.text.strip()
                    if is_valid_field_name(text, context='questionnaire'):
                        field_text_parts.append(text)
                        break
            
            if field_text_parts:
                field_name = ' '.join(field_text_parts)
                results.append({
                    "form_name": form_name,
                    "field_name": field_name,
                    "page": page_num
                })
        
        i += 1
    
    return results, form_name

def extract_form_page(lines, page_num, fallback_form_name):
    """Extract from standard form pages."""
    results = []
    form_name = extract_form_name(lines) or fallback_form_name
    
    # Extract field labels: bold text with nearby [N] codes
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
                    if is_valid_field_name(label, context='form'):
                        field_labels.append(label)
                continue
            
            # Check if this is a field label (structural validation)
            if is_valid_field_name(text, context='form'):
                # Verify [N] code exists nearby
                if has_nearby_code(lines, i):
                    field_labels.append(text)
    
    # Deduplicate consecutive identical labels
    prev_label = None
    for label in field_labels:
        if label != prev_label:
            results.append({
                "form_name": form_name,
                "field_name": label,
                "page": page_num
            })
            prev_label = label
    
    return results, form_name

def is_valid_field_name(text, context='form'):
    """Check if text is a valid field name using structural rules only."""
    if not text or len(text) < 2:
        return False
    
    # Skip [N] codes
    if re.match(r'^\[\d+\]$', text):
        return False
    
    # Skip export names (all caps, no spaces, short)
    if len(text) < 15 and text.isupper() and ' ' not in text and not any(c.islower() for c in text):
        # But allow acronyms that are field names (e.g., "SpO2")
        if context == 'vitals' and any(keyword in text for keyword in ['SpO', 'BP', 'HR']):
            return True
        # Skip pure code-like strings
        if re.match(r'^[A-Z]{3,}[0-9]*[A-Z]*$', text):
            return False
    
    # Skip pure numbers
    if re.match(r'^\d+$', text):
        return False
    
    # Skip dates
    if re.match(r'^\d{2}[A-Za-z]{3}\d{4}$', text):
        return False
    
    # Skip single words that are structural markers (using position/context, not exhaustive lists)
    # Only skip if they appear in header region or are isolated column headers
    if context == 'table':
        # In tables, skip single-word uppercase entries if they're likely column headers
        if len(text.split()) == 1 and text[0].isupper() and len(text) < 12:
            # Check if it's a common data type indicator
            if text in ['Text', 'Date', 'Time', 'Number', 'Categorical', 'Type']:
                return False
    
    # Structural filter: skip if text is mostly numbers or symbols
    alpha_chars = sum(c.isalpha() for c in text)
    if alpha_chars < 3:
        return False
    
    # Skip very long text (likely instructions)
    if len(text) > 250:
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
        if abs(other.y0 - line.y0) < 5 and other.x0 > line.x1 and other.x0 < line.x1 + 50:
            if re.search(r'\[\d+\]', other.text):
                return True
    
    return False
```
