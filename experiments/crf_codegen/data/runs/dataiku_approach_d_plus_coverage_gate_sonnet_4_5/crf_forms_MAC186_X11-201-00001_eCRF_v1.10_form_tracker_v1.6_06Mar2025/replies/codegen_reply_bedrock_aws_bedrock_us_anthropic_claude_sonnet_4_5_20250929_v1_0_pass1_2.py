STRATEGY:

This document has three layout families:

1. **Cluster 1 (336 pages, currently 98% covered)**: Data-entry forms with bold field labels, bracketed IDs, and large form titles. These are working well but missing some fields because the current program is too aggressive in filtering out answer options and has hardcoded text blocklists.

2. **Cluster 0 (387 pages, currently 0% covered)**: "Variable details" metadata pages showing field definitions in a tabular format. These have "Variable details" as a bold header and contain columns like "Name", "Export Name", "Type", etc. The Name column (starting around x=80) contains the actual field labels we need to extract. These are NOT junk pages - they define the fields for their associated forms.

3. **Cluster 2 (18 pages, 0% covered)**: Visit separator pages with just "Visit:" and a day number in large text. These are genuinely non-content pages.

The fix:
- **Form title tracking**: Continue carrying forward form titles across pages. For cluster 0 metadata pages, the form title appears on the preceding data-entry page, so we maintain it.
- **Cluster 1 (data-entry forms)**: Remove all hardcoded text blocklists. Instead, identify fields structurally: bold text in the 7-10pt range, positioned in the left column (x < 400), excluding only bracketed IDs by pattern. Don't filter by specific words like "Yes", "No", etc. - let position and style do the work.
- **Cluster 0 (metadata pages)**: Extract field names from the "Name" column (x position around 80-230). These lines are NOT bold but appear in a consistent column after the "Name" header.
- **Cluster 2 (visit separators)**: Skip pages that only contain "Visit:" and day numbers (very sparse, large text only).

The key insight: we were skipping metadata pages entirely, but they contain field definitions. We were also over-filtering data-entry pages with word blocklists. Both need structural rules instead.

```python
import re
from typing import List, Dict, Tuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Detect page type
        page_type = classify_page(lines)
        
        if page_type == "visit_separator":
            # Skip visit separator pages (just "Visit:" and day number)
            continue
        
        # Look for form title: large text (size > 15) in upper portion
        for line in lines:
            if line.size > 15 and 60 < line.y0 < 110:
                # Exclude page identifiers
                if not re.match(r'^MAC\d+_', line.text) and line.text.strip():
                    text = line.text.strip()
                    # Skip if it's just "Visit:" or a day number
                    if text not in ["Visit:", "Day"] and not re.match(r'^Day \d+$', text):
                        current_form = text
                        break
        
        # Extract fields based on page type
        if page_type == "metadata":
            fields = extract_fields_from_metadata(lines)
        else:  # data_entry
            fields = extract_fields_from_data_entry(lines)
        
        for field_name in fields:
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return results

def classify_page(lines: List) -> str:
    """Determine the page layout type."""
    # Check for visit separator: very sparse page with just "Visit:" and day
    content_lines = [l for l in lines if l.y0 > 50 and l.y0 < 800]
    if len(content_lines) <= 3:
        texts = [l.text.strip() for l in content_lines]
        if "Visit:" in texts or any(re.match(r'^Day \d+$', t) for t in texts):
            return "visit_separator"
    
    # Check for metadata page: has "Variable details" header
    for line in lines:
        if line.text.strip() == "Variable details" and line.bold:
            return "metadata"
    
    return "data_entry"

def extract_fields_from_metadata(lines: List) -> List[str]:
    """Extract field names from Variable details metadata pages."""
    fields = []
    
    # Find the "Name" column header to establish x position
    name_col_x = None
    for line in lines:
        if line.text.strip() == "Name" and line.bold:
            name_col_x = line.x0
            break
    
    if name_col_x is None:
        return fields
    
    # Extract field names from the Name column
    # They appear at similar x position to the header, are not bold, not bracketed IDs
    for line in lines:
        # Skip headers and bracketed IDs
        if line.bold or re.match(r'^\[\d+\]$', line.text.strip()):
            continue
        
        # Check if in Name column (within reasonable tolerance)
        if abs(line.x0 - name_col_x) < 15:
            text = line.text.strip()
            # Skip empty, column headers, and very short text
            if text and len(text) > 2:
                # Skip if it looks like a column header value
                if text not in ["Name", "Export Name", "Type", "Max length", "Categories"]:
                    fields.append(text)
    
    return fields

def extract_fields_from_data_entry(lines: List) -> List[str]:
    """Extract field labels from data-entry form pages."""
    fields = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Skip page headers and footers
        if line.y0 < 50 or line.y0 > 800:
            i += 1
            continue
        
        text = line.text.strip()
        if not text:
            i += 1
            continue
        
        # Skip bracketed IDs (they're not field labels themselves)
        if re.match(r'^\[\d+\]$', text):
            i += 1
            continue
        
        # Skip standalone row numbers at far left
        if re.match(r'^\d{1,3}$', text) and line.x0 < 50:
            i += 1
            continue
        
        # Field labels: bold, reasonable size, in left/center area
        if line.bold and 6 <= line.size <= 11 and line.x0 < 450:
            # Skip if it's a page identifier
            if re.match(r'^MAC\d+_', text):
                i += 1
                continue
            
            # Skip common structural headers that appear at specific positions
            # (top of page, very consistent y position across pages)
            if line.y0 < 70 and text in ["Variable details"]:
                i += 1
                continue
            
            # This is a field label
            field_text = text
            
            # Check for multi-line labels (continuation at similar x, close y)
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # Continuation: similar x, reasonable y gap, not a new field marker
                if (abs(next_line.x0 - line.x0) < 20 and 
                    0 < next_line.y0 - lines[j-1].y0 < 20 and
                    not re.search(r'^\[\d+\]$', next_line.text.strip())):
                    # Stop if next line is also bold (new field) or far indented (answer option)
                    if next_line.bold or next_line.x0 > line.x0 + 30:
                        break
                    field_text += " " + next_line.text.strip()
                    j += 1
                else:
                    break
            
            # Clean up: remove bracketed IDs embedded in the label
            field_text = re.sub(r'\s*\[\d+\]\s*', ' ', field_text).strip()
            
            # Final validation: must have reasonable length
            if field_text and len(field_text) > 1:
                fields.append(field_text)
            
            i = j if j > i + 1 else i + 1
        else:
            i += 1
    
    return fields
```