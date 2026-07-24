STRATEGY:

The document contains two main layout families: "Variable details" pages (family C) that list technical metadata about form fields, and actual data-entry form pages (families D and others) that display the fields themselves. I will extract fields only from the data-entry pages, not from the metadata tables. Form titles appear in two locations: a small bold line near the top (e.g., "Demographics" at y~48) and a larger title at y~74 (size 17.4). I will use the larger, more prominent title as the form_name and carry it forward across continuation pages that lack it. Field labels on data-entry pages are bold text at size 7.8-9.6, positioned at x~44-150, followed by bracketed numbers (e.g., "[1]"). I will identify fields by this pattern: bold text in the left column with an associated bracket marker. Answer options (Yes/No, categorical choices) appear as non-bold or indented text below the field label and are excluded. Tabular layouts (like page 159) show column headers with bracket numbers; the headers themselves are fields, and I extract them once per occurrence. Pages with "Variable details" headers (family C) are metadata and skipped entirely. When a page has no large title, I carry forward the most recent form_name from prior pages. I verify each line is a field label by checking it is bold, in the field-label position range, and not a known structural element (page headers, "More rows", row numbers). Multi-line labels are joined by detecting continuation lines at similar x-positions without bracket markers.

```python
# This CRF has data-entry forms (family D) with bold field labels and bracketed IDs,
# plus metadata "Variable details" pages (family C) that we skip.
# Form titles appear as large text (~17pt) and are carried forward across pages.

import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip metadata pages (Variable details tables)
        if any(line.text == "Variable details" and line.bold for line in lines):
            continue
        
        # Look for form title: large text (size > 15) around y=70-100
        for line in lines:
            if line.size > 15 and 60 < line.y0 < 110:
                # Exclude page identifiers and generic headers
                if not re.match(r'^MAC\d+_', line.text) and line.text.strip():
                    current_form = line.text.strip()
                    break
        
        # Extract fields from data-entry pages
        fields = extract_fields_from_page(lines)
        
        for field_name in fields:
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return results

def extract_fields_from_page(lines: List) -> List[str]:
    fields = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Skip page headers, footers, and structural elements
        if line.y0 < 50 or line.y0 > 800:
            i += 1
            continue
        
        # Skip known non-field patterns
        text = line.text.strip()
        if not text or text in ["More rows: 1  5  10", "Complete for all parameters"]:
            i += 1
            continue
        
        # Skip row numbers (single digits or small numbers at far left)
        if re.match(r'^\d{1,3}$', text) and line.x0 < 50:
            i += 1
            continue
        
        # Field labels: bold, size 7-10, x position 40-400, with meaningful text
        if line.bold and 7 <= line.size <= 10 and 40 <= line.x0 <= 400:
            # Check if this looks like a field label (not a column header in a repeated position)
            # Field labels often have bracketed numbers nearby or are followed by answer options
            
            # Skip if it's just a bracketed number
            if re.match(r'^\[\d+\]$', text):
                i += 1
                continue
            
            # Skip answer options (Yes/No patterns, typically not at the leftmost position for labels)
            if text in ["Yes", "No", "Unknown", "Other"] and line.x0 > 50:
                i += 1
                continue
            
            # Skip categorical values that appear in lists
            if is_likely_answer_option(text, line, lines):
                i += 1
                continue
            
            # This is likely a field label
            field_text = text
            
            # Check for multi-line labels (continuation lines at similar x, no bracket)
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # Continuation: similar x position, no bracket marker, reasonable y gap
                if (abs(next_line.x0 - line.x0) < 20 and 
                    0 < next_line.y0 - lines[j-1].y0 < 20 and
                    not re.search(r'\[\d+\]', next_line.text) and
                    not next_line.text.strip() in ["Yes", "No"]):
                    field_text += " " + next_line.text.strip()
                    j += 1
                else:
                    break
            
            # Clean up the field name
            field_text = re.sub(r'\s*\[\d+\]\s*', '', field_text).strip()
            
            if field_text and len(field_text) > 1:
                # Additional filtering: skip if it looks like a table column header repeated many times
                # or if it's a section instruction
                if not is_structural_text(field_text):
                    fields.append(field_text)
            
            i = j if j > i + 1 else i + 1
        else:
            i += 1
    
    return fields

def is_likely_answer_option(text: str, line, all_lines: List) -> bool:
    """Check if this text is likely an answer option rather than a field label."""
    # Common answer patterns
    if text in ["Yes", "No", "Unknown", "Not Reported", "Other", "Normal", 
                "Abnormal NCS", "Abnormal CS", "Standing", "Semi-Supine"]:
        return True
    
    # Check if indented relative to nearby bold labels
    if line.x0 > 55:
        # Look for a parent label above
        for other in all_lines:
            if other.bold and other.y0 < line.y0 and abs(other.y0 - line.y0) < 50:
                if other.x0 < line.x0 - 5:
                    return True
    
    return False

def is_structural_text(text: str) -> bool:
    """Filter out structural/instructional text that isn't a field."""
    # Skip very short text
    if len(text) < 3:
        return True
    
    # Skip pure numbers or dates
    if re.match(r'^[\d\s\-/:.]+$', text):
        return True
    
    # Skip common table headers that appear in metadata
    if text in ["Name", "Export Name", "Type", "Max length", "Categories", 
                "Variable details", "Details", "Test", "Result", "Interpretation"]:
        # These are only structural in certain contexts; in forms they may be real fields
        # Use position to disambiguate if needed
        return False
    
    return False
```