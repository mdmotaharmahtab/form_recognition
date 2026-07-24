STRATEGY:

This document contains multiple layout types that need different handling:

1. **Table of Contents pages (cluster 5, pages 1-9)**: These show numbered form titles in blue but are NOT actual forms - they're navigation pages. Skip extraction here by detecting the TOC pattern (numbered list format like "3.120.", "3.121." with no actual field labels).

2. **Standard CRF pages (clusters 0, 1, 2, 7, 8)**: These work well with the current approach. Form titles are large blue text at top; field labels are black, left-aligned, medium-sized text. Continue current logic.

3. **Answer option reference pages (cluster 3, pages like 938, 941)**: These show lists of possible answers (medication forms, routes) with no actual data-entry fields. They have no form title and consist only of option lists. Skip extraction by detecting: no large blue title present AND page consists mainly of right-aligned option text.

4. **C-SSRS continuation pages (cluster 4, pages like 398, 693)**: These show only a form title ("C-SSRS since last visit - Page 3/4") with no fields visible - the fields are on earlier pages. The title is present but smaller/different position. Extract nothing but carry the title forward for subsequent pages.

5. **Form title persistence**: Carry forward the most recent form title across all pages until a new title appears. Handle cases where title may be smaller or positioned differently on continuation pages.

6. **Field extraction improvements**:
   - Exclude instructional text that looks like fields (long sentences with specific phrases like "Ask questions", "If Yes then")
   - Exclude table row labels that are just "Row N" 
   - Exclude version stamps like "Version Number 14-Jan-2009"
   - Include checkbox-style fields that may appear as short phrases
   - Better detect wrapped multi-line field labels by checking y-distance and x-alignment

7. **Coverage**: Process all pages except true TOC and option-reference pages. Don't skip based on density.

```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Detect and skip table of contents pages
        if is_toc_page(lines):
            continue
        
        # Detect and skip answer option reference pages
        if is_option_reference_page(lines):
            continue
        
        # Look for form title: blue text, size >= 14pt
        new_title = find_form_title(lines)
        if new_title:
            current_form = new_title
        
        # Extract fields from this page
        page_fields = extract_fields_from_page(lines, page_num)
        
        # Assign current form name to all fields
        for field in page_fields:
            field['form_name'] = current_form
            results.append(field)
    
    return results


def is_toc_page(lines: List) -> bool:
    """Detect table of contents pages by numbered list pattern."""
    # TOC pages have many lines starting with pattern like "3.120." in blue
    numbered_items = 0
    for line in lines:
        if line.non_black and line.size >= 14:
            # Check for numbered list pattern: digit.digit.
            if re.match(r'^\d+\.\d+\.', line.text.strip()):
                numbered_items += 1
    
    # If we see many numbered items, it's a TOC
    return numbered_items > 10


def is_option_reference_page(lines: List) -> bool:
    """Detect pages that only list answer options (no fields)."""
    # These pages have no large blue title and consist mainly of 
    # right-aligned option text
    has_title = False
    option_lines = 0
    total_content_lines = 0
    
    for line in lines:
        text = line.text.strip()
        if not text or len(text) < 2:
            continue
        
        # Check for page numbers
        if re.match(r'^Page \d+ of \d+$', text):
            continue
        
        # Check for form title
        if line.non_black and line.size >= 14:
            has_title = True
        
        # Count content lines
        if line.size >= 8 and line.size <= 12:
            total_content_lines += 1
            # Options are typically right-aligned or centered
            if line.x0 > 300:
                option_lines += 1
    
    # If no title and mostly option-style lines, skip
    if not has_title and total_content_lines > 15 and option_lines > total_content_lines * 0.7:
        return True
    
    return False


def find_form_title(lines: List) -> str:
    """Find form title: blue text, size >= 14pt, near top half of page."""
    for line in lines:
        if line.non_black and line.size >= 14.0 and line.y0 < 400:
            text = line.text.strip()
            if text and len(text) > 3:
                # Exclude page numbers
                if not re.match(r'^Page \d+', text) and not re.match(r'^\d+$', text):
                    # Exclude TOC numbered items
                    if not re.match(r'^\d+\.\d+\.', text):
                        return text
    return ""


def extract_fields_from_page(lines: List, page_num: int) -> List[Dict]:
    """Extract field labels from a page."""
    fields = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip red annotation lines (technical codes in brackets)
        if line.non_black and '[' in line.text:
            i += 1
            continue
        
        # Skip page numbers
        if re.match(r'^Page \d+ of \d+$', line.text.strip()):
            i += 1
            continue
        
        # Skip very small or very large text
        if line.size < 7 or line.size > 13:
            i += 1
            continue
        
        # Check if this is a potential field label
        # Left-aligned (x < 150), black text, reasonable size
        if line.x0 < 150 and not line.non_black:
            text = line.text.strip()
            
            # Skip empty or very short
            if not text or len(text) < 3:
                i += 1
                continue
            
            # Skip pure punctuation
            if text in ['•', '-', ':', '–']:
                i += 1
                continue
            
            # Skip standalone answer options
            if text in ['Yes', 'No', 'N/A', 'NA', 'Unknown']:
                i += 1
                continue
            
            # Skip "Row N" labels (these are table furniture, not fields)
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip version stamps
            if re.match(r'^Version Number', text):
                i += 1
                continue
            
            # Skip right-aligned text (answer options)
            if line.x0 > 400:
                i += 1
                continue
            
            # Collect wrapped lines for this field
            field_text = text
            j = i + 1
            
            # Look ahead for continuation lines
            while j < len(lines):
                next_line = lines[j]
                
                # Stop at red annotation
                if next_line.non_black and '[' in next_line.text:
                    break
                
                # Stop at next field (similar x, black, similar size, larger y gap)
                if (next_line.x0 < 150 and not next_line.non_black and 
                    abs(next_line.size - line.size) < 2):
                    # Check y-distance from previous line
                    y_gap = next_line.y0 - lines[j-1].y0
                    if y_gap > 25:  # New field
                        break
                
                # Stop at answer options (right side)
                if next_line.x0 > 400:
                    break
                
                # Continuation line: similar x (within 40px), close y (< 20px), black
                if (abs(next_line.x0 - line.x0) < 40 and 
                    next_line.y0 - lines[j-1].y0 < 20 and 
                    not next_line.non_black and
                    next_line.size >= 7 and next_line.size <= 13):
                    cont_text = next_line.text.strip()
                    if cont_text and not cont_text.startswith('['):
                        field_text += ' ' + cont_text
                    j += 1
                else:
                    break
            
            # Clean up field text
            field_text = ' '.join(field_text.split())
            
            # Exclude instructional text (long sentences with specific patterns)
            if is_instructional_text(field_text):
                i = j
                continue
            
            # Exclude page furniture labels
            if field_text in ['Repeat Pages', 'Page Label']:
                i = j
                continue
            
            # Final validation
            if (field_text and 
                not re.match(r'^\d+$', field_text) and
                not re.match(r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$', field_text) and
                len(field_text) >= 3):
                
                fields.append({
                    'form_name': '',
                    'field_name': field_text,
                    'page': page_num
                })
            
            i = j
        else:
            i += 1
    
    return fields


def is_instructional_text(text: str) -> bool:
    """Detect instructional text that should not be extracted as fields."""
    # Long sentences with instructional keywords
    if len(text) > 100:
        instruction_patterns = [
            r'Ask questions',
            r'If both are',
            r'If the answer to',
            r'complete.*section',
            r'If Yes then please fill',
            r'When person begins',
            r'stops.*instead of being stopped'
        ]
        for pattern in instruction_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
    
    return False
```