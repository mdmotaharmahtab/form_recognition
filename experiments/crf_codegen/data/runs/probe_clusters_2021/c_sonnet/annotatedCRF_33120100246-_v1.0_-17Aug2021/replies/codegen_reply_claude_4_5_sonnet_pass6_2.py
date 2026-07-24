I need to analyze the problems and fix the extraction program. Let me examine the issues:

1. **False positives**: Extracting non-field text like "Control Period Day 2", "page enrols if..."
2. **Wrong form attribution**: Some fields assigned to wrong forms
3. **Missing fields**: Not extracting some visible fields on pages 518, 559
4. **Low coverage**: Cluster 0 (5 pages) has 0% coverage - these are schedule tables that should be skipped

Looking at the sample pages (11, 13), I can see they are schedule tables with visit/page listings - NOT data-entry forms. The program should skip these entirely.

The key issues:
- Schedule tables are being processed when they should be skipped
- Need better detection of actual form pages vs schedule/TOC pages
- Need better field label detection to avoid visit labels and conditional text
- Need to handle different form layouts (pages 518, 559 have fields we're missing)

Let me rewrite the program:

```python
import re
from collections import defaultdict

def extract(pages):
    results = []
    
    # Build page_number → form_name mapping from schedule tables
    page_to_form = {}
    for page_idx, lines in pages:
        if not lines:
            continue
        # Schedule tables have "Page Number" / "Page Label" headers
        has_schedule_headers = any(
            ('Page Label' in line.text or 'Page Number' in line.text) and line.bold
            for line in lines
        )
        if has_schedule_headers:
            # Extract page → form mapping from schedule rows
            i = 0
            while i < len(lines):
                line = lines[i]
                # Page number: numeric only, black, size ~7-8
                if (not line.non_black and line.size >= 7 and line.size <= 9 and
                    re.match(r'^\d+$', line.text.strip())):
                    page_num = int(line.text.strip())
                    # Look for blue label text in next lines (x offset > 40)
                    label_parts = []
                    j = i + 1
                    while j < len(lines) and j < i + 5:
                        next_line = lines[j]
                        # Blue text with x offset indicates label
                        if next_line.non_black and abs(next_line.x0 - line.x0) > 40:
                            label_parts.append(next_line.text.strip())
                            j += 1
                        else:
                            break
                    if label_parts:
                        form_name = ' '.join(label_parts)
                        page_to_form[page_num] = form_name
                    i = j
                else:
                    i += 1
    
    # Process each page for field extraction
    current_form = ""
    for page_idx, lines in pages:
        page_num_1based = page_idx + 1
        
        if not lines:
            continue
        
        # Detect schedule/TOC pages - skip them entirely
        has_schedule_structure = False
        has_visit_label_header = False
        has_page_label_header = False
        
        for line in lines:
            if line.bold and line.size >= 7 and line.size <= 9:
                text = line.text.strip()
                if 'Visit Label' in text or 'Visit Number' in text:
                    has_visit_label_header = True
                if 'Page Label' in text or 'Page Number' in text:
                    has_page_label_header = True
        
        # If both headers present, it's a schedule table
        if has_visit_label_header or has_page_label_header:
            # Check for multiple page numbers in column (schedule structure)
            page_numbers = [line for line in lines if not line.non_black and 
                          re.match(r'^\d+$', line.text.strip()) and line.size >= 7 and line.size <= 9]
            if len(page_numbers) >= 3:
                has_schedule_structure = True
        
        # Skip TOC, schedule, and visit listing pages
        is_toc = any('CHANGE HISTORY' in line.text or 'TABLE OF CONTENTS' in line.text 
                     for line in lines if line.size > 12)
        
        if is_toc or has_schedule_structure:
            continue
        
        # Get form name for this page
        if page_num_1based in page_to_form:
            current_form = page_to_form[page_num_1based]
        else:
            # Look for bold blue header as form title (near top, size 13+)
            for line in lines:
                if (line.bold and line.non_black and line.size >= 13 and 
                    line.y0 < 150 and len(line.text.strip()) > 3 and
                    not any(skip in line.text for skip in ['Schedule', 'Visit', 'CHANGE HISTORY'])):
                    current_form = line.text.strip()
                    break
        
        # Extract field labels from this page
        # Strategy: find black text that looks like field labels
        # Skip: red annotations, answer options, visit labels, schedule text, page furniture
        
        field_candidates = []
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text.strip()
            
            # Skip red text (technical annotations) - check for red color
            if line.non_black and ('#ff0000' in str(line.non_black).lower() or 
                                   'ff0000' in str(line.non_black).lower()):
                i += 1
                continue
            
            # Skip empty or very short
            if not text or len(text) < 3:
                i += 1
                continue
            
            # Skip pure numbers or dates
            if re.match(r'^[\d\.\s\-/]+$', text):
                i += 1
                continue
            
            # Skip answer options
            if text in ['Yes', 'No', 'YES', 'NO', 'yes', 'no', 'NA', 'N/A']:
                i += 1
                continue
            
            # Skip visit/period labels (common in schedules)
            if re.match(r'^(Control Period|Treatment Period|Steady-state|Screening Period|Follow-up)', text):
                i += 1
                continue
            
            # Skip "Day N" patterns
            if re.match(r'^Day \d+$', text):
                i += 1
                continue
            
            # Skip "Row N" labels
            if re.match(r'^Row \d+$', text):
                i += 1
                continue
            
            # Skip conditional enrollment text
            if 'page enrols if' in text.lower() or 'if applicable' in text.lower():
                i += 1
                continue
            
            # Skip page furniture (top of page, small font)
            if line.y0 < 50 and line.size < 9:
                i += 1
                continue
            
            # Skip large bold headers (section titles, not field labels)
            if line.bold and line.size > 11:
                i += 1
                continue
            
            # Candidate field labels: black text, reasonable font size
            # Field labels are typically size 8-11, not bold, black
            if (not line.non_black and line.size >= 7 and line.size <= 12 and
                not line.bold):
                
                # Collect wrapped lines for this field
                field_parts = [text]
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    next_text = next_line.text.strip()
                    
                    # Stop if we hit red text
                    if next_line.non_black and ('#ff0000' in str(next_line.non_black).lower()):
                        break
                    
                    # Continuation line: similar x, close y, reasonable size
                    if (abs(next_line.x0 - line.x0) < 25 and 
                        next_line.y0 - lines[j-1].y0 < 18 and
                        next_line.size >= 7 and next_line.size <= 12 and
                        not next_line.non_black and
                        len(next_text) > 0 and
                        not next_text.startswith('[')):
                        # Check if it's a natural continuation
                        # (starts lowercase, or previous doesn't end sentence)
                        if (next_text[0].islower() or 
                            not field_parts[-1].rstrip().endswith(('?', '.', ':'))):
                            field_parts.append(next_text)
                            j += 1
                        else:
                            break
                    else:
                        break
                
                field_text = ' '.join(field_parts)
                
                # Filter out non-field patterns
                # Skip rating scale numbers
                if re.search(r'\(\d+\)', field_text):
                    i = j
                    continue
                
                # Skip descriptive/instructional text
                skip_patterns = [
                    'examples are', 'examples include', 'person has', 'when person',
                    'acts or preparation', 'such as:', 'note:', 'instructions:',
                    'overdose:', 'shooting:', 'jumping:', 'hanging:', 'cutting:',
                    'page enrols', 'if applicable'
                ]
                if any(pat in field_text.lower() for pat in skip_patterns):
                    i = j
                    continue
                
                # Valid field if it looks like a question or label
                # Questions end with ?, labels often end with :, or have multiple words
                is_question = field_text.endswith('?')
                is_label = field_text.endswith(':')
                has_substance = len(field_text.split()) >= 3
                
                # Also accept shorter labels that contain key field words
                has_field_keywords = any(word in field_text for word in 
                    ['Date', 'Time', 'Number', 'Bottle', 'Capsules', 'Blood Pressure',
                     'Heart Rate', 'Temperature', 'Signed', 'ICF', 'Dispensed', 'Returned',
                     'Systolic', 'Diastolic', 'End Date', 'End Time', 'Verified'])
                
                if is_question or is_label or has_substance or has_field_keywords:
                    # Clean up: remove trailing colon
                    field_text = field_text.rstrip(':').strip()
                    
                    # Final validation: not empty, not too long (not a paragraph)
                    if field_text and len(field_text) < 200:
                        if field_text not in field_candidates:
                            field_candidates.append(field_text)
                
                i = j
            else:
                i += 1
        
        # Emit records for this page
        for field_name in field_candidates:
            if current_form:  # Only emit if we have a form name
                results.append({
                    "form_name": current_form,
                    "field_name": field_name,
                    "page": page_num_1based
                })
    
    return results
```
