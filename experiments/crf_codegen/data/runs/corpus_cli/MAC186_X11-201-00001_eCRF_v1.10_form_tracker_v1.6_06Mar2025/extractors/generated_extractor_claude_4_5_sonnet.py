import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    last_form_name = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Convert lines to Line objects if needed
        if lines and not isinstance(lines[0], Line):
            lines = [Line(text=ln.text, x0=ln.x0, y0=ln.y0, x1=ln.x1, y1=ln.y1,
                         size=ln.size, bold=ln.bold, non_black=ln.non_black) for ln in lines]
        
        if not lines:
            continue
        
        # Detect page type and extract
        page_type = detect_page_type(lines)
        
        if page_type == 'variable_details':
            page_results, form_name = extract_variable_details(lines, page_num, last_form_name)
        elif page_type == 'variable_details_questionnaire':
            page_results, form_name = extract_variable_details_questionnaire(lines, page_num, last_form_name)
        elif page_type == 'export_code_definitions':
            page_results, form_name = extract_export_code_definitions(lines, page_num, last_form_name)
        elif page_type == 'compact_vitals':
            page_results, form_name = extract_compact_vitals(lines, page_num, last_form_name)
        elif page_type == 'numbered_questionnaire':
            page_results, form_name = extract_numbered_questionnaire(lines, page_num, last_form_name)
        elif page_type == 'form_page':
            page_results, form_name = extract_form_page(lines, page_num, last_form_name)
        elif page_type == 'visit_title':
            page_results, form_name = [], last_form_name
        else:
            page_results, form_name = [], last_form_name
        
        # Update last_form_name if we found one
        if form_name:
            last_form_name = form_name
        
        results.extend(page_results)
    
    return results

def detect_page_type(lines):
    """Detect page layout type by structural features."""
    # Check for visit title pages (only "Visit:" and day number, very sparse)
    large_text_count = sum(1 for line in lines if line.size > 15)
    if large_text_count <= 3 and len(lines) < 10:
        for line in lines:
            if 'Visit:' in line.text and line.size > 15:
                return 'visit_title'
    
    # Check for variable details table (header or continuation)
    has_name_column = False
    has_export_column = False
    has_variable_header = False
    
    for line in lines[:15]:
        if line.y0 < 65:
            if 'Variable details' in line.text and line.bold:
                has_variable_header = True
            if line.x0 > 70 and line.x0 < 100 and 'Name' in line.text and line.bold:
                has_name_column = True
            if line.x0 > 220 and line.x0 < 250 and 'Export' in line.text:
                has_export_column = True
    
    if has_variable_header or (has_name_column and has_export_column):
        return 'variable_details'
    
    # Check for export code definitions: [N] codes + export variable names + data types
    # Structure: [N] at x~41, export code at x~235, data type at x~390
    has_bracket_codes = False
    has_export_codes = False
    has_data_types = False
    
    for line in lines[:30]:
        # [N] pattern at left
        if line.x0 > 35 and line.x0 < 50 and re.match(r'^\[\d+\]$', line.text.strip()):
            has_bracket_codes = True
        # Export codes at x~235
        if line.x0 > 220 and line.x0 < 250 and line.size < 8:
            text = line.text.strip()
            if len(text) > 3 and re.match(r'^[A-Z][A-Z0-9_]+$', text):
                has_export_codes = True
        # Data type descriptions at x~390
        if line.x0 > 380 and line.x0 < 410 and line.size < 8:
            text = line.text.strip()
            if any(keyword in text for keyword in ['Categorical', 'Number', 'Text', 'Date', 'continuous', 'dichotomous']):
                has_data_types = True
    
    if has_bracket_codes and has_export_codes and has_data_types:
        return 'export_code_definitions'
    
    # Check for variable details questionnaire variant: [N] codes + numbered questions + export codes
    # Structure: [N] at x~41, question text at x~81, export code at x~235
    has_question_pattern = False
    
    for line in lines[:30]:
        # Check for numbered question text (e.g., "15. I worry...")
        if line.x0 > 75 and line.x0 < 90 and re.match(r'^\d+\.\s+\w+', line.text.strip()):
            has_question_pattern = True
    
    if has_bracket_codes and has_question_pattern:
        return 'variable_details_questionnaire'
    
    # Check for compact vitals table (field names at right edge, x>500)
    right_edge_fields = 0
    for line in lines[:50]:
        if line.x0 > 490 and line.size < 9:
            text = line.text.strip()
            # Structural check: contains mixed-case medical terms
            if len(text) > 5 and any(c.isupper() for c in text) and any(c.islower() for c in text):
                right_edge_fields += 1
    
    if right_edge_fields >= 3:
        return 'compact_vitals'
    
    # Check for numbered questionnaire (sequential numbers with text at x~64)
    numbered_items = 0
    for i, line in enumerate(lines[:40]):
        if line.x0 < 50 and line.size < 8:
            if re.match(r'^\d+$', line.text.strip()):
                # Check if next line or nearby has text at x~64
                for j in range(i+1, min(i+3, len(lines))):
                    if lines[j].x0 > 60 and lines[j].x0 < 90 and len(lines[j].text) > 10:
                        numbered_items += 1
                        break
    
    if numbered_items >= 4:
        return 'numbered_questionnaire'
    
    # Check for standard form page (large title or [N] codes with bold labels)
    for line in lines[:15]:
        if line.y0 < 120 and line.size > 15:
            return 'form_page'
    
    for line in lines[:30]:
        if line.bold and re.search(r'\[\d+\]', line.text):
            return 'form_page'
    
    return 'unknown'

def extract_form_name(lines, top_n=15):
    """Extract form name from page header."""
    # Look for large title (sz > 15) or bold section label (sz 7-9)
    for line in lines[:top_n]:
        # Large title
        if line.y0 > 60 and line.y0 < 120 and line.size > 15:
            return line.text.strip()
        # Bold section label
        elif line.y0 > 40 and line.y0 < 60 and line.bold and line.size > 7 and line.size < 9:
            text = line.text.strip()
            # Skip document IDs (contain underscore or start with MAC)
            if '_' not in text and not text.startswith('MAC'):
                return text
    
    return ""

def extract_variable_details(lines, page_num, fallback_form_name):
    """Extract from variable details table pages."""
    results = []
    form_name = extract_form_name(lines, top_n=8) or fallback_form_name
    
    # Find Name column position (x range for field names)
    name_col_x = None
    for line in lines[:10]:
        if line.y0 < 65 and 'Name' in line.text and line.bold:
            name_col_x = line.x0
            break
    
    if name_col_x is None:
        name_col_x = 80  # Default
    
    # Extract field names from Name column
    seen_fields = set()
    
    for line in lines:
        # Data rows: x near Name column, reasonable font size, below header area
        if line.x0 > name_col_x - 10 and line.x0 < name_col_x + 40 and line.size < 8 and line.y0 > 50:
            text = line.text.strip()
            
            # Structural filters
            if is_valid_field_name(text, context='table') and text not in seen_fields:
                results.append({
                    "form_name": form_name,
                    "field_name": text,
                    "page": page_num
                })
                seen_fields.add(text)
    
    return results, form_name

def extract_export_code_definitions(lines, page_num, fallback_form_name):
    """Extract from export code definition pages.
    
    These pages show: [N] code | Export variable name | Data type | Field length
    The export variable names ARE the field identifiers, but only if they're
    descriptive enough (contain underscores or mixed case or are long).
    """
    results = []
    form_name = extract_form_name(lines, top_n=8) or fallback_form_name
    
    # Extract from export code column (x~235)
    seen_fields = set()
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for [N] code
        if line.x0 > 35 and line.x0 < 50 and line.size < 8 and re.match(r'^\[\d+\]$', line.text.strip()):
            # Find export code in same row (x~235)
            for j in range(i, min(i + 3, len(lines))):
                export_line = lines[j]
                # Export code at x~235, within vertical range
                if export_line.x0 > 220 and export_line.x0 < 250 and abs(export_line.y0 - line.y0) < 5:
                    text = export_line.text.strip()
                    # Valid export codes: should be descriptive field identifiers
                    # Skip pure machine codes (short, all caps, no underscores)
                    if (len(text) > 6 and 
                        re.match(r'^[A-Z][A-Z0-9_]+$', text) and 
                        ('_' in text or len(text) > 15) and
                        text not in seen_fields):
                        results.append({
                            "form_name": form_name,
                            "field_name": text,
                            "page": page_num
                        })
                        seen_fields.add(text)
                        break
        
        i += 1
    
    return results, form_name

def extract_variable_details_questionnaire(lines, page_num, fallback_form_name):
    """Extract from variable details questionnaire variant (numbered questions with export codes)."""
    results = []
    form_name = extract_form_name(lines, top_n=8) or fallback_form_name
    
    # Extract field labels from question text column (x~81)
    # Structure: [N] at x~41, question at x~81, export at x~235
    seen_fields = set()
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for [N] code or numbered question
        is_bracket = line.x0 > 35 and line.x0 < 50 and line.size < 8 and re.match(r'^\[\d+\]$', line.text.strip())
        is_number = line.x0 > 35 and line.x0 < 50 and line.size < 8 and re.match(r'^\d+$', line.text.strip())
        
        if is_bracket or is_number:
            # Collect all question text parts in same row (x~81, within 25 points vertically for wrapping)
            field_parts = []
            base_y = line.y0
            
            for j in range(i, min(i + 15, len(lines))):
                text_line = lines[j]
                # Question text at x~81, within vertical range
                if text_line.x0 > 75 and text_line.x0 < 95 and abs(text_line.y0 - base_y) < 25:
                    text = text_line.text.strip()
                    # Skip if it's an export code (at x~235) or answer option
                    if text and not (text_line.x0 > 220 and text.isupper()):
                        # Clean question number prefix if present
                        cleaned = re.sub(r'^\d+\.\s*', '', text)
                        if cleaned and len(cleaned) > 2 and not re.match(r'^\d+\s*-\s*', cleaned):
                            field_parts.append(cleaned)
            
            if field_parts:
                field_name = ' '.join(field_parts)
                if field_name not in seen_fields and is_valid_field_name(field_name, context='questionnaire'):
                    results.append({
                        "form_name": form_name,
                        "field_name": field_name,
                        "page": page_num
                    })
                    seen_fields.add(field_name)
        
        i += 1
    
    return results, form_name

def extract_compact_vitals(lines, page_num, fallback_form_name):
    """Extract from compact vital signs tables (field names at right edge)."""
    results = []
    form_name = extract_form_name(lines) or fallback_form_name
    
    # Extract field names from right column (x > 490)
    seen_fields = set()
    
    for line in lines:
        if line.x0 > 490 and line.y0 > 45 and line.size < 9:
            text = line.text.strip()
            
            if is_valid_field_name(text, context='vitals') and text not in seen_fields:
                results.append({
                    "form_name": form_name,
                    "field_name": text,
                    "page": page_num
                })
                seen_fields.add(text)
    
    return results, form_name

def extract_numbered_questionnaire(lines, page_num, fallback_form_name):
    """Extract from numbered questionnaire pages."""
    results = []
    form_name = extract_form_name(lines) or fallback_form_name
    
    # Find numbered items (number at x<50, text at x~64)
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for row number
        if line.x0 < 55 and line.size < 8 and re.match(r'^\d+$', line.text.strip()):
            # Collect all text parts in same row area (next 15 lines, x > 60, within 20 points vertically)
            field_text_parts = []
            base_y = line.y0
            
            for j in range(i+1, min(i+15, len(lines))):
                next_line = lines[j]
                # Text in same row area, x position around 64
                if next_line.x0 > 60 and next_line.x0 < 90 and abs(next_line.y0 - base_y) < 20:
                    text = next_line.text.strip()
                    # Check if it's field text (not answer options or isolated single words)
                    if text and not re.match(r'^\d+\s*-\s*', text) and len(text) > 2:
                        field_text_parts.append(text)
            
            if field_text_parts:
                field_name = ' '.join(field_text_parts)
                if is_valid_field_name(field_name, context='questionnaire'):
                    results.append({
                        "form_name": form_name,
                        "field_name": field_name,
                        "page": page_num
                    })
        
        i += 1
    
    return results, form_name

def extract_form_page(lines, page_num, fallback_form_name):
    """Extract from standard form pages."""
    results = []
    form_name = extract_form_name(lines) or fallback_form_name
    
    # Extract field labels: bold text with nearby [N] codes
    field_labels = []
    
    for i, line in enumerate(lines):
        if line.y0 > 90 and line.bold:
            text = line.text.strip()
            
            # Skip if line contains [N] code itself
            if re.search(r'\[\d+\]', text):
                # Extract label before [N] if present
                match = re.match(r'^(.+?)\s*\[\d+\]', text)
                if match:
                    label = match.group(1).strip()
                    if is_valid_field_name(label, context='form'):
                        field_labels.append(label)
                continue
            
            # Check if this is a field label (structural validation)
            if is_valid_field_name(text, context='form'):
                # Verify [N] code exists nearby
                if has_nearby_code(lines, i):
                    field_labels.append(text)
    
    # Deduplicate consecutive identical labels
    prev_label = None
    for label in field_labels:
        if label != prev_label:
            results.append({
                "form_name": form_name,
                "field_name": label,
                "page": page_num
            })
            prev_label = label
    
    return results, form_name

def is_valid_field_name(text, context='form'):
    """Check if text is a valid field name using structural rules only."""
    if not text or len(text) < 2:
        return False
    
    # Skip [N] codes
    if re.match(r'^\[\d+\]$', text):
        return False
    
    # Skip pure numbers
    if re.match(r'^\d+\.?$', text):
        return False
    
    # Skip dates (various formats)
    if re.match(r'^\d{2}[A-Za-z]{3}\d{4}$', text) or re.match(r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$', text):
        return False
    
    # Skip answer options with leading number-dash pattern
    if re.match(r'^\d+\s*[-–]\s*', text):
        return False
    
    # Skip export codes in non-export contexts (short all-caps with no spaces/underscores)
    if context != 'export_code_definitions':
        if len(text) <= 12 and text.isupper() and ' ' not in text and '_' not in text:
            # Allow specific medical abbreviations in vitals context
            if context == 'vitals' and any(pattern in text for pattern in ['SpO', 'BP', 'HR', 'RR']):
                pass
            else:
                # Pure short uppercase codes without underscores are machine identifiers
                if re.match(r'^[A-Z]{3,}[0-9]*[A-Z]*$', text) and not any(c.islower() for c in text):
                    return False
    
    # Structural filter: require minimum alphabetic content
    alpha_chars = sum(c.isalpha() for c in text)
    if alpha_chars < 3:
        return False
    
    # Skip very long text (likely instructions)
    if len(text) > 250:
        return False
    
    # In table/form context, skip very short isolated words that are structural
    if context in ['table', 'form'] and len(text.split()) == 1 and len(text) <= 4:
        # Single-char or very short text is likely a column header fragment
        return False
    
    # Skip text that's mostly punctuation or symbols
    alnum_chars = sum(c.isalnum() for c in text)
    if alnum_chars < len(text) * 0.5:
        return False
    
    return True

def has_nearby_code(lines, idx):
    """Check if a [N] code exists near this line."""
    line = lines[idx]
    
    # Check next few lines (within 20 points vertically)
    for i in range(idx + 1, min(idx + 5, len(lines))):
        next_line = lines[i]
        if next_line.y0 - line.y0 > 20:
            break
        if re.search(r'\[\d+\]', next_line.text):
            return True
    
    # Check same line area (adjacent x, similar y)
    for other in lines:
        if abs(other.y0 - line.y0) < 5 and other.x0 > line.x1 and other.x0 < line.x1 + 50:
            if re.search(r'\[\d+\]', other.text):
                return True
    
    return False
