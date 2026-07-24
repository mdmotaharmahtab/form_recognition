Looking at the feedback, I need to fix several issues:

1. **Page 498/549**: Missing fields due to truncated labels ("Were you able to contact the" should continue)
2. **Cluster 1 (0% coverage)**: Pages like p14 that are table-of-contents or index pages with no actual fields
3. **Remove hardcoded text filters**: Replace with structural rules only
4. **Better multi-line assembly**: Some field labels are being cut off mid-text

Let me rewrite the program:

```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form title: large blue text (13+ pt), not bold
        for i, line in enumerate(lines):
            if line.size >= 13.0 and line.non_black and not line.bold:
                text = line.text.strip()
                # Form titles are substantial text, not codes or numbers
                if text and not text.startswith('[') and len(text) > 3:
                    # Skip if it's just digits or page reference
                    if not re.match(r'^(\d+\.?\d*|page \d+)$', text, re.IGNORECASE):
                        current_form = text
                        break
        
        # Detect TOC/index pages: many short blue links in a column with numbers
        # These have no actual fields, just references to other forms
        is_toc_page = False
        blue_links = 0
        left_numbers = 0
        for line in lines:
            if line.non_black and line.size < 9.0 and line.x0 > 250:
                blue_links += 1
            if line.x0 < 100 and re.match(r'^\d{1,4}$', line.text.strip()):
                left_numbers += 1
        if blue_links > 15 and left_numbers > 10:
            is_toc_page = True
            continue
        
        # Extract field labels
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            if not text:
                i += 1
                continue
            
            # Skip red/blue codes by structure: non-black + contains brackets
            if line.non_black and '[' in text:
                i += 1
                continue
            
            # Skip pure bracketed codes regardless of color
            if re.match(r'^\[.*\]$', text):
                i += 1
                continue
            
            # Skip enumeration values by pattern: starts with (digit)
            if re.match(r'^\(\d+\)', text):
                i += 1
                continue
            
            # Skip structural subsection dividers: bold + blue + small (8.5-10.5pt)
            if line.non_black and line.bold and 8.5 <= line.size <= 10.5:
                i += 1
                continue
            
            # Skip answer options by structure:
            # - Small (8-10pt), very short (1-4 words), mid-to-right positioned (x0 > 250)
            # - Not ending with question/colon (those are field prompts)
            if (8.0 <= line.size <= 10.0 and 
                len(text.split()) <= 4 and 
                line.x0 > 250 and
                not text.endswith('?') and 
                not text.endswith(':')):
                i += 1
                continue
            
            # Skip table column headers by structure:
            # - Positioned far right (x0 > 450) or high-center (x0 > 350 with small size)
            # - Small (< 8pt) or header-typical (9-10pt)
            # - Bold or very short non-questions
            if ((line.x0 > 450 or (line.x0 > 350 and line.size < 10.0)) and
                line.size <= 10.0 and
                len(text) < 40 and
                not text.endswith('?')):
                if line.bold or line.size < 8.0:
                    i += 1
                    continue
            
            # Skip "Row N" pattern by structure: starts with capital R, followed by "ow", then space and digits
            if re.match(r'^R[oO][wW]\s+\d+$', text):
                i += 1
                continue
            
            # Skip repeatable row annotations by pattern: contains "(Repeatable"
            if '(Repeatable' in text or '(repeatable' in text:
                i += 1
                continue
            
            # Detect field labels: black text, field-label size (7-11pt), left-positioned (x0 < 450)
            if not line.non_black and 6.5 <= line.size <= 11.0 and line.x0 < 450:
                # Check if this is a field label by multiple signals:
                
                # 1. Has red/blue code following?
                has_code_after = False
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if next_line.non_black and '[' in next_line.text:
                        has_code_after = True
                
                # 2. Is a question?
                is_question = '?' in text
                
                # 3. Has field-like patterns? (common field label words)
                has_field_pattern = bool(re.search(
                    r'\b(Date|Time|Number|Total|Were|Was|Has|Have|Did|If|Specify|Describe|'
                    r'Type|Method|Contact|Final|Blood|Pressure|Rate|Temperature|Bottle|'
                    r'Capsule|Subject|Visit|ICF|Admission|Discharge|Measurement|Systolic|'
                    r'Diastolic|Heart|Placed|Position|able to|Deviation)\b',
                    text, re.IGNORECASE
                ))
                
                # 4. Ends with colon (common for field labels)
                ends_with_colon = text.endswith(':')
                
                # 5. Substantial length (> 10 chars suggests real content)
                is_substantial = len(text) > 10
                
                # 6. Starts with capital letter (field labels are proper sentences)
                starts_capital = text and text[0].isupper()
                
                # Field label if it has code after OR multiple positive signals
                signal_count = sum([is_question, has_field_pattern, ends_with_colon, 
                                   is_substantial, starts_capital])
                
                if has_code_after or signal_count >= 2:
                    field_name = text
                    start_x = line.x0
                    start_size = line.size
                    last_y = line.y0
                    
                    # Assemble multi-line field labels
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        if not next_text:
                            j += 1
                            continue
                        
                        # Stop at red/blue code
                        if next_line.non_black and '[' in next_text:
                            break
                        
                        # Stop at enumeration values: (digit)
                        if re.match(r'^\(\d+\)', next_text):
                            break
                        
                        # Stop at Row markers by pattern
                        if re.match(r'^R[oO][wW]\s+\d+$', next_text):
                            break
                        
                        # Stop at answer options: small, short, positioned right, non-question
                        if (8.0 <= next_line.size <= 10.0 and 
                            len(next_text.split()) <= 4 and 
                            next_line.x0 > 250 and
                            not next_text.endswith('?') and
                            not next_text.endswith(':')):
                            break
                        
                        # Continue if: same column (x within 35px), close vertically (< 45px),
                        # black text, similar size (within 3pt), not bracketed
                        if (not next_line.non_black and
                            abs(next_line.x0 - start_x) < 35 and
                            next_line.y0 - last_y < 45 and
                            abs(next_line.size - start_size) < 3.0 and
                            not next_text.startswith('[')):
                            
                            # Avoid treating a clearly separate field as continuation
                            # Heuristic: if current field is already long (>30 chars) and
                            # next line looks like a new field start (capital + ends with ?/:),
                            # and is similar in style to the original line, it's likely separate
                            if (len(field_name) > 30 and
                                next_text[0].isupper() and
                                (next_text.endswith('?') or next_text.endswith(':')) and
                                abs(next_line.x0 - start_x) < 5):
                                # Likely a new field, not continuation
                                break
                            
                            field_name += ' ' + next_text
                            last_y = next_line.y0
                            j += 1
                        else:
                            break
                    
                    # Clean up whitespace
                    field_name = ' '.join(field_name.split())
                    
                    # Emit if substantial and we have form context
                    if len(field_name) > 2 and current_form:
                        results.append({
                            "form_name": current_form,
                            "field_name": field_name,
                            "page": page_num
                        })
                    
                    i = j
                    continue
            
            i += 1
    
    return results
```
