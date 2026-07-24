Looking at the error, the issue is clear: `pages` is being passed as a list of tuples rather than a list of dictionaries. The code expects `page.get('blocks')` but `page` is a tuple, which doesn't have a `.get()` method.

I need to handle the tuple structure. Typically in document parsing, tuples might be `(page_dict, metadata)` or similar. Let me rewrite to handle this robustly:

```python
from typing import List, Dict, Any, Union, Tuple
import re

def extract(pages: Union[List[Dict[str, Any]], List[Tuple]]) -> List[Dict[str, Any]]:
    """Extract form_name and field_name from CRF pages."""
    records = []
    
    # Handle different input formats
    normalized_pages = []
    for item in pages:
        if isinstance(item, tuple):
            # If tuple, take the first element (usually the page dict)
            page = item[0] if len(item) > 0 else {}
        elif isinstance(item, dict):
            page = item
        else:
            continue
        normalized_pages.append(page)
    
    for page_num, page in enumerate(normalized_pages, 1):
        if not isinstance(page, dict):
            continue
            
        blocks = page.get('blocks', [])
        if not blocks:
            continue
        
        page_height = page.get('height', 1000)
        page_width = page.get('width', 1000)
        
        # Sort blocks by vertical position, then horizontal
        sorted_blocks = sorted(blocks, key=lambda b: (b.get('bbox', [0,0,0,0])[1], b.get('bbox', [0,0,0,0])[0]))
        
        # Find form name (large, bold, top of page)
        form_name = None
        for block in sorted_blocks[:15]:
            bbox = block.get('bbox', [0, 0, 0, 0])
            y_pos = bbox[1]
            text = block.get('text', '').strip()
            
            if y_pos < page_height * 0.25 and len(text) > 5:
                flags = block.get('flags', 0)
                size = block.get('size', 0)
                
                # Check if bold or large
                is_bold = (flags & 16) or (flags & 32)
                is_large = size > 12
                
                # Skip junk patterns
                if any(x in text.lower() for x in ['page', 'of ', 'visit', 'date:', 'subject']):
                    continue
                if re.match(r'^\d+\s+of\s+\d+$', text, re.IGNORECASE):
                    continue
                    
                if (is_bold or is_large) and not form_name:
                    form_name = text
                    break
        
        if not form_name:
            form_name = "Form"
        
        # Extract fields
        field_lines = []
        
        for block in sorted_blocks:
            bbox = block.get('bbox', [0, 0, 0, 0])
            text = block.get('text', '').strip()
            x_pos = bbox[0]
            y_pos = bbox[1]
            
            if not text or len(text) < 2:
                continue
            
            # Skip header/footer regions
            if y_pos < page_height * 0.15 or y_pos > page_height * 0.95:
                continue
            
            # Skip far-right content (often page numbers or codes)
            if x_pos > page_width * 0.85:
                continue
            
            # Skip pure page numbering patterns
            if re.match(r'^\d+$', text) and x_pos < page_width * 0.1:
                continue
            if re.match(r'^\d+\s+of\s+\d+$', text, re.IGNORECASE):
                continue
            if re.match(r'^page\s+\d+', text, re.IGNORECASE):
                continue
            
            # Skip signature/date labels (page furniture)
            if re.match(r'^(signature|date|investigator|time|name|initials)[\s:]*$', text, re.IGNORECASE):
                continue
            
            # Skip answer options and rating scales
            if re.match(r'^(\d+\s*[-–]\s*\d+|yes\s*/\s*no|n\s*/\s*a)$', text, re.IGNORECASE):
                continue
            if text.lower() in ['yes', 'no', 'unknown', 'na', 'n/a', 'ongoing']:
                continue
            
            # Skip pure codes/numbers (but allow numbered fields)
            if re.match(r'^[\d\.\-\s]+$', text):
                continue
            if re.match(r'^[A-Z]{1,4}\d{1,3}$', text):
                continue
            
            # Skip data dictionary patterns
            if 'data dictionary' in text.lower():
                continue
            if re.match(r'^(variable|type|length|format|label|values)', text, re.IGNORECASE):
                continue
            
            # Accept numbered list items (e.g., "1. Field name" or "33. Stereotyped thinking")
            # These are legitimate field labels
            if re.match(r'^\d{1,2}\.\s+\w', text):
                field_lines.append({
                    'text': text,
                    'y': y_pos,
                    'x': x_pos,
                    'bbox': bbox
                })
                continue
            
            # Accept substantial text that isn't pure punctuation
            cleaned = re.sub(r'[^\w\s]', '', text)
            if len(cleaned) > 3:
                field_lines.append({
                    'text': text,
                    'y': y_pos,
                    'x': x_pos,
                    'bbox': bbox
                })
        
        # Merge continuation lines
        merged_fields = []
        i = 0
        while i < len(field_lines):
            current = field_lines[i]
            merged_text = current['text']
            
            # Look ahead for continuation lines
            j = i + 1
            while j < len(field_lines):
                next_line = field_lines[j]
                
                # Check if next line is a continuation (close vertically, similar x or indented)
                y_diff = next_line['y'] - current['y']
                x_diff = abs(next_line['x'] - current['x'])
                
                # If next line starts with a number (new field), stop merging
                if re.match(r'^\d{1,2}\.\s', next_line['text']):
                    break
                
                # Continuation: close vertically and horizontally aligned or indented
                if y_diff < 20 and (x_diff < 50 or next_line['x'] > current['x']):
                    merged_text += ' ' + next_line['text']
                    j += 1
                else:
                    break
            
            if merged_text:
                merged_fields.append(merged_text)
            
            i = j if j > i + 1 else i + 1
        
        # Create records
        for field_name in merged_fields:
            # Clean up the field name
            field_name = ' '.join(field_name.split())
            
            if len(field_name) > 3:
                records.append({
                    'form_name': form_name,
                    'field_name': field_name
                })
    
    return records
```
