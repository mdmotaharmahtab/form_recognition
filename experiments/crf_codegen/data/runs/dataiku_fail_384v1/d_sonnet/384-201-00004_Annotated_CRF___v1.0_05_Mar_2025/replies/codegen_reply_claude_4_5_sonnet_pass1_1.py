```python
# This annotated CRF has multiple layout families:
# - Family A/B: cover/approval pages (no data fields)
# - Family C: main form pages with field definitions in a structured layout
# - Family D: reference/lookup tables (units, code lists, lab panels)
# Strategy: Extract fields from family C by identifying field labels (sz=7.5 black text
# at x~46.5) paired with input markers. Form names are large colored headers (sz=10.5+
# #31708f). Family D pages are reference tables, not data-entry fields. Use color,
# size, and x-position to discriminate fields from technical annotations.

import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip cover/approval pages (families A/B) - very few lines or signature blocks
        if page_num <= 3:
            continue
        
        # Detect reference table pages (family D): white header at top, then column headers
        # with "Coded/Decode", "Name/Symbol", etc. These are NOT data-entry fields.
        is_reference_table = False
        for i, line in enumerate(lines[:10]):
            if line.size >= 10 and "#ffffff" in str(line.non_black) and i < 5:
                # Check if followed by column headers (sz ~10.5, #666677, "Coded", "Name", etc.)
                for j in range(i+1, min(i+5, len(lines))):
                    if lines[j].size >= 10 and lines[j].bold:
                        text_sample = " ".join([l.text for l in lines[i:i+10]])
                        if any(kw in text_sample for kw in ["Coded", "Decode", "Order ID", "Container", "Symbol"]):
                            is_reference_table = True
                            break
                break
        
        if is_reference_table:
            continue
        
        # Extract form name: large colored header (sz >= 10, color #31708f, x < 100)
        # typically at y ~72-73, text like "Electrocardiogram 2", "Urine Collection...", etc.
        for i, line in enumerate(lines):
            if (line.size >= 10 and line.non_black and 
                line.x0 < 100 and 40 < line.y0 < 600):
                # Check if this is a teal/blue header (#31708f or similar)
                # and not white (#ffffff which is reference tables)
                text = line.text.strip()
                # Filter out technical annotations and short fragments
                if (len(text) > 3 and 
                    not text.startswith("Origin:") and
                    not text.startswith("Repeating:") and
                    not text.startswith("Domain:") and
                    not text.startswith("SAS Dataset") and
                    not text in ["Aliases:", "Role Restriction:", "Comment:", "Description:"] and
                    not re.match(r'^[A-Z0-9_]+$', text)):  # not machine codes
                    # This might be a form header
                    current_form = text
                    break
        
        # Extract fields: look for label lines (sz ~7.5, black, x ~46.5)
        # followed by input markers like [brackets], O choice, or underscores
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Field label pattern: sz 7.5, black, x between 40-50, not technical text
            if (7 <= line.size <= 8 and not line.non_black and 
                40 <= line.x0 <= 55 and line.y0 > 80):
                
                text = line.text.strip()
                
                # Skip technical annotations (often in square brackets or machine codes)
                if (text.startswith("[") or 
                    text.startswith("Odm OID") or
                    text.startswith("CC Mapping") or
                    text in ["Aliases:", "Comment:", "Description:", "Role Restriction:"] or
                    re.match(r'^\[?[A-Z][A-Z0-9_]+\]?$', text)):  # machine codes like [PCDTC]
                    i += 1
                    continue
                
                # Check if next 1-3 lines contain input markers (at x ~240-260)
                has_input = False
                for j in range(i+1, min(i+4, len(lines))):
                    next_line = lines[j].text.strip()
                    if (240 <= lines[j].x0 <= 270 and 
                        (next_line.startswith("O ") or  # radio option
                         "[_" in next_line or  # text input
                         next_line.startswith("["))):  # field marker
                        has_input = True
                        break
                
                # Also check if this line itself contains a label pattern
                # (like "Was the sample collected?" or "PR" or "QRS")
                if (has_input or 
                    (len(text) > 2 and 
                     not text.startswith("Code List:") and
                     not text.startswith("Format:") and
                     not re.match(r'^(dd-MMM|N\(|Format|Data Type|Origin)', text))):
                    
                    # Clean up the label: join multi-line labels
                    label_parts = [text]
                    k = i + 1
                    while k < min(i + 5, len(lines)):
                        next_text = lines[k].text.strip()
                        # Continue if same x position and looks like continuation
                        if (40 <= lines[k].x0 <= 55 and 
                            7 <= lines[k].size <= 8 and
                            not lines[k].non_black and
                            not next_text.startswith("[") and
                            not next_text.startswith("O ") and
                            not next_text.startswith("Code List:") and
                            len(next_text) > 0):
                            label_parts.append(next_text)
                            k += 1
                        else:
                            break
                    
                    field_label = " ".join(label_parts).strip()
                    
                    # Final validation: skip if looks like technical metadata
                    if (len(field_label) > 2 and
                        not field_label.startswith("[") and
                        not re.match(r'^[A-Z][A-Z0-9_]+$', field_label) and
                        field_label not in ["Aliases:", "Comment:", "Description:"] and
                        not field_label.startswith("Code List:") and
                        not field_label.startswith("Format:") and
                        not field_label.startswith("Data Type:") and
                        not field_label.startswith("Origin:") and
                        not field_label.startswith("Odm OID")):
                        
                        records.append({
                            "form_name": current_form,
                            "field_name": field_label,
                            "page": page_num
                        })
            
            i += 1
    
    # Deduplicate exact duplicates (same form, field, page)
    seen = set()
    unique_records = []
    for rec in records:
        key = (rec["form_name"], rec["field_name"], rec["page"])
        if key not in seen:
            seen.add(key)
            unique_records.append(rec)
    
    return unique_records
```
