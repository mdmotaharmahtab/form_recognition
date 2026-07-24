import re
from collections import defaultdict

def extract(pages):
    records = []
    current_form = ""
    
    for page_idx, lines in pages:
        page_num = page_idx + 1
        
        if not lines:
            continue
        
        # Detect version history table pages by columnar structure
        # Look for lines aligned in columns with version/date patterns
        x_positions = defaultdict(list)
        for line in lines:
            if line.y0 > 100 and line.y0 < 600 and line.size >= 8 and line.size <= 10:
                x_rounded = round(line.x0 / 10) * 10  # Group by approximate x position
                x_positions[x_rounded].append(line.text.strip())
        
        # Check if we have 3-4 columns with version-like content
        columns_with_content = [col for col in x_positions.values() if len(col) >= 3]
        if len(columns_with_content) >= 3:
            all_text = " ".join([" ".join(col) for col in columns_with_content])
            # Look for version patterns and date patterns
            has_versions = bool(re.search(r'\b\d+\.\d+', all_text))
            has_dates = bool(re.search(r'\d{1,2}[-/]\w{3}[-/]\d{4}|\d{1,2}[A-Z][a-z]{2}\d{4}', all_text))
            version_keywords = any(word in all_text.lower() for word in ['version', 'changed by', 'details'])
            
            if has_versions and has_dates and version_keywords:
                continue  # Skip version history page
        
        # Skip copyright/attribution pages: very sparse with copyright notice
        page_text = " ".join(l.text for l in lines)
        substantive_lines = [l for l in lines if len(l.text.strip()) > 10 and 
                            l.y0 > 120 and l.y0 < 750]
        
        if "© 2008 The Research Foundation for Mental Hygiene" in page_text and \
           len(substantive_lines) < 15:
            continue
        
        # Skip simple instruction pages: colored title + single bracketed instruction
        colored_titles = [l for l in lines if l.non_black and l.size >= 14 and l.y0 < 300]
        bracketed_lines = [l for l in lines if l.text.strip().startswith("(") and 
                          l.text.strip().endswith(")") and l.y0 > 150]
        other_content = [l for l in lines if not l.non_black and l.size >= 8 and 
                        l.y0 > 150 and l.y0 < 750 and len(l.text.strip()) > 5 and
                        not (l.text.strip().startswith("(") and l.text.strip().endswith(")"))]
        
        if len(colored_titles) >= 1 and len(bracketed_lines) >= 1 and len(other_content) < 3:
            continue
        
        # Detect form title: large (≥14pt), colored, near top (y0 < 350)
        # Or carry forward from previous page if no new title found
        found_new_title = False
        for line in lines:
            if line.size >= 14 and line.non_black and line.y0 < 350:
                text = line.text.strip()
                # Exclude annotations in brackets
                if text and not text.startswith("(") and len(text) > 2:
                    current_form = text
                    found_new_title = True
                    break
        
        # Collect field candidates
        field_candidates = []
        
        for i, line in enumerate(lines):
            text = line.text.strip()
            
            # Basic filters
            if not text:
                continue
            if line.non_black:  # Skip colored text (annotations)
                continue
            if line.size < 7 or line.size > 13:  # Slightly wider range
                continue
            
            # Position filters: fields are in main content area
            if line.y0 < 100:  # Skip header area
                continue
            if line.y0 > 780:  # Skip footer area
                continue
            
            # Skip page numbers
            if re.match(r'^Page \d+ of \d+$', text):
                continue
            
            # Skip very short text unless it's bold or looks like a field label
            if len(text) <= 2 and not line.bold:
                continue
            
            # Allow longer text if it's a question (contains ?)
            max_length = 250 if '?' in text else 150
            if len(text) > max_length:
                continue
            
            # Skip parenthetical instructions (UI hints) - but not if they're part of a question
            if text.startswith("(") and text.endswith(")") and '?' not in text:
                continue
            
            # Detect concatenated checkbox options: multiple capitalized phrases without proper punctuation
            # Pattern: "Word Word Word Word" with 3+ capital-starting words and no commas/semicolons
            words = text.split()
            capital_starts = [w for w in words if w and w[0].isupper()]
            has_punctuation = any(p in text for p in [',', ';', ':', '.', '?'])
            
            # If we have many capital words, no punctuation, and it's long, it might be concatenated options
            if len(capital_starts) >= 4 and not has_punctuation and len(text) > 40 and not line.bold:
                # Try to split on common patterns
                # Look for pattern like "Word1 Word2 Word3 Word4" where each pair is a phrase
                # For now, skip these as they're likely concatenated options
                continue
            
            # Check for multi-line label continuation
            # Lines that are close vertically and horizontally aligned
            if field_candidates and \
               abs(line.x0 - field_candidates[-1]["x0"]) < 30 and \
               line.y0 - field_candidates[-1]["y1"] < 25 and \
               line.y0 - field_candidates[-1]["y1"] > 0:
                # Continuation of previous line
                field_candidates[-1]["text"] += " " + text
                field_candidates[-1]["y1"] = line.y1
            else:
                # New field candidate
                field_candidates.append({
                    "text": text,
                    "x0": line.x0,
                    "y0": line.y0,
                    "y1": line.y1,
                    "bold": line.bold,
                    "size": line.size
                })
        
        # Add valid fields to records
        for cand in field_candidates:
            text = cand["text"]
            
            # Final validation: skip if it looks like a filled date value
            if re.match(r'^\d{1,2}[-/]\w{3}[-/]\d{4}$', text):
                continue
            
            # Skip if it's just a number (but allow if bold - might be a field label)
            if re.match(r'^\d+\.?\d*$', text) and len(text) < 10 and not cand["bold"]:
                continue
            
            # Skip standalone "Page?" - it's a fragment
            if text == "Page?":
                continue
            
            # Skip version numbers
            if re.match(r'^\d+\.\d+(\.\d+)?$', text):
                continue
            
            # Skip single words that are common in version tables
            if text.lower() in ['version', 'date', 'details', 'initial', 'draft', 'updates']:
                continue
            
            # Skip names that look like authors (First Last pattern with no other context)
            if re.match(r'^[A-Z][a-z]+ [A-Z][a-z]+$', text) and len(text) < 30:
                # Could be an author name in version history
                # But allow if it's bold or part of a longer phrase
                if not cand["bold"] and len(text.split()) == 2:
                    continue
            
            # Valid field
            records.append({
                "form_name": current_form,
                "field_name": text,
                "page": page_num
            })
    
    # Deduplicate exact duplicates
    seen = set()
    unique_records = []
    for rec in records:
        key = (rec["form_name"], rec["field_name"], rec["page"])
        if key not in seen:
            seen.add(key)
            unique_records.append(rec)
    
    return unique_records
