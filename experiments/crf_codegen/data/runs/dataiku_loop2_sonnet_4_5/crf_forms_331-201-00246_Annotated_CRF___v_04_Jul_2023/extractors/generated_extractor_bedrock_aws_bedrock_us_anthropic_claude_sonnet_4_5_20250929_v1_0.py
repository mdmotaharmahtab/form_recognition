import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    seen_fields = set()  # Track (form, field, page) to avoid duplicates
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip table of contents pages (pages 1-2 based on sample)
        if page_num <= 2:
            continue
        
        # Find form name: large colored headers (size >= 15, colored, not black)
        # Also check for continuation headers (e.g., "FormName - Page N")
        for line in lines:
            if line.size >= 15.0 and line.non_black and not line.text.startswith('['):
                # Clean up form name
                form_text = line.text.strip()
                # Remove " - Page N" suffix if present
                form_text = re.sub(r'\s*-\s*Page\s+\d+\s*$', '', form_text)
                # Skip if it looks like a section number (e.g., "3.1. Visit Date")
                if not re.match(r'^\d+\.', form_text):
                    current_form = form_text
                    break
        
        # Extract field labels
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Skip empty lines, page numbers, technical codes
            if not text:
                continue
            if re.match(r'^Page \d+ of \d+$', text):
                continue
            if text.startswith('[') and text.endswith(']'):
                continue
            if re.match(r'^\[.*\]$', text):
                continue
            
            # Skip table headers and common column labels
            if text in ['Criteria', 'Met/Not Met', 'Sample', 'Timepoint', 'Sample Status',
                       'Time of Collection', 'Barcode Number', 'Test', 'Result', 'Status',
                       'Reason not done', 'Date of Collection', 'Scan', 'Suicidal Ideation',
                       'Since Last Visit', 'Response', 'Behavior', 'Ideation']:
                continue
            
            # Skip answer options (Yes/No/Met/Not Met/etc.)
            if text in ['Yes', 'No', 'Met', 'Not Met', 'Positive', 'Negative', 'Not Done',
                       'Collected', 'Not Collected', 'Not Applicable', 'N/A', 'Predose',
                       '1h postdose', '1.5h postdose', '2h postdose', '2.5h postdose',
                       '3h postdose', '4h postdose', '6h postdose', '8h postdose']:
                continue
            
            # Skip row labels
            if re.match(r'^Row \d+$', text):
                continue
            
            # Skip technical annotations (gray text or red text with TYPE/VISIBILITY/etc.)
            if line.non_black and ('[' in text or 'TYPE:' in text or 'VISIBILITY:' in text):
                continue
            
            # Skip scanner/barcode placeholders
            if text in ['Scan']:
                continue
            
            # CRITICAL: Skip section headers that look like "3.55. Clinical Laboratory Assessments"
            # These are TOC-style references, not field labels
            if re.match(r'^\d+\.\d+\.\s+[A-Z]', text):
                continue
            
            # CRITICAL: Skip partial sentences that are line-wrapped continuation text
            # These typically:
            # - Don't start with capital letter or start mid-sentence
            # - Are fragments of longer criteria text
            # - Don't end with punctuation or question mark
            if (len(text) > 50 and 
                not text.endswith('?') and 
                not text.endswith('.') and
                not text.endswith(':') and
                not re.match(r'^[A-Z\d]', text)):
                # Check if this looks like a continuation (starts with lowercase or mid-phrase)
                if text[0].islower() or text.startswith('interpretation of'):
                    continue
            
            # Skip text that looks like it's part of a wrapped sentence
            # (contains phrases that indicate middle of sentence)
            if any(phrase in text.lower() for phrase in [
                'that could compromise', 'that could interfere with the',
                'interpretation of trial results', 'ability to comply with'
            ]):
                continue
            
            # Field labels are typically:
            # - Black text (not colored)
            # - Size 9-10.5 typically
            # - Not starting with backslash-number (criteria numbering)
            # - Actual questions or prompts
            
            is_field = False
            
            # Pattern 1: Questions ending with "?"
            if text.endswith('?') and not line.non_black and line.size <= 11:
                is_field = True
            
            # Pattern 2: Field prompts (not bold, black, reasonable size)
            # Exclude criteria text (starts with \d+\.)
            if (not line.non_black and 
                line.size >= 8.5 and line.size <= 11 and
                not re.match(r'^\\?\d+\\.', text) and
                not line.bold and
                len(text) > 10 and
                not text.startswith('If ') and
                'describe' not in text.lower()):
                
                # Check if it looks like a field label
                if any(keyword in text for keyword in ['Time of', 'Date of', 'Collection Date',
                                                        'Were ', 'reason:', 'Planned Timepoint',
                                                        'subject ']):
                    is_field = True
            
            # Pattern 3: Specific field patterns
            if (not line.non_black and line.size >= 8.5 and line.size <= 11):
                # Time/date fields
                if re.match(r'^(Time|Date) (of|subject)', text):
                    is_field = True
                # Collection/measurement prompts
                if re.match(r'^(Were |If not |Collection |Planned )', text):
                    is_field = True
            
            # Pattern 4: Criteria text (numbered exclusion/inclusion criteria)
            # These are field labels in this CRF
            if (not line.non_black and 
                re.match(r'^\\?\d+\\.', text) and
                line.size >= 8.5 and line.size <= 10):
                # This is a criteria item - it's a field
                # Clean up the text
                clean_text = re.sub(r'^\\?\d+\\.\\?\s*', '', text)
                if len(clean_text) > 20:  # Substantial criteria text
                    is_field = True
                    text = clean_text
            
            # Pattern 5: Black text fields in medium size range (broader capture)
            # This catches fields that don't match specific patterns above
            if (not line.non_black and 
                line.size >= 8.0 and line.size <= 12.0 and
                len(text) > 15 and
                not text.isupper() and  # Skip all-caps headers
                not re.match(r'^Page \d+', text) and
                ':' in text or text.endswith('?') or 
                any(word in text.lower() for word in ['date', 'time', 'specify', 'describe', 
                                                       'indicate', 'provide', 'enter', 'record',
                                                       'assessment', 'measurement', 'value'])):
                is_field = True
            
            if is_field:
                # Clean up field name
                field_name = text.strip()
                
                # Skip if it's just a description prompt
                if field_name.startswith('If Yes, describe'):
                    continue
                
                # Create record
                key = (current_form, field_name, page_num)
                if key not in seen_fields:
                    seen_fields.add(key)
                    results.append({
                        "form_name": current_form,
                        "field_name": field_name,
                        "page": page_num
                    })
    
    return results
