```python
# This CRF document contains multiple layout families:
# - Family A: Table of contents / index page
# - Family B: Continuation of table of contents
# - Family C & D: Laboratory results review forms with enumeration lists and comment fields
# - Family E: Criteria/assessment forms with row-based questions and response options
# Strategy: Extract field labels from each layout by identifying question text and labels,
# excluding machine codes (in brackets), answer options, and page furniture.

import re
from typing import List, Dict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from the page (typically large, colored text near top)
        form_name = extract_form_name(lines)
        
        # Identify layout family and extract fields accordingly
        if is_toc_page(lines):
            # Table of contents - no data entry fields
            continue
        elif is_lab_results_page(lines):
            # Laboratory results review pages (families C & D)
            results.extend(extract_lab_fields(lines, form_name, page_num))
        elif is_criteria_page(lines):
            # Criteria/assessment pages (family E)
            results.extend(extract_criteria_fields(lines, form_name, page_num))
        else:
            # Generic extraction for other pages
            results.extend(extract_generic_fields(lines, form_name, page_num))
    
    return results

def extract_form_name(lines):
    """Extract the form/section title from the page."""
    # Look for large colored text near the top (typically form titles)
    for line in lines[:20]:  # Check first 20 lines
        if line.size >= 13 and line.non_black and line.y0 < 150:
            # Skip if it looks like a machine code
            if not re.match(r'^\[.*\]$', line.text):
                return line.text.strip()
    return ""

def is_toc_page(lines):
    """Check if this is a table of contents page."""
    # TOC pages have many numbered section links
    toc_pattern_count = sum(1 for line in lines if re.match(r'^\d+\.\d+\.', line.text))
    return toc_pattern_count > 10

def is_lab_results_page(lines):
    """Check if this is a laboratory results review page."""
    # Lab pages have specific patterns like "clinically significant abnormal"
    for line in lines[:10]:
        if 'clinically significant abnormal' in line.text.lower():
            return True
    return False

def is_criteria_page(lines):
    """Check if this is a criteria/assessment page (family E)."""
    # Criteria pages have "Row" labels and Met/Not Met columns
    has_row_labels = any('Row' in line.text and line.bold for line in lines[:30])
    has_met_notmet = any('Met' in line.text and 'Not Met' in line.text for line in lines[:30])
    return has_row_labels or has_met_notmet

def extract_lab_fields(lines, form_name, page_num):
    """Extract fields from laboratory results pages."""
    results = []
    
    # Look for field labels (non-code, non-option text)
    for i, line in enumerate(lines):
        text = line.text.strip()
        
        # Skip machine codes
        if re.match(r'^\[.*\]$', text):
            continue
        
        # Skip answer options (Yes/No/N/A, Positive/Negative)
        if text in ['Yes', 'No', 'N/A', 'Positive', 'Negative', 'Met', 'Not Met']:
            continue
        
        # Skip TYPE/VISIBILITY annotations
        if text.startswith('[TYPE:') or text.startswith('[VISIBILITY:'):
            continue
        
        # Look for question-like text (ends with ?)
        if text.endswith('?') and line.size >= 7 and line.size <= 10:
            # Join with next line if it's a continuation
            full_text = text
            if i + 1 < len(lines) and not lines[i+1].text.startswith('['):
                next_text = lines[i+1].text.strip()
                if not next_text.endswith('?') and len(next_text) > 0:
                    if not next_text in ['Yes', 'No', 'N/A']:
                        full_text = text + ' ' + next_text
            
            results.append({
                'form_name': form_name,
                'field_name': full_text,
                'page': page_num
            })
        
        # Look for field labels (specific patterns)
        elif 'abnormal assay #' in text.lower():
            results.append({
                'form_name': form_name,
                'field_name': text,
                'page': page_num
            })
        elif 'Investigator comment' in text:
            results.append({
                'form_name': form_name,
                'field_name': text,
                'page': page_num
            })
        elif text.startswith('Result of'):
            results.append({
                'form_name': form_name,
                'field_name': text,
                'page': page_num
            })
    
    return results

def extract_criteria_fields(lines, form_name, page_num):
    """Extract fields from criteria/assessment pages."""
    results = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        text = line.text.strip()
        
        # Skip machine codes
        if re.match(r'^\[.*\]$', text):
            i += 1
            continue
        
        # Skip answer options
        if text in ['Yes', 'No', 'N/A', 'Met', 'Not Met']:
            i += 1
            continue
        
        # Skip Row labels
        if re.match(r'^Row \d+$', text):
            i += 1
            continue
        
        # Look for questions or field labels
        if text.endswith('?') and line.size >= 7 and line.size <= 10:
            # Collect multi-line question
            full_text = text
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                next_text = next_line.text.strip()
                
                # Stop at machine codes or answer options
                if re.match(r'^\[.*\]$', next_text):
                    break
                if next_text in ['Yes', 'No', 'N/A', 'Met', 'Not Met']:
                    break
                if next_line.size > 10:  # Different section
                    break
                if next_line.y0 - line.y0 > 50:  # Too far apart
                    break
                
                # Continue if it's a continuation line
                if next_line.bold == line.bold and abs(next_line.size - line.size) < 1:
                    full_text += ' ' + next_text
                    j += 1
                else:
                    break
            
            results.append({
                'form_name': form_name,
                'field_name': full_text,
                'page': page_num
            })
            i = j
        
        # Look for field labels without question marks
        elif line.bold and line.size >= 7 and line.size <= 10:
            # Skip if it's just a row label or section header
            if not re.match(r'^Row \d+$', text) and len(text) > 3:
                # Check if it's a real field label (not just formatting)
                if not text.startswith('If ') or text.endswith(':'):
                    # Collect multi-line label
                    full_text = text
                    j = i + 1
                    while j < len(lines) and j < i + 5:
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        if re.match(r'^\[.*\]$', next_text):
                            break
                        if next_text in ['Yes', 'No', 'N/A', 'Met', 'Not Met']:
                            break
                        
                        if next_line.bold and abs(next_line.size - line.size) < 1:
                            if next_line.y0 - lines[j-1].y0 < 20:
                                full_text += ' ' + next_text
                                j += 1
                            else:
                                break
                        else:
                            break
                    
                    # Only add if it looks like a real field
                    if len(full_text) > 10 or full_text.endswith(':'):
                        results.append({
                            'form_name': form_name,
                            'field_name': full_text,
                            'page': page_num
                        })
                    i = j
                else:
                    i += 1
            else:
                i += 1
        else:
            i += 1
    
    return results

def extract_generic_fields(lines, form_name, page_num):
    """Generic field extraction for other page types."""
    results = []
    
    for i, line in enumerate(lines):
        text = line.text.strip()
        
        # Skip machine codes
        if re.match(r'^\[.*\]$', text):
            continue
        
        # Skip answer options
        if text in ['Yes', 'No', 'N/A', 'Positive', 'Negative', 'Met', 'Not Met']:
            continue
        
        # Look for questions
        if text.endswith('?') and line.size >= 7 and line.size <= 11:
            results.append({
                'form_name': form_name,
                'field_name': text,
                'page': page_num
            })
        
        # Look for field labels (text followed by machine code)
        elif line.size >= 7 and line.size <= 10 and not line.non_black:
            # Check if next line is a machine code
            if i + 1 < len(lines):
                next_text = lines[i+1].text.strip()
                if re.match(r'^\[.*\]$', next_text):
                    # This is likely a field label
                    if len(text) > 3 and not text.startswith('Row'):
                        results.append({
                            'form_name': form_name,
                            'field_name': text,
                            'page': page_num
                        })
    
    return results
```