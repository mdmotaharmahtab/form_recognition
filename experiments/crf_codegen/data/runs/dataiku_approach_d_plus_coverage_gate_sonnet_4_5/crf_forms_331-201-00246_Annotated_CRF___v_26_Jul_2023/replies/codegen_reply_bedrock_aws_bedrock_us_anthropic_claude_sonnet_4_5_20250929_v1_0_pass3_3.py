STRATEGY:

This revision addresses the false positives by focusing on structural discrimination rather than text-based filtering:

1. **Form title detection**: Identify form titles as large (size ≥ 14), bold or blue text in the upper portion of the page (y0 < 300). Carry the current form title forward across pages until a new title is detected. Handle cases where titles may be absent or positioned differently by maintaining state.

2. **Field vs. non-field discrimination**:
   - **Schedule tables**: Detect schedule pages by looking for grid-like structures with many vertical-aligned items. On these pages, extract only the actual assessment/procedure names from the leftmost column (x0 < 200), excluding visit labels, enrollment conditions, and column headers.
   - **Question forms**: On standard forms, extract fields that are left-aligned (x0 < 400), medium-sized (8-12pt), and structured as questions or labels. Skip items that are:
     - Far-right positioned (x0 > 500) - typically answer options or codes
     - Very small (size < 7) - technical annotations
     - In red/non-black small text - machine codes
     - Indented significantly (x0 > 250 on non-schedule pages) - sub-items or options
   - **Rating scale tables**: Detect by presence of column headers like "Intensity", "Lifetime", "Past 3 Month". Extract only the row labels from the leftmost column (x0 < 250), not the column headers or rating anchors.

3. **Structural patterns**:
   - Use x-position to distinguish field labels (left-aligned) from options (right or indented)
   - Use y-position clustering to identify table headers vs. content
   - Use font size to distinguish titles (large), fields (medium), and annotations (small)
   - Detect page layout type (schedule, questionnaire, rating scale) and apply appropriate extraction logic

4. **Coverage**: Process every page, extracting fields based on detected layout type. Never skip pages based on density or line count heuristics.

```python
import re
from typing import List, Dict, Tuple

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Detect form title: large, bold/blue text in upper area
        new_title = detect_form_title(lines)
        if new_title:
            current_form = new_title
        
        # Detect page layout type
        layout_type = detect_layout_type(lines)
        
        # Extract fields based on layout
        if layout_type == "schedule":
            fields = extract_schedule_fields(lines)
        elif layout_type == "rating_scale":
            fields = extract_rating_scale_fields(lines)
        else:
            fields = extract_standard_fields(lines)
        
        for field_name in fields:
            records.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return records

def detect_form_title(lines: List) -> str:
    """Detect form title: large text in upper portion"""
    for line in lines:
        text = line.text.strip()
        
        # Skip empty
        if not text:
            continue
        
        # Look for large text in upper area
        if line.y0 < 300 and line.size >= 14:
            # Skip page numbers and common headers
            if re.match(r'^(Page \d+|CHANGE HISTORY|\d+\.\d+\.).*', text):
                continue
            
            # Skip copyright and author lines
            if re.search(r'(©|Posner|Disclaimer|Version \d+\.\d+)', text):
                continue
            
            # Likely a title
            if len(text) > 3:
                return text
    
    return ""

def detect_layout_type(lines: List) -> str:
    """Determine page layout type"""
    
    # Count lines in different x-position ranges
    left_column = [ln for ln in lines if ln.x0 < 200 and not ln.text.strip().startswith('[')]
    
    # Check for schedule indicators
    schedule_keywords = ['Visit', 'Day -', 'Screening', 'Baseline', 'Follow-up', 'Titration']
    schedule_count = sum(1 for ln in lines if any(kw in ln.text for kw in schedule_keywords))
    
    if schedule_count > 10:
        return "schedule"
    
    # Check for rating scale indicators
    rating_headers = ['Intensity of Ideation', 'Lifetime', 'Past 3 Month', 'Past Month', 'Since Last Visit']
    has_rating_header = any(any(hdr in ln.text for hdr in rating_headers) for ln in lines if ln.y0 < 200)
    
    if has_rating_header:
        return "rating_scale"
    
    return "standard"

def extract_schedule_fields(lines: List) -> List[str]:
    """Extract assessment names from schedule tables"""
    fields = []
    seen = set()
    
    for line in lines:
        text = line.text.strip()
        
        # Skip empty, annotations, page numbers
        if not text or text.startswith('[') or text.startswith('('):
            continue
        if re.match(r'^Page \d+', text):
            continue
        
        # Only extract from leftmost column (assessment names)
        if line.x0 > 200:
            continue
        
        # Skip if very small (annotations)
        if line.size < 7:
            continue
        
        # Skip visit labels and column headers
        if re.match(r'^(Visit|Screen|Baseline|Day|Week|Month|Titration|Follow|Unscheduled|Schedule)', text):
            continue
        
        # Skip enrollment conditions
        if 'enrol' in text.lower() or 'if SEX' in text or 'if Protocol' in text:
            continue
        
        # Skip "Yes" and other single-word non-fields
        if text in ['Yes', 'No', 'N/A', 'NA', 'Unknown']:
            continue
        
        # Must be multi-word or substantial single word
        if len(text.split()) >= 2 or len(text) > 15:
            if text not in seen:
                fields.append(text)
                seen.add(text)
    
    return fields

def extract_rating_scale_fields(lines: List) -> List[str]:
    """Extract question labels from rating scale tables"""
    fields = []
    seen = set()
    
    # Find where content starts (after headers)
    header_y_max = 0
    for line in lines:
        if line.y0 < 250 and any(hdr in line.text for hdr in ['Intensity', 'Lifetime', 'Past', 'Since']):
            header_y_max = max(header_y_max, line.y1)
    
    for line in lines:
        text = line.text.strip()
        
        # Skip empty, annotations
        if not text or text.startswith('['):
            continue
        
        # Skip header area
        if line.y0 < header_y_max + 10:
            continue
        
        # Only extract from leftmost column (question text)
        if line.x0 > 250:
            continue
        
        # Skip small annotations
        if line.size < 7:
            continue
        
        # Skip column headers that appear in content area
        if text in ['Intensity of Ideation', 'Lifetime', 'Past 3 Month', 'Past Month', 'Since Last Visit']:
            continue
        
        # Skip rating anchors and short responses
        if re.match(r'^(definitely|probably|likely|somewhat|very|not at all|\d+)$', text, re.IGNORECASE):
            continue
        
        # Skip author names and citations
        if re.match(r'^[A-Z]\.$', text) or text in ['P.', 'J.', 'A.', 'M.']:
            continue
        
        # Must be substantial text
        if len(text) > 10 or (len(text.split()) >= 2 and len(text) > 5):
            if text not in seen:
                fields.append(text)
                seen.add(text)
    
    return fields

def extract_standard_fields(lines: List) -> List[str]:
    """Extract fields from standard questionnaire pages"""
    fields = []
    seen = set()
    
    i = 0
    while i < len(lines):
        line = lines[i]
        text = line.text.strip()
        
        # Skip empty, annotations
        if not text or text.startswith('['):
            i += 1
            continue
        
        # Skip page numbers and footers
        if line.y0 > 750 or re.match(r'^Page \d+', text):
            i += 1
            continue
        
        # Skip if too far right (likely options or codes)
        if line.x0 > 500:
            i += 1
            continue
        
        # Skip small text (annotations, codes)
        if line.size < 7:
            i += 1
            continue
        
        # Skip red/colored small text (technical codes)
        if line.non_black and line.size < 10:
            i += 1
            continue
        
        # Skip if heavily indented (sub-items, options)
        if line.x0 > 250 and not is_field_label_pattern(text):
            i += 1
            continue
        
        # Check if this looks like a field label
        if is_field_label_pattern(text):
            # Collect continuation lines
            field_text = text
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # Continue if close vertically and similar x-position
                if (next_line.y0 - line.y1 < 15 and 
                    abs(next_line.x0 - line.x0) < 30 and
                    not next_line.text.strip().startswith('[')):
                    field_text += " " + next_line.text.strip()
                    j += 1
                else:
                    break
            
            # Clean and validate
            field_text = clean_field_text(field_text)
            if field_text and len(field_text) > 3 and field_text not in seen:
                fields.append(field_text)
                seen.add(field_text)
            
            i = j
            continue
        
        i += 1
    
    return fields

def is_field_label_pattern(text: str) -> bool:
    """Check if text looks like a field label"""
    
    # Skip pure numbers or dates
    if re.match(r'^[\d\s\-\:\.\/]+$', text):
        return False
    
    # Skip very short
    if len(text) < 3:
        return False
    
    # Questions are fields
    if '?' in text:
        return True
    
    # Labels ending with colon
    if text.endswith(':') and len(text) > 5:
        return True
    
    # Multi-word phrases
    if len(text.split()) >= 3:
        return True
    
    # Two-word phrases starting with capital
    if len(text.split()) == 2 and text[0].isupper():
        return True
    
    # Single substantial words
    if len(text) > 12 and text[0].isupper():
        return True
    
    return False

def clean_field_text(text: str) -> str:
    """Clean field text"""
    # Remove annotations
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
```