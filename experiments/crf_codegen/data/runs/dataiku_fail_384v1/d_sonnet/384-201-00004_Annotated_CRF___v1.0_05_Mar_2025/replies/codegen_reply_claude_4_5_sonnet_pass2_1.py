```python
# This CRF contains several layout families:
# - Family A/B: Cover/approval pages (no fields to extract)
# - Family C: Schedule/table-of-contents pages listing study events and forms
# - Family D: Detailed form annotation pages with field specifications
# Strategy: Extract from family C (form schedules) and family D (field details).
# Family C: Extract form names from the "Form" column.
# Family D: Extract fields from repeating sections marked by field codes and labels.

import re
from collections import defaultdict

def extract(pages):
    results = []
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Try to identify page type by structural markers
        lines_text = [ln.text for ln in lines]
        
        # Family C: Schedule pages with "Study Event" and "Form" column headers
        # Look for the header row: "Study Event" / "Form" or "Timepoint" / "Form"
        is_schedule_page = False
        form_column_x = None
        
        for i, ln in enumerate(lines):
            if ln.text.strip() in ["Study Event", "Timepoint"] and ln.bold:
                # Look for "Form" header nearby
                for j in range(max(0, i-2), min(len(lines), i+5)):
                    if lines[j].text.strip() == "Form" and lines[j].bold:
                        is_schedule_page = True
                        form_column_x = lines[j].x0
                        break
                if is_schedule_page:
                    break
        
        if is_schedule_page and form_column_x is not None:
            # Extract form names from the Form column
            # Forms appear below the header row, aligned near form_column_x
            # Heuristic: lines with x0 close to form_column_x, size ~9pt, not colored annotations
            for ln in lines:
                # Skip if this is a header or annotation
                if ln.bold or ln.size < 8 or ln.size > 11:
                    continue
                if ln.non_black:
                    continue
                # Check x alignment: within ~30pts of form_column_x
                if abs(ln.x0 - form_column_x) < 30:
                    form_name = ln.text.strip()
                    # Filter out non-form lines: empty, page numbers, protocol numbers, etc.
                    if not form_name or len(form_name) < 3:
                        continue
                    # Skip lines that look like dates, times, technical codes
                    if re.match(r'^Day\s+[-\d]+', form_name):
                        continue
                    if re.match(r'^\d{2}:\d{2}:\d{2}', form_name):
                        continue
                    if re.match(r'^[-\d:\s()]+$', form_name):
                        continue
                    # Skip known non-field text
                    if form_name in ["Annotated CRF", "https://drvince.clinspark.com"]:
                        continue
                    # This looks like a form name
                    results.append({
                        "form_name": form_name,
                        "field_name": form_name,
                        "page": page_num
                    })
            continue
        
        # Family D: Detailed annotation pages
        # These pages have a large colored banner at the top (size 12, white text on colored background)
        # with the form name, followed by repeating field sections.
        # Each field section has a field code (bold, small font, e.g. "CMTRT") and a field label.
        
        # Look for form name in the colored banner at top
        form_name = None
        for ln in lines[:20]:  # Check first 20 lines
            if ln.size >= 11 and ln.size <= 13 and ln.non_black:
                # This is likely the form title
                candidate = ln.text.strip()
                # Skip obvious non-titles
                if candidate and not re.match(r'^(Origin|Aliases|Odm|Format|Data Type)', candidate):
                    if candidate not in ["384-201-00004", "Annotated CRF"]:
                        form_name = candidate
                        break
        
        if not form_name:
            # Try to find form name in section headers (10.5pt, colored text)
            for ln in lines[:30]:
                if ln.size >= 10 and ln.size <= 11 and ln.non_black:
                    candidate = ln.text.strip()
                    if candidate and len(candidate) > 5:
                        # Filter out technical annotations
                        if not re.match(r'^(Origin|Repeating|Domain|Conditionally)', candidate):
                            form_name = candidate
                            break
        
        # Extract fields from Family D pages
        # Fields are identified by:
        # 1. A field code in bold small font (5-6pt) on the right side (x > 450)
        # 2. A field label on the left side (x < 100), size 7-8pt
        # The label usually appears a few lines after or before the code.
        
        field_sections = []
        for i, ln in enumerate(lines):
            # Look for field codes: bold, small font (5-6pt), right side
            if ln.bold and 5 <= ln.size <= 6.5 and ln.x0 > 450:
                code = ln.text.strip()
                # Field codes are uppercase alphanumeric, e.g. CMTRT, CMDOSE, INC001
                if re.match(r'^[A-Z]{2,}[A-Z0-9]*$', code):
                    # Find the corresponding label
                    # Look in nearby lines (within 20 lines before/after)
                    label = None
                    for j in range(max(0, i-20), min(len(lines), i+20)):
                        cand_ln = lines[j]
                        # Label is on the left side, size 7-8pt, not bold
                        if 40 < cand_ln.x0 < 100 and 7 <= cand_ln.size <= 8.5 and not cand_ln.bold:
                            cand_text = cand_ln.text.strip()
                            # Skip technical annotations
                            if cand_text.startswith('[') or cand_text in ["O Yes", "O No", "O N/A", "O Unspecified"]:
                                continue
                            # Skip empty or very short
                            if len(cand_text) < 3:
                                continue
                            # Skip code lists, technical notes
                            if re.match(r'^Code List:', cand_text):
                                continue
                            # This looks like a label
                            label = cand_text
                            break
                    
                    if label:
                        field_sections.append((code, label))
        
        # Add extracted fields to results
        if form_name and field_sections:
            for code, label in field_sections:
                results.append({
                    "form_name": form_name,
                    "field_name": label,
                    "page": page_num
                })
    
    # Deduplicate results
    seen = set()
    deduplicated = []
    for rec in results:
        key = (rec["form_name"], rec["field_name"], rec["page"])
        if key not in seen:
            seen.add(key)
            deduplicated.append(rec)
    
    return deduplicated
```
