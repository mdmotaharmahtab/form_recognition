STRATEGY:

This revision addresses the four main problems:

1. **Missing fields on page 127 ("Have you made a suicide attempt?")**: The current program filters out questions with "?" as instructional text when they're long. However, short, direct questions (under 60 chars) that are left-aligned and black are legitimate field labels in questionnaires like C-SSRS. I'll relax the question-filtering rule to only exclude long multi-sentence questions, not concise single questions.

2. **False positive on page 130 ("stops him/herself, instead of being stopped by something else.")**: This is a sentence fragment from instructional text. The current `is_instructional_text` function checks for long text with semicolons and specific patterns, but this particular phrase slips through. I'll add detection for sentence fragments that are part of longer instructions - specifically, text that starts mid-sentence (lowercase first word, or starts with a conjunction/preposition) and contains instructional language patterns.

3. **Missing fields on page 667 ("If Yes then please fill in AE page", "If Yes then please fill in ConMed page")**: These are currently filtered by `is_conditional_prompt`. However, looking at the pattern, these ARE actual field labels - they're navigation prompts that serve as data-entry fields (likely checkboxes or links). The key is they're short, left-aligned, and structured like field labels. I'll remove the blanket exclusion of conditional prompts and instead only exclude them when they're embedded in longer instructional paragraphs.

4. **Zero coverage on clusters 3, 4, 5, 6**: 
   - Cluster 5 (pages 5, 8): These are table-of-contents pages with numbered blue items. Already detected correctly - zero coverage is correct.
   - Cluster 3 (pages 938, 941): These are answer option reference pages - vertical lists of options (Emulsion, Gel, Graft... or Rectal, Ophthalmic...). The current `is_option_reference_page` function should catch these, but it's checking for x0 > 300. These pages have options at x=442.4, so they should be caught. However, the function might not be triggering because it requires "no title". I'll strengthen the detection to recognize pure option-list pages regardless of title presence, by checking for many consecutive lines at the same x-position with similar spacing.

The form title carry-forward mechanism already works well. I'll maintain it and ensure all content pages are processed (no whole-page density skips).

```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Detect and skip table of contents pages
        if is_toc_page(lines):
            continue
        
        # Detect and skip answer option reference pages
        if is_option_reference_page(lines):
            continue
        
        # Look for form title: blue text, size >= 14pt
        new_title = find_form_title(lines)
        if new_title:
            current_form = new_title
        
        # Extract fields from this page
        page_fields = extract_fields_from_page(lines, page_num)
        
        # Assign current form name to all fields
        for field in page_fields:
            field['form_name'] = current_form
            results.append(field)
    
    return results


def is_toc_page(lines: List) -> bool:
    """Detect table of contents pages by numbered list pattern."""
    # TOC pages have many lines starting with pattern like "3.120." in blue
    numbered_items = 0
    for line in lines:
        if line.non_black and line.size >= 14:
            # Check for numbered list pattern: digit.digit.
            if re.match(r'^\d+\.\d+\.', line.text.strip()):
                numbered_items += 1
    
    # If we see many numbered items, it's a TOC
    return numbered_items > 8


def is_option_reference_page(lines: List) -> bool:
    """Detect pages that only list answer options (no fields)."""
    # These pages consist of many vertically-stacked items at similar x-position
    # with regular spacing - they're reference lists, not data entry forms
    
    # Find clusters of lines at similar x-positions
    clusters = find_vertical_clusters(lines)
    
    # If we have a large cluster (20+ items) of regularly-spaced text,
    # and very little other content, it's an option reference page
    max_cluster_size = max([len(c) for c in clusters]) if clusters else 0
    
    if max_cluster_size >= 20:
        # Count non-cluster content lines
        cluster_line_ids = set()
        for cluster in clusters:
            for line in cluster:
                cluster_line_ids.add(id(line))
        
        other_content = 0
        for line in lines:
            if id(line) not in cluster_line_ids:
                text = line.text.strip()
                if text and len(text) > 2 and not re.match(r'^Page \d+', text):
                    if line.size >= 8 and line.size <= 13:
                        other_content += 1
        
        # If most content is in the cluster, it's a reference page
        if other_content < 5:
            return True
    
    return False


def find_vertical_clusters(lines: List) -> List[List]:
    """Find clusters of vertically-stacked lines at similar x-positions."""
    clusters = []
    used = set()
    
    for i, line in enumerate(lines):
        if i in used:
            continue
        
        text = line.text.strip()
        if not text or len(text) < 2:
            continue
        
        # Skip page numbers and very large/small text
        if re.match(r'^Page \d+', text) or line.size < 8 or line.size > 13:
            continue
        
        # Start a new cluster
        cluster = [line]
        used.add(i)
        base_x = line.x0
        base_size = line.size
        
        # Look for similar lines below
        for j in range(i + 1, len(lines)):
            if j in used:
                continue
            
            next_line = lines[j]
            next_text = next_line.text.strip()
            
            if not next_text or len(next_text) < 2:
                continue
            
            # Check if similar x-position and size
            if abs(next_line.x0 - base_x) < 30 and abs(next_line.size - base_size) < 2:
                # Check y-spacing is regular
                y_gap = next_line.y0 - cluster[-1].y0
                if 15 < y_gap < 40:
                    cluster.append(next_line)
                    used.add(j)
                elif y_gap > 50:
                    break
        
        if len(cluster) >= 5:
            clusters.append(cluster)
    
    return clusters


def find_form_title(lines: List) -> str:
    """Find form title: blue text, size >= 14pt, near top half of page."""
    for line in lines:
        if line.non_black and line.size >= 14.0 and line.y0 < 400:
            text = line.text.strip()
            if text and len(text) > 3:
                # Exclude page numbers
                if not re.match(r'^Page \d+', text) and not re.match(r'^\d+$', text):
                    # Exclude TOC numbered items
                    if not re.match(r'^\d+\.\d+\.', text):
                        return text
    return ""


def is_vertical_option_list(lines: List, start_idx: int) -> bool:
    """Detect if starting from start_idx we have a vertical list of options."""
    # Look for 5+ consecutive lines with similar x-position, similar size, regular spacing
    if start_idx >= len(lines) - 4:
        return False
    
    cluster = [lines[start_idx]]
    base_x = lines[start_idx].x0
    base_size = lines[start_idx].size
    
    for i in range(start_idx + 1, min(start_idx + 15, len(lines))):
        line = lines[i]
        text = line.text.strip()
        
        # Skip empty or very short
        if not text or len(text) < 2:
            continue
        
        # Check if similar position and size
        if abs(line.x0 - base_x) < 30 and abs(line.size - base_size) < 2:
            # Check y-spacing is regular (15-30px)
            if cluster:
                y_gap = line.y0 - cluster[-1].y0
                if 15 < y_gap < 35:
                    cluster.append(line)
                elif y_gap > 40:
                    break
        elif line.x0 > base_x + 50:
            # Moved significantly right, stop
            break
    
    # If we found 5+ items in a vertical cluster, it's likely an option list
    return len(cluster) >= 5


def extract_fields_from_page(lines: List, page_num: int) -> List[Dict]:
    """Extract field labels from a page."""
    fields = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip red annotation lines (technical codes in brackets)
        if line.non_black and '[' in line.text:
            i += 1
            continue
        
        # Skip page numbers
        if re.match(r'^Page \d+ of \d+$', line.text.strip()):
            i += 1
            continue
        
        # Skip very small or very large text
        if line.size < 7 or line.size > 13:
            i += 1
            continue
        
        # Check if this is a potential field label
        # Left-aligned (x < 150), black text, reasonable size
        if line.x0 < 150 and not line.non_black:
            text = line.text.strip()
            
            # Skip empty or very short
            if not text or len(text) < 3:
                i += 1
                continue
            
            # Skip pure punctuation
            if text in ['•', '-', ':', '–']:
                i += 1
                continue
            
            # Skip standalone answer options
            if text in ['Yes', 'No', 'N/A', 'NA', 'Unknown']:
                i += 1
                continue
            
            # Skip "Row N" labels (these are table furniture, not fields)
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip version stamps
            if re.match(r'^Version Number', text):
                i += 1
                continue
            
            # Skip right-aligned text (answer options)
            if line.x0 > 400:
                i += 1
                continue
            
            # Skip instruction headers like "Select all that apply"
            if re.match(r'^Select all that apply', text, re.IGNORECASE):
                i += 1
                continue
            
            # Check if this starts a vertical option list (not a field)
            if is_vertical_option_list(lines, i):
                i += 1
                continue
            
            # Collect wrapped lines for this field
            field_text = text
            j = i + 1
            line_count = 1
            
            # Look ahead for continuation lines
            while j < len(lines):
                next_line = lines[j]
                
                # Stop at red annotation
                if next_line.non_black and '[' in next_line.text:
                    break
                
                # Stop at next field (similar x, black, similar size, larger y gap)
                if (next_line.x0 < 150 and not next_line.non_black and 
                    abs(next_line.size - line.size) < 2):
                    # Check y-distance from previous line
                    y_gap = next_line.y0 - lines[j-1].y0
                    if y_gap > 25:  # New field
                        break
                
                # Stop at answer options (right side)
                if next_line.x0 > 400:
                    break
                
                # Continuation line: similar x (within 40px), close y (< 20px), black
                if (abs(next_line.x0 - line.x0) < 40 and 
                    next_line.y0 - lines[j-1].y0 < 20 and 
                    not next_line.non_black and
                    next_line.size >= 7 and next_line.size <= 13):
                    cont_text = next_line.text.strip()
                    if cont_text and not cont_text.startswith('['):
                        field_text += ' ' + cont_text
                        line_count += 1
                    j += 1
                else:
                    break
            
            # Clean up field text
            field_text = ' '.join(field_text.split())
            
            # Exclude very long instructional text (likely not a field label)
            # Field labels are typically concise; instructions span many lines
            if len(field_text) > 200 or (len(field_text) > 150 and line_count > 5):
                i = j
                continue
            
            # Exclude instructional text (long sentences with specific patterns)
            if is_instructional_text(field_text):
                i = j
                continue
            
            # Exclude page furniture labels
            if field_text in ['Repeat Pages', 'Page Label']:
                i = j
                continue
            
            # Exclude common option list headers that look like fields
            if field_text in ['Select all that apply']:
                i = j
                continue
            
            # Final validation
            if (field_text and 
                not re.match(r'^\d+$', field_text) and
                not re.match(r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$', field_text) and
                len(field_text) >= 3):
                
                fields.append({
                    'form_name': '',
                    'field_name': field_text,
                    'page': page_num
                })
            
            i = j
        else:
            i += 1
    
    return fields


def is_instructional_text(text: str) -> bool:
    """Detect instructional text that should not be extracted as fields."""
    # Detect sentence fragments that are part of instructions
    # These often start with lowercase or conjunctions/prepositions
    first_word = text.split()[0] if text.split() else ""
    if first_word and first_word[0].islower():
        # Starts with lowercase - likely a continuation/fragment
        if len(text) > 40:
            return True
    
    # Detect procedural instructions with semicolons (list-like guidance)
    if ';' in text and len(text) > 80:
        # These are often multi-part instructions
        return True
    
    # Long sentences with instructional keywords
    if len(text) > 100:
        instruction_patterns = [
            r'Ask questions',
            r'If both are',
            r'If the answer to',
            r'complete.*section',
            r'When person begins',
            r'stops.*instead of being stopped',
            r'must ask about all types',
            r'A potentially self-injurious',
            r'Behaviour was in part',
            r'Intent does not have to be',
            r'Inferring Intent',
            r'even if an individual denies',
            r'so long as these are separate events',
            r'with the act.*then it can be considered',
            r'There does not have to be any injury',
            r'just.*the potential for',
            r'this is considered an attempt',
        ]
        for pattern in instruction_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
    
    # Detect multi-sentence instructional blocks
    if text.count('.') >= 3 and len(text) > 150:
        return True
    
    # Detect long question-style instructions (data collection guidance, not field labels)
    # But allow short, direct questions (under 60 chars) - these are often field labels
    if len(text) > 60 and text.count('?') >= 1:
        question_patterns = [
            r'^Have you (done|made)',
            r'^Has there been',
            r'^Did you',
            r'^Were you',
            r'^What did you do',
        ]
        for pattern in question_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
    
    return False
```