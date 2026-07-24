```python
import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    seen = set()  # Track (form, field) to avoid duplicates within same context
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Try to identify form name from headers
        # Form names appear as bold text at y~48.5 or as larger text at y~73.9
        form_candidates = []
        for line in lines:
            # Bold header around y=48-49
            if line.bold and 48 <= line.y0 <= 50 and line.size >= 7:
                text = line.text.strip()
                if text and not re.match(r'^\[?\d+\]?$', text) and 'Variable details' not in text:
                    form_candidates.append(text)
            # Larger form title around y=73-74
            elif 73 <= line.y0 <= 75 and line.size >= 15:
                text = line.text.strip()
                if text and text not in ['Visit:', 'Screening']:
                    form_candidates.append(text)
        
        if form_candidates:
            # Use the last/most specific form name found
            current_form = form_candidates[-1]
            seen.clear()  # Reset seen fields for new form
        
        # Check if this is a "Variable details" metadata page
        is_variable_page = any('Variable details' in line.text for line in lines)
        
        # Also detect tabular variable detail pages by structure:
        # - Bracketed numbers in column 1 (x~41)
        # - Field labels in column 2 (x~80)
        # - Export names in column 3 (x~235)
        # - Type info in column 4 (x~390)
        has_bracket_column = any(75 <= line.x0 <= 85 and re.match(r'^\[\d+\]$', line.text.strip()) for line in lines)
        has_export_column = any(230 <= line.x0 <= 240 and re.match(r'^[A-Z]{3,}\d+[A-Z]?$', line.text.strip()) for line in lines)
        has_type_column = any(385 <= line.x0 <= 395 and ('Categorical' in line.text or 'Number' in line.text or 'Date' in line.text or 'Text' in line.text) for line in lines)
        
        is_tabular_variable_page = has_bracket_column and has_export_column and has_type_column
        
        # Detect checklist-style pages (like page 434)
        # These have checkboxes and "Not Done" options, with structured layout
        has_not_done = any('Not Done' in line.text for line in lines)
        has_checkboxes = any(re.search(r'☐|□', line.text) for line in lines)
        is_checklist_page = has_not_done or has_checkboxes
        
        # Detect lab result pages (like page 470)
        # These have "Interpretation" columns and specific lab terms
        has_interpretation = any('Interpretation' in line.text for line in lines)
        has_lab_terms = any(text in line.text for line in lines for text in ['Specimen', 'Glucose', 'Protein', 'pH', 'Colour'])
        is_lab_page = has_interpretation and has_lab_terms
        
        if is_variable_page:
            # Extract from "Name" column (x~80.7) - bold text
            for line in lines:
                if 75 <= line.x0 <= 85 and line.y0 > 70:
                    text = line.text.strip()
                    # Skip headers and bracketed numbers
                    if text and text != 'Name' and not re.match(r'^\[?\d+\]?$', text):
                        # Check it's not a technical export name (all caps with no spaces typically)
                        if not (text.isupper() and len(text) > 3 and ' ' not in text):
                            key = (current_form, text)
                            if key not in seen:
                                results.append({
                                    "form_name": current_form,
                                    "field_name": text,
                                    "page": page_num
                                })
                                seen.add(key)
        elif is_tabular_variable_page:
            # Extract from column 2 (x~80.7) - field labels (may not be bold)
            # These are the actual question texts
            for line in lines:
                if 75 <= line.x0 <= 85 and line.y0 > 40:
                    text = line.text.strip()
                    # Skip if empty or just a bracket
                    if not text or re.match(r'^\[?\d+\]?$', text):
                        continue
                    # Skip if it's a technical code
                    if re.match(r'^[A-Z]{3,}\d+[A-Z]?$', text):
                        continue
                    # Skip common non-field text
                    if text in ['Name', 'Export Name', 'Type', 'Max length', 'Categories']:
                        continue
                    # Skip single-word option values
                    if text in ['Yes', 'No', 'Negative', 'Trace', 'Small', 'Moderate', 'Large']:
                        continue
                    
                    key = (current_form, text)
                    if key not in seen:
                        results.append({
                            "form_name": current_form,
                            "field_name": text,
                            "page": page_num
                        })
                        seen.add(key)
        elif is_lab_page:
            # Lab result pages: extract field names more comprehensively
            # Look for all text that represents field labels
            for line in lines:
                if line.y0 < 70:  # Skip headers
                    continue
                
                text = line.text.strip()
                if not text:
                    continue
                
                # Skip bracketed numbers
                if re.match(r'^\[?\d+\]?$', text):
                    continue
                
                # Look for field patterns
                is_field = False
                
                # Check if it's a main field label (contains key lab terms)
                if any(term in text for term in ['Specimen Appearance', 'Glucose', 'pH', 'Protein', 'Colour', 
                                                   'Ketones', 'Blood', 'Bilirubin', 'Urobilinogen', 'Nitrite', 
                                                   'Leukocyte', 'Specific Gravity']):
                    is_field = True
                
                # Check if it ends with "Interpretation" or "Specify"
                if text.endswith('Interpretation') or text.endswith('Specify') or ', Specify' in text:
                    is_field = True
                
                # Check for "Sent for" pattern
                if 'Sent for' in text:
                    is_field = True
                
                # Check for "Other Specify" pattern
                if 'Other Specify' in text or 'Other, Specify' in text:
                    is_field = True
                
                # Skip if it's just a value or option
                if text in ['Yes', 'No', 'Normal', 'Abnormal', 'Not Done', 'Negative', 'Trace', 'Small', 
                           'Moderate', 'Large', 'Positive', 'Clear', 'Cloudy', 'Yellow', 'Amber', 'Red', 
                           'Brown', 'Orange']:
                    is_field = False
                
                # Skip numeric values or ranges
                if re.match(r'^[\d\.\-≤≥<>]+$', text):
                    is_field = False
                
                # Skip partial phrases that are not complete field names
                if text in ['Other', 'Other,']:
                    is_field = False
                
                if is_field:
                    key = (current_form, text)
                    if key not in seen:
                        results.append({
                            "form_name": current_form,
                            "field_name": text,
                            "page": page_num
                        })
                        seen.add(key)
        elif is_checklist_page:
            # Checklist pages: extract field labels more comprehensively
            # Build a map of y-coordinates to lines for context analysis
            lines_by_y = defaultdict(list)
            for line in lines:
                if line.y0 >= 70:  # Skip headers
                    lines_by_y[round(line.y0, 1)].append(line)
            
            # Collect all text with brackets (potential field labels)
            bracketed_texts = []
            for line in lines:
                if line.y0 >= 70 and '[' in line.text and ']' in line.text:
                    text = line.text.strip()
                    clean_text = re.sub(r'\s*\[\d+\]\s*', ' ', text).strip()
                    if clean_text:
                        bracketed_texts.append((line.y0, line.x0, text, clean_text, line.bold))
            
            # Extract field names
            for line in lines:
                if line.y0 < 70:  # Skip headers
                    continue
                
                text = line.text.strip()
                
                # Skip if empty
                if not text:
                    continue
                
                # Remove bracketed numbers for analysis
                clean_text = re.sub(r'\s*\[\d+\]\s*', ' ', text).strip()
                if not clean_text:
                    continue
                
                # Identify field labels by patterns
                is_field = False
                
                # Pattern 1: Single-word fields that are known to be fields
                if clean_text in ['Eye', 'Repeat']:
                    is_field = True
                
                # Pattern 2: "Not Done" as a field
                if clean_text == 'Not Done':
                    is_field = True
                
                # Pattern 3: Text ending with Date, Time, or Specify
                if clean_text.endswith('Date') or clean_text.endswith('Time') or clean_text.endswith('Specify'):
                    is_field = True
                
                # Pattern 4: Specific known field patterns for pupillometry
                if any(keyword in clean_text for keyword in ['Pupillometry Date', 'Position Rest Time', 
                                                              'Pupillometry Start Time', 'Rest Time', 'Start Time']):
                    is_field = True
                
                # Pattern 5: "Reviewed, signed and dated" pattern (full phrase)
                if 'Reviewed' in clean_text and 'signed' in clean_text and 'dated' in clean_text:
                    # Only if it's the full phrase
                    if 'physician' in clean_text or len(clean_text.split()) >= 5:
                        is_field = True
                
                # Pattern 6: "Reason not" pattern (but not fragments)
                if clean_text.startswith('Reason not') or clean_text.startswith('Reason Not'):
                    # Only if it's a complete phrase
                    if len(clean_text.split()) >= 3:
                        is_field = True
                
                # Pattern 7: Long descriptive text (likely instructions or field labels)
                if len(clean_text.split()) >= 6:
                    # Check if it looks like an instruction or field label
                    if any(keyword in clean_text for keyword in ['downloaded', 'spreadsheet', 'Bluetooth', 'device']):
                        is_field = True
                
                # Pattern 8: Bold text with brackets (likely field labels)
                if line.bold and '[' in text and ']' in text:
                    # Check if it's substantial
                    if len(clean_text.split()) >= 1:
                        is_field = True
                
                # Skip common non-field words (but not if they match patterns above)
                if not is_field and clean_text in ['Not', 'Done', 'Performed', 'Yes', 'No', 'Position', 'Readings', 
                                 'Reviewed', 'Reason', 'Left', 'Right']:
                    is_field = False
                
                # Skip fragments that are clearly not complete fields
                skip_fragments = ['and dated by a', 'and dated', 'Reason not review, signed', 'Date', 'Time']
                if clean_text in skip_fragments:
                    is_field = False
                
                # Skip very short fragments unless they're known fields
                if len(clean_text.split()) == 1 and len(clean_text) < 4:
                    if clean_text not in ['Eye', 'Repeat']:
                        is_field = False
                
                if is_field:
                    key = (current_form, clean_text)
                    if key not in seen:
                        results.append({
                            "form_name": current_form,
                            "field_name": clean_text,
                            "page": page_num
                        })
                        seen.add(key)
        else:
            # Standard form pages: extract bold text as field labels
            for line in lines:
                if line.bold and line.y0 >= 70:
                    text = line.text.strip()
                    
                    # Skip if empty
                    if not text:
                        continue
                    
                    # Skip bracketed numbers alone
                    if re.match(r'^\[?\d+\]?$', text):
                        continue
                    
                    # Remove bracketed numbers for the field name
                    clean_text = re.sub(r'\s*\[\d+\]\s*', ' ', text).strip()
                    if not clean_text:
                        continue
                    
                    # Skip common non-field text
                    if clean_text in ['Yes', 'No', 'Unknown', 'Not Done', 'Other']:
                        continue
                    
                    # Skip page numbers and headers
                    if re.match(r'^Page \d+', clean_text):
                        continue
                    
                    key = (current_form, clean_text)
                    if key not in seen:
                        results.append({
                            "form_name": current_form,
                            "field_name": clean_text,
                            "page": page_num
                        })
                        seen.add(key)
    
    return results
```