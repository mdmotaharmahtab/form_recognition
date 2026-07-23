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

class CRFFuzzyMatcher:
    def __init__(self, opensearch_client,client,proj, llm_fallback={"form_field_value": f"Not found"}, score_threshold=0.40):
        """
        :param opensearch_client: Initialized OpenSearch client
        :param index_name: Name of the OpenSearch index
        :param llm_fallback: Function(form_name, field_name) -> dict | None
        :param score_threshold: Threshold for LLM fallback (0–1)
        """
        self.opensearch_client = OpensearchUtil(client, proj).opensearch_client
        #self.opensearch_client = opensearch_client
        self.index_name = proj.get_variables()['local'].get('ecs_opensearch')
        dataiku_project_var = "${projectKey}"
        if dataiku_project_var in self.index_name:
            # Replace projectKey placeholder with actual project key
            self.index_name = self.index_name.replace(dataiku_project_var, opensearch_client.project.project_key).lower()
        self.proj = proj
        
        self.llm_fallback = llm_fallback
        self.score_threshold = score_threshold
        self._embedding_cache = {} 

    #from rapidfuzz import process, fuzz
    
    
    def get_all_standard_forms(self):
        """
        Fetch all unique standard form names from OpenSearch once.
        """
        query_all_forms = {
            "size": 1000,  # adjust if you have more than 1000 forms
            "_source": ["form_name"],
            "query": {
                "bool": {
                    "must": {"match_all": {}},
                    "filter": [
                        {"term": {"source.keyword": "Standard"}}
                    ]
                }
            }
        }

        res = self.opensearch_client.search(index=self.index_name, body=json.dumps(query_all_forms))
        hits = res.get("hits", {}).get("hits", [])
        return [hit["_source"]["form_name"] for hit in hits]


    def get_standard_crf(self, form_name,all_form_names,field_names):
        """
        Fetch CRF standards using fuzzy matching for form_name first.
        Then query OpenSearch for the matched standard form.
        """
        if not form_name:
            return None

        form_name_clean = form_name.strip()

        # Step 1: Get list of all unique standard form names from OpenSearch
        

        if not all_form_names:
            return None

        # Step 2: Fuzzy match input form_name to standard form
#         matched_form, score, _ = process.extractOne(
#             form_name_clean, all_form_names, scorer=fuzz.partial_ratio
#         )
        matched_form = process.extract(form_name_clean, all_form_names, scorer=fuzz.partial_ratio,score_cutoff=70)
        
        
#         from soa_extraction.opensearch_utils import OpensearchUtil
        import nest_asyncio
        import asyncio
#         nest_asyncio.apply()
#         m = OpensearchUtil(client, proj)
#         embed_response = m.create_embedding(field_names,  proj.get_variables()['local'].get('default_embeddings_model_id'))
       
#         vec = embed_response["response"]
        
        
#         if score < 70:
#             return None
        # Step 3: Query OpenSearch for the matched standard form
        
#         print(f"😶 This is the matched form name : ",matched_form)
        
        return matched_form
        
        query = {
            "size": 10000,  # adjust if you have more than 1000 forms
#             "_source": ["form_name"],
            "query": {
                "bool": {
                    "must": {"match_all": {}},
                    
                    "filter": [
                        {"term": {"form_name.keyword": matched_form}}
                    ]
                }
            }
        }

        res_std = self.opensearch_client.search(index=self.index_name, body=json.dumps(query))
        hits_std = res_std.get("hits", {}).get("hits", [])

        if not hits_std:
            return pd.DataFrame([])

        results = [hit["_source"] for hit in hits_std]

        return pd.DataFrame([
            {
                "validation_id": item.get("validation_id"),
                "ecs_id": item.get("ecs_id"),
                "form_id": item.get("form_id"),
                "form_name": item.get("form_name"),
                "form_field_value": item.get("form_field_value"),
                "validation_logic": item.get("validation_logic"),
                "reasoning": item.get("reasoning"),
                "action": item.get("action"),
                "source": item.get("source"),
                "action_details": item.get("action_details"),
                "path" : item.get("path")
            }
            for item in results
        ])
    
    def get_all_historical_forms(self):
        """
        Fetch all unique standard form names from OpenSearch once.
        """
        query_all_forms = {
            "size": 1000,  # adjust if you have more than 1000 forms
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
    
    
    def search_knn_with_reranking(self, form_names, query_vector, field_name, sourcetype, top_k=10):
        """
        Advanced re-ranking that prioritizes:
        1. Multi-word phrase matches (e.g., "version number" as a phrase)
        2. Token overlap
        3. Semantic similarity
        4. Fuzzy string match
        """
        # First, get semantic matches
        query = {
            "size": top_k * 3,  # Get more candidates for re-ranking
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
                                    "k": top_k * 3
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

        # Re-ranking logic with phrase detection
        import re
        from rapidfuzz import fuzz

        # Prepare query analysis
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'was', 'were', 'is', 'are'}
        query_lower = field_name.lower()
        query_tokens = set(re.findall(r'\b\w+\b', query_lower))
        query_tokens = {t for t in query_tokens if t not in stopwords and len(t) > 2}

        # Extract bigrams and trigrams from query for phrase matching
        query_words = [w for w in re.findall(r'\b\w+\b', query_lower) if w not in stopwords]
        query_bigrams = set()
        query_trigrams = set()

        for i in range(len(query_words) - 1):
            query_bigrams.add(f"{query_words[i]} {query_words[i+1]}")

        for i in range(len(query_words) - 2):
            query_trigrams.add(f"{query_words[i]} {query_words[i+1]} {query_words[i+2]}")

        results = []
        for hit in hits:
            src = hit["_source"]
            field_value = src.get("form_field_value", "")
            field_lower = field_value.lower()

            # Calculate multiple similarity metrics
            knn_score = hit["_score"]

            # 1. Token overlap score
            field_tokens = set(re.findall(r'\b\w+\b', field_lower))
            field_tokens = {t for t in field_tokens if t not in stopwords and len(t) > 2}

            if query_tokens:
                token_overlap = len(query_tokens & field_tokens) / len(query_tokens)
            else:
                token_overlap = 0.0

            # 2. Phrase matching (bigrams and trigrams)
            field_words = [w for w in re.findall(r'\b\w+\b', field_lower) if w not in stopwords]
            field_bigrams = set()
            field_trigrams = set()

            for i in range(len(field_words) - 1):
                field_bigrams.add(f"{field_words[i]} {field_words[i+1]}")

            for i in range(len(field_words) - 2):
                field_trigrams.add(f"{field_words[i]} {field_words[i+1]} {field_words[i+2]}")

            # Score phrase matches (more weight for longer phrases)
            phrase_score = 0.0
            if query_trigrams and field_trigrams:
                trigram_overlap = len(query_trigrams & field_trigrams) / len(query_trigrams)
                phrase_score += trigram_overlap * 4.0  # Highest weight for 3-word phrases

            if query_bigrams and field_bigrams:
                bigram_overlap = len(query_bigrams & field_bigrams) / len(query_bigrams)
                # Only count bigram if it's NOT just "informed consent" when we have more specific terms
                # Check if the last word in query is a specific term (date, time, number, etc.)
                specific_terms = {'date', 'time', 'number', 'version', 'code', 'value', 'status', 'type', 'name', 'id'}
                has_specific_term = bool(query_tokens & specific_terms)

                if has_specific_term:
                    # Weight bigrams that include the specific term more heavily
                    matching_bigrams = query_bigrams & field_bigrams
                    specific_bigram_found = False
                    for bigram in matching_bigrams:
                        if any(term in bigram for term in (query_tokens & specific_terms)):
                            specific_bigram_found = True
                            break

                    if specific_bigram_found:
                        phrase_score += bigram_overlap * 3.0  # High weight for specific bigrams
                    else:
                        phrase_score += bigram_overlap * 0.5  # Low weight for generic bigrams like "informed consent"
                else:
                    phrase_score += bigram_overlap * 2.0  # Normal weight when no specific terms

            # 3. Fuzzy string similarity
            fuzzy_score = fuzz.token_sort_ratio(field_name, field_value) / 100.0

            # 4. Penalty for question-type fields (they're usually not data fields)
            question_penalty = 0.0
            if '?' in field_value or field_value.lower().startswith(('was ', 'is ', 'are ', 'were ', 'has ', 'have ', 'did ', 'does ', 'do ')):
                question_penalty = 3.0  # Strong penalty for questions (increased from 0.5)

            # 5. Length similarity bonus (fields with similar length are often more related)
            len_ratio = min(len(field_name), len(field_value)) / max(len(field_name), len(field_value))
            length_bonus = len_ratio * 0.5

            # Combined score with adjusted weights
            combined_score = (
                0.3 * knn_score +           # Semantic similarity (reduced weight)
                3.0 * token_overlap +        # Individual token matches (increased)
                5.0 * phrase_score +         # Multi-word phrase matches (HIGH priority, increased)
                1.0 * fuzzy_score +          # Overall string similarity
                length_bonus -               # Bonus for similar length
                question_penalty             # Penalty for question-type fields (now 3.0)
            )

            src["knn_score"] = knn_score
            src["token_overlap"] = token_overlap
            src["phrase_score"] = phrase_score
            src["fuzzy_score"] = fuzzy_score
            src["question_penalty"] = question_penalty
            src["combined_score"] = combined_score

            results.append(src)

        # Sort by combined score
        df = pd.DataFrame(results)
        df = df.sort_values('combined_score', ascending=False).head(top_k)

        # Debug output
        print(f"\n📊 Top 3 re-ranked matches for '{field_name}':")
        for idx, row in df.head(3).iterrows():
            penalty_str = f", Penalty: {row['question_penalty']:.2f}" if row['question_penalty'] > 0 else ""
            print(f"  Combined: {row['combined_score']:.3f} (kNN: {row['knn_score']:.3f}, "
                  f"Token: {row['token_overlap']:.3f}, Phrase: {row['phrase_score']:.3f}, "
                  f"Fuzzy: {row['fuzzy_score']:.3f}{penalty_str})")
            print(f"    → {row['form_field_value']}")

        return df


    def search_knn_hybrid(self, form_names, query_vector, field_name, sourcetype, top_k=10):
        """
        Hybrid search using OpenSearch query-time boosting.
        Less control than re-ranking but faster.
        """
        import re
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                     'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been'}

        tokens = re.findall(r'\b\w+\b', field_name.lower())
        important_tokens = [t for t in tokens if t not in stopwords and len(t) > 2]

        # Build should clauses
        should_clauses = []

        # Individual token matches
        for token in important_tokens:
            should_clauses.append({
                "match": {
                    "form_field_value": {
                        "query": token,
                        "boost": 1.5
                    }
                }
            })

        # Bigram phrase matches (higher boost)
        words = [w for w in re.findall(r'\b\w+\b', field_name.lower()) if w not in stopwords]
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            should_clauses.append({
                "match_phrase": {
                    "form_field_value": {
                        "query": bigram,
                        "boost": 4.0,
                        "slop": 1
                    }
                }
            })

        # Full phrase match (highest boost)
        should_clauses.append({
            "match_phrase": {
                "form_field_value": {
                    "query": field_name,
                    "boost": 5.0,
                    "slop": 2
                }
            }
        })

        # Penalize questions
        must_not_clauses = []

        query = {
            "size": top_k * 3,
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
                                    "k": top_k * 3
                                }
                            }
                        }
                    ],
                    "should": should_clauses,
                    "filter": [
                        {"term": {"source.keyword": sourcetype}},
                        {"terms": {"form_name.keyword": form_names}}
                    ],
#                     "minimum_should_match": 0
                }
            }
        }

        
        res = self.opensearch_client.search(index=self.index_name, body=json.dumps(query))
        hits = res.get("hits", {}).get("hits", [])

        results = []
        for hit in hits:
            src = hit["_source"]
            src["knn_score"] = hit["_score"]
            results.append(src)

        df = pd.DataFrame(results)
        if not df.empty:
            df = df.sort_values('knn_score', ascending=False).head(top_k)

        return df


    def search_knn(self, form_names, query_vector, sourcetype, field_name, top_k=10):
        """
        Main search method - uses advanced re-ranking by default.
        """
        return self.search_knn_with_reranking(
            form_names, query_vector, field_name, sourcetype, top_k
        )
    
    
    def make_llm_call_batch(self,form_name, field_names_list):
        
        """
        Modified LLM call that generates validation rules for multiple fields at once.

        Args:
            form_name: Name of the form
            field_names_list: List of field names for this form

        Returns:
            List of validation rule dictionaries
        """
        # Format field names as a numbered list for the prompt
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
            # Get LLM from project
            default_llm_model = self.proj.get_variables()['local'].get('default_llm_model')
            llm = self.proj.get_llm(default_llm_model).as_langchain_llm(
                completion_settings={
                    "temperature": 0,
                    "timeout": 300,
                    "max_tokens": 16000  # Increased for batch processing
                }
            )

            output = llm.invoke(prompt)
            return output

        except Exception as e:
            print(f"❌ LLM batch call failed for form '{form_name}': {e}")
            return None


    def parse_llm_batch_output(self,llm_response, form_name, field_names_list):
        """
        Parse LLM batch response and ensure all fields are covered.

        Returns:
            Dictionary mapping field_name -> validation_dict
        """
        try:
            # Clean response
            response_text = str(llm_response)
            response_text = re.sub(r'```json\s*', '', response_text)
            response_text = re.sub(r'```\s*', '', response_text)
            response_text = response_text.strip()

            # Parse JSON
            parsed = json.loads(response_text)

            if not isinstance(parsed, list):
                print(f"⚠️ LLM returned non-array for '{form_name}'")
                return {}

            # Map results by field name
            results_map = {}
            for item in parsed:
                if 'error' in item:
                    continue

                field_value = item.get("form_field_value", "")
                if field_value:
                    # Normalize the field name for matching
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

            # Check coverage
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

    def create_default_validation(self,form_name, field_name):
        """
        Create a basic validation rule when LLM fails or misses a field.
        Returns minimal structure - let user handle domain mapping themselves.
        """
        variable_name = field_name.upper().replace(' ', '_')
        variable_name = ''.join(c for c in variable_name if c.isalnum() or c == '_')

        return {
            "validation_id": None,  # Don't try to generate - unreliable without proper domain
            "ecs_id": None,
            "form_id": None,
            "form_name": form_name,
            "form_field_value": field_name,
            "variable_name": variable_name,
            "form_domain_name": None,  # Don't guess - could be wrong
            "validation_logic": f"{field_name} must not be blank when enterable",
            "reasoning": "Default validation - LLM failed to generate rule",
            "action": "Manual review required",
            "action_details": f"LLM did not generate validation rule for {field_name}",
            "source": "LLM_FAILED",  # Clear indicator this needs attention
            "path": None
        }

    
    def fuzzy_match_fields(self, sub_data):
        """
        Run field matching using semantic similarity instead of fuzzy text.
        """
        output_list = []

        all_standard_forms = self.get_all_standard_forms()
        all_historical_forms = self.get_all_historical_forms()

        print("Fetched forms:", len(all_standard_forms), "standard,", len(all_historical_forms), "historical")
        unmatched_by_form = {}
        for row in sub_data:
            form_name = row.get("form_name")
            field_name = row.get("field_name")

            if not form_name or not field_name:
                continue

            print(f"🔍 Matching: {form_name} — {field_name}")
            matched_row = None

            # ---------- STEP 1: Try Standard ----------
            # ---------- STEP 1: Try Standard ----------
            if matched_row is None:
                reference_df = self.get_standard_crf(form_name, all_standard_forms, field_name)
                
                name_list = []
                if reference_df:
                    for kh in reference_df:
                        name_list.append(kh[0])
                    print(list(set(name_list)))
                    # Embed the query field once
                    query_vec = np.array(
                        asyncio.run(
                            create_embeddings_new(self.proj, [field_name], self.proj.get_variables()['local'].get('default_embeddings_model_id'))
                        )["response"][0]
                    ).tolist()

                    # Use OpenSearch kNN search for top 10 most similar fields
                    knn_df = self.search_knn(list(set(name_list)), query_vec,"Standard",field_name, top_k=10)
                    if not knn_df.empty:
                        best_row = knn_df.iloc[0].to_dict()
                        best_score = best_row.get("knn_score", 0.0)
                        print(f"🔥 OpenSearch top match for {field_name}: {best_row['form_field_value']} (score={best_score:.3f})")

                        if best_score >= self.score_threshold:
                            matched_row = best_row
                            matched_row.update({
                                "original_form_name": form_name,
                                "original_field": field_name,
                                "score": best_score
                            })
                            output_list.append(matched_row)
                            continue


            # ---------- STEP 2: Try Historical ----------
            if matched_row is None:
                reference_df = self.get_standard_crf(form_name, all_historical_forms, field_name)
              
                if reference_df:
                    name_list = []
                    if reference_df:
                        for kh in reference_df:
                            name_list.append(kh[0])
                    print(list(set(name_list)))
                    # Embed the query field once
                    query_vec = np.array(
                        asyncio.run(
                            create_embeddings_new(self.proj, [field_name], self.proj.get_variables()['local'].get('default_embeddings_model_id'))
                        )["response"][0]
                    ).tolist()

                    # Use OpenSearch kNN search for top 10 most similar fields
                    knn_df = self.search_knn(list(set(name_list)), query_vec,"Historic",field_name, top_k=10)
                    if not knn_df.empty:
                        best_row = knn_df.iloc[0].to_dict()
                        best_score = best_row.get("knn_score", 0.0)
                        print(f"🔥 OpenSearch top match for {field_name}: {best_row['form_field_value']} (score={best_score:.3f})")

                        if best_score >= self.score_threshold:
                            matched_row = best_row
                            matched_row.update({
                                "original_form_name": form_name,
                                "original_field": field_name,
                                "score": best_score
                            })
                            output_list.append(matched_row)
                            continue
                
            '''if matched_row is None:
                if form_name not in unmatched_by_form:
                    unmatched_by_form[form_name] = []
                unmatched_by_form[form_name].append(row)
                print(f"  ⏳ No match - queued for LLM batch")    ''' 
            

             # ---------- STEP 3: LLM fallback ----------
            if matched_row is None or matched_row["score"] < self.score_threshold:
                
                llm_output = {
                 "ecs_id": matched_row.get("ecs_id") if matched_row else None,
                 "form_id": matched_row.get("form_id") if matched_row else None,
                 "original_form_name": form_name,
                 "original_field": field_name,
                 "score": matched_row.get("score") if matched_row else None,
                 "source": "LLM Generated"
                }
                print(f"❌ No strong semantic match; falling back to LLM for {form_name}")
                output_list.append(llm_output)
                    
        
                    
            

        return output_list