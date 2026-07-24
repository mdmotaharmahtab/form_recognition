import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Detect and skip non-field pages
        if is_skip_page(lines):
            continue
        
        # Extract form name from title header
        form_title = extract_form_title(lines)
        if form_title:
            current_form = form_title
        
        # Check if this is a schedule/TOC table layout - SKIP extraction
        if is_schedule_table(lines):
            continue
        
        # Check if this is a TOC section listing page - SKIP extraction
        if is_toc_listing_page(lines):
            continue
        
        # Check if this is an empty repeatable row instruction page - SKIP
        if is_empty_repeatable_page(lines):
            continue
        
        # Extract fields from page
        page_fields = extract_fields_from_page(lines, current_form, page_num)
        records.extend(page_fields)
    
    return records


def is_skip_page(lines):
    """Detect pages that should be skipped based on structural markers."""
    text_content = [line.text for line in lines[:30]]
    text_str = " ".join(text_content).lower()
    
    # Skip annotated CRF title page
    if any("annotated crf" in line.text.lower() for line in lines[:10]):
        return True
    
    # Skip disclaimer/copyright pages
    has_disclaimer = any("disclaimer:" in line.text.lower() for line in lines[:50])
    has_copyright = any("research foundation for mental hygiene" in line.text.lower() 
                       for line in lines[:50])
    if has_disclaimer and has_copyright:
        return True
    
    # Skip Change History pages - detect by version numbers and dates
    version_pattern_count = 0
    date_pattern_count = 0
    for line in lines[:50]:
        if re.match(r'^\d+\.\d+$', line.text.strip()):
            version_pattern_count += 1
        if re.match(r'^\d{2}[A-Za-z]{3}\d{4}$', line.text.strip()):
            date_pattern_count += 1
    
    if version_pattern_count >= 3 and date_pattern_count >= 3:
        return True
    
    return False


def is_schedule_table(lines):
    """Detect if page is a schedule/visit table with columns."""
    headers_found = []
    for line in lines[:20]:
        if line.y0 < 150 and line.bold:
            text_lower = line.text.lower()
            if text_lower in ['visit num', 'visit label', 'page num', 'page label', 'dynamic?']:
                headers_found.append(text_lower)
    
    return len(headers_found) >= 3


def is_toc_listing_page(lines):
    """Detect if page is a TOC listing with numbered section titles."""
    # Look for pattern: multiple lines with section numbers (3.152., 3.153., etc)
    # in blue color, large font
    section_pattern_count = 0
    for line in lines:
        # TOC entries are typically blue, 15pt, left-aligned around x=159
        if line.non_black and line.size >= 14.0 and line.size <= 16.0:
            if 150 < line.x0 < 170:
                text = line.text.strip()
                # Match patterns like "3.152." or similar section numbers
                if re.match(r'^\d+\.\d+\.', text):
                    section_pattern_count += 1
    
    # If we see 10+ section-numbered entries, it's a TOC page
    return section_pattern_count >= 10


def is_empty_repeatable_page(lines):
    """Detect pages with only repeatable row instructions and no actual fields."""
    # Look for pages with:
    # 1. A form title header (large blue text)
    # 2. "(Repeatable row added with Add Row button)" text
    # 3. Very few other content lines
    
    has_repeatable_instruction = False
    content_line_count = 0
    
    for line in lines:
        text = line.text.strip().lower()
        
        # Count actual content lines (exclude headers, footers, page numbers)
        if line.y0 > 150 and line.y0 < 750 and not line.non_black and line.size >= 9.0:
            if text and len(text) > 3 and not re.match(r'^page \d+ of \d+$', text):
                content_line_count += 1
        
        # Check for repeatable row instruction
        if "repeatable row" in text and "add row button" in text:
            has_repeatable_instruction = True
    
    # If we have the instruction but very few other lines, skip this page
    return has_repeatable_instruction and content_line_count < 5


def extract_form_title(lines):
    """Extract form/section title from large colored header."""
    for line in lines[:40]:
        if line.y0 > 300:
            break
        
        # Form titles are typically 12-18pt, colored or bold
        if line.size >= 12.0 and line.size <= 18.0:
            if line.non_black or line.bold:
                text = line.text.strip()
                if text and not is_structural_noise(text):
                    # Don't treat TOC section numbers as form titles
                    if re.match(r'^\d+\.\d+\.', text):
                        continue
                    return text
    
    return ""


def is_structural_noise(text):
    """Check if text is structural noise, not a real title."""
    noise_patterns = [
        r'^\d+\s*$',
        r'^page \d+ of \d+$',
        r'^row \d+$',
        r'^\[.*\]$',
        r'^visit num',
        r'^schedule_',
        r'^repeatable row',
    ]
    lower_text = text.lower()
    return any(re.match(pat, lower_text) for pat in noise_patterns)


def extract_fields_from_page(lines, form_name, page_num):
    """Extract data-entry fields from a page."""
    fields = []
    
    # First pass: identify instructional blocks to exclude
    instruction_regions = identify_instruction_regions(lines)
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        if should_skip_line(line):
            i += 1
            continue
        
        # Skip if this line is within an instruction region
        if is_in_instruction_region(line, instruction_regions):
            i += 1
            continue
        
        if is_potential_field(line):
            # Collect this line and potential continuation lines
            field_text = line.text.strip()
            field_lines = [line]
            j = i + 1
            
            # Join wrapped lines
            while j < len(lines):
                next_line = lines[j]
                
                if should_skip_line(next_line):
                    break
                if abs(next_line.x0 - line.x0) > 30:
                    break
                if next_line.y0 - line.y0 > 50:
                    break
                if next_line.size >= 9.0 and next_line.y0 - line.y0 > 30:
                    break
                
                if is_potential_field(next_line):
                    field_text += " " + next_line.text.strip()
                    field_lines.append(next_line)
                    j += 1
                else:
                    break
            
            # Clean and validate the field
            field_text = clean_field_text(field_text)
            if is_valid_field(field_text, field_lines, lines):
                fields.append({
                    "form_name": form_name,
                    "field_name": field_text,
                    "page": page_num
                })
            
            i = j
        else:
            i += 1
    
    return fields


def identify_instruction_regions(lines):
    """Identify blocks of instructional text that should not be extracted."""
    regions = []
    
    # Look for disclaimer blocks
    for i, line in enumerate(lines):
        text = line.text.strip()
        if "Disclaimer:" in text or "This scale is intended" in text:
            # Mark region from this line downward
            regions.append({
                'start_y': line.y0,
                'end_y': line.y0 + 200,  # Typical disclaimer block height
                'type': 'disclaimer'
            })
    
    # Look for rating scale instruction blocks
    # These often have phrases like "The following features should be rated"
    for i, line in enumerate(lines):
        text = line.text.lower()
        if "should be rated" in text or "most severe" in text:
            # Look for surrounding context to define region
            start_y = line.y0 - 20
            end_y = line.y0 + 150
            regions.append({
                'start_y': start_y,
                'end_y': end_y,
                'type': 'instruction'
            })
    
    return regions


def is_in_instruction_region(line, instruction_regions):
    """Check if a line falls within an instruction region."""
    for region in instruction_regions:
        if region['start_y'] <= line.y0 <= region['end_y']:
            return True
    return False


def should_skip_line(line):
    """Check if line should be skipped entirely."""
    text = line.text.strip()
    
    # Skip technical codes (red text with brackets)
    if line.non_black and ('[' in text or 'TYPE:' in text or 'VISIBILITY:' in text):
        return True
    
    # Skip red text in typical size range for codes
    if line.non_black and line.size < 11.0:
        return True
    
    # Skip page numbers
    if re.match(r'^page \d+ of \d+$', text.lower()):
        return True
    
    # Skip very small text
    if line.size < 8.5:
        return True
    
    # Skip footer region
    if line.y0 > 780:
        return True
    
    # Skip header region
    if line.y0 < 115:
        return True
    
    return False


def is_potential_field(line):
    """Check if line looks like a field label."""
    text = line.text.strip()
    
    # Must be black text
    if line.non_black:
        return False
    
    # Typical field label size
    if line.size < 8.5 or line.size > 12.0:
        return False
    
    # Must have actual content
    if not text or len(text) < 2:
        return False
    
    # Should not be pure structural markers
    if is_structural_noise(text):
        return False
    
    return True


def clean_field_text(text):
    """Clean up extracted field text."""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove trailing punctuation artifacts
    text = re.sub(r'\s*[•\-]+\s*$', '', text)
    
    return text


def is_valid_field(field_text, field_lines, all_lines):
    """Validate that extracted text is a real field, not noise."""
    if not field_text:
        return False
    
    lower_text = field_text.lower()
    
    # Filter out disclaimer/instruction phrases
    instruction_phrases = [
        'disclaimer:',
        'this scale is intended',
        'the following features',
        'should be rated',
        'most severe',
        'ask about time',
        'was feeling the most',
    ]
    for phrase in instruction_phrases:
        if phrase in lower_text:
            return False
    
    # Filter out common non-fields by structural patterns
    non_field_patterns = [
        r'^x\s*$',
        r'^\d+\s*$',
        r'^yes\s*$',
        r'^no\s*$',
        r'^scan\s*$',
        r'^collected\s*$',
        r'^not collected\s*$',
        r'^row \d+$',
        r'^version',
        r'^date$',
        r'^details$',
        r'^changed by',
        r'^visit number',
        r'^visit label',
        r'^page num',
        r'^page label',
        r'^dynamic',
        r'^description of dynamic',
        r'^sample status',
        r'^timepoint',
        r'^barcode',
        r'^backup',
        r'^time of collection',
        r'^trial day',
        r'^start date$',
        r'^stop date$',
        r'^initial contact$',
        r'^second contact',
        r'^third contact',
        r'^certified letter',
        r'^method of contact',
        r'^type of contact',
        r'^\(repeatable row',
        r'^intensity of ideation$',
        r'^past 3 month$',
    ]
    
    for pattern in non_field_patterns:
        if re.match(pattern, lower_text):
            return False
    
    # Reject very short text
    if len(field_text) < 3:
        return False
    
    # Reject if it looks like a column header
    if len(field_text.split()) <= 2 and any(keyword in lower_text for keyword in 
        ['sample', 'date', 'time', 'status', 'number', 'barcode', 'visit', 'page']):
        return False
    
    # Filter out medical procedure/condition names that are answer options
    # These typically appear in groups and are Title Case
    if is_answer_option(field_text, field_lines, all_lines):
        return False
    
    # Filter out rating scale items like "(1) Wish to be dead"
    if re.match(r'^\(\d+\)', field_text):
        return False
    
    return True


def is_answer_option(field_text, field_lines, all_lines):
    """Detect if text is an answer option rather than a field label."""
    
    # Pattern 1: Title Case medical terms (likely answer options)
    # "Bilateral Oophorectomy" - Title Case, 2-4 words, < 50 chars
    if re.match(r'^[A-Z][a-z]+(\s+[A-Z][a-z]+){1,3}$', field_text):
        if len(field_text) < 50 and len(field_text.split()) <= 4:
            # Check if there are similar formatted items nearby (answer list pattern)
            if has_nearby_similar_items(field_lines[0], all_lines):
                return True
    
    # Pattern 2: Short procedure/test names without question context
    medical_keywords = [
        'oophorectomy', 'tubal ligation', 'hysterectomy', 
        'temperature', 'respiratory rate', 'orthostatic',
        'imp administration', 'predose', 'postdose',
    ]
    lower_text = field_text.lower()
    if any(kw in lower_text for kw in medical_keywords):
        # If it's short and lacks question markers, likely an answer option
        if len(field_text) < 60 and '?' not in field_text:
            # Check if preceded by a checkbox or bullet point pattern
            if has_checkbox_pattern_nearby(field_lines[0], all_lines):
                return True
    
    return False


def has_nearby_similar_items(line, all_lines):
    """Check if there are similar formatted items nearby (suggesting answer list)."""
    similar_count = 0
    line_idx = all_lines.index(line) if line in all_lines else -1
    
    if line_idx == -1:
        return False
    
    # Check 5 lines before and after
    for i in range(max(0, line_idx - 5), min(len(all_lines), line_idx + 6)):
        if i == line_idx:
            continue
        
        other = all_lines[i]
        # Similar if: same x position, similar size, within 100px vertically
        if abs(other.x0 - line.x0) < 20 and abs(other.size - line.size) < 1.0:
            if abs(other.y0 - line.y0) < 100:
                text = other.text.strip()
                # Title Case pattern
                if re.match(r'^[A-Z][a-z]+(\s+[A-Z][a-z]+){1,3}$', text):
                    similar_count += 1
    
    # If we find 2+ similar items, this is likely an answer list
    return similar_count >= 2


def has_checkbox_pattern_nearby(line, all_lines):
    """Check if line appears to be part of a checkbox/option list."""
    line_idx = all_lines.index(line) if line in all_lines else -1
    
    if line_idx == -1:
        return False
    
    # Look for checkbox markers (small text, specific symbols) within 50px horizontally
    for i in range(max(0, line_idx - 3), min(len(all_lines), line_idx + 4)):
        other = all_lines[i]
        
        # Check for checkbox-like markers to the left
        if other.x0 < line.x0 - 10 and abs(other.y0 - line.y0) < 15:
            text = other.text.strip()
            if text in ['□', '☐', 'X', 'x', '○', '●'] or len(text) == 1:
                return True
    
    return False
