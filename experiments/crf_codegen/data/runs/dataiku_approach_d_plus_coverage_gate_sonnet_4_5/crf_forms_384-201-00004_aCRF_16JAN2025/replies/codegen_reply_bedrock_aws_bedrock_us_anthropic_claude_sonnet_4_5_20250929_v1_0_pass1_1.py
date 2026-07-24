STRATEGY:

The document is a clinical CRF with a title page, table-of-contents pages (layout family B), code-list pages (also family B), and field-bearing form pages (families C and D). Form titles appear in a white-on-colored banner at y≈34.8 with size 12pt (family C/D) or as colored headers at y≈72.8 with size 10.5pt. I will extract the form name from the white banner when present and carry it forward across continuation pages that lack it, since a form spans multiple pages. Field labels appear at x≈46.5 in size 7.5pt black text on family D pages, and similar positions on family C pages. I distinguish fields from answer options by checking that options appear immediately below their field (smaller y-gap, often with "O" radio markers or indented x-position). Code-list pages (family B) show tables with "Coded"/"Decode" headers and are not field pages; I will skip them by detecting the header pattern. The TOC pages list form names in blue links but hold no data-entry fields, so I skip them by detecting the "Study Events" or similar heading and the columnar layout. I will NOT skip pages based on a single cue like font size alone; instead I check for structural signatures (the TOC column headers, the code-list table headers). For pages with fields, I join wrapped label lines by detecting continuation text at the same x-position with small y-gap. I exclude technical annotations in the right column (x>450) and small gray metadata lines. I carry the current form name forward until a new form title is encountered, ensuring every field record has a form_name.

CODE:

```python
# CRF extraction: title page, TOC/code-list pages (skip), and field pages (families C/D).
# Form titles in white banner at y~34.8 sz=12; fields at x~46.5 sz=7.5; carry form forward.

import re
from typing import List, Dict

def extract(pages):
    results = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        # Skip title page (page 1)
        if page_num == 1:
            continue
        
        # Detect TOC/code-list pages by structural headers
        if _is_toc_or_codelist_page(lines):
            continue
        
        # Extract form title from white banner or colored header
        form_title = _extract_form_title(lines)
        if form_title:
            current_form = form_title
        
        # Extract fields from this page
        fields = _extract_fields(lines, current_form, page_num)
        results.extend(fields)
    
    return results

def _is_toc_or_codelist_page(lines):
    # TOC pages have "Study Events" header and columns "Name", "Forms", "Type"
    # Code-list pages have "Coded" and "Decode" headers
    for line in lines[:15]:
        if line.size >= 10 and ("Study Events" in line.text or 
                                 ("Coded" in line.text and "Decode" in line.text)):
            return True
        if line.y0 < 70 and ("Category Visit" in line.text or 
                              ("Coded" in line.text or "Decode" in line.text)):
            return True
    return False

def _extract_form_title(lines):
    # White banner at y~34.8 sz=12 (families C/D)
    for line in lines:
        if 30 < line.y0 < 40 and 11 < line.size < 13 and line.x0 < 100:
            text = line.text.strip()
            if text and not text.startswith("384-201"):
                return text
    # Colored header at y~72.8 sz=10.5 (alternative)
    for line in lines:
        if 70 < line.y0 < 80 and 9.5 < line.size < 11.5 and line.x0 < 100:
            text = line.text.strip()
            if text and not re.match(r'^(Origin|Aliases)', text):
                return text
    return ""

def _extract_fields(lines, form_name, page_num):
    fields = []
    # Field labels at x~46.5, sz~7.5, black, not in brackets, not options
    i = 0
    while i < len(lines):
        line = lines[i]
        # Field label candidates: x in [40,60], sz in [7,8], black, not bold
        if (40 <= line.x0 <= 60 and 7 <= line.size <= 8 and 
            not line.bold and not line.non_black):
            text = line.text.strip()
            # Skip bracketed codes, metadata, options
            if (text and not text.startswith('[') and 
                not text.startswith('O ') and
                not re.match(r'^(SAS Field Name|Aliases|Description|Code List|dd-MMM)', text)):
                # Join wrapped lines
                full_label = text
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if (40 <= next_line.x0 <= 60 and 
                        next_line.y0 - line.y0 < 20 and
                        not next_line.text.strip().startswith('[') and
                        not next_line.text.strip().startswith('O ')):
                        full_label += " " + next_line.text.strip()
                        j += 1
                    else:
                        break
                # Check if this is an answer option (follows a field closely)
                if not _is_answer_option(lines, i):
                    fields.append({
                        "form_name": form_name,
                        "field_name": full_label,
                        "page": page_num
                    })
                i = j
                continue
        i += 1
    return fields

def _is_answer_option(lines, idx):
    # Options appear below a field with small y-gap, often with "O" marker
    if idx == 0:
        return False
    line = lines[idx]
    # Check if preceded by a field label within 30 points
    for j in range(max(0, idx-5), idx):
        prev = lines[j]
        if (40 <= prev.x0 <= 60 and 7 <= prev.size <= 8 and
            line.y0 - prev.y0 < 30 and
            not prev.text.strip().startswith('O ')):
            # This line is close below a field, likely an option
            if line.text.strip().startswith('O '):
                return True
    return False
```