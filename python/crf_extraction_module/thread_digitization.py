import os
import io
import pdfplumber
from uuid import uuid4
import re

class HistoricalCRF:
    
    def __init__(self, client, proj, chunk_size=1000):
        self.proj = proj
        self.client = client
        self.chunk_size = chunk_size
        self.config = proj.get_variables()["local"]
        
        # Managed folder and file list
        self.s3_folder_dataset_id = self.config.get('file_upload')
        self.input_folder = proj.get_managed_folder(self.s3_folder_dataset_id)
        self.files = self.input_folder.list_contents().get("items", [])
        self.toc_page_limit = 20
        print(f"Found {len(self.files)} files.")
        
        # Snowflake configs
        self.snowflake_conn = self.config.get("snowflake_connection_string")
        self.table_file_upload = self.config.get("ecs", {}).get("ecs_file_upload", {})
        
        # Precompiled regex
        self.pattern_field_value = re.compile(r'^(?P<field>.+?)(?:\t|\s{2,})+(?P<value>.+?)\s*$')
        self.pattern_continuation = re.compile(r'^(?!\s)(?!.*\s$)(?P<value>.+)$')
    
    def _clean_summary(self, text):
        text = re.sub(r'\s+', ' ', text).strip()
        if not text.endswith('.'):
            text += '.'
        return text
    
    def _update_progress(self, file_id, percent):
        update_query = f"""
            UPDATE {self.table_file_upload}
            SET "digitization_percent" = '{percent}'
            WHERE "crf_file_id" = '{file_id}';
        """
        self.client.sql_query(query=update_query, connection=self.snowflake_conn, post_queries=["COMMIT"])
    
    def _extract_fields_from_page(self, page_text):
        lines = page_text.split("\n")
        header_lines, field_value_map = [], {}
        current_field = None
        in_field_section = False

        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if not in_field_section:
                if "generated" in line.lower():
                    in_field_section = True
                    continue
                header_lines.append(line)
            else:
                m = self.pattern_field_value.match(line)
                p = self.pattern_continuation.match(line)

                if m:
                    current_field = m.group("field").strip()
                    value = m.group("value").strip()
                elif p and current_field:
                    value = p.group("value").strip()
                else:
                    continue

                field_value_map.setdefault(current_field, []).append(value)

        # Format fields for output
        final_fields = [{"field_name": k, "field_value": v} for k, v in field_value_map.items()]
        header_text = " ".join([h for h in header_lines if "form" in h.lower() or "folder" in h.lower()])

        return header_text, final_fields
    
    def historical_mapping(self, file_path, file_id):
        response = []

        try:
            # Load PDF
            with self.input_folder.get_file(file_path) as stream:
                pdf_file_like = io.BytesIO(stream.raw.data)

            with pdfplumber.open(pdf_file_like) as pdf:
                total_pages = len(pdf.pages)
                last_update_range = -1

                for page_num, page in enumerate(pdf.pages):
                    percent = int((page_num / total_pages) * 100)
                    current_range = (percent // 10) * 10
                    if current_range != last_update_range and 10 <= percent < 100:
                        self._update_progress(file_id, percent)
                        last_update_range = current_range

                    page_text = page.extract_text(layout=True)
                    if not page_text or "field name" in page_text.lower():
                        continue

                    header_text, final_fields = self._extract_fields_from_page(page_text)
                    if not final_fields or not header_text:
                        continue

                    res = {
                        "template_name": os.path.basename(file_path),
                        "path": file_path,
                        "id": uuid4().hex,
                        "source_data": {
                            "assessments": header_text,
                            "fields": final_fields
                        }
                    }
                    response.append(res)

        except Exception as e:
            print(f"Error processing file {file_path}: {e}")

        return response
