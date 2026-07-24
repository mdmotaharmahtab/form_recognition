STRATEGY:

This revision addresses the specific page-level failures while maintaining existing coverage:

1. **Form title detection and persistence**: Continue detecting large titles (>15pt) in the upper portion, but also handle cluster 2 pages where "Visit:" and "Day N" appear as the only large text - these are valid section titles that should be combined. Carry forward the current form title across pages that lack a title (metadata pages, continuation pages).

2. **Metadata pages (cluster 0, 1)**: Already handled correctly - extract from the "Name" column. The 95% coverage issue is that some metadata pages have the Name column at a different x-position or the header detection fails. Make column detection more flexible by searching a wider y-range and allowing more x-tolerance.

3. **Data-entry pages - field vs non-field separation**:
   - **Fields to extract**: Bold text in main content area (x0 < 450, y between 50-800, size 6-11pt), excluding structural junk
   - **Options/checkboxes ("Yes No", "Negative", etc.)**: These appear as bold text but are typically very short (≤10 chars), positioned to the right of actual field labels, or appear in repeating patterns. Exclude bold text that is ≤10 characters AND appears at x > 200 (right side positioning)
   - **Table content**: Already filtered by semicolon lists, number patterns, "ID N" patterns - keep these filters
   - **Multi-word concatenated options**: Text like "American Indian or Alaska Native Asian..." is actually a run-on list of checkbox options. Detect by: contains " or " multiple times, or is very long (>80 chars) with many capital words
   - **Section headers with metadata**: Already filtered by " - Day N" and "; Performed" patterns - keep these

4. **Missing fields on specific pages**: The fields like "Informed Consent Obtained", "C-SSRS Performed", "Device Serial Number" are being skipped because they're either:
   - Not bold (need to also check non-bold text that looks like a field label by position and context)
   - Being filtered as furniture/options incorrectly
   
   Add a secondary pass: after extracting bold fields, also look for non-bold text that appears in field-label positions (left-aligned in main content, followed by whitespace or input indicators, reasonable length 10-80 chars).

5. **Cluster 2 pages (Visit/Day separator pages)**: These contain only the visit title - extract the title as the form name and carry it forward, but don't extract fields from these pages as they're pure navigation/separator pages.

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
    # Check for Visit/Day separator pages (cluster 2)
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
            # Exclude page identifiers (MAC####_...)
            if re.match(r'^MAC\d+_', text):
                continue
            # Exclude sparse separator text when alone
            if text in ["Visit:", "Day"] or re.match(r'^Day \d+$', text):
                continue
            # Valid title
            if text and len(text) > 1:
                return text
    return ""

def is_table_header_or_cell(text: str, line) -> bool:
    """Detect table headers, row labels, or cell content."""
    text = text.strip()
    
    # Pattern: "ID" followed by number (e.g., "ID 1")
    if re.search(r'\bID\s+\d+\b', text):
        return True
    
    # Semicolon-separated lists (table cells or scale anchors)
    if text.count(';') >= 2:
        return True
    
    # Multiple numbers with spaces or comparison operators (scale values)
    if re.search(r'\d+\.?\d*\s+\d+\.?\d*', text) or re.search(r'[≤≥<>]\s*\d', text):
        return True
    
    # Short concatenated words that look like table cells (e.g., "Exclusion Inclusion")
    words = text.split()
    if len(words) >= 2 and len(text) < 50:
        # Check if it's just concatenated single words (no articles/prepositions)
        if all(len(w) > 3 and w[0].isupper() for w in words):
            # Could be table row labels
            if len(words) <= 4:
                return True
    
    return False

def is_section_header_with_metadata(text: str, line) -> bool:
    """Detect section headers with embedded metadata (not field labels)."""
    text = text.strip()
    
    # Pattern: text with " - Day N" (e.g., "SDI - Day 1")
    if re.search(r'\s-\sDay\s+\d+', text):
        return True
    
    # Pattern: ends with "; Performed" or similar status indicators
    if re.search(r';\s*(Performed|Not Performed|Completed)$', text):
        return True
    
    return False

def is_option_or_checkbox_label(text: str, line) -> bool:
    """Detect answer options, checkbox labels, or rating scale anchors."""
    text = text.strip()
    
    # Very short bold text on the right side (checkboxes like "Yes No")
    if len(text) <= 10 and line.x0 > 200:
        # Common checkbox patterns
        if text in ["Yes", "No", "Yes No", "Negative", "Positive", "Normal", "Abnormal"]:
            return True
    
    # Long run-on lists of options (e.g., "American Indian or Alaska Native Asian...")
    if len(text) > 80:
        # Multiple " or " suggests concatenated options
        if text.count(" or ") >= 2:
            return True
        # Many capitalized words in a row
        words = text.split()
        if len(words) > 10 and sum(1 for w in words if w and w[0].isupper()) > 8:
            return True
    
    # Scale anchors or rating labels (e.g., "Lifetime", "Past 60 Months")
    # These are typically short and appear in table-like structures
    if len(text) < 30 and line.x0 > 150:
        # Contains time periods or scale descriptors
        if re.search(r'\b(Lifetime|Past|Months|Days|Weeks|Years)\b', text):
            return True
        # Numbered items in a list (e.g., "1. Wish to be Dead")
        if re.match(r'^\d+\.', text):
            return True
    
    return False

def is_recurring_furniture(text: str, line) -> bool:
    """Detect recurring page furniture by structural position."""
    text = text.strip()
    
    # Far right column (x > 500) - likely a repeated template element
    if line.x0 > 500:
        # Short phrases in this area are often furniture
        if len(text) < 30:
            return True
    
    return False

def extract_fields_from_page(lines: List) -> List[str]:
    """Extract field labels from any page type."""
    fields = []
    
    # Check if this is a metadata page
    is_metadata = any(line.text.strip() == "Variable details" and line.bold for line in lines)
    
    # Check if this is a separator page (only Visit/Day text)
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
    
    # Find the "Name" column header - search more broadly
    name_col_x = None
    for line in lines:
        text = line.text.strip()
        if text == "Name" and line.bold and 50 < line.y0 < 120:
            name_col_x = line.x0
            break
    
    if name_col_x is None:
        return fields
    
    # Extract field names from the Name column
    for line in lines:
        # Skip bold headers and bracketed IDs
        if line.bold or re.match(r'^\[\d+\]$', line.text.strip()):
            continue
        
        # Check if in Name column (more tolerance)
        if abs(line.x0 - name_col_x) < 25:
            text = line.text.strip()
            if text and len(text) > 2:
                # Skip column header values (structural: they appear near the top)
                if line.y0 < 100:
                    continue
                fields.append(text)
    
    return fields

def extract_fields_from_data_entry(lines: List) -> List[str]:
    """Extract field labels from data-entry form pages."""
    fields = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Skip header and footer zones
        if line.y0 < 50 or line.y0 > 800:
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
        
        # Skip standalone numbers at far left (row numbers)
        if re.match(r'^\d{1,3}$', text) and line.x0 < 50:
            i += 1
            continue
        
        # Primary: Field labels are bold, reasonable size, in main content area
        if line.bold and 6 <= line.size <= 11 and line.x0 < 450:
            # Skip page identifiers
            if re.match(r'^MAC\d+_', text):
                i += 1
                continue
            
            # Skip table headers/cells
            if is_table_header_or_cell(text, line):
                i += 1
                continue
            
            # Skip section headers with metadata
            if is_section_header_with_metadata(text, line):
                i += 1
                continue
            
            # Skip options/checkboxes
            if is_option_or_checkbox_label(text, line):
                i += 1
                continue
            
            # Skip recurring furniture
            if is_recurring_furniture(text, line):
                i += 1
                continue
            
            # This is a field label - collect multi-line continuations
            field_text = text
            j = i + 1
            
            while j < len(lines):
                next_line = lines[j]
                # Continuation: similar x, close y, not a new field
                if (abs(next_line.x0 - line.x0) < 20 and 
                    0 < next_line.y0 - lines[j-1].y0 < 20 and
                    not re.match(r'^\[\d+\]$', next_line.text.strip())):
                    # Stop if next is bold (new field) or far indented (option)
                    if next_line.bold or next_line.x0 > line.x0 + 30:
                        break
                    field_text += " " + next_line.text.strip()
                    j += 1
                else:
                    break
            
            # Clean embedded bracketed IDs
            field_text = re.sub(r'\s*\[\d+\]\s*', ' ', field_text).strip()
            
            # Final validation
            if field_text and len(field_text) > 1:
                fields.append(field_text)
            
            i = j if j > i + 1 else i + 1
        
        # Secondary: Non-bold field labels (for fields missed by bold-only filter)
        elif (not line.bold and 6 <= line.size <= 11 and 
              40 < line.x0 < 300 and len(text) >= 10 and len(text) <= 80):
            # Must look like a field label: starts with capital, contains spaces
            if text[0].isupper() and ' ' in text:
                # Not a table cell or option
                if not is_table_header_or_cell(text, line):
                    if not is_option_or_checkbox_label(text, line):
                        if not is_section_header_with_metadata(text, line):
                            # Check if followed by input space (next line is far right or much lower)
                            is_field = False
                            if i + 1 < len(lines):
                                next_line = lines[i + 1]
                                # Next element is far to the right or much lower
                                if next_line.x0 > line.x0 + 100 or next_line.y0 > line.y0 + 15:
                                    is_field = True
                            else:
                                is_field = True
                            
                            if is_field:
                                fields.append(text)
            i += 1
        else:
            i += 1
    
    return fields
```