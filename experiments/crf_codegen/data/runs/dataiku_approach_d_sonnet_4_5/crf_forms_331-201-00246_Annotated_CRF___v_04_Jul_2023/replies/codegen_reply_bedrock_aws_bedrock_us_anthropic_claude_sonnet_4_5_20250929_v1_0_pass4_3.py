```python
import re
from typing import List, Dict, Tuple

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Calculate page dimensions for relative positioning
        max_y = max(ln.y0 for ln in lines) if lines else 792
        max_x = max(ln.x0 for ln in lines) if lines else 612
        
        # Sort lines by y, then x for processing
        sorted_lines = sorted(lines, key=lambda ln: (ln.y0, ln.x0))
        
        # Look for form title: large colored text (sz >= 14, blue color)
        # Form titles typically appear near top of page
        for line in sorted_lines:
            if line.y0 < max_y * 0.3:  # Top 30% of page
                if line.size >= 14.0 and line.non_black:
                    text = line.text.strip()
                    # Skip page numbers
                    if text and not re.match(r'^Page \d+', text, re.IGNORECASE):
                        current_form = text
                        break
        
        # Detect if this is a "Change History" or version control page
        # These pages have specific patterns we should skip entirely
        is_change_history = False
        if current_form and 'change' in current_form.lower() and 'history' in current_form.lower():
            is_change_history = True
        
        # Also detect by content: if we see multiple date patterns and "Changed By"
        change_history_indicators = 0
        for line in sorted_lines[:20]:  # Check first 20 lines
            text = line.text.strip()
            if re.match(r'^\d{1,2}-[A-Za-z]{3}-\d{4}', text):
                change_history_indicators += 1
            if 'changed by' in text.lower() or 'version' in text.lower():
                change_history_indicators += 1
        
        if change_history_indicators >= 3:
            is_change_history = True
        
        # Skip extraction for change history pages
        if is_change_history:
            continue
        
        # Detect if this is a copyright/attribution footer page
        # These contain long copyright text and references
        copyright_lines = 0
        for line in sorted_lines:
            text = line.text.strip()
            if '©' in text or 'copyright' in text.lower():
                copyright_lines += 1
            if 'columbia' in text.lower() and 'suicide' in text.lower():
                copyright_lines += 1
            if 'oquendo' in text.lower() or 'mann' in text.lower():
                copyright_lines += 1
        
        is_copyright_page = copyright_lines >= 2
        
        # Extract field labels
        i = 0
        while i < len(sorted_lines):
            line = sorted_lines[i]
            
            # Skip if in footer area (bottom ~5% of page)
            if line.y0 > max_y * 0.95:
                i += 1
                continue
            
            # Skip if in extreme header area (top ~10% of page, except form titles already captured)
            if line.y0 < max_y * 0.1:
                i += 1
                continue
            
            # Skip if non-black (technical annotations in color)
            if line.non_black:
                i += 1
                continue
            
            text = line.text.strip()
            
            # Skip empty text
            if not text:
                i += 1
                continue
            
            # Skip page numbers (pattern: "Page N of M" or just "Page N")
            if re.match(r'^Page \d+', text, re.IGNORECASE):
                i += 1
                continue
            
            # Skip pure numbers (likely row numbers or IDs)
            if re.match(r'^\d+$', text):
                i += 1
                continue
            
            # Skip single characters (bullets, markers)
            if len(text) == 1:
                i += 1
                continue
            
            # Skip technical field codes in brackets
            if re.match(r'^\[.*\]$', text):
                i += 1
                continue
            
            # Skip if it's a repeatable row instruction (in parentheses, contains "row")
            if text.startswith('(') and text.endswith(')') and 'row' in text.lower():
                i += 1
                continue
            
            # Skip if it's bold and very short (likely a column header or marker)
            if line.bold and len(text) <= 3:
                i += 1
                continue
            
            # Skip copyright/attribution text by content patterns
            if is_copyright_page:
                i += 1
                continue
            
            # Skip long academic citations and references
            if len(text) > 150:
                # Check if it looks like a citation
                if any(indicator in text.lower() for indicator in 
                       ['developed by', 'ph.d.', 'm.d.', 'psychiatric institute', 
                        'reprints', 'inquiries', 'contact', 'evaluation in clinical']):
                    i += 1
                    continue
            
            # Skip version history table content by structural position
            # These typically appear in left columns with dates
            if re.match(r'^\d{1,2}-[A-Za-z]{3}-\d{4}', text):
                i += 1
                continue
            
            # Skip "Changed By" column headers
            if text.lower() in ['changed by', 'change description', 'version']:
                i += 1
                continue
            
            # Skip deployment/technical change descriptions
            # These are typically in specific columns and contain technical keywords
            technical_keywords = ['deploy', 'uat', 'integration', 'feedback sheet', 
                                 'client feedback', 'production', 'version', 'updated',
                                 'fixes for', 'implemented', 'applied changes']
            if any(keyword in text.lower() for keyword in technical_keywords):
                # But allow if it's a question or clearly a field label
                if '?' not in text and not text.endswith(':'):
                    i += 1
                    continue
            
            # Heuristic: Field labels are typically:
            # 1. Questions (contain ?)
            # 2. Descriptive phrases (multiple words, reasonable length)
            # 3. Date/time/status labels
            # 4. Not all uppercase unless it's a reasonable acronym
            
            is_field = False
            
            # Pattern 1: Questions
            if '?' in text:
                is_field = True
            
            # Pattern 2: Multi-word descriptive text (not too short, not all caps unless short)
            elif ' ' in text and len(text) > 8:
                # Allow if not all caps, or if all caps but short (acronym)
                if not text.isupper() or len(text) <= 15:
                    is_field = True
            
            # Pattern 3: Single-word labels with field-like keywords
            elif len(text) > 5:
                field_keywords = ['date', 'time', 'subject', 'patient', 'status', 
                                 'method', 'commit', 'transcribed', 'reason', 
                                 'placed', 'measurement', 'visit', 'sample',
                                 'barcode', 'collected', 'ongoing', 'indication',
                                 'medication', 'procedure', 'surgery', 'term',
                                 'record', 'start', 'end', 'timepoint', 'tubal',
                                 'intrauterine', 'birth', 'control', 'condom',
                                 'spermicide', 'sponge', 'implant', 'injection',
                                 'device', 'ligation', 'pills', 'depot']
                if any(keyword in text.lower() for keyword in field_keywords):
                    is_field = True
            
            # Pattern 4: Colon-terminated labels (common in forms)
            elif text.endswith(':') and len(text) > 3:
                is_field = True
            
            if is_field:
                # Check if next lines continue this label (wrapped text)
                full_label = text
                j = i + 1
                while j < len(sorted_lines):
                    next_line = sorted_lines[j]
                    
                    # If next line is within ~20 units in y and not colored
                    if (abs(next_line.y0 - line.y0) < 20 and 
                        not next_line.non_black):
                        next_text = next_line.text.strip()
                        
                        # Skip if it's empty or a bracket code
                        if not next_text or re.match(r'^\[.*\]$', next_text):
                            j += 1
                            continue
                        
                        # Skip if it's a page number
                        if re.match(r'^Page \d+', next_text, re.IGNORECASE):
                            break
                        
                        # Check if it looks like a continuation
                        if abs(next_line.x0 - line.x0) < 50:
                            # If it's very short and looks like an answer, stop
                            if len(next_text) <= 3 and next_text.upper() == next_text:
                                break
                            
                            # Otherwise, likely a continuation
                            full_label += ' ' + next_text
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # Clean up the label
                full_label = ' '.join(full_label.split())
                
                # Final validation: ensure it's not just furniture
                # Skip if it's a date pattern (version history)
                if re.match(r'^\d{1,2}-[A-Za-z]{3}-\d{4}', full_label):
                    i = j
                    continue
                
                # Skip if it contains names that look like version history
                if re.search(r'(Hardut|Giucal|Rubei|Manolescu)', full_label):
                    i = j
                    continue
                
                # Skip very long text that looks like citations
                if len(full_label) > 150 and any(indicator in full_label.lower() for indicator in 
                       ['developed by', 'ph.d.', 'm.d.', 'psychiatric', 'reprints', 'contact']):
                    i = j
                    continue
                
                # Emit the record
                if full_label and len(full_label) > 2 and current_form:
                    records.append({
                        "form_name": current_form,
                        "field_name": full_label,
                        "page": page_num
                    })
                
                i = j
            else:
                i += 1
    
    return records
```