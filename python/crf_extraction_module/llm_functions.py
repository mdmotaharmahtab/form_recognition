import dataikuapi
from typing import Dict, Any
import sys
from utilities.tools import (
    count_tokens
)
import json 
import os
import io
import fitz  # PyMuPDF
#from langgraph_utils.Info_extractor import InfoExtractorAgent
# from langgraph_utils.chat_history import SnowflakeChatMessageHistory
import json
#from langgraph_utils.file_parser import FileParser
#from langgraph_utils.digitization import main_handler
import uuid
#from langgraph_utils import creds
#from langgraph_utils.variables import PROJECT_NAME, SECRET_NAME, TOKEN_KEY
from utils.connection import get_dataiku_client_and_project
import logging
import tempfile
import re
import pymupdf4llm
from dataikuapi import DSSClient
from dataikuapi.dss.project import DSSProject
import pandas as pd

class LLMFuntions:
    
    def __init__(self, client : DSSClient, proj: DSSProject):
        self.default_llm_model = proj.get_variables()['local'].get('default_llm_model')
        self.llm = proj.get_llm(self.default_llm_model).as_langchain_llm()
        
    def is_toc_present(self,pdf_text):  
        """
        Use OpenAI to detect whether the given page contains any part of a Table of Contents (TOC).
        The model is instructed to:
        1. Look for TOC-like headings (e.g., "Table of Contents", "Contents", "Index").
        2. If no heading is found, check if section titles with page numbers are present (which may indicate a continuation).
        3. Return 'yes' only if there's strong evidence of a TOC or TOC entries. Return 'no' otherwise.
        """
        try:
            prompt = (
                "You are analyzing a single page of a PDF to determine if it contains part of a Table of Contents (TOC).\n"
                "Follow these steps strictly:\n"
                "1. Look for a heading that clearly indicates a TOC is present, such as 'Table of Contents', 'Contents', or 'Index'.\n"
                "2. If no heading is found, check whether the page contains multiple section titles (like '1 Introduction', '2 Methods', etc.) "
                "each followed by a page number (e.g., 5, 12, 18). This might indicate it's a continuation of a TOC page.\n"
                "3. If both a heading and structured entries are missing, return 'no'.\n"
                "Return only one word: 'yes' or 'no'. Do not add any other text.\n\n"
                f"Document text:\n{pdf_text}"
            )

            messages = [
                {"role": "system", "content": "You are a strict document structure evaluator."},
                {"role": "user", "content": prompt}
            ]

            
            content = self.llm.invoke(messages).strip().lower()
            input_token =  count_tokens(str(prompt))
            output_token =  count_tokens(str(content))
            return content == "yes" , input_token , output_token

        except Exception as ex:
            print(f"Error in TOC detection via OpenAI: {ex}")
            return None
        
    def exctract_protocol_summary_pageNumber(self,toc_list):
        prompt = (f'''
        
                You are an expert in medical document parsing. Given the Table of Contents (TOC) from a clinical or medical protocol document used for CRF (Case Report Form) design, identify the **starting and ending page numbers** of the following sections and their common variations:

                1. **Protocol Summary**
                   - Common variations: "Protocol Summary","PROTOCOL AMENDMENT ACCEPTANCE FORM" , "Protocol Synopsis", "Study Summary", "Summary of Protocol"

                2. **Inclusion/Exclusion Criteria**
                   - Common variations: "Inclusion Criteria", "Exclusion Criteria", "Eligibility Criteria", "Subject Eligibility", "Eligibility Requirements", "Participant Inclusion/Exclusion"

                ### Instructions:
                - Return the result in the below format:
                ```

                [("Section Label", start_page, end_page)]

                ```
                - The `start_page` is the page number where the section begins.
                - The `end_page` is the page just before the next section begins.
                - If multiple variations of a section appear (e.g., both "Inclusion Criteria" and "Exclusion Criteria"), combine their range using the **lowest start** and **highest end**.
                - If a section appears on only one page, start and end can be the same.
                - Do not return any explanations or extra text — only the final list of tuples.

                ### Example Output:
                [("Protocol Summary", 3, 6), ("Inclusion/Exclusion Criteria", 7, 9)]

                Now extract the information from the following TOC:
                {toc_list}

        ''')
        
        messages = [
            {"role": "system", "content": f"""You are a medical document parser that returns structured data only."""},
            {"role": "user", "content": prompt}
        ]

        
        try:

            ans = self.llm.invoke(messages)
            input_token =  count_tokens(str(messages))
            output_token =  count_tokens(str(ans))
#             validity = ans.strip().lower()
            return ans , input_token , output_token 

        except Exception as e:
            print(f"Error checking section name: {e}")
            return False ,_,_
    
    def exctract_table_header(self,top_rows):
        
        prompt = (f'''
           You are given the top 5 rows of a table extracted from a PDF. These rows contain the table headers, where the first few rows represent merged column groups (parent headers), and the last row represents the detailed column names (child headers).

            Your task:
            1. Analyze the structure of the headers.
            2. Identify the parent and child relationships.
            3. Return ONLY the final header as a valid Python list of tuples, where each tuple is (parent, child).
               - If a column does not have a parent, use the column name as parent and set child as None.
               - If a column does not have a child (only one level), use child as None.
            4. Preserve special characters, superscripts, and spacing exactly as they appear.
            5. Do NOT include any explanations, comments, or extra text. Output only the list.

            Example output:
            [
                ("Period", "Trial Day"),
                ("Screening", "−28 to −2"),
                ("Check-in", "−1"),
                ("Treatment", "1"),
                ...
                ("Telephone Follow-upᵃ", "21(+2)"),
                ("Notes", None)
            ]

            Now, here are the first 5 rows of the table:
            {top_rows}

                

        ''')
        
        messages = [
            {"role": "system", "content": f"""You are given the top 5 rows of a table extracted from a PDF. These rows contain the table headers, where the first few rows represent merged column groups (parent headers), and the last row represents the detailed column names (child headers)."""},
            {"role": "user", "content": prompt}
        ]

        
        try:

            ans = self.llm.invoke(messages)
#             validity = ans.strip().lower()
            input_token =  count_tokens(str(messages))
            output_token =  count_tokens(str(ans))
            return ans , input_token , output_token 

        except Exception as e:
            print(f"Error checking section name: {e}")
            return False
    
    def exctract_footnote(self,top_rows):
        
        prompt = (f'''
            You are an expert text normalizer and formatter for scientific PDF footnotes.

            You are given an HTML snippet extracted from a PDF (via pdf_document[page_num].get_text("html")).  
            In this HTML:
            - Superscript footnote markers are not inside <sup> tags.  
            - They appear as small text elements (e.g., using a smaller "font-size" style).  
            - Footnote content may follow immediately or be spread across multiple spans/divs.  
            - There may be noise or broken fragments.

            ### Your Tasks:
            1. **Detect footnote markers**:  
               - Identify text with the smallest `font-size` in the HTML as footnote markers.  
               - The marker is usually a single character (letter, number, or symbol).  

            2. **Extract associated text**:  
               - Collect text following the marker until the next marker or end of the footnote section.  
               - Merge fragmented parts if they belong to the same footnote.  

            3. **Ignore irrelevant or empty entries** that do not contribute to a valid note.  

            4. **Preserve order** of markers as they appear in the HTML.  

            5. **Ensure uniqueness**: if the same marker appears multiple times with different notes, merge them intelligently.

            6. **Clean text**:  
               - Remove stray characters (e.g., "X X X"), duplicate spaces, repeated dashes, etc.  

            7. **Return the output** strictly as a JSON object where keys are superscript markers and values are the cleaned footnote text.

            8. **Do not hallucinate** or add information not present in the input HTML.
            9. Return the result as a **clean JSON object** where each key is a marker and its value is the cleaned footnote text.
            10. **Do not add any explanations or extra text — only return the final JSON.**

            ### Example:

            #### Input HTML:
            ```html
            <span style="font-size:6px">a</span> Follow-up  
            <span style="font-size:6px">a</span> Check-in Section 4.1  
            <span style="font-size:6px">b</span> Physical Examination
            ````

            #### Expected Output:

            {{
            "a": "Follow-up; Check-in Section 4.1",
            "b": "Physical Examination"
            }}

            ---

            ### Now process the following HTML and return only the final JSON:

            {top_rows}
            
            ### WHAT NOT TO DO
                    
            - DO NOT RETURN PYTHON CODE BLOCKS
            - Do **not** include explanations, markdown, or formatting. Only return a valid JSON. No preamble. No wrapping text.

  
        ''')
        
        messages = [
            {"role": "system", "content": f"""You are an expert text normalizer and formatter for scientific PDF footnotes""" },
            {"role": "user", "content": prompt}
        ]

        
        try:

            ans = self.llm.invoke(messages)
            input_token =  count_tokens(str(messages))
            output_token =  count_tokens(str(ans))
#             validity = ans.strip().lower()
            return ans , input_token , output_token 

        except Exception as e:
            print(f"Error checking section name: {e}")
            return False
       
    
    def get_club_assesmetnts_name(self,table):
        
        
        
        prompt = (f"""

            You are a data normalization and grouping assistant.

            You will receive a list of tuples {table}, each containing:
            - an `_id` (a UUID)
            - an `assessment_name` (a descriptive string)

            Your task is to process this list and group the entries based on common themes or leading phrases in the `assessment_name`.

            **Example input:
            [
                (
                    '_id': 'eca936be-3538-4406-9edf-607fb5ca0a7a',
                    'assessment_name': 'Adverse Events (for single study treatment)',
                ),
                (
                    '_id': '7953f9e2-08f7-4830-806d-28cd89bb767b',
                    'assessment_name': 'Adverse Events (Multiple Study Treatment) Were any adverse events experienced? ⭘ No ⭘ Yes',
                )
            ]

            Expected output:
            A single JSON object that groups UUIDs by the common assessment theme, inferred from the leading part of the `assessment_name`.

            Example output:
            ```json
            {{
                "Adverse Events": [
                    "eca936be-3538-4406-9edf-607fb5ca0a7a",
                    "7953f9e2-08f7-4830-806d-28cd89bb767b"
                ],
                "Demographics": [
                    "some-other-uuid-1234-from-input"
                ]
            }}
            ```

            Rules:

            * The grouping key should be a **generalized theme** from the start of `assessment_name`, such as `"Adverse Events"`, `"Demographics"`, etc.
            * Only return the final JSON object.
            * UUIDs must be returned as strings.






            """)
        messages = [
            {"role": "system", "content": "You are a data normalization and grouping assistant"},
            {"role": "user", "content": prompt}
        ]

        
        try:

            ans = self.llm.invoke(messages)
            input_token =  count_tokens(str(messages))
            output_token =  count_tokens(str(ans))
#             validity = ans.strip().lower()
            return ans , input_token , output_token
        except Exception as e:
            print(f"Error checking section name: {e}")
            return False
        
    def get_perfect_mapping_feilds(self,table):
        
        json_str = table.to_json(orient="records")
        #print(json_str)
        
        prompt = (f"""
            You are a data transformation assistant.
            Given a JSON_INPUT = {json_str}, where:

            - The **first entry** contains the "assessment_name" as a label (typically the first cell or key).
            - The remaining entries represent **field names** and their corresponding **field values**.

            Your task is to convert this input into the following JSON structure:

            ```json
            {{
                "assessment_name": "< a meaningful value from the first entry (do not preserve newlines if present) take the only first sentence till first newline character>",
                "fields": [
                    {{
                        "field_name": "<a meaningful label derived from the key or nearby context>",
                        "field_value": "<value for that field>"
                    }},
                    ...
                ]
            }}
            ```
            Guidelines:

            The assessment name must should be meaningful as in the original input.
            Ensure the output is valid JSON:
            Escape backslashes (\) as double backslashes (\\\\) where needed.
            The field_name should be meaningful:
            Ignore blank or empty field names unless the value provides clear context.
            If necessary, infer a descriptive label from adjacent fields or typical patterns (e.g., if a field only says "DD", and the previous field is a date prompt, combine them).
            Only return the final JSON object — no extra explanation or text.
            """)
        messages = [
            {"role": "system", "content": "You are a data transformation assistant"},
            {"role": "user", "content": prompt}
        ]

        
        try:

            ans = self.llm.invoke(messages)
            input_token =  count_tokens(str(messages))
            output_token =  count_tokens(str(ans))
#             validity = ans.strip().lower()
            return ans, input_token , output_token 
        except Exception as e:
            print(f"Error checking section name: {e}")
            return False
        
    def extract_refrence_from_soa(self,table):
        
        json_str = table.to_json(orient="records")
        print(json_str)
        prompt = (f'''
                
                YOU ARE A CLINICAL DATA INTERPRETATION EXPERT AGENT THAT PROCESSES TABULAR CLINICAL TRIAL SCHEDULES FORMATTED AS A LIST OF JSON OBJECTS. EACH OBJECT REPRESENTS A ROW FROM A TABLE, WHERE KEYS ARE COLUMN HEADERS (FLATTENED WITH UNDERSCORES) AND VALUES ARE CELL CONTENTS.

                    YOUR TASK IS TO EXTRACT A STRUCTURED, CLEAN LIST OF WHICH PROCEDURES OCCUR ON WHICH VISIT DAYS.
                    
                    JSON_INPUT = {json_str}
                    ---




                    ### CHAIN OF THOUGHT

                    FOLLOW THIS REASONING SEQUENCE FOR EVERY INPUT TABLE:

                    1. UNDERSTAND: RECOGNIZE THAT INPUT IS A LIST OF ROW DICTIONARIES WHERE EACH KEY IS A COLUMN LABEL AND EACH VALUE IS THE CELL CONTENT.
                    2. BASICS: IDENTIFY THE SPECIAL COLUMN THAT CONTAINS PROCEDURE NAMES. IT IS ALWAYS NAMED SOMETHING LIKE `"Study Procedures_nan"` OR SIMILAR VARIANT.
                    3. BREAK DOWN:
                       - EXTRACT PROCEDURE NAME FROM THE CORRECT KEY (e.g., `"Study Procedures_nan"`).
                       - FOR EACH OTHER COLUMN:
                         - IF THE KEY IS A VISIT DAY (e.g., `"Screening_nan"` or `"Day -1_nan"` or `"Discharge (EOS) or ET_Days 4 to 9"`):
                           - CLEAN THE COLUMN NAME (REMOVE `_nan`, EXTRACT VISIT DAY LABEL).
                    4. ANALYZE:
                       - IF THE CELL VALUE IS `"X"` OR `"x"` → MAP THE PROCEDURE TO THAT VISIT DAY.
                       - IF THE CELL VALUE IS NON-EMPTY DESCRIPTIVE TEXT → MAP PROCEDURE TO `"description, visit_day"`.
                    5. BUILD:
                       - COMPILE TUPLES OF THE FORM `(procedure, visit_day)` OR `(procedure, "description, visit_day")`.
                    6. EDGE CASES:
                       - IGNORE KEYS LIKE `"nan_nan"` OR `"Notes_nan"` THAT ARE NON-DAY, NON-PROCEDURE FIELDS.
                       - IGNORE ANY NULL, EMPTY, OR WHITESPACE-ONLY CELLS.
                    7. FINAL ANSWER:
                       - RETURN A CLEAN PYTHON LIST OF TUPLES:
                       - Do **not** include explanations, markdown, or formatting. Only return a valid Python list of tuples. No preamble. No wrapping text.

                    ```python
                    [
                      (procedure_name, visit_day_label),
                      (procedure_header ~~ procedure_name, "description, visit_day_label"),
                      ...
                    ]
                    ```

                    ---

                    ### EXAMPLE INPUT (JSON FORMAT)

                    
                    [
                      {{
                        "Study Procedures_nan": "Informed consent",
                        "Screening_nan": "X",
                        "Day -1_nan": "",
                        "Discharge (EOS) or ET_Days 4 to 9": ""
                      }},
                      {{
                        "Study Procedures_nan": "Inclusion/exclusion criteria",
                        "Screening_nan": "X",
                        "Day -1_nan": "X",
                        "Discharge (EOS) or ET_Days 4 to 9": ""
                      }},
                      
                      {{
                      "Study Procedures":"Pharmacokinetics ~~ Physical examination",
                      "Screening":"",
                      "Day -1":"X",
                      "Days 1 to 3":"",
                      "Discharge (EOS) or ET_Days 4 to 9":"Discharge",
                      "Notes":"Symptom-directed at discharge."
                      }}
                    ]
                   

                    ---

                    ### EXPECTED OUTPUT

                   
                    ```python[
                      ("Informed consent", "Screening"),
                      ("Inclusion/exclusion criteria", "Screening"),
                      ("Inclusion/exclusion criteria", "Day -1"),
                    ]```
                    

                    ---

                    ### TEXT CLEANING RULES

                    - REMOVE SUFFIXES LIKE `_nan` OR `_nan_1` FROM COLUMN HEADERS
                    - TRIM WHITESPACE AND LINE BREAKS FROM BOTH COLUMN LABELS AND CELL CONTENTS
                    - NORMALIZE CAPITALIZATION OF 'X'/'x' → ALWAYS TREATED AS INDICATOR

                    ---

                    ### WHAT NOT TO DO
                    
                    - DO NOT RETURN PYTHON CODE BLOCKS
                    - DO NOT INCLUDE PLACEHOLDER TEXT LIKE `"description"` — ALWAYS INSERT THE ACTUAL CELL VALUE
                    - DO NOT INCLUDE EMPTY, NULL, OR NON-VISIT METADATA COLUMNS
                    - DO NOT INCLUDE NON-DAY/NON-PROCEDURE COLUMNS (E.G., `"nan_nan"`, `"Notes_nan"`)
                    - DO NOT GUESS VISIT NAMES — USE EXACT CLEANED COLUMN LABELS
                    - NEVER OMIT NON-"X" DESCRIPTIONS (THEY CONTAIN IMPORTANT TIMING INFO)
                    - AVOID DUPLICATES IN OUTPUT — ENSURE EACH PAIR IS UNIQUE
                    - Do **not** include explanations, markdown, or formatting. Only return a valid Python list of tuples. No preamble. No wrapping text.

                    ---

                    ### BONUS

                    IF A CELL CONTAINS A DESCRIPTION LIKE `"Pre-dose, 0.5h, 1h"` UNDER `"Day 1_nan"` AND THE PROCEDURE IS `"Blood Sampling"` — OUTPUT:

                    
                    [("Blood Sampling", "Pre-dose, 0.5h, 1h - Day 1"),("Pharmacokinetics ~~ Physical examination","Day -1")]

                    
                ''')
        messages = [
            {"role": "system", "content": "YOU ARE A CLINICAL DATA STANDARDS EXPERT AND HTML STRUCTURING SPECIALIST, INTERNATIONALLY RECOGNIZED FOR YOUR PRECISION IN EVALUATING AND FORMATTING CLINICAL TRIAL DOCUMENTS. YOUR MISSION IS TO **EVALUATE WHETHER A GIVEN HTML TABLE REPRESENTS A PERFECT SCHEDULE OF ACTIVITIES (SOA)** IN A CLINICAL TRIAL, AND THEN **FORMAT OR CORRECT THE TABLE INTO A PERFECTLY STRUCTURED, GCP-COMPLIANT SOA HTML TABLE."},
            {"role": "user", "content": prompt}
        ]

        
        try:

            ans = self.llm.invoke(messages)
            input_token =  count_tokens(str(messages))
            output_token =  count_tokens(str(ans))
#             validity = ans.strip().lower()
            return ans , input_token , output_token 
        except Exception as e:
            print(f"Error checking section name: {e}")
            return False
        
        
    def is_valid_section_name(self,section_name):
        """
        Determines if the input string is a valid section or subsection heading in a clinical or research document.
        Uses a balanced prompt with examples for better LLM judgment.
        """
        prompt = (
            "Determine whether the following text is a valid section, subsection, or table heading in a clinical or scientific research document. "
            "Consider typical structure, formatting, and topic relevance of real document headings. "
            "Return only 'yes' or 'no'.\n\n"
            "Examples:\n"
            "- 'Non-Amgen Medicinal Product Background: Pembrolizumab' → yes\n"
            "- '1.1 Study Objectives' → yes\n"
            "- 'Adverse Events of Special Interest' → yes\n"
            "- '3.7.2 Interim Analyses' → yes\n"
            "- 'Statistical Methods' → yes\n"
            "- 'Table 1 Summary of Adverse Events' → yes\n"
            "- 'Table 3: Laboratory Parameters' → yes\n"
            "- 'months after autologous stem cell transplantation; when using PET...' → no\n"
            "- 'such as lymph nodes or organs.' → no\n"
            "- '...can help identify relapse earlier' → no\n\n"
            f"Text: '{section_name}'\n"
            "Is this a valid section, subsection, or table heading? Answer only with 'yes' or 'no'."
        )


        messages = [
            {"role": "system", "content": "You are a helpful assistant that checks clinical document section names."},
            {"role": "user", "content": prompt}
        ]

        try:
#                 llm = build_model(max_tokens=10, temperature=0.0)
            ans = self.llm.invoke(messages)
            input_token =  count_tokens(str(messages))
            output_token =  count_tokens(str(ans))
            validity = ans.strip().lower()
            return validity == "yes" , input_token , output_token 
        except Exception as e:
            print(f"Error checking section name: {e}")
            return False , False, False
        
    def group_headers(self,table):
        


        prompt = (f"""
            You are given a list of indexed schedule headers.
            {table}

            Task: Group headers into tuples if they share the same final visit day. 
            - Normalize superficial differences (spaces, hyphens, prefixes, case). 
            - Compare based on visit sequence, especially the last visit day. 
            - If headers end at the same day, put them in the same tuple. 
            - Return only a Python list of tuples, nothing else.

            Example:
            Input:
            [[0,'...treatment_day 10...'],
             [1,'...period 3_day 9|discharge_day 10...'],
             [2,'...treatment_day 10...'],
             [3,'...discharge_day 10...'],
             [4,'...discharge_day 13...'],
             [5,'...discharge_day 13...']]

            Output: [(0,1,2,3),(4,5)]

            """)
        
        messages = [
            
            {"role": "user", "content": prompt}
        ]


        try:

            ans = self.llm.invoke(messages)
            input_token =  count_tokens(str(messages))
            output_token =  count_tokens(str(ans))
#             validity = ans.strip().lower()
            return ans, input_token , output_token 
        except Exception as e:
            print(f"Error checking section name: {e}")
            return False


        