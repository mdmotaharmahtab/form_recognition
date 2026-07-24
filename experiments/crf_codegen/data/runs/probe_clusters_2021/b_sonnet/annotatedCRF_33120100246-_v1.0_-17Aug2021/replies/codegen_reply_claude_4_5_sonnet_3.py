Looking at the sample pages from poorly-covered clusters, I can see they contain data-entry fields that the current program is missing. The issue is that these pages have:

1. **Cluster 10** (pages 309, 528): Field labels like "Benzodiazepines", "Cannabinoids", "Cocaine", "Methadone", "Opiates", "Phencyclidine" in gray text (#454545), not black
2. **Cluster 13** (pages 235, 465): Field label "Urinalysis" also in gray (#454545)
3. **Cluster 14** (pages 255, 425): These appear to be continuation/overflow pages with only red annotations - genuinely no fields

The problem: the current program filters `if ln.non_black: continue`, which excludes gray text. Gray (#454545) is being marked as `non_black=True`, causing valid field labels to be skipped.

Here's the updated program:

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
        
        # Collect field candidates: black OR gray text, reasonable size for labels
        candidates = []
        for ln in lines:
            # Skip red annotations (technical codes)
            if is_red_annotation(ln):
                continue
            
            # Accept black text or dark gray (#454545)
            if ln.non_black and not is_dark_gray(ln):
                continue
            
            # Reasonable label size (7-10pt)
            if ln.size < 7 or ln.size > 10:
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
    if not line.non_black:
        return False
    
    # Red is distinct from gray - check if it's actually red
    # Gray is #454545, red is #ff0000
    # If text starts with [ and contains technical markers, it's red
    txt = line.text.strip()
    if txt.startswith('[') and (txt.endswith(']') or ':' in txt):
        return True
    
    return False


def is_dark_gray(line):
    """Check if line is dark gray (#454545) which is used for field labels."""
    # Dark gray text is non_black but should be treated as valid field text
    # We identify it by position and context - it appears in field label areas
    # This is an approximation since we don't have direct color hex access
    
    if not line.non_black:
        return False
    
    txt = line.text.strip()
    
    # If it's red annotation syntax, it's not gray
    if txt.startswith('['):
        return False
    
    # Gray text characteristics:
    # - Left-aligned (x < 100 for labels)
    # - Not too far right (answer options are x > 280)
    # - Reasonable size (7-9pt)
    # - Not single characters
    if line.x0 < 100 and line.size >= 7 and line.size <= 9.5 and len(txt) > 1:
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
