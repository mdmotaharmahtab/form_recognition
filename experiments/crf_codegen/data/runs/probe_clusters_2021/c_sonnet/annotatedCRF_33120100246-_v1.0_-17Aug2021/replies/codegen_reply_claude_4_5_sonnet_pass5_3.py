Looking at the execution metrics and sample pages, my previous program extracted 0 records because it was too focused on looking for blue form titles and strict annotation patterns that don't exist in these pages.

From the sample pages, I can see:
- **Cluster 0 & 1**: Pages with red technical annotations (`[LBTEST1]`, `[TYPE: text]`, etc.) but fields are the **black text labels** above them
- **Cluster 2**: Form pages with structured fields like "Date of Attempt", "Actual Lethality/Medical Damage:", "Potential Lethality: Only answer if Actual Lethality=0" - these are **bold black text** field labels
- Form titles appear as large blue text (e.g., "C-SSRS since last visit - Page 4")

The key insight: **field labels are black text (often bold), followed by answer options or annotations in smaller text or red technical markers**.

```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form titles: large blue text (size >= 13)
        for ln in lines:
            if ln.size >= 13 and ln.non_black:
                text = ln.text.strip()
                # Clean form title
                text = re.sub(r'^\d+\.?\d*\.\s*', '', text)
                if text and len(text) > 5 and not re.match(r'^(PAGES?|Page \d+)$', text, re.I):
                    current_form = text
                    break
        
        # If no form found yet, try medium blue text (10-13)
        if not current_form:
            for ln in lines:
                if 10 <= ln.size < 13 and ln.non_black:
                    text = ln.text.strip()
                    text = re.sub(r'^\d+\.?\d*\.\s*', '', text)
                    if text and len(text) > 8:
                        current_form = text
                        break
        
        # Extract fields
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty or very short
            if not text or len(text) < 3:
                i += 1
                continue
            
            # Skip red technical annotations (machine codes)
            if line.non_black and ('[' in text or 'TYPE:' in text or 'VISIBILITY:' in text):
                i += 1
                continue
            
            # Skip pure row markers
            if re.match(r'^Row \d+$', text, re.I):
                i += 1
                continue
            
            # Field detection: black text with good size
            is_black = not line.non_black
            is_field_size = 7 <= line.size <= 11
            
            if not (is_black and is_field_size):
                i += 1
                continue
            
            # Check if this looks like a field label
            # Field labels often:
            # 1. End with colon or question mark
            # 2. Are followed by answer options (starting with \0.\, \1.\, etc.)
            # 3. Are followed by red annotations
            # 4. Are descriptive text (not single words like "Yes", "No")
            
            has_colon_or_question = text.endswith(':') or '?' in text
            
            # Look ahead for evidence this is a field
            has_answer_options = False
            has_red_annotation = False
            next_is_continuation = False
            
            for j in range(i+1, min(i+8, len(lines))):
                next_text = lines[j].text.strip()
                
                # Check for answer options
                if re.match(r'^\\[0-9]\.\\ ', next_text):
                    has_answer_options = True
                
                # Check for red annotations
                if lines[j].non_black and ('[' in next_text or 'TYPE:' in next_text):
                    has_red_annotation = True
                
                # Check for continuation (same x position, black text)
                if (not lines[j].non_black and 
                    abs(lines[j].x0 - line.x0) < 10 and
                    7 <= lines[j].size <= 11 and
                    len(next_text) > 2 and
                    not next_text.startswith('\\') and
                    not re.match(r'^Row \d+$', next_text, re.I)):
                    next_is_continuation = True
                else:
                    break
            
            # Exclude obvious non-fields
            is_single_answer = text in ['Yes', 'No', 'Current', 'Former', 'Never', 'Collected', 'Not', 'Applicable']
            is_pure_number = re.match(r'^\d+$', text)
            is_section_marker = text.startswith('\\') or re.match(r'^\([0-9]\)', text)
            
            # Is this a field?
            is_field = (
                (has_colon_or_question or has_answer_options or has_red_annotation) and
                not is_single_answer and
                not is_pure_number and
                not is_section_marker and
                len(text) >= 5
            )
            
            if is_field and current_form:
                # Collect multi-line field labels
                full_text = text
                k = i + 1
                while k < len(lines) and k < i + 6:
                    next_line = lines[k]
                    next_text = next_line.text.strip()
                    
                    # Stop at answer options, annotations, or new fields
                    if not next_text:
                        k += 1
                        continue
                    if next_line.non_black:
                        break
                    if next_text.startswith('\\'):
                        break
                    if re.match(r'^Row \d+$', next_text, re.I):
                        break
                    if next_text.endswith(':') and len(next_text) > 5:
                        break
                    
                    # Check if continuation (similar x position)
                    if abs(next_line.x0 - line.x0) < 10 and 7 <= next_line.size <= 11:
                        # Don't include single answer words
                        if next_text not in ['Yes', 'No', 'Current', 'Former', 'Never', 'Collected', 'Not', 'Applicable']:
                            full_text += ' ' + next_text
                            k += 1
                        else:
                            break
                    else:
                        break
                
                # Clean up
                full_text = re.sub(r'\s+', ' ', full_text).strip()
                
                # Final validation
                if len(full_text) >= 5:
                    results.append({
                        "form_name": current_form,
                        "field_name": full_text,
                        "page": page_num
                    })
                
                # Skip past the lines we consumed
                i = k
            else:
                i += 1
    
    # Deduplicate consecutive identical records
    deduplicated = []
    prev_key = None
    for rec in results:
        key = (rec['form_name'], rec['field_name'])
        if key != prev_key:
            deduplicated.append(rec)
            prev_key = key
    
    return deduplicated
```
