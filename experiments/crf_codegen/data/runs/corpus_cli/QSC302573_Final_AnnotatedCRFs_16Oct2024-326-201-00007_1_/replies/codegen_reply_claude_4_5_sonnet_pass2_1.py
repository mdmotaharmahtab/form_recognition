```python
# Layout analysis: CRF with Activity-based structure. Activities (bold lines starting
# at x~167.7) define field_name. Each activity has a Line # at x~488.4. Activities
# nest under the most recent Schedule Category & Name (form_name). Page 213 shows
# rating-scale options ("1 - Feeling active..."), which are NOT fields per spec.
# Strategy: Track form name from "Schedule Category & Name:"; extract Activity lines
# (bold, x~167.7) as field_name; skip answer options, machine codes, and scaffolding.

import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Check if this is one of our target layouts by looking for signature patterns
        has_schedule_category = any("Schedule Category & Name:" in ln.text for ln in lines)
        has_annotated_crf_title = any(ln.text == "Annotated CRF" and ln.size >= 18 for ln in lines)
        
        if not (has_schedule_category and has_annotated_crf_title):
            continue
        
        for i, ln in enumerate(lines):
            # Update form_name when we see "Schedule Category & Name:"
            if ln.text == "Schedule Category & Name:" and ln.bold:
                # Next line at same Y or slightly below contains the form name
                for j in range(i+1, min(i+5, len(lines))):
                    if lines[j].x0 > 150 and lines[j].y0 >= ln.y0 - 5 and lines[j].y0 <= ln.y0 + 20:
                        # Extract form name, strip the prefix code if present
                        form_text = lines[j].text.strip()
                        # Keep as-is per spec: "exactly as printed"
                        current_form = form_text
                        break
            
            # Extract Activity fields: bold lines around x=167.7 that are questions
            # Skip if it's a header (Timepoint/Activity/Line #), answer option marker, or machine code
            if (ln.bold and 
                160 <= ln.x0 <= 175 and 
                ln.text and
                ln.text not in ["Activity", "Answer(s):"] and
                not ln.text.startswith("O ") and  # Answer options
                not re.match(r'^\[.*\]\s*SAS:', ln.text)):  # Machine codes
                
                # Check if this looks like a field question
                # Activity lines often contain meaningful text, not just scaffolding
                if (len(ln.text) > 5 and 
                    ":" not in ln.text[:30] or "?" in ln.text or "ICF" in ln.text or "Session" in ln.text):
                    
                    # Collect potential continuation lines
                    field_parts = [ln.text.strip()]
                    
                    # Look ahead for wrapped continuation (same x position, immediately following)
                    for j in range(i+1, min(i+10, len(lines))):
                        next_ln = lines[j]
                        # Continuation: similar x, close y, not bold header, not other structure
                        if (160 <= next_ln.x0 <= 175 and 
                            next_ln.y0 > ln.y0 and 
                            next_ln.y0 - ln.y0 < 25 and
                            not next_ln.text.startswith("dd -") and
                            not next_ln.text.startswith("_ _") and
                            not next_ln.text.startswith("O ") and
                            not next_ln.text.startswith("[") and
                            next_ln.text not in ["Answer(s):", "Comment:", "Staff Initials:", "Activity"] and
                            len(next_ln.text) > 3):
                            
                            # Check if it's a continuation or a new activity
                            if next_ln.bold and "?" in next_ln.text:
                                break  # It's a new question
                            
                            # If it starts with uppercase or continues sentence, likely continuation
                            if not re.match(r'^[A-Z].*[?]', next_ln.text):
                                field_parts.append(next_ln.text.strip())
                        elif next_ln.text in ["Staff Initials:", "Answer(s):", "Comment:"]:
                            break
                        elif next_ln.y0 - ln.y0 > 25:
                            break
                    
                    field_name = " ".join(field_parts)
                    
                    # Final validation: skip if this looks like page furniture or machine code
                    if (field_name and 
                        not re.match(r'^Page \d+ of \d+', field_name) and
                        not re.match(r'^Date Created:', field_name) and
                        not re.match(r'^\d+ - [A-Z]', field_name) and  # Rating scale options
                        "SAS:" not in field_name):
                        
                        results.append({
                            "form_name": current_form,
                            "field_name": field_name,
                            "page": page_num
                        })
    
    return results
```
