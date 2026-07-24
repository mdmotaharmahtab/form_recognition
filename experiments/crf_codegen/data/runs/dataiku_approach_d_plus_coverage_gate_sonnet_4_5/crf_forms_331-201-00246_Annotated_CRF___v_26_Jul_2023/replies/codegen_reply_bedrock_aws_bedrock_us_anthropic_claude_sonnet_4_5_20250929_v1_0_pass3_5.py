STRATEGY:

This revision addresses the core problem: the program currently uses extensive literal text blocklists that only fit the sample pages seen during development. The new approach:

**Form title detection and persistence:**
- Detect form titles by structural characteristics: large text (≥14pt) in the upper portion (y0 < 300), substantial length (>3 chars)
- Exclude structural furniture: page numbers (pattern "Page N of M"), version/copyright lines, but do NOT blocklist by literal content words
- Carry forward the current form title across subsequent pages, even when the title doesn't repeat
- Reset form context only when a new large title appears

**Field vs. non-field discrimination (structural only):**
- **Position-based**: Fields appear in the main content area (y0 between header and footer bands, x0 in left/center columns)
- **Style-based**: Fields use standard text size (≥7pt for body text); very small text (<7pt) is annotations
- **Column-based**: In schedule tables, only extract from the leftmost column (assessment names); in rating scales, only from the question column (left side, x0 < 250)
- **Pattern-based structural markers**: Skip pure numeric strings, single-character entries, but NOT by matching specific words like "Yes", "No", "Intensity", etc.

**Layout-specific handling:**
- **Schedule tables**: Extract from left column below the visit header band, skip visit labels by position (in header) not by word matching
- **Rating scales**: The poorly-covered cluster 2 pages show rating scale headers ("Intensity of Ideation", "Since Last Visit"). Extract question text from the left column, below headers, ignoring the column headers themselves by position
- **Standard forms**: Extract multi-word phrases and questions from the main content area

**Coverage improvements:**
- Remove all literal word blocklists (the 37+ hardcoded strings)
- For cluster 2 (rating scales at 25% coverage): recognize that "Intensity of Ideation" and "Since Last Visit" are column headers (top area, y0 < 200), not fields; extract the actual question items below them
- Handle pages where form titles don't repeat by maintaining form context
- Use relative positioning with generous slack to handle layout variations

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
    """Detect form title by structural characteristics only"""
    for line in lines:
        text = line.text.strip()
        
        # Skip empty
        if not text:
            continue
        
        # Look for large text in upper area (structural)
        if line.y0 < 300 and line.size >= 14:
            # Skip page numbers by pattern (structural)
            if re.match(r'^Page \d+( of \d+)?$', text):
                continue
            
            # Skip version/copyright by pattern (structural)
            if re.match(r'^(Version \d+\.\d+|©|\(c\))', text, re.IGNORECASE):
                continue
            
            # Skip single initials (structural: very short with periods)
            if re.match(r'^[A-Z]\.\s*[A-Z]\.$', text):
                continue
            
            # Likely a title if substantial
            if len(text) > 3:
                return text
    
    return ""

def detect_layout_type(lines: List) -> str:
    """Determine page layout type by structural characteristics"""
    
    # Check for schedule: multiple lines in upper-left with similar x-position
    # (visit column headers)
    upper_left_count = 0
    for ln in lines:
        if ln.y0 < 250 and ln.x0 < 150:
            upper_left_count += 1
    
    if upper_left_count > 8:
        return "schedule"
    
    # Check for rating scale: multiple column headers in upper area
    # Look for horizontal spread of text in header band
    header_texts = []
    for ln in lines:
        if ln.y0 < 200 and ln.size >= 9:
            header_texts.append((ln.x0, ln.text.strip()))
    
    # If we have text spread across multiple x-positions in header, likely rating scale
    if len(header_texts) >= 2:
        x_positions = [x for x, _ in header_texts]
        if max(x_positions) - min(x_positions) > 300:
            return "rating_scale"
    
    return "standard"

def extract_schedule_fields(lines: List) -> List[str]:
    """Extract assessment names from schedule tables"""
    fields = []
    seen = set()
    
    # Find header band dynamically (where visit labels cluster)
    header_y_max = 0
    header_count = 0
    for line in lines:
        if line.y0 < 250 and line.x0 > 150:  # Right of leftmost column
            header_y_max = max(header_y_max, line.y1)
            header_count += 1
    
    # If we found header elements, set boundary
    if header_count > 5:
        header_y_max += 10
    else:
        header_y_max = 200  # Default
    
    for line in lines:
        text = line.text.strip()
        
        # Skip empty or annotations (structural: brackets/parens)
        if not text or text.startswith('[') or text.startswith('('):
            continue
        
        # Skip page numbers (structural pattern)
        if re.match(r'^Page \d+', text):
            continue
        
        # Only extract from leftmost column (structural: x-position)
        if line.x0 > 200:
            continue
        
        # Skip very small text (structural: size)
        if line.size < 7:
            continue
        
        # Skip header band (structural: position)
        if line.y0 < header_y_max:
            continue
        
        # Skip footer area (structural: position)
        if line.y0 > 750:
            continue
        
        # Skip pure numbers/codes (structural pattern)
        if re.match(r'^[\d\s\-\:\.\/]+$', text):
            continue
        
        # Skip single characters (structural: length)
        if len(text) <= 2:
            continue
        
        # Must be substantial text
        if len(text) > 3:
            if text not in seen:
                fields.append(text)
                seen.add(text)
    
    return fields

def extract_rating_scale_fields(lines: List) -> List[str]:
    """Extract question labels from rating scale tables"""
    fields = []
    seen = set()
    
    # Find header band: text in upper area with horizontal spread
    header_y_max = 0
    for line in lines:
        if line.y0 < 200 and line.size >= 9:
            header_y_max = max(header_y_max, line.y1)
    
    # Add buffer below headers
    header_y_max += 15
    
    for line in lines:
        text = line.text.strip()
        
        # Skip empty or annotations (structural)
        if not text or text.startswith('[') or text.startswith('('):
            continue
        
        # Skip page numbers (structural pattern)
        if re.match(r'^Page \d+', text):
            continue
        
        # Skip header area (structural: position)
        if line.y0 < header_y_max:
            continue
        
        # Skip footer area (structural: position)
        if line.y0 > 750:
            continue
        
        # Only extract from left column (structural: x-position)
        # Rating scales have questions on left, ratings on right
        if line.x0 > 300:
            continue
        
        # Skip small annotations (structural: size)
        if line.size < 7:
            continue
        
        # Skip pure numbers/codes (structural pattern)
        if re.match(r'^[\d\s\-\:\.\/\(\)]+$', text):
            continue
        
        # Skip single characters or very short (structural: length)
        if len(text) <= 2:
            continue
        
        # Skip colored small text (technical codes, structural: color + size)
        if line.non_black and line.size < 10:
            continue
        
        # Must be substantial text (multi-word or long single word)
        if len(text) > 8 or len(text.split()) >= 2:
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
        
        # Skip empty or annotations (structural)
        if not text or text.startswith('[') or text.startswith('('):
            i += 1
            continue
        
        # Skip page numbers and footers (structural: position or pattern)
        if line.y0 > 750 or re.match(r'^Page \d+', text):
            i += 1
            continue
        
        # Skip header area (structural: position)
        if line.y0 < 100:
            i += 1
            continue
        
        # Skip far right (structural: position - likely options/codes)
        if line.x0 > 500:
            i += 1
            continue
        
        # Skip small text (structural: size - annotations)
        if line.size < 7:
            i += 1
            continue
        
        # Skip colored small text (structural: color + size - technical codes)
        if line.non_black and line.size < 10:
            i += 1
            continue
        
        # Check if this looks like a field label (structural patterns)
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
    """Check if text looks like a field label using structural patterns only"""
    
    # Skip pure numbers/codes (structural pattern)
    if re.match(r'^[\d\s\-\:\.\/\(\)]+$', text):
        return False
    
    # Skip very short (structural: length)
    if len(text) < 3:
        return False
    
    # Questions are fields (structural: punctuation)
    if '?' in text:
        return True
    
    # Labels ending with colon (structural: punctuation)
    if text.endswith(':') and len(text) > 5:
        return True
    
    # Multi-word phrases (structural: word count)
    if len(text.split()) >= 3:
        return True
    
    # Two-word phrases starting with capital (structural: case + word count)
    if len(text.split()) == 2 and text[0].isupper() and len(text) > 8:
        return True
    
    # Single substantial words (structural: length + case)
    if len(text) > 15 and text[0].isupper():
        return True
    
    return False

def clean_field_text(text: str) -> str:
    """Clean field text"""
    # Remove annotations (structural: brackets/parens)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
```