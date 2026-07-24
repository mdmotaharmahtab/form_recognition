STRATEGY:

This document contains multiple layout families that need different handling:

1. **Form titles**: Large blue text (~16.5pt, #004c99) marks form/section names. These appear at the top of form pages but may be absent on continuation pages. We carry forward the last seen form title across all subsequent pages until a new title appears.

2. **Definition/copyright pages (cluster 0)**: Pages with Columbia Suicide History Form citations and copyright notices. These contain no data-entry fields - they are reference/attribution pages. We detect them by the presence of copyright text or "Columbia Suicide History Form" references and skip field extraction.

3. **Table header pages (cluster 1)**: Pages showing only column headers like "Record", "Term", "Onset Date", "Onset Time" with no data rows below. These are empty table templates. We detect them by having only a few short header-like texts near the top and skip them.

4. **Repeatable row instruction pages (cluster 2)**: Pages with just a form title and "(Repeatable row added with Add Row button)" text. These are structural instruction pages with no actual fields. We detect and skip them.

5. **Actual field pages (cluster 4)**: Pages with checkboxes, field labels, and answer options. Field labels are black text ~9-10.5pt. We distinguish fields from answer options by:
   - Fields: black text, meaningful labels (often questions or statements)
   - Options: may be indented, shorter phrases, or bulleted items
   - We extract multi-line field labels by detecting continuation lines with similar x-position

6. **Missing fields**: The audit shows "Vasectomy" was missed and "Of Childbearing Potential" was incorrectly extracted as a field (it's likely a section header or category label). We refine detection to:
   - Include all checkbox/field labels regardless of length
   - Exclude section category headers (short phrases that introduce groups of options)
   - Better handle fields that appear in lists or grids

The key is to process every page, carry forward form titles, and use structural cues (position, size, style) rather than content filtering to separate fields from non-fields.

```python
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
            if ln.size >= 15.0 and ln.non_black
        ]
        if form_title_candidates:
            # Take the first/topmost large blue text as form title
            current_form = form_title_candidates[0].text.strip()
        
        # Skip definition/copyright pages
        if is_definition_page(lines):
            continue
        
        # Skip empty table header pages
        if is_empty_table_header_page(lines):
            continue
        
        # Skip repeatable row instruction pages
        if is_repeatable_instruction_page(lines):
            continue
        
        # Extract fields from this page
        fields = extract_fields_from_page(lines)
        
        for field_name in fields:
            records.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return records

def is_definition_page(lines):
    """Detect definition/copyright pages (cluster 0)"""
    all_text = " ".join(ln.text for ln in lines)
    
    # Check for copyright and Columbia Suicide History Form references
    if "© 2008 The Research Foundation" in all_text:
        return True
    if "Columbia Suicide History Form" in all_text:
        return True
    if "posnerk@nyspi.columbia.edu" in all_text:
        return True
    
    return False

def is_empty_table_header_page(lines):
    """Detect pages with only table column headers (cluster 1)"""
    # Filter to non-page-number lines
    content_lines = [ln for ln in lines if not re.match(r'Page \d+ of \d+', ln.text.strip())]
    
    # If very few lines (< 6) and they're all short (< 20 chars) and near top (y < 200)
    if len(content_lines) < 6:
        short_top_lines = [ln for ln in content_lines if len(ln.text.strip()) < 20 and ln.y0 < 200]
        if len(short_top_lines) == len(content_lines):
            return True
    
    return False

def is_repeatable_instruction_page(lines):
    """Detect pages with just repeatable row instructions (cluster 2)"""
    all_text = " ".join(ln.text for ln in lines)
    
    # Check for repeatable row instruction text
    if "Repeatable row added with Add Row button" in all_text:
        # Count non-title, non-page-number content
        content_lines = [
            ln for ln in lines 
            if ln.size < 15 and not re.match(r'Page \d+ of \d+', ln.text.strip())
        ]
        # If only the instruction line is present, skip
        if len(content_lines) <= 2:
            return True
    
    return False

def extract_fields_from_page(lines):
    """Extract field labels from a page"""
    fields = []
    i = 0
    
    while i < len(lines):
        ln = lines[i]
        
        # Skip page numbers
        if re.match(r'Page \d+ of \d+', ln.text.strip()):
            i += 1
            continue
        
        # Skip form titles (large blue text)
        if ln.size >= 15.0 and ln.non_black:
            i += 1
            continue
        
        # Skip red annotations (technical metadata)
        if ln.non_black and is_red_annotation(ln.text):
            i += 1
            continue
        
        # Candidate field: black text, size 8.5-11pt
        if not ln.non_black and 8.5 <= ln.size <= 11:
            text = ln.text.strip()
            
            # Skip empty or very short text
            if len(text) < 3:
                i += 1
                continue
            
            # Skip technical markers
            if text.startswith('[') and text.endswith(']'):
                i += 1
                continue
            
            # Skip row labels
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip bullet points that are answer options (single bullets)
            if text.startswith('•') and len(text) < 50:
                i += 1
                continue
            
            # Skip standalone category headers (short, all caps or title case, no punctuation)
            # These are like "Of Childbearing Potential" - section labels not fields
            if is_category_header(text, ln):
                i += 1
                continue
            
            # Check for multi-line field (continuation lines)
            field_text = text
            j = i + 1
            while j < len(lines):
                next_ln = lines[j]
                # Continuation: similar x (within 10pt), y within 20pt, same size range, black
                if (abs(next_ln.x0 - ln.x0) < 10 and 
                    next_ln.y0 - lines[j-1].y1 < 20 and 
                    not next_ln.non_black and 
                    8.5 <= next_ln.size <= 11 and
                    not next_ln.text.strip().startswith('[') and
                    not re.match(r'^Row \d+$', next_ln.text.strip())):
                    field_text += " " + next_ln.text.strip()
                    j += 1
                else:
                    break
            
            # Clean and validate
            field_text = clean_field_text(field_text)
            if is_valid_field(field_text):
                fields.append(field_text)
            
            i = j
        else:
            i += 1
    
    return fields

def is_category_header(text, line):
    """Detect section category headers that aren't actual fields"""
    # Very short text (< 5 words) that's not a question
    words = text.split()
    if len(words) <= 5 and not text.endswith('?'):
        # Check if it's title-case or all caps (typical of headers)
        if text.istitle() or text.isupper():
            # Not a field if it doesn't contain common field words
            field_indicators = ['does', 'has', 'is', 'was', 'will', 'date', 'time', 'number', 'name']
            if not any(indicator in text.lower() for indicator in field_indicators):
                return True
    
    return False

def is_red_annotation(text):
    """Detect red technical annotations"""
    return text.startswith('[') and any(kw in text for kw in ['TYPE:', 'VISIBILITY:', 'Read-only'])

def clean_field_text(text):
    """Clean up field text"""
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove trailing question marks (keep internal ones)
    text = re.sub(r'\?$', '', text)
    return text

def is_valid_field(text):
    """Validate that text is a real field label"""
    if len(text) < 3:
        return False
    
    # Skip pure dates
    if re.match(r'^\d+[\-/]\d+[\-/]\d+$', text):
        return False
    
    # Skip standalone answer options
    if text in ['Yes', 'No', 'N/A', 'Collected', 'Not Collected', 'X', 'Unknown']:
        return False
    
    # Skip table column headers (single words, title case)
    if len(text.split()) == 1 and text[0].isupper() and text in ['Record', 'Term', 'Date', 'Time', 'Onset']:
        return False
    
    return True
```