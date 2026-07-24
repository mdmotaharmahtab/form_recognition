Looking at the coverage gaps, I can see two main issues:

1. **Cluster 1 (drug screen tables)**: Pages like 309, 528 have substance names (Benzodiazepines, Cannabinoids, etc.) that ARE field labels, not answer options. My current code incorrectly filters them out.

2. **Cluster 2 (C-SSRS cover pages)**: Pages like 250, 420 are genuinely non-data pages (disclaimers/copyright), so 0% coverage is correct.

3. **Cluster 7 (schedule tables)**: Pages like 13, 16 are reference schedules (Visit/Page mapping tables), not data entry forms. The 20% coverage suggests I'm catching some but treating these as fields when they shouldn't be.

The main fix needed is recognizing that substance names in drug screen tables are actual field labels (one field per substance), not answer options.

```python
import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form title: large blue text, typically sz >= 13
        form_title = None
        for line in lines:
            # Look for prominent blue headings (form titles)
            if line.size >= 13.0 and line.non_black and not line.text.startswith('['):
                # Skip table of contents patterns
                if not re.match(r'^\d+(\.\d+)?\.?\s', line.text):
                    form_title = line.text.strip()
                    break
        
        # Update current form context
        if form_title:
            current_form = form_title
        
        # Detect page type by structural markers
        page_type = classify_page(lines)
        
        # Skip non-data pages
        if page_type in ['toc', 'schedule', 'cover', 'disclaimer']:
            continue
        
        # Process field-bearing pages
        fields = extract_fields(lines, current_form, page_type)
        for field_name in fields:
            records.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return records

def classify_page(lines):
    """Classify page type by structural markers"""
    text_samples = [l.text.strip() for l in lines if not l.text.startswith('[')]
    
    # Table of contents: has "CHANGE HISTORY" or "TABLE OF CONTENTS" heading
    if any('CHANGE HISTORY' in t or 'TABLE OF CONTENTS' in t for t in text_samples):
        return 'toc'
    
    # Schedule tables: have Schedule_ prefix in machine codes and Visit/Page column headers
    has_schedule_code = any('Schedule_' in l.text for l in lines if l.text.startswith('['))
    has_visit_columns = any(t in ['Visit Number', 'Page Number', 'Visit Label', 'Page Label'] for t in text_samples)
    if has_schedule_code and has_visit_columns:
        return 'schedule'
    
    # C-SSRS cover/disclaimer pages: have copyright notice and disclaimer text
    has_copyright = any('© 20' in t and 'Research Foundation' in t for t in text_samples)
    has_disclaimer = any('Disclaimer:' in t for t in text_samples)
    has_cssrs_title = any('COLUMBIA-SUICIDE SEVERITY RATING SCALE' in t for t in text_samples)
    if has_copyright and has_disclaimer and has_cssrs_title:
        return 'disclaimer'
    
    # Drug screen table: has substance names and Positive/Negative/Not Done columns
    has_drug_options = any(t in ['Positive', 'Negative', 'Not Done'] for t in text_samples)
    substance_names = ['Amphetamines', 'Barbiturates', 'Benzodiazepines', 'Cannabinoids', 
                       'Cocaine', 'Methadone', 'Opiates', 'Phencyclidine']
    has_substances = any(any(sub in t for sub in substance_names) for t in text_samples)
    if has_drug_options and has_substances:
        return 'drug_screen'
    
    return 'data_form'

def extract_fields(lines, form_name, page_type):
    """Extract fields based on page type"""
    if page_type == 'drug_screen':
        return extract_drug_screen_fields(lines)
    else:
        return extract_standard_fields(lines)

def extract_drug_screen_fields(lines):
    """Extract fields from drug screen tables - substance names are field labels"""
    fields = []
    
    # Known substance patterns (structural: left-aligned, size ~7.8, not bold)
    substance_patterns = [
        'Amphetamines', 'Barbiturates', 'Benzodiazepines', 'Cannabinoids',
        'Cocaine', 'Methadone', 'Opiates', 'Phencyclidine', 'Propoxyphene',
        'Buprenorphine', 'Oxycodone', 'MDMA', 'Methamphetamine', 'Tricyclic'
    ]
    
    for line in lines:
        text = line.text.strip()
        
        # Skip machine codes and metadata
        if text.startswith('[') or 'TYPE:' in text or 'VISIBILITY:' in text:
            continue
        
        # Skip answer options (these appear to the right)
        if text in ['Positive', 'Negative', 'Not Done', 'Yes', 'No']:
            continue
        
        # Skip read-only markers
        if text == '[Read-only field]':
            continue
        
        # Check if this is a substance name (field label)
        # Structural: left column (x < 150), reasonable size (6-10), not red
        if line.x0 < 150 and 6.0 <= line.size <= 10.0 and not line.text.startswith('['):
            # Match known substances or patterns
            for pattern in substance_patterns:
                if pattern in text:
                    fields.append(text)
                    break
    
    return deduplicate_fields(fields)

def extract_standard_fields(lines):
    """Extract fields from standard forms"""
    fields = []
    question_lines = []
    
    # Filter to field labels (questions/prompts)
    for line in lines:
        text = line.text.strip()
        
        # Skip machine codes, type annotations, visibility markers
        if text.startswith('[') or 'TYPE:' in text or 'VISIBILITY:' in text:
            continue
        
        # Skip answer options - these are right-aligned or in specific positions
        if is_answer_option(line, lines):
            continue
        
        # Skip table headers (structural labels)
        if is_table_header(text):
            continue
        
        # Skip page furniture (footers, version numbers, etc.)
        if line.size < 6.0 or is_page_furniture(text):
            continue
        
        # Skip structural row labels
        if line.bold and re.match(r'^Row\s+\d+:?$', text):
            continue
        
        question_lines.append(line)
    
    # Group lines into fields
    i = 0
    while i < len(question_lines):
        line = question_lines[i]
        text = line.text.strip()
        
        # Skip empty or very short fragments
        if len(text) < 3:
            i += 1
            continue
        
        # Check if this is a field label
        if is_field_label(text):
            # Collect continuation lines (wrapping)
            full_text = text
            j = i + 1
            while j < len(question_lines):
                next_line = question_lines[j]
                next_text = next_line.text.strip()
                
                # Stop if we hit another clear field label
                if is_field_label(next_text) and not is_continuation(next_text):
                    break
                
                # Stop if next line is structurally different (different column/section)
                if abs(next_line.y0 - line.y0) > 30 and abs(next_line.x0 - line.x0) > 20:
                    break
                
                # Check if this is a continuation (same column, nearby Y)
                if abs(next_line.x0 - line.x0) < 20 and next_line.y0 - line.y0 < 20:
                    full_text += " " + next_text
                    j += 1
                else:
                    break
            
            # Clean and add field
            field_name = clean_field_name(full_text)
            if field_name and len(field_name) > 5:
                fields.append(field_name)
            
            i = j
        else:
            i += 1
    
    return deduplicate_fields(fields)

def is_answer_option(line, all_lines):
    """Check if line is an answer option (not a field label)"""
    text = line.text.strip()
    
    # Common answer patterns (exact matches for short options)
    short_options = [
        'Yes', 'No', 'Not Applicable', 'Not Done', 'Positive', 'Negative',
        'Current', 'Former', 'Never', 'Scan',
        'Per Day', 'Per Week', 'Pack', 'Cigar', 'Cartridge', 'None'
    ]
    if text in short_options:
        return True
    
    # Numbered options like (1), (2)
    if re.match(r'^\(\d+\)$', text):
        return True
    
    # Long enumeration descriptions in parentheses
    if text.startswith('(') and text.endswith(')') and len(text) > 30:
        return True
    
    # Answer options are typically right-aligned (x > 300) or centered
    if line.x0 > 300 and len(text) < 15:
        return True
    
    return False

def is_table_header(text):
    """Check if text is a table header (structural, not a field)"""
    # Exact match common headers
    headers = [
        'Visit', 'Visit Label', 'Visit Number', 'Page', 'Page Label', 'Page Number',
        'Dynamic?', 'Description of Dynamic', 'Sample', 'Date of Collection',
        'Time of Collection', 'Scan', 'Barcode Number', 'Actual Attempts',
        'Most Lethal Attempt', 'Type of Contact', 'Method of Contact',
        'Date of Contact/Attempt', 'Were you able to contact the Subject?'
    ]
    return text in headers

def is_page_furniture(text):
    """Check if text is page furniture (headers, footers, metadata)"""
    # Version numbers
    if re.match(r'^Version\s+\d', text):
        return True
    
    # Dates in format like 17Aug2021
    if re.match(r'^\d{1,2}[A-Z][a-z]{2}\d{4}$', text):
        return True
    
    # Pack version labels
    if text == 'Pack Version':
        return True
    
    # Disclaimers and copyright
    if 'Disclaimer:' in text or '© 20' in text:
        return True
    
    # Page numbers (standalone numbers)
    if re.match(r'^\d{1,3}$', text):
        return True
    
    return False

def is_field_label(text):
    """Check if text looks like a field label/question"""
    # Questions end with ?
    if text.endswith('?'):
        return True
    
    # Field labels with colons (but not structural like "Row 1:")
    if ':' in text and len(text) < 100:
        if not re.match(r'^Row\s+\d+:?$', text):
            return True
    
    # Longer descriptive text (likely a field label)
    # Must have some lowercase (not all-caps structural text)
    if len(text) > 15 and any(c.islower() for c in text):
        return True
    
    return False

def is_continuation(text):
    """Check if text is likely a continuation of previous line"""
    # Starts with lowercase (mid-sentence)
    if text and text[0].islower():
        return True
    
    # Very short fragments
    if len(text) < 20 and not text.endswith('?'):
        return True
    
    return False

def clean_field_name(text):
    """Clean and normalize field name"""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove trailing colon
    if text.endswith(':'):
        text = text[:-1].strip()
    
    # Remove "Row N" prefixes
    text = re.sub(r'^Row\s+\d+\s*', '', text)
    
    # Remove question numbering like "1.", "2."
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
