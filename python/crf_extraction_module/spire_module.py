import io

import logging
import dataiku
import mammoth
from bs4 import BeautifulSoup
from IPython.core.display import display, HTML
import subprocess
from spire.doc import *
from spire.doc.common import *
# from System.IO import MemoryStream


logger = logging.getLogger(__name__)

class SpireExtractor:
    
    def __init__(self, client, proj, chunk_size=1000):
        self.client = client
        self.proj = proj
        self.chunk_size = chunk_size
        self.folder_id = proj.get_variables()['local'].get('R_and_D_folder')
        self.input_folder = proj.get_managed_folder(self.folder_id)
        self.files = self.input_folder.list_contents()["items"]
        self.toc_page_limit = 20
        
    def safely_normalize_spire_html(self,html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")

        # 1. Only remove <div> with header/footer styles (don't touch inner HTML)
        for div in soup.find_all("div"):
            style = div.get("style", "")
            if "-spr-headerfooter-type" in style:
                div.decompose()

        # 2. Only remove <br> with page break styles
        for br in soup.find_all("br"):
            style = br.get("style", "")
            if "page-break-before" in style or "mso-break-type" in style:
                br.decompose()

        # 3. Remove all <img> tags
        for img in soup.find_all("img"):
            img.decompose()

        return str(soup)
    
    def normalize_toc_entry(self,s):
        s = s.lower()
        s = re.sub(r'\s+', '', s)                 # remove all whitespace
        s = re.sub(r'[^a-z0-9\.]', '', s)         # keep only letters, digits, dots
        return s
    
    def extract_section_number(self,text):
        match = re.match(r'^(\d+(?:\.\d+)*)\.?', text)
        return match.group(1) if match else None
    

    def remove_leading_section_number(self,text):
        # Removes patterns like '11.3.', '6.2.1.', or '3.' from the start of the string
        return re.sub(r'^\d+(?:\.\d+)*\.?', '', text).strip()
    


    #     from bs4 import BeautifulSoup

    def get_bold_fonts_by_size(self, soup):
        heading_map = {
            18: "h2",
            16: "h3",
            14: "h4",
            12: "h5",
            8:  "h6",
        }

        import re
        matched_fonts = []

        for font_tag in soup.find_all("font"):
            style = font_tag.get("style", "")
            match = re.search(r"font-size:\s*(\d+)pt", style)
            if not match:
                continue
            size = int(match.group(1))
            if size not in heading_map:
                continue

            # Check if bold: either <b> or <strong> tags inside or style with font-weight:bold
            is_bold = False

            # Check font tag attributes style for font-weight:bold
            if "font-weight:bold" in style.lower():
                is_bold = True

            # Or check children tags <b> or <strong>
            if not is_bold:
                if font_tag.find(["b", "strong"]):
                    is_bold = True

            if is_bold:
                matched_fonts.append(font_tag)

        return matched_fonts





    def split_html_by_section_preserve_styles_as_dict(self,full_html: str, sections_with_pages: list) -> dict:

        final_section_dict = {}
        full_html = self.safely_normalize_spire_html(full_html)

        soup = BeautifulSoup(full_html, "html.parser")
        print(soup)
        styles = str(soup.head) if soup.head else ""
        html_sections = [str(h) for h in self.get_bold_fonts_by_size(soup)]

       
            
#         print("soup",html_sections)
        heading_positions = []

        for section in html_sections:
#             print(section)
            section_str = str(section)
            start_pos = full_html.find(section_str)
            heading_positions.append((start_pos, section, section_str))

        

        # Normalize ToC titles (remove multiple spaces)
        print("heading_positions",heading_positions)
        valid_titles = set()
        toc_title_map = {}
        matched_toc_titles = set()  # To track matched ToC entries

        for sec_num, sec_title, *_ in sections_with_pages:
            joined_section = self.normalize_toc_entry(f"{sec_num}{sec_title}")
            valid_titles.add(joined_section)
            toc_title_map[joined_section] = f"{sec_num} {sec_title}"

        last_valid_key = None
        for i, (start_pos, section, section_str) in enumerate(heading_positions):
            print(i,(start_pos, section, section_str))
            end_pos = heading_positions[i + 1][0] if i + 1 < len(heading_positions) else len(full_html)
            section_html = full_html[start_pos:end_pos]
            section_title = section.get_text(strip=True)
            key = section_title.strip()

            # Normalize heading text too
            norm_key = self.normalize_toc_entry(key)

            # matched = any(norm_key in toc_title or toc_title in norm_key for toc_title in valid_titles)

            matched_title = None

            # First pass: norm_key in toc_title
            for toc_title in valid_titles:
                if norm_key == toc_title or norm_key in toc_title :
                    matched_title = toc_title
                    matched_toc_titles.add(matched_title)
                    break

            # Second pass (fallback): toc_title in norm_key
            if not matched_title:
                for toc_title in valid_titles:
                    if toc_title in norm_key:
                        matched_title = toc_title
                        matched_toc_titles.add(matched_title)
                        break

            # --- Third pass: only if section numbers match ---
            if not matched_title:
                norm_sec_num = self.extract_section_number(norm_key)
                for toc_title in valid_titles:
                    toc_sec_num = self.extract_section_number(toc_title)

                    if norm_sec_num and toc_sec_num and norm_sec_num == toc_sec_num:
                        # Strip section numbers
                        norm_key_stripped = self.remove_leading_section_number(norm_key)
                        toc_title_stripped = self.remove_leading_section_number(toc_title)

                        # Try exact or partial match on stripped titles
                        if (
                            norm_key_stripped == toc_title_stripped
                            or norm_key_stripped in toc_title_stripped
                            or toc_title_stripped in norm_key_stripped
                        ):
                            matched_title = toc_title
                            matched_toc_titles.add(matched_title)
                            break


            if matched_title:
                key = toc_title_map.get(matched_title, section_title.strip())
                full_section_html = f"""<!DOCTYPE html>
                <html>
                {styles}
                <body>
                {section_html}
                </body>
                </html>"""

                final_section_dict[key] = full_section_html.strip()
                last_valid_key = key
            else:
                logger.info(f"[WARNING] Heading not in ToC: '{key}' — normalized as '{norm_key}' — not found in sections_with_pages")
                if last_valid_key:
                    final_section_dict[last_valid_key] += f"\n{section_html}"

        # Log unmatched ToC entries
        unmatched_titles = valid_titles - matched_toc_titles
        for unmatched in unmatched_titles:
            final_section_dict[toc_title_map[unmatched]] = "" ##update
            logger.info(f"[WARNING] ToC entry not found in HTML: '{toc_title_map[unmatched]}' — normalized as '{unmatched}'")

        return final_section_dict
    
    def extract_tables_from_html_by_page_range(self, html: str, start_page: int, end_page: int) -> list:
        
        """
        Extracts <table> elements from specific page ranges using 'page-break-before' as delimiter.

        Args:
            html (str): The full HTML content from LibreOffice.
            start_page (int): Starting page number (inclusive).
            end_page (int): Ending page number (inclusive).

        Returns:
            list: List of HTML <table> strings within the given page range.
        """
        soup = BeautifulSoup(html, "html.parser")
        current_page = 1
        tables_in_range = []
        elements = soup.body.find_all(recursive=False)  # Only top-level elements

        for elem in elements:
            # Detect page breaks
            if elem.name == "p" and "style" in elem.attrs:
                style = elem["style"].lower()
                if "page-break-before: always" in style:
                    print("current_page",current_page)
                    current_page += 1

            # If in range, collect tables
            
            if start_page <= current_page <= end_page:
                print("start_page_hello",start_page , current_page , end_page,elem)
                tables_in_range.append(str(elem))


            # Exit early if past range
            if current_page > end_page:
                break

        return tables_in_range

    def process_docx_to_section_html_dict_from_s3(self, docx_filename, sections_with_pages) -> dict:
        """
        Converts a DOCX file from a Dataiku managed folder into section-wise HTML using LibreOffice.

        Args:
            docx_filename (str): The DOCX file name inside the managed folder.
            sections_with_pages (list): List of tuples (section_title, page_num)

        Returns:
            dict: section-wise HTML content.
        """
        try:

            with self.input_folder.get_file(docx_filename) as stream:

                docx_bytes = stream.raw.data  

            with tempfile.TemporaryDirectory() as tmpdir:

                input_path = os.path.join(tmpdir, "input.docx")
                output_path = os.path.join(tmpdir, "output.html")

                # Save DOCX bytes to file
                with open(input_path, "wb") as f:
                    f.write(docx_bytes)

                # Convert using LibreOffice
                result = subprocess.run([
                    "libreoffice",
                    "--headless",
                    "--convert-to", "html",
                    "--outdir", tmpdir,
                    input_path
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                if result.returncode != 0:
                    raise RuntimeError(f"LibreOffice failed: {result.stderr.decode()}")

                # Find generated HTML file
                html_file = next((f for f in os.listdir(tmpdir) if f.endswith(".html")), None)
                
                if not html_file:
                    raise FileNotFoundError("No HTML file generated by LibreOffice.")

                with open(os.path.join(tmpdir, html_file), "r", encoding="utf-8") as f:
                    html=  f.read()

            logger.info("[INFO] DOCX successfully converted to HTML using LibreOffice.")
            display(HTML(html))
#             print(html)

            section_tables = {}
    
            for _, sec_title, start_page, end_page in sections_with_pages:
                tables = self.extract_tables_from_html_by_page_range(html, start_page, end_page)
#                 print(tables)
                for i in tables:
                    display(HTML(i))
                    section_tables[sec_title] = tables
    
            return section_tables

        except Exception as e:
            logger.error(f"[ERROR] Failed to process DOCX to section HTML: {e}")
            return {}