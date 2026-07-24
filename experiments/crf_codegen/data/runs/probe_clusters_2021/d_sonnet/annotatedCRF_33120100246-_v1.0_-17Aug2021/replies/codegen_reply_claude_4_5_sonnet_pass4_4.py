I'll analyze the issues and rewrite the program to fix them while maintaining existing coverage.

Key problems to address:
1. **Cluster 0 & 3 & 4 (0% coverage)**: Title/disclaimer pages and answer option pages - these appear to be non-field pages, which is correct to skip
2. **Page 13 missing fields**: The schedule table continues on page 13 but wasn't extracted
3. **False positives**: "Urinalysis" as form name, and C-SSRS question text extracted as fields
4. **Hardcoded filters**: Need to replace with structural rules

Let me rewrite the program:

```python
import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip pages that are purely instructional/legal (copyright, disclaimers)
        if is_disclaimer_page(lines):
            continue
        
        # Skip answer option description pages (red text, right column only)
        if is_answer_legend_page(lines):
            continue
        
        form_name = find_form_title(lines)
        
        if is_schedule_page(lines):
            results.extend(extract_schedule_fields(lines, page_num))
        elif is_lab_collection_page(lines):
            results.extend(extract_lab_fields(lines, page_num))
        elif is_cssrs_data_page(lines):
            results.extend(extract_cssrs_data_fields(lines, form_name, page_num))
        elif form_name:
            results.extend(extract_generic_fields(lines, form_name, page_num))
    
    return results

def is_disclaimer_page(lines):
    """Detect title/disclaimer/copyright pages with no data entry fields."""
    # Look for copyright, disclaimer markers in upper portion
    has_copyright = False
    has_disclaimer = False
    has_field_codes = False
    
    for i, line in enumerate(lines):
        text_lower = line.text.lower()
        
        # Check for copyright/contact info
        if i < 40 and any(marker in text_lower for marker in ['©', 'columbia.edu', 'reprints', 'nyspi.columbia']):
            has_copyright = True
        
        # Check for disclaimer heading
        if i < 30 and text_lower.strip() == 'disclaimer:':
            has_disclaimer = True
        
        # Check for field codes (brackets with capital letters)
        if re.search(r'\[[A-Z]{2}[A-Z0-9]+\]', line.text):
            has_field_codes = True
    
    # Title/disclaimer pages have copyright or disclaimer but no field codes
    return (has_copyright or has_disclaimer) and not has_field_codes

def is_answer_legend_page(lines):
    """Detect pages showing only answer scale descriptions (red text, right side)."""
    # These pages have predominantly red text on the right (x > 340)
    # and minimal or no black text with field structure
    red_right_lines = 0
    content_lines = 0
    
    for line in lines:
        if line.size > 6 and len(line.text.strip()) > 15:
            content_lines += 1
            if line.non_black and line.x0 > 340:
                red_right_lines += 1
    
    # If most substantial content is red and on the right, it's a legend
    if content_lines > 5 and red_right_lines / content_lines > 0.75:
        return True
    
    return False

def find_form_title(lines):
    """Find the form title - typically blue, large, near top."""
    for line in lines[:20]:
        # Blue or large text in header area
        if (line.non_black or line.size >= 13) and line.y0 < 150:
            text = line.text.strip()
            # Must be substantial, not a technical marker
            if len(text) > 8 and not text.startswith('['):
                # Skip generic headers
                if not re.match(r'^(Schedule|CHANGE HISTORY|PAGES?|Row \d+)$', text, re.IGNORECASE):
                    return text
    return ""

def is_schedule_page(lines):
    """Check if this is a Schedule of Assessments page."""
    for line in lines[:40]:
        if 'Schedule of Assessments' in line.text or 'Schedule_' in line.text:
            return True
    return False

def extract_schedule_fields(lines, page_num):
    """Extract page labels from schedule tables."""
    results = []
    seen_fields = set()
    
    for i, line in enumerate(lines):
        # Blue hyperlinks in the label column (around x=270-290)
        if line.non_black and 240 < line.x0 < 320 and line.size < 11:
            text = line.text.strip()
            
            # Must be substantial
            if len(text) < 3:
                continue
            
            # Skip column headers by position (very top of table)
            if line.y0 < 120:
                continue
            
            # Skip technical markers
            if text.startswith('[') or text.startswith('('):
                continue
            
            # Check if this continues on next line(s)
            full_text = text
            j = i + 1
            while j < len(lines) and j < i + 4:
                next_line = lines[j]
                # Same column, close vertical spacing
                if next_line.non_black and 240 < next_line.x0 < 320 and next_line.y0 - lines[j-1].y0 < 18:
                    full_text += ' ' + next_line.text.strip()
                    j += 1
                else:
                    break
            
            # Deduplicate
            if full_text not in seen_fields and len(full_text) > 3:
                seen_fields.add(full_text)
                results.append({
                    'form_name': 'Schedule of Assessments',
                    'field_name': full_text,
                    'page': page_num
                })
    
    return results

def is_lab_collection_page(lines):
    """Check if this is a laboratory/specimen collection form."""
    has_lab_codes = False
    has_specimen_indicator = False
    
    for line in lines[:50]:
        # Lab field codes
        if re.search(r'\[LB[A-Z]+\d*\]', line.text):
            has_lab_codes = True
        
        # Specimen type indicators in header
        if line.y0 < 120 and any(term in line.text for term in ['Urinalysis', 'Blood', 'Serum', 'Plasma', 'Collected']):
            has_specimen_indicator = True
    
    return has_lab_codes and has_specimen_indicator

def extract_lab_fields(lines, page_num):
    """Extract fields from laboratory forms."""
    results = []
    
    # Determine specimen type from header (not a form name itself)
    form_name = "Laboratory/Specimen Collection"
    for line in lines[:25]:
        if line.y0 < 100 and line.size > 8:
            text = line.text.strip()
            # Look for specimen descriptors that are more than just type names
            if len(text) > 15 and not text.startswith('['):
                # Must contain "collection" or similar to be a form title
                if any(kw in text.lower() for kw in ['collection', 'sample', 'laboratory', 'assessment']):
                    form_name = text
                    break
    
    seen_codes = set()
    for i, line in enumerate(lines):
        # Field codes in brackets
        match = re.search(r'\[([A-Z]{2}[A-Z0-9]+)\]', line.text)
        if match:
            code = match.group(1)
            
            # Must be a field code prefix (LB, VS, EG, etc.)
            if not re.match(r'^(LB|VS|EG|DM|MH|CM|AE)', code[:2]):
                continue
            
            if code not in seen_codes:
                seen_codes.add(code)
                
                # Find descriptive label
                label = find_field_label_near(lines, i, line)
                
                # Label must be substantial and descriptive
                if label and len(label) > 8:
                    results.append({
                        'form_name': form_name,
                        'field_name': label,
                        'page': page_num
                    })
    
    return results

def find_field_label_near(lines, current_idx, code_line):
    """Find descriptive label near a field code."""
    # Look above (column header)
    for line in lines[:current_idx]:
        if abs(line.x0 - code_line.x0) < 40 and 5 < code_line.y0 - line.y0 < 50:
            text = line.text.strip()
            if len(text) > 3 and not text.startswith('['):
                return text
    
    # Look to the left on same row
    for line in lines:
        if line.x0 < code_line.x0 - 50 and abs(line.y0 - code_line.y0) < 8:
            text = line.text.strip()
            if len(text) > 3 and not text.startswith('['):
                return text
    
    return None

def is_cssrs_data_page(lines):
    """Check if this is a C-SSRS data entry page (not title/legend)."""
    has_cssrs_code = False
    has_data_structure = False
    is_title_page = False
    
    for i, line in enumerate(lines):
        # CSS field codes
        if '[CSS' in line.text:
            has_cssrs_code = True
        
        # Data structure: "Row" labels with numbers
        if i < 100 and line.bold and re.match(r'^Row \d+$', line.text.strip()):
            has_data_structure = True
        
        # Title page markers
        if i < 40 and ('COLUMBIA-SUICIDE' in line.text or 'RATING SCALE' in line.text):
            is_title_page = True
    
    return has_cssrs_code and has_data_structure and not is_title_page

def extract_cssrs_data_fields(lines, form_name, page_num):
    """Extract fields from C-SSRS data entry pages."""
    results = []
    
    # These pages have structured rows with field labels and codes
    # Field labels are typically bold, left column (x < 200)
    # But NOT questions - those are longer prose
    
    seen_labels = set()
    
    for i, line in enumerate(lines):
        # Bold labels in left area
        if line.bold and line.x0 < 200 and 7 < line.size < 11:
            text = line.text.strip()
            
            # Skip row markers
            if re.match(r'^Row \d+$', text):
                continue
            
            # Skip answer options
            if text in ['Yes', 'No'] or re.match(r'^\d+$', text):
                continue
            
            # Skip technical markers
            if text.startswith('[') or text.startswith('('):
                continue
            
            # Field labels are typically short (< 60 chars) and descriptive
            # Questions with "?" are longer and should be skipped
            if 5 < len(text) < 60 and '?' not in text:
                # Assemble multi-line labels
                full_text = text
                j = i + 1
                while j < len(lines) and j < i + 3:
                    next_line = lines[j]
                    if next_line.x0 < 200 and next_line.y0 - lines[j-1].y0 < 18:
                        next_text = next_line.text.strip()
                        if next_text and not next_text.startswith('[') and len(next_text) < 60:
                            full_text += ' ' + next_text
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # Final filter: must contain key field indicator words
                if any(kw in full_text for kw in ['Date', 'Lethality', 'Method', 'Potential', 'Actual', 'Time']):
                    if full_text not in seen_labels:
                        seen_labels.add(full_text)
                        results.append({
                            'form_name': form_name,
                            'field_name': full_text,
                            'page': page_num
                        })
    
    return results

def extract_generic_fields(lines, form_name, page_num):
    """Extract fields from other form types."""
    results = []
    seen_fields = set()
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Field labels in left area, reasonable size
        if line.x0 < 220 and 7 < line.size < 12:
            text = line.text.strip()
            
            # Must be substantial
            if len(text) < 5:
                i += 1
                continue
            
            # Skip technical markers
            if text.startswith('[') or text.startswith('(') or re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip answer options
            if text in ['Yes', 'No'] or re.match(r'^\d+$', text):
                i += 1
                continue
            
            # Assemble multi-line text
            full_text = text
            j = i + 1
            while j < len(lines) and j < i + 5:
                next_line = lines[j]
                if abs(next_line.x0 - line.x0) < 40 and next_line.y0 - lines[j-1].y0 < 20 and next_line.x0 < 220:
                    next_text = next_line.text.strip()
                    if next_text and not next_text.startswith('['):
                        full_text += ' ' + next_text
                        j += 1
                    else:
                        break
                else:
                    break
            
            # Fields are typically questions (with "?") or multi-word labels
            if ('?' in full_text or len(full_text.split()) >= 3) and full_text not in seen_fields:
                seen_fields.add(full_text)
                results.append({
                    'form_name': form_name,
                    'field_name': full_text,
                    'page': page_num
                })
            
            i = j
            continue
        
        i += 1
    
    return results
```
