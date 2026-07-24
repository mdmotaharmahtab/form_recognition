import re
from collections import namedtuple

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Look for form title - large blue text, typically 14+ point size
        for i, line in enumerate(lines):
            # Form titles are in blue (#004c99 or similar blue), size ~14pt, not bold
            if line.size >= 13.0 and line.non_black and not line.bold:
                # Check if this looks like a form title (not a technical code in brackets)
                text = line.text.strip()
                if text and not text.startswith('[') and not re.match(r'^\d+$', text):
                    # Avoid header/footer page numbers and other metadata
                    if not re.match(r'^(Pack Version|Annotated CRF|\d+\.?\d*|page \d+)', text, re.IGNORECASE):
                        current_form = text
                        break
        
        # Extract field labels - these are black text questions/labels
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip empty lines
            if not text:
                i += 1
                continue
            
            # Skip red technical codes by structure: non-black + contains brackets
            if line.non_black and '[' in text:
                i += 1
                continue
            
            # Skip lines that are just bracketed codes (any color)
            if re.match(r'^\[.*\]$', text):
                i += 1
                continue
            
            # Skip TYPE/VISIBILITY markers by structure: starts with [TYPE: or [VISIBILITY:
            if text.startswith('[TYPE:') or text.startswith('[VISIBILITY:') or '[Read-only field]' in text:
                i += 1
                continue
            
            # Skip answer options by structure: small text (8.5-10pt), very short, often centered/indented
            # Answer options are typically 1-3 words, positioned differently than field labels
            if line.size >= 8.5 and line.size <= 10.0 and len(text.split()) <= 3:
                # Check if it looks like an answer option by position
                # Answer options often appear indented or in a different column
                # Skip if it's very short and not a question
                if not text.endswith('?') and not text.endswith(':'):
                    # Look ahead to see if next line is a field label or code
                    # If this is between field labels, it's likely an option
                    is_option = False
                    if i > 0 and i + 1 < len(lines):
                        prev_line = lines[i - 1]
                        next_line = lines[i + 1]
                        # If surrounded by field-like structures, likely an option
                        if (prev_line.size >= 7.0 or next_line.size >= 7.0) and len(text) < 20:
                            is_option = True
                    
                    if is_option:
                        i += 1
                        continue
            
            # Skip enumeration values by structure: starts with (digit)
            if re.match(r'^\(\d+\)', text):
                i += 1
                continue
            
            # Skip row markers by structure: "Row" + number pattern
            if re.match(r'^Row \d+$', text, re.IGNORECASE):
                i += 1
                continue
            
            # Skip repeatable row headers by structure: contains "(Repeatable row"
            if '(Repeatable row' in text:
                i += 1
                continue
            
            # Skip conditional logic by structure: starts with YES/NO + "page enrols"
            if re.match(r'^(YES|NO)\s+page enrols', text, re.IGNORECASE):
                i += 1
                continue
            
            # Skip subsection markers by structure: blue + bold + small size (8.5-10pt)
            # These are structural dividers, not field labels
            if line.non_black and line.bold and line.size >= 8.5 and line.size <= 10.5:
                i += 1
                continue
            
            # Look for field labels - black text, reasonable size (7-10pt)
            # Field labels are typically questions or prompts
            if not line.non_black and line.size >= 6.5 and line.size <= 11.0:
                # Check if this could be a field label
                # Field labels are followed by red codes OR are questions OR contain field keywords
                
                # Look ahead for red technical code
                has_code = False
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if next_line.non_black and '[' in next_line.text:
                        has_code = True
                
                # Check if it's a question
                is_question = text.endswith('?')
                
                # Check for field-like patterns (structural clues)
                # Fields often contain certain patterns that distinguish them from junk
                has_field_pattern = (
                    ':' in text or  # "Date:", "Time:", etc.
                    '?' in text or  # Questions
                    re.search(r'\b(Date|Time|Number|Bottle|Total|Blood Pressure|Heart Rate|Temperature|ICF)\b', text, re.IGNORECASE) or
                    re.search(r'\b(Were|Was|Has|Have|Did|If|Specify|Describe)\b', text) or
                    text.endswith(':') or
                    len(text) > 15  # Longer text more likely to be a real field
                )
                
                # Also detect by position: field labels are often left-aligned at consistent x position
                # If it's at a typical field label x position (not indented far right)
                at_field_position = line.x0 < 500  # Reasonable left-side position
                
                if (has_code or is_question or has_field_pattern) and at_field_position:
                    field_name = text
                    
                    # Collect multi-line field labels
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        next_text = next_line.text.strip()
                        
                        # Stop if we hit a red code
                        if next_line.non_black and '[' in next_text:
                            break
                        
                        # Stop if we hit answer options (structural check)
                        if (next_line.size >= 8.5 and next_line.size <= 10.0 and 
                            len(next_text.split()) <= 3 and 
                            not next_text.endswith('?')):
                            break
                        
                        # Check if continuation line: similar x position, close proximity, black, reasonable size
                        if (not next_line.non_black and
                            abs(next_line.x0 - line.x0) < 30 and 
                            next_line.y0 - lines[j-1].y0 < 40 and
                            next_line.size >= 6.5 and next_line.size <= 11.0 and
                            not next_text.startswith('[') and
                            not re.match(r'^Row \d+$', next_text, re.IGNORECASE) and
                            next_text):
                            field_name += ' ' + next_text
                            j += 1
                        else:
                            break
                    
                    # Clean up the field name
                    field_name = ' '.join(field_name.split())
                    
                    # Skip if too short (likely junk) or no form context
                    if len(field_name) > 2 and current_form:
                        results.append({
                            "form_name": current_form,
                            "field_name": field_name,
                            "page": page_num
                        })
                    
                    i = j
                    continue
            
            i += 1
    
    return results
