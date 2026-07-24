I've rewritten the extraction program to be less aggressive with filtering. Key changes:

1. **Better numeric prefix handling**: Changed from rejecting any text starting with digits to only rejecting PURE numeric text. Now accepts fields like "33. Stereotyped thinking" and "27. Duration of ideation".

2. **Refined filtering logic**: 
   - Keep numbered list items (pattern `\d+\.` followed by substantial text)
   - Only skip standalone single digits at the very left margin (page numbering)
   - Skip "X of Y" page numbers explicitly

3. **Improved continuation detection**: Better detection of when a wrapped line is part of the same field vs. a new numbered field

4. **More lenient acceptance**: Text longer than 3 characters that isn't pure punctuation/whitespace/codes is accepted as a field

5. **Still preserves original coverage**: Keeps all the structural detection for data dictionary pages, signature pages, form name extraction, and answer option filtering that was working correctly.

The program now extends rather than replaces the working logic, adding better handling for numbered fields while maintaining the 99% coverage on cluster 1.
