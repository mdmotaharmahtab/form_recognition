import time
import json
import pandas as pd
from rapidfuzz import fuzz, process
from crf_extraction_module.opensearch_utils import OpensearchUtil, create_embeddings_new
import asyncio
import nest_asyncio
import numpy as np
import json
import pandas as pd
import re
import uuid

class CRFFuzzyMatcher:
    def __init__(self, opensearch_client,client,proj,llm_fallback={"form_field_value": f"Not found"}, score_threshold=0.40):
        """
        :param opensearch_client: Initialized OpenSearch client
        :param llm_fallback: Function(form_name, field_name) -> dict | None
        :param score_threshold: Threshold for LLM fallback (0–1)
        """
        self.opensearch_client = OpensearchUtil(client, proj).opensearch_client
        self.index_name = proj.get_variables()['local'].get('ecs_opensearch')
        dataiku_project_var = "${projectKey}"
        if dataiku_project_var in self.index_name:
            self.index_name = self.index_name.replace(dataiku_project_var, opensearch_client.project.project_key).lower()
        
        self.llm_fallback = llm_fallback
        self.score_threshold = score_threshold
        self._embedding_cache = {} 

    def get_all_standard_forms(self):
        """
        Fetch all unique standard form names from OpenSearch once.
        """
        query_all_forms = {
            "size": 5000,
            "_source": ["form_name"],
            "query": {
                "bool": {
                    "must": {"match_all": {}},
                    
                }
            }
        }

        res = self.opensearch_client.search(index=self.index_name, body=json.dumps(query_all_forms))
        hits = res.get("hits", {}).get("hits", [])
        return [hit["_source"]["form_name"] for hit in hits]

    def get_all_historical_forms(self):
        """
        Fetch all unique historical form names from OpenSearch once.
        """
        query_all_forms = {
            "size": 1000,
            "_source": ["form_name"],
            "query": {
                "bool": {
                    "must": {"match_all": {}},
                    "filter": [
                        {"term": {"source.keyword": "Historic"}}
                    ]
                }
            }
        }

        res = self.opensearch_client.search(index=self.index_name, body=json.dumps(query_all_forms))
        hits = res.get("hits", {}).get("hits", [])
        return [hit["_source"]["form_name"] for hit in hits]

    def get_standard_crf(self, form_name, all_form_names):
        """
        Fetch CRF standards using fuzzy matching for form_name first.
        Then query OpenSearch for the matched standard form.
        """
        if not form_name:
            return None

        form_name_clean = form_name.strip()

        if not all_form_names:
            return None

        from rapidfuzz import process, fuzz
        matched_form = process.extract(form_name_clean, all_form_names, scorer=fuzz.partial_ratio, score_cutoff=70,limit=len(all_form_names))
        if form_name == "IMP Administration":
            
            print("all match form",matched_form,all_form_names)
            
        return matched_form
    
    def get_all_field_oids_forms(self,form_name,key_name):
        
    
        query = {
                "size": 10000,  # adjust if you have more than 1000 forms
    #             "_source": ["form_name"],
                "query": {
                    "bool": {
                        "must": {"match_all": {}},
                        "filter": key_name
                    }
                }
            }

        res_std = self.opensearch_client.search(index=self.index_name, body=json.dumps(query))
        hits_std = res_std.get("hits", {}).get("hits", [])

        if not hits_std:
            return []

        results = [hit["_source"] for hit in hits_std]
        print("len of results",len(results))
        return [
            {
                "validation_id": item.get("validation_id"),
                "ecs_id": item.get("ecs_id"),
                "form_id": item.get("form_id"),
                "form_name": item.get("form_name"),
                "form_field_value": item.get("form_field_value"),
                "validation_logic": item.get("validation_logic"),
                "reasoning": item.get("reasoning"),
                "indication" : item.get("indication"),
                "molecule" : item.get("molecule"),
                "ta" : item.get("ta"),
                "field_oids" : item.get("field_oids"),
                "action": item.get("action"),
                "source": item.get("source"),
                "action_details": item.get("action_details"),
                "path" : item.get("path")
            }
            for item in results
        ] 

    def search_knn(self, form_names, query_vector, sourcetype, field_name, top_k=10):
        """
        Pure semantic search using OpenSearch kNN.
        Returns top_k results based solely on vector similarity.
        """
        query = {
            "size": top_k,
            "_source": [
                "validation_id", "ecs_id", "form_id", "form_name",
                "form_field_value", "validation_logic", "reasoning",
                "action", "action_details", "source", "path"
            ],
            "query": {
                "bool": {
                    "must": [
                        {
                            "knn": {
                                "form_field_vector": {
                                    "vector": query_vector,
                                    "k": top_k
                                }
                            }
                        }
                    ],
                    "filter": [
                        {"term": {"source.keyword": sourcetype}},
                        {"terms": {"form_name.keyword": form_names}}
                    ]
                }
            }
        }

        res = self.opensearch_client.search(index=self.index_name, body=json.dumps(query))
        hits = res.get("hits", {}).get("hits", [])

        if not hits:
            return pd.DataFrame()

        results = []
        for hit in hits:
            src = hit["_source"]
            src["knn_score"] = hit["_score"]
            results.append(src)

        df = pd.DataFrame(results)
        
        # Debug output
        if not df.empty:
            print(f"\n📊 Top 3 semantic matches for '{field_name}':")
            for idx, row in df.head(3).iterrows():
                print(f"  Score: {row['knn_score']:.3f}")
                print(f"    → {row['form_field_value']}")

        return df

    def make_llm_call_batch(self, form_name, field_names_list):
        """
        Modified LLM call that generates validation rules for multiple fields at once.
        """
        fields_str = "\n".join([f"{i+1}. {field}" for i, field in enumerate(field_names_list)])

        prompt = f"""You are an Edit Check Specification Specialist for Case Report Forms (CRFs). 

            Generate validation rules for the following form and its fields:

            **Form Name:** {form_name}

            **Field Names:**
            {fields_str}

            **Instructions:**
            1. Return ONLY a JSON array (no markdown, no explanations, no code fences)
            2. Generate one validation object per field
            3. Each object must have these exact keys:
               - validation_id
               - form_name
               - form_domain_name
               - form_field_value (the field name)
               - variable_name (UPPERCASE snake_case of field name)
               - validation_logic
               - reasoning
               - action
               - action_details
               - source (set to "LLM Generated")

            4. **Deterministic Rules:**
               - variable_name: Convert field name to UPPERCASE_SNAKE_CASE
               - form_domain_name: Use standard mappings (Demographics->DM, Medical History->MH, Vital Signs->VS, Adverse Event->AE, Concomitant Meds->CM, Informed Consent->IC, Physical Examination->PE, Laboratory->LB). If not mapped, use first 2-3 letters of each word.
               - validation_id: Use format "MVAL_{{domain}}_{{sequential_number}}" (e.g., MVAL_DM_001, MVAL_DM_002)

            5. **Validation Logic Rules** (apply as appropriate):
               - Date fields: Must not be in future, must be valid date
               - Time fields: Must be valid 24-hour format
               - Number fields: Must be numeric, appropriate range
               - Yes/No questions: Must have selection
               - Required fields: Must not be blank when enterable
               - "Other specify" fields: Required when "Other" is selected
               - Status/Code fields: Must match controlled vocabulary

            6. **Important:**
               - Generate rules in the SAME ORDER as the field list above
               - Do not skip any fields
               - Keep validation_logic concise but specific
               - If a field type is unclear, generate a basic "must not be blank" rule

            Return only the JSON array, nothing else.
            """

        try:
            default_llm_model = proj.get_variables()['local'].get('default_llm_model')
            llm = proj.get_llm(default_llm_model).as_langchain_llm(
                completion_settings={
                    "temperature": 0,
                    "timeout": 300,
                    "max_tokens": 16000
                }
            )

            output = llm.invoke(prompt)
            return output

        except Exception as e:
            print(f"❌ LLM batch call failed for form '{form_name}': {e}")
            return None

    def parse_llm_batch_output(self, llm_response, form_name, field_names_list):
        """
        Parse LLM batch response and ensure all fields are covered.
        """
        try:
            response_text = str(llm_response)
            response_text = re.sub(r'```json\s*', '', response_text)
            response_text = re.sub(r'```\s*', '', response_text)
            response_text = response_text.strip()

            parsed = json.loads(response_text)

            if not isinstance(parsed, list):
                print(f"⚠️ LLM returned non-array for '{form_name}'")
                return {}

            results_map = {}
            for item in parsed:
                if 'error' in item:
                    continue

                field_value = item.get("form_field_value", "")
                if field_value:
                    results_map[field_value.strip().lower()] = {
                        "validation_id": item.get("validation_id"),
                        "ecs_id": None,
                        "form_id": None,
                        "form_name": item.get("form_name", form_name),
                        "form_field_value": field_value,
                        "validation_logic": item.get("validation_logic"),
                        "reasoning": item.get("reasoning"),
                        "action": item.get("action"),
                        "action_details": item.get("action_details"),
                        "source": "LLM Generated",
                        "path": None,
                        "variable_name": item.get("variable_name"),
                        "form_domain_name": item.get("form_domain_name")
                    }

            missing_fields = []
            for field in field_names_list:
                if field.strip().lower() not in results_map:
                    missing_fields.append(field)

            if missing_fields:
                print(f"⚠️ LLM missed {len(missing_fields)} fields for '{form_name}': {missing_fields[:3]}...")

            return results_map

        except json.JSONDecodeError as e:
            print(f"❌ JSON parse error for '{form_name}': {e}")
            print(f"Response preview: {response_text[:300]}...")
            return {}
        except Exception as e:
            print(f"❌ Parse error for '{form_name}': {e}")
            return {}

    def create_default_validation(self, form_name, field_name):
        """
        Create a basic validation rule when LLM fails or misses a field.
        """
        variable_name = field_name.upper().replace(' ', '_')
        variable_name = ''.join(c for c in variable_name if c.isalnum() or c == '_')

        return {
            "validation_id": None,
            "ecs_id": None,
            "form_id": None,
            "form_name": form_name,
            "form_field_value": field_name,
            "variable_name": variable_name,
            "form_domain_name": None,
            "validation_logic": f"{field_name} must not be blank when enterable",
            "reasoning": "Default validation - LLM failed to generate rule",
            "action": "Manual review required",
            "action_details": f"LLM did not generate validation rule for {field_name}",
            "source": "LLM_FAILED",
            "path": None
        }

    def is_subset(self,left, right):
        left_set = set(left)
        right_set = set(right)
        return left_set.issubset(right_set)

    


    def fuzzy_match_fields(self, sub_data,indication,molecule,ta):
        """
        Run field matching using semantic similarity only.
        """
        output_list = []

        all_standard_forms = self.get_all_standard_forms()
#         all_historical_forms = self.get_all_historical_forms()

        print("Fetched forms:", len(all_standard_forms))
        unmatched_by_form = {}

        final_answer = [] 
        fecthed_all_field_oids = []
        
        for each_form_oid in sub_data:
            field_oids_copy = each_form_oid.get("field_oids")
            fecthed_all_field_oids += field_oids_copy
            
        fecthed_all_field_oids = list(set(fecthed_all_field_oids))
        
            
        for row in sub_data:
            
            form_name = row.get("form_name")
            field_oids = row.get("field_oids")
            all_fields = row.get("fields")

            if not form_name or not field_oids:
                continue

#             print(f"🔍 Matching: {form_name} — {field_oids}")
            matched_row = None

#             # STEP 1: try pulling all the editchecks based on form name 
            if matched_row is None:
                reference_df = self.get_standard_crf(form_name, all_standard_forms)
               
                
                
                name_list = []
                if reference_df:
                    for kh in reference_df:
                        
                        name_list.append(kh[0])
                       
                    get_all_related_forms = []
                    
                    name_list = list(set(name_list))
                    
                    
                    for each_form_name in name_list:
                        terms = []
                        if form_name == "IMP Administration":
                            print("--->kh",name_list)

                        if molecule:
                            terms.append( {"term": {f"molecule.keyword": molecule}})
                            terms.append( {"term": {f"source.keyword": "Historical"}})
                        elif indication :
                            terms.append( {"term": {f"indication.keyword": indication}})
                            terms.append( {"term": {f"source.keyword": "Historical"}})
                        elif ta:
                            terms.append( {"term": {f"ta.keyword": ta}})
                            terms.append( {"term": {f"source.keyword": "Historical"}})


                        stad_term = [{"term": {f"source.keyword": "Standard"}}] 

                        terms.append({"term": {"form_name.keyword": each_form_name}})
                        stad_term.append({"term": {"form_name.keyword": each_form_name}})
                        if each_form_name == "IMP Administration":
                            print("----+>",terms)
                            
                        data_mapping = self.get_all_field_oids_forms(each_form_name,terms)
                        
                        std_data_mapping = self.get_all_field_oids_forms(each_form_name,stad_term)
                        if each_form_name == "IMP Administration":
                            print("std_data_mapping--->",std_data_mapping,data_mapping)
                        get_all_related_forms += data_mapping
                        if len(std_data_mapping) > 0:
                            get_all_related_forms += std_data_mapping
                            
                        
                   
                    
                    seperate_standard_form = []
                    seperate_historical_form = []
                    
                    for each_source in get_all_related_forms:
                        if "Standard" == each_source['source']:
                            seperate_standard_form.append(each_source)
                        else :
                            #if molecule == each_source["molecule"]:
                            seperate_historical_form.append(each_source)
                            #elif indication == each_source["indication"]:
                               # seperate_historical_form.append(each_source)
                            #elif ta == each_source["ta"]:
                                #seperate_historical_form.append(each_source)
                            #else:
                                #seperate_historical_form.append(each_source)
                    #step 2 checking in standard for checks 
                    import ast
                    
                    llm_process = False
#                     print("form name :",form_name,len(seperate_historical_form))
                    for each_standard_form in seperate_standard_form:
                        std_field_oids = ast.literal_eval(each_standard_form["field_oids"])
                        #if  self.is_subset(std_field_oids,field_oids) and len(std_field_oids)> 0:
                            #llm_process =  self.is_subset(std_field_oids,field_oids)
                        if  self.is_subset(std_field_oids,fecthed_all_field_oids) and len(std_field_oids)> 0:
                            llm_process =  self.is_subset(std_field_oids,fecthed_all_field_oids)
                            each_standard_form["form_name"] = form_name
                            final_answer.append(each_standard_form)
                        
                      
                    for each_historical_form in seperate_historical_form:
                        hst_field_oids = ast.literal_eval(each_historical_form["field_oids"])
                       
                       
                        #if self.is_subset(hst_field_oids,field_oids) and len(hst_field_oids)> 0:
                            #llm_process =  self.is_subset(hst_field_oids,field_oids)
                        if self.is_subset(hst_field_oids,fecthed_all_field_oids) and len(hst_field_oids)> 0:
                            llm_process =  self.is_subset(hst_field_oids,fecthed_all_field_oids)
                            each_historical_form["form_name"] = form_name
                            final_answer.append(each_historical_form)
                            
                            
                    # print("------------>",fecthed_all_field_oids)
                    
                    if not llm_process:
                        for each_fields in all_fields:
                            
                        
                           final_answer.append(
                            {
                                "validation_id": "",
                                "ecs_id": str(uuid.uuid4()),
                                "form_id": "",
                                "form_name": form_name,
                                "form_field_value": each_fields['field_name'],
                                
                                "validation_logic":"",
                                "reasoning": "",
                                "indication" :"",
                                "molecule" : "",
                                "ta" : "",
                                "field_oids" : field_oids,
                                "action": "",
                                "source": "LLM Generated",
                                "action_details": "",
                                "path" : ""
                            })
                            
                
                else:
                    
                    for each_fields in all_fields:
                        
                        final_answer.append(
                        {
                            "validation_id": "",
                            "ecs_id": str(uuid.uuid4()),
                            "form_id": "",
                            "form_name": form_name,
                            "form_field_value": each_fields['field_name'],

                            "validation_logic":"",
                            "reasoning": "",
                            "indication" :"",
                            "molecule" : "",
                             "ta" : "",
                            "field_oids" : field_oids,
                            "action": "",
                            "source": "LLM Generated",
                            "action_details": "",
                            "path" : ""
                        })
                
        return final_answer          
                              
