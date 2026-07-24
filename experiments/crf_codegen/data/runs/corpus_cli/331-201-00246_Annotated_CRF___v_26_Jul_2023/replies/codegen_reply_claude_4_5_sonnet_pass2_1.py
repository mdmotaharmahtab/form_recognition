```python
# LAYOUT OBSERVATIONS:
# - Most pages have a large colored title header (16.5pt, #004c99) near y~153
# - Data-entry fields appear as regular black text (9-10.5pt) in left column
# - Technical codes in red (#ff0000) like [TYPE:...], [VISIBILITY:...] appear below fields
# - Table of contents pages (families A-C) list section titles in blue (#2477cc)
# - Multi-column data tables have column headers at y~124
# - Some pages are disclaimers/copyright (families G,H) with no fields
#
# STRATEGY:
# 1. Extract form_name from large blue/colored headers (size 12-16.5, typically y<200)
# 2. Identify data-entry fields: black text 9-10.5pt, NOT red codes, NOT table headers
# 3. Skip TOC pages (families A-C), disclaimers (G,H), change history (D)
# 4. Handle multi-line field wrapping by joining consecutive lines
# 5. Filter out answer options, column headers, and page furniture

import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip empty pages
        if not lines:
            continue
        
        # Detect and skip non-field pages by structural markers
        if is_skip_page(lines):
            continue
        
        # Extract form name from title header
        form_title = extract_form_title(lines)
        if form_title:
            current_form = form_title
        
        # Extract fields from this page
        page_fields = extract_fields_from_page(lines, current_form, page_num)
        records.extend(page_fields)
    
    return records


def is_skip_page(lines):
    """Detect pages that should be skipped based on structural markers."""
    text_content = [line.text for line in lines[:30]]
    text_str = " ".join(text_content).lower()
    
    # Skip table of contents pages (contain "pages" header and numbered links)
    if any("page label" in line.text.lower() and "page num" in " ".join(text_content).lower() 
           for line in lines[:20]):
        return True
    
    # Skip change history pages
    if any(line.text == "Change History" for line in lines[:10]):
        return True
    
    # Skip disclaimer/copyright pages (C-SSRS boilerplate)
    if any("columbia-suicide severity" in line.text.lower() or 
           "disclaimer:" in line.text.lower() or
           "research foundation for mental hygiene" in line.text.lower()
           for line in lines[:50]):
        return True
    
    # Skip annotated CRF title page
    if any("annotated crf" in line.text.lower() for line in lines[:10]):
        return True
    
    return False


def extract_form_title(lines):
    """Extract form/section title from large colored header."""
    # Look for prominent title in first ~300 vertical points
    for line in lines[:40]:
        if line.y0 > 300:
            break
        
        # Form titles are typically 12-16.5pt, colored (blue/teal), bold or distinct
        if line.size >= 12.0 and line.size <= 18.0:
            # Colored text is often a title
            if line.non_black or line.bold:
                text = line.text.strip()
                # Filter out pure structural markers
                if text and not is_structural_noise(text):
                    # Clean up wrapped titles
                    return text
    
    return ""


def is_structural_noise(text):
    """Check if text is structural noise, not a real title."""
    noise_patterns = [
        r'^\d+\s*$',  # pure numbers
        r'^page \d+ of \d+$',  # page numbers
        r'^row \d+$',  # row labels
        r'^\[.*\]$',  # technical codes
        r'^visit num',  # table headers
        r'^schedule_',  # schedule labels
        r'^repeatable row',
    ]
    lower_text = text.lower()
    return any(re.match(pat, lower_text) for pat in noise_patterns)


def extract_fields_from_page(lines, form_name, page_num):
    """Extract data-entry fields from a page."""
    fields = []
    
    # Group lines into potential field candidates
    field_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip if clearly not a field
        if should_skip_line(line):
            i += 1
            continue
        
        # Check if this looks like a field label
        if is_potential_field(line):
            # Collect this line and potential continuation lines
            field_text = line.text.strip()
            j = i + 1
            
            # Join wrapped lines (similar x position, close y position, similar style)
            while j < len(lines):
                next_line = lines[j]
                # Stop if we hit a technical code or very different position
                if should_skip_line(next_line):
                    break
                if abs(next_line.x0 - line.x0) > 30:
                    break
                if next_line.y0 - line.y0 > 50:
                    break
                # Stop if next line looks like a new field
                if next_line.size >= 9.0 and next_line.y0 - line.y0 > 30:
                    break
                
                # Join continuation
                if is_potential_field(next_line):
                    field_text += " " + next_line.text.strip()
                    j += 1
                else:
                    break
            
            # Clean and validate the field
            field_text = clean_field_text(field_text)
            if is_valid_field(field_text, lines):
                fields.append({
                    "form_name": form_name,
                    "field_name": field_text,
                    "page": page_num
                })
            
            i = j
        else:
            i += 1
    
    return fields


def should_skip_line(line):
    """Check if line should be skipped entirely."""
    text = line.text.strip()
    
    # Skip technical codes (red text with brackets)
    if line.non_black and ('[' in text or 'TYPE:' in text or 'VISIBILITY:' in text):
        return True
    
    # Skip red text
    if line.non_black and line.size < 11.0:
        return True
    
    # Skip page numbers
    if re.match(r'^page \d+ of \d+$', text.lower()):
        return True
    
    # Skip very small text
    if line.size < 8.5:
        return True
    
    # Skip lines at bottom of page (footer region)
    if line.y0 > 780:
        return True
    
    # Skip lines at very top (header region)
    if line.y0 < 115:
        return True
    
    return False


def is_potential_field(line):
    """Check if line looks like a field label."""
    text = line.text.strip()
    
    # Must be black text
    if line.non_black:
        return False
    
    # Typical field label size
    if line.size < 8.5 or line.size > 12.0:
        return False
    
    # Must have actual content
    if not text or len(text) < 2:
        return False
    
    # Should not be pure structural markers
    if is_structural_noise(text):
        return False
    
    return True


def clean_field_text(text):
    """Clean up extracted field text."""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove trailing punctuation artifacts
    text = re.sub(r'\s*[•\-]+\s*$', '', text)
    
    return text


def is_valid_field(field_text, lines):
    """Validate that extracted text is a real field, not noise."""
    if not field_text:
        return False
    
    lower_text = field_text.lower()
    
    # Filter out common non-fields
    non_field_patterns = [
        r'^x\s*$',  # checkbox markers
        r'^\d+\s*$',  # pure numbers
        r'^yes\s*$',  # answer options
        r'^no\s*$',
        r'^scan\s*$',
        r'^collected\s*$',
        r'^not collected\s*$',
        r'^row \d+$',
        r'^version',
        r'^date$',
        r'^details$',
        r'^changed by',
        r'^visit number',
        r'^visit label',
        r'^page num',
        r'^page label',
        r'^dynamic',
        r'^description of dynamic',
        r'^sample status',
        r'^timepoint',
        r'^barcode',
        r'^backup',
        r'^time of collection',
        r'^trial day',
        r'^start date$',
        r'^stop date$',
        r'^initial contact$',
        r'^second contact',
        r'^third contact',
        r'^certified letter',
        r'^method of contact',
        r'^type of contact',
        r'^\(repeatable row',
    ]
    
    for pattern in non_field_patterns:
        if re.match(pattern, lower_text):
            return False
    
    # Reject very short text unless it's clearly a question
    if len(field_text) < 3:
        return False
    
    # Reject if it looks like a column header (short, generic)
    if len(field_text.split()) <= 2 and any(keyword in lower_text for keyword in 
        ['sample', 'date', 'time', 'status', 'number', 'barcode', 'visit', 'page']):
        return False
    
    return True
```
