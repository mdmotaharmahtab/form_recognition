I need to analyze the issues and fix the extraction program. Let me break down the problems:

1. **Cluster 2 (10 pages, 0% covered)**: These are disclaimer/title pages - correctly skipped
2. **Cluster 1 (50% covered)**: Pages with only machine codes and TYPE annotations - need to handle these metadata-only pages
3. **False positives on pages 9, 10**: Extracting table headers and structural elements from Schedule tables
4. **Missing fields on pages 72, 485**: Long descriptive text that's actually a field label
5. **False positives on pages 72, 255, 485**: Extracting answer option descriptions and rating anchors

The main issues are:
- Schedule table detection is too weak - still extracting headers/labels
- Long parenthetical text (rating scale anchors) being extracted as fields
- Multi-line field labels with embedded descriptions not being captured

Here's the fixed program:

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
        
        # Skip pages that are clearly non-data
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
    """Detect non-data pages by structural markers"""
    text_samples = [l.text.strip() for l in lines if not l.text.startswith('[')]
    
    # Table of contents
    if any('CHANGE HISTORY' in t or 'TABLE OF CONTENTS' in t for t in text_samples):
        return True
    
    # Schedule tables: have Schedule_ codes AND column headers AND sparse content
    has_schedule_code = any('Schedule_' in l.text for l in lines if l.text.startswith('['))
    has_visit_label = any('Visit Label' in t for t in text_samples)
    has_visit_number = any('Visit Number' == t for t in text_samples)
    if has_schedule_code and (has_visit_label or has_visit_number):
        return True
    
    # Cover/disclaimer pages: copyright + disclaimer OR long disclaimer text
    has_copyright = any('©' in t and 'Research Foundation' in t for t in text_samples)
    has_disclaimer = any('Disclaimer:' in t for t in text_samples)
    has_long_disclaimer = any('This scale is intended to be used by individuals' in t for t in text_samples)
    if (has_copyright and has_disclaimer) or has_long_disclaimer:
        return True
    
    # Metadata-only pages: only machine codes and TYPE/VISIBILITY annotations
    non_machine = [l for l in lines if not l.text.startswith('[')]
    has_only_annotations = all('TYPE:' in l.text or 'VISIBILITY:' in l.text or 
                               '[Read-only field]' in l.text or not l.text.strip() 
                               for l in non_machine if l.text.strip())
    if has_only_annotations and len(non_machine) <= 10:
        return True
    
    return False

def extract_fields_from_page(lines, form_name):
    """Extract all field labels from a page using structural classification"""
    fields = []
    
    # Pre-filter: detect if this is a schedule/table page by structure
    is_schedule_page = detect_schedule_page_structure(lines)
    
    # Classify each line by its structural role
    classified = []
    for i, line in enumerate(lines):
        role = classify_line_role(line, lines, i, is_schedule_page)
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
            
            # Check if continuation (same X column within 25px, Y within 25px)
            if abs(next_line.x0 - line.x0) < 25 and 0 < next_line.y0 - line.y0 < 25:
                # Is this a continuation or a new field?
                if is_likely_continuation(next_text, full_text):
                    full_text += " " + next_text
                    j += 1
                else:
                    break
            else:
                break
        
        # Clean and add field
        field_name = clean_field_name(full_text)
        if field_name and len(field_name) > 3 and is_valid_field_label(field_name):
            fields.append(field_name)
        
        i = j if j > i else i + 1
    
    return deduplicate_fields(fields)

def detect_schedule_page_structure(lines):
    """Detect if this page has schedule/table structure"""
    text_samples = [l.text.strip() for l in lines if not l.text.startswith('[')]
    
    # Multiple short labels in top area (Y < 150) suggesting table headers
    top_labels = [l for l in lines if l.y0 < 150 and not l.text.startswith('[')]
    short_top = [l for l in top_labels if len(l.text.strip()) < 30]
    
    # Check for table header patterns
    has_visit_number = any('Visit Number' == t for t in text_samples)
    has_page_number = any('Page Number' == t for t in text_samples)
    has_schedule_label = any('Schedule' == t for t in text_samples)
    
    # Has many short labels suggesting columnar layout
    if len(short_top) >= 5 and (has_visit_number or has_page_number or has_schedule_label):
        return True
    
    return False

def classify_line_role(line, all_lines, index, is_schedule_page):
    """Classify a line's structural role on the page"""
    text = line.text.strip()
    
    # Machine codes
    if text.startswith('['):
        return 'machine_code'
    
    # Type annotations
    if 'TYPE:' in text or 'VISIBILITY:' in text or text == '[Read-only field]':
        return 'annotation'
    
    # Empty or too small
    if not text or line.size < 6.0:
        return 'junk'
    
    # Page furniture
    if is_structural_furniture(line, text):
        return 'furniture'
    
    # On schedule pages, aggressively filter table headers
    if is_schedule_page and is_schedule_table_element(line, text, all_lines):
        return 'table_header'
    
    # Answer options and rating anchors
    if is_answer_option_or_anchor(line, text):
        return 'answer_option'
    
    # Table headers by structural pattern
    if is_structural_table_header(line, text, all_lines):
        return 'table_header'
    
    # Everything else that looks like user-facing text is a potential field label
    if looks_like_field_label(line, text):
        return 'field_label'
    
    return 'unknown'

def is_schedule_table_element(line, text, all_lines):
    """Detect schedule table headers and cells aggressively"""
    # Single-word short labels that are table headers
    if len(text) < 20 and ' ' not in text.strip():
        if text in ['Schedule', 'Number', 'Visit', 'Page', 'Screen', 'Day', 'Label', 'Description', 'Dynamic']:
            return True
    
    # Visit/page labels with numbers/ranges
    if re.match(r'^(Screen|Visit|Page|Titration)\s+(Visit\s+)?\d+', text):
        return True
    if re.match(r'^Day\s+-?\d+', text):
        return True
    
    # Conditional enrollment text
    if 'page enrols if' in text or 'if Is the Subject required' in text:
        return True
    if text.startswith('if ') and '=' in text and len(text) < 100:
        return True
    
    # Schedule codes
    if text.startswith('Schedule_'):
        return True
    
    # Very short labels in header area (Y < 120) on schedule-like pages
    if line.y0 < 120 and len(text) < 25:
        # Count neighbors in same row
        same_row = sum(1 for l in all_lines if abs(l.y0 - line.y0) < 8 and not l.text.startswith('['))
        if same_row >= 4:
            return True
    
    return False

def is_structural_furniture(line, text):
    """Detect page furniture by structural patterns"""
    # Version numbers
    if re.match(r'^Version\s+\d', text):
        return True
    
    # Dates in format like 17Aug2021
    if re.match(r'^\d{1,2}[A-Z][a-z]{2}\d{4}$', text):
        return True
    
    # Pack version labels
    if text == 'Pack Version':
        return True
    
    # Standalone page numbers
    if re.match(r'^\d{1,3}$', text) and line.x0 > 200:
        return True
    
    return False

def is_answer_option_or_anchor(line, text):
    """Detect answer options and rating scale anchors"""
    # Very short options, right-aligned or centered
    if len(text) <= 15 and line.x0 > 280:
        return True
    
    # Numbered options like (1), (2)
    if re.match(r'^\(\d+\)$', text):
        return True
    
    # Long parenthetical descriptions (rating anchors/enumeration descriptions)
    # These are typically answer option explanations, not field labels
    if text.startswith('(') and text.endswith(')') and len(text) > 40:
        return True
    
    # Answer value enumerations in brackets
    if re.match(r'^\(values?:', text):
        return True
    if text.startswith('(') and ('values:' in text or 'e.g.' in text):
        return True
    
    # Per Day, Per Week, etc. - right column short labels
    if len(text) < 20 and line.x0 > 250 and not text.endswith('?') and ':' not in text:
        return True
    
    # Long descriptive text that's clearly an answer option explanation
    # Starts with caps but contains "you" "the subject" etc. and is mid-paragraph
    if len(text) > 80 and not text.endswith('?') and ':' not in text:
        # Contains explanatory phrases typical of rating anchors
        if any(phrase in text.lower() for phrase in ['e.g.', 'includes', 'as opposed to', 'this is different', 'worked out']):
            # Check if it's mid-column (not left-aligned for a field label)
            if line.x0 > 60 or text[0].islower():
                return True
    
    # Partial sentences that are clearly continuations of rating descriptions
    if text[0].islower() and len(text) > 50:
        return True
    
    return False

def is_structural_table_header(line, text, all_lines):
    """Detect table headers by structural patterns"""
    # Bold text in header row
    if line.bold and line.y0 < 100:
        return True
    
    # Short labels in top row that appear repeatedly
    if len(text) < 30 and line.y0 < 120:
        same_row = sum(1 for l in all_lines if abs(l.y0 - line.y0) < 5 and not l.text.startswith('['))
        if same_row >= 3:
            return True
    
    return False

def looks_like_field_label(line, text):
    """Check if text looks like a field label structurally"""
    # Questions (end with ?)
    if text.endswith('?'):
        return True
    
    # Field labels with colons (but not structural markers)
    if ':' in text and len(text) < 150:
        if not re.match(r'^Row\s+\d+:?\s*$', text):
            return True
    
    # Longer descriptive text (likely a field label)
    # Must have some lowercase (not all-caps structural text)
    if len(text) > 12 and any(c.islower() for c in text):
        # But not if it's a long explanatory paragraph
        if len(text) > 200 and not text.endswith('?') and ':' not in text:
            # Very long without question/colon is likely rating anchor
            return False
        return True
    
    # Left-aligned text with reasonable size
    if line.x0 < 200 and 7.0 <= line.size <= 11.0 and len(text) > 5:
        # Has mixed case (not all caps)
        if any(c.islower() for c in text) and any(c.isupper() for c in text):
            return True
    
    return False

def is_likely_continuation(text, previous_text):
    """Check if text is likely a continuation of previous line"""
    # Starts with lowercase (mid-sentence)
    if text and text[0].islower():
        return True
    
    # Very short fragments without punctuation
    if len(text) < 25 and not text.endswith('?') and ':' not in text:
        return True
    
    # Previous text seems incomplete (doesn't end with sentence terminator)
    if previous_text and not re.search(r'[.?!]\s*$', previous_text):
        # Current text looks like continuation (lowercase start or no colon)
        if text[0].islower() or (':' not in text and not text.endswith('?')):
            return True
    
    return False

def is_valid_field_label(text):
    """Final validation: is this really a field label and not junk?"""
    # Filter out rating scale anchors that slipped through
    # These have specific patterns
    if len(text) > 150 and not text.endswith('?'):
        # Contains explanatory phrases
        if any(phrase in text.lower() for phrase in 
               ['e.g.', 'includes', 'as opposed to', 'this is different', 'worked out',
                'you could not', 'would say', 'i thought about']):
            return False
    
    # Filter out enumeration lists (0) Something, (1) Something
    if re.match(r'^\(\d+\)', text):
        return False
    
    # Filter out value lists
    if text.startswith('(values:'):
        return False
    
    return True

def clean_field_name(text):
    """Clean and normalize field name"""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove trailing colon
    if text.endswith(':'):
        text = text[:-1].strip()
    
    # Remove "Row N" prefixes
    text = re.sub(r'^Row\s+\d+\s*', '', text)
    
    # Remove question numbering
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
