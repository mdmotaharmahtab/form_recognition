```python
"""
Layout observations:
- This is a clinical CRF with a consistent structure across pages
- Form name appears in "Schedule Category & Name:" line (after the code)
- Field names are bold black text at x~167.7, typically followed by date/time placeholders
- Activities (field names) appear after "Activity" header column
- Answer options (O Yes/No, radio buttons) and SAS codes are NOT field names
- Blue text (#4682b4) marks metadata (Staff Initials, Answer(s), Comment, Barcode) - not field names
- Line numbers appear at x~488.4 and help identify activity blocks

Strategy:
- Extract form name from "Schedule Category & Name:" line (text after comma)
- Identify field blocks by bold text at x~167.7 that follows timepoint/line number pattern
- Filter out answer options, metadata labels, and continuation lines
- Use structural markers (date placeholders, line numbers) to identify field boundaries
"""

import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from "Schedule Category & Name:" line
        for i, line in enumerate(lines):
            if "Schedule Category & Name:" in line.text:
                # Form name is on same line or next line after the comma
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Extract text after comma (form name part)
                    match = re.search(r',\s*(.+)', next_line.text)
                    if match:
                        current_form = match.group(1).strip()
                    elif ',' in next_line.text:
                        parts = next_line.text.split(',', 1)
                        if len(parts) > 1:
                            current_form = parts[1].strip()
                    else:
                        current_form = next_line.text.strip()
        
        # Find field names - bold text at x~167.7 that represents questions/activities
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field names are bold, black, at x~167.7, and not metadata labels
            if (line.bold and not line.non_black and 
                165 <= line.x0 <= 170 and line.size >= 9.5):
                
                text = line.text.strip()
                
                # Skip metadata labels (blue text equivalents in structure)
                if text in ["Activity", "Answer(s):", "Timepoint", "Line #"]:
                    i += 1
                    continue
                
                # Skip answer options (start with O or radio button patterns)
                if re.match(r'^O\s+', text):
                    i += 1
                    continue
                
                # Skip SAS codes and technical annotations
                if '[' in text and ']' in text and 'SAS:' in text:
                    i += 1
                    continue
                
                # Skip lines that are just continuation text (parenthetical notes)
                # but collect multi-line field names
                if text.startswith('(') and text.endswith(')'):
                    i += 1
                    continue
                
                # Valid field name candidate
                # Check if this follows an activity pattern (after timepoint/line number)
                # Look back for line number or date pattern
                is_field = False
                for j in range(max(0, i - 5), i):
                    prev = lines[j]
                    # Line numbers at x~488
                    if prev.x0 >= 485 and re.search(r'\d+\.\d+', prev.text):
                        is_field = True
                        break
                    # Or date/time placeholders
                    if 'dd - MMM - yyyy' in prev.text or '_ _ - _ _ _' in prev.text:
                        is_field = True
                        break
                
                # Also check if next few lines have date placeholders (field structure)
                if not is_field:
                    for j in range(i + 1, min(i + 4, len(lines))):
                        next_line = lines[j]
                        if 'dd - MMM - yyyy' in next_line.text or '_ _ : _ _' in next_line.text:
                            is_field = True
                            break
                
                if is_field and text:
                    # Collect multi-line field names (continuation lines at same x position)
                    full_text = text
                    k = i + 1
                    while k < len(lines):
                        next_line = lines[k]
                        if (next_line.bold and not next_line.non_black and
                            165 <= next_line.x0 <= 170 and 
                            not next_line.text.startswith('O ') and
                            'SAS:' not in next_line.text and
                            next_line.text.strip() not in ["Answer(s):", "Staff Initials:", "Comment:", "Barcode:"]):
                            # Check if it's a continuation (starts with lowercase or parenthesis)
                            if (next_line.text.strip().startswith('(') or 
                                (next_line.text.strip() and next_line.text.strip()[0].islower())):
                                full_text += " " + next_line.text.strip()
                                k += 1
                            else:
                                break
                        else:
                            break
                    
                    results.append({
                        "form_name": current_form,
                        "field_name": full_text,
                        "page": page_num
                    })
            
            i += 1
    
    return results
```