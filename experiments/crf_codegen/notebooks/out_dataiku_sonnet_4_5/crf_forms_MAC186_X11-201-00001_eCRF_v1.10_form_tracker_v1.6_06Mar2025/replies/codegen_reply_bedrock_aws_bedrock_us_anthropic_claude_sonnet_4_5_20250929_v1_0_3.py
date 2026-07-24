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
            # Lab result pages: extract field names that end with specific patterns
            # Look for bold text that represents field labels
            for line in lines:
                if line.y0 < 70:  # Skip headers
                    continue
                
                text = line.text.strip()
                if not text:
                    continue
                
                # Skip bracketed numbers
                if re.match(r'^\[?\d+\]?$', text):
                    continue
                
                # Look for field patterns: words ending with specific suffixes or containing key terms
                # Field names on lab pages often include: "Specimen", "Glucose", "pH", "Protein", "Colour", etc.
                is_field = False
                
                # Check if it's a main field label (contains key lab terms)
                if any(term in text for term in ['Specimen Appearance', 'Glucose', 'pH', 'Protein', 'Colour', 'Ketones', 'Blood', 'Bilirubin', 'Urobilinogen', 'Nitrite', 'Leukocyte']):
                    is_field = True
                
                # Check if it ends with "Interpretation" or "Specify"
                if text.endswith('Interpretation') or text.endswith('Specify'):
                    is_field = True
                
                # Skip if it's just a value or option
                if text in ['Yes', 'No', 'Normal', 'Abnormal', 'Not Done', 'Negative', 'Trace', 'Small', 'Moderate', 'Large', 'Positive']:
                    is_field = False
                
                # Skip numeric values or ranges
                if re.match(r'^[\d\.\-≤≥<>]+$', text):
                    is_field = False
                
                # Skip single-word values that are likely options
                if text in ['Clear', 'Cloudy', 'Yellow', 'Amber', 'Red', 'Brown', 'Orange']:
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
            # Checklist pages: only extract main section headers or clear field labels
            # Skip individual checklist items that are just options
            for line in lines:
                if not line.bold or line.y0 < 70:  # Skip headers
                    continue
                
                text = line.text.strip()
                
                # Skip if empty or just a bracket
                if not text or re.match(r'^[\[\]\d\s]+$', text):
                    continue
                
                # Remove bracketed numbers
                clean_text = re.sub(r'\s*\[\d+\]\s*', ' ', text).strip()
                if not clean_text:
                    continue
                
                # Skip common checklist options
                if clean_text in ['Not', 'Done', 'Not Done', 'Performed', 'Yes', 'No', 'Position', 'Readings', 'Reviewed', 'Reason']:
                    continue
                
                # Skip short single-word items that are likely options
                if len(clean_text.split()) == 1 and len(clean_text) < 15:
                    continue
                
                # Skip items that look like procedural notes rather than field labels
                if clean_text in ['Pupillometry', 'PLR', 'PLR MAX', 'Occult Blood']:
                    continue
                
                # Only keep if it's a substantial field label (multi-word or ends with specific patterns)
                if len(clean_text.split()) >= 3 or clean_text.endswith('Specify') or clean_text.endswith('Date') or clean_text.endswith('Time'):
                    key = (current_form, clean_text)
                    if key not in seen:
                        results.append({
                            "form_name": current_form,
                            "field_name": clean_text,
                            "page": page_num
                        })
                        seen.add(key)
        else:
            # Standard form page - extract bold field labels with bracketed markers
            # Build a map of y-positions to bracketed numbers
            bracket_positions = {}
            for line in lines:
                match = re.search(r'\[(\d+)\]', line.text)
                if match:
                    bracket_positions[line.y0] = True
            
            # Extract field labels
            for line in lines:
                if not line.bold or line.y0 < 70:  # Skip headers
                    continue
                
                text = line.text.strip()
                
                # Skip if empty, just a bracket, or common non-field text
                if not text:
                    continue
                if re.match(r'^[\[\]\d\s]+$', text):
                    continue
                if text in ['Yes', 'No', 'Name', 'Export Name', 'Type', 'Max length', 'Categories']:
                    continue
                
                # Remove bracketed numbers from the text
                clean_text = re.sub(r'\s*\[\d+\]\s*', ' ', text).strip()
                if not clean_text:
                    continue
                
                # Skip if it looks like a technical code (short all-caps with numbers)
                if re.match(r'^[A-Z]{3,}\d+[A-Z]?$', clean_text):
                    continue
                
                # Skip option values (single words that are likely choices)
                if clean_text in ['Negative', 'Trace', 'Small', 'Moderate', 'Large', 
                                   'Left', 'Right', 'Performed']:
                    continue
                
                # Check if there's a bracket nearby (within 5 points vertically)
                has_nearby_bracket = False
                for bracket_y in bracket_positions:
                    if abs(line.y0 - bracket_y) <= 5:
                        has_nearby_bracket = True
                        break
                
                # Also check if the line itself contains a bracket
                if '[' in text and ']' in text:
                    has_nearby_bracket = True
                
                # For standard forms, we want bold labels that have bracket markers
                # or are clearly field labels (longer descriptive text)
                if has_nearby_bracket or len(clean_text.split()) >= 2:
                    # Additional filters
                    if clean_text.lower() in ['yes', 'no']:
                        continue
                    
                    # Skip if it's just a number or date-like
                    if re.match(r'^\d+(\.\d+)?$', clean_text):
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