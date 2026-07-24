```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for Schedule Category & Name to update current form
        for i, line in enumerate(lines):
            if line.x0 < 100 and line.bold and "Schedule Category & Name:" in line.text:
                # Next line should contain the form name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Extract the descriptive part after the comma
                    if "," in next_line.text:
                        parts = next_line.text.split(",", 1)
                        if len(parts) > 1:
                            current_form = parts[1].strip()
                        else:
                            current_form = next_line.text.strip()
                    else:
                        current_form = next_line.text.strip()
                break
        
        # Extract activities and their questions
        # Activities are bold lines at x~167.7 that contain ":" and are followed by questions
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check if this is an activity header (bold, x~167.7, contains ":")
            if (line.bold and 
                160 < line.x0 < 175 and 
                ":" in line.text and
                not line.text.startswith("Answer") and
                not line.text.startswith("Comment") and
                not line.text.startswith("Barcode") and
                not line.text.startswith("Staff") and
                not "HH:mm" in line.text and
                not "dd - MMM - yyyy" in line.text):
                
                # This might be an activity header
                activity_name = line.text.strip()
                
                # Look ahead for question lines (bold, x~167.7, not answer/comment/etc)
                j = i + 1
                question_buffer = []  # Buffer to accumulate multi-line questions
                
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Stop if we hit another activity or major section
                    if (next_line.bold and 160 < next_line.x0 < 175 and 
                        ":" in next_line.text and
                        not next_line.text.startswith("Answer") and
                        not next_line.text.startswith("Comment") and
                        not next_line.text.startswith("Barcode") and
                        not next_line.text.startswith("Staff")):
                        break
                    
                    # Check if this is a question line
                    if (next_line.bold and 
                        160 < next_line.x0 < 175 and
                        not next_line.text.startswith("Answer") and
                        not next_line.text.startswith("Comment") and
                        not next_line.text.startswith("Barcode") and
                        not next_line.text.startswith("Staff") and
                        not next_line.text.startswith("O ") and
                        not next_line.non_black and
                        not re.match(r'^[A-Z]+\s*$', next_line.text) and
                        not re.match(r'^\s*_+\s*$', next_line.text) and
                        not "SAS:" in next_line.text and
                        not re.match(r'.*\[.*\].*SAS:', next_line.text) and
                        len(next_line.text) > 5):
                        
                        # Check if this line ends with a question mark or looks complete
                        text = next_line.text.strip()
                        
                        # Skip if it looks like metadata or formatting
                        if re.match(r'^(dd|HH|mm|yyyy|MMM)', text):
                            j += 1
                            continue
                        
                        # Skip lines that are clearly continuation fragments
                        # (start with lowercase, or are parenthetical notes)
                        if (text[0].islower() or 
                            text.startswith("(") or
                            text.endswith(";") and "(" in text):
                            j += 1
                            continue
                        
                        # Skip lines that end with "and;" or "if" (incomplete instructions)
                        if text.endswith("and;") or text.endswith(" if"):
                            j += 1
                            continue
                        
                        # If we have a buffer, check if this continues it
                        if question_buffer:
                            # If this line starts with lowercase or continues the sentence
                            if text[0].islower() or text.startswith("research?"):
                                question_buffer.append(text)
                                # Check if we now have a complete question
                                full_text = " ".join(question_buffer)
                                if full_text.endswith("?"):
                                    results.append({
                                        "form_name": current_form,
                                        "field_name": full_text,
                                        "page": page_num
                                    })
                                    question_buffer = []
                                j += 1
                                continue
                            else:
                                # New question started, save buffer if it looks complete
                                full_text = " ".join(question_buffer)
                                if full_text.endswith("?") or len(full_text) > 20:
                                    results.append({
                                        "form_name": current_form,
                                        "field_name": full_text,
                                        "page": page_num
                                    })
                                question_buffer = []
                        
                        # If the line ends with a question mark, it's a complete question
                        if text.endswith("?"):
                            results.append({
                                "form_name": current_form,
                                "field_name": text,
                                "page": page_num
                            })
                        # If it ends with a comma or looks incomplete, start buffering
                        elif (text.endswith(",") or 
                              text.endswith("for potential future") or
                              text.endswith("will be taken and other data collected may be used")):
                            question_buffer = [text]
                        # Otherwise, check if it looks like a complete question
                        # (starts with capital, has verb structure, reasonable length)
                        elif (len(text) > 15 and 
                              not text.endswith("prior to") and
                              not text.endswith("within") and
                              not text.endswith("for potential future")):
                            results.append({
                                "form_name": current_form,
                                "field_name": text,
                                "page": page_num
                            })
                    
                    j += 1
                
                # If we have a buffer at the end, save it if it looks complete
                if question_buffer:
                    full_text = " ".join(question_buffer)
                    if full_text.endswith("?") or len(full_text) > 20:
                        results.append({
                            "form_name": current_form,
                            "field_name": full_text,
                            "page": page_num
                        })
            
            i += 1
    
    return results
```