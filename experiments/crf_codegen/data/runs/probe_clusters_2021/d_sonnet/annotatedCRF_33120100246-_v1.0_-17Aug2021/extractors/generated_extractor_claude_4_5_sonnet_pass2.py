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
            # BUT allow "Investigator comment" pattern and "If Yes," patterns
            # AND allow escaped numbered criteria
            if len(text) < 15 and (line.bold or line.x0 > 400):
                # Check if this is an "Investigator comment" or similar field
                if not ('comment' in text.lower() or text.startswith('If Yes,') or re.match(r'^\\[0-9]+\\.\\', text)):
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
            # UNLESS it's a numbered inclusion/exclusion criterion (starts with \N.\)
            # OR starts with "If Yes," (which is a field prefix)
            instruction_starts = ['If ', 'When ', 'Once ', 'Has there been', 'Person has', 'Person is']
            is_instruction = any(text.startswith(prefix) for prefix in instruction_starts)
            
            # Exception: "If Yes," is a field label prefix, not an instruction
            # BUT filter "If Yes, describe" as it's an answer prompt
            if text.startswith('If Yes,'):
                if text == 'If Yes, describe' or text.startswith('If Yes, describe '):
                    i += 1
                    continue
                is_instruction = False
            # Exception: numbered criteria starting with \N.\ are fields, not instructions
            elif re.match(r'^\\[0-9]+\\.\\', text):
                is_instruction = False
            
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
            
            # 2b. Label with colon on RIGHT side (lab assay fields like "Chemistry clinically significant abnormal assay # 1:")
            # These appear around x=330-380
            elif text.endswith(':') and 300 < line.x0 < 400 and 20 < len(text) < 100 and line.size >= 7.5:
                # Look for keywords suggesting it's a lab field
                if any(kw in text.lower() for kw in ['abnormal', 'assay', 'chemistry', 'hematology']):
                    is_field_label = True
            
            # 3. Numbered items like "1." or "a." (potential checklist/criteria)
            elif re.match(r'^[0-9a-z]\.\s+.{10,}', text) and line.x0 < 300 and line.size >= 7.5:
                is_field_label = True
            
            # 3b. Escaped numbered items like "\1.\" or "\23.\" (inclusion/exclusion criteria)
            # These can appear anywhere horizontally, not just left side
            elif re.match(r'^\\[0-9]+\\.\\', text) and line.size >= 7.5:
                is_field_label = True
            
            # 4. Bold labels on left side (table row headers, criteria labels)
            elif line.bold and line.x0 < 280 and 15 < len(text) < 100 and line.size >= 8.0:
                # But not column headers (near top of page)
                if line.y0 > 100:
                    is_field_label = True
            
            # 5. Lab assay dropdown options: right-positioned (x>330), medium size (8-10), short text
            # These appear as vertical lists of test names
            elif 330 < line.x0 < 380 and 8.0 <= line.size <= 10.0 and 10 < len(text) < 80 and line.y0 > 80:
                # Look for preceding section header (descriptive text on left, similar y-coordinate)
                found_header = False
                for prev_line in reversed(sorted_lines[:i]):
                    if abs(prev_line.y0 - line.y0) > 30:
                        break
                    if prev_line.x0 < 200 and prev_line.y0 < line.y0 and len(prev_line.text.strip()) > 15:
                        # Check if it looks like a section header (contains "abnormal", "assay", etc.)
                        header_text = prev_line.text.strip().lower()
                        if any(kw in header_text for kw in ['abnormal', 'assay', 'clinically', 'significant']):
                            found_header = True
                            break
                
                if found_header:
                    is_field_label = True
            
            # 6. "Investigator comment" pattern: left side, contains "comment"
            elif 'comment' in text.lower() and line.x0 < 150 and line.size >= 7.5:
                is_field_label = True
            
            # 7. "If Yes," prefix fields: left side, starts with "If Yes,"
            # BUT not "If Yes, describe" (already filtered above)
            elif text.startswith('If Yes,') and line.x0 < 150 and line.size >= 7.5:
                is_field_label = True
            
            # 8. "Result of Repeat Test" pattern (cluster 2 pages)
            # Left side, contains "Result"
            elif 'Result' in text and line.x0 < 150 and line.size >= 7.5 and len(text) > 10:
                is_field_label = True
            
            if not is_field_label:
                i += 1
                continue
            
            # Build multi-line field label if needed
            field_parts = [text]
            j = i + 1
            
            # Look for continuation lines
            # Special handling for long inclusion/exclusion criteria
            is_long_criterion = re.match(r'^\\[0-9]+\\.\\', text)
            
            while j < len(sorted_lines):
                next_line = sorted_lines[j]
                next_text = next_line.text.strip()
                
                # Stop conditions (structural)
                y_diff = next_line.y0 - line.y0
                
                # For long criteria, allow more vertical space
                max_y_diff = 150 if is_long_criterion else 25
                
                if y_diff > max_y_diff:  # Too far down
                    break
                if next_line.x0 > 350 and line.x0 < 300:  # Moved to answer column (but not for right-side fields)
                    break
                if next_line.size >= 13.0 and next_line.non_black:  # New form title
                    break
                if next_line.non_black and next_text.startswith('['):  # Machine code
                    break
                
                # For regular fields, stop at options
                if not is_long_criterion and (next_text.startswith('(') or len(next_text) < 3):
                    break
                
                # Check if this is a continuation (similar x position, close y, similar size)
                x_diff = abs(next_line.x0 - line.x0)
                size_diff = abs(next_line.size - line.size)
                
                # For long criteria, be more lenient with x position
                max_x_diff = 50 if is_long_criterion else 30
                
                if x_diff < max_x_diff and size_diff < 1.5 and len(next_text) > 3:
                    # Check it's not a new field label
                    if not (next_text.endswith('?') or next_text.endswith(':') or 
                            re.match(r'^[0-9a-z]\.\s+', next_text) or
                            re.match(r'^\\[0-9]+\\.\\', next_text) or
                            'comment' in next_text.lower()):
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
            field_label = re.sub(r'^\\[0-9]+\\.\\s*', '', field_label)  # Remove leading "\1.\ "
            
            # Final quality checks (structural)
            # Too short (likely fragment) - but allow "Investigator comment" pattern
            if len(field_label) < 8:
                if not ('comment' in field_label.lower() or field_label.startswith('If Yes,') or 'Result' in field_label):
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
            # BUT allow "and" at the start
            if field_label and field_label[0].islower() and not field_label.startswith('and'):
                i = j
                continue
            
            # Filter "If Yes, describe" prompts
            if field_label == 'If Yes, describe' or field_label.startswith('If Yes, describe '):
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
