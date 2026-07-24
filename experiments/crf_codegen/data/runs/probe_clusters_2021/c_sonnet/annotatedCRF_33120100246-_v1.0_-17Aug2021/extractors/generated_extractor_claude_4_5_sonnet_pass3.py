import re
from collections import defaultdict

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
    
    # Strategy 1: Tabular layout with dark gray labels (cluster 2 pages)
    # Pattern: dark gray text at left margin, followed by Yes/No options
    fields.extend(extract_tabular_fields(lines, seen))
    
    # Strategy 2: Question-style fields (existing strategy, refined)
    fields.extend(extract_question_fields(lines, seen))
    
    return fields

def extract_tabular_fields(lines, seen):
    """Extract fields from tabular layout with dark gray labels."""
    fields = []
    
    # Find lines that are left-aligned, appropriate size, likely labels
    for i, line in enumerate(lines):
        # Skip machine codes
        if is_machine_code(line.text):
            continue
        
        text = line.text.strip()
        
        # Left-margin labels in tabular form layout
        # These are typically non-black (gray), size 7-8.5, at left margin
        if (line.non_black and 
            line.size >= 7.0 and line.size <= 8.5 and
            line.x0 < 60 and  # Left margin
            len(text) > 3):
            
            # Check if followed by Yes/No options (confirming it's a field)
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
    """Extract question-style field labels."""
    fields = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip machine codes (red text in brackets)
        if is_machine_code(line.text):
            i += 1
            continue
        
        # Skip if wrong size range
        if line.size < 6.5 or line.size > 12.0:
            i += 1
            continue
        
        text = line.text.strip()
        
        # Check if this looks like a field label
        if is_field_label(line, text, lines, i):
            # Collect multi-line labels
            full_label = text
            j = i + 1
            
            # Look ahead for continuation lines
            while j < len(lines):
                next_line = lines[j]
                
                # Stop at machine code
                if is_machine_code(next_line.text):
                    break
                
                # Check if continuation: close y, similar x-start, similar size
                y_gap = next_line.y0 - lines[j-1].y0
                x_diff = abs(next_line.x0 - line.x0)
                size_diff = abs(next_line.size - line.size)
                
                if (y_gap < 15 and x_diff < 30 and size_diff < 2.0):
                    next_text = next_line.text.strip()
                    
                    # Don't continue into obvious non-field text
                    if is_structural_junk(next_line, next_text, lines, j):
                        break
                    
                    full_label += " " + next_text
                    j += 1
                else:
                    break
            
            # Clean and validate
            full_label = clean_label(full_label)
            if full_label and is_valid_field(full_label) and full_label not in seen:
                fields.append(full_label)
                seen.add(full_label)
            
            i = j
        else:
            i += 1
    
    return fields

def is_machine_code(text):
    """Check if text is a machine code/annotation."""
    text = text.strip()
    if re.match(r'^\[.*\]$', text):
        return True
    return False

def is_field_label(line, text, lines, idx):
    """Determine if a line is likely a field label."""
    # Must have meaningful text
    if len(text) < 3:
        return False
    
    # Must be black text (not colored) - but check carefully
    # Some forms use non-black for labels, handled in tabular extraction
    if line.non_black and line.size < 7.0:
        return False
    
    # Appropriate size for field labels
    if line.size < 6.5 or line.size > 12.0:
        return False
    
    # Questions ending with ?
    if text.endswith('?'):
        # But not long instructional sentences
        if len(text) > 200:
            return False
        return True
    
    # Field labels with common patterns
    field_patterns = [
        r'^(Was|Were|Has|Have|Did|Does|Is|Are)\b',
        r'\b(date|time|sample|collected|administered|completion|reason)\b',
        r'\b(Manufacturer|Item|Lot|Expiration)\b',
        r'^(Rater\'?s?|Subject|Person|Patient|Participant)',
    ]
    
    for pattern in field_patterns:
        if re.search(pattern, text, re.I):
            # Exclude very long instructional text
            if len(text) > 250:
                return False
            return True
    
    return False

def is_structural_junk(line, text, lines, idx):
    """Identify junk by structural properties, not literal text."""
    # Very short fragments
    if len(text) < 2:
        return True
    
    # Page numbers (digits only, small, at margins)
    if re.match(r'^\d+$', text) and line.size < 10:
        return True
    
    # Answer options in specific positions/contexts
    # Typically aligned to the right, or in a column separate from labels
    if line.x0 > 400:  # Right side of page
        if text in ['Yes', 'No', 'Normal', 'Abnormal', 'Not Done']:
            return True
    
    # Very long paragraphs (instructions, not field labels)
    # Look for multiple sentences or excessive length
    if len(text) > 300:
        return True
    
    # Text that's clearly part of a longer instructional block
    # Check if surrounded by similar-length lines at same x-position
    if len(text) > 150:
        # Count nearby long lines at similar x
        long_neighbors = 0
        for offset in [-2, -1, 1, 2]:
            neighbor_idx = idx + offset
            if 0 <= neighbor_idx < len(lines):
                neighbor = lines[neighbor_idx]
                if (abs(neighbor.y0 - line.y0) < 50 and
                    abs(neighbor.x0 - line.x0) < 20 and
                    len(neighbor.text.strip()) > 100):
                    long_neighbors += 1
        
        # If surrounded by similar long text, it's instructional prose
        if long_neighbors >= 2:
            return True
    
    # Parenthetical fragments (often answer explanations)
    if text.startswith('(') and text.endswith(')') and len(text) < 50:
        return True
    
    return False

def is_valid_field(text):
    """Final validation that this is a legitimate field label."""
    # Remove extra whitespace
    text = text.strip()
    
    # Must have content
    if len(text) < 2:
        return False
    
    # Reject if it's just punctuation or numbers
    if re.match(r'^[\d\s\.\,\;\:\-\(\)]+$', text):
        return False
    
    # Reject overly long text blocks (instructions, not field labels)
    if len(text) > 400:
        return False
    
    # Reject text that's clearly an answer description or rating anchor
    # These tend to be complete sentences with specific grammatical patterns
    instructional_patterns = [
        r'^(Select all that apply)',
        r'^(The following features)',
        r'^(Inferring Intent)',
        r'^(Ask questions \d+ and \d+)',
        r'(e\.g\.|i\.e\.)',
        r'so long as',
        r'must ask about',
    ]
    
    for pattern in instructional_patterns:
        if re.search(pattern, text, re.I):
            return False
    
    # Reject if contains long parenthetical explanations
    paren_content = re.findall(r'\([^)]{50,}\)', text)
    if paren_content:
        return False
    
    return True

def clean_label(text):
    """Clean and normalize field label text."""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove trailing punctuation fragments
    text = re.sub(r'\s*[,;:]+$', '', text)
    
    return text
