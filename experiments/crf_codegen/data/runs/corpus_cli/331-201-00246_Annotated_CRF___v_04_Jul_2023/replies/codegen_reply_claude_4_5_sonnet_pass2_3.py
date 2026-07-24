Looking at the problems, I need to fix:

1. **Change History tables** (pages 11-12): These are tabular data where column headers and cell values are being extracted as fields
2. **C-SSRS rating scales** (page 120, 683): Rating anchors and scale descriptors are being extracted
3. **Disclaimers and instruction text** (page 250): Long prose text is being extracted
4. **Table of contents pages** (pages 5, 8 - cluster 6): These are TOC pages with blue hyperlinks, currently 0% covered (correctly!)

The key insight: I need better **structural discrimination** based on:
- **Tables**: Detect tabular layouts and skip cell content (keep only the table's title)
- **Multi-column text in parentheses**: Rating anchors like "(0) Does not apply"
- **Long prose**: Disclaimers, instructions (sentences > certain length)
- **Blue hyperlinked text**: TOC entries (color #2477cc)

Let me rewrite with these structural filters:

```python
import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Sort lines by y, then x for processing
        sorted_lines = sorted(lines, key=lambda ln: (ln.y0, ln.x0))
        
        # Detect form name: large text (size >= 14), often colored or bold
        # Typically at top of page (y < 350)
        # EXCLUDE blue TOC links (#2477cc)
        form_candidates = []
        for line in sorted_lines:
            if line.y0 < 350 and line.size >= 14:
                text = line.text.strip()
                # Skip page numbers
                if re.search(r'^Page\s+\d+\s+of\s+\d+', text, re.I):
                    continue
                # Skip pure numbers (table row numbers)
                if re.match(r'^\d+(\.\d+)?\.?\s*$', text):
                    continue
                # Skip blue TOC hyperlinks
                if line.non_black and '#2477cc' in str(line.non_black).lower():
                    continue
                # Valid form title
                if len(text) > 3:
                    form_candidates.append((line.y0, text))
        
        # Pick the topmost substantial form title
        if form_candidates:
            form_candidates.sort()
            current_form = form_candidates[0][1]
        
        # DETECT TABULAR LAYOUT
        # If page has many lines with similar y-coordinates (rows) and varied x-coordinates (columns),
        # it's likely a table. Count y-coordinate clusters.
        y_coords = [line.y0 for line in sorted_lines if 100 < line.y0 < 800 and line.size >= 8]
        y_clusters = defaultdict(int)
        for y in y_coords:
            # Cluster y values within 5 points
            cluster_key = round(y / 5) * 5
            y_clusters[cluster_key] += 1
        
        # If many rows have 3+ items, it's tabular
        rows_with_multiple_items = sum(1 for count in y_clusters.values() if count >= 3)
        is_table_page = rows_with_multiple_items >= 8
        
        # Extract fields using structural rules
        field_lines = []
        
        for line in sorted_lines:
            text = line.text.strip()
            
            # Skip empty
            if not text:
                continue
            
            # STRUCTURAL FILTERS
            
            # 1. Skip red annotations (technical metadata)
            if line.non_black and '#ff0000' in str(line.non_black).lower():
                continue
            
            # 2. Skip blue TOC hyperlinks (#2477cc)
            if line.non_black and '#2477cc' in str(line.non_black).lower():
                continue
            
            # 3. Skip page numbers (bottom of page, centered)
            if re.search(r'Page\s+\d+\s+of\s+\d+', text, re.I):
                continue
            
            # 4. Skip lines that are pure bracketed annotations
            if text.startswith('[') and text.endswith(']'):
                continue
            
            # 5. Skip very large text (>= 14pt) - those are headers/titles
            if line.size >= 14:
                continue
            
            # 6. Skip very small text (< 8pt) - typically footnotes
            if line.size < 8:
                continue
            
            # 7. Skip answer options: single-word gray text
            if line.non_black and len(text.split()) <= 2 and text in ['Yes', 'No', 'X', 'N/A', 'Male', 'Female']:
                continue
            
            # 8. Skip lines at extreme page edges (furniture)
            if line.y0 < 100 or line.y0 > 800:
                continue
            
            # 9. Skip standalone dates (change history)
            if re.match(r'^\d{1,2}-?[A-Z][a-z]{2}-?\d{4}$', text):
                continue
            
            # 10. Skip version numbers (pure numeric patterns like "1.0" or "2.1.5")
            if re.match(r'^\d+(\.\d+)+$', text):
                continue
            
            # 11. Skip enumeration codes (3-6 uppercase letters + digits)
            if re.match(r'^[A-Z]{3,6}\d+$', text):
                continue
            
            # 12. Skip copyright symbols and URLs
            if '©' in text or 'copyright' in text.lower() or 'http' in text.lower():
                continue
            
            # 13. NEW: Skip rating scale anchors - patterns like "(0) Text" or "(1-5) Text"
            if re.match(r'^\([0-9\-]+\)\s+', text):
                continue
            
            # 14. NEW: Skip long prose text (disclaimers, instructions)
            # If text contains 2+ sentences (multiple '. ' or ends with period after 100+ chars), skip
            sentence_count = text.count('. ') + (1 if text.endswith('.') else 0)
            if sentence_count >= 2 or (len(text) > 100 and '.' in text):
                continue
            
            # 15. NEW: On table pages, skip most content (keep only if it looks like a section label)
            # Table cell content: non-bold, regular size, varies in x position
            if is_table_page:
                # Skip if it's small regular text at varied x positions (likely table cells)
                # Keep only if it's bold or larger (likely a row/section label)
                if not line.bold and line.size < 12:
                    continue
            
            # 16. Skip text that looks like table data values (names, short phrases in table cells)
            # Pattern: single name like "Andreea Hardut" or short phrase without punctuation
            if is_table_page:
                # If it contains slashes, likely a name pair in table cell
                if '/' in text:
                    continue
                # If it's 1-4 words with capital letters, likely table content
                words = text.split()
                if 1 <= len(words) <= 4 and any(w[0].isupper() for w in words if w):
                    # Check if it looks like a proper name or short table entry
                    # Real field labels usually have articles, prepositions, or longer structure
                    has_structure = any(w.lower() in ['the', 'a', 'an', 'of', 'for', 'to', 'in', 'at', 'on', 'by', 'with'] for w in words)
                    if not has_structure and not text.endswith(('?', ':')):
                        continue
            
            # POSITIVE SELECTION: Likely field labels
            # - Black or dark text (not red, not blue)
            # - Moderate size (8-13 pt)
            # - In main content area (y: 100-800)
            # - Has substance (length > 2)
            # - Looks like a label (ends with colon, or contains question mark, or has structural words)
            
            if (not (line.non_black and ('#ff0000' in str(line.non_black).lower() or '#2477cc' in str(line.non_black).lower())) and
                8 <= line.size <= 13 and
                100 < line.y0 < 800 and
                len(text) > 2):
                field_lines.append(line)
        
        # Join wrapped field labels: lines close in y and similar x
        grouped_fields = []
        i = 0
        while i < len(field_lines):
            label_parts = [field_lines[i].text.strip()]
            base_x = field_lines[i].x0
            last_y = field_lines[i].y0
            j = i + 1
            
            # Look ahead for continuation lines
            while j < len(field_lines):
                dy = field_lines[j].y0 - last_y
                dx = abs(field_lines[j].x0 - base_x)
                
                # If next line is close vertically (within 25 points) and similar x (within 40)
                # it's likely a continuation
                if dy < 25 and dx < 40:
                    label_parts.append(field_lines[j].text.strip())
                    last_y = field_lines[j].y0
                    j += 1
                else:
                    break
            
            full_label = ' '.join(label_parts)
            # Clean up the label
            full_label = re.sub(r'\s+', ' ', full_label).strip()
            
            # Final structural filter: skip very short or pure punctuation
            if len(full_label) > 2 and not re.match(r'^[•\-\d.,:;()\[\]]+$', full_label):
                grouped_fields.append(full_label)
            
            i = j if j > i else i + 1
        
        # Deduplicate within page
        seen = set()
        for field in grouped_fields:
            if field not in seen:
                seen.add(field)
                records.append({
                    "form_name": current_form,
                    "field_name": field,
                    "page": page_num
                })
    
    return records
```
