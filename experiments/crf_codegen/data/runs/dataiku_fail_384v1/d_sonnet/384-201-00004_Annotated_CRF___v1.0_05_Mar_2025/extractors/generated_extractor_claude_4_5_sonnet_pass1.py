# Annotated CRF with multiple layout families:
# - Family A/B: cover/approval pages
# - Family C: main form pages with field definitions
# - Family D: reference/lookup tables (units, code lists, lab panels)
# Strategy: Extract fields from family C by structural position and style.
# Field labels are sz~7.5 black text at x~46.5, paired with input markers or
# metadata blocks. Form names are large colored headers (sz>=10, #31708f-like, x<100).
# Reference tables (family D) have "Coded/Decode" column headers - skip those pages.
# Use position, size, and color to discriminate, not literal text matching.

import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip early cover/approval pages (very sparse, signature blocks)
        if page_num <= 3:
            continue
        
        # Detect reference table pages (family D): look for "Coded" + "Decode" 
        # column headers at y~59-60, sz~10.5, bold, at different x positions
        is_reference_table = False
        coded_header = False
        decode_header = False
        for line in lines[:15]:
            if (line.size >= 10 and line.bold and 
                50 <= line.y0 <= 70 and line.x0 < 100):
                if "Coded" in line.text:
                    coded_header = True
                elif "Decode" in line.text and line.x0 > 250:
                    decode_header = True
        if coded_header and decode_header:
            is_reference_table = True
        
        if is_reference_table:
            continue
        
        # Extract form name: large header (sz >= 10, colored, x < 100, y < 80)
        # Color should NOT be white (#ffffff = reference tables)
        for line in lines[:20]:
            if (line.size >= 10 and line.non_black and 
                line.x0 < 100 and 30 < line.y0 < 80):
                text = line.text.strip()
                # Form headers are substantial text, not single-word codes
                if (len(text) > 3 and 
                    not text.startswith("Origin") and
                    not text.startswith("Repeating") and
                    not text.startswith("Domain") and
                    not text.startswith("SAS Dataset") and
                    not text.startswith("Odm OID") and
                    "#ffffff" not in str(line.non_black)):
                    # Avoid all-caps machine codes with underscores like "CMROUTE"
                    if "_" not in text and not re.match(r'^[A-Z0-9_]+$', text):
                        current_form = text
                        break
        
        # Extract fields: look for label lines at x~46.5, sz~7.5, black
        # These may be followed by input markers, code lists, or metadata blocks
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field label candidate: sz 7-8, black, x in left column (40-55)
            # Must be below header area (y > 80)
            if (7 <= line.size <= 8 and not line.non_black and 
                40 <= line.x0 <= 55 and line.y0 > 80):
                
                text = line.text.strip()
                
                # Skip machine codes in brackets like [PCDTC], [LBCLSIG_THCSIG]
                # Pattern: starts with [ 
                if text.startswith("["):
                    i += 1
                    continue
                
                # Skip metadata keywords that appear at this x position
                # but are not field labels (structural: they're at x~46 but are
                # technical annotations, identified by being exactly these keywords)
                if text in ["Aliases:", "Comment:", "Description:", "Role Restriction:"]:
                    i += 1
                    continue
                
                # Skip lines that are clearly technical (start with technical prefixes)
                # These are structural identifiers, not literal blocklists
                if (text.startswith("SAS Field Name:") or
                    text.startswith("Odm OID") or
                    text.startswith("CC Mapping")):
                    i += 1
                    continue
                
                # Check for evidence this is a data field:
                # 1. Next few lines contain input markers (x~240-270)
                # 2. Next few lines contain metadata like "Code List:" (x~296+)
                # 3. It's a short label (like "PR", "QRS", "BMI") in field context
                
                has_input_marker = False
                has_metadata = False
                
                # Look ahead 1-5 lines for input markers or metadata
                for j in range(i+1, min(i+6, len(lines))):
                    next_text = lines[j].text.strip()
                    next_x = lines[j].x0
                    
                    # Input markers at x~240-270
                    if (240 <= next_x <= 270 and
                        (next_text.startswith("O ") or "[_" in next_text or 
                         next_text.startswith("["))):
                        has_input_marker = True
                    
                    # Metadata at x~296+ (Code List, Format, Data Type, etc.)
                    if next_x > 290:
                        if (next_text.startswith("Code List:") or
                            next_text.startswith("Format:") or
                            next_text.startswith("Data Type:") or
                            next_text.startswith("SDS Var Name:")):
                            has_metadata = True
                
                # Accept as field if:
                # - Has supporting evidence (input marker or metadata), OR
                # - Is a short medical abbreviation (2-4 chars, all caps, no underscores)
                #   These are field labels like "PR", "QRS", "QT", "BMI", not codes
                # - Is non-trivial text (>= 2 chars) that doesn't look like a machine code
                #   Machine codes have underscores or match patterns like XXXX_YYYY
                
                is_short_medical_abbrev = (2 <= len(text) <= 4 and 
                                           text.isupper() and 
                                           "_" not in text and
                                           text.isalpha())
                
                is_likely_field = (has_input_marker or has_metadata or
                                   is_short_medical_abbrev or
                                   (len(text) >= 2 and "_" not in text and 
                                    not re.match(r'^[A-Z][A-Z0-9]+$', text)))
                
                if is_likely_field:
                    # Collect multi-line label if it continues
                    label_parts = [text]
                    k = i + 1
                    while k < min(i + 5, len(lines)):
                        next_line = lines[k]
                        next_text = next_line.text.strip()
                        
                        # Continue if same structural position (x~40-55, sz~7-8, black)
                        # and doesn't look like a new field or metadata
                        if (40 <= next_line.x0 <= 55 and 
                            7 <= next_line.size <= 8 and
                            not next_line.non_black and
                            len(next_text) > 0 and
                            not next_text.startswith("[") and
                            not next_text.startswith("O ") and
                            not next_text.startswith("Code List:") and
                            not next_text.startswith("Format:") and
                            not next_text.startswith("Data Type:") and
                            not next_text in ["Aliases:", "Comment:", "Description:"]):
                            label_parts.append(next_text)
                            k += 1
                        else:
                            break
                    
                    field_label = " ".join(label_parts).strip()
                    
                    # Final validation: must be non-empty, non-bracketed
                    # Allow short uppercase labels (they're medical abbreviations)
                    if (len(field_label) > 0 and
                        not field_label.startswith("[")):
                        
                        records.append({
                            "form_name": current_form,
                            "field_name": field_label,
                            "page": page_num
                        })
            
            i += 1
    
    # Deduplicate exact duplicates
    seen = set()
    unique_records = []
    for rec in records:
        key = (rec["form_name"], rec["field_name"], rec["page"])
        if key not in seen:
            seen.add(key)
            unique_records.append(rec)
    
    return unique_records
