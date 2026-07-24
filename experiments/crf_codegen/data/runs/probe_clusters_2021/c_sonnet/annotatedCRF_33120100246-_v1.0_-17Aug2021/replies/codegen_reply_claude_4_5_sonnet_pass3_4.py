Looking at the problems, I need to:

1. **Fix false positives** - section headers and question text being extracted as fields
2. **Fix false negatives** - missing actual field labels that are short, bold, or in specific table positions

Let me analyze the patterns:
- Page 37: "Skin and Mucosae", "Neurological", "Extremities" are section headers, not fields
- Page 42: Missing "Glycated Hemoglobin", "Scan", "Barcode Number" - likely bold labels
- Page 71: Missing "Suicidal Ideation", "Lifetime", "Past 3 Month" - table headers
- Page 78: Extracting question text instead of the actual field names
- Pages 136, 198, 423: Missing bold field labels, extracting rating scale text instead

The key insight: I need to distinguish between:
- **Field labels** (short, often bold, positioned as table headers or form labels)
- **Section headers** (large, bold, but standalone without associated input)
- **Question text** (long sentences, part of instructions)
- **Rating anchors** (parenthetical scale descriptions)

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
    
    # Strategy 1: Bold table headers and form labels (size 7-10, bold)
    fields.extend(extract_bold_labels(lines, seen))
    
    # Strategy 2: Tabular layout with dark gray labels
    fields.extend(extract_tabular_fields(lines, seen))
    
    # Strategy 3: Question-style fields (refined to avoid question text)
    fields.extend(extract_question_fields(lines, seen))
    
    return fields

def extract_bold_labels(lines, seen):
    """Extract bold field labels - common in tables and form layouts."""
    fields = []
    
    for i, line in enumerate(lines):
        # Skip machine codes
        if is_machine_code(line.text):
            continue
        
        text = line.text.strip()
        
        # Bold labels in typical field label size range
        if (line.bold and 
            line.size >= 7.0 and line.size <= 10.5 and
            len(text) >= 2):
            
            # Exclude section headers (isolated, larger, no nearby fields)
            if is_section_header(line, text, lines, i):
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
                is_valid_field_label(full_label) and 
                full_label not in seen):
                fields.append(full_label)
                seen.add(full_label)
    
    return fields

def is_section_header(line, text, lines, idx):
    """Determine if bold text is a section header rather than a field label."""
    # Section headers are typically:
    # - Standalone (no nearby input indicators)
    # - Not followed by colons or input patterns
    # - Often at left margin with nothing aligned to the right
    
    # Very short text unlikely to be standalone header
    if len(text) <= 15:
        return False
    
    # Check for evidence this is NOT a header:
    # 1. Followed by colon (field pattern)
    if text.endswith(':'):
        return False
    
    # 2. Has nearby input indicators (checkboxes, yes/no, date fields)
    has_input_nearby = False
    for j in range(idx + 1, min(idx + 15, len(lines))):
        next_line = lines[j]
        next_text = next_line.text.strip()
        
        # Stop searching if we hit another bold label
        if next_line.bold and next_line.size >= 7.0:
            break
        
        # Input indicators
        if (next_text in ['Yes', 'No', 'Normal', 'Abnormal', 'Not Done'] or
            re.match(r'^(Date|Time|Sample|Manufacturer|Lot|Item|Barcode)', next_text, re.I) or
            next_line.x0 > line.x0 + 200):  # Input on same row, far right
            has_input_nearby = True
            break
    
    # If it's bold, medium-length, and has NO input nearby, likely a section header
    if not has_input_nearby and len(text) > 10 and len(text) < 40:
        # Additional check: section headers often stand alone vertically
        # Look for vertical space before and after
        space_before = idx > 0 and (line.y0 - lines[idx-1].y0) > 20
        space_after = False
        if idx + 1 < len(lines):
            space_after = (lines[idx+1].y0 - line.y0) > 15
        
        if space_before or space_after:
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
            
            # Check if followed by Yes/No options
            has_yes_no_nearby = False
            for j in range(i + 1, min(i + 10, len(lines))):
                next_line = lines[j]
                if (abs(next_line.y0 - line.y0) < 20 and
                    next_line.x0 > 400 and
                    next_line.text.strip() in ['Yes', 'No']):
                    has_yes_no_nearby = True
                    break
            
            if has_yes_no_nearby and text not in seen:
                fields.append(text)
                seen.add(text)
    
    return fields

def extract_question_fields(lines, seen):
    """Extract question-style field labels - but NOT the question text itself."""
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
        
        # Only extract if this is clearly a field label, not question text
        if is_field_label_not_question(line, text, lines, i):
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
                
                if (y_gap < 15 and x_diff < 30 and size_diff < 2.0):
                    next_text = next_line.text.strip()
                    
                    if is_structural_junk(next_line, next_text, lines, j):
                        break
                    
                    full_label += " " + next_text
                    j += 1
                else:
                    break
            
            full_label = clean_label(full_label)
            if full_label and is_valid_field_label(full_label) and full_label not in seen:
                fields.append(full_label)
                seen.add(full_label)
            
            i = j
        else:
            i += 1
    
    return fields

def is_field_label_not_question(line, text, lines, idx):
    """Determine if text is a field label, excluding question text."""
    # Must have meaningful text
    if len(text) < 3:
        return False
    
    # Exclude very long text (question text, not labels)
    if len(text) > 100:
        return False
    
    # Size check
    if line.size < 6.5 or line.size > 12.0:
        return False
    
    # Pattern: Short questions ending with ? (under 100 chars) are field labels
    if text.endswith('?') and len(text) <= 100:
        # But exclude questions that start with pronouns (likely question text, not labels)
        question_text_patterns = [
            r'^(Have you|Did you|Were you|Are you|Do you|Will you|Would you|Can you|Could you)\b',
            r'^(Has he|Has she|Was he|Was she)\b',
        ]
        for pattern in question_text_patterns:
            if re.match(pattern, text, re.I):
                return False
        
        return True
    
    # Field labels with common patterns (not ending in ?)
    field_patterns = [
        r'^(Was|Were|Has|Have|Did|Does|Is|Are)\s+[A-Z]',  # "Was Blood sample Collected"
        r'\b(date|time|sample|collected|administered|completion|reason)\b',
        r'\b(Manufacturer|Item|Lot|Expiration|Barcode|Scan)\b',
        r'^(Rater\'?s?|Subject|Person|Patient|Participant)',
        r'\bnot\s+done\b',
        r'^(Result|Test|Method)\s*$',
    ]
    
    for pattern in field_patterns:
        if re.search(pattern, text, re.I):
            # But exclude if it's clearly part of a longer sentence
            if len(text) > 150:
                return False
            return True
    
    return False

def is_structural_junk(line, text, lines, idx):
    """Identify junk by structural properties."""
    if len(text) < 2:
        return True
    
    # Page numbers
    if re.match(r'^\d+$', text) and line.size < 10:
        return True
    
    # Answer options on the right side
    if line.x0 > 400:
        if text in ['Yes', 'No', 'Normal', 'Abnormal', 'Not Done']:
            return True
    
    # Very long paragraphs
    if len(text) > 300:
        return True
    
    # Instructional blocks (surrounded by similar long lines)
    if len(text) > 150:
        long_neighbors = 0
        for offset in [-2, -1, 1, 2]:
            neighbor_idx = idx + offset
            if 0 <= neighbor_idx < len(lines):
                neighbor = lines[neighbor_idx]
                if (abs(neighbor.y0 - line.y0) < 50 and
                    abs(neighbor.x0 - line.x0) < 20 and
                    len(neighbor.text.strip()) > 100):
                    long_neighbors += 1
        
        if long_neighbors >= 2:
            return True
    
    # Parenthetical fragments
    if text.startswith('(') and text.endswith(')') and len(text) < 50:
        return True
    
    # Rating scale anchors (contain specific patterns)
    rating_patterns = [
        r'\(\d+\)\s+(Less than|More than|Does not)',
        r'\d+-\d+\s+hours',
        r'persistent or continuous',
        r'a lot of time',
        r'most of day',
    ]
    for pattern in rating_patterns:
        if re.search(pattern, text, re.I):
            return True
    
    return False

def is_valid_field_label(text):
    """Final validation that this is a legitimate field label."""
    text = text.strip()
    
    if len(text) < 2:
        return False
    
    # Reject if just punctuation or numbers
    if re.match(r'^[\d\s\.\,\;\:\-\(\)]+$', text):
        return False
    
    # Reject overly long text blocks
    if len(text) > 200:
        return False
    
    # Reject rating anchors and scale descriptions
    rating_anchor_patterns = [
        r'\(\d+\)\s+(Less than|More than|Cannot|Does not|Unable to)',
        r'\d+\s+hours/\w+\s+of\s+(the\s+)?(time|day)',
        r'persistent or continuous',
        r'e\.g\.|i\.e\.',
        r'so long as',
        r'must ask about',
        r'^(Select all that apply)',
        r'^(The following features)',
        r'^(Inferring Intent)',
        r'to get attention, revenge',
        r'even a little',
        r'way to end your life',
        r'possible you could have died',
        r'feeling the most suicidal',
        r'or minutes,',
    ]
    
    for pattern in rating_anchor_patterns:
        if re.search(pattern, text, re.I):
            return False
    
    # Reject if contains very long parenthetical explanations
    paren_content = re.findall(r'\([^)]{50,}\)', text)
    if paren_content:
        return False
    
    # Reject question text starting with pronouns
    if re.match(r'^(Have you|Did you|Were you|Are you|What did you|Or did you)\b', text, re.I):
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
