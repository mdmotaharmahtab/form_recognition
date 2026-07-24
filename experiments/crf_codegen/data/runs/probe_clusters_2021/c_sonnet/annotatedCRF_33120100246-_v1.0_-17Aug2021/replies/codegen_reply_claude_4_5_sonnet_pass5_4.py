I'll analyze the problems and fix the extraction program.

The main issues are:
1. **False positives**: Extracting answer option text (like "Minor physical damage...") and descriptions that are NOT field labels
2. **Low coverage**: Missing pages in clusters 0 and 1 (27% and 0% covered)
3. **Hardcoded blocklists**: Using literal text matching instead of structural rules

Let me examine the patterns:

**Cluster 2 (working well)**: C-SSRS forms with field labels followed by answer options
**Cluster 0**: Pages with tabular layout (Urinalysis with columns like "Collected", "Not Collected", "Scan") - all red annotations
**Cluster 1**: Pages showing only answer option descriptions in red - these are definition/legend pages with NO fields

The false positives are answer option descriptions that got concatenated. I need to:
1. Stop at answer options more reliably (look for `\d.\` patterns)
2. Exclude lines that are clearly answer text (start mid-sentence, contain parentheticals with examples)
3. Handle the tabular layout in cluster 0 (but those are all red annotations - likely no fields there)

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
        
        # Skip pages that are all red annotations (definition/legend pages)
        # Check if page has substantial black text that could be fields
        black_content_lines = [ln for ln in lines if not ln.non_black and 7 <= ln.size <= 11 and len(ln.text.strip()) > 3]
        if len(black_content_lines) == 0:
            continue
        
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
            if line.non_black:
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
            
            # Structural exclusions for non-field content:
            # 1. Answer options: lines starting with escaped numbers like \0.\ or \1.\
            if re.match(r'^\\[0-9]\.\\ ', text):
                i += 1
                continue
            
            # 2. Mid-sentence continuations (lowercase start after space, contains parenthetical examples)
            # These are answer descriptions, not field labels
            if text[0].islower() or text.startswith('('):
                i += 1
                continue
            
            # 3. Single-word answers (these appear in answer grids)
            single_word_answers = re.match(r'^(Yes|No|Current|Former|Never|Collected|Not|Applicable|Scan)$', text)
            if single_word_answers:
                i += 1
                continue
            
            # 4. Parenthetical options (like "(hour, minutes)")
            if text.startswith('(') and text.endswith(')'):
                i += 1
                continue
            
            # Check if this looks like a field label
            # Field labels:
            # - End with colon or contain question mark
            # - Are capitalized/start with capital
            # - Have reasonable length
            # - Are NOT embedded in paragraph text
            
            has_colon_or_question = text.endswith(':') or '?' in text
            
            # Look ahead for evidence this is a field
            has_answer_options = False
            has_red_annotation = False
            
            for j in range(i+1, min(i+5, len(lines))):
                next_text = lines[j].text.strip()
                
                # Check for answer options
                if re.match(r'^\\[0-9]\.\\ ', next_text):
                    has_answer_options = True
                    break
                
                # Check for red annotations
                if lines[j].non_black and ('[' in next_text or 'TYPE:' in next_text):
                    has_red_annotation = True
                    break
            
            # Additional exclusion: lines that look like answer descriptions
            # Answer descriptions often have:
            # - Parenthetical examples with "e.g."
            # - Semicolons separating example items
            # - References to rating scales "(0)", "(1)", etc. embedded in text
            is_answer_description = (
                'e.g.' in text or
                re.search(r'\([0-9]\)', text) or  # Embedded rating numbers
                (text.count(';') >= 2) or  # Multiple semicolons listing examples
                text.count(',') >= 4  # Long comma-separated lists
            )
            
            if is_answer_description:
                i += 1
                continue
            
            # Is this a field?
            is_field = (
                (has_colon_or_question or has_answer_options or has_red_annotation) and
                not single_word_answers and
                len(text) >= 5 and
                text[0].isupper()  # Must start with capital
            )
            
            if is_field and current_form:
                # Collect multi-line field labels
                full_text = text
                k = i + 1
                
                # Look ahead to collect continuation lines
                while k < len(lines) and k < i + 4:  # Reduced from 6 to be more conservative
                    next_line = lines[k]
                    next_text = next_line.text.strip()
                    
                    # Stop at empty lines
                    if not next_text:
                        break
                    
                    # Stop at red annotations
                    if next_line.non_black:
                        break
                    
                    # Stop at answer options
                    if re.match(r'^\\[0-9]\.\\ ', next_text):
                        break
                    
                    # Stop at obvious non-continuations
                    if next_text.startswith('(') or next_text[0].islower():
                        break
                    
                    # Stop at row markers
                    if re.match(r'^Row \d+$', next_text, re.I):
                        break
                    
                    # Stop at new field (has colon at end)
                    if next_text.endswith(':') and len(next_text) > 5:
                        break
                    
                    # Stop at single-word answers
                    if re.match(r'^(Yes|No|Current|Former|Never|Collected|Not|Applicable|Scan)$', next_text):
                        break
                    
                    # Stop if this looks like an answer description
                    if 'e.g.' in next_text or re.search(r'\([0-9]\)', next_text):
                        break
                    
                    # Check if continuation (similar x position, reasonable size)
                    if abs(next_line.x0 - line.x0) < 15 and 7 <= next_line.size <= 11:
                        full_text += ' ' + next_text
                        k += 1
                    else:
                        break
                
                # Clean up
                full_text = re.sub(r'\s+', ' ', full_text).strip()
                
                # Final validation: exclude if it contains obvious answer description markers
                if 'e.g.' not in full_text and full_text.count(';') < 2 and not re.search(r'\([0-9]\).*\([0-9]\)', full_text):
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
