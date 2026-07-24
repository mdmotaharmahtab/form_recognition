```python
"""
Layout observation:
- This is a clinical CRF with a consistent structure across 489 pages
- Each page has a header with "Schedule Category & Name:" followed by the form name
- Fields are organized in repeating blocks with: Timepoint, Activity (bold), Line #
- Field questions appear in bold after the Activity name
- Answer options (O Yes/No, checkboxes, etc.) and SAS codes are NOT fields
- Staff Initials, Answer(s), and Comment are structural markers, not field names

Strategy:
- Extract form_name from "Schedule Category & Name:" line (after the comma)
- Identify field blocks by detecting Activity lines (bold, x~167, contains text)
- Field questions are bold lines at x~167 that are NOT "Answer(s):", "Comment:", 
  or structural headers, and appear after an Activity line
- Track current form across pages since it may not repeat on every page
"""

import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Update current form name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Next line or same line may contain the form name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Form name is after the comma in format "CODE, Name"
                    if "," in next_line.text:
                        parts = next_line.text.split(",", 1)
                        if len(parts) > 1:
                            current_form = parts[1].strip()
                break
        
        # Find field questions
        # Look for bold lines at x~167 that are field questions
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip if not in the activity/question column (x around 167)
            if not (160 < line.x0 < 175):
                i += 1
                continue
            
            # Skip structural markers and headers
            if line.text in ["Answer(s):", "Comment:", "Activity", "Timepoint"]:
                i += 1
                continue
            
            # Skip lines that are just SAS codes or technical annotations
            if line.text.startswith("[") and line.text.endswith("]"):
                i += 1
                continue
            
            if "SAS:[" in line.text:
                i += 1
                continue
            
            # Field questions are bold, in the question column
            if line.bold and line.text.strip():
                text = line.text.strip()
                
                # Skip answer options (start with "O ")
                if text.startswith("O "):
                    i += 1
                    continue
                
                # Skip date/time format indicators
                if text in ["dd - MMM - yyyy", "HH:mm", "_ _ - _ _ _ - _ _ _ _", "_ _ : _ _"]:
                    i += 1
                    continue
                
                # Skip "Line #" header
                if text == "Line #":
                    i += 1
                    continue
                
                # Skip page numbers and other numeric-only content
                if re.match(r'^[\d\.\s\(\)]+$', text):
                    i += 1
                    continue
                
                # Skip "Staff Initials:"
                if text == "Staff Initials:":
                    i += 1
                    continue
                
                # This looks like a field question
                # Collect continuation lines if the question spans multiple lines
                full_question = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Check if next line is a continuation (same x position, bold, not a marker)
                    if (next_line.bold and 
                        160 < next_line.x0 < 175 and 
                        next_line.text.strip() and
                        not next_line.text.strip().startswith("O ") and
                        next_line.text.strip() not in ["Answer(s):", "Comment:", "Staff Initials:"] and
                        not next_line.text.strip().startswith("[") and
                        "SAS:[" not in next_line.text and
                        abs(next_line.y0 - lines[j-1].y0) < 20):  # Close vertical proximity
                        full_question += " " + next_line.text.strip()
                        j += 1
                    else:
                        break
                
                # Clean up the question text
                full_question = full_question.strip()
                
                # Skip if it's just a code or number
                if re.match(r'^[\d\.\s\(\)]+$', full_question):
                    i += 1
                    continue
                
                # Add the field
                if full_question and current_form:
                    results.append({
                        "form_name": current_form,
                        "field_name": full_question,
                        "page": page_num
                    })
                
                i = j  # Skip the lines we've already processed
            else:
                i += 1
    
    return results
```