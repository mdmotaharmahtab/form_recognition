Looking at the sample pages, I can see three distinct patterns:

1. **Cluster 1 (pages 174, 187)**: These are reference/lookup tables with "Coded/Decode" headers - exactly the type the program already skips. These pages contain NO data-entry fields (just code lists like "mg/mg", "ORAL/Oral"). Zero coverage here is CORRECT.

2. **Cluster 0 (pages 95, 113)**: These are the detailed field definition pages (Family D/F) that the program is designed to handle. Looking at page 95, I can see fields like "Body system", "Examination result", "Clinical significance" that SHOULD be extracted. The program claims 76% coverage, so it's getting most of these.

3. **Cluster 2 (pages 11, 14)**: These are study schedule pages showing timepoints and form names in a timeline format. The current program tries to extract from the "Form" column in schedule tables, but these pages have a different layout - they list forms at x~207.8 (not x~165 as expected). Forms like "Urine Collection - PK - Active Interval Collection (2-4)", "Blood Collection - PD Creatinine", "Lunch Start", "Dinner Start", etc. appear at x=207.8 and should be extracted.

The main issue is **Cluster 2** - the schedule pages have forms at a different x-coordinate than the program expects. I need to add more flexible handling for schedule table layouts.

```python
# Layout observation:
# - Family A/B: cover/approval pages (no data fields)
# - Family C: study schedule tables with event/timepoint/form columns
# - Family D: detailed field definition pages with form headers in white-on-color bar
# - Family E: reference tables (units, code lists) - not data-entry fields
# - Family F: long field specs similar to D
# Form names appear in white text on colored backgrounds (sz=12.0 #ffffff) at top of D/F pages.
# Fields in D/F have labels at x~46.5, with technical metadata in right column x>450.

import re
from collections import defaultdict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Detect reference/lookup table pages (family E) - skip entirely
        # They have symmetric two-column layouts with "Coded/Decode" or "Name/Symbol" headers
        headers = [ln.text.strip() for ln in lines if ln.y0 < 80 and ln.size >= 10]
        if any(re.search(r'\b(Coded|Decode|Symbol|Order ID|Container)\b', h, re.I) for h in headers):
            # Check if this is a reference table (both columns are list content, not field definitions)
            has_field_label_column = any(ln.x0 < 100 and ln.y0 > 100 and 
                                         re.search(r'\[.*?\]', ln.text) for ln in lines)
            if not has_field_label_column:
                continue  # skip reference table pages
        
        # Detect cover/approval pages (family A/B) by structural markers
        if any("aCRF Approval Form" in ln.text or "By signing below" in ln.text for ln in lines):
            continue
        
        # Extract form name from white-on-color header (family D/F pattern)
        for ln in lines:
            if (ln.y0 < 50 and ln.size >= 11 and ln.non_black and 
                "Origin:" not in ln.text and "Protocol" not in ln.text and 
                "Sponsor" not in ln.text and "DM-010" not in ln.text):
                candidate = ln.text.strip()
                # Filter out pure technical markers
                if not re.match(r'^(Origin|Aliases|Repeating|Domain|SAS)', candidate):
                    current_form = candidate
                    break
        
        # Family C: schedule tables with Study Event / Timepoint / Form columns
        # Detect by presence of "Study Event" column header at x<60
        has_study_event_col = any(ln.text.strip() == "Study Event" and ln.x0 < 60 and ln.y0 < 80 
                                   for ln in lines)
        
        if has_study_event_col:
            # Look for form names in the rightmost text column (typically x>200)
            # Forms appear as text lines at consistent x-positions, size 9.0, y>60
            form_candidates = []
            
            for ln in lines:
                # Forms are typically at x~165-210, size 9.0, y>60, black text
                if (ln.y0 > 60 and 150 < ln.x0 < 220 and 
                    abs(ln.size - 9.0) < 0.5 and not ln.non_black):
                    form_text = ln.text.strip()
                    
                    # Filter out non-form content
                    if (form_text and len(form_text) > 3 and 
                        # Exclude conditional visibility notes, timepoints, study events
                        "Conditionally" not in form_text and
                        "Conditional Item:" not in form_text and
                        "Visible If" not in form_text and
                        "Timepoint:" not in form_text and
                        "Study Event:" not in form_text and
                        "Form:" not in form_text and
                        # Exclude time patterns like "00:40:00 (2)"
                        not re.match(r'^[\d:*()-]+$', form_text) and
                        # Exclude pure day markers
                        not re.match(r'^Day\s+\d+$', form_text, re.I)):
                        
                        # This looks like a form name
                        form_candidates.append(form_text)
            
            # Add unique form names from this schedule page
            for form_text in set(form_candidates):
                results.append({
                    "form_name": form_text,
                    "field_name": form_text,
                    "page": page_num
                })
            
            continue  # done with this schedule page
        
        # Family D/F: field definition pages
        # Field labels are at x~46.5, y>100, size~7.5, followed by input markers or options
        # They wrap across lines; join continuations.
        # Right column (x>400) is technical metadata - ignore.
        
        field_candidates = []
        for i, ln in enumerate(lines):
            if (40 < ln.x0 < 70 and ln.y0 > 90 and 7 <= ln.size <= 8 and 
                not ln.non_black and not re.search(r'\[.*?\]', ln.text)):
                
                text = ln.text.strip()
                # Skip obvious non-fields
                if (not text or len(text) < 3 or 
                    re.match(r'^(Aliases|Description|Comment|Role Restriction|SAS Field|Format|Data Type|Origin|Mandatory|Edit Checks|Code List|Sample Path|Requires|Device|Conditional|Visible|Default|Range|Units|dd-MMM|Disallow)', text, re.I)):
                    continue
                
                # Collect wrapped continuations: same x0, consecutive y
                parts = [text]
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if (abs(nxt.x0 - ln.x0) < 5 and nxt.y0 - lines[j-1].y0 < 12 and 
                        7 <= nxt.size <= 8 and not nxt.non_black):
                        parts.append(nxt.text.strip())
                        j += 1
                    else:
                        break
                
                full_text = " ".join(parts)
                
                # Filter out answer options (lines starting with O or checkbox marker)
                if re.match(r'^O\s', full_text):
                    continue
                
                # Filter out line-number only patterns
                if re.match(r'^\d+\.\s*$', full_text):
                    continue
                
                # Must look like a question or label
                if len(full_text) > 5:
                    field_candidates.append((ln.y0, full_text))
        
        # De-duplicate vertically close candidates (keep first in each y-band)
        field_candidates.sort()
        seen_y = set()
        for y, fld in field_candidates:
            # Band fields within 15pt y-range
            if not any(abs(y - sy) < 15 for sy in seen_y):
                seen_y.add(y)
                results.append({
                    "form_name": current_form,
                    "field_name": fld,
                    "page": page_num
                })
    
    # Final de-duplication by (form_name, field_name)
    unique = {}
    for rec in results:
        key = (rec["form_name"], rec["field_name"])
        if key not in unique:
            unique[key] = rec
    
    return list(unique.values())
```
