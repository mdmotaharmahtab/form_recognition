Let me write the improved extraction program:

```python
import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    form_last_seen_page = -1
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip table-of-contents pages (pages 1-10)
        if page_num <= 10:
            continue
        
        # Detect if this is a TOC/schedule page (all or mostly blue links)
        if is_toc_or_schedule_page(lines):
            continue
        
        # Identify form title: large blue/colored text near top, typically 14+ pt
        form_candidates = [ln for ln in lines if ln.y0 < 120 and ln.size >= 14 and ln.non_black]
        if form_candidates:
            current_form = form_candidates[0].text.strip()
            form_last_seen_page = page_num
        elif page_num - form_last_seen_page > 5:
            # Reset form if we haven't seen a title in 5+ pages
            current_form = ""
        
        # Collect field candidates: black OR dark gray text
        candidates = []
        for ln in lines:
            # Skip red annotations (technical codes)
            if is_red_annotation(ln):
                continue
            
            # Accept black text or dark gray (#454545)
            if ln.non_black and not is_dark_gray(ln):
                continue
            
            # Reasonable label size (7-10.5pt) - extended upper bound slightly
            if ln.size < 7 or ln.size > 10.5:
                continue
            
            candidates.append(ln)
        
        # Parse by structural position
        for ln in candidates:
            txt = ln.text.strip()
            
            if not txt:
                continue
            
            # Skip by structure, not literal text
            if should_skip_by_structure(txt, ln, lines, page_num):
                continue
            
            # Valid field label
            if current_form:
                records.append({
                    "form_name": current_form,
                    "field_name": txt,
                    "page": page_num
                })
        
        # Extract checkbox enumeration labels (right-side lists)
        # These are the category labels for checkbox groups
        enum_labels = extract_enumeration_labels(lines, page_num)
        for label in enum_labels:
            if current_form:
                records.append({
                    "form_name": current_form,
                    "field_name": label,
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


def extract_enumeration_labels(lines, page_num):
    """Extract enumeration/checkbox option labels that form field categories."""
    labels = []
    
    # Look for vertical lists of options on the right side
    # These are gray (#454545) text, x > 350, size ~9pt
    right_side_options = [
        ln for ln in lines 
        if ln.non_black 
        and ln.x0 > 350 
        and ln.size >= 8.5 and ln.size <= 10
        and len(ln.text.strip()) > 2
        and not is_red_annotation(ln)
    ]
    
    if not right_side_options:
        return labels
    
    # Group by vertical clusters (items within 25px vertically)
    clusters = []
    for ln in sorted(right_side_options, key=lambda x: x.y0):
        txt = ln.text.strip()
        
        # Skip obvious non-field text
        if txt in ['Yes', 'No', 'Scan']:
            continue
        if re.match(r'^[0-9]+h?\s*(postdose|predose|Postdose|Predose)', txt.lower()):
            continue
        
        placed = False
        for cluster in clusters:
            # Check if this line is close to any item in cluster
            if any(abs(ln.y0 - item.y0) < 25 for item in cluster):
                cluster.append(ln)
                placed = True
                break
        
        if not placed:
            clusters.append([ln])
    
    # Extract labels from clusters with 3+ items (likely checkbox lists)
    for cluster in clusters:
        if len(cluster) >= 3:
            for ln in cluster:
                txt = ln.text.strip()
                # Clean up and validate
                if len(txt) > 1 and len(txt) < 80:
                    labels.append(txt)
    
    return labels


def is_toc_or_schedule_page(lines):
    """Detect table-of-contents or schedule pages (blue links, no data entry)."""
    # Count blue/colored text lines (hyperlinks in TOC)
    colored_lines = [ln for ln in lines if ln.non_black and ln.size >= 7 and ln.size <= 14]
    total_content_lines = [ln for ln in lines if ln.size >= 7 and ln.size <= 14 and len(ln.text.strip()) > 2]
    
    if len(total_content_lines) < 10:
        return False
    
    # If >70% of content is colored (blue links), it's likely a TOC page
    if len(colored_lines) / len(total_content_lines) > 0.7:
        return True
    
    # Check for schedule table structure: "Schedule_" prefix or repeated visit/page number patterns
    schedule_markers = [ln for ln in lines if ln.text.strip().startswith('Schedule_')]
    if schedule_markers:
        return True
    
    return False


def is_red_annotation(line):
    """Technical annotations are in red color."""
    if not line.non_black:
        return False
    
    txt = line.text.strip()
    
    # Red annotations have specific patterns: [code: description] or technical markers
    if txt.startswith('[') and (':' in txt or txt.endswith(']')):
        return True
    
    return False


def is_dark_gray(line):
    """Check if line is dark gray (#454545) which is used for field labels."""
    if not line.non_black:
        return False
    
    txt = line.text.strip()
    
    # If it's red annotation syntax, it's not gray
    if txt.startswith('['):
        return False
    
    # Gray text characteristics:
    # - Left-aligned or mid-page (x < 450 for field labels, extended range)
    # - Reasonable size (7-10pt)
    # - Not single characters
    if line.x0 < 450 and line.size >= 7 and line.size <= 10.5 and len(txt) > 1:
        return True
    
    return False


def should_skip_by_structure(text, line, all_lines, page_num):
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
    
    # 5. Very short answers on far right side (x > 450)
    if line.x0 > 450 and len(text) <= 20:
        return True
    
    # 6. Version/date stamps
    if re.match(r'^Version \d+', text) or re.match(r'^\d{1,2}[A-Z][a-z]{2}\d{4}$', text):
        return True
    
    # 7. Overly long instructional text (> 200 chars) is likely instructions not field label
    if len(text) > 200:
        return True
    
    # 8. Schedule/template markers (repeated structural keywords)
    if text.startswith('Schedule_'):
        return True
    
    # 9. Copyright/legal text markers by structure: bottom of page + keywords
    if line.y0 > 550 and any(kw in text.lower() for kw in ['copyright', '©', 'reprints', 'permission', 'disclaimer']):
        return True
    
    # 10. Detect disclaimer/legal blocks: very long text with legal keywords
    if is_disclaimer_or_legal_block(text, line, all_lines):
        return True
    
    # 11. Detect timing/dosage labels that are column headers (not data fields)
    # These appear in specific vertical patterns with consistent spacing
    if is_timing_column_header(text, line, all_lines):
        return True
    
    # 12. Very short text on right side (x > 250) and small size - likely scale anchors
    if line.x0 > 280 and len(text) <= 15 and line.size < 8:
        return True
    
    # 13. Detect title-like text that's actually a section marker, not field label
    # Bold text at far left in specific size range, surrounded by structural markers
    if is_section_marker_not_field(text, line, all_lines):
        return True
    
    # 14. Instructional text at bottom of page (collect vital signs instructions)
    if line.y0 > 600 and len(text) > 60:
        return True
    
    # 15. Citations and author lists (name lists with semicolons)
    if ';' in text and re.search(r'[A-Z]\.\;', text):
        return True
    
    # 16. Text with multiple author-like patterns
    if text.count(',') > 3 and text.count(';') > 2:
        return True
    
    return False


def is_disclaimer_or_legal_block(text, line, all_lines):
    """Detect disclaimer, copyright, or legal text blocks."""
    # Legal text markers
    legal_keywords = [
        'disclaimer', 'copyright', 'scale is intended', 
        'individuals who have received training',
        'determination of the presence',
        'based on those used in'
    ]
    
    # Check for legal keywords
    text_lower = text.lower()
    if any(kw in text_lower for kw in legal_keywords):
        return True
    
    # Long text block with formal language patterns
    if len(text) > 100:
        formal_patterns = [
            r'this scale',
            r'is intended to',
            r'based on those',
            r'individuals who have',
            r'determination of'
        ]
        if any(re.search(pat, text_lower) for pat in formal_patterns):
            return True
    
    return False


def is_timing_column_header(text, line, all_lines):
    """Detect timing labels like '1h postdose' that are column headers, not fields."""
    # Pattern: time + postdose/predose
    if not re.match(r'^\d+\.?\d*h?\s*(postdose|predose|Postdose|Predose)', text.lower()):
        return False
    
    # Column headers appear in consistent vertical sequences
    # Find similar lines nearby (within 50px vertically)
    similar_nearby = [
        ln for ln in all_lines 
        if abs(ln.y0 - line.y0) < 50 
        and ln.x0 > 250  # Right side positioning
        and re.match(r'^\d+\.?\d*h?\s*(postdose|predose)', ln.text.strip().lower())
    ]
    
    # If 3+ timing labels clustered together, they're column headers
    if len(similar_nearby) >= 3:
        return True
    
    return False


def is_section_marker_not_field(text, line, all_lines):
    """Detect section markers that look like bold headers but aren't field labels."""
    # Section markers are often:
    # - At very left margin (x < 50)
    # - Larger bold text
    # - Followed immediately by structural elements (tables, visit numbers)
    
    if line.x0 > 50:
        return False
    
    # Check for bold/large text
    if line.size < 9:
        return False
    
    # Look for "Visit Number", "Page Number", "Visit Label" patterns below
    nearby_below = [
        ln for ln in all_lines
        if ln.y0 > line.y0 and ln.y0 < line.y0 + 30
        and re.match(r'^(Visit|Page|Schedule)\s*(Number|Label|Name)?$', ln.text.strip())
    ]
    
    if nearby_below:
        return True
    
    return False
```
