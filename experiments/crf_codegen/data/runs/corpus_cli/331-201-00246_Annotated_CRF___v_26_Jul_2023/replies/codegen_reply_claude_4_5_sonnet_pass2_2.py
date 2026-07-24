Looking at the problems, I can see three main issues to fix:

1. **Page 12** (Change History page) is being extracted when it should be skipped - it contains version numbers and change log entries, not data-entry fields
2. **Pages 20, 25** (cluster 1 - table of contents/visit schedules) are not being extracted but contain real data
3. **Page 42** extracted "Bilateral Oophorectomy Bilateral Tubal Ligation" which appears to be answer options, not a field label
4. **Pages 479, 777, 778** (clusters 4, 5 - C-SSRS disclaimer pages) are correctly being skipped

Let me rewrite the program to fix these issues:

```python
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
        
        # Check if this is a schedule/TOC table layout
        if is_schedule_table(lines):
            page_fields = extract_schedule_fields(lines, current_form, page_num)
        else:
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
    
    # Skip disclaimer/copyright pages - look for disclaimer header and copyright text
    has_disclaimer = any("disclaimer:" in line.text.lower() for line in lines[:50])
    has_copyright = any("research foundation for mental hygiene" in line.text.lower() 
                       for line in lines[:50])
    if has_disclaimer and has_copyright:
        return True
    
    # Skip Change History pages - detect by "Version" column header and version numbers
    # Look for version number pattern (0.3, 0.4, etc) combined with date pattern
    version_pattern_count = 0
    date_pattern_count = 0
    for line in lines[:50]:
        if re.match(r'^\d+\.\d+$', line.text.strip()):
            version_pattern_count += 1
        if re.match(r'^\d{2}[A-Za-z]{3}\d{4}$', line.text.strip()):
            date_pattern_count += 1
    
    # If we see multiple version numbers and dates, it's a change history page
    if version_pattern_count >= 3 and date_pattern_count >= 3:
        return True
    
    return False


def is_schedule_table(lines):
    """Detect if page is a schedule/visit table with columns."""
    # Look for column headers in upper portion
    headers_found = []
    for line in lines[:20]:
        if line.y0 < 150 and line.bold:
            text_lower = line.text.lower()
            if text_lower in ['visit num', 'visit label', 'page num', 'page label', 'dynamic?']:
                headers_found.append(text_lower)
    
    # Need at least 3 characteristic headers
    return len(headers_found) >= 3


def extract_schedule_fields(lines, form_name, page_num):
    """Extract fields from schedule/TOC table pages."""
    fields = []
    
    # These pages have blue links as field labels in the "Page Label" column
    # They typically appear at x~290
    for line in lines:
        # Skip if not in content area
        if line.y0 < 150 or line.y0 > 780:
            continue
        
        # Blue text in Page Label column (x around 290)
        if line.non_black and 280 < line.x0 < 320:
            text = line.text.strip()
            
            # Skip structural noise
            if is_structural_noise(text):
                continue
            
            # Skip if it's a column header
            if text.lower() in ['page label', 'description of dynamic']:
                continue
            
            # This is likely a field label (page/form title)
            if text and len(text) > 2:
                fields.append({
                    "form_name": form_name,
                    "field_name": text,
                    "page": page_num
                })
    
    return fields


def extract_form_title(lines):
    """Extract form/section title from large colored header."""
    for line in lines[:40]:
        if line.y0 > 300:
            break
        
        # Form titles are typically 12-16.5pt, colored, bold or distinct
        if line.size >= 12.0 and line.size <= 18.0:
            if line.non_black or line.bold:
                text = line.text.strip()
                if text and not is_structural_noise(text):
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
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        if should_skip_line(line):
            i += 1
            continue
        
        if is_potential_field(line):
            # Collect this line and potential continuation lines
            field_text = line.text.strip()
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
                    j += 1
                else:
                    break
            
            # Clean and validate the field
            field_text = clean_field_text(field_text)
            if is_valid_field(field_text):
                fields.append({
                    "form_name": form_name,
                    "field_name": field_text,
                    "page": page_num
                })
            
            i = j
        else:
            i += 1
    
    return fields


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


def is_valid_field(field_text):
    """Validate that extracted text is a real field, not noise."""
    if not field_text:
        return False
    
    lower_text = field_text.lower()
    
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
    ]
    
    for pattern in non_field_patterns:
        if re.match(pattern, lower_text):
            return False
    
    # Reject very short text
    if len(field_text) < 3:
        return False
    
    # Reject if it looks like a column header (short, generic)
    if len(field_text.split()) <= 2 and any(keyword in lower_text for keyword in 
        ['sample', 'date', 'time', 'status', 'number', 'barcode', 'visit', 'page']):
        return False
    
    # Filter out answer options that appear as standalone text
    # These are typically short phrases that appear in sequence (multiple choice)
    # They often have clinical terminology pattern: "Condition Condition"
    if re.match(r'^[A-Z][a-z]+\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)*$', field_text):
        # This looks like "Bilateral Oophorectomy" pattern - likely an answer option
        # Real field labels usually have question structure or more context
        if len(field_text.split()) <= 4 and len(field_text) < 50:
            return False
    
    return True
```
