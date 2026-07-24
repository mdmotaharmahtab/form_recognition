```python
import re
from collections import defaultdict

def extract(pages):
    records = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Identify page layout type
        layout_type = identify_layout(lines)
        
        if layout_type == "schedule_table":
            # Schedule tables: no data-entry fields, skip
            continue
        elif layout_type == "cssrs_intensity_lifetime":
            # C-SSRS Intensity tables with Lifetime/Past 3 Month columns
            extract_cssrs_intensity_lifetime(lines, page_num, records)
        elif layout_type == "cssrs_intensity_since_last":
            # C-SSRS Intensity tables with "Since Last Visit" header
            extract_cssrs_intensity_since_last(lines, page_num, records)
        elif layout_type == "cssrs_disclaimer":
            # Disclaimer page - no fields
            continue
        elif layout_type == "cssrs_intensity_header_only":
            # Header-only page with no actual fields
            continue
        else:
            # Other pages - check for standard form fields
            extract_standard_fields(lines, page_num, records)
    
    # Deduplicate while preserving order
    seen = set()
    unique_records = []
    for rec in records:
        key = (rec['form_name'], rec['field_name'], rec['page'])
        if key not in seen:
            seen.add(key)
            unique_records.append(rec)
    
    return unique_records

def identify_layout(lines):
    """Identify the layout type of the page."""
    # Check for schedule table: has "Visit Num", "Visit Label", "Page Num", "Page Label" headers
    has_visit_num = any(line.text.strip() == "Visit Num" and line.bold for line in lines)
    has_page_num = any(line.text.strip() == "Page Num" and line.bold for line in lines)
    if has_visit_num and has_page_num:
        return "schedule_table"
    
    # Check for C-SSRS disclaimer page
    has_disclaimer = any("Disclaimer:" in line.text for line in lines)
    has_version = any("Version 1/14/09" in line.text for line in lines)
    has_columbia = any("COLUMBIA-SUICIDE SEVERITY" in line.text for line in lines)
    if has_disclaimer and has_version and has_columbia:
        return "cssrs_disclaimer"
    
    # Check for C-SSRS Intensity with Lifetime/Past 3 Month columns
    has_intensity = any(line.text.strip() == "Intensity of Ideation" and line.y0 < 150 for line in lines)
    has_lifetime = any(line.text.strip() == "Lifetime" and line.y0 < 150 for line in lines)
    has_past_3_month = any(line.text.strip() == "Past 3 Month" and line.y0 < 150 for line in lines)
    if has_intensity and has_lifetime and has_past_3_month:
        return "cssrs_intensity_lifetime"
    
    # Check for C-SSRS Intensity with "Since Last Visit" header
    has_since_last = any(line.text.strip() == "Since Last Visit" and line.y0 < 150 for line in lines)
    if has_intensity and has_since_last:
        # Check if this is just a header page with no actual content
        # Look for actual field content (bold text in left column below header)
        has_field_content = False
        for line in lines:
            if (line.y0 > 150 and line.bold and not line.non_black and 
                line.x0 < 100 and len(line.text.strip()) > 10 and
                not re.match(r'^Row \d+$', line.text.strip())):
                has_field_content = True
                break
        
        if has_field_content:
            return "cssrs_intensity_since_last"
        else:
            return "cssrs_intensity_header_only"
    
    return "standard"

def extract_cssrs_intensity_lifetime(lines, page_num, records):
    """Extract fields from C-SSRS Intensity pages with Lifetime/Past 3 Month columns."""
    form_name = "C-SSRS Intensity of Ideation"
    
    # Look for field labels - these are bold black text in the left column
    # They appear at x ~61-62 and are questions/labels
    for i, line in enumerate(lines):
        # Skip header rows
        if line.y0 < 150:
            continue
        
        # Skip red text (machine codes)
        if line.non_black and '[' in line.text:
            continue
        
        # Look for bold black text in left column (field labels)
        if line.bold and not line.non_black and line.x0 < 100:
            text = line.text.strip()
            
            # Skip "Row X" labels
            if re.match(r'^Row \d+$', text):
                continue
            
            # Skip structural headers
            if text in ["Most severe ideation"]:
                continue
            
            # Valid field label - check if it continues on next lines
            field_text = text
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # Continue if next line is close, same column, bold, black
                if (next_line.bold and not next_line.non_black and 
                    next_line.x0 < 100 and abs(next_line.x0 - line.x0) < 20 and
                    next_line.y0 - line.y1 < 30 and
                    not '[' in next_line.text):
                    next_text = next_line.text.strip()
                    # Stop at next field marker
                    if re.match(r'^Row \d+$', next_text):
                        break
                    field_text += ' ' + next_text
                    j += 1
                else:
                    break
            
            # Add if it looks like a real field (not just a single word)
            if len(field_text) > 10 or '?' in field_text:
                records.append({
                    'form_name': form_name,
                    'field_name': field_text,
                    'page': page_num
                })

def extract_cssrs_intensity_since_last(lines, page_num, records):
    """Extract fields from C-SSRS Intensity pages with 'Since Last Visit' header."""
    form_name = "C-SSRS Intensity of Ideation - Since Last Visit"
    
    # Look for field labels - bold black text in left column, below the headers
    # These are actual question labels, not structural text
    # We need to identify complete field labels that span multiple lines
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip header area (top ~150 pixels)
        if line.y0 < 150:
            i += 1
            continue
        
        # Skip red text (machine codes)
        if line.non_black and '[' in line.text:
            i += 1
            continue
        
        # Look for bold black text in left column
        if line.bold and not line.non_black and line.x0 < 100:
            text = line.text.strip()
            
            # Skip "Row X" labels
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip structural headers that aren't questions
            if text in ["Most severe ideation"]:
                i += 1
                continue
            
            # Start collecting a potential field label
            field_text = text
            j = i + 1
            
            # Continue collecting lines that are part of the same field
            while j < len(lines):
                next_line = lines[j]
                
                # Stop if we hit red text (machine code)
                if next_line.non_black and '[' in next_line.text:
                    break
                
                # Continue if next line is close, same column, bold, black
                if (next_line.bold and not next_line.non_black and 
                    next_line.x0 < 100 and abs(next_line.x0 - line.x0) < 20 and
                    next_line.y0 - lines[j-1].y1 < 30):
                    next_text = next_line.text.strip()
                    
                    # Stop at next field marker
                    if re.match(r'^Row \d+$', next_text):
                        break
                    
                    # Stop at structural headers
                    if next_text in ["Most severe ideation"]:
                        break
                    
                    field_text += ' ' + next_text
                    j += 1
                else:
                    break
            
            # Only add if it's a complete field label (question or longer phrase)
            # Must be substantial enough to be a real field
            if len(field_text) > 15 or '?' in field_text:
                records.append({
                    'form_name': form_name,
                    'field_name': field_text,
                    'page': page_num
                })
            
            # Move to the next unprocessed line
            i = j
        else:
            i += 1

def extract_standard_fields(lines, page_num, records):
    """Extract fields from standard form pages."""
    # Look for form title: large blue text
    form_title = None
    for line in lines:
        if line.size >= 15.0 and line.non_black and '#004c99' in str(line):
            form_title = line.text.strip()
            break
    
    if not form_title:
        return
    
    # Extract fields - black text that looks like field labels
    for i, line in enumerate(lines):
        # Skip red text (machine codes)
        if line.non_black and '[' in line.text:
            continue
        
        # Skip page numbers
        if re.match(r'Page \d+ of \d+', line.text.strip()):
            continue
        
        # Look for field labels - black text, reasonable size
        if not line.non_black and line.size >= 9.0 and line.size <= 12.0:
            text = line.text.strip()
            
            # Skip empty lines
            if not text:
                continue
            
            # Skip pure numbers or dates
            if re.match(r'^\d+$', text) or re.match(r'^\d{1,2}[A-Za-z]{3,9}\d{4}$', text):
                continue
            
            # Check if this looks like a field label (longer phrases or questions)
            if len(text) > 5 and not text.startswith('['):
                # Collect continuation lines
                field_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if (not next_line.non_black and 
                        next_line.y0 - line.y1 < 20 and 
                        abs(next_line.x0 - line.x0) < 20 and
                        next_line.size >= 9.0 and next_line.size <= 12.0 and
                        not '[' in next_line.text):
                        next_text = next_line.text.strip()
                        if not next_text or re.match(r'^\d+$', next_text):
                            break
                        field_text += ' ' + next_text
                        j += 1
                    else:
                        break
                
                # Add if valid
                if len(field_text) > 5 and not re.match(r'^[\d\s\-/]+$', field_text):
                    records.append({
                        'form_name': form_title,
                        'field_name': field_text,
                        'page': page_num
                    })
```