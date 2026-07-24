def extract(pages):
    """
    This document contains two main layout families:
    - Family A: aCRF Approval Form pages with structured fields (Sponsor Name, Protocol Number, etc.)
    - Family B: Electronic Record and Signature Disclosure pages (legal/consent text, no data-entry fields)
    
    Strategy: Extract fields from Family A pages by identifying bold labels followed by their values.
    Family B pages contain only prose text with no data-entry fields, so they are skipped.
    """
    import re
    
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Check if this is a Family B page (Electronic Record and Signature Disclosure)
        # These pages have distinctive text patterns and no data-entry fields
        text_sample = ' '.join(line.text for line in lines[:20])
        if 'ELECTRONIC RECORD AND SIGNATURE DISCLOSURE' in text_sample or \
           'Electronic Record and Signature Disclosure created on:' in text_sample:
            continue
        
        # Check if this is a Family A page (aCRF Approval Form)
        # Look for the distinctive title
        is_approval_form = False
        for line in lines:
            if 'aCRF Approval Form' in line.text:
                is_approval_form = True
                break
        
        if not is_approval_form:
            continue
        
        # Extract fields from Family A pages
        # These pages have bold labels on the left and values on the right
        # The form name is "aCRF Approval Form"
        form_name = "aCRF Approval Form"
        
        # Look for bold labels that represent field names
        for i, line in enumerate(lines):
            # Skip header information
            if line.y0 < 100:
                continue
            
            # Look for bold text that appears to be a field label
            if line.bold and line.size >= 14:
                field_text = line.text.strip()
                
                # Filter out non-field text
                if not field_text:
                    continue
                if field_text.startswith('DM-'):
                    continue
                if 'Sponsor Name:' in field_text or 'Protocol Number:' in field_text:
                    continue
                if field_text == 'aCRF Approval Form':
                    continue
                if 'By signing below' in field_text:
                    continue
                
                # Valid field labels we expect
                valid_labels = [
                    'Sponsor Name',
                    'Protocol Number',
                    'Protocol Title',
                    'aCRF Version',
                    'Prepared by',
                    'Date'
                ]
                
                if field_text in valid_labels:
                    results.append({
                        "form_name": form_name,
                        "field_name": field_text,
                        "page": page_num
                    })
    
    return results
