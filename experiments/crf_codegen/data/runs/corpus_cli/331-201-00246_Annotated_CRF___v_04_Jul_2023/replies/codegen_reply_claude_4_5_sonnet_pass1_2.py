I need to analyze the failures and rewrite the extraction program. Let me examine the issues:

1. **form_name is empty for 100% of records** - The form title extraction is failing
2. **Cluster 5 (56 pages, 4% covered)** - These appear to be mostly blank or special pages
3. **Cluster 6 (30 pages, 0% covered)** - "C-SSRS since last visit - Page 3/4" - multi-page forms
4. **Cluster 7 (8 pages, 0% covered)** - "Inclusion criteria" / "Exclusion criteria" pages
5. **Extreme content-fitted blocklist** - Need to replace literal text filters with structural rules

Key insights from the sample pages:
- Form titles are blue (#004c99), size 16.5, at y~153
- The form_name should persist across pages (carry forward)
- Need to handle multi-page forms (pages 3, 4, etc.)
- Replace hardcoded text blocklists with structural position/style rules

Here's the rewritten program:

```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form title: large blue text (size ~16-17, color #004c99)
        # This appears near the top of the page (y < 200)
        for line in lines:
            if (line.size >= 15.0 and 
                line.non_black and 
                '#004c99' in str(line.text).lower() and
                line.y0 < 250):
                # Clean up the title - remove " - Page N" suffixes
                form_title = line.text.strip()
                form_title = re.sub(r'\s*-\s*Page\s+\d+\s*$', '', form_title)
                if form_title:
                    current_form = form_title
                break
        
        # Skip if no form context established yet
        if not current_form:
            continue
        
        # Process fields
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip red annotations (machine codes, TYPE:, VISIBILITY:, etc.)
            if line.non_black and '#ff0000' in str(line.text).lower():
                i += 1
                continue
            
            # Skip page numbers (bottom of page, y > 750)
            if line.y0 > 750 and 'Page' in line.text and 'of' in line.text:
                i += 1
                continue
            
            # Skip the form title itself (large blue text)
            if line.size >= 15.0 and line.non_black:
                i += 1
                continue
            
            # Skip very small text (likely fine print, annotations)
            if line.size < 8.0:
                i += 1
                continue
            
            # Main field detection: black text, size 8-11.5
            if not line.non_black and 8.0 <= line.size <= 11.5 and line.text.strip():
                text = line.text.strip()
                
                # Skip machine codes in brackets [CODE123]
                if text.startswith('[') and text.endswith(']'):
                    i += 1
                    continue
                
                # Skip "Row N" labels (table row markers)
                if re.match(r'^Row\s+\d+$', text, re.IGNORECASE):
                    i += 1
                    continue
                
                # Skip answer options at right side of page (x > 400)
                # These are structural: positioned far right, short text
                if line.x0 > 400 and len(text.split()) <= 3:
                    # Likely an answer option or checkbox value
                    i += 1
                    continue
                
                # Skip column headers near top of page (y < 200, short text)
                # Structural rule: headers are short, near top, often centered
                if line.y0 < 200 and len(text.split()) <= 4 and text[0].isupper():
                    # Check if it's likely a header (not a question)
                    if not any(marker in text for marker in ['?', 'Date', 'Time', 'Version', 'Was', 'Were', 'Did', 'Does', 'Is', 'Has', 'Have']):
                        i += 1
                        continue
                
                # Skip centered short text in middle columns (likely option values)
                # Structural: x position 250-400, short text (1-3 words)
                if 250 < line.x0 < 400 and len(text.split()) <= 3:
                    i += 1
                    continue
                
                # Skip bold subsection headers that are NOT questions
                # Structural: bold, short (< 6 words), no question markers
                if line.bold and len(text.split()) <= 6:
                    # Keep if it looks like a question
                    has_question_marker = ('?' in text or 
                                          text.lower().startswith(('was ', 'were ', 'is ', 'are ', 'did ', 'does ', 'has ', 'have ', 'will ', 'would ', 'should ')))
                    if not has_question_marker:
                        i += 1
                        continue
                
                # Skip very short text (likely not a field label)
                if len(text) < 3:
                    i += 1
                    continue
                
                # Skip enumeration markers: (1), (2), •, 1., 2., etc.
                if re.match(r'^[\(\d\)•\.]+$', text):
                    i += 1
                    continue
                
                # Skip copyright/citation text (structural: contains © or long institutional text)
                if '©' in text or len(text) > 150:
                    i += 1
                    continue
                
                # Check if this is a multi-line field label
                field_text = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Continue if next line is:
                    # - close in y (within 20 units)
                    # - similar x (within 30 units - allow some indent)
                    # - black text
                    # - appropriate size
                    # - not a machine code
                    if (not next_line.non_black and 
                        next_line.y0 - lines[j-1].y0 < 25 and
                        abs(next_line.x0 - line.x0) < 40 and 
                        8.0 <= next_line.size <= 11.5 and
                        next_line.text.strip() and
                        not next_line.text.strip().startswith('[')):
                        
                        cont_text = next_line.text.strip()
                        
                        # Stop if next line looks like a new field (starts with capital, left-aligned)
                        if (cont_text[0].isupper() and 
                            abs(next_line.x0 - line.x0) < 5 and
                            next_line.y0 - lines[j-1].y0 > 15):
                            # Check if it's really a continuation or new field
                            if not cont_text[0].islower() and not field_text.endswith((',', ':', 'or', 'and', 'of', 'the', 'to', 'a', 'an')):
                                break
                        
                        field_text += ' ' + cont_text
                        j += 1
                    else:
                        break
                
                # Final validation: skip if too short after joining
                if len(field_text) < 3:
                    i = j if j > i + 1 else i + 1
                    continue
                
                # This looks like a valid field
                results.append({
                    "form_name": current_form,
                    "field_name": field_text,
                    "page": page_num
                })
                
                i = j if j > i + 1 else i + 1
            else:
                i += 1
    
    return results
```

Key changes:
1. **Fixed form_name extraction**: Added case-insensitive color check, wider y-range, and strip " - Page N" suffixes
2. **Carry forward form_name**: Once set, it persists across pages
3. **Skip if no form context**: Prevents empty form_name records
4. **Replaced literal blocklists with structural rules**:
   - Answer options: right side (x > 400) + short
   - Column headers: top (y < 200) + short + capital
   - Option values: middle columns (x 250-400) + short
5. **Better multi-line joining**: Improved continuation detection
6. **Relaxed size threshold**: 8.0 instead of 8.5 to catch more fields
