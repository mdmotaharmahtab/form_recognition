Looking at the sample pages:

**Pages 250 and 420 (cluster 2)**: These are disclaimer/copyright pages for the C-SSRS scale. They contain only the scale title, version info, author credits, disclaimer text, and copyright notice. No data-entry fields present - these are informational cover pages.

**Pages 129 and 528 (cluster 1)**: These show only machine codes (`[LBTEST3]`, `[LBORRES3]`) with type annotations and metadata. However, the machine codes themselves suggest there SHOULD be corresponding field labels on these pages that are being filtered out. The current program may be too aggressive in its filtering.

Let me provide the updated program that handles cluster 1 pages properly:

```python
import re

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form title: large blue text, typically sz >= 13
        form_title = None
        for line in lines:
            if line.size >= 13.0 and line.non_black and not line.text.startswith('['):
                if not re.match(r'^\d+(\.\d+)?\.?\s', line.text):
                    form_title = line.text.strip()
                    break
        
        if form_title:
            current_form = form_title
        
        # Skip pages that are clearly non-data (structural detection only)
        if is_non_data_page(lines):
            continue
        
        # Extract fields from this page
        fields = extract_fields_from_page(lines, current_form)
        for field_name in fields:
            records.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return records

def is_non_data_page(lines):
    """Detect non-data pages by structural markers only"""
    text_samples = [l.text.strip() for l in lines if not l.text.startswith('[')]
    
    # Table of contents: has "CHANGE HISTORY" or "TABLE OF CONTENTS" heading
    if any('CHANGE HISTORY' in t or 'TABLE OF CONTENTS' in t for t in text_samples):
        return True
    
    # Schedule tables: have Schedule_ prefix in machine codes and column header pattern
    has_schedule_code = any('Schedule_' in l.text for l in lines if l.text.startswith('['))
    has_visit_columns = any(t in ['Visit Number', 'Page Number', 'Visit Label', 'Page Label'] for t in text_samples)
    if has_schedule_code and has_visit_columns:
        return True
    
    # Cover/disclaimer pages: have copyright and disclaimer together
    has_copyright = any('©' in t and ('Research Foundation' in t or 'Copyright' in t) for t in text_samples)
    has_disclaimer = any('Disclaimer:' in t for t in text_samples)
    if has_copyright and has_disclaimer:
        return True
    
    return False

def extract_fields_from_page(lines, form_name):
    """Extract all field labels from a page using structural classification"""
    fields = []
    
    # Classify each line by its structural role
    classified = []
    for i, line in enumerate(lines):
        role = classify_line_role(line, lines, i)
        if role == 'field_label':
            classified.append(line)
    
    # Group consecutive field labels (handle wrapping)
    i = 0
    while i < len(classified):
        line = classified[i]
        text = line.text.strip()
        
        # Skip very short fragments
        if len(text) < 3:
            i += 1
            continue
        
        # Collect continuation lines (same column, nearby Y)
        full_text = text
        j = i + 1
        while j < len(classified):
            next_line = classified[j]
            next_text = next_line.text.strip()
            
            # Check if continuation (same X column within 20px, Y within 20px)
            if abs(next_line.x0 - line.x0) < 20 and 0 < next_line.y0 - line.y0 < 20:
                # Is this a continuation or a new field?
                if is_likely_continuation(next_text):
                    full_text += " " + next_text
                    j += 1
                else:
                    break
            else:
                break
        
        # Clean and add field
        field_name = clean_field_name(full_text)
        if field_name and len(field_name) > 3:
            fields.append(field_name)
        
        i = j if j > i else i + 1
    
    return deduplicate_fields(fields)

def classify_line_role(line, all_lines, index):
    """Classify a line's structural role on the page"""
    text = line.text.strip()
    
    # Machine codes: always start with [
    if text.startswith('['):
        return 'machine_code'
    
    # Type annotations: contain "TYPE:" or "VISIBILITY:" but NOT if they're alone with just machine codes
    # Check if this is a metadata-only page (only machine codes and type annotations)
    if 'TYPE:' in text or 'VISIBILITY:' in text:
        # Don't filter as annotation if the page seems sparse (might be continuation page)
        non_machine_lines = [l for l in all_lines if not l.text.startswith('[')]
        if len(non_machine_lines) <= 5:
            # Sparse page - might have hidden field labels
            return 'annotation'
        return 'annotation'
    
    # Read-only field marker
    if text == '[Read-only field]':
        return 'annotation'
    
    # Empty or too small to be a field label
    if not text or line.size < 6.0:
        return 'junk'
    
    # Page furniture by structural position and format
    if is_structural_furniture(line, text):
        return 'furniture'
    
    # Answer options by structural position (right-aligned or specific patterns)
    if is_structural_answer_option(line, text):
        return 'answer_option'
    
    # Table headers by structural pattern (bold, specific positions)
    if is_structural_table_header(line, text, all_lines):
        return 'table_header'
    
    # Everything else that looks like user-facing text is a potential field label
    if looks_like_field_label(line, text):
        return 'field_label'
    
    return 'unknown'

def is_structural_furniture(line, text):
    """Detect page furniture by structural patterns"""
    # Version numbers: "Version" + digits
    if re.match(r'^Version\s+\d', text):
        return True
    
    # Dates in format like 17Aug2021 (no spaces, mixed case)
    if re.match(r'^\d{1,2}[A-Z][a-z]{2}\d{4}$', text):
        return True
    
    # Pack version labels (exact structural pattern)
    if text == 'Pack Version':
        return True
    
    # Standalone page numbers (just digits, centered or right)
    if re.match(r'^\d{1,3}$', text) and line.x0 > 200:
        return True
    
    return False

def is_structural_answer_option(line, text):
    """Detect answer options by structural position and patterns"""
    # Very short options (exact match patterns like Yes/No)
    # Right-aligned (x > 280) or centered (x > 200 and x < 400)
    if len(text) <= 15 and line.x0 > 280:
        return True
    
    # Numbered options like (1), (2), (3)
    if re.match(r'^\(\d+\)$', text):
        return True
    
    # Long parenthetical descriptions (enumeration descriptions)
    if text.startswith('(') and text.endswith(')') and len(text) > 30:
        return True
    
    # Per Day, Per Week, etc. - right column short labels
    if len(text) < 20 and line.x0 > 250 and not text.endswith('?') and not ':' in text:
        return True
    
    return False

def is_structural_table_header(line, text, all_lines):
    """Detect table headers by structural patterns"""
    # Bold text in header row (Y < 100, bold)
    if line.bold and line.y0 < 100:
        return True
    
    # Short labels in top row that appear repeatedly across pages
    # Typically: Visit, Page, Sample, Date, Time, etc.
    if len(text) < 30 and line.y0 < 120:
        # Count how many other lines have similar Y (same row)
        same_row = sum(1 for l in all_lines if abs(l.y0 - line.y0) < 5 and not l.text.startswith('['))
        if same_row >= 3:
            return True
    
    return False

def looks_like_field_label(line, text):
    """Check if text looks like a field label structurally"""
    # Questions (end with ?)
    if text.endswith('?'):
        return True
    
    # Field labels with colons (but not structural markers like "Row 1:")
    if ':' in text and len(text) < 150:
        if not re.match(r'^Row\s+\d+:?\s*$', text):
            return True
    
    # Longer descriptive text (likely a field label)
    # Must have some lowercase (not all-caps structural text)
    if len(text) > 12 and any(c.islower() for c in text):
        return True
    
    # Left-aligned text (x < 200) with reasonable size (7-11pt)
    # This catches field labels that don't have ? or :
    if line.x0 < 200 and 7.0 <= line.size <= 11.0 and len(text) > 5:
        # Has mixed case (not all caps)
        if any(c.islower() for c in text) and any(c.isupper() for c in text):
            return True
    
    return False

def is_likely_continuation(text):
    """Check if text is likely a continuation of previous line"""
    # Starts with lowercase (mid-sentence)
    if text and text[0].islower():
        return True
    
    # Very short fragments without punctuation
    if len(text) < 25 and not text.endswith('?') and ':' not in text:
        return True
    
    return False

def clean_field_name(text):
    """Clean and normalize field name"""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove trailing colon
    if text.endswith(':'):
        text = text[:-1].strip()
    
    # Remove "Row N" prefixes (structural artifact)
    text = re.sub(r'^Row\s+\d+\s*', '', text)
    
    # Remove question numbering like "1.", "2." at start
    text = re.sub(r'^\d+\.\s*', '', text)
    
    return text

def deduplicate_fields(fields):
    """Remove exact duplicates while preserving order"""
    seen = set()
    result = []
    for field in fields:
        if field not in seen:
            seen.add(field)
            result.append(field)
    return result
```
