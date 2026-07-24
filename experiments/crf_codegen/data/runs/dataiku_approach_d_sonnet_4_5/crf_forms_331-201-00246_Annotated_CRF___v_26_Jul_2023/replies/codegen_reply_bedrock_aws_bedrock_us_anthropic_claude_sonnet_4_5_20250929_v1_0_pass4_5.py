```python
import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form title - large colored text (sz >= 15, colored, not black)
        form_title = None
        for line in lines:
            if line.size >= 15 and line.non_black and line.text.strip():
                text = line.text.strip()
                # Skip generic section headers that aren't form titles
                if text not in ["CHANGE HISTORY", "SCHEDULE OF ASSESSMENT", "PAGES"]:
                    form_title = text
                    break
        
        if form_title:
            current_form = form_title
        
        # Skip pages with no form context
        if not current_form:
            continue
        
        # Identify page type by structural markers
        
        # Copyright/attribution pages: have copyright symbol and long attribution text at bottom
        has_copyright = any("© 2008 The Research Foundation" in line.text for line in lines)
        if has_copyright:
            continue
        
        # Table of contents pages: have "Annotated CRF" title
        is_toc = any(line.text == "Annotated CRF" and line.size >= 20 for line in lines)
        if is_toc:
            continue
        
        # Change history pages: detect by "Change History" title AND tabular structure
        # Key: has column headers "Version", "Date", "Changed By", "Details" in header region
        has_change_title = any("Change History" in line.text and line.size >= 15 for line in lines)
        if has_change_title:
            # Check for change history column headers in upper region
            header_texts = [l.text.strip() for l in lines if l.y0 < 250 and l.size >= 9]
            if any("Version" in h for h in header_texts) and any("Changed By" in h for h in header_texts):
                # Skip this entire page - it's a change history table
                continue
        
        # Section title pages: only have form title and "(Repeatable row...)" note, very sparse
        # These have the form title, the repeatable note, and page number - nothing else
        non_page_num_lines = [l for l in lines if not re.match(r'^Page \d+ of \d+$', l.text.strip())]
        non_title_lines = [l for l in non_page_num_lines if not (l.size >= 15 and l.non_black)]
        repeatable_note_lines = [l for l in non_title_lines if "Repeatable row" in l.text]
        
        # If page only has title + repeatable note (very sparse), skip
        if len(non_title_lines) <= 2 and len(repeatable_note_lines) > 0:
            continue
        
        # Extract fields
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty lines
            if not text:
                i += 1
                continue
            
            # Skip page numbers (structural: bottom of page, specific format)
            if re.match(r'^Page \d+ of \d+$', text):
                i += 1
                continue
            
            # Skip red technical annotations (structural: red color #ff0000)
            if line.non_black and '#ff0000' in str(line.non_black).lower():
                i += 1
                continue
            
            # Skip gray text (structural: gray color #999999)
            if line.non_black and '#999999' in str(line.non_black).lower():
                i += 1
                continue
            
            # Skip bullet points alone
            if text == '•':
                i += 1
                continue
            
            # Skip "Row N" labels (structural: specific pattern)
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip "(Repeatable row...)" notes (structural: parenthetical note)
            if "Repeatable row" in text and text.startswith("("):
                i += 1
                continue
            
            # Skip form titles (already captured, structural: large colored)
            if line.size >= 15 and line.non_black:
                i += 1
                continue
            
            # Skip copyright/attribution text (structural: contains copyright symbol, at bottom)
            if "©" in text and line.y0 > 250:
                i += 1
                continue
            
            # Skip long attribution paragraphs (structural: very long lines, small font, at bottom)
            if len(text) > 100 and line.y0 > 140 and line.y0 < 300 and line.size <= 9:
                i += 1
                continue
            
            # Skip change history data cells (structural: in change history context, small text in data region)
            # These are below the header region (y > 250) and are short fragments
            if "Change History" in current_form:
                # Skip all content on change history pages - they're metadata tables
                i += 1
                continue
            
            # Handle table headers (structural: upper region of page, y < 200, size >= 9)
            if line.y0 >= 100 and line.y0 <= 200 and line.size >= 9 and not line.non_black:
                # This is a potential column header
                # Collect multi-line headers (continuation at same x position)
                header_text = text
                j = i + 1
                while j < len(lines) and lines[j].y0 <= 200 and abs(lines[j].x0 - line.x0) < 20:
                    next_text = lines[j].text.strip()
                    if next_text and not re.match(r'^Page \d+ of \d+$', next_text):
                        header_text += " " + next_text
                    j += 1
                
                # Valid header: reasonable length, not just ID markers
                if len(header_text) > 2 and not re.match(r'^(Record|ID|Sample)$', header_text):
                    results.append({
                        "form_name": current_form,
                        "field_name": header_text,
                        "page": page_num
                    })
                i = j if j > i + 1 else i + 1
                continue
            
            # Regular field labels (structural: black text, size 8.5-12, not in header/footer regions)
            if not line.non_black and line.size >= 8.5 and line.size <= 12:
                # Skip if in footer region (y > 750)
                if line.y0 > 750:
                    i += 1
                    continue
                
                # Skip if in header attribution region (y < 300 and very long)
                if line.y0 < 300 and len(text) > 100:
                    i += 1
                    continue
                
                # Skip section headers (structural: bold, larger size >= 11)
                if line.bold and line.size >= 11:
                    i += 1
                    continue
                
                # Check if this looks like a question/field label
                if len(text) >= 3:
                    # Collect continuation lines (structural: same x position, close y)
                    field_text = text
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        # Check if continuation (similar x, close y, not red, not page number)
                        if (abs(next_line.x0 - line.x0) < 10 and 
                            next_line.y0 - lines[j-1].y0 < 20 and
                            not (next_line.non_black and '#ff0000' in str(next_line.non_black).lower()) and
                            next_line.text.strip() and
                            not re.match(r'^Page \d+ of \d+$', next_line.text)):
                            field_text += " " + next_line.text.strip()
                            j += 1
                        else:
                            break
                    
                    # Skip short answer options (structural: very short, common answer words)
                    if len(field_text) <= 5 and field_text in ["Yes", "No", "N/A", "X", "Scan"]:
                        i = j if j > i + 1 else i + 1
                        continue
                    
                    # Skip bullet list items that are very short (structural: starts with bullet, < 30 chars)
                    if field_text.startswith("•") and len(field_text) < 30:
                        i = j if j > i + 1 else i + 1
                        continue
                    
                    # Skip answer option lists (structural: multiple short items at same x, close y)
                    # These are typically 2-3 words each, stacked vertically
                    # BUT: if the text is long (>50 chars) or contains question markers, it's likely a field
                    is_likely_question = len(field_text) > 50 or '?' in field_text
                    
                    if not is_likely_question and len(field_text.split()) <= 3 and j < len(lines):
                        # Look ahead to see if there are more short items at same x
                        similar_items = 1
                        k = j
                        while k < len(lines) and k < j + 3:
                            if (abs(lines[k].x0 - line.x0) < 10 and 
                                lines[k].y0 - lines[k-1].y0 < 20 and
                                len(lines[k].text.strip().split()) <= 3):
                                similar_items += 1
                                k += 1
                            else:
                                break
                        
                        # If we found multiple short items stacked, skip this as answer options
                        if similar_items >= 2:
                            i = j if j > i + 1 else i + 1
                            continue
                    
                    # Additional check: skip if this looks like a checkbox option
                    # (short text that's part of a list of birth control methods, etc.)
                    # Structural: if text is < 80 chars and doesn't end with '?', and there are
                    # similar items nearby at same x, it's likely an option not a field
                    if (not is_likely_question and 
                        len(field_text) < 80 and 
                        not field_text.endswith('?') and
                        j < len(lines)):
                        # Check if there are similar-length items at same x within next few lines
                        similar_count = 0
                        k = j
                        while k < len(lines) and k < j + 5:
                            if (abs(lines[k].x0 - line.x0) < 10 and 
                                lines[k].y0 - lines[k-1].y0 < 25 and
                                len(lines[k].text.strip()) > 10 and
                                len(lines[k].text.strip()) < 100):
                                similar_count += 1
                                k += 1
                            else:
                                break
                        
                        # If we found 2+ similar items, this is likely a checkbox list
                        if similar_count >= 2:
                            i = j if j > i + 1 else i + 1
                            continue
                    
                    # Valid field
                    results.append({
                        "form_name": current_form,
                        "field_name": field_text,
                        "page": page_num
                    })
                    i = j if j > i + 1 else i + 1
                    continue
            
            i += 1
    
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for r in results:
        key = (r["form_name"], r["field_name"], r["page"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    
    return deduped
```