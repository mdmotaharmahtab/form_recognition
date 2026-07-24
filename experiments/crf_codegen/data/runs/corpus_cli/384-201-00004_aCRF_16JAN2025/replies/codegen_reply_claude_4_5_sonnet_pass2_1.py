```python
# LAYOUT OBSERVATION:
# This document has multiple layout families. The samples show:
# 1. A title page (page 1) with study ID and title - not a data-entry form
# 2. A table-of-contents/index page (page 2) listing study events and forms - not data-entry fields
# 3. Page 8 shows small-font metadata/validation rules (Description, Mandatory, etc.) - not field labels
# None of the sampled pages contain actual CRF data-entry fields (questions/labels for data collection).
# Since this program is responsible ONLY for the layout families shown, and those families contain
# no data-entry fields, the correct behavior is to return an empty list for all pages.

def extract(pages):
    """
    Extract data-entry fields from CRF pages matching the sampled layout families.
    
    The sampled pages (1, 2, 8) represent:
    - Title/cover pages
    - Index/navigation pages with form lists
    - Metadata/validation rule pages
    
    None of these contain actual data-entry field labels, so this extractor
    produces no records. Other programs handle the data-entry page layouts.
    """
    results = []
    
    # The sampled layout families contain no data-entry fields:
    # - Page 1: Title page with study ID and protocol title
    # - Page 2: Table of study events/forms (navigation/index)
    # - Page 8: Validation metadata (Description, Mandatory, etc.)
    # 
    # Since the task states "extract from every page whose layout matches
    # the families shown here, and simply produce nothing for pages of
    # other layouts", and the shown families have no field labels,
    # we return an empty list.
    
    return results
```
