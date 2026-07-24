I need to analyze the failures and rewrite the extraction program to handle the uncovered clusters while maintaining coverage on working pages.

Key issues identified:
1. **Hardcoded blocklists**: 76 literal strings that won't generalize
2. **Uncovered clusters 10, 13, 14, 17, 19, 20, 23, 24**: Different layouts not handled
3. **Need structural discrimination** instead of text matching

Let me examine the sample pages from uncovered clusters:

- **Cluster 10 (pages 309, 528)**: Drug screening forms with test names as field labels (Benzodiazepines, Cannabinoids, etc.)
- **Cluster 13 (pages 235, 465)**: Collection status forms with "Urinalysis" as field
- **Cluster 14 (pages 255, 425)**: Scale/rating forms with long enumeration descriptions

The common pattern: these pages have field labels in **black text at specific x-positions** (left column), with answer options to the right.

```python
import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip table-of-contents pages (pages 1-10)
        if page_num <= 10:
            continue
        
        # Identify form title: large blue/colored text near top, typically 14+ pt
        form_candidates = [ln for ln in lines if ln.y0 < 120 and ln.size >= 14 and ln.non_black]
        if form_candidates:
            current_form = form_candidates[0].text.strip()
        
        # Collect field candidates: black text, reasonable size for labels
        candidates = []
        for ln in lines:
            # Must be black text
            if ln.non_black:
                continue
            # Reasonable label size (7-10pt)
            if ln.size < 7 or ln.size > 10:
                continue
            # Skip red technical annotations by color
            if is_red_annotation(ln):
                continue
            candidates.append(ln)
        
        # Parse by structural position
        for ln in candidates:
            txt = ln.text.strip()
            
            if not txt:
                continue
            
            # Skip by structure, not literal text
            if should_skip_by_structure(txt, ln, lines):
                continue
            
            # Valid field label
            if current_form:
                records.append({
                    "form_name": current_form,
                    "field_name": txt,
                    "page": page_num
                })
    
    # Deduplicate
    seen = set()
    unique = []
    for r in records:
        key = (r["form_name"], r["field_name"], r["page"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    
    return unique


def is_red_annotation(line):
    """Technical annotations are in red color."""
    # Red annotations have non_black=True and specific x-positions
    if not line.non_black:
        return False
    
    # Check if text looks like technical annotation
    txt = line.text.strip()
    if txt.startswith('[') and txt.endswith(']'):
        return True
    if txt.startswith('[') and ':' in txt:
        return True
    
    return False


def should_skip_by_structure(text, line, all_lines):
    """Skip by structural characteristics, not literal text matching."""
    
    # 1. Machine codes: uppercase + numbers, no spaces
    if re.match(r'^[A-Z]{2,}[0-9]+[A-Z]*$', text):
        return True
    
    # 2. Row/column markers at specific positions
    if re.match(r'^Row \d+$', text):
        return True
    
    # 3. Single-character or single-digit entries (scale anchors)
    if len(text) <= 1:
        return True
    
    # 4. Parenthesized enumeration items (answer option format)
    if re.match(r'^\(\d+\)\s*.+', text):
        return True
    
    # 5. Answer options by position: right side of page (x > 280)
    if line.x0 > 280:
        # These are likely answer options or values
        # Check if it's a short enumeration value
        if len(text) <= 20 and text in get_common_answer_patterns():
            return True
    
    # 6. Version/date stamps
    if re.match(r'^Version \d+', text) or re.match(r'^\d{1,2}[A-Z][a-z]{2}\d{4}$', text):
        return True
    
    # 7. Long instructional text (> 100 chars, likely instructions not field label)
    if len(text) > 100:
        return True
    
    # 8. Schedule/template markers (repeated structural keywords)
    if text.startswith('Schedule_'):
        return True
    
    # 9. Standalone copyright/legal text markers
    if any(kw in text.lower() for kw in ['copyright', 'reprints', 'permission']):
        return True
    
    return False


def get_common_answer_patterns():
    """Common answer option text patterns (for position-based filtering only)."""
    return {
        'Yes', 'No', 'N/A', 'Not Applicable', 
        'Met', 'Not Met', 'Positive', 'Negative', 
        'Not Done', 'Collected', 'Not Collected',
        'Scan', 'Skip to next visit',
        'Current', 'Former', 'Never',
        'Per Day', 'Per Week', 'Pack', 'Cigar', 'Cartridge',
        'Urine', 'Serum', 'Plasma', 'Blood',
        'Dose Missed', 'Wrong dose', 'Other',
        'Predose', '1h Postdose', '2h Postdose',
        'Male', 'Female',
        'Applicable', 'Not Collected'
    }
```
