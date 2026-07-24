```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name:" line
        form_name = ""
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Next line should contain the actual schedule name
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Extract everything after the comma and code
                    match = re.search(r',\s*(.+)$', next_line.text)
                    if match:
                        form_name = match.group(1).strip()
                break
        
        # Identify structural elements by position and style
        # Section headers: bold, left-aligned (~167), end with #N pattern
        section_headers = set()
        for i, line in enumerate(lines):
            if (line.bold and 
                165 <= line.x0 <= 170 and 
                line.size >= 9.5):
                text = line.text.strip()
                # Section headers end with #N and contain a colon
                if re.search(r'#\d+\s*$', text) and ':' in text:
                    section_headers.add(i)
        
        # Identify structural column headers that appear repeatedly across pages
        structural_headers = set()
        y_positions = {}
        for i, line in enumerate(lines):
            if line.bold and 165 <= line.x0 <= 170:
                text = line.text.strip()
                # Track y-positions and text of potential structural headers
                y_key = round(line.y0, 1)
                if y_key not in y_positions:
                    y_positions[y_key] = []
                y_positions[y_key].append((i, text))
        
        # Mark lines at repeated y-positions with same text as structural
        for y_key, items in y_positions.items():
            if len(items) > 1:
                for idx, text in items:
                    structural_headers.add(idx)
        
        # Additionally mark common column headers by text pattern
        for i, line in enumerate(lines):
            if line.bold and 165 <= line.x0 <= 170:
                text = line.text.strip()
                if text in ["Activity", "Answer(s):", "Timepoint", "Comment:", "Staff Initials:"]:
                    structural_headers.add(i)
        
        # Identify answer options by structure: start with "O " or checkbox "[ ]"
        answer_options = set()
        for i, line in enumerate(lines):
            text = line.text.strip()
            if re.match(r'^O\s+', text) or text.startswith('[ ]'):
                answer_options.add(i)
        
        # Identify SAS variable codes: [VARNAME] pattern at start
        sas_codes = set()
        for i, line in enumerate(lines):
            text = line.text.strip()
            if re.match(r'^\[[\w_]+\]', text):
                sas_codes.add(i)
        
        # Identify date/time format templates: dd, MMM, yyyy, HH, mm
        format_templates = set()
        for i, line in enumerate(lines):
            text = line.text.strip()
            if re.match(r'^(dd|MMM|yyyy|HH|mm)\s*$', text):
                format_templates.add(i)
        
        # Identify operator notes: start with **
        operator_notes = set()
        for i, line in enumerate(lines):
            text = line.text.strip()
            if text.startswith('**'):
                operator_notes.add(i)
        
        # Identify placeholder lines: only underscores, dashes, colons, dots, spaces
        placeholders = set()
        for i, line in enumerate(lines):
            text = line.text.strip()
            if text and re.match(r'^[_\s\-:#\.]+$', text):
                placeholders.add(i)
        
        # Identify checklist items (bullet points with dashes or checkboxes)
        checklist_items = set()
        for i, line in enumerate(lines):
            text = line.text.strip()
            if re.match(r'^-\s+', text):
                checklist_items.add(i)
        
        # Identify instruction/note continuations that should not be field labels
        instruction_continuations = set()
        for i in range(1, len(lines)):
            line = lines[i]
            text = line.text.strip()
            
            if (line.bold and 165 <= line.x0 <= 170 and
                text and len(text) > 0):
                # Check if it looks like a continuation of instructions
                if (text[0].islower() or 
                    text.startswith('(') or
                    text.startswith('applicable)') or
                    text.startswith('findings?') or
                    text.startswith('visit?')):
                    instruction_continuations.add(i)
        
        # Find field labels
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field labels are bold, at x≈167.7
            if (line.bold and 
                165 <= line.x0 <= 170 and 
                line.size >= 9.5 and
                line.text.strip()):
                
                text = line.text.strip()
                
                # Skip all identified structural elements
                if (i in section_headers or
                    i in structural_headers or
                    i in answer_options or
                    i in sas_codes or
                    i in format_templates or
                    i in operator_notes or
                    i in placeholders or
                    i in checklist_items or
                    i in instruction_continuations):
                    i += 1
                    continue
                
                # This looks like a field label - collect continuation lines
                field_parts = [text]
                j = i + 1
                
                # Look ahead for continuation lines
                while j < len(lines):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Stop if we hit any structural element
                    if (j in section_headers or
                        j in structural_headers or
                        j in answer_options or
                        j in sas_codes or
                        j in format_templates or
                        j in operator_notes or
                        j in placeholders or
                        j in checklist_items):
                        break
                    
                    # Continuation line: bold, similar x position, not empty
                    if (next_line.bold and 
                        165 <= next_line.x0 <= 170 and
                        next_line.size >= 9.5 and
                        next_text):
                        
                        # Skip if marked as instruction continuation
                        if j in instruction_continuations:
                            break
                        
                        # Check if this is a valid continuation
                        # Stop if it looks like a new field (starts with capital and previous ended with ?)
                        if (field_parts and 
                            field_parts[-1].endswith('?') and
                            next_text[0].isupper() and
                            not next_text.startswith('(')):
                            break
                        
                        # NEW: Stop if the previous line ended with a complete sentence/question
                        # and the next line starts a new complete question
                        # Pattern: "...prior to Screening" followed by "visit?" is a fragment
                        # Pattern: "...prior to Screening" on one line is complete if next starts new question
                        if (field_parts and 
                            len(field_parts) >= 1):
                            combined_so_far = " ".join(field_parts)
                            
                            # If we have a complete question already and next line is a fragment ending in "?"
                            # that doesn't start with uppercase, it's likely a dangling fragment
                            if (combined_so_far.endswith('?') and 
                                next_text.endswith('?') and
                                next_text[0].islower()):
                                # This is a fragment like "visit?" - skip it
                                break
                            
                            # If current ends with "to Screening" or similar preposition phrase
                            # and next is just "visit?" or similar short fragment, it's likely incomplete
                            # But we need to distinguish real continuations from fragments
                            if (next_text.endswith('?') and 
                                len(next_text.split()) <= 2 and
                                next_text[0].islower()):
                                # Short lowercase fragment ending in ? - likely not a real continuation
                                break
                        
                        # NEW: Detect fragments that are incomplete sentence endings
                        # Pattern: "Targeted Physical Examination Findings: Any clinically significant abnormal"
                        # followed by more text - this is a fragment if it doesn't end properly
                        # A complete field should end with punctuation or be a complete phrase
                        if (field_parts and 
                            not field_parts[-1].endswith(('?', '.', ':', ')')) and
                            next_text[0].islower()):
                            # Previous line doesn't end properly and next starts lowercase
                            # This might be a continuation, but check if it's a dangling fragment
                            # If next line is very short and doesn't complete the thought, skip
                            if len(next_text.split()) <= 3:
                                break
                        
                        field_parts.append(next_text)
                        j += 1
                    else:
                        break
                
                # Join the parts into a complete field name
                field_name = " ".join(field_parts)
                
                # Final validation: skip if it looks like a checklist summary or instruction block
                if (field_name.count('-') > 3 or
                    field_name.count(';') > 2):
                    i = j
                    continue
                
                # NEW: Skip incomplete fragments that don't form valid field labels
                # A valid field should either:
                # 1. End with proper punctuation (?, ., :, ))
                # 2. Be a complete noun phrase (not ending mid-sentence)
                # Skip if it ends with adjectives/prepositions suggesting incompleteness
                if field_name:
                    words = field_name.split()
                    last_word = words[-1].lower().rstrip('?.,;:')
                    
                    # Skip if ends with words that suggest incomplete phrase
                    incomplete_endings = [
                        'abnormal', 'significant', 'prior', 'to', 'within',
                        'any', 'the', 'a', 'an', 'of', 'for', 'with', 'in'
                    ]
                    
                    if last_word in incomplete_endings and not field_name.endswith('?'):
                        i = j
                        continue
                    
                    # Skip very short fragments that end with "?"
                    if len(words) <= 2 and field_name.endswith('?') and words[0][0].islower():
                        i = j
                        continue
                
                # Add to results
                results.append({
                    "form_name": form_name,
                    "field_name": field_name,
                    "page": page_num
                })
                
                # Move past the lines we've processed
                i = j
            else:
                i += 1
    
    return results
```