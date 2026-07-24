import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Detect TOC pages by structure: many numbered section entries (3.XX. Title) in blue/colored text
        toc_pattern_count = sum(1 for line in lines 
                               if re.match(r'^\d+\.\d+\.', line.text.strip()) 
                               and line.non_black)
        is_toc_page = toc_pattern_count > 5
        
        if is_toc_page:
            continue
        
        # Extract form name: large blue text (size >= 15, color #004c99 or similar blue)
        # This appears at top of form pages
        for line in lines:
            text = line.text.strip()
            if (line.size >= 15.0 and line.non_black and 
                text and not text.startswith('[') and 
                not re.match(r'^\d+\.\d+\.', text) and
                not re.match(r'^Page \d+ of \d+$', text)):
                current_form = text
                break
        
        # Extract field names
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            if not text:
                i += 1
                continue
            
            # Skip page numbers
            if re.match(r'^Page \d+ of \d+$', text):
                i += 1
                continue
            
            # Skip red text (technical annotations like [TYPE:, [VISIBILITY:, etc.)
            if line.non_black and '#ff0000' in str(line.__dict__):
                i += 1
                continue
            
            # Skip gray text (answer options like Yes/No, radio button labels)
            if line.non_black and '#999999' in str(line.__dict__):
                i += 1
                continue
            
            # Skip bracketed machine codes
            if text.startswith('['):
                i += 1
                continue
            
            # Skip lines that are purely technical keywords
            if text in ['Read-only', 'TYPE:', 'VISIBILITY:']:
                i += 1
                continue
            
            # Identify field labels: black text, size typically 8-11
            # Field labels are questions, statements, or data entry prompts
            if not line.non_black and 7.5 <= line.size <= 11.5:
                # Collect this line and any continuation lines
                field_text = text
                field_x0 = line.x0
                field_y0 = line.y0
                field_size = line.size
                j = i + 1
                
                # Look ahead for continuation lines
                while j < len(lines):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    if not next_text:
                        j += 1
                        continue
                    
                    # Stop at red annotations
                    if next_line.non_black and '#ff0000' in str(next_line.__dict__):
                        break
                    
                    # Stop at bracketed codes
                    if next_text.startswith('['):
                        break
                    
                    # Stop at page numbers
                    if re.match(r'^Page \d+ of \d+$', next_text):
                        break
                    
                    # Stop if vertical gap is too large (new field/section)
                    if next_line.y0 - field_y0 > 60:
                        break
                    
                    # Check if continuation: similar x position, similar size, black text
                    if (not next_line.non_black and
                        abs(next_line.x0 - field_x0) < 30 and
                        abs(next_line.size - field_size) < 2.5):
                        field_text += ' ' + next_text
                        field_y0 = next_line.y0  # Update for next iteration
                        j += 1
                    else:
                        break
                
                # Clean up field text
                field_text = ' '.join(field_text.split())
                
                # Filter out non-fields by structural characteristics
                
                # Skip single bullets or very short fragments that aren't questions
                if field_text in ['•', '-', '*'] or (len(field_text) < 3 and not field_text.endswith('?')):
                    i = j
                    continue
                
                # Skip copyright and definition headers
                if ('©' in field_text or 'copyright' in field_text.lower()):
                    i = j
                    continue
                
                # Skip if it starts with ** and looks like a header/instruction (not a field)
                # But keep it if it's a question or instruction that's actually a field label
                if field_text.startswith('**') and not field_text.endswith('**'):
                    # This is likely a bold instruction/question - keep it
                    pass
                elif field_text.startswith('Definitions of'):
                    i = j
                    continue
                
                # Skip "Row N" labels that are just structural markers
                # But keep "Row N If Yes, describe" or similar which are actual fields
                if re.match(r'^Row \d+$', field_text):
                    i = j
                    continue
                
                # Skip "Select all that apply" standalone instructions
                if field_text == 'Select all that apply':
                    i = j
                    continue
                
                # Detect if this is a long definition/instruction block (not a field)
                # These are characterized by:
                # - Very long text (> 300 chars)
                # - Multiple sentences with detailed explanations
                # - Contains phrases like "For example", "This is considered", "Inferring Intent"
                is_definition_block = (len(field_text) > 300 and
                                      field_text.count('.') > 3 and
                                      any(phrase in field_text for phrase in 
                                          ['For example', 'This is considered', 'Inferring Intent',
                                           'does not have to be', 'can be inferred']))
                
                if is_definition_block:
                    i = j
                    continue
                
                # Detect list-of-test-names pattern (like lab test lists)
                lab_test_indicators = ['Albumin', 'Alkaline phosphatase', 'ALT', 'AST', 'Calcium', 
                                      'Carbon dioxide', 'Chloride', 'Cholesterol', 'Creatine', 
                                      'Creatinine', 'Gamma glutamyl', 'Glucose', 'Lactate', 
                                      'Magnesium', 'Phosphorus', 'Potassium', 'Prolactin', 
                                      'bilirubin', 'protein', 'Triglycerides', 'Sodium', 
                                      'Urea nitrogen', 'Uric acid', 'Hematocrit', 'Hemoglobin',
                                      'corpuscular', 'Platelet', 'Red blood cell', 'White blood cell',
                                      'Glycated Hemoglobin']
                
                lab_test_count = sum(1 for term in lab_test_indicators if term in field_text)
                is_lab_test_list = (lab_test_count >= 3 or 
                                   (lab_test_count >= 2 and ';' in field_text))
                
                if is_lab_test_list:
                    i = j
                    continue
                
                # Detect C-SSRS instruction blocks - these are very long explanatory texts
                # Key pattern: starts with "Row N" and contains very long explanatory text (>150 chars)
                # with multiple sentences and specific instructional phrases
                # OR contains detailed behavioral explanations
                is_cssrs_instruction = (
                    # Long Row N instructions with detailed explanations
                    (re.match(r'^Row \d+', field_text) and
                     len(field_text) > 150 and
                     (field_text.count('.') >= 2 or field_text.count(';') >= 2) and
                     any(phrase in field_text for phrase in
                         ['must ask about', 'does not have to be', 
                          'can be considered', 'can be inferred',
                          'Examples are similar', 'instead of being stopped',
                          'Select all that apply, so long as',
                          'A potentially self-injurious act',
                          'Intent does not have to be',
                          'There does not have to be any injury',
                          'When person begins to take steps',
                          'stops themselves before they actually',
                          'stops him/herself, instead of being stopped'])) or
                    # Long explanatory text about self-injurious behavior (not starting with Row)
                    (len(field_text) > 150 and
                     field_text.count('.') >= 2 and
                     any(phrase in field_text for phrase in
                         ['Or did you do it purely for other reasons',
                          'without ANY intention of killing yourself',
                          'Self-Injurious Behavior without suicidal intent',
                          'like to relieve stress, feel better']))
                )
                
                if is_cssrs_instruction:
                    i = j
                    continue
                
                # Detect if this is a bare list item without context (just an option name)
                is_bare_list_item = (len(field_text.split()) <= 3 and 
                                    not field_text.endswith('?') and
                                    not field_text.endswith(':') and
                                    not any(kw in field_text for kw in 
                                           ['Date', 'Time', 'Number', 'Was', 'Is', 'Did', 'Does', 
                                            'Has', 'Have', 'Will', 'Row']))
                
                # Check if this looks like a complete field label
                is_complete_field = (len(field_text) >= 15 or 
                                   field_text.endswith('?') or
                                   field_text.endswith(':') or
                                   field_text.endswith(')') or  # Include parenthetical units
                                   any(kw in field_text for kw in 
                                       ['Date', 'Time', 'Number', 'Was', 'Is', 'Did', 'Does', 
                                        'Has', 'Have', 'Will', 'Subject', 'Patient', 'Clinician',
                                        'Row', 'If Yes', 'attempt', 'Rate', 'breaths', 'celsius',
                                        'Temperature', 'Respiratory']))
                
                # Accept if it's a complete field
                if is_complete_field and not is_bare_list_item:
                    results.append({
                        'form_name': current_form,
                        'field_name': field_text,
                        'page': page_num
                    })
                    i = j
                    continue
                
                # For shorter text, check if it's in a field context
                if len(field_text) >= 10 and not is_bare_list_item:
                    results.append({
                        'form_name': current_form,
                        'field_name': field_text,
                        'page': page_num
                    })
                
                i = j
            else:
                i += 1
    
    return results
