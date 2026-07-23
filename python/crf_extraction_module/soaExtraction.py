import dataikuapi
from typing import Dict, Any
import sys
import time 
import random
import os
import io
import fitz  # PyMuPDF
import pdfplumber
#from utilities import creds
#from langgraph_utils.Info_extractor import InfoExtractorAgent
# from langgraph_utils.chat_history import SnowflakeChatMessageHistory
import json
#from langgraph_utils.file_parser import FileParser
#from langgraph_utils.digitization import main_handler
import uuid
#from langgraph_utils import creds
#from langgraph_utils.variables import PROJECT_NAME, SECRET_NAME, TOKEN_KEY
from utils.connection import get_dataiku_client_and_project
from IPython.core.display import display, HTML
import logging
import tempfile
import re
import pymupdf4llm
from dataikuapi import DSSClient
from dataikuapi.dss.project import DSSProject
import pandas as pd
from soa_extraction.llm_functions import LLMFuntions
from  soa_extraction.spire_module import SpireExtractor
import ast
from uuid import uuid4
from datetime import datetime
# import from GLOBAL SHARED CODE
from utils import connection 
# imports from library 
from utilities.creds import RD_PROJECT_NAME
from variables import SECRET_NAME , TOKEN_KEY
from utilities.logging_config import logging

DATAIKU_HOST , API_SECRET_KEY  = connection.get_dataiku_host_and_api_key(RD_PROJECT_NAME,SECRET_NAME,TOKEN_KEY)
        
client = dataikuapi.DSSClient(DATAIKU_HOST, API_SECRET_KEY)
proj = client.get_project(RD_PROJECT_NAME)



class SOAExtraction:
    
    def __init__(self,client,proj, chunk_size=1000):
        self.proj = proj
        self.client = client
        self.s3_folder_dataset_id = proj.get_variables()['local'].get("crf").get("crf_temp_upload_folder")
        #self.s3_folder_dataset_id = proj.get_variables()['local'].get("R_and_D_folder")
        print(self.s3_folder_dataset_id)
        self.input_folder = proj.get_managed_folder(self.s3_folder_dataset_id)
        self.files = self.input_folder.list_contents()["items"]
        self.toc_page_limit = 20
        self.config = proj.get_variables()["local"]


        print(self.files) 
    
    def is_valid_section(self,title):
        lower = title.lower()
        return not any(keyword in lower for keyword in [
            "table of", "list of tables", "list of figures", "figure", "table"
        ])

        
    def extract_bookmarked_sections(self,pdf_path, num_pages):
        
        with self.input_folder.get_file(pdf_path) as stream:
            file_bytes = stream.raw.data
            
        doc = fitz.open(stream = file_bytes, filetype = 'pdf')
        toc_entries = doc.get_toc(simple=True)
        fallback_sections = []

        section_pattern = re.compile(r'^((?:\d+\.)+\d*\.?)[\s:\-–]+(.*)')

        for level, title, page in toc_entries:
            if not self.is_valid_section(title):
                continue

            match = section_pattern.match(title.strip())
            if match:
                section_number = match.group(1).strip()
                section_title = match.group(2).strip()
                start_page = min(page, num_pages)
                fallback_sections.append((section_number, section_title, start_page))

        return fallback_sections
    
  
    def normalize_toc(self,text):
        return ' '.join(text.lower().split())

    def is_toc_line(self, text):
        """
        Identify Table of Contents (TOC) lines like:
            '1.1 Introduction .......... 3'
            'Glossary of Terms     45'
            'Appendix A - References ...... 112'
            'Table 1 Study Objectives .......... 10'
            'Table 2: Drug Summary     15'

        Returns True if the line matches a typical TOC pattern.
        """
        text = text.strip()

        # Acceptable separator: dots, dashes, en/em-dashes, or long whitespace
        sep_pattern = r"(?:\s?[.\-–—]{2,}\s?|\s{4,})"

        # Pattern 1: Numbered section + title + separator + page number
        pattern_numbered = re.compile(
            rf"^\s*(\d+(?:\.\d+)*)(?:\s+)(.+?){sep_pattern}(\d{{1,4}})\s*$"
        )

        # Pattern 2: Title + separator + page number (non-numbered entries)
        pattern_unnumbered = re.compile(
            rf"^([A-Za-z][A-Za-z\s,&\-():]+?){sep_pattern}(\d{{1,4}})\s*$"
        )

        # Pattern 3: Title and page number separated by multiple spaces only (no leader chars)
        pattern_whitespace_only = re.compile(
            r"^(.+?)\s{4,}(\d{1,4})$"
        )

        # Pattern 4: Table entries like "Table 1: Description .... 12"
        pattern_table_entry = re.compile(
            rf"^\s*Table\s+\d+[:\-]?\s+.+?{sep_pattern}(\d{{1,4}})\s*$",
            re.IGNORECASE
        )

        return any([
            pattern_numbered.match(text),
            pattern_unnumbered.match(text),
            pattern_whitespace_only.match(text),
            pattern_table_entry.match(text)
        ])

    
    #------ To detect the page range of table of content start : end ------
    
    def detect_toc_page_range(self,doc, max_scan_pages=25, min_toc_lines_threshold=3):
        
        
        def normalize_section_key(section_str: str):
            clean_str = section_str.strip('.').strip()
            return tuple(int(part) for part in clean_str.split('.') if part)

        
        
        def merge_and_sort_section_tuples(list1, list2):
            combined = list1 + list2

            # Avoid duplicates based on normalized section number
            seen = {}
            for entry in combined:
                key = normalize_section_key(entry[0])
                if key not in seen:
                    seen[key] = entry  # Preserve first occurrence

            # Sort by page number (3rd element of tuple)
            sorted_items = sorted(seen.values(), key=lambda x: x[2])
            return sorted_items

        
        def normalize_toc(text):
            return ' '.join(text.lower().split())
        
        def is_toc_heading(line):
            norm = normalize_toc(line)
            return norm in {
                'table of contents',
                'toc',
                'table of content'
            }
        
        def merge_lines(lines, max_merge=3):
            merged = []
            for i in range(len(lines)):
                group = ""
                for j in range(max_merge):
                    if i + j < len(lines):
                        group += lines[i + j].strip() + " "
                        yield group.strip()
        
        toc_start, toc_end = None, None
        consecutive_toc_pages = 0
        
        for i in range(min(max_scan_pages, len(doc))):
            text = doc[i].get_text()
#             print(text)
            lines = text.split('\n')
            # Heuristic: Look for TOC heading
            if toc_start is None and any(is_toc_heading(l) for l in lines):
                
                toc_start = i

            # Try merged line groups to detect TOC entries
            toc_lines = []
            for candidate in merge_lines(lines, max_merge=3):
                if self.is_toc_line(candidate):
                    
                    toc_lines.append(candidate)

            if toc_start is not None:
                if len(toc_lines) >= min_toc_lines_threshold:
                    toc_end = i
                    consecutive_toc_pages += 1
                else:
                    
                    break
            elif len(toc_lines) >= min_toc_lines_threshold:
                toc_start = i
                toc_end = i
                consecutive_toc_pages = 1

        if toc_start is not None and toc_end is not None:
            print(f"\nTOC detected from page from regex {toc_start} to {toc_end}")
        else:
            print("\n TOC not found")

        return toc_start, toc_end
    
    
    def extract_sections(self,text):
        
        try:
            pattern = r'''
            ^\s*(?P<number_plain>\d+(\.\d+)*\.?)\s+(?P<name_plain>Schedule of (Assessments|Activities))$
            |
            ^\*{0,2}(?P<number>\d+(\.\d+)*\.?)\*{0,2}\s+\*\*(?P<name>.*?)\*\*
            |
            ^\*\*(?P<number2>\d+(\.\d+)*\.?)\s+(?P<name2>.+?)\*\*$
            |
            ^\*\*_(?P<number3>\d+(\.\d+)*\.?)_\*\*\s+\*\*_(?P<name3>.*?)_\** 
            |
            ^\*\*_(?P<number4>\d+(\.\d+)*\.?)\s+(?P<name4>.+?)_\*\*
            |
            ^\*\*_?(?P<table_md>Table\s+\d+)_?\*\*\s*:?\s*\*\*_?(?P<table_title_md>.*?)_?\*\*
            |
            ^\*\*_?(?P<figure_md>Figure\s+\d+)_?\*\*:?\s+\*\*_?(?P<figure_title_md>.*?)_?\*\*
            |
            \s{1,}\#?\s*\*\*(?P<appendix_md>Appendix\s+\d+)\*\*\s{1,}\*\*(?P<appendix_title_md>.+?)\*\*

            '''

            matches = re.finditer(pattern, text, re.MULTILINE | re.VERBOSE)
            sections = []

            for match in matches:
                number = (
                    match.groupdict().get('number_plain') or
                    match.groupdict().get('number') or
                    match.groupdict().get('number2') or
                    match.groupdict().get('number3') or
                    match.groupdict().get('number4') or
                    match.groupdict().get('table_md') or
                    match.groupdict().get('figure_md') or
                    match.groupdict().get('appendix_md')
                )
                
                name = (
                    match.groupdict().get('name_plain') or
                    match.groupdict().get('name') or
                    match.groupdict().get('name2') or
                    match.groupdict().get('name3') or
                    match.groupdict().get('name4') or
                    match.groupdict().get('table_title_md') or
                    match.groupdict().get('figure_title_md') or
                    match.groupdict().get('appendix_title_md')
                )
                print("-------------",number,name)
                if number is not None and isinstance(name, str):
                    sections.append((number.strip(), name.strip()))
            return sections

        except Exception as ex:
            print(f"Error while extracting sections from input text: {text}")
            raise Exception(f"Error while extracting sections from input text: {text}")

    
    def extract_section_with_hash(self,text):
        try:
            # Regex pattern for section starting with #
            pattern = r'^\s*#{1,3}\s*(\d+(\.\d+)*\.?)\s+(.+?)\s*$'

            # Find all matches
            matches = re.finditer(pattern, text, re.MULTILINE)

            sections = []
            for match in matches:
                number = match.group(1)
                name = match.group(3)
                if number is not None and isinstance(name, str):
                    sections.append((number, name.strip()))

            return sections
        except Exception as ex:
            raise Exception(f"Error while extracting section for input text: {text}")
            


    def custom_sort_key(self, item):
        
        section_key, section_value = item

        # Try to match a purely numeric section like '6.2.1'
        numeric_match = re.match(r'^(\d+(\.\d+)*)$', section_key[1])
        if numeric_match:
            numeric_parts = [int(part) for part in section_key[1].split('.')]
            
            # Return a consistent type: section_value, and a tuple of ints
            return (section_value, tuple(numeric_parts))

        # Otherwise it's an alphanumeric like 'Appendix 1'
        alphanumeric_parts = re.findall(r'[A-Za-z]+|\d+', section_key[1])
        alphanumeric_parts = [part.lower() for part in alphanumeric_parts]  # normalize
        
        return (section_value + 1000, tuple(alphanumeric_parts))


        
    def normalize_section_key(self,section_str: str):
        alphanumeric_parts = re.findall(r'[A-Za-z]+|\d+', section_str)
        
        if(alphanumeric_parts):
            if alphanumeric_parts[0] in ['Table','table']:
                section_str = '99.'+ alphanumeric_parts[1]
            elif alphanumeric_parts[0] in ['Figure','figure']:
                section_str = '100.'+ alphanumeric_parts[1]
            elif alphanumeric_parts[0] in  ['Appendix','appendix']:
                section_str = '101.'+ alphanumeric_parts[1]
                
        clean_str = section_str.strip('.').strip()
        return tuple(int(part) for part in clean_str.split('.') if part)
    

    #Sort and merge tuples based on normalized section number
    def merge_and_sort_section_tuples(self,list1, list2):
        
        combined = list1 + list2
        print("combined",combined)
       
        seen = {}
        for entry in combined:
            key = self.normalize_section_key(entry[0])
            
            if key not in seen:
                seen[key] = entry  # Preserve first occurrence with original formatting

        # Sort by normalized section key
        
        sorted_items = [seen[k] for k in sorted(seen.keys())]
        return sorted_items
    
    def assign_end_pages(self,final_sections, total_pages):
        try:
            if not final_sections:
                return []

            for i in range(len(final_sections) - 1):
                next_section_start_page = final_sections[i + 1][2]
                final_sections[i] = final_sections[i] + (next_section_start_page,)

            if final_sections:
                final_sections[-1] = final_sections[-1] + (total_pages,)
            return final_sections
        except Exception as ex:
            print(f"Error in assign_end_pages")
            raise Exception("Error: in assign_end_pages")
            
    def create_section_dataframe(self,sections_with_pages):
        """Converts the section data to a pandas DataFrame and adds hierarchy levels."""
        try:

            # Convert to a pandas DataFrame
            df = pd.DataFrame(sections_with_pages, columns=['Section Number', 'Section Name', 'Start Page', 'End Page'])

            def get_section_hierarchy(section_number):
                """Splits the section number into parts to determine hierarchy level."""
                return section_number.strip('.').split('.')

            # Add a hierarchy level column
            df['Hierarchy'] = df['Section Number'].apply(get_section_hierarchy).apply(len)

            # Sort the DataFrame by hierarchy and section number
            df = df.sort_values(by=['Hierarchy', 'Section Number'])

            # Reset index for ease of processing
            df = df.reset_index(drop=True)

            return df
        except Exception as ex:
            print(f"Error in create_section_dataframe " + str(ex))
            raise Exception(f"Error in create_section_dataframe " + str(ex))

    
    def adjust_end_pages_for_hierarchy(self,df):
        """Adjusts the end pages for sections based on their hierarchy."""
        try:

            # Iterate from the deepest hierarchy level to the top
            for level in sorted(df['Hierarchy'].unique(), reverse=True):
                # Filter sections at the current level
                current_level_sections = df[df['Hierarchy'] == level]

                # Process only if not the deepest level
                if level > 1:
                    # Parent level
                    parent_level = level - 1
                    # Get sections at the parent level
                    parent_sections = df[df['Hierarchy'] == parent_level]

                    for parent_idx, parent_row in parent_sections.iterrows():
                        parent_number = parent_row['Section Number']

                        # Find all subsections that start with the parent section number + '.'
                        subsections = df[df['Section Number'].str.startswith(parent_number + '.')]

                        if not subsections.empty:
                            # Find the maximum end page among the subsections
                            max_end_page = subsections['End Page'].max()

                            # Update the parent section's end page if it's less than max_end_page
                            if parent_row['End Page'] < max_end_page:
                                df.at[parent_idx, 'End Page'] = max_end_page
            return df
        except Exception as ex:
            print("Error in : 'adjust_end_pages_for_hierarchy'" + str(ex))
            raise Exception("Error in : 'adjust_end_pages_for_hierarchy'" + str(ex))
            
    
        
    def file_extractor(self,file_name,protocol_id,user_id):
        start_time = time.time()
        table_ctl_protocol = self.config.get("crf", {}).get("crf_tables", {}).get("ctl_protocol")
        llm_token_usage_log = self.config["common_tables"]["llmtokenusagelog"]
        
        
        file_path = None
        for f in self.files:
            if file_name in f['path']:
                file_path = f['path']
                break

        if not file_path:
            raise FileNotFoundError("No matching file found in managed folder.")
        
        with self.input_folder.get_file(file_path) as stream:
            file_bytes = stream.raw.data
        
        
        pdf_document = fitz.open(stream = file_bytes, filetype = 'pdf')
        num_pages = pdf_document.page_count
        print(f"No. of Pages {num_pages}")
#         pdf_document.close()
        random_int = random.randint(5,10)
        sql_query = f"""UPDATE {table_ctl_protocol}
                        SET "digitization_percent" = '{random_int}',"description" = 'Digitization process getting started'
                        WHERE "protocol_id" = '{protocol_id}';
                
                            """
        logging.info(f"executing sql query:{sql_query}")
        client.sql_query(query =  sql_query, connection = proj.get_variables()['local'].get("snowflake_connection_string"),  post_queries=["COMMIT"])
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
            
        md_text_pages = []
        openai_toc_found = False
        openai_toc_entries = []
        bookmarked_sections = []
        toc_start_page = 0
        toc_end_page = 0
        df = None
        sections_with_pages = None
        doc_id= ""
        llmOperations = LLMFuntions(self.client, self.proj)

        # Section detection from built-in TOC
        bookmarked_sections = self.extract_bookmarked_sections(file_path, num_pages)
        if bookmarked_sections:
            print(
                f"TOC detected with {len(bookmarked_sections)} sections. Skipping OpenAI TOC."
            )
           
        else:
            print(f"Unable to detect built-in TOC, Forming a new TOC.")
            
        for i in range(min(self.toc_page_limit, num_pages)):
            
            try:
                page_markdown = pymupdf4llm.to_markdown(pdf_document, pages=[i])
                toc , input_token_toc_present , output_token_toc_present = llmOperations.is_toc_present(page_markdown)
                
                if toc and toc_start_page == 0:
                    toc_start_page = i
                elif not toc and toc_start_page != 0 and toc_end_page == 0:
                    toc_end_page = i
                    break
            except Exception as e:
                print(f"Error processing TOC on page {i}: {e}")
        
        print(f"toc_start_page {toc_start_page}, toc_end_page {toc_end_page}")
        
        toc_start_fitz, toc_end_fitz = self.detect_toc_page_range(
            pdf_document, max_scan_pages=self.toc_page_limit
        )
        
        # --- Compute union of both results the toc page number we got from open ai and regex ---
        all_starts = [p for p in [toc_start_page, toc_start_fitz] if p is not None]
        all_ends = [p for p in [toc_end_page, toc_end_fitz+1] if p is not None]
        
        print(all_starts,all_ends)
        
        if all_starts and all_ends:
            toc_start_page = min(all_starts)
            toc_end_page = max(all_ends)
            
            
        else:
            toc_end_page = toc_start_page = None
            print("Could not detect complete TOC range")

        valid_sections_with_start_pages = []
        
        openai_toc_entries = []
        openai_sections_set = {
            (entry[0].strip(), entry[1].strip()) for entry in openai_toc_entries
        }
        
        
        print(f"Final TOC page range: {toc_start_page} to {toc_end_page}")

        for i in range(num_pages):
            if i < toc_end_page:                 
                md_text_pages.append("") # Append empty placeholder for ToC or skipped pages
            else:
                try:
                    page_markdown = pymupdf4llm.to_markdown(pdf_document, pages=[i])
                    mark = page_markdown
                    md_text_pages.append(page_markdown)
                except Exception as e:
                    print(f"Error processing page {i}: {e}")

        print(f"Level 1: AI TOC search complete")
        toc_time = time.time()
        random_int = random.randint(10,20)
        print("AI TOC time taken : ", toc_time - start_time)
        sql_query = f"""UPDATE {table_ctl_protocol}
                        SET "digitization_percent" = '{random_int}',"description" = 'Searching Table of Content'
                        WHERE "protocol_id" = '{protocol_id}';
                
                            """
        logging.info(f"executing sql query:{sql_query}")
        client.sql_query(query =  sql_query, connection = proj.get_variables()['local'].get("snowflake_connection_string"),  post_queries=["COMMIT"])
        
        for i, page_content in enumerate(md_text_pages):

            sections = self.extract_sections(page_content)

            hash_sections = self.extract_section_with_hash(page_content)
            sections.extend(hash_sections)

            for section in sections:
                section_number = section[0]
                section_name = section[1]
                section_number_cleaned = re.sub(r'(\d+)\.$', r'\1', section_number)
                
                flag , input_token_valid_section , output_token_valid_section =  llmOperations.is_valid_section_name(section_name)
                if flag :
#                     print(section_name)
                    matching_openai_section = next(
                        (
                            openai_name
                            for openai_num, openai_name in openai_sections_set
                            if (
                                openai_num == section_number
                                or openai_name == section_number_cleaned
                            )
                            and (
                                section_name.lower() in openai_name.lower()
                                or openai_name.lower() in section_name.lower()
                            )
                        ),
                        None,
                    )                   
                    if matching_openai_section:
                        section_name = matching_openai_section

                    valid_sections_with_start_pages.append(
                        (section_number, section_name, i + 1)
                    )
                else:
                    print(f"Invalid Section: {section_name}")

        print(f"Level 2: FITZ TOC search complete")
        fitz_toc_time = time.time()
        random_int = random.randint(20,30)
        print("FITZ TOC serch time ", fitz_toc_time - toc_time)
        sql_query = f"""UPDATE {table_ctl_protocol}
                        SET "digitization_percent" = '{random_int}' , "description" = 'Searching Table of Content'
                        WHERE "protocol_id" = '{protocol_id}';
                
                            """
        logging.info(f"executing sql query:{sql_query}")
        client.sql_query(query =  sql_query, connection = proj.get_variables()['local'].get("snowflake_connection_string"),  post_queries=["COMMIT"])
        all_sections = {}
        ai_sections_dict = {}
        formatted_toc_entries = []
        print("openai_toc_found",valid_sections_with_start_pages)
        if openai_toc_found:
            for entry in openai_toc_entries:
                try:
                    section_number = entry[0].strip()

                    section_name = entry[1].strip()
                    start_page = int(entry[2].strip())
                    if (section_name, section_number) not in ai_sections_dict:
                        formatted_toc_entries.append((section_number, section_name, start_page))
                        ai_sections_dict[(section_name, section_number)] = 1
                except ValueError:
                    print(f"Error formatting TOC entry: {entry}")
            for section in formatted_toc_entries:
                all_sections[(section[1], section[0])] = section[2]
                
        print(f"Level 3: TOC merging done")
        toc_merging_time = time.time()
        print("TOC merging_time:",toc_merging_time - fitz_toc_time)
        
        for section in valid_sections_with_start_pages:
            section_number = section[0]
            section_name = section[1]
            start_page = section[2]

            section_key = (section_name, section_number)
            if section_key not in all_sections:
                all_sections[section_key] = start_page

        # Create a dictionary of fallback sections with their start pages for easier lookup
        fallback_sections_dict = {
            (section[1], section[0]): section[2] for section in valid_sections_with_start_pages
        }

        # Calculate page difference per section
        page_differences = {}  # Track differences for each matching section
        for section in valid_sections_with_start_pages:
            section_name = section[1]
            section_number = section[0]
            if (section_name, section_number) in all_sections:
                difference = section[2] - all_sections[(section_name, section_number)]
                page_differences[(section_name, section_number)] = difference

        print(f"Level 4: TOC pages added")
        toc_page_add = time.time()
        random_int = random.randint(30,40)
        print("TOC pages added time :", toc_page_add - toc_merging_time)
        sql_query = f"""UPDATE {table_ctl_protocol}
                        SET "digitization_percent" = '{random_int}', "description" = 'Found Table of Content'
                        WHERE "protocol_id" = '{protocol_id}';
                
                            """
        logging.info(f"executing sql query:{sql_query}")
        client.sql_query(query =  sql_query, connection = proj.get_variables()['local'].get("snowflake_connection_string"),  post_queries=["COMMIT"])
        
        openai_only_sections = []
        
        for section in formatted_toc_entries:  # Entries from OpenAI
            section_name = section[1]
            section_number = section[0]

            if (section_name, section_number) in fallback_sections_dict:
                fallback_start_page = fallback_sections_dict.get((section_name, section_number))
                if fallback_start_page and fallback_start_page != section[2]:
                    difference = fallback_start_page - section[2]
                    adjusted_start_page = section[2] + difference

                else:
                    adjusted_start_page = section[2]
            else:
                adjusted_start_page = section[2]
                openai_only_sections.append((section[0], section[1], adjusted_start_page))


            # Update the all_sections dictionary with the adjusted start page
            all_sections[(section[1], section[0])] = adjusted_start_page

        print(f"Level 5: Final TOC formatting starts")
        random_int = random.randint(40,45)
        sql_query = f"""UPDATE {table_ctl_protocol}
                        SET "digitization_percent" = '{random_int}', "description" = 'Extracting Table of Content'
                        WHERE "protocol_id" = '{protocol_id}';
                
                            """
        logging.info(f"executing sql query:{sql_query}")
        client.sql_query(query =  sql_query, connection = proj.get_variables()['local'].get("snowflake_connection_string"),  post_queries=["COMMIT"])
        # sorted_sections = sorted(all_sections.items(), key=lambda x: (x[1], [int(part) for part in x[0][1].split('.')]))
        sorted_sections = sorted(all_sections.items(), key=self.custom_sort_key)
        final_sections = [(sec[0][1], sec[0][0], sec[1]) for sec in sorted_sections]

        print(f"------final_sections sections before merging are----- {final_sections}.")
        print(f"------bookmarked_sections sections before merging are----- {bookmarked_sections}.")
        final_sections_pass_through = self.merge_and_sort_section_tuples(final_sections,bookmarked_sections) ## remove sorting##
        print(f"-----final_sections_pass_through sections after merging---- {final_sections_pass_through}.")
        
        
        sections_with_pages = self.assign_end_pages(final_sections_pass_through, num_pages) ##testing using the merged result

        sections_with_pages = [entry for entry in sections_with_pages if entry[2] <= entry[3]]


        print(f"-----FINAL sections_with_pages are----- '{sections_with_pages}'")
        df = self.create_section_dataframe(sections_with_pages)
        df = self.adjust_end_pages_for_hierarchy(df)

        print(f"Level 6: Final TOC formatting ends {df}")
        random_int = random.randint(45,50)
        sql_query = f"""UPDATE {table_ctl_protocol}
                        SET "digitization_percent" = '{random_int}', "description" = 'Formatting Table of Content'
                        WHERE "protocol_id" = '{protocol_id}';
                
                            """
        logging.info(f"executing sql query:{sql_query}")
        client.sql_query(query =  sql_query, connection = proj.get_variables()['local'].get("snowflake_connection_string"),  post_queries=["COMMIT"])
        
        
        file_type = file_name.split("/")[-1].split(".")[-1]
        
        print("file_type",file_type)
        spire_SOA_extraction = SpireExtractor(self.client,self.proj)
        
        try:
            random_int = random.randint(50,60)
            sql_query = f"""UPDATE {table_ctl_protocol}
                            SET "digitization_percent" = '{random_int}' , "description" = 'Formatting Table of Content'
                            WHERE "protocol_id" = '{protocol_id}';

                                """
            logging.info(f"executing sql query:{sql_query}")
            client.sql_query(query =  sql_query, connection = proj.get_variables()['local'].get("snowflake_connection_string"),  post_queries=["COMMIT"])
        
            if final_sections_pass_through:
                section_html_dict = {}
                if file_type == "docx":
                    print(f"Converting DOCX to HTML")
                    section_html_dict = (
                        spire_SOA_extraction.process_docx_to_section_html_dict_from_s3(
                            file, final_sections_pass_through
                        )
                    )
                    
                else:

                    filter_soa = []
                    for i in final_sections_pass_through:
                        if self.normalize_toc(i[1]) in [
                            "schedule of activities",
                            "soa",
                            "schedule of assessments",
                            "Schedule of Assessments"
                        ]:

                            filter_soa.append(i)

                    def filter_by_lowest_page(items):
                        filtered = {}
                        for item in items:
                            # item = (key, name, page_start, page_end)
                            name = item[1]
                            page_start = item[2]

                            # Keep the item with the lowest page_start for each name
                            if name not in filtered or page_start < filtered[name][2]:
                                filtered[name] = item

                        # Return filtered values as list
                        return list(filtered.values())

                    print("filter_soa", filter_by_lowest_page(filter_soa))

                    pdf_file_like = io.BytesIO(file_bytes)
                    
                    
                    
                    table_settings = {
                        "vertical_strategy": "lines",  # can also try "text" if lines aren't working
                        "horizontal_strategy": "lines",
                        "snap_tolerance": 3,
                        "join_tolerance": 3,
                        "edge_min_length": 3,
                        "intersection_tolerance": 3,
                        "min_words_vertical": 1,
                        "min_words_horizontal": 1,
                        "text_tolerance": 3,
                        "text_x_tolerance": 3,
                        "text_y_tolerance": 3,
                    }

                    def detect_header_rows(table):
                        header_rows = []
                        for i, row in enumerate(table):
                            row_str = [str(cell).strip() for cell in row]

                            # If the row contains any "X" (case-insensitive), stop and return collected headers
                            if any(c.lower() == "x" for c in row_str):
                                break

                            header_rows.append(row)

                        return header_rows

                    def merge_header_rows(header_rows):

                        transposed = list(zip(*header_rows))
                        merged = [
                            " ".join(filter(None, map(str, col)))
                            .replace("\n", " ")
                            .strip()
                            for col in transposed
                        ]
                        return merged

                    all_tables = []
                    superscripts  = []
                    all_table_set = []
                    with pdfplumber.open(pdf_file_like) as pdf:
                        # Pages 12 to 16 (1-based) => indexes 11 to 15
                        for i in filter_soa:

                            for page_num in range(i[2] - 1, i[3]):
                                page = pdf.pages[page_num]
                                html_content = pdf_document[page_num].get_text("html")

                                superscripts.append(html_content)
                                
                                tables = page.extract_tables(
                                    table_settings=table_settings
                                )
                                all_table_set.extend(tables)

                    all_tables = []
                   
                    cleaned_table = []
                    
                    footnotes_response,footnote_input_token , footnote_output_token  = llmOperations.exctract_footnote(superscripts) 

                    print("super script",footnotes_response)
                    
                    

                    def make_unique_columns(cols):
                        seen = {}
                        result = []
                        for col in cols:
                            if col not in seen:
                                seen[col] = 0
                                result.append(col)
                            else:
                                seen[col] += 1
                                result.append(f"{col}_{seen[col]}")
                        return result

                    def merge_section_headers(df):
                        # Copy to avoid modifying original
                        df = df.copy()

                        first_col = df.columns[0]
                        section_header = None
                        rows_to_drop = []

                        for i in range(len(df)):
                            row = df.iloc[i]

                            if row[1:].isna().all():
                                
                                print("---- found row with section header",row)

                                section_header = row[first_col]
                                rows_to_drop.append(i)  # mark this row to remove later
                            elif section_header:

                                df.at[i, first_col] = (
                                    f"{section_header} + {row[first_col]}"
                                )

                        df = df.drop(rows_to_drop).reset_index(drop=True)
                        return df


                    flattened_cols = [
                        "_".join(map(str, col)).strip() for col in df.columns.values
                    ]
                    df.columns = make_unique_columns(flattened_cols)

                    for indx,table in enumerate(all_table_set):
                        header_rows = detect_header_rows(table)
                        if indx < 1 or len(table_header_str) < 2:

                            table_header_str , input_token_extract_table_header,output_token_extract_table_header = llmOperations.exctract_table_header(
                                header_rows
                            )
                            data_start_index = len(header_rows) - 1

                        import ast

                        header_list = ast.literal_eval(table_header_str)
                        flattened_cols = [
                            f"{p}_{c}" if c else p for p, c in header_list
                        ]

                        print("----->", flattened_cols)  


                        num_cols = len(flattened_cols)

                        cleaned_rows = []

                        display(table)
                        print("data_start_index : ",data_start_index)
                        for idx, row in enumerate(table[data_start_index:], start=data_start_index):
                            
                            row = list(row)
                            if row[0] is None or str(row[0]).strip() == "":
                                shifted = row[1:] + [row[0]]
                                cleaned_rows.append(shifted)
                            else:
                                print("else conditon-->",row)
                                cleaned_rows.append(row)
                        df_temp = pd.DataFrame(cleaned_rows)

                        # Only clean if DataFrame has more columns than num_cols
                        if df_temp.shape[1] > num_cols:
                            # Drop columns where all values are None or empty string
                            df_temp = df_temp.dropna(axis=1, how="all")  # Drop all-NaN columns
                            df_temp = df_temp.loc[:, ~(df_temp.astype(str).apply(lambda x: x.str.strip()) == "").all()]  # Drop all-empty-string columns

                            # Update cleaned_rows from cleaned DataFrame
                            cleaned_rows = df_temp.values.tolist()

                        print("num_cols -->", num_cols)
                        data_rows = [r[:num_cols] for r in cleaned_rows]

                        

                        df_temp = pd.DataFrame(data_rows)
                        display(df_temp)
                        
                        df_temp = df_temp.dropna(
                            axis=1, how="all"
                        )  
                        df_temp = df_temp.loc[
                            :, ~(df_temp.applymap(lambda x: x is None).all())
                        ]

                        df_temp.columns = make_unique_columns(
                            flattened_cols[: df_temp.shape[1]]
                        )
                        df = df_temp

                        all_tables.append(df)

                    if all_tables:

                        full_df = pd.concat(all_tables, ignore_index=True, sort=False)
                        first_col = full_df.columns[0]

                        # Filter out rows where the first column is either equal to the header name or is NaN/None
                        full_df = full_df[~((full_df[first_col] == first_col) | (full_df[first_col].isna()))].reset_index(drop=True)
                        
                        print("FOOTNOTE RESPONSE >>>", repr(footnotes_response))

                        footnotes =  json.loads(footnotes_response)

                        

                        def append_footnotes_first_column(df, footnotes):
                            
                            updated_df = df.copy()
                            col_name = df.columns[0]  # only first column

                            for i, cell in enumerate(updated_df[col_name]):

                                text = str(cell)

                                markers = re.findall(r"(?:^|\n)([a-z])(?:\n|$)", text)

                                for marker in markers:

                                    if marker in footnotes:

                                        text += f"~~ [Note {marker}: {footnotes[marker]}]"

                                updated_df.at[i, col_name] = text

                            return updated_df

                        updated_df = append_footnotes_first_column(full_df, footnotes)
                        
                        
                        random_int = random.randint(60,75)
                        sql_query = f"""UPDATE {table_ctl_protocol}
                                        SET "digitization_percent" = '{random_int}' , "description" = ' Table of Content Formatted , Starting Extracting Schedule of Assessments'
                                        WHERE "protocol_id" = '{protocol_id}';

                                            """
                        logging.info(f"executing sql query:{sql_query}")
                        client.sql_query(query =  sql_query, connection = proj.get_variables()['local'].get("snowflake_connection_string"),  post_queries=["COMMIT"])
        

        
                        # Find the Notes column (case-insensitive)
                        notes_col = next((col for col in updated_df.columns if col.lower() == "notes"), None)
                        
                    
                        print("notes_col",notes_col)
                        if notes_col:
                            first_col = updated_df.columns[0]

                            # Merge first column with Notes values
                            updated_df[first_col] = updated_df.apply(
                                lambda row: (
                                    f"{row[first_col]} ~~~ [note : {row[notes_col]}]"
                                    if pd.notna(row[notes_col]) and str(row[notes_col]).strip().lower() != "none"
                                    else row[first_col]
                                ),
                                axis=1
                            )
                         
                        final_df_without_notes = updated_df.drop(
                        columns=[col for col in updated_df.columns if 'notes' in col.lower()],
                        errors='ignore'
                        )
                            
                        update_df_header = merge_section_headers(final_df_without_notes)
                        print("---- removed section headers")
                        display(update_df_header)

                        # Find the Notes column (case-insensitive)
                        final_df = update_df_header
                        
                        '''notes_col = next((col for col in update_df_header.columns if col.lower() == "notes"), None)
                        print("notes_col",notes_col)
                        if notes_col:
                            first_col = update_df_header.columns[0]

                            # Merge first column with Notes values
                            update_df_header[first_col] = update_df_header.apply(
                                lambda row: (
                                    f"{row[first_col]} ~~ [note : {row[notes_col]}]"
                                    if pd.notna(row[notes_col]) and str(row[notes_col]).strip().lower() != "none"
                                    else row[first_col]
                                ),
                                axis=1
                            )

                            

                        
                        final_df = update_df_header.drop(
                        columns=[col for col in update_df_header.columns if 'notes' in col.lower()],
                        errors='ignore'
                        )'''
                        
                    else:
                        print("No tables found.")
                        final_df = ''
                        
                #display(final_df)
                if  isinstance(final_df, str):
                    raise  Exception(f"Error from file_extractor: due to no Tables were found")
                
                columns = list(final_df.columns)[1:]   # skip first column (row labels)
                row_labels = final_df.iloc[:, 0]       # first column is row labels

                references = []
                
                
                random_int = random.randint(75,85)
                sql_query = f"""UPDATE {table_ctl_protocol}
                                SET "digitization_percent" = '{random_int}' , "description" = 'Extracting Schedule of Assessments'
                                WHERE "protocol_id" = '{protocol_id}';

                                    """
                logging.info(f"executing sql query:{sql_query}")
                client.sql_query(query =  sql_query, connection = proj.get_variables()['local'].get("snowflake_connection_string"),  post_queries=["COMMIT"])
        

                for i, row_label in enumerate(row_labels):
                    for col in columns:
                        cell_value = str(final_df.iloc[i][col]).strip()
                        if len(cell_value) > 0 and cell_value.lower() != "none":
                            if cell_value.lower() != "x":
                                
                                references.append((f"{row_label} ~~~~ [ Note : {cell_value}] ", col))
                            else:
                                references.append((f"{row_label} ~~~~ ", col))

                
                response = references 
                #response = llmOperations.extract_refrence_from_soa(final_df)
                
                get_protocol_summary_pages , input_token_extract_protocol , output_token_extract_protocol = (
                    llmOperations.exctract_protocol_summary_pageNumber(
                        final_sections_pass_through
                    )
                )

                print("get_protocol_summary_pages", get_protocol_summary_pages)
                pro_sum_time = time.time()
                print("total time for protocol_summary_time ", pro_sum_time - toc_page_add)
                clean_pages_num = ast.literal_eval(get_protocol_summary_pages)
                protocol_summary = ""
                ie_summary = ""
                if clean_pages_num:
                    with pdfplumber.open(pdf_file_like) as pdf:
                        protocol_summary = ""
                        for page_num in range(
                            clean_pages_num[0][1] - 1, clean_pages_num[0][2] + 1
                        ):

                            page = pdf.pages[page_num]
                            text = page.extract_text()
                            if text:
                                protocol_summary += text

                    if len(clean_pages_num) > 1:
                        with pdfplumber.open(pdf_file_like) as pdf:

                            for page_num in range(
                                clean_pages_num[1][1] - 1, clean_pages_num[1][2] + 1
                            ):

                                page = pdf.pages[page_num]
                                text = page.extract_text()
                                if text:
                                    ie_summary += text

                ctl_forms_feild_mapping = self.config["common_tables"][
                    "ctl_protocol_extraction"
                ]


                protocol_name = file_path.split("/")[-1].replace("'", "''")
                protocol_path = file_path.replace("'", "''")
                protocol_soa = final_df.to_string().replace("'", "''")
                protocol_soa_reference = response
                protocol_summary = protocol_summary.replace("'", "''")
                protocol_ie_ae = ie_summary.replace("'", "''")
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                #print()

                post_comment_query = f"""
                    INSERT INTO {ctl_forms_feild_mapping} (
                        "user_id",
                        "protocol_id",
                        "protocal_name",
                        "protocol_path",
                        "protocol_soa",
                        "protocol_soa_reference",
                        "protocol_summary",
                        "protocol_ie_ae",
                        "created_at"
                    )
                    VALUES (
                        '{user_id}',
                        '{protocol_id}',
                        '{protocol_name}',
                        '{protocol_path}',
                        $$ {protocol_soa} $$,
                        $$ {protocol_soa_reference} $$,
                        $$ {protocol_summary} $$,
                        $$ {protocol_ie_ae} $$,
                        '{created_at}'
                    )
                """
                # Execute the SQL query
                client.sql_query(
                    query=post_comment_query,
                    connection=proj.get_variables()["local"].get(
                        "snowflake_connection_string"
                    ),
                    post_queries=["COMMIT"],
                )

                

                random_int = random.randint(90,96)
                sql_query = f"""UPDATE {table_ctl_protocol}
                        SET "digitization_percent" = '{random_int}' ,  "description" = 'Schedule of Assessments Extracted'
                        WHERE "protocol_id" = '{protocol_id}';
                
                            """
                logging.info(f"executing sql query:{sql_query}")
                
                input_tokens = input_token_toc_present +  input_token_valid_section + input_token_extract_table_header +  input_token_extract_protocol + footnote_input_token
                output_tokens =  output_token_toc_present + output_token_valid_section + output_token_extract_table_header + output_token_extract_protocol + footnote_output_token
                end_time = time.time()
                total_time = end_time - start_time
                print("total time taken",total_time)
                request_id = uuid.uuid4()
                logging_query = f"""INSERT INTO {llm_token_usage_log}
                    (request_id, report_type, workflow,  input_token, output_token,  protocol_id,execution_time,created_at)
                    VALUES (
                        '{request_id}', 'CRF', 'Digitization', 
                        {input_tokens}, {output_tokens}, '{protocol_id}', {total_time},current_timestamp
                    )
                
                """
                client.sql_query(query =  logging_query, connection = proj.get_variables()['local'].get("snowflake_connection_string"),  post_queries=["COMMIT"])
                
# input_token_toc_present , output_token_toc_present ; input_token_valid_section , output_token_valid_section ;
#input_token_extract_table_header,output_token_extract_table_header ; input_token_extract_protocol , output_token_extract_protocol
                client.sql_query(query =  sql_query, connection = proj.get_variables()['local'].get("snowflake_connection_string"),  post_queries=["COMMIT"])

                return full_df, final_df, response
                

            else:
                ## Look at an alternative where you send the entire file
                print(f"Skipping pass-through as no sections are detected in the file")

        except Exception as e:
            import traceback
            print(f"Error occurred in pass-through functionality: {e}")
            t = traceback.format_exc()
            return f"error occured due to {t}"
                 