import re
from typing import List, Dict, Any
#necessary imports 
from datetime import datetime
import traceback
import dataikuapi
import io

import base64
import uuid
# import from GLOBAL SHARED CODE
from utils import connection 
# imports from library 
import re
from utilities.variables import RD_PROJECT_NAME
from utilities.variables import SECRET_NAME , TOKEN_KEY
from utilities.logging_config import logging
# from soa_extraction.crf_extraction import HistoricalCRF
# import HistoricalCRF
import traceback
import os
import io
import logging
import re
from uuid import uuid4
from typing import List, Dict, Any

import traceback

import fitz  # PyMuPDF (not actually used here but could be if needed)
import pdfplumber


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)




class GenericFormFieldExtractor:
    """
    Generic extractor for any fields from clinical trial forms.
    No hardcoded field-specific logic - works with any field names.
    """
    
    def extract_fields(self, text: str, field_names: List[str]) -> Dict[str, Any]:
        """
        Extract any specified fields from form text.
        
        Args:
            text: The form text (single page or multiple pages)
            field_names: List of field names to extract (e.g., ['Date of Birth', 'Sex at Birth', 'Age'])
        
        Returns:
            Dictionary with field names as keys and their values/options
        """
        results = {}
        lines = text.strip().split('\n')
        
        for field_name in field_names:
            field_data = self._extract_field(field_name, lines)
            results[field_name] = field_data
        
        return results
    
    def _extract_field(self, field_name: str, lines: List[str]) -> Dict[str, Any]:
        """
        Extract a single field and its associated data.
        Returns field number and any values/options found.
        """
        field_lower = field_name.strip().lower()
        
        for i, line in enumerate(lines):
            # Check if this line contains the field name
#             print(line)
            if field_lower in line.lower():
                field_info = {
                    'field_name': field_name,
                    'field_number': None,
                    'line_text': line.strip(),
                    'values': [],
                    'options': []
                }
                
                # Extract field number (usually at the end of the line)
                field_num_match = re.search(r'\s+(\d+)\s*$', line)
#                 print(line,field_num_match)
                if field_num_match:
                    field_info['field_number'] = field_num_match.group(1)
                
                # Look at subsequent lines for options/values
                field_info['options'] = self._extract_options(lines, i)
                
                # Extract selected/checked values (lines with numbers at the end)
                field_info['values'] = self._extract_selected_values(lines, i)
                
                return field_info
        
        return None
    
    def _extract_options(self, lines: List[str], start_idx: int, max_lines: int = 20) -> List[str]:
        """
        Extract all available options for a field.
        Options are typically indented text following the field name.
        """
        options = []
        
        for i in range(start_idx + 1, min(start_idx + max_lines, len(lines))):
            line = lines[i]
            
            # Stop if we hit another field (less indented text with content)
            if self._is_new_field(line):
                break
            
            # Check if line is an option (indented, has content)
            if self._is_option_line(line):
                option_text = self._clean_option_text(line)
                if option_text:
                    options.append(option_text)
        
        return options
    
    def _extract_selected_values(self, lines: List[str], start_idx: int, max_lines: int = 20) -> List[str]:
        """
        Extract selected/checked values (options with numbers indicating selection).
        """
        selected = []
        
        for i in range(start_idx, min(start_idx + max_lines, len(lines))):
            line = lines[i]
            
            # Stop if we hit another field
            if i > start_idx and self._is_new_field(line):
                break
            
            # Check if this line has a selection indicator (number at end or marked)
            if self._has_selection_indicator(line):
                value_text = self._extract_value_text(line)
                if value_text:
                    selected.append(value_text)
        
        return selected
    
    def _is_new_field(self, line: str) -> bool:
        """Check if line starts a new field."""
        # New fields typically start with less indentation and have substantial text
        stripped = line.strip()
        if not stripped:
            return False
        
        # Check indentation - new fields usually have 5-20 spaces
        leading_spaces = len(line) - len(line.lstrip())
        
        # New field if: moderate indentation, has letter start, and reasonable length
        if 5 <= leading_spaces <= 25 and stripped[0].isupper() and len(stripped) > 3:
            # Not a new field if heavily indented (likely an option)
            if leading_spaces > 30:
                return False
            return True
        
        return False
    
    def _is_option_line(self, line: str) -> bool:
        """Check if line is an option/choice."""
        stripped = line.strip()
        if not stripped:
            return False
        
        # Options are usually indented more than fields
        leading_spaces = len(line) - len(line.lstrip())
        
        return leading_spaces >= 20 and len(stripped) > 1
    
    def _clean_option_text(self, line: str) -> str:
        """Clean option text by removing numbers and extra whitespace."""
        text = line.strip()
        # Remove trailing numbers (field reference numbers)
        text = re.sub(r'\s+\d+\s*$', '', text)
        return text.strip()
    
    def _has_selection_indicator(self, line: str) -> bool:
        """Check if line has a selection indicator (letter + number or just number at end)."""
        # Pattern: text followed by single letter and/or number at end
        # Examples: "Male 4", "Y 1", "M 3"
        return bool(re.search(r'[A-Z]\s+\d+\s*$', line))
    
    def _extract_value_text(self, line: str) -> str:
        """Extract the value text from a selected option."""
        text = line.strip()
        # Remove the selection indicator (letter and/or number at end)
        text = re.sub(r'\s+[A-Z]?\s*\d+\s*$', '', text)
        return text.strip()
    
    def extract_all_fields(self, text: str) -> List[Dict[str, Any]]:
        """
        Auto-detect and extract ALL fields from the form.
        Useful when you don't know field names in advance.
        """
        all_fields = []
        lines_old = text.strip().split('\n')
#         print("this is line : ",lines_old)
        lines = []
        rec = 0
        for u,each_line in enumerate(lines_old):
            if "Generated On" in each_line:
                rec = u
                break
        if rec > 0:
            
            lines = lines_old[rec:]
        else:
            lines = lines_old
        
            
        
        for i, line in enumerate(lines):
            
#             if self._is_new_field(line):

            clean = line.strip()

#                 print("clean line",clean)
            # pattern = r'^(?:\d+\.\s*(.+)|([A-Za-z].*))$'
            pattern =r'^(?:\d+\s*[\.\)]\s*(.+)|(.+))$'

            m = re.match(pattern, clean)
            if m:
                # m.group(1) is the text after "1."
                # m.group(2) is the full unnumbered text 
                field_name=  (m.group(1) or m.group(2)).strip()


            print("ext field:", field_name)

            # Ignore if ends with '?'
            if field_name and '?' not in field_name[-5:]:
                field_name_clean = field_name.rstrip('?').strip()
            else:
                field_name_clean = field_name.strip()

            if field_name_clean and len(field_name_clean) > 2:
                field_data = self._extract_field(field_name_clean, lines)
                if field_data:
                    all_fields.append(field_data)

#         for i, line in enumerate(lines):
            
#             if self._is_new_field(line):
#                 # Extract field name
           
# #                 field_name = re.sub(r'\s+\d+\s*$', '', line.strip())
                
# #                 field_name = re.sub(r'^\s*\d+\.\s*(.*)', '', line.strip())

#                 print("ext field :",field_name)
#                 if field_name and '?' not in field_name[-5:]:  # Skip question marks
#                     field_name_clean = field_name.rstrip('?').strip()
#                 else:
#                     field_name_clean = field_name.strip()

#                 if field_name_clean and len(field_name_clean) > 2:
#                     field_data = self._extract_field(field_name_clean, lines)
#                     if field_data:
#                         all_fields.append(field_data)
        
        return all_fields



class HistoricalCRF:
    """
    Class to extract structured data from historical CRF PDFs stored in a Dataiku managed folder.
    """

    def __init__(self, client, proj, chunk_size: int = 1000):
        """
        Initialize the HistoricalCRF extractor.

        :param client: Dataiku API client
        :param proj: Dataiku project handle
        :param chunk_size: (Optional) Number of characters per chunk for downstream processing
        """
        self.proj = proj
        self.client = client
        self.chunk_size = chunk_size

        self.variables = proj.get_variables().get("local", {})
        self.s3_folder_dataset_id = self.variables.get("file_upload")
        if not self.s3_folder_dataset_id:
            raise ValueError("Missing 'file_upload' folder in project variables.")

        self.input_folder = proj.get_managed_folder(self.s3_folder_dataset_id)
        self.files = self.input_folder.list_contents().get("items", [])
        self.toc_page_limit = 20
        self.config = self.variables

        logger.info(f"📂 Found {len(self.files)} files in managed folder: {self.s3_folder_dataset_id}")
        
#     import pdfplumber
#     import re
#     from collections import defaultdict

    def extract_fields_from_page(self,page):
        words = page.extract_words()

        # Step 1: group words into rows based on y-position (tolerance ~2px)
        grouped = defaultdict(list)
        for w in words:
            y = round(w["top"] / 2)  # normalize row grouping
            grouped[y].append(w)

        results = []

        for y, row_words in sorted(grouped.items()):
            # sort words left to right
            row_words = sorted(row_words, key=lambda w: w["x0"])

            # Step 2: Detect if row contains a field number
            first = row_words[0]["text"]

            if not re.fullmatch(r"\d+", first):
                continue  # skip non-field rows

            field_number = int(first)

            # Step 3: Right-most token = OID (but filter out noise)
            rightmost = row_words[-1]["text"]

            # skip footers
            if rightmost.isdigit() or rightmost.lower() == "of":
                continue

            # must contain letters to be a valid OID
            if not re.search(r"[A-Z]", rightmost):
                continue

            results.append({
                "field_number": field_number,
                "field_oid": rightmost
            })

        return results


    def historical_mapping(self, file_path: str,file_id) -> List[Dict[str, Any]]:
        """
        Process a single PDF file, extracting headers and fields into structured data.

        :param file_path: Path of the file inside the managed folder.
        :return: List of dictionaries containing structured CRF data.
        """
        response = []
        oid_response = []
        back_track = []
        previous_pointer = 0
        prev_track = []
        try:
            with self.input_folder.get_file(file_path) as stream:
                file_bytes = stream.raw.data

            pdf_file_like = io.BytesIO(file_bytes)
            import pymupdf4llm
            import fitz
            pdf_document = fitz.open(stream = file_bytes, filetype = 'pdf')
            with pdfplumber.open(pdf_file_like) as pdf:
                total_pages = len(pdf.pages)
                snowflake_conn = self.config.get("snowflake_connection_string")
        
        
                #input_folder =  project.get_managed_folder(proj_vars.get("ecs").get("file_upload"))
                table_file_upload = self.config.get("ecs", {}).get("ecs_file_upload", {})
                field_names_list= []
                page_list = []
                page_idx = 0
                
                
                
                for page_num, page in enumerate(pdf.pages[1:], start=1):
                    try:
                        page_text = page.extract_text(layout=True)
                        
                        
                        if page_num % 70 == 0 or page_num == total_pages:
                            percent = (page_num / total_pages) * 100

                            # dynamic description logic
                            if percent < 10:
                                desc = "Initializing digitization..."
                            elif percent < 40:
                                desc = "Extracting text from pages..."
                            elif percent < 70:
                                desc = "Processing extracted content..."
                            elif percent < 90:
                                desc = "Structuring and cleaning data..."
                            elif percent < 100:
                                desc = "Finalizing digitization..."
                            else:
                                desc = "Digitization completed"

                            update_query = f"""
                                UPDATE {table_file_upload}
                                SET 
                                    "digitization_percent" = {percent},
                                    "description" = '{desc}'
                                WHERE "crf_file_id" = '{file_id}';
                            """

                            self.client.sql_query(
                                query=update_query,
                                connection=snowflake_conn,
                                post_queries=["COMMIT"]
                            )


                        
                        if not page_text:
                            logger.debug(f"⚠️ Skipping empty page {page_num} in {file_path}")
                            continue

                        if "field name" in page_text.lower():
                            set_axis = True
                        
                            FIELD_NUM_X_MAX = 150       # field number left column threshold
                            FIELD_OID_X_MIN = 300       # include-field-OID right column threshold

                            results_oids = []
                            current_field = None
                        
                            words = page.extract_words()
                            
  
                            for indx, w in enumerate(words):
                                
                                text = w["text"]
                              
                                if "include" == text.lower():
                                    
                                    FIELD_OID_X_MIN = w["x0"] - 50
                                    break
                               
                                
                            for indx, w in enumerate(words):
                                
                                text = w["text"]
                                if "field" == text.lower():
                                    
                                        
                                    FIELD_NUM_X_MAX = w["x0"] - 10
                                    break
                                    
                                    
#                             print("FIELD_OID_X_MIN,FIELD_NUM_X_MAX--->",FIELD_OID_X_MIN,FIELD_NUM_X_MAX)
                                
                            for w in words:
                                
                                text = w["text"]
                                x0 = w["x0"]

                                
                                if re.fullmatch(r"\d+", text) and x0 < FIELD_NUM_X_MAX:
                                    
                                    current_field = {
                                        "field_number": int(text),
                                        "field_name": ""
                                    }
                                    results_oids.append(current_field)
                                    continue

                                # 2️⃣ Capture Include Field OID (rightmost column)
                                if x0 > FIELD_OID_X_MIN and re.fullmatch(r"[A-Z0-9_]+", text):
                                    if text.isdigit():
                                        continue

                                    # ignore footer tokens like "of"
                                    if text.lower() == "of":
                                        continue

                                    # match only true OID tokens (must contain at least 1 letter)
                                    if not re.search(r"[A-Z]", text):
                                        continue
                                        
                                    if current_field:
                                        current_field["field_name"] += text
                                    continue
                                    
                                    
                            
                                    

                            result = self.extract_oids(page_text, file_path,results_oids)
                            
                            if result:
                           
                                oid_response.append(result)
                            
                            continue
                            
                        
                            
                        result = self._process_page(page_text, file_path)
              
                        if result:
                           
                            response.append(result)
#                             page_list.append(page_idx)
#                             page_idx +=1
                           

                    except Exception as page_error:
                        logger.error(f"❌ Error processing page {page_num} in {file_path}: {page_error}")
                        t = traceback.format_exc()
                        return {"message":f"error caused ue to {t}"}

        except Exception as file_error:
            logger.error(f"❌ Error opening or processing file {file_path}: {file_error}")
            t = traceback.format_exc()
            return {"message":f"error caused ue to {t}"}

        
        return response,oid_response
    
    def extract_oids(self,page_text: str, file_path: str,results_oids: list) -> Dict[str,Any]:
        
        
        
        # Fix broken OIDs: join lines where second line is a single letter
       

        lines = page_text.split("\n")
        
        
#         print(page_text)
        pattern = r'(?m)^\s*(\d+)\s+([A-Z0-9_]+)\s*\$?\d*'
        

        matches = re.findall(pattern, page_text)
        
        field_names_list = results_oids
        
#         field_names_list = [{"field_number": int(num), "field_name": name} for num, name in matches]
#         print(field_names_list)
#         pattern = r'(?m)^\s*\d+\s+([A-Z0-9_]+)\s*\$?\d*'
    
#         field_names_list = re.findall(pattern, page_text)
        
        #print(field_names_list)
        form_started = False
        form_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Stop capturing when Folder or Generated appears
            if  line.lower().startswith("generated") or line.lower().startswith("source"):
                break

            # Start capturing when "Form:" appears
            if line.lower().startswith("form:"):
                form_started = True
                cleaned = line.split(":", 1)[1].strip()
                form_lines.append(cleaned)
                continue

            # If form capturing already started, keep appending
            if form_started:
                form_lines.append(line)
                continue

        # Final merged form name
        header_text = " ".join(form_lines).strip()
        
        if field_names_list and header_text:
            return {
                
                "template_name": os.path.basename(file_path),
                "path": file_path,
                "id": str(uuid4()),
                "source_data": {
                    "assessments": header_text,
                    "fields_oid": field_names_list,
                },
            }

        return None
        
    def _process_page(self, page_text: str, file_path: str) -> Dict[str, Any]:
        """
        Process a single page's text, extracting header and field-value pairs.

        :param page_text: Extracted text from a PDF page
        :param file_path: The path of the file (for reference)
        :return: A dictionary with structured data or None if nothing found
        """
        
        #print(page_text)
        
        # Initialize extractor
        extractor = GenericFormFieldExtractor()

        # MAIN USE CASE: Auto-extract ALL fields from the document
        

        all_fields = extractor.extract_all_fields(page_text)

        
        final_fields = []
        for field in all_fields:
            if  field['field_number']:
                final_fields.append({
                    "field_name" : field['field_name'],
                    "field_number" : field['field_number']
                })
               

        
    
    
        lines = page_text.split("\n")
        header_lines = []
        field_value_map = {}
        current_field = None
        in_field_section = False
       
        
       
        field_pattern = re.compile(r'^(?P<field>.+?)(?:\s{2,})(?P<value>.+?)\s*$', re.MULTILINE)


        value_continuation_pattern = re.compile(r"^(?!\s)(?!.*\s$)(?P<value>.+)$")
        
        form_started = False
        form_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Stop capturing when Folder or Generated appears
            if  line.lower().startswith("generated") or line.lower().startswith("source"):
                break

            # Start capturing when "Form:" appears
            if line.lower().startswith("form:"):
                form_started = True
                cleaned = line.split(":", 1)[1].strip()
                form_lines.append(cleaned)
                continue

            # If form capturing already started, keep appending
            if form_started:
                form_lines.append(line)
                continue

        # Final merged form name
        header_text = " ".join(form_lines).strip()
        
        if final_fields and header_text:
            
            return {
                
                "template_name": os.path.basename(file_path),
                "path": file_path,
                "id": str(uuid4()),
                "source_data": {
                    "assessments": header_text,
                    "fields": final_fields,
                },
            }

        return None


def extract_crf_new(file_path,client,project,file_id):
    """
    Input Args:
        file_path: str
        
    Response:
        result : dict
    """
    try:
        logging.info("Intializing client for file_upload function ")
       
        DATAIKU_HOST , API_SECRET_KEY  = connection.get_dataiku_host_and_api_key(RD_PROJECT_NAME,SECRET_NAME,TOKEN_KEY)
        
        client = dataikuapi.DSSClient(DATAIKU_HOST, API_SECRET_KEY)
        project = client.get_project(RD_PROJECT_NAME)
        proj_vars = project.get_variables()["local"]
        
        snowflake_conn = proj_vars.get("snowflake_connection_string")
        
        obj = HistoricalCRF(client , project)
        final_list = []
        response,response_oid = obj.historical_mapping(file_path,file_id)
        
        from collections import defaultdict
        import copy
        def merge_sections_per_file(results,field_name):
            merged = defaultdict(dict)

            for item in results:
                file_path = item["path"]
                assessment = item["source_data"]["assessments"]

                if assessment not in merged[file_path]:
                    merged[file_path][assessment] = copy.deepcopy(item)
                else:
                    # merge fields for same file + same assessment
                    merged[file_path][assessment]["source_data"][field_name] += item["source_data"][field_name]


            # flatten structure
            final = []
            for file_assessments in merged.values():
                final.extend(file_assessments.values())

            return final

        ans = merge_sections_per_file(response,"fields")
        ans_oid = merge_sections_per_file(response_oid,"fields_oid")
        
#         print(ans)
#         print(ans_oid)
        merged_list = []
        for d1 in ans:
            matched = False

            for d2 in ans_oid:
                if (
                    d1["template_name"] == d2["template_name"]
                    and d1["source_data"]["assessments"] == d2["source_data"]["assessments"]
                ):
                    
                    fields = d1["source_data"]["fields"]
                    fields_oid = d2["source_data"]["fields_oid"]

                    
                    for i, field in enumerate(fields):
                        found_oids_name = None
                        for each_oids in fields_oid:
#                             print(int(each_oids["field_number"]),int(field["field_number"]))
                            if int(each_oids["field_number"]) == int(field["field_number"]):
                                found_oids_name = each_oids["field_name"]
                            
                        
                        field["field_oid"] = found_oids_name

                    merged_list.append(d1)
                    matched = True
                    break  # stop checking after first match

            if not matched:
                # keep original entry unchanged
                merged_list.append(d1)

        # --- Result ---
#         import pprint
#         pprint.pprint(merged_list)
        
        for resp in merged_list:
            form_name = resp['source_data']['assessments']
            match = re.search(r'Form[:\s]*(.*)', form_name)
            if match:
                form_name = match.group(1)
            for field in resp['source_data']['fields']:
                
                field_name = field['field_name']
                field_oid = field['field_oid']
                #field_oid = field["field_oid"]
                final_list.append({
                    "form_name": form_name,
                    "field_name": re.split(r'\t|\s{2,}', field_name.strip())[0],
                    "field_oid" : field_oid
                    #"field_oid" : field_oid
                })

        #  Deduplicate based on both form_name and field_name
        seen = set()
        deduped_list = []
        for item in final_list:
            key = (item["form_name"].strip().lower(), item["field_name"].strip().lower())
            if key not in seen:
                seen.add(key)
                deduped_list.append(item)

        return {
            "result": deduped_list
        }

    except:
        t = traceback.format_exc()
        logging.error(f"Error caused due to {t}")
        return {"message": f"Error caused due to {t}"}

