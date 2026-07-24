```python
import re
from typing import List, Dict
from collections import Counter

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if line.text.startswith("Schedule Category & Name:"):
                # Next line contains the form name
                if i + 1 < len(lines):
                    form_text = lines[i + 1].text.strip()
                    # Remove leading code like "QSC302573, "
                    if ", " in form_text:
                        current_form = form_text.split(", ", 1)[1]
                    else:
                        current_form = form_text
                break
        
        # Analyze page structure to identify field label column
        # Field labels are typically bold, at a consistent x position (around 167-170)
        bold_x_positions = []
        for line in lines:
            if line.bold and 9.5 < line.size < 10.5 and not line.non_black:
                bold_x_positions.append(line.x0)
        
        # Identify the field label column (most common x position in the 160-180 range)
        field_label_x = None
        if bold_x_positions:
            candidates = [x for x in bold_x_positions if 160 < x < 180]
            if candidates:
                # Use the most common x position
                x_counts = Counter([round(x, 0) for x in candidates])
                if x_counts:
                    field_label_x = x_counts.most_common(1)[0][0]
        
        # If we couldn't identify a field label column, skip detailed extraction
        if field_label_x is None:
            continue
        
        # Identify structural markers (repeated template furniture)
        structural_markers = {"Activity", "Answer(s):", "Comment:", "Barcode:"}
        
        # Process lines to extract fields
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check for non-bold measurement fields at x=238.7
            # These appear under "Answer(s):" and contain measurement prompts with underscores
            if (not line.bold and 
                230 < line.x0 < 245 and 
                9.5 < line.size < 10.5 and
                not line.non_black and
                "_" in line.text and
                not line.text.startswith("O ") and
                not line.text.startswith("[") and
                "SAS:[Name=" not in line.text):
                
                # Extract the field name (text before the underscores)
                field_text = line.text.strip()
                
                # Remove the underscore pattern and units/format at the end
                # Split on multiple spaces followed by underscores
                match = re.match(r'^(.+?)\s{2,}_', field_text)
                if match:
                    field_name = match.group(1).strip()
                    
                    # Skip if it's just a placeholder pattern like "Date _" or "Time _"
                    # These are typically very short (1-2 words) and end with underscore
                    if field_name and len(field_name) > 0:
                        # Skip single-word underscore fields that are likely placeholders
                        words = field_name.split()
                        if len(words) == 1 and words[0] in ["Date", "Time", "Version"]:
                            i += 1
                            continue
                        # Skip two-word patterns like "No of Units" that are sub-parts
                        if len(words) <= 3 and not any(c.islower() for c in field_name):
                            # Very short all-caps phrases are likely sub-labels
                            i += 1
                            continue
                        
                        results.append({
                            "form_name": current_form,
                            "field_name": field_name,
                            "page": page_num
                        })
                
                i += 1
                continue
            
            # Check if this is a field label candidate (bold text in field label column)
            if (line.bold and 
                abs(line.x0 - field_label_x) < 10 and 
                9.5 < line.size < 10.5 and
                not line.non_black):
                
                # Skip standard structural headers (template furniture)
                if line.text in structural_markers:
                    i += 1
                    continue
                
                # Skip answer options (always start with "O ")
                if line.text.startswith("O "):
                    i += 1
                    continue
                
                # Skip technical annotations in brackets at start
                if line.text.startswith("[") and "]" in line.text:
                    i += 1
                    continue
                
                # Skip SAS annotations
                if "SAS:[Name=" in line.text:
                    i += 1
                    continue
                
                # Detect section headers by structure: ends with "# <number>"
                if "#" in line.text and re.search(r'#\s*\d+\s*$', line.text):
                    i += 1
                    continue
                
                # Collect the field label (may span multiple lines)
                field_parts = [line.text]
                j = i + 1
                
                # Look ahead for continuation lines
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Check if next line is a continuation (same column, bold, appropriate size)
                    if (next_line.bold and 
                        abs(next_line.x0 - field_label_x) < 10 and 
                        9.5 < next_line.size < 10.5 and 
                        not next_line.non_black):
                        
                        # Stop at structural markers
                        if (next_line.text in structural_markers or
                            next_line.text.startswith("O ") or
                            next_line.text.startswith("[") or
                            "SAS:[Name=" in next_line.text):
                            break
                        
                        # Stop at section headers
                        if "#" in next_line.text and re.search(r'#\s*\d+\s*$', next_line.text):
                            break
                        
                        # It's a continuation
                        field_parts.append(next_line.text)
                        j += 1
                    else:
                        break
                
                # Join the field label
                field_name = " ".join(field_parts).strip()
                
                # Structural exclusions based on the complete field:
                
                # Skip if entire field is parenthetical instruction
                if field_name.startswith("(") and field_name.endswith(")"):
                    i = j
                    continue
                
                # Skip if it's a fragment ending with ")" - likely continuation of previous instruction
                if field_name.endswith(")") and "(" not in field_name:
                    i = j
                    continue
                
                # Skip structural patterns that indicate instructions/calculations rather than fields:
                # Pattern 1: All-caps multi-word phrases ending with colon (section headers)
                if re.match(r'^[A-Z][A-Z\s\-]+:', field_name) and field_name.count(' ') >= 2:
                    i = j
                    continue
                
                # Pattern 2: Starts with timing prefix and contains structural markers
                # e.g., "PRE-DOSE Triplicate ECG 1:" or "POST-DOSE - Something:"
                if re.match(r'^(PRE-DOSE|POST-DOSE|Predose|Postdose)\s+.*:', field_name):
                    # This is a section header, not a field
                    i = j
                    continue
                
                # Pattern 3: Contains calculation/instruction keywords in structural position
                # These appear as standalone bold text describing what will happen
                if re.match(r'^(Difference|ECG Difference|Vital Signs)\s', field_name):
                    # Check if it's a descriptive statement rather than a question
                    if not field_name.endswith("?") and ("Calculation" in field_name or "will be" in field_name):
                        i = j
                        continue
                
                # Add the field
                if field_name and len(field_name) > 0:
                    results.append({
                        "form_name": current_form,
                        "field_name": field_name,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return results
```