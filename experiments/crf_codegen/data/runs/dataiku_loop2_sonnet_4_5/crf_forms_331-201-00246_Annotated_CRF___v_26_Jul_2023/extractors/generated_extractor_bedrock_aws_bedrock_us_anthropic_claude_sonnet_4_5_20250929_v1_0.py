import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Group lines by y-coordinate to identify rows
        y_groups = defaultdict(list)
        for line in lines:
            y_groups[round(line.y0, 1)].append(line)
        
        for line in lines:
            # Detect form names: large blue headings (sz=16.5, color #004c99)
            if line.size >= 16.0 and line.non_black:
                # Check if it's a blue heading
                if not line.text.startswith('[') and line.text not in ['Supine', 'Standing']:
                    current_form = line.text.strip()
            
            # Detect field labels: black or gray text, size ~9.0-10.5, not technical codes
            # Include gray text (#999999) which is used for field labels in tables
            is_gray = line.non_black and '#999999' in str(line.non_black).lower()
            
            if (line.size >= 8.5 and line.size <= 11.0 and 
                not line.bold and 
                (not line.non_black or is_gray) and
                not line.text.startswith('[')):
                
                text = line.text.strip()
                
                # Skip empty, page numbers
                if not text:
                    continue
                if re.match(r'^Page \d+ of \d+$', text):
                    continue
                
                # Skip answer options at right side of page (Yes/No/Met/Not Met/etc at specific x positions)
                if line.x0 > 650 and text in ['Yes', 'No', 'Met', 'Not Met', 
                                               'Positive', 'Negative', 'Not Done',
                                               'Collected', 'Not Collected', 
                                               'Not Applicable', '0', '1', '2', '3', '4', '5']:
                    continue
                
                # Skip row labels like "Row 5", "Row 12", etc.
                if re.match(r'^Row \d+$', text):
                    continue
                
                # Skip technical annotations and codes
                if re.match(r'^\[.*\]$', text):
                    continue
                if re.match(r'^\(.*\)$', text):
                    continue
                
                # Skip pure dates, times, numbers
                if re.match(r'^\d{1,2}[A-Za-z]{3,9}\d{4}$', text):
                    continue
                if re.match(r'^\d+(\.\d+)?$', text) and len(text) < 4:
                    continue
                
                # Skip timepoint options (predose, postdose, etc.) when they appear as standalone values
                if re.match(r'^(N/A|Predose|\d+\.?\d*h [Pp]ostdose)$', text, re.IGNORECASE):
                    continue
                
                # Skip procedure specifications headers
                if text.startswith('Procedures Specifications:'):
                    continue
                
                # Skip descriptive instructions that are not questions
                if text.startswith('Collect vital signs after'):
                    continue
                if text.startswith('Water should not be restricted'):
                    continue
                
                # Skip partial text fragments that are clearly incomplete (from page 17/18)
                if re.match(r'^ed to be Titrated \? = Yes', text):
                    continue
                if re.match(r'^to be Titrated \? =Yes on', text):
                    continue
                
                # Skip test/assay names that are just descriptive labels, not data entry fields
                # These appear in gray but are category labels, not fields
                test_names = [
                    'Platelet count', 'Red blood cell count', 'White blood cell count (absolute and differential)',
                    'Hemoglobin', 'Hematocrit', 'Mean corpuscular volume', 'Mean corpuscular hemoglobin',
                    'Mean corpuscular hemoglobin concentration', 'Neutrophils', 'Lymphocytes', 'Monocytes',
                    'Eosinophils', 'Basophils', 'Reticulocyte count'
                ]
                if text in test_names:
                    continue
                
                # Valid field patterns:
                # 1. Criteria fields start with backslash-number pattern
                is_criteria = re.match(r'^\\?\d+\\.', text)
                
                # 2. Questions typically end with '?' or contain question words
                is_question = ('?' in text or 
                              text.startswith('If ') or
                              text.startswith('Were ') or
                              text.startswith('Date ') or
                              text.startswith('Time ') or
                              text.startswith('Planned '))
                
                # 3. Table column headers (size 10.5, at top of page area)
                is_column_header = (line.size >= 10.0 and line.y0 < 200 and 
                                   text not in ['Sample', 'Test', 'Result', 'Status', 'Scan'] and
                                   len(text) > 2)
                
                # 4. Gray text field labels (used in table rows)
                is_gray_label = is_gray and len(text) > 2
                
                # 5. Check if this line is followed by a red technical code
                has_code_below = False
                for other in lines:
                    if (other.non_black and 
                        other.y0 > line.y0 and 
                        other.y0 < line.y0 + 30 and
                        abs(other.x0 - line.x0) < 50 and
                        other.text.startswith('[')):
                        has_code_below = True
                        break
                
                # 6. Specific field patterns we know are valid
                # Include patterns like "Hematology clinically significant abnormal assay # 3"
                is_known_field = (text.startswith('If Yes, describe') or
                                 text.startswith('Date of ') or
                                 text.startswith('Actual Lethality') or
                                 text.startswith('Potential Lethality') or
                                 'PK' in text or  # Pharmacokinetic samples
                                 re.match(r'.+ clinically significant abnormal assay # \d+', text) or  # Page 566 pattern
                                 text in ['Hematology', 'Chemistry', 'Suicidal Ideation', 
                                         'Since Last Visit', 'Actual Attempts', 'Most Lethal Attempt',
                                         'Sample Status', 'Time of Collection', 'Barcode Number',
                                         'Backup Barcode Number', 'Reason not done', 'Date of Collection',
                                         'Timepoint'])
                
                # Extract if it matches any valid pattern
                if (is_criteria or is_question or has_code_below or 
                    is_column_header or is_gray_label or is_known_field):
                    # Clean up the text
                    field_text = text
                    # Remove leading numbering from criteria
                    field_text = re.sub(r'^\\?\d+\\.?\s*', '', field_text)
                    
                    if field_text and current_form:
                        results.append({
                            "form_name": current_form,
                            "field_name": field_text,
                            "page": page_num
                        })
    
    # Deduplicate consecutive identical entries
    deduplicated = []
    prev = None
    for r in results:
        key = (r['form_name'], r['field_name'])
        if key != prev:
            deduplicated.append(r)
            prev = key
    
    return deduplicated
