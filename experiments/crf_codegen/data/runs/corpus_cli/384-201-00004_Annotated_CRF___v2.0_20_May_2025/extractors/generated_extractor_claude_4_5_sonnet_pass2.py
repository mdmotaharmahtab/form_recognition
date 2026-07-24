# This document contains multiple layout families; this program handles only the
# approval/history pages (pages 1-3 and similar admin pages). The real CRF data-entry
# pages are handled by other programs. We extract labeled metadata fields from the
# approval form (page 1) and ignore version-history and signature pages.
# Strategy: detect the "aCRF Approval Form" title on page 1 and extract the bold
# labels paired with their values; skip all other page types.

import re
from typing import List, Dict, Any

def extract(pages):
    results = []
    
    for page_num, lines in pages:
        if not lines:
            continue
        
        # Check if this is the aCRF Approval Form page (page 1 style)
        # Look for the distinctive "aCRF Approval Form" title
        is_approval_form = False
        for line in lines:
            if 'aCRF Approval Form' in line.text:
                is_approval_form = True
                break
        
        if not is_approval_form:
            continue
        
        # Extract fields from the approval form
        # Pattern: bold label on left, value on right
        # Labels: Sponsor Name, Protocol Number, Protocol Title, aCRF Version, Prepared by, Date
        
        for i, line in enumerate(lines):
            # Skip header/footer content
            if line.y0 < 100 or line.y0 > 700:
                continue
            
            # Look for bold labels (16pt bold text on left side)
            if line.bold and line.size >= 14 and line.x0 < 100:
                # Known field labels we want to extract
                label_patterns = [
                    'Sponsor Name',
                    'Protocol Number', 
                    'Protocol Title',
                    'aCRF Version',
                    'Prepared by',
                    'Date'
                ]
                
                label_text = line.text.strip()
                
                # Check if this line matches any of our field labels
                for pattern in label_patterns:
                    if pattern.lower() in label_text.lower():
                        # Use the exact label text as field_name
                        results.append({
                            "form_name": "aCRF Approval Form",
                            "field_name": label_text,
                            "page": page_num + 1
                        })
                        break
    
    return results
