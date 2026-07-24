```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Detect pure reference/lookup table pages (cluster 1) - skip entirely
        # These have symmetric two-column "Coded/Decode" layout with no field labels
        has_coded_decode = False
        for ln in lines:
            if ln.y0 < 80 and ln.size >= 10 and "Coded" in ln.text:
                # Check for paired "Decode" header nearby
                for ln2 in lines:
                    if (ln2.y0 < 80 and ln2.size >= 10 and "Decode" in ln2.text and
                        abs(ln2.y0 - ln.y0) < 5 and ln2.x0 > ln.x0 + 200):
                        has_coded_decode = True
                        break
        
        if has_coded_decode:
            # Verify it's a pure lookup table (no field label column at x<100)
            has_field_labels = any(
                ln.x0 < 100 and ln.y0 > 100 and 7 <= ln.size <= 8 and
                re.search(r'\[.*?\]', ln.text)
                for ln in lines
            )
            if not has_field_labels:
                continue  # skip reference table page
        
        # Detect cover/approval pages by signature markers
        if any("By signing below" in ln.text or "aCRF Approval Form" in ln.text 
               for ln in lines):
            continue
        
        # Extract form name from white-on-color header (cluster 0 field definition pages)
        for ln in lines:
            if (ln.y0 < 50 and ln.size >= 11 and ln.non_black):
                candidate = ln.text.strip()
                # Structural filter: reject technical metadata patterns
                if (candidate and len(candidate) > 2 and
                    not re.match(r'^(Origin|Aliases|Repeating|Domain|SAS|Protocol|Sponsor|DM-\d)', candidate)):
                    current_form = candidate
                    break
        
        # Detect schedule table pages (cluster 2/3) by structural markers
        # Look for "Study Event" column header at left edge or time patterns in column 2
        has_schedule_structure = False
        for ln in lines:
            if (ln.x0 < 60 and ln.y0 < 80 and ln.size >= 9 and
                ln.text.strip() == "Study Event"):
                has_schedule_structure = True
                break
        
        # Also detect by time column pattern (cluster 2 variant)
        if not has_schedule_structure:
            time_patterns = sum(1 for ln in lines 
                              if 120 < ln.x0 < 160 and ln.y0 > 50 and 
                              re.match(r'^[\d:\-\*\(\)]+$', ln.text.strip()))
            if time_patterns > 5:
                has_schedule_structure = True
        
        if has_schedule_structure:
            # Extract form names from schedule tables
            # Forms appear in rightmost text column, size ~9.0, y>50
            # Structural position: x in range 150-250 for main form column
            
            form_candidates = []
            
            for ln in lines:
                # Form column: x ~165-210 (main position), size ~9, y>50, black text
                if (ln.y0 > 50 and 150 < ln.x0 < 220 and
                    abs(ln.size - 9.0) < 0.5 and not ln.non_black):
                    
                    form_text = ln.text.strip()
                    
                    # Structural filters
                    if not form_text or len(form_text) < 3:
                        continue
                    
                    # Exclude by structure: time patterns (all digits/colons/dashes)
                    if re.match(r'^[\d:*().\-\s]+$', form_text):
                        continue
                    
                    # Exclude by structure: "Day N" pattern
                    if re.match(r'^Day\s+\d+$', form_text):
                        continue
                    
                    # Accept as form name
                    form_candidates.append(form_text)
            
            # Add unique forms from this schedule page
            for form_text in set(form_candidates):
                results.append({
                    "form_name": form_text,
                    "field_name": form_text,
                    "page": page_num
                })
            
            continue  # done with schedule page
        
        # Field definition pages (cluster 0): detailed field layouts
        # Field labels at x ~40-70, y>90, size ~7-8, black text
        # Technical metadata in right column (x>400) - ignore
        # Fields may wrap across multiple lines - join them
        
        field_candidates = []
        i = 0
        while i < len(lines):
            ln = lines[i]
            
            # Field label column: x in 40-100 (expanded range), y>70, size 7-9, black
            if (40 < ln.x0 < 100 and ln.y0 > 70 and 7 <= ln.size <= 9 and
                not ln.non_black):
                
                text = ln.text.strip()
                
                # Skip empty or very short
                if not text or len(text) < 3:
                    i += 1
                    continue
                
                # Structural filters - no literal text blocklists
                
                # Skip if in right metadata column (x>400)
                if ln.x0 > 400:
                    i += 1
                    continue
                
                # Skip technical markers by pattern (structural: brackets with code syntax)
                # This catches [SAS Field Name: ...], [PETEST], etc.
                if re.match(r'^\[(?:[A-Z_]+[:\.]|SAS\s)', text):
                    i += 1
                    continue
                
                # Skip answer options (structural: starts with "O " - radio button)
                if re.match(r'^O\s', text):
                    i += 1
                    continue
                
                # Skip text input placeholders (structural: bracket pattern)
                if re.match(r'^\[_{3,}\]$', text):
                    i += 1
                    continue
                
                # Skip code list annotations (gray text pattern in middle column)
                if ln.size < 7.5 and 240 < ln.x0 < 270:
                    i += 1
                    continue
                
                # Collect wrapped continuations: same x0, consecutive y positions
                parts = [text]
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    prev = lines[j-1]
                    
                    # Continuation: same x column, y close to previous, same size/color
                    if (abs(nxt.x0 - ln.x0) < 5 and nxt.y0 - prev.y0 < 15 and
                        7 <= nxt.size <= 9 and not nxt.non_black and
                        nxt.x0 < 100):  # still in left column
                        
                        # Stop if we hit a structural boundary marker
                        if re.match(r'^\[(?:[A-Z_]+[:\.]|SAS\s)', nxt.text.strip()):
                            break
                        if re.match(r'^O\s', nxt.text.strip()):
                            break
                            
                        parts.append(nxt.text.strip())
                        j += 1
                    else:
                        break
                
                full_text = " ".join(parts)
                
                # Final filter: must look like a human-readable question/label
                # Check it's not a pure technical pattern
                if (len(full_text) > 4 and 
                    not re.match(r'^[A-Z_]+$', full_text)):  # not pure uppercase code
                    field_candidates.append((ln.y0, full_text))
                
                i = j  # skip past continuations
            else:
                i += 1
        
        # De-duplicate vertically close fields (within 15pt y-band)
        field_candidates.sort()
        seen_y = []
        for y, fld in field_candidates:
            # Check if this y is far enough from all previously seen y values
            if not any(abs(y - sy) < 15 for sy in seen_y):
                seen_y.append(y)
                results.append({
                    "form_name": current_form,
                    "field_name": fld,
                    "page": page_num
                })
    
    # Final de-duplication by (form_name, field_name)
    unique = {}
    for rec in results:
        key = (rec["form_name"], rec["field_name"])
        if key not in unique:
            unique[key] = rec
    
    return list(unique.values())
```
