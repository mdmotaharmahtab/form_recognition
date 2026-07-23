import os
import io
import fitz  # PyMuPDF
import pdfplumber
from uuid import uuid4


class historical_CRF:
    
    def __init__(self, client, proj, chunk_size=1000):
        self.proj = proj
        self.client = client
        self.s3_folder_dataset_id = proj.get_variables()['local'].get('file_upload') # change file upload 
        self.input_folder = proj.get_managed_folder(self.s3_folder_dataset_id)
        self.files = self.input_folder.list_contents()["items"]
        self.toc_page_limit = 20
        self.config = proj.get_variables()["local"]
        print(self.files)

    def historical_mapping(self, file_path,file_id,paths=[]):
        result = []

#         for file in paths:
#             path = file
#             print(path)
#             parts = path.strip('/').split('/')

#             if "Historical" in path:
                
#                 result.append({
                    
#                     "path": path,
                   
    
#                 })
        result.append(file_path)

        response = []
        snowflake_conn = self.config.get("snowflake_connection_string")
        table_file_upload = self.config.get("ecs", {}).get("ecs_file_upload", {})

        for i in result:
            

            with self.input_folder.get_file(file_path) as stream:
                file_bytes = stream.raw.data
            
            
            try:
                
                import re

                def clean_summary(text):
                    # Remove newlines, tabs, and collapse extra spaces
                    text = re.sub(r'\s+', ' ', text).strip()

                    # Ensure it ends with a single period
                    if not text.endswith('.'):
                        text += '.'

                    return text
                
                pdf_file_like = io.BytesIO(file_bytes)
                with pdfplumber.open(pdf_file_like) as pdf:
                    total_pages = len(pdf.pages)
                    print(total_pages)
                    snowflake_conn = self.config.get("snowflake_connection_string")
                    table_file_upload = self.config.get("ecs", {}).get("ecs_file_upload", {})
                    i = 0
                    percent = 0
                    for page_num, page in enumerate(pdf.pages):
                        i = i +1
                        res = {}
                        last_update_range = None
                        
                        
                        current_range = (percent // 10) * 10
                        #print(i)
                        if i % 100 == 0 :
                            print(i)
                            percent = percent + 10
                            
                        
                            update_query = f"""
                                            UPDATE {table_file_upload}
                                            SET "digitization_percent" = '{percent}' , "description" = 'file is getting digitized'
                                            WHERE "crf_file_id" = '{file_id}'
                                             ;
                                        """
                            print(update_query)
                            if percent >= 90:
                                 update_query = f"""
                                            UPDATE {table_file_upload}
                                            SET "digitization_percent" = '{percent}' , "description" = 'almost there '
                                            WHERE "crf_file_id" = '{file_id}'
                                             ;
                                        """
                                
                            self.client.sql_query(query = update_query,connection = snowflake_conn,  post_queries=["COMMIT"])
                            last_update_range = current_range
#                         parts = i["path"].strip('/').split('/')
                        therapeutic_area = ''
                        source =  "Unknown"
                        template_name = os.path.basename(file_path)
                        unique_id = uuid4()
#                         print(hist_id)
                        res = {
                           
                            
                            "template_name": template_name,
                            "path": file_path,
                            "id": unique_id,

                        }
                        
                        page_text = page.extract_text(layout=True)
                        
                        if page_text and "field name" in page_text.lower():
                            continue

                        if not page_text:
                            continue

                        lines = page_text.split('\n')
                        header_lines = []
                        field_value_map = {}
                        current_field = ""
                        in_field_section = False

                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue

                            # Trigger point for header vs fields
                            if not in_field_section:
                                if "generated" in line.lower():
                                    in_field_section = True
                                    continue
                                header_lines.append(line)
                            else:
                                if len(line.strip()) == 0:
                                    continue
                                
                                pattern = r'''
                                    ^                              # Start of line
                                    (?P<field>.+?)                 # Field name (non-greedy)
                                    (?:\t|\s{2,})+                 # Separator: tab or ≥2 spaces
                                    (?P<value>.+?)                 # Value
                                    \s*$                           # Optional trailing spaces
                                '''
                                pattern2  = r'^(?!\s)(?!.*\s$)(?P<value>.+)$'

                                
                                
                                
                                
                                
#                                 current_field = None

                                # Step 1 ─ collect every “proper” field line
                                m = re.match(pattern, line, re.VERBOSE)
                                p = re.match(pattern2, line, re.VERBOSE) 
                                if m:
                                    if m.group("field") and m.group("value"):
                                        feild = m.group("field")
                                        current_field = feild
                                        value = m.group("value")
                                        
                                        
                                if p:
                                    if p.group("value") and current_field:
                                        # Continuation of previous field
#                                         feild = current_field
                                        value = p.group("value")
                                        
                        
                               
                                
                                left_part = current_field.strip()
                                right_part = value.strip()

                                if left_part:
                                    if left_part in field_value_map and right_part:
                                        field_value_map[left_part].append(right_part)
                                     
                                    else:
                                        
                                        field_value_map[left_part] = [right_part.strip()]
                             

                        final_feilds = []
                        for k in field_value_map:
                            
                            final_feilds.append({
                                "field_name" : k,
                                "field_value": field_value_map[k]
                            })
                        
                        head = ""
                        for j in header_lines:
                            if "form" in j.lower().strip() or "folder" in j.lower().strip():
                                head += j + " "
                        
                        res["source_data"] = {
                            "assessments" : head,
                            "fields" : final_feilds 
                            
                        }
#                         print(res)
                    
#                     print(res)
                        if final_feilds and head:
                            response.append(res)
#                             print(f"✅ extraction for {i['path']} completed")
                    

            except Exception as e:
                print(f"Error processing file {i['path']}: {e}")
        
        

        return response
