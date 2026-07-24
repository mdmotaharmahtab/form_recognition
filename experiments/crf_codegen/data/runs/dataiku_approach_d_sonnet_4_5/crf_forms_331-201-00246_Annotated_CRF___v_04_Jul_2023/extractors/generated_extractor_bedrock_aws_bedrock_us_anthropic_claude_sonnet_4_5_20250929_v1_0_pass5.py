import re
from typing import List, Dict, Tuple

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip TOC pages (families A, B) - they have blue links but no data fields
        if is_toc_page(lines):
            continue
        
        # Extract form title (large blue text, typically sz >= 15)
        form_title = extract_form_title(lines)
        if form_title:
            current_form = form_title
        
        # Extract fields from this page
        page_fields = extract_fields_from_page(lines, current_form, page_num)
        records.extend(page_fields)
    
    return records


def is_toc_page(lines) -> bool:
    """Detect table of contents pages by structure."""
    # TOC pages have many blue links with section numbers like "3.1.", "3.2."
    blue_section_pattern = re.compile(r'^\d+\.\d+\.')
    blue_count = 0
    
    for line in lines:
        if line.non_black and blue_section_pattern.match(line.text.strip()):
            blue_count += 1
    
    # If we have many blue section links, it's a TOC
    return blue_count > 5


def extract_form_title(lines) -> str:
    """Extract form/section title - large blue text."""
    for line in lines:
        text = line.text.strip()
        # Form titles are typically large (sz >= 15), blue (#004c99 or similar), not red
        if (line.size >= 14.5 and line.non_black and 
            not text.startswith('[') and 
            not re.match(r'^\d+\.\d+\.', text) and  # Not TOC entry
            not text.startswith('Page ') and
            len(text) > 3):
            # Check if it's blue (not red)
            # Blue titles are in #004c99, #1d60a4, #2477cc range
            # Red codes are #ff0000, gray is #999999
            # We'll accept it if it's colored and reasonably sized
            if line.size >= 15:
                return text
    return ""


def is_eligibility_checklist_page(lines) -> bool:
    """Detect eligibility criteria checklist pages."""
    # Look for the specific instruction text and multiple INCL/EXCL codes
    has_instruction = False
    incl_excl_count = 0
    
    for line in lines:
        text = line.text.strip()
        if 'did not meet eligibility criteria' in text:
            has_instruction = True
        if re.match(r'^(INCL|EXCL)\d+$', text):
            incl_excl_count += 1
    
    return has_instruction and incl_excl_count >= 5


def extract_fields_from_page(lines, form_name: str, page_num: int) -> List[Dict]:
    """Extract field labels from a CRF page."""
    fields = []
    
    # Check if this is an eligibility checklist page
    if is_eligibility_checklist_page(lines):
        # Extract the instruction text as the field label
        for line in lines:
            text = line.text.strip()
            if 'did not meet eligibility criteria' in text:
                fields.append({
                    'form_name': form_name,
                    'field_name': text,
                    'page': page_num
                })
                break
        return fields
    
    # Regular field extraction for other pages
    i = 0
    
    while i < len(lines):
        line = lines[i]
        text = line.text.strip()
        
        # Skip if empty or too short
        if not text or len(text) < 2:
            i += 1
            continue
        
        # Skip technical codes in red (start with '[')
        if text.startswith('['):
            i += 1
            continue
        
        # Skip page numbers
        if re.match(r'^Page \d+ of \d+', text):
            i += 1
            continue
        
        # Skip table headers (specific patterns from samples)
        if text in ['Sample', 'Timepoint', 'Sample Status', 'Time of', 'Barcode', 
                    'Backup', 'Collection', 'Number', 'Barcode Number']:
            i += 1
            continue
        
        # Skip row labels like "Row 1", "Row 2"
        if re.match(r'^Row \d+$', text):
            i += 1
            continue
        
        # Skip codes like INCL1, EXCL1, etc. (standalone on a line)
        if re.match(r'^(INCL|EXCL)\d+$', text):
            i += 1
            continue
        
        # Skip gray text (often pre-filled values or examples)
        # Gray is #999999, we check for non_black but need to distinguish from red
        # Actually, we can't distinguish colors beyond non_black, so use size/position
        
        # Skip very small text (likely footnotes)
        if line.size < 8:
            i += 1
            continue
        
        # Skip colored text that's not a title (red codes, gray examples)
        # Field labels should be black
        if line.non_black and line.size < 14:
            i += 1
            continue
        
        # Skip copyright and reference text
        if '©' in text or 'Columbia' in text or 'Research Foundation' in text:
            i += 1
            continue
        
        # Skip instructional text (long sentences)
        if len(text) > 150:
            i += 1
            continue
        
        # Skip definitions and instructions starting with certain patterns
        if (text.startswith('Definitions of') or 
            text.startswith('For reprints')):
            i += 1
            continue
        
        # Skip "Scan" placeholders
        if text == 'Scan':
            i += 1
            continue
        
        # Skip answer options (Yes/No, Collected/Not Collected, etc.)
        if text in ['Yes', 'No', 'Unknown', 'Collected', 'Not', 'Not Collected']:
            i += 1
            continue
        
        # Potential field label - black text, reasonable size (9-12pt typically)
        if not line.non_black and 8.5 <= line.size <= 13:
            # Check if next line is a technical code (red, starts with '[')
            is_field = False
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                next_text = next_line.text.strip()
                # If next line is a red code, this is likely a field label
                if next_text.startswith('[') and next_line.non_black:
                    is_field = True
            
            # Also accept if it looks like a question/label (ends with colon or question mark)
            if text.endswith(':') or text.endswith('?'):
                is_field = True
            
            # Accept if it's a descriptive phrase (has multiple words, not all caps)
            if ' ' in text and not text.isupper() and len(text) > 10:
                # But not if it's instructional text
                if not any(x in text.lower() for x in ['collect', 'after', 'resting', 'position']):
                    is_field = True
            
            if is_field:
                # Collect continuation lines (same x position, similar size, black)
                field_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    # Stop at red codes
                    if next_text.startswith('['):
                        break
                    # Stop at significant position change
                    if abs(next_line.x0 - line.x0) > 5:
                        break
                    # Stop at size change
                    if abs(next_line.size - line.size) > 1:
                        break
                    # Stop if colored
                    if next_line.non_black:
                        break
                    # Stop if empty
                    if not next_text:
                        break
                    # Continuation line
                    field_text += ' ' + next_text
                    j += 1
                
                # Clean up the field text
                field_text = ' '.join(field_text.split())
                
                # Final validation - not too short, not a header
                if len(field_text) >= 5 and field_text not in ['Sample', 'Timepoint']:
                    fields.append({
                        'form_name': form_name,
                        'field_name': field_text,
                        'page': page_num
                    })
                
                i = j
                continue
        
        i += 1
    
    return fields
