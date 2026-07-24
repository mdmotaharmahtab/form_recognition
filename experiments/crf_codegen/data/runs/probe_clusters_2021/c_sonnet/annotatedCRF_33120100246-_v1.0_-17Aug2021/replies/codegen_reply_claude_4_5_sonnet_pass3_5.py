Looking at the quality feedback, I need to fix several structural issues:

1. **Remove all literal string blocklists** - replace with structural discriminators
2. **Fix column-based field detection** - "Test" and "Result" are column headers in tables
3. **Better distinguish table headers from answer options** - "Not Done" is sometimes a checkbox option, not a field
4. **Handle multi-row form layouts** - "Row 1", "Row 2" are layout artifacts, not fields
5. **Detect question/field patterns better** - long descriptive text vs. actual field labels
6. **Extract composite field names** - "Glycated Hemoglobin" spans multiple formatting

Let me rewrite with structural rules only:

```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form name - large colored header at top of page
        form_candidates = []
        for line in lines[:20]:
            if line.size >= 13.0 and line.non_black and line.bold:
                text = line.text.strip()
                if text and not is_machine_code(text):
                    form_candidates.append((line.y0, text))
        
        if form_candidates:
            form_candidates.sort(key=lambda x: x[0])
            current_form = form_candidates[0][1]
        
        # Extract fields using multiple layout strategies
        fields = extract_fields_from_page(lines)
        
        for field_name in fields:
            results.append({
                "form_name": current_form,
                "field_name": field_name,
                "page": page_num
            })
    
    return results

def extract_fields_from_page(lines):
    """Extract field labels from a single page using multiple strategies."""
    fields = []
    seen = set()
    
    # Strategy 1: Bold table headers and form labels
    fields.extend(extract_bold_labels(lines, seen))
    
    # Strategy 2: Tabular layout with dark gray labels
    fields.extend(extract_tabular_fields(lines, seen))
    
    # Strategy 3: Question-style fields
    fields.extend(extract_question_fields(lines, seen))
    
    # Strategy 4: Column headers in data tables
    fields.extend(extract_table_column_headers(lines, seen))
    
    return fields

def extract_bold_labels(lines, seen):
    """Extract bold field labels - common in tables and form layouts."""
    fields = []
    
    for i, line in enumerate(lines):
        if is_machine_code(line.text):
            continue
        
        text = line.text.strip()
        
        # Bold labels in typical field label size range
        if (line.bold and 
            line.size >= 7.0 and line.size <= 10.5 and
            len(text) >= 2):
            
            # Exclude by structural position
            if is_excluded_by_structure(line, text, lines, i):
                continue
            
            # Collect multi-line bold labels
            full_label = text
            j = i + 1
            
            while j < len(lines):
                next_line = lines[j]
                
                if is_machine_code(next_line.text):
                    break
                
                # Continuation: close y, similar x, same bold style, similar size
                y_gap = next_line.y0 - lines[j-1].y0
                x_diff = abs(next_line.x0 - line.x0)
                size_diff = abs(next_line.size - line.size)
                
                if (next_line.bold and 
                    y_gap < 15 and x_diff < 30 and size_diff < 2.0):
                    full_label += " " + next_line.text.strip()
                    j += 1
                else:
                    break
            
            full_label = clean_label(full_label)
            
            # Validate and add
            if (full_label and 
                is_valid_field_label_structural(full_label, line, lines, i) and 
                full_label not in seen):
                fields.append(full_label)
                seen.add(full_label)
    
    return fields

def is_excluded_by_structure(line, text, lines, idx):
    """Exclude text based on structural properties, not literal strings."""
    # Very short labels at right margin (likely answer options)
    if len(text) <= 15 and line.x0 > 400:
        # Check if it's isolated on the right (checkbox option)
        has_label_on_left = False
        for j in range(max(0, idx - 10), idx):
            prev_line = lines[j]
            if (abs(prev_line.y0 - line.y0) < 20 and 
                prev_line.x0 < 200 and
                len(prev_line.text.strip()) > 10):
                has_label_on_left = True
                break
        
        if has_label_on_left:
            return True
    
    # Section headers: standalone bold text with vertical space
    if line.bold and len(text) > 10 and len(text) < 50:
        # Check for vertical isolation
        space_before = idx > 0 and (line.y0 - lines[idx-1].y0) > 20
        space_after = idx + 1 < len(lines) and (lines[idx+1].y0 - line.y0) > 15
        
        # Check if no input fields nearby
        has_input_nearby = False
        for j in range(idx + 1, min(idx + 15, len(lines))):
            next_line = lines[j]
            
            if next_line.bold and next_line.size >= 7.0:
                break
            
            # Input indicators: right-side text, date/time patterns, colon endings
            if (next_line.x0 > line.x0 + 150 or
                text.endswith(':') or
                re.search(r'\b(date|time|sample|barcode)\b', next_line.text, re.I)):
                has_input_nearby = True
                break
        
        if (space_before or space_after) and not has_input_nearby:
            return True
    
    # Layout markers: "Row N" pattern at left margin
    if line.x0 < 60 and re.match(r'^Row\s+\d+$', text, re.I):
        return True
    
    # Version/footer text (small, at bottom, contains date or version)
    if line.size < 8.0 and line.y0 > 700:
        if re.search(r'\b(version|page|\d{1,2}-\w{3}-\d{4})\b', text, re.I):
            return True
    
    return False

def extract_tabular_fields(lines, seen):
    """Extract fields from tabular layout with dark gray labels."""
    fields = []
    
    for i, line in enumerate(lines):
        if is_machine_code(line.text):
            continue
        
        text = line.text.strip()
        
        # Left-margin labels in tabular form layout
        if (line.non_black and 
            line.size >= 7.0 and line.size <= 8.5 and
            line.x0 < 60 and
            len(text) > 3):
            
            # Must have input field indicators nearby (right side or below)
            has_input_field = False
            
            # Check same row (far right)
            for j in range(i + 1, min(i + 10, len(lines))):
                next_line = lines[j]
                if abs(next_line.y0 - line.y0) < 10:
                    if next_line.x0 > 300:
                        has_input_field = True
                        break
                elif next_line.y0 - line.y0 > 20:
                    break
            
            if has_input_field and text not in seen:
                fields.append(text)
                seen.add(text)
    
    return fields

def extract_table_column_headers(lines, seen):
    """Extract column headers from data tables."""
    fields = []
    
    # Find table structures: rows with multiple columns aligned vertically
    for i, line in enumerate(lines):
        if is_machine_code(line.text):
            continue
        
        text = line.text.strip()
        
        # Candidate column header: short, mid-size, positioned in table area
        if (line.size >= 7.0 and line.size <= 9.5 and
            len(text) >= 3 and len(text) <= 30 and
            200 < line.x0 < 500):
            
            # Check if this is part of a columnar structure
            # Look for vertically aligned content below
            aligned_below = 0
            for j in range(i + 1, min(i + 20, len(lines))):
                next_line = lines[j]
                x_diff = abs(next_line.x0 - line.x0)
                y_gap = next_line.y0 - line.y0
                
                # Stop if we've gone too far down
                if y_gap > 100:
                    break
                
                # Count lines aligned in same column
                if x_diff < 20 and y_gap > 5:
                    aligned_below += 1
            
            # If multiple lines below are aligned, this is likely a column header
            if aligned_below >= 3 and text not in seen:
                fields.append(text)
                seen.add(text)
    
    return fields

def extract_question_fields(lines, seen):
    """Extract question-style field labels."""
    fields = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        if is_machine_code(line.text):
            i += 1
            continue
        
        if line.size < 6.5 or line.size > 12.0:
            i += 1
            continue
        
        text = line.text.strip()
        
        # Identify field labels structurally
        if is_field_label_by_structure(line, text, lines, i):
            full_label = text
            j = i + 1
            
            # Collect multi-line labels
            while j < len(lines):
                next_line = lines[j]
                
                if is_machine_code(next_line.text):
                    break
                
                y_gap = next_line.y0 - lines[j-1].y0
                x_diff = abs(next_line.x0 - line.x0)
                size_diff = abs(next_line.size - line.size)
                
                # Continue if same formatting and close proximity
                if (y_gap < 15 and x_diff < 30 and size_diff < 2.0):
                    next_text = next_line.text.strip()
                    
                    # Stop at structural boundaries
                    if is_structural_boundary(next_line, next_text, lines, j):
                        break
                    
                    full_label += " " + next_text
                    j += 1
                else:
                    break
            
            full_label = clean_label(full_label)
            if full_label and is_valid_field_label_structural(full_label, line, lines, i) and full_label not in seen:
                fields.append(full_label)
                seen.add(full_label)
            
            i = j
        else:
            i += 1
    
    return fields

def is_field_label_by_structure(line, text, lines, idx):
    """Determine if text is a field label based on structure."""
    if len(text) < 3:
        return False
    
    # Too long to be a field label (likely prose/instructions)
    if len(text) > 150:
        return False
    
    # Questions ending with ? (short to medium length)
    if text.endswith('?') and len(text) <= 100:
        # Exclude if it's in a paragraph block (surrounded by long lines)
        in_paragraph = False
        for offset in [-1, 1]:
            neighbor_idx = idx + offset
            if 0 <= neighbor_idx < len(lines):
                neighbor = lines[neighbor_idx]
                if (abs(neighbor.y0 - line.y0) < 20 and
                    abs(neighbor.x0 - line.x0) < 20 and
                    len(neighbor.text.strip()) > 100):
                    in_paragraph = True
                    break
        
        if not in_paragraph:
            return True
    
    # Statements starting with common field patterns
    # But at left margin or standard label position
    if line.x0 < 150:
        if re.match(r'^(Was|Were|Has|Have|Did|Does|Is|Are)\s+\w', text, re.I):
            # Not too long (under 100 chars = field, over = prose)
            if len(text) < 100:
                return True
        
        if re.search(r'\b(date|time|sample|collected|barcode|manufacturer|lot|item|expiration|reason)\b', text, re.I):
            if len(text) < 80:
                return True
    
    return False

def is_structural_boundary(line, text, lines, idx):
    """Identify structural boundaries that stop label collection."""
    # Empty or very short
    if len(text) < 2:
        return True
    
    # Page numbers (small, numeric only)
    if re.match(r'^\d+$', text) and line.size < 10:
        return True
    
    # Answer options positioned far right
    if line.x0 > 400 and len(text) < 20:
        return True
    
    # Paragraph blocks (long lines in sequence)
    if len(text) > 150:
        # Check for surrounding long lines
        long_neighbors = 0
        for offset in [-1, 1]:
            neighbor_idx = idx + offset
            if 0 <= neighbor_idx < len(lines):
                neighbor = lines[neighbor_idx]
                if (abs(neighbor.y0 - line.y0) < 30 and
                    len(neighbor.text.strip()) > 100):
                    long_neighbors += 1
        
        if long_neighbors >= 1:
            return True
    
    # Parenthetical asides (short, in parens)
    if text.startswith('(') and text.endswith(')') and len(text) < 60:
        return True
    
    return False

def is_valid_field_label_structural(text, line, lines, idx):
    """Validate field label using structural properties only."""
    text = text.strip()
    
    if len(text) < 2:
        return False
    
    # Reject if just punctuation or numbers
    if re.match(r'^[\d\s\.\,\;\:\-\(\)]+$', text):
        return False
    
    # Reject overly long text blocks
    if len(text) > 200:
        return False
    
    # Structural: reject if surrounded by long prose lines (it's part of instructions)
    prose_neighbors = 0
    for offset in [-2, -1, 1, 2]:
        neighbor_idx = idx + offset
        if 0 <= neighbor_idx < len(lines):
            neighbor = lines[neighbor_idx]
            if (abs(neighbor.y0 - line.y0) < 40 and
                abs(neighbor.x0 - line.x0) < 30 and
                len(neighbor.text.strip()) > 120):
                prose_neighbors += 1
    
    if prose_neighbors >= 2:
        return False
    
    # Structural: reject rating scale anchors (parenthetical number + description)
    if re.match(r'\(\d+\)\s+\w', text):
        # Likely a rating anchor if in a vertical list of similar items
        similar_above = False
        similar_below = False
        
        if idx > 0:
            prev = lines[idx - 1]
            if (line.y0 - prev.y0 < 20 and
                abs(line.x0 - prev.x0) < 10 and
                re.match(r'\(\d+\)\s+\w', prev.text.strip())):
                similar_above = True
        
        if idx + 1 < len(lines):
            next_line = lines[idx + 1]
            if (next_line.y0 - line.y0 < 20 and
                abs(next_line.x0 - line.x0) < 10 and
                re.match(r'\(\d+\)\s+\w', next_line.text.strip())):
                similar_below = True
        
        if similar_above or similar_below:
            return False
    
    # Structural: reject long parenthetical explanations
    paren_count = text.count('(')
    if paren_count >= 2 and len(text) > 80:
        return False
    
    # Structural: reject if contains multiple sentences (period + space + capital)
    sentence_breaks = len(re.findall(r'\.\s+[A-Z]', text))
    if sentence_breaks >= 2:
        return False
    
    return True

def is_machine_code(text):
    """Check if text is a machine code/annotation."""
    text = text.strip()
    if re.match(r'^\[.*\]$', text):
        return True
    return False

def clean_label(text):
    """Clean and normalize field label text."""
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\s*[,;:]+$', '', text)
    return text
```
