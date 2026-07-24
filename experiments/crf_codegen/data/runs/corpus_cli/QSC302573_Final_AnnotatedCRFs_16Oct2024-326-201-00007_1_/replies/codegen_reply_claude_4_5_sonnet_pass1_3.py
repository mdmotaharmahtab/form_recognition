Looking at the failures, I can see several patterns:

1. **Section headers with "#1" etc.** are being extracted as fields (e.g., "Informed Consent: Photo ID #1")
2. **Multi-line questions are being split** when they shouldn't be (e.g., the Future Use Sub Study question)
3. **Instructional text in parentheses/dashes** is being extracted as separate fields
4. **Some legitimate questions are being skipped** due to overly aggressive filtering

Let me rewrite the program to fix these issues:

```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        if not lines:
            continue
        
        page_num = page_idx + 1
        
        # Extract form_name from "Schedule Category & Name:" line
        form_name = ""
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Next line should contain the actual schedule name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Extract text after the comma
                    match = re.search(r',\s*(.+)', next_line.text)
                    if match:
                        form_name = match.group(1).strip()
                break
        
        # Skip if no form name found (not our layout)
        if not form_name:
            continue
        
        # Find all question fields (bold text at x~167.7 that are actual questions)
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for bold questions at x~167.7
            if (line.bold and 
                167 < line.x0 < 170 and 
                line.size >= 9.5 and
                not line.text.startswith("Answer(s):") and
                not line.text.startswith("Comment:") and
                "Activity" not in line.text and
                "Timepoint" not in line.text and
                not re.match(r'^Day \d+', line.text) and
                not line.text.startswith("Staff Initials:") and
                not re.match(r'^\d+\.\d+', line.text) and  # Skip line numbers
                "SAS:" not in line.text and
                "Barcode:" not in line.text):
                
                # Skip lines that are answer options
                if line.text.strip().startswith("O ") or line.text.strip().startswith("-"):
                    i += 1
                    continue
                
                # Skip section headers that end with "#1", "#2" etc. (these are just organizing headers)
                # e.g., "Informed Consent: Photo ID #1"
                if re.search(r'#\d+\s*$', line.text.strip()):
                    i += 1
                    continue
                
                # Skip instructional text (starts with "Please")
                if line.text.strip().startswith("Please "):
                    i += 1
                    continue
                
                # Skip section headers that have multiple colons
                if line.text.count(":") >= 2:
                    i += 1
                    continue
                
                # This is likely a question - collect continuation lines
                question_parts = [line.text.strip()]
                j = i + 1
                
                # Look ahead for continuation lines - be more aggressive about collecting them
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop at staff initials, answers, comments, or new timepoint
                    if (next_line.text.startswith("Staff Initials:") or
                        next_line.text.startswith("Answer(s):") or
                        next_line.text.startswith("Comment:") or
                        next_line.text.startswith("dd - MMM") or
                        next_line.text.startswith("HH:mm") or
                        re.match(r'^Day \d+', next_line.text) or
                        next_line.text.startswith("Barcode:") or
                        (next_line.bold and ":" in next_line.text and next_line.x0 < 100)):
                        break
                    
                    # Stop if next line is a section header with #N suffix
                    if (next_line.bold and 167 < next_line.x0 < 170 and 
                        re.search(r'#\d+\s*$', next_line.text.strip())):
                        break
                    
                    # Stop if next line looks like a new question (bold at x~167)
                    # But be careful not to stop on continuation lines
                    if (next_line.bold and 167 < next_line.x0 < 170 and 
                        not next_line.text.strip().startswith("where ") and
                        not next_line.text.strip().startswith("and ") and
                        not next_line.text.strip().startswith("research?") and
                        not re.match(r'^\(', next_line.text.strip()) and
                        not next_line.text.strip().startswith("protect ") and
                        not next_line.text.strip().startswith("workbook)")):
                        # Check if it's really a new question or just continuation
                        text_stripped = next_line.text.strip()
                        # If starts with lowercase or is clearly continuation, include it
                        if text_stripped and text_stripped[0].isupper() and "?" not in question_parts[-1]:
                            # Might be new question, but check if previous ended mid-sentence
                            last_part = question_parts[-1].rstrip()
                            if last_part.endswith((",", "and", "or", "where", "the", "a", "for")):
                                # Continuation
                                pass
                            else:
                                break
                    
                    # Continuation at similar x position (or slightly indented for wrapped text)
                    if (165 < next_line.x0 < 185 and 
                        next_line.size >= 9.0 and
                        not next_line.text.startswith("O ") and
                        not next_line.text.strip().startswith("[") and
                        "SAS:" not in next_line.text):
                        
                        text_stripped = next_line.text.strip()
                        
                        # Include continuation lines more liberally
                        if text_stripped:
                            # Skip if it's a section header with #N
                            if re.search(r'#\d+\s*$', text_stripped):
                                break
                            
                            question_parts.append(text_stripped)
                            j += 1
                        else:
                            j += 1
                    else:
                        break
                
                # Join the question parts
                field_name = " ".join(question_parts)
                
                # Clean up common prefixes/suffixes
                field_name = re.sub(r'\s+', ' ', field_name).strip()
                
                # Filter out non-questions
                # Skip if starts with orphaned continuation words
                if re.match(r'^(where|and|or|research\?)\s+', field_name, re.IGNORECASE):
                    i = j
                    continue
                
                # Skip if it's just a parenthetical note alone
                if re.match(r'^\([^)]+\)$', field_name):
                    i = j
                    continue
                
                # Skip section headers (end with colon and contain colon earlier)
                if field_name.endswith(":") and ":" in field_name[:-1]:
                    i = j
                    continue
                
                # Skip if ends with "#N" (section header)
                if re.search(r'#\d+\s*$', field_name):
                    i = j
                    continue
                
                # Skip instructional fragments that got through
                if field_name.startswith("Confirm TDL form completed:") and field_name == "Confirm TDL form completed:":
                    i = j
                    continue
                
                # Skip standalone instructional text in parentheses/dashes at end
                # But keep the main question if it has substance before the instruction
                # e.g., keep "PK Sample for Bioanalysis - Gently invert..." as one field
                
                # Skip if just "Barcode:"
                if field_name == "Barcode:":
                    i = j
                    continue
                
                # Skip very short fragments that are likely not questions
                if len(field_name) < 10 and not field_name.endswith("?"):
                    i = j
                    continue
                
                # Skip if looks like metadata rather than a question
                if (field_name and 
                    len(field_name) > 3 and
                    not re.match(r'^\d+\.\d+\s*\(', field_name) and
                    "Line #" not in field_name):
                    
                    # Skip duplicates on same page
                    dup = False
                    for r in results:
                        if r["page"] == page_num and r["field_name"] == field_name and r["form_name"] == form_name:
                            dup = True
                            break
                    
                    if not dup and field_name:
                        results.append({
                            "form_name": form_name,
                            "field_name": field_name,
                            "page": page_num
                        })
                
                i = j
            else:
                i += 1
    
    return results
```
