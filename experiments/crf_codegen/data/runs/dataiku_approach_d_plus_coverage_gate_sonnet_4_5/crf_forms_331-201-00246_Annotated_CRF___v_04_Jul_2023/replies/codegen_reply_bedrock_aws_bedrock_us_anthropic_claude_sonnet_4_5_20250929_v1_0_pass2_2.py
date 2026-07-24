Looking at the sample pages, I can see they contain data-entry fields that my program is missing:

**Cluster 2 (pages 497, 793)**: These have column headers "Suicidal Behaviour" and "Since Last Visit" with a field underneath (indicated by the TYPE annotation). The field label is in the header row itself.

**Cluster 1 (pages 243, 973)**: These have table layouts with "Test" and "Result" columns. The test names (Cotinine, Methadone, Opiates, Phencyclidine, Propoxyphene) are shown in gray (#999999) text, which my program currently skips. These gray labels are actual field labels, not placeholders.

The key issues:
1. My program skips gray text (#999999), but in these layouts gray text contains the actual field labels
2. For cluster 2, the column headers themselves ARE the field names when there's only one data row
3. I need to extract gray text as field labels in table contexts

Here's the updated program:

```python
# CRF extraction: handles multiple layout families with table-based and
# question-based field structures. Tracks form titles across pages and
# extracts field labels from table rows and question text.

import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title: large colored text, typically size 16.5, color #004c99
        for line in lines:
            if line.size >= 15.0 and line.non_black and line.y0 < 300:
                # Potential form title
                text = line.text.strip()
                if text and not text.startswith('[') and len(text) > 3:
                    # Exclude technical annotations and very short text
                    if not re.match(r'^(Row \d+|Page \d+)$', text):
                        current_form = text
                        break
        
        # Extract fields based on layout patterns
        fields = extract_fields_from_page(lines, page_num)
        
        for field_name in fields:
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return results

def extract_fields_from_page(lines: list, page_num: int) -> List[str]:
    fields = []
    
    # Identify table headers (y~124, size 10.5, black, not bold typically)
    headers = []
    for line in lines:
        if 120 <= line.y0 <= 160 and line.size >= 9.5 and line.size <= 11.0:
            if not line.text.startswith('[') and line.text.strip():
                headers.append((line.x0, line.text.strip(), line.y0))
    
    # Check for special case: headers as field names (cluster 2 pattern)
    # When there are only column headers and TYPE annotations below, headers are the fields
    has_type_annotations = any('[TYPE:' in line.text for line in lines)
    gray_field_labels = [line for line in lines if line.text.strip() and not line.non_black and 
                         line.size >= 8.5 and line.size <= 10.0 and 
                         not line.text.startswith('[') and line.y0 > 140]
    
    if headers and has_type_annotations and len(gray_field_labels) == 0:
        # Cluster 2 pattern: headers are the field names
        for x, header_text, y in headers:
            if header_text not in ['Test', 'Result'] and len(header_text) > 3:
                fields.append(header_text)
    
    # Sort lines by y position for sequential processing
    sorted_lines = sorted(lines, key=lambda l: (l.y0, l.x0))
    
    # Track field candidates
    i = 0
    while i < len(sorted_lines):
        line = sorted_lines[i]
        text = line.text.strip()
        
        # Skip technical annotations, page numbers, row markers
        if text.startswith('[') or text.startswith('Page ') or re.match(r'^Row \d+$', text):
            i += 1
            continue
        
        # Skip answer options (common patterns)
        if text in ['Yes', 'No', 'Normal', 'Abnormal', 'Not Done', 'NA', 
                    'Positive', 'Negative', 'Collected', 'Not Collected',
                    'Scan', 'Not Applicable']:
            i += 1
            continue
        
        # Skip very short or numeric-only text
        if len(text) < 3 or text.isdigit():
            i += 1
            continue
        
        # Extract gray text field labels (cluster 1 pattern - test names in gray)
        # Gray text in table context is often the field label
        if not line.non_black and line.size >= 8.5 and line.size <= 10.0:
            if line.y0 > 140 and is_valid_gray_field(text):
                fields.append(text)
                i += 1
                continue
        
        # Identify field labels: non-red, non-gray, substantive text
        # Gray text (#999999) is often placeholder/example
        if not line.non_black or (line.size >= 9.0 and not text.startswith('(')):
            # Check if this is a question or label
            if is_field_label(text, line):
                # Collect continuation lines (wrapped text)
                full_text = text
                j = i + 1
                while j < len(sorted_lines):
                    next_line = sorted_lines[j]
                    next_text = next_line.text.strip()
                    
                    # Check if next line is a continuation
                    if (abs(next_line.x0 - line.x0) < 20 and 
                        next_line.y0 - line.y0 < 20 and
                        not next_text.startswith('[') and
                        not re.match(r'^(Yes|No|Row \d+)$', next_text) and
                        len(next_text) > 0):
                        # Likely continuation
                        if not next_text[0].isupper() or next_text.endswith(','):
                            full_text += ' ' + next_text
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # Clean and add field
                full_text = clean_field_name(full_text)
                if full_text and is_valid_field(full_text):
                    fields.append(full_text)
                
                i = j
                continue
        
        i += 1
    
    return fields

def is_valid_gray_field(text: str) -> bool:
    """Check if gray text is a valid field label (e.g., test names)"""
    # Must have reasonable length
    if len(text) < 3:
        return False
    
    # Should not be answer options
    if text in ['Positive', 'Negative', 'Not Done', 'Yes', 'No']:
        return False
    
    # Should contain alphabetic characters
    if not re.search(r'[a-zA-Z]{3,}', text):
        return False
    
    return True

def is_field_label(text: str, line) -> bool:
    """Determine if text is likely a field label"""
    # Must have reasonable length
    if len(text) < 5:
        return False
    
    # Should not be all caps (often headers)
    if text.isupper() and len(text) > 20:
        return False
    
    # Should contain some alphabetic characters
    if not re.search(r'[a-zA-Z]{3,}', text):
        return False
    
    # Check for question patterns
    if '?' in text or text.startswith('Have you') or text.startswith('What'):
        return True
    
    # Check for label patterns (ends with colon, contains "of", etc.)
    if text.endswith(':') or ' of ' in text.lower():
        return True
    
    # Size and position hints
    if line.size >= 9.0 and line.y0 > 150:
        return True
    
    return False

def is_valid_field(text: str) -> bool:
    """Final validation of field name"""
    # Remove common false positives
    invalid_patterns = [
        r'^Page \d+',
        r'^Row \d+$',
        r'^\d+$',
        r'^\([0-9]+\)',
        r'^VISIBILITY:',
        r'^TYPE:',
        r'^\[.*\]$'
    ]
    
    for pattern in invalid_patterns:
        if re.match(pattern, text):
            return False
    
    # Must have substantive content
    if len(text.split()) < 2 and not text.endswith('?'):
        return False
    
    return True

def clean_field_name(text: str) -> str:
    """Clean up field name text"""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove trailing punctuation except question marks
    if not text.endswith('?'):
        text = text.rstrip('.,;:')
    
    return text
```