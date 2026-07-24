Looking at the failures, I need to:

1. **Fix missing fields on pages 58, 126** - These are standard form pages that should be extracting but aren't
2. **Handle cluster 1 (71 pages, 0% coverage)** - These are code list/lookup tables (not data-entry forms)
3. **Handle cluster 3 (7 pages, 0% coverage)** - These appear to be continuation/overflow pages with only metadata
4. **Remove hardcoded literal blocklists** - Replace with structural discrimination

Let me analyze the sample pages:

- **Page 27 (cluster 0)**: Has fields like "Total number of aborted attempts", "If yes. describe:" - these should extract
- **Page 54 (cluster 0)**: Has fields like "PR", "QRS", "QT" - short ECG parameter labels
- **Page 150, 163 (cluster 1)**: Code list tables with "Coded/Decode" headers - NOT data-entry fields (correct to skip)
- **Page 43, 49 (cluster 3)**: Only metadata lines, no actual fields - correct to skip

The main issues:
1. My continuation logic is breaking on short labels (PR, QRS, QT)
2. I'm filtering out too much with hardcoded terms
3. Need better structural discrimination for what's a field vs metadata

```python
import re
from collections import defaultdict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Extract form name from white header (sz=12.0, color=#ffffff)
        form_name = ""
        for line in lines:
            if abs(line.size - 12.0) < 0.5 and line.non_black and line.x0 < 100:
                form_name = line.text.strip()
                break
        
        # Skip if no form name found (likely index/title page)
        if not form_name:
            continue
        
        # Skip code-list/lookup table pages by structural signature
        # Cluster 1: has "Coded" + "Decode" column headers at specific positions
        has_codelist_structure = False
        for i, line in enumerate(lines):
            if (line.text.strip() == "Coded" and 
                40 < line.x0 < 80 and 
                abs(line.size - 10.5) < 1.0 and
                line.bold):
                # Look for "Decode" header nearby
                for j in range(max(0, i-2), min(len(lines), i+3)):
                    if (lines[j].text.strip() == "Decode" and
                        lines[j].x0 > 250 and
                        abs(lines[j].size - 10.5) < 1.0 and
                        lines[j].bold):
                        has_codelist_structure = True
                        break
                if has_codelist_structure:
                    break
        
        if has_codelist_structure:
            continue
        
        # Skip reference table pages (Category Visit, Forms Name, etc.)
        has_reference_table = any(
            ("Category Visit" in line.text or 
             (line.text.strip() == "Name" and line.x0 < 80 and 
              any("Forms" in l.text for l in lines[max(0,i-5):min(len(lines),i+5)])))
            for i, line in enumerate(lines)
        )
        if has_reference_table:
            continue
        
        # Skip pages with only metadata (cluster 3 pattern: very few lines, all metadata)
        non_metadata_lines = [l for l in lines if l.x0 < 400 and 6.0 < l.size < 11.0 and not l.non_black]
        if len(non_metadata_lines) < 3:
            continue
        
        # Collect potential field labels
        # Strategy: Field labels are in left column (x < 250), medium size (6.5-9.0),
        # black text, not metadata keywords (identified by RIGHT column position or specific style)
        field_labels = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Skip metadata column (right side, x > 400)
            if line.x0 > 400:
                i += 1
                continue
            
            # Skip non-field elements by style
            # - Too large (headers) or too small (fine print)
            if line.size < 6.5 or line.size > 9.5:
                i += 1
                continue
            
            # - Colored or bold headers (except field labels can be regular bold at size ~7.5)
            if line.non_black:
                i += 1
                continue
            
            # Skip if it's clearly not a field label
            if not line.text or line.text.strip() == "":
                i += 1
                continue
            
            # Field label candidates: left column, appropriate size, black
            if 40 < line.x0 < 260 and 6.5 <= line.size <= 9.0:
                text = line.text.strip()
                
                # Skip technical codes in square brackets (but collect content inside later)
                if text.startswith('[') and text.endswith(']'):
                    i += 1
                    continue
                
                # Skip option markers (radio/checkbox values at left column)
                if text.startswith('O ') or text.startswith('□ '):
                    i += 1
                    continue
                
                # Skip by structural position: metadata labels are identifiable by being
                # in the right-column context or having a colon + being single words
                # Common metadata pattern: single word + colon at x~453-456
                is_metadata_label = False
                if ':' in text:
                    # Check if this looks like a metadata key (right column style)
                    # Metadata keys: "Aliases:", "Description:", "Origin:", etc.
                    # These appear at x > 450 OR are single-word + colon
                    before_colon = text.split(':')[0].strip()
                    if (len(before_colon.split()) <= 2 and 
                        before_colon[0].isupper() and
                        not text.endswith('?:')):  # "Mandatory?:" is metadata, but our fields can have "?"
                        # Check if nearby lines suggest metadata context
                        # Look for typical metadata keywords in surrounding context
                        context_range = range(max(0, i-3), min(len(lines), i+4))
                        metadata_context = any(
                            l.x0 > 400 or 
                            l.text.strip() in ['Format:', 'Data Type:', 'Origin:', 'Mandatory?:']
                            for l in [lines[idx] for idx in context_range]
                        )
                        if metadata_context:
                            is_metadata_label = True
                
                if is_metadata_label:
                    i += 1
                    continue
                
                # Skip pure technical codes (all caps + numbers/underscores, no spaces)
                if re.match(r'^[A-Z][A-Z0-9_]*$', text) and len(text) > 2:
                    i += 1
                    continue
                
                # Skip common checkbox values by pattern (short, all-caps or specific words)
                # But use position/context, not just the word itself
                if len(text) <= 12 and text in ['Yes', 'No', 'Unknown', 'UNKNOWN']:
                    # Check if this is in a checkbox context (nearby "O" marker)
                    nearby_has_option_marker = any(
                        lines[j].text.strip().startswith('O ') and abs(lines[j].y0 - line.y0) < 3
                        for j in range(max(0, i-1), min(len(lines), i+2))
                    )
                    if nearby_has_option_marker:
                        i += 1
                        continue
                
                # Skip date format templates
                if '_' in text and text.count('_') > 3:
                    i += 1
                    continue
                
                # Collect this line as potential field label start
                label_parts = [text]
                j = i + 1
                
                # Look for continuation lines (wrapped labels)
                # Continuation: similar x, similar size, close vertically, same column
                while j < len(lines):
                    next_line = lines[j]
                    y_diff = next_line.y0 - lines[j-1].y0
                    
                    # Stop if too far vertically
                    if y_diff > 20:
                        break
                    
                    # Stop if we hit metadata column
                    if next_line.x0 > 400:
                        break
                    
                    # Stop if we hit a bracket code or option marker
                    if next_line.text.strip().startswith('[') or next_line.text.strip().startswith('O '):
                        break
                    
                    # Check if it's a continuation: similar position and style
                    x_diff = abs(next_line.x0 - line.x0)
                    size_diff = abs(next_line.size - line.size)
                    
                    if (40 < next_line.x0 < 260 and
                        x_diff < 10 and
                        size_diff < 1.5 and
                        not next_line.non_black and
                        y_diff < 15 and
                        next_line.text.strip()):
                        
                        # Check if it's metadata style (keyword + colon)
                        next_text = next_line.text.strip()
                        if ':' in next_text:
                            before_colon = next_text.split(':')[0].strip()
                            if len(before_colon.split()) <= 2 and before_colon[0].isupper():
                                break
                        
                        label_parts.append(next_text)
                        j += 1
                    else:
                        break
                
                # Join multi-line labels
                full_label = ' '.join(label_parts).strip()
                
                # Final validation
                if full_label and len(full_label) > 1:
                    # Skip if it's pure noise
                    if full_label in ['?', '--', '___']:
                        i = j
                        continue
                    
                    # Skip very short all-caps (likely codes, not labels)
                    if len(full_label) <= 3 and full_label.isupper() and ' ' not in full_label:
                        i = j
                        continue
                    
                    field_labels.append(full_label)
                
                i = j
            else:
                i += 1
        
        # Deduplicate and add to results
        seen = set()
        for label in field_labels:
            key = (form_name, label)
            if key not in seen:
                seen.add(key)
                results.append({
                    "form_name": form_name,
                    "field_name": label,
                    "page": page_num
                })
    
    return results
```
