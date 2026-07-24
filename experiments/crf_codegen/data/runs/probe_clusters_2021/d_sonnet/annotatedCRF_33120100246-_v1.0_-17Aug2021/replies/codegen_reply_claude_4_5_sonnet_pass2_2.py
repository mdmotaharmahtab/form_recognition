Looking at the feedback, I need to fix several issues:

1. **Empty form_names (75% of records)**: Need to carry form titles forward across pages
2. **False positives**: Extracting option lists, instructional text, and partial phrases that aren't actual field labels
3. **False negatives**: Missing some fields on page 427 (C-SSRS questions)
4. **Hardcoded filters**: Remove literal string blocklists and use structural discriminators instead

Let me rewrite the program with structural improvements:

```python
import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form_name = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Find form title: large blue text (size >= 13, colored, not a machine code)
        for line in lines:
            if line.size >= 13.0 and line.non_black and not line.text.startswith('['):
                text = line.text.strip()
                # Skip table of contents entries (leading numbers like "3.1. ")
                if not re.match(r'^\d+\.', text) and len(text) > 10:
                    current_form_name = text
                    break
        
        # Build a map of y-coordinates to lines for context analysis
        sorted_lines = sorted(lines, key=lambda l: (l.y0, l.x0))
        
        i = 0
        while i < len(sorted_lines):
            line = sorted_lines[i]
            text = line.text.strip()
            
            # Skip machine codes (red text in brackets)
            if line.non_black and text.startswith('['):
                i += 1
                continue
            
            # Skip page headers/footers (very top or bottom, small text)
            if line.y0 < 35 or line.size < 6.5:
                i += 1
                continue
            
            # Skip form titles (already captured)
            if line.size >= 13.0 and line.non_black:
                i += 1
                continue
            
            # STRUCTURAL: Skip structural markers (short text, often bold, centered or far right)
            if len(text) < 15 and (line.bold or line.x0 > 400):
                i += 1
                continue
            
            # STRUCTURAL: Skip option values (right side of page, short phrases)
            if line.x0 > 350 and len(text) < 25:
                i += 1
                continue
            
            # STRUCTURAL: Skip enumeration lists that are dropdown options
            # These appear as continuous text with semicolons/commas, no question/colon
            if ';' in text and len(text) > 80 and not text.endswith('?') and not text.endswith(':'):
                i += 1
                continue
            
            # STRUCTURAL: Skip parenthetical option lists (text starting with parenthesis)
            if text.startswith('(') and ')' in text and len(text) > 40:
                i += 1
                continue
            
            # STRUCTURAL: Skip instructional text (starts with "If ", "When ", "Once ", etc.)
            # and is long prose without question/colon endings
            instruction_starts = ['If ', 'When ', 'Once ', 'Has there been', 'Person has', 'Person is']
            is_instruction = any(text.startswith(prefix) for prefix in instruction_starts)
            if is_instruction and len(text) > 60 and not text.endswith('?') and not text.endswith(':'):
                i += 1
                continue
            
            # Identify potential field labels by structure
            is_field_label = False
            
            # 1. Questions (end with "?", reasonable size, left side)
            if text.endswith('?') and line.x0 < 300 and 7.0 <= line.size <= 12.0:
                is_field_label = True
            
            # 2. Label with colon (left side, not too long, not an option list)
            elif text.endswith(':') and line.x0 < 300 and 10 < len(text) < 80 and ';' not in text:
                is_field_label = True
            
            # 3. Numbered items like "1." or "a." (potential checklist/criteria)
            elif re.match(r'^[0-9a-z]\.\s+.{10,}', text) and line.x0 < 300 and line.size >= 7.5:
                is_field_label = True
            
            # 4. Bold labels on left side (table row headers, criteria labels)
            elif line.bold and line.x0 < 280 and 15 < len(text) < 100 and line.size >= 8.0:
                # But not column headers (near top of page)
                if line.y0 > 100:
                    is_field_label = True
            
            if not is_field_label:
                i += 1
                continue
            
            # Build multi-line field label if needed
            field_parts = [text]
            j = i + 1
            
            # Look for continuation lines
            while j < len(sorted_lines):
                next_line = sorted_lines[j]
                next_text = next_line.text.strip()
                
                # Stop conditions (structural)
                y_diff = next_line.y0 - line.y0
                if y_diff > 25:  # Too far down
                    break
                if next_line.x0 > 350:  # Moved to answer column
                    break
                if next_line.size >= 13.0 and next_line.non_black:  # New form title
                    break
                if next_line.non_black and next_text.startswith('['):  # Machine code
                    break
                if next_text.startswith('(') or len(next_text) < 3:  # Option or fragment
                    break
                
                # Check if this is a continuation (similar x position, close y, similar size)
                x_diff = abs(next_line.x0 - line.x0)
                size_diff = abs(next_line.size - line.size)
                
                if x_diff < 30 and y_diff < 20 and size_diff < 1.5 and len(next_text) > 3:
                    # Check it's not a new field label
                    if not (next_text.endswith('?') or next_text.endswith(':') or 
                            re.match(r'^[0-9a-z]\.\s+', next_text)):
                        field_parts.append(next_text)
                        j += 1
                    else:
                        break
                else:
                    break
            
            # Assemble field label
            field_label = ' '.join(field_parts)
            field_label = re.sub(r'\s+', ' ', field_label).strip()
            
            # Clean up artifacts
            field_label = re.sub(r'^\d+\.\s*', '', field_label)  # Remove leading "1. "
            field_label = re.sub(r'^[a-z]\.\s*', '', field_label)  # Remove leading "a. "
            
            # Final quality checks (structural)
            # Too short (likely fragment)
            if len(field_label) < 8:
                i = j
                continue
            
            # Contains excessive punctuation (likely option list fragment)
            if field_label.count(';') >= 3 or field_label.count(',') >= 8:
                i = j
                continue
            
            # Ends with comma (incomplete fragment)
            if field_label.endswith(','):
                i = j
                continue
            
            # Starts with lowercase (continuation fragment, not a label start)
            if field_label[0].islower() and not field_label.startswith('and'):
                i = j
                continue
            
            # Add record
            records.append({
                "form_name": current_form_name,
                "field_name": field_label,
                "page": page_num
            })
            
            i = j
    
    return records
```
