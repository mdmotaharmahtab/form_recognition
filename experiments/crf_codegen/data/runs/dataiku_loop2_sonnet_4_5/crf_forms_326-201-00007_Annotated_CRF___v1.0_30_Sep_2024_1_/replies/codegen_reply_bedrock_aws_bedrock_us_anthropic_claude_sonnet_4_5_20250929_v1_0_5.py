```python
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
                
                # Skip section headers that end with "#" followed by a number (e.g., "Admission Restrictions: Photo ID #1")
                # These are activity/section labels, not data entry fields
                if re.search(r'#\d+\s*$', text):
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
                        not re.search(r'#\d+\s*$', next_line.text.strip()) and
                        abs(next_line.y0 - lines[j-1].y0) < 20):  # Close vertical proximity
                        
                        next_text = next_line.text.strip()
                        
                        # Check if this is a standalone parenthetical note (not a continuation)
                        if next_text.startswith("(") and next_text.endswith(")") and len(full_question) > 50:
                            # This is a standalone instruction, not part of the question
                            break
                        
                        # Check if this is a standalone field (ends with "?") rather than a continuation
                        if next_text.endswith("?") and len(next_text) > 10 and len(full_question) > 30:
                            # Check if it looks like a complete question on its own
                            # If it starts with a capital letter and forms a complete question, it's separate
                            if next_text[0].isupper() and any(next_text.lower().startswith(word) for word in ["has", "is", "was", "were", "did", "does", "do", "can", "will", "would", "should"]):
                                # This is likely a separate field, not a continuation
                                break
                        
                        full_question += " " + next_text
                        j += 1
                    else:
                        break
                
                # Clean up the question text
                full_question = full_question.strip()
                
                # Skip if it's just a code or number
                if re.match(r'^[\d\.\s\(\)]+$', full_question):
                    i += 1
                    continue
                
                # Skip if it ends with a section header pattern
                if re.search(r'#\d+\s*$', full_question):
                    i += 1
                    continue
                
                # Skip if it's just a parenthetical note (but not if it's part of a longer question)
                if full_question.startswith("(") and full_question.endswith(")") and len(full_question) < 100:
                    i += 1
                    continue
                
                # Skip short fragments that end with "?" but don't look like complete questions
                if full_question.endswith("?") and len(full_question) < 20:
                    i += 1
                    continue
                
                # Skip standalone instruction fragments
                if full_question in ["Update Medical History where appropriate.", "Please ensure that an Adverse Event is completed", "Please ensure that a Concomitant Medication is completed", "Please ensure that a Protocol Deviation is completed"]:
                    i += 1
                    continue
                
                # Skip incomplete fragments that are clearly continuations
                incomplete_fragments = [
                    "Admission visit?",
                    "Has participant consumed food or beverages containing pomelo, grapefruit, grapefruit juice,",
                    "Seville oranges, Seville orange juice, blueberry juice, or cranberry juice within 48 hours (72hrs prior to dosing) prior to Admission visit? (If 'Yes' exclude per exclusion criteria #24)",
                    "Has the participant consumed any food containing poppy seeds within 48 hours prior to",
                    "Has the participant had strenuous activity (e.g. weightlifting) within 72 hours prior to Admission",
                    "Has the participant use of tobacco products or experience daily exposure to second-hand",
                    "smoke since Screening?  (If 'Yes' exclude per exclusion criteria #14)"
                ]
                if full_question in incomplete_fragments:
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