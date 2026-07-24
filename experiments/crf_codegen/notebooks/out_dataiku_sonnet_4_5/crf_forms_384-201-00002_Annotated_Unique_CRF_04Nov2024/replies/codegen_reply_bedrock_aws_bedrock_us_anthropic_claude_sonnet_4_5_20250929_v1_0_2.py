```python
import re

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Check if this is a data dictionary page (has "Field Name Data Type" header)
        is_data_dict = any(
            "Field Name Data Type" in line.text or 
            ("Field Name" in line.text and "Data Type" in line.text and line.y0 < 200)
            for line in lines
        )
        
        if is_data_dict:
            continue
        
        # Extract form name from "Form: " line
        for line in lines:
            if line.text.startswith("Form: ") and line.bold and line.y0 < 150:
                current_form = line.text[6:].strip()
                break
        
        # Extract field questions
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty lines, headers, footers, page numbers
            if not text:
                continue
            if line.y0 < 140:  # Skip header area
                continue
            if line.y0 > 680:  # Skip footer area
                continue
            
            # Skip lines that are just numeric codes (right side, near x=527)
            if line.x0 > 500 and re.match(r'^\d+$', text):
                continue
            
            # Skip answer options (right side or indented, common patterns)
            if line.x0 > 400:
                # These are typically answer choices or codes
                if re.match(r'^\d+=', text):  # "1=Absent", "2=Minimal"
                    continue
                if text in ['Yes', 'No']:
                    continue
                if re.match(r'^\d+\s*$', text):  # Just numbers
                    continue
                # Skip common answer patterns
                if any(pattern in text for pattern in ['=Absent', '=Minimal', '=Mild', '=Moderate', '=Severe', '=Extreme']):
                    continue
            
            # Skip signature prompts and instructions
            if 'password' in text.lower() or 'signature' in text.lower():
                continue
            if text.startswith('Signature Prompt:'):
                continue
            
            # Skip table headers
            if text in ['Units', 'Values', 'Pre-Filled', 'Include', 'Field OID', 'Category']:
                continue
            
            # Skip technical field codes (e.g., "LBCAT", "LBPERF", "$25")
            if re.match(r'^[A-Z_]+$', text) and len(text) < 20:
                continue
            if re.match(r'^\$\d+$', text):
                continue
            if re.match(r'^dd MMM$', text) or text == 'yyyy':
                continue
            
            # Skip lines that look like data values or codes
            if re.match(r'^[A-Z\s]+=', text):  # "CHEMISTRY =", "Y = Yes"
                continue
            if text.startswith('Fixed Unit:'):
                continue
            
            # Skip regulatory text (page 1)
            if 'Pursuant to Section' in text or 'Code of Federal Regulations' in text:
                continue
            if text.startswith('Log.'):
                continue
            
            # Skip instruction text that's not a field
            if text == 'Check all that apply':
                continue
            
            # Skip form/section titles that look like field names but aren't
            if text in ['Holter Continuous Ecg', 'Holter Continuous ECG']:
                # Check if this is actually a section header (bold, larger, etc.)
                if line.bold or line.fontsize > 11:
                    continue
            
            # Skip rating scale descriptions (detailed scoring text)
            # These are typically longer descriptive text with semicolons and detailed criteria
            if ';' in text and len(text) > 50:
                # Check if it looks like scoring criteria
                if re.search(r'\d+=.*\d+=', text):  # Multiple "N=" patterns
                    continue
                if any(word in text.lower() for word in ['diminution', 'resistance', 'absence', 'slowing', 'noted by']):
                    continue
            
            # Skip lines that are clearly rating descriptions (start with number=description)
            if re.match(r'^\d+=.{20,}', text):  # Long descriptions starting with "1=..."
                continue
            
            # Skip multi-part rating descriptions
            if text.startswith('1=') or text.startswith('2=') or text.startswith('3=') or text.startswith('4='):
                if any(word in text.lower() for word in ['slight', 'moderate', 'marked', 'complete', 'severe', 'mild']):
                    continue
            
            # Skip continuation lines of rating descriptions
            if line.x0 > 100 and line.x0 < 400:
                # Check if previous line was a rating description
                if i > 0:
                    prev_text = lines[i-1].text.strip()
                    if re.match(r'^\d+=', prev_text) and len(prev_text) > 20:
                        continue
            
            # Skip lines that are fragments of rating scales
            if len(text) > 30 and not text.endswith('?'):
                # Check for rating scale language patterns
                if any(phrase in text.lower() for phrase in [
                    'completely with', 'thump as it hits', 'mainly noted by', 
                    'lack of', 'good deal', 'falls freely'
                ]):
                    continue
            
            # Field questions are left-aligned (x < 400) and are descriptive text
            if line.x0 >= 90 and line.x0 < 400:
                # Must contain letters and be reasonably long
                if not re.search(r'[a-zA-Z]', text):
                    continue
                if len(text) < 5:
                    continue
                
                # Skip if it's just a continuation of values/codes
                if text.startswith('=') or text.endswith('='):
                    continue
                
                # Skip common non-field patterns
                if text in ['PANSS']:
                    continue
                if re.match(r'^\d+\s*$', text):
                    continue
                
                # Skip lines that are part of multi-line instructions
                if i > 0 and lines[i-1].x0 > 80 and lines[i-1].x0 < 100:
                    prev_text = lines[i-1].text.strip()
                    if 'Manual' in prev_text or 'Published' in prev_text:
                        continue
                
                # This looks like a field question
                results.append({
                    "form_name": current_form,
                    "field_name": text,
                    "page": page_num
                })
    
    return results
```