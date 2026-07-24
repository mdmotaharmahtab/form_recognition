STRATEGY:

This revision addresses the specific failures while maintaining existing coverage:

1. **Form title detection**: Continue carrying forward the current form title across pages. For cluster 2 separator pages (Visit:/Day N), these are correctly identified and skipped. For metadata pages (cluster 0), the form title comes from the preceding data-entry page. The title detection already works for most pages; no major changes needed.

2. **Metadata pages (cluster 0)**: These "Variable details" pages are being extracted but the column detection is too strict. The "Name" column header search needs to be more flexible in y-position (currently 50-120, but should allow wider range). Also, the field extraction is filtering out valid entries by checking y0 < 100, which may be too restrictive.

3. **Data-entry field extraction improvements**:
   - **Missing fields on page 2, 6, 8, 12, 134, 470, 550**: These are likely non-bold fields or fields with specific structural patterns that the current secondary filter misses. The secondary filter requires text length >= 10, but some valid fields are shorter (e.g., "Test", "Performed"). Also, the "followed by input space" heuristic may be too strict.
   - **False positives (Yes No, option lists, table cells)**: The current filters catch many of these, but need refinement:
     - "Yes No" appears at various x-positions and should be excluded when it's a standalone pair of checkbox labels
     - Long concatenated option lists (race categories) need better detection
     - Table headers like "Inclusion / Exclusion Criteria ID 1 Exclusion" contain structural markers (ID + number pattern)
     - Scale values and interpretations (pH, Glucose, etc.) are in specific x-ranges and have characteristic patterns

4. **Structural discrimination**:
   - Field labels: typically x0 < 300, size 6-11pt, in content area (y0: 50-750)
   - Options/checkboxes: often x0 > 300 or very short text in right columns
   - Table cells: contain patterns like "ID \d+", semicolon lists, numeric ranges, interpretation keywords
   - Remove hardcoded string blocklists; use position and pattern instead

5. **Coverage**: Ensure all content pages are processed, including those with non-bold fields or unusual layouts.

```python
import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Try to detect a new form title on this page
        new_form = detect_form_title(lines)
        if new_form:
            current_form = new_form
        
        # Extract fields from this page
        fields = extract_fields_from_page(lines)
        
        for field_name in fields:
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return results

def detect_form_title(lines: List) -> str:
    """Detect form title: large text in upper portion of page."""
    # Check for Visit/Day separator pages
    visit_text = ""
    day_text = ""
    for line in lines:
        if line.size > 15:
            text = line.text.strip()
            if text == "Visit:":
                visit_text = text
            elif text.startswith("Day "):
                day_text = text
    
    if visit_text and day_text:
        return f"{visit_text} {day_text}"
    
    # Standard form title detection
    for line in lines:
        # Form titles are large (>15pt) and in upper area
        if line.size > 15 and 60 < line.y0 < 110:
            text = line.text.strip()
            # Exclude page identifiers
            if re.match(r'^MAC\d+_', text):
                continue
            # Exclude sparse separator text when alone
            if text in ["Visit:", "Day"] or re.match(r'^Day \d+$', text):
                continue
            # Valid title
            if text and len(text) > 1:
                return text
    return ""

def is_checkbox_pair(text: str, line) -> bool:
    """Detect standalone Yes/No checkbox pairs."""
    text = text.strip()
    # Exact matches for common checkbox pairs
    if text in ["Yes No", "No Yes"]:
        return True
    # Two short words that are common checkbox values
    words = text.split()
    if len(words) == 2:
        checkbox_words = {"Yes", "No", "Negative", "Positive", "Normal", "Abnormal", "True", "False"}
        if all(w in checkbox_words for w in words):
            return True
    return False

def is_table_content(text: str, line) -> bool:
    """Detect table headers, cells, or structured data."""
    text = text.strip()
    
    # Pattern: "ID" followed by number (table row identifier)
    if re.search(r'\bID\s+\d+\b', text):
        return True
    
    # Semicolon-separated lists (table cells or scale anchors)
    if text.count(';') >= 2:
        return True
    
    # Multiple numbers with spaces (scale values, ranges)
    if re.search(r'\d+\.?\d*\s+\d+\.?\d*', text):
        return True
    
    # Comparison operators with numbers (e.g., "≤ 5")
    if re.search(r'[≤≥<>]\s*\d', text):
        return True
    
    # "Interpretation" keyword (table column content)
    if "Interpretation" in text and len(text) < 40:
        return True
    
    # Short text in far-right area (likely table cell or checkbox)
    if line.x0 > 400 and len(text) < 20:
        return True
    
    # Concatenated capitalized words without articles (table row labels)
    words = text.split()
    if len(words) >= 3 and len(words) <= 6 and len(text) < 80:
        if all(len(w) > 2 and w[0].isupper() for w in words):
            # Check if it looks like a list of categories
            if any(w in ["Inclusion", "Exclusion", "Criteria"] for w in words):
                return True
    
    return False

def is_option_list(text: str, line) -> bool:
    """Detect answer option lists or rating scale anchors."""
    text = text.strip()
    
    # Very long text with multiple "or" (concatenated options)
    if len(text) > 80 and text.count(" or ") >= 2:
        return True
    
    # Many capitalized words in a row (race/ethnicity options)
    words = text.split()
    if len(words) > 10:
        cap_count = sum(1 for w in words if w and w[0].isupper())
        if cap_count > 8:
            return True
    
    # Time period descriptors in right area (scale anchors)
    if line.x0 > 200 and len(text) < 30:
        if re.search(r'\b(Lifetime|Past|Months|Days|Weeks|Years)\b', text):
            return True
    
    # Numbered list items (e.g., "1. Description")
    if re.match(r'^\d+\.', text):
        return True
    
    # Common single-word options in right area
    if line.x0 > 300 and len(text) < 15:
        option_words = {"Yes", "No", "Negative", "Positive", "Normal", "Abnormal", 
                       "Trace", "None", "Mild", "Moderate", "Severe"}
        if text in option_words:
            return True
    
    return False

def is_section_metadata(text: str, line) -> bool:
    """Detect section headers with embedded metadata."""
    text = text.strip()
    
    # Pattern: text with " - Day N"
    if re.search(r'\s-\sDay\s+\d+', text):
        return True
    
    # Pattern: ends with status indicators
    if re.search(r';\s*(Performed|Not Performed|Completed|Pending)$', text):
        return True
    
    return False

def is_descriptive_prompt(text: str, line) -> bool:
    """Detect descriptive prompts that are not field labels."""
    text = text.strip()
    
    # "If yes, describe:" type prompts
    if re.match(r'^If\s+(yes|no),?\s+', text, re.IGNORECASE):
        return True
    
    # Standalone "Yes" or "No" (not a field label)
    if text in ["Yes", "No"] and line.x0 > 200:
        return True
    
    # "Description of..." headers
    if text.startswith("Description of") and len(text) < 40:
        return True
    
    # "Type #" pattern
    if re.match(r'^Type\s+#', text):
        return True
    
    return False

def is_scale_header(text: str, line) -> bool:
    """Detect scale or rating headers."""
    text = text.strip()
    
    # All caps short phrases (scale section headers)
    if text.isupper() and 10 < len(text) < 50:
        if any(word in text for word in ["INTENSITY", "SEVERITY", "FREQUENCY", "RATING"]):
            return True
    
    return False

def extract_fields_from_page(lines: List) -> List[str]:
    """Extract field labels from any page type."""
    # Check page type
    is_metadata = any(line.text.strip() == "Variable details" and line.bold for line in lines)
    
    is_separator = all(
        line.size > 15 or line.text.strip() in ["", "Visit:", "Day"] or 
        re.match(r'^(Day \d+|MAC\d+_)', line.text.strip())
        for line in lines
    )
    
    if is_separator:
        return []
    elif is_metadata:
        return extract_fields_from_metadata(lines)
    else:
        return extract_fields_from_data_entry(lines)

def extract_fields_from_metadata(lines: List) -> List[str]:
    """Extract field names from Variable details metadata pages."""
    fields = []
    
    # Find the "Name" column header - search broadly
    name_col_x = None
    for line in lines:
        text = line.text.strip()
        if text == "Name" and line.bold:
            name_col_x = line.x0
            break
    
    if name_col_x is None:
        return fields
    
    # Extract field names from the Name column
    for line in lines:
        # Skip bold headers and bracketed IDs
        if line.bold or re.match(r'^\[\d+\]$', line.text.strip()):
            continue
        
        # Check if in Name column (with tolerance)
        if abs(line.x0 - name_col_x) < 25:
            text = line.text.strip()
            if text and len(text) > 2:
                fields.append(text)
    
    return fields

def extract_fields_from_data_entry(lines: List) -> List[str]:
    """Extract field labels from data-entry form pages."""
    fields = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Skip header and footer zones
        if line.y0 < 50 or line.y0 > 750:
            i += 1
            continue
        
        text = line.text.strip()
        if not text:
            i += 1
            continue
        
        # Skip bracketed IDs
        if re.match(r'^\[\d+\]$', text):
            i += 1
            continue
        
        # Skip standalone row numbers at far left
        if re.match(r'^\d{1,3}$', text) and line.x0 < 50:
            i += 1
            continue
        
        # Skip page identifiers
        if re.match(r'^MAC\d+_', text):
            i += 1
            continue
        
        # Primary: Bold field labels
        if line.bold and 6 <= line.size <= 11 and line.x0 < 350:
            # Apply structural filters
            if is_checkbox_pair(text, line):
                i += 1
                continue
            if is_table_content(text, line):
                i += 1
                continue
            if is_option_list(text, line):
                i += 1
                continue
            if is_section_metadata(text, line):
                i += 1
                continue
            if is_descriptive_prompt(text, line):
                i += 1
                continue
            if is_scale_header(text, line):
                i += 1
                continue
            
            # Collect multi-line continuations
            field_text = text
            j = i + 1
            
            while j < len(lines):
                next_line = lines[j]
                if (abs(next_line.x0 - line.x0) < 20 and 
                    0 < next_line.y0 - lines[j-1].y0 < 20 and
                    not re.match(r'^\[\d+\]$', next_line.text.strip())):
                    if next_line.bold or next_line.x0 > line.x0 + 30:
                        break
                    field_text += " " + next_line.text.strip()
                    j += 1
                else:
                    break
            
            # Clean embedded bracketed IDs
            field_text = re.sub(r'\s*\[\d+\]\s*', ' ', field_text).strip()
            
            if field_text and len(field_text) > 1:
                fields.append(field_text)
            
            i = j if j > i + 1 else i + 1
        
        # Secondary: Non-bold field labels
        elif (not line.bold and 6 <= line.size <= 11 and 
              40 < line.x0 < 300):
            # Must look like a field label
            if len(text) >= 3 and (text[0].isupper() or text[0].isdigit()):
                # Apply structural filters
                if is_checkbox_pair(text, line):
                    i += 1
                    continue
                if is_table_content(text, line):
                    i += 1
                    continue
                if is_option_list(text, line):
                    i += 1
                    continue
                if is_section_metadata(text, line):
                    i += 1
                    continue
                if is_descriptive_prompt(text, line):
                    i += 1
                    continue
                if is_scale_header(text, line):
                    i += 1
                    continue
                
                # Additional validation: should have some word characters
                if re.search(r'[A-Za-z]{3,}', text):
                    fields.append(text)
            
            i += 1
        else:
            i += 1
    
    return fields
```