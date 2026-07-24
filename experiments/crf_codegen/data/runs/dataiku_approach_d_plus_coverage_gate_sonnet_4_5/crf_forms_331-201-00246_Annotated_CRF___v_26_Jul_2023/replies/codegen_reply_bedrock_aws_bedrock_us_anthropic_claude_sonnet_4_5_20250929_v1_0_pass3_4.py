STRATEGY:

This revision addresses the core problem: the program was using hardcoded text blocklists that only fit the sample pages seen during development. The poorly-covered cluster 2 pages (25% coverage) show rating scale tables with "Intensity of Ideation" and "Since Last Visit" headers - the same layout type the program claims to handle, but with different question text that wasn't in the blocklist.

**Form title handling:** Carry forward the most recent large-text title found in the upper portion of any page (y0 < 300, size >= 14). When no new title appears, use the previous form_name. Skip only structural markers (page numbers matching "Page \d+ of \d+", version/copyright lines by pattern, not by literal text).

**Field vs. furniture separation (structural, not textual):**
- **Column position:** Rating scale questions are in the leftmost column (x0 < 250). Column headers and rating anchors appear further right or in the header band (y0 < header_y_max).
- **Size and style:** Skip very small text (size < 7) which marks annotations. Skip red/colored text in small sizes (technical codes).
- **Vertical zones:** Identify the header band dynamically by finding where column header keywords appear, then extract only below that band.
- **Pattern-based, not word-based:** A line is a field label if it's substantial (multi-word or long), in the content column, and not a pure number/date. Remove all hardcoded word blocklists.

**Coverage of every layout:**
- **Schedule tables:** Extract from leftmost column (x0 < 200), skip visit/column headers by position (y0 in header band) and pattern (starts with "Visit", "Screen", "Day", "Week", "Month"), not by exhaustive word lists.
- **Rating scales:** Extract from leftmost column (x0 < 250), below the header band. The sample shows these pages have the same structure as before but different question text.
- **Standard forms:** Extract field labels by position (x0 < 400 for main content), size (>= 7), and pattern (questions, multi-word phrases, colon-ending labels).

The key fix: replace all "if text in [long list]" and "if any(word in text for word in [list])" checks with structural checks on x0, y0, size, and simple regex patterns that generalize across all instances of that layout.

```python
import re
from typing import List, Dict, Tuple

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Detect form title: large text in upper area
        new_title = detect_form_title(lines)
        if new_title:
            current_form = new_title
        
        # Skip if no form context yet
        if not current_form:
            continue
        
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
            # Skip page numbers (structural pattern)
            if re.match(r'^Page \d+( of \d+)?$', text):
                continue
            
            # Skip version/copyright lines (structural pattern)
            if re.match(r'^(Version \d+\.\d+|©|\(c\)|Disclaimer)', text, re.IGNORECASE):
                continue
            
            # Skip author initials pattern
            if re.match(r'^[A-Z]\.\s*[A-Z]\.', text):
                continue
            
            # Skip change history headers
            if text.upper() in ['CHANGE HISTORY', 'REVISION HISTORY']:
                continue
            
            # Likely a title if substantial
            if len(text) > 3:
                return text
    
    return ""

def detect_layout_type(lines: List) -> str:
    """Determine page layout type by structure"""
    
    # Check for schedule indicators: multiple lines with visit-related patterns
    visit_pattern_count = 0
    for ln in lines:
        # Visit labels typically start with these patterns
        if re.match(r'^(Visit|Screen|Baseline|Day|Week|Month|Titration|Follow)', ln.text.strip()):
            visit_pattern_count += 1
    
    if visit_pattern_count > 8:
        return "schedule"
    
    # Check for rating scale: header keywords in upper area
    rating_header_keywords = ['Intensity', 'Lifetime', 'Past', 'Since Last Visit']
    has_rating_header = False
    for ln in lines:
        if ln.y0 < 200:
            if any(kw in ln.text for kw in rating_header_keywords):
                has_rating_header = True
                break
    
    if has_rating_header:
        return "rating_scale"
    
    return "standard"

def extract_schedule_fields(lines: List) -> List[str]:
    """Extract assessment names from schedule tables"""
    fields = []
    seen = set()
    
    # Find header band (where visit labels appear)
    header_y_max = 0
    for line in lines:
        if line.y0 < 250 and re.match(r'^(Visit|Screen|Baseline|Day|Week|Month)', line.text.strip()):
            header_y_max = max(header_y_max, line.y1)
    
    for line in lines:
        text = line.text.strip()
        
        # Skip empty, annotations
        if not text or text.startswith('[') or text.startswith('('):
            continue
        
        # Skip page numbers
        if re.match(r'^Page \d+', text):
            continue
        
        # Only extract from leftmost column (assessment names)
        if line.x0 > 200:
            continue
        
        # Skip if very small (annotations)
        if line.size < 7:
            continue
        
        # Skip header band
        if line.y0 < header_y_max + 5:
            continue
        
        # Skip visit/column header patterns
        if re.match(r'^(Visit|Screen|Baseline|Day|Week|Month|Titration|Follow|Unscheduled|Schedule)', text):
            continue
        
        # Skip enrollment condition patterns (structural: starts with "if" or "page enrols")
        if re.match(r'^(if |page enrol)', text, re.IGNORECASE):
            continue
        
        # Skip single-word non-substantive entries
        if len(text.split()) == 1 and len(text) < 15:
            if text in ['Yes', 'No', 'NA', 'N/A', 'Unknown', 'Male', 'Female']:
                continue
        
        # Must be multi-word or substantial
        if len(text.split()) >= 2 or len(text) > 15:
            if text not in seen:
                fields.append(text)
                seen.add(text)
    
    return fields

def extract_rating_scale_fields(lines: List) -> List[str]:
    """Extract question labels from rating scale tables"""
    fields = []
    seen = set()
    
    # Find header band dynamically
    header_y_max = 0
    for line in lines:
        if line.y0 < 250:
            # Look for column header patterns
            if re.search(r'(Intensity|Lifetime|Past|Since)', line.text):
                header_y_max = max(header_y_max, line.y1)
    
    for line in lines:
        text = line.text.strip()
        
        # Skip empty, annotations
        if not text or text.startswith('[') or text.startswith('('):
            continue
        
        # Skip page numbers
        if re.match(r'^Page \d+', text):
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
        
        # Skip pure numbers, dates, codes
        if re.match(r'^[\d\s\-\:\.\/\(\)]+$', text):
            continue
        
        # Skip single-word rating anchors (structural: single word, short)
        if len(text.split()) == 1 and len(text) < 12:
            continue
        
        # Skip author initial patterns
        if re.match(r'^[A-Z]\.$', text):
            continue
        
        # Must be substantial text (multi-word or long)
        if len(text) > 10 or len(text.split()) >= 2:
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
        if not text or text.startswith('[') or text.startswith('('):
            i += 1
            continue
        
        # Skip page numbers and footers (structural: bottom area or pattern)
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
        
        # Check if this looks like a field label
        if is_field_label_pattern(text):
            # Collect continuation lines
            field_text = text
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                next_text = next_line.text.strip()
                
                # Continue if close vertically, similar x-position, and not a new field
                if (next_line.y0 - line.y1 < 15 and 
                    abs(next_line.x0 - line.x0) < 30 and
                    not next_text.startswith('[') and
                    not next_text.startswith('(') and
                    not is_field_label_pattern(next_text)):
                    field_text += " " + next_text
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
    """Check if text looks like a field label (structural patterns)"""
    
    # Skip pure numbers, dates, codes
    if re.match(r'^[\d\s\-\:\.\/\(\)]+$', text):
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
    
    # Multi-word phrases (3+ words)
    if len(text.split()) >= 3:
        return True
    
    # Two-word phrases starting with capital
    if len(text.split()) == 2 and text[0].isupper() and len(text) > 8:
        return True
    
    # Single substantial words
    if len(text) > 15 and text[0].isupper():
        return True
    
    return False

def clean_field_text(text: str) -> str:
    """Clean field text"""
    # Remove annotations
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
```