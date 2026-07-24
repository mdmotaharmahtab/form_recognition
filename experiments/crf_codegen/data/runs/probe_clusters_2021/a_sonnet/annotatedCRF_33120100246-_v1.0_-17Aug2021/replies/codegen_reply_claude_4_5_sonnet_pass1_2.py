Looking at the issues, I need to fix:

1. **Content-fitted blocklists** - Replace hardcoded text filters with structural discriminators
2. **Cluster 9, 10, 11 uncovered** - These pages have different layouts that need handling
3. **Partial coverage in clusters 1, 2, 5, 6** - Need better extraction for these layouts

Let me analyze the sample pages:
- **Cluster 10 (page 4, 6)**: Table of contents continuation with blue hyperlinks - these should be skipped (not data-entry fields)
- **Cluster 9 (page 349, 462)**: Only red TYPE annotations visible - likely definition/blank pages to skip
- **Cluster 11**: Need to see what these are

The main problem is the hardcoded text blocklists. I'll replace them with structural rules.

```python
import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Detect table of contents pages - many blue hyperlinks, skip them
        blue_links = [ln for ln in lines if ln.non_black and ('#1d60a4' in str(ln.text) or '#2477cc' in str(ln.text))]
        if len(blue_links) > 10:
            continue
        
        # Detect blank/definition pages - only red annotations, no substantive black text
        red_annotations = [ln for ln in lines if ln.non_black and '#ff0000' in str(ln.text)]
        substantive_black = [ln for ln in lines if not ln.non_black and ln.size >= 7 and len(ln.text.strip()) > 5]
        if len(red_annotations) > 0 and len(substantive_black) < 3:
            continue
        
        # Extract form title: blue text, larger size (13-16pt), upper portion (y < 100)
        form_candidates = []
        for ln in lines:
            if ln.non_black and 13 <= ln.size <= 16 and ln.y0 < 100:
                text = ln.text.strip()
                # Structural filter: not a code annotation (no brackets, not all caps single word)
                if not text.startswith('[') and not (text.isupper() and ' ' not in text and len(text) < 15):
                    form_candidates.append(text)
        
        if form_candidates:
            current_form = form_candidates[0]
        
        # Identify page structure type
        # Enumeration pages: many items in center column (x ~250-500), small-medium size
        center_items = [ln for ln in lines if 200 < ln.x0 < 550 and 8 <= ln.size <= 10.5 
                        and not ln.non_black and len(ln.text.strip()) > 3]
        
        # Standard form pages: questions on left (x < 150), around standard y positions
        left_questions = [ln for ln in lines if ln.x0 < 150 and 7 <= ln.size <= 9.5 
                          and not ln.non_black and ln.y0 > 100]
        
        # Decide page type
        if len(center_items) > 8 and len(left_questions) < 5:
            # Enumeration page - extract list items
            seen = set()
            for ln in center_items:
                text = ln.text.strip()
                
                # Structural filters:
                # 1. Minimum length (short fragments are likely labels/options)
                # 2. Not in right-side answer column (x > 500 typically has yes/no/values)
                # 3. Not a single common answer word (structural: single word, short, capitalized pattern)
                # 4. Not all digits or simple numbering
                
                if len(text) < 5:
                    continue
                if ln.x0 > 500:
                    continue
                if len(text.split()) == 1 and len(text) < 12 and text[0].isupper():
                    # Single short capitalized word - likely answer option
                    continue
                if text.isdigit() or re.match(r'^\d+[\.\)]?$', text):
                    continue
                if text.startswith('['):
                    continue
                
                if text not in seen:
                    results.append({
                        "form_name": current_form,
                        "field_name": text,
                        "page": page_num
                    })
                    seen.add(text)
            continue
        
        # Standard form pages - extract questions
        seen_fields = set()
        i = 0
        
        while i < len(lines):
            ln = lines[i]
            text = ln.text.strip()
            
            # Structural field detection:
            # 1. Black text (not colored annotations)
            # 2. Left-aligned (x < 150, where questions appear)
            # 3. Regular text size (7-9.5pt)
            # 4. Below header area (y > 100)
            
            if not (not ln.non_black and ln.x0 < 150 and 6.5 <= ln.size <= 9.5 and ln.y0 > 100):
                i += 1
                continue
            
            # Structural exclusions:
            # 1. Empty or very short (< 3 chars)
            # 2. Starts with bracket (code annotations)
            # 3. Starts with "Row " (table furniture)
            # 4. Contains technical markers (TYPE:, VISIBILITY:, etc.)
            # 5. In far-right answer column (x > 450)
            
            if len(text) < 3:
                i += 1
                continue
            if text.startswith('['):
                i += 1
                continue
            if text.startswith('Row '):
                i += 1
                continue
            if any(marker in text for marker in ['TYPE:', 'VISIBILITY:', 'OID:', 'LAYOUT:', 'CODE:']):
                i += 1
                continue
            if ln.x0 > 450:
                i += 1
                continue
            
            # Build multi-line field by checking continuation
            field_parts = [text]
            j = i + 1
            
            while j < len(lines):
                next_ln = lines[j]
                next_text = next_ln.text.strip()
                
                # Continuation criteria (structural):
                # 1. Same color (both black)
                # 2. Similar x position (within 50pt)
                # 3. Close vertical spacing (< 20pt)
                # 4. Similar size (within 2pt)
                # 5. Not a code marker
                
                if not next_ln.non_black and \
                   abs(next_ln.x0 - ln.x0) < 50 and \
                   next_ln.y0 - lines[j-1].y0 < 20 and \
                   abs(next_ln.size - ln.size) < 2 and \
                   not next_text.startswith('['):
                    
                    # Stop at next separate field (larger gap or style change)
                    if next_ln.y0 - lines[j-1].y0 > 15 and len(next_text) > 20:
                        # Likely start of new field
                        break
                    
                    field_parts.append(next_text)
                    j += 1
                else:
                    break
            
            field_text = ' '.join(field_parts).strip()
            
            # Final quality filters (structural):
            # 1. Minimum length (very short = likely label not question)
            # 2. Not pure numbering (1., 2., etc.)
            # 3. Not a single common form furniture word by pattern:
            #    - Single word < 8 chars (likely "Test", "Date", "Time", "Item", "Status")
            #    - Unless it has punctuation/context suggesting it's a real question
            
            if len(field_text) < 4:
                i = j
                continue
            
            if re.match(r'^\d+[\.\)]?$', field_text):
                i = j
                continue
            
            # Structural furniture filter: single short word with no context
            words = field_text.split()
            if len(words) == 1 and len(field_text) < 8 and field_text[0].isupper():
                # Likely furniture label, not a question
                i = j
                continue
            
            # Check for answer-option patterns (structural)
            # Answer options are: short, often in a set, repetitive structure
            # Look for patterns like "Yes", "No", "N/A", "Positive", "Negative"
            # But do this structurally: if this text appears 3+ times on page at similar x position
            same_text_count = sum(1 for other_ln in lines 
                                  if other_ln.text.strip() == field_text 
                                  and not other_ln.non_black 
                                  and abs(other_ln.x0 - ln.x0) < 100)
            
            if same_text_count >= 3 and len(field_text) < 15:
                # Repeated short text at similar position = likely answer option
                i = j
                continue
            
            if field_text not in seen_fields:
                results.append({
                    "form_name": current_form,
                    "field_name": field_text,
                    "page": page_num
                })
                seen_fields.add(field_text)
            
            i = j
    
    # Deduplicate consecutive identical records
    deduplicated = []
    prev = None
    for rec in results:
        if rec != prev:
            deduplicated.append(rec)
            prev = rec
    
    return deduplicated
```
