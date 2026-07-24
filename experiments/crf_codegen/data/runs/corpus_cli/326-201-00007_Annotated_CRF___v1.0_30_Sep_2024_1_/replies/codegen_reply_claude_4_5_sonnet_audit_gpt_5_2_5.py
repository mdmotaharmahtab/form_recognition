Looking at the quality gate failures, I can see the main issues:

1. **Multi-line questions are being split incorrectly** - "Has the participant's photographic and wristband ID been verified and wristband applied to participant's wrist?" is being extracted as separate fragments
2. **"Staff Initials:" and "Comment:" are being missed** - these are consistent metadata fields
3. **Section headers and structural elements are being extracted as fields** - like "Activity", "Admission Restrictions: ICF Version/Date #1", etc.

The core problem is that my continuation logic is stopping too early for wrapped questions. I need to fix the multi-line assembly while better filtering structural non-fields.

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
            # Characteristics: bold, far left (x < 100), ends with "#N" pattern OR contains "#N"
            if (line.bold and 
                line.x0 < 100 and
                re.search(r'#\d+', line.text)):
                i += 1
                continue
            
            # STRUCTURAL RULE: Skip column headers / table headers
            # Single words at top, or very short labels
            if line.bold and line.y0 < 120 and len(line.text.strip()) < 30:
                i += 1
                continue
            
            # STRUCTURAL RULE: Skip structural labels with "#N" pattern in middle content area
            # "Admission Restrictions: ICF Version/Date #1" - these are section markers, not fields
            if (line.bold and 
                line.x0 > 100 and
                re.search(r'#\d+\s*$', line.text)):
                i += 1
                continue
            
            # PATTERN 1: Main field labels (bold, main content area, reasonable size)
            if (line.bold and 
                line.x0 > 100 and 
                8.5 < line.size < 12 and
                line.y0 > 100):
                
                text = line.text.strip()
                
                # STRUCTURAL RULE: Skip standalone answer/comment section markers
                if (line.x0 > 400 and 
                    len(text.split()) <= 2 and 
                    text.endswith(":")):
                    i += 1
                    continue
                
                # STRUCTURAL RULE: Skip answer options (radio/checkbox items)
                if text.startswith("O "):
                    i += 1
                    continue
                
                # STRUCTURAL RULE: Skip single-word headers without colon
                # "Activity", "Findings", etc - these are column/section headers
                if (len(text.split()) == 1 and 
                    not text.endswith(":") and
                    not text.endswith("?")):
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
                        re.search(r'#\d+', next_line.text)):
                        break
                    
                    # STRUCTURAL RULE: Stop at structured metadata fields
                    # Pattern: bold, smaller size (8-9.5), left side, ends with colon
                    if (next_line.bold and 
                        8 < next_line.size < 9.5 and
                        next_line.x0 < 250 and
                        next_line.text.strip().endswith(":")):
                        break
                    
                    # STRUCTURAL RULE: Stop at section markers with #N
                    if (next_line.bold and 
                        next_line.x0 > 100 and
                        re.search(r'#\d+\s*$', next_line.text)):
                        break
                    
                    # STRUCTURAL RULE: Stop at next clear field label
                    # Must be: different vertical position (gap), different x-position, or different size
                    vertical_gap = next_line.y0 - lines[j-1].y0
                    size_diff = abs(next_line.size - line.size)
                    x_similar = abs(next_line.x0 - line.x0) < 50
                    
                    # If next line is bold with significantly different position/size, it's a new field
                    if (next_line.bold and 
                        next_line.x0 > 100 and
                        8.5 < next_line.size < 12 and
                        ((vertical_gap > 30 and not x_similar) or size_diff > 2)):
                        break
                    
                    # STRUCTURAL RULE: Continuation line criteria
                    # Must be: bold, similar size, reasonable vertical gap, similar x-position
                    # OR: ends mid-sentence (no punctuation) suggesting wrap
                    last_text = field_parts[-1] if field_parts else ""
                    continues_sentence = (last_text and 
                                         not last_text.endswith(('.', '?', ':', ';')) and
                                         not last_text.endswith(')')  and
                                         not re.search(r'\d+\s*$', last_text))  # not ending with number
                    
                    if (next_line.bold and 
                        next_line.x0 > 80 and  # Allow some wrap indentation
                        size_diff < 2 and
                        vertical_gap < 35):  # Relaxed for wrapped lines
                        
                        cont_text = next_line.text.strip()
                        
                        # Skip if it's just format markers
                        if cont_text.startswith("(") and cont_text.endswith(")") and "_" in cont_text:
                            j += 1
                            continue
                        
                        # Skip if it's a structural label with #N
                        if re.search(r'#\d+\s*$', cont_text):
                            break
                        
                        # Include if it continues a sentence or is close enough and similar position
                        if continues_sentence or (vertical_gap < 20 and x_similar):
                            field_parts.append(cont_text)
                            j += 1
                        else:
                            break
                    else:
                        break
                
                field_name = " ".join(field_parts).strip()
                
                # STRUCTURAL RULE: Skip if only format markers
                if field_name.startswith("(") and field_name.endswith(")"):
                    i = j
                    continue
                
                # STRUCTURAL RULE: Skip if it's just a section marker with #N
                if re.search(r'#\d+\s*$', field_name):
                    i = j
                    continue
                
                # STRUCTURAL RULE: Skip if it contains embedded section marker pattern
                # "Some Text: More Text #1" - this is structural labeling
                if re.search(r':\s*[A-Za-z\s]+#\d+\s*$', field_name):
                    i = j
                    continue
                
                # Valid field: has substance, looks like a question or label
                if (field_name and 
                    len(field_name) > 3 and 
                    not field_name in ["Activity", "Findings"]):
                    results.append({
                        "form_name": current_form_name,
                        "field_name": field_name,
                        "page": page_num
                    })
                
                i = j
                continue
            
            # PATTERN 2: Metadata/staff fields (bold, smaller size, left-aligned)
            # "Staff Initials:", "Comment:", "Date:", "Time:"
            if (line.bold and 
                8 < line.size < 9.5 and
                line.x0 < 300 and
                line.y0 > 100):
                
                text = line.text.strip()
                
                # STRUCTURAL RULE: Label ends with colon, short
                if text.endswith(":") and len(text.split()) <= 4:
                    # Skip if it's a section marker
                    if not re.search(r'#\d+', text):
                        results.append({
                            "form_name": current_form_name,
                            "field_name": text,
                            "page": page_num
                        })
                    i += 1
                    continue
                
                # STRUCTURAL RULE: Date/Time fields with format pattern
                if "_" in text or ":" in text:
                    label_match = re.match(r'^([A-Z][A-Za-z\s]{2,}?)(?:\s*_|\s*\()', text)
                    if label_match:
                        label = label_match.group(1).strip()
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
            if (not line.bold and
                8 < line.size < 11 and
                "_" in line.text and
                line.y0 > 100 and
                line.x0 > 100):
                
                text = line.text.strip()
                
                # STRUCTURAL RULE: Extract label before underscores
                label_match = re.match(r'^([A-Za-z][A-Za-z\s\-/]+?)\s+_', text)
                if label_match:
                    label = label_match.group(1).strip()
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
            
            # PATTERN 4: Non-bold labels followed by colon
            if (not line.bold and
                8.5 < line.size < 10 and
                line.x0 > 100 and
                line.y0 > 100 and
                line.text.strip().endswith(":")):
                
                text = line.text.strip()
                
                # STRUCTURAL RULE: Single-line label ending with colon
                if line.x0 < 400 and len(text.split()) <= 8:
                    results.append({
                        "form_name": current_form_name,
                        "field_name": text,
                        "page": page_num
                    })
            
            i += 1
    
    return results
```
