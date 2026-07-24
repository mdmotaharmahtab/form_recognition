Looking at the quality audit, I can see the core issues:

1. **Multi-line fields are being split** - e.g., "Has the participant's photographic and wristband ID been verified and wristband applied to participant's wrist?" is being extracted as three separate records
2. **Section headers are being extracted as fields** - e.g., "Admission Restrictions: Photo ID #1" 
3. **Metadata fields with format markers are being extracted incorrectly** - e.g., "Date:", "Time:", "Version:" separately instead of recognizing them as part of structured fields
4. **Real fields are being skipped** because they span multiple lines

The program is using hardcoded string blocklists instead of structural rules. Let me rewrite with proper structural discrimination:

```python
import re
from collections import namedtuple

Line = namedtuple('Line', ['text', 'x0', 'y0', 'x1', 'y1', 'size', 'bold', 'non_black'])

def extract(pages):
    results = []
    current_form_name = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form_name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                remainder = line.text.split("Schedule Category & Name:")[-1].strip()
                if remainder and not remainder.startswith("Timepoint"):
                    current_form_name = remainder
                elif i + 1 < len(lines):
                    candidate = lines[i + 1].text.strip()
                    if candidate and not candidate.startswith(("Timepoint", "Activity", "Line")):
                        current_form_name = candidate
                break
        
        # Extract fields
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # STRUCTURAL RULE: Skip section headers (group organizational labels)
            # Characteristics: bold, far left (x < 100), ends with "#N" pattern
            # These organize fields but are NOT themselves fields
            if (line.bold and 
                line.x0 < 100 and
                re.search(r'#\d+\s*$', line.text)):
                i += 1
                continue
            
            # STRUCTURAL RULE: Skip column headers / table headers
            # Characteristics: bold, very top of page (y < 120), short text
            if line.bold and line.y0 < 120 and len(line.text.strip()) < 30:
                i += 1
                continue
            
            # PATTERN 1: Main field labels (bold, main content area, reasonable size)
            # These are the primary question/field labels
            if (line.bold and 
                line.x0 > 100 and 
                8.5 < line.size < 12 and
                line.y0 > 100):
                
                text = line.text.strip()
                
                # STRUCTURAL RULE: Skip standalone answer/comment section markers
                # These are single-word/short markers at label position that introduce answer areas
                # Pattern: single word ending with colon, x-position right of main content
                if (line.x0 > 400 and 
                    len(text.split()) <= 2 and 
                    text.endswith(":")):
                    i += 1
                    continue
                
                # STRUCTURAL RULE: Skip answer options (radio/checkbox items)
                # Pattern: "O " prefix (circle marker), indented under question
                if text.startswith("O "):
                    i += 1
                    continue
                
                # Collect complete multi-line field label
                field_parts = [text]
                j = i + 1
                
                while j < len(lines):
                    next_line = lines[j]
                    
                    # STRUCTURAL RULE: Stop at standalone markers (right-aligned, single word + colon)
                    if (next_line.x0 > 400 and 
                        len(next_line.text.strip().split()) <= 2 and
                        next_line.text.strip().endswith(":")):
                        break
                    
                    # STRUCTURAL RULE: Stop at answer options
                    if next_line.text.strip().startswith("O ") and next_line.x0 > 100:
                        break
                    
                    # STRUCTURAL RULE: Stop at next section header (left-aligned, #N pattern)
                    if (next_line.bold and 
                        next_line.x0 < 100 and 
                        re.search(r'#\d+\s*$', next_line.text)):
                        break
                    
                    # STRUCTURAL RULE: Stop at next field label
                    # Gap check: reasonable vertical distance (adjusted for multi-line wrapping)
                    vertical_gap = next_line.y0 - lines[j-1].y0
                    if (next_line.bold and 
                        next_line.x0 > 100 and
                        8.5 < next_line.size < 12 and
                        vertical_gap > 25):  # Increased threshold for wrapped lines
                        break
                    
                    # STRUCTURAL RULE: Stop at structured metadata fields
                    # Pattern: bold, smaller size (8-9.5), left side, ends with colon
                    if (next_line.bold and 
                        8 < next_line.size < 9.5 and
                        next_line.x0 < 250 and
                        next_line.text.strip().endswith(":")):
                        break
                    
                    # STRUCTURAL RULE: Continuation line criteria
                    # Same font characteristics, close vertical position, similar x-alignment
                    size_diff = abs(next_line.size - line.size)
                    x_similar = abs(next_line.x0 - line.x0) < 50  # Allow some wrap indentation
                    
                    if (next_line.bold and 
                        next_line.x0 > 100 and
                        size_diff < 2 and
                        vertical_gap < 25 and
                        x_similar):
                        
                        cont_text = next_line.text.strip()
                        
                        # Skip if it's just format markers (like "(dd - mmm - yyyy)")
                        if not (cont_text.startswith("(") and cont_text.endswith(")")):
                            field_parts.append(cont_text)
                        j += 1
                    else:
                        break
                
                field_name = " ".join(field_parts).strip()
                
                # Clean up the field name
                # Remove trailing format hints in parentheses if they're the only content
                if field_name.startswith("(") and field_name.endswith(")"):
                    i = j
                    continue
                
                # Valid field: has substance, not just punctuation
                # Remove duplicate/concatenated section markers with #N pattern
                if re.match(r'^[A-Za-z\s:]+#\d+\s*$', field_name):
                    # This is a section header that slipped through
                    i = j
                    continue
                
                if field_name and len(field_name) > 3 and not field_name.endswith(("#", ":")):
                    results.append({
                        "form_name": current_form_name,
                        "field_name": field_name,
                        "page": page_num
                    })
                
                i = j
                continue
            
            # PATTERN 2: Metadata/staff fields (bold, smaller size, left-aligned)
            # "Staff Initials:", "Comment:" - recurring template fields
            if (line.bold and 
                8 < line.size < 9.5 and
                line.x0 < 250 and
                line.y0 > 100):
                
                text = line.text.strip()
                
                # STRUCTURAL RULE: Label ends with colon, single line
                if text.endswith(":") and len(text.split()) <= 3:
                    results.append({
                        "form_name": current_form_name,
                        "field_name": text,
                        "page": page_num
                    })
                    i += 1
                    continue
                
                # STRUCTURAL RULE: Date/Time fields with format pattern
                # Pattern: "Date _ _ - _ _ _ - _ _ _ _" or "Time _ _ : _ _"
                # Extract the label before the format markers
                if "_" in text or ":" in text:
                    # Match label at start (before format markers or underscores)
                    label_match = re.match(r'^([A-Z][A-Za-z\s]{2,}?)(?:\s*_|\s*\()', text)
                    if label_match:
                        label = label_match.group(1).strip()
                        # Ensure it's a real label, not a format marker
                        if label and not label.startswith(("dd", "HH", "mm", "yy", "MM")):
                            if not label.endswith(":"):
                                label += ":"
                            results.append({
                                "form_name": current_form_name,
                                "field_name": label,
                                "page": page_num
                            })
                    i += 1
                    continue
            
            # PATTERN 3: Non-bold data entry fields with underscores/blanks
            # "Diastolic _ _ _ _ mmHg", "Open Field ______", "Ventricular Rate _ _ _"
            if (not line.bold and
                8 < line.size < 11 and
                "_" in line.text and
                line.y0 > 100 and
                line.x0 > 100):
                
                text = line.text.strip()
                
                # STRUCTURAL RULE: Extract label before underscores
                # Pattern: text followed by spaces and underscores
                label_match = re.match(r'^([A-Za-z][A-Za-z\s\-/]+?)\s+_', text)
                if label_match:
                    label = label_match.group(1).strip()
                    # Valid label: not format markers, reasonable length
                    if (label and 
                        len(label) > 2 and 
                        not label.startswith(("dd", "HH", "mm", "yy", "MM"))):
                        
                        if not label.endswith(":"):
                            label += ":"
                        results.append({
                            "form_name": current_form_name,
                            "field_name": label,
                            "page": page_num
                        })
            
            # PATTERN 4: Non-bold labels followed by colon (form field labels at data position)
            # These appear in structured layouts where labels are not bolded
            if (not line.bold and
                8.5 < line.size < 10 and
                line.x0 > 100 and
                line.y0 > 100 and
                line.text.strip().endswith(":")):
                
                text = line.text.strip()
                
                # STRUCTURAL RULE: Single-line label ending with colon
                # Not an answer marker (those are right-aligned)
                if line.x0 < 400 and len(text.split()) <= 8:
                    results.append({
                        "form_name": current_form_name,
                        "field_name": text,
                        "page": page_num
                    })
            
            i += 1
    
    return results
```
