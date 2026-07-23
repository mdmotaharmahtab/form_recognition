
import json
import dataikuapi
# from langgraph.checkpoint.memory import MemorySaver
# from langchain_core.messages import HumanMessage
from langchain.schema import AIMessage
import time
import pandas as pd
from datetime import datetime
from opensearchpy import OpenSearch
import json
from opensearchpy.helpers import bulk
import uuid
import asyncio
import nest_asyncio
import numpy as np

    
# def opensearch_retrieval_node(state: ChartState) -> ChartState:
#     query = state["query"]
#     doc_id = state.get("doc_id")
#     k = state.get("top_k", 3)
#     proj = state["proj"]
#     proj_variables = proj.get_variables()["local"]

#     index_name = proj_variables.get("opensearch_index")
#     index_name = index_name.replace("${projectKey}", proj.project_key).lower()

#     opensearch_client = OpensearchUtil(state["client"], proj)
#     context_docs = opensearch_client.search_similar_documents(index_name, query, k=k, doc_id=doc_id)

#     combined_text = "\n".join(doc['content'] for doc in context_docs)
#     messages = [HumanMessage(content=query)]

#     return {
#         **state,
#         "context": combined_text,
#         "documents": context_docs,
#         "messages": messages,
#     }


async def create_embeddings_new(proj, chunks, model_id):
        """
        Generates embeddings for a given text chunk using the specified model.

        Arguments:
            proj (object): The project object to retrieve the LLM (Language Learning Model).
            chunks (str): The text chunk to generate embeddings for.
            model_id (str): The ID of the embedding model to be used.

        Returns:
            dict: A dictionary with 'success' (bool) and 'response' (embedding vector) or 'message' (str) if an error occurs.
        """
        try:
            llm = proj.get_llm(model_id).as_langchain_embeddings()

            # Create embeddings of the provided chunk
            embeddings = await llm.aembed_documents(chunks)
            return {
                "success": True,
                "response": embeddings
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": str(e)
            }

class OpensearchUtil:

    def __init__(self, client, proj):

        self.project = proj
        
        # Retrieve credentials from Opensearch connection 
        self.project_configs = self.project.get_variables()["local"]
        opensearch_connection = self.project_configs["opensearch_connection"]

        

        conn_info = client.get_connection(opensearch_connection).get_info()

       

        # Initialize OpenSearch Client
        self.opensearch_client = OpenSearch(
            hosts=[{"host": conn_info["params"]["host"], "port": conn_info["params"]["port"]}],
            http_auth = (conn_info["params"]["username"], conn_info["params"]["password"]),
            use_ssl=conn_info["params"]["ssl"],
            verify_certs=False
        )

        
    
    
    
    def bulk_insert(self, index_name, documents):

        docs_to_store = []
        for document in documents:
          
            action = {
                "_op_type": "index",  # Operation type (index = insert)
                "_index": index_name,  # Index name
                "_id": document['id'],  # Use the unique document ID
                "_source": document  # Document body
            }
            docs_to_store.append(action)

        success, failed = bulk(self.opensearch_client, docs_to_store)
        print(f"Successfullly indexed {success} documents.")
        print(f"Failed to index {failed} documents.")
        if failed:
            raise Exception("Document indexing encountered an unknown error. ")
    
    
    
    async def create_embeddings(self,proj, chunks, model_id):
        """
        Creates embeddings for the provided text using the specified model.

        Args:
            text (str): The text to generate embeddings for.
            model_id (str): The identifier of the model to use.

        Returns:
            dict: A dictionary with:
                - "success" (bool): Indicates whether the operation was successful.
                - "response" (any): The generated embeddings if successful, or an error message if failed.
        """
        
        
        try:
            llm = proj.get_llm(model_id).as_langchain_embeddings()

            embeddings =  await llm.aembed_documents(chunks)
            
                     
            return {
                "success": True,
                "response": embeddings
            }
        

        except Exception as e:
            return {
                "success": False,
                "message": e
            }
        
    def create_embedding(self, text, model_id):
        """
        Creates embeddings for the provided text using the specified model.

        Args:
            text (str): The text to generate embeddings for.
            model_id (str): The identifier of the model to use.

        Returns:
            dict: A dictionary with:
                - "success" (bool): Indicates whether the operation was successful.
                - "response" (any): The generated embeddings if successful, or an error message if failed.
        """

        if not text.strip():
            return {
            "success": False,
            "message": "Query text cannot be empty for embeddings."
        }
    
        proj = self.project
        try:
            llm = proj.get_llm(model_id)

            emb_query = llm.new_embeddings(text_overflow_mode="TRUNCATE")
            
            # Create embeddings of the provided chunk
            emb_query.add_text(text)
            res = emb_query.execute()
                     
            
            return {
                "success": True,
                "response": res.get_embeddings()[0]
            }

        except Exception as e:
            return {
                "success": False,
                "message": e
            }
        
        
        
    def crf_search_similar_documents(self, index_name, query, k):
        """
        Searches for similar documents in OpenSearch using vector similarity only.

        Args:
            index_name (str): The OpenSearch index name.
            query (str): The query text to vectorize and search against.
            k (int): Number of top similar documents to retrieve.

        Returns:
            list of dict: List of top-k similar documents with doc_id, content, metadata, and similarity_score.
        """
        # Generate embedding for the query
        embed_response = self.create_embedding(query, self.project_configs.get("default_embeddings_model_id"))
        print("Embedding model used:", self.project_configs.get("default_embeddings_model_id"))

        if not embed_response.get("success"):
            raise Exception(embed_response.get("message"))

        # Clean up the embedding if it’s a string
        vector = embed_response.get("response")
        if isinstance(vector, str):
            
            vector = json.loads(vector)

        # Construct the KNN query (no filters)
        search_query = {
            "size": k,
            "query": {
                "knn": {
                    "assessment_vector": {
                        "vector": vector,
                        "k": k
                    }
                }
            }
        }

        # Execute search
        response = self.opensearch_client.search(
            index=index_name,
            body=json.dumps(search_query)
        )

        # Parse results
        hits = response.get('hits', {}).get('hits', [])
        results = [
            {
                "assessment_id": hit["_source"].get("assessment_id"),
                "content": hit["_source"].get("assessment"),
                "path":  hit["_source"].get("path"),
                "form_id":  hit["_source"].get("form_id"),
                "form_name":  hit["_source"].get("form_name"),
                "source":  hit["_source"].get("source"),
                "template_name":  hit["_source"].get("template_name"),
                "therapeutic_area":  hit["_source"].get("therapeutic_area"),
                "knn_score": hit.get("_score", 1.0),
                "similarity_score": hit.get("_score")
            }
            for hit in hits
        ]

        return results
    
    def get_open_serach_standard_crf(self, index_name):
        
        
        all_std_query = {
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"source.keyword": "Standard CRF"}}
                        ]
                    }
                },
                "aggs": {
                    "distinct_assessments": {
                        "terms": {
                            "field": "assessment.keyword",
                            "size": 1000  # Adjust if you expect more than 1000 unique values
                        }
                    }
                },
                "size": 100  # We only want the aggregation results, not actual documents
            }
            
        res_std = self.opensearch_client.search(index=index_name, body=json.dumps(all_std_query))
        hits = res_std.get("hits", {}).get("hits", [])

        results = [hit["_source"] for hit in hits]
        all_std_crf = []
        for item in results:

            all_std_crf.append({"assessment_ids": item["assessment_id"],
            "form_ids": item["form_id"],
            "assessment_name": item.get("assessment"),
            "path": item.get("path"),
            "form_name": item.get("form_name"),
            "source": item.get("source"),
            "template_name": item.get("template_name"),
            "therapeutic_area": item.get("therapeutic_area")})

        return all_std_crf
    
    
    def crf_search_similar_documents_intense(self, index_name, query, protocol_query, k):
        
        """
        Performs a two-level semantic similarity search:
        1. KNN search using 'assessment_vector' (top 10)
        2. If highest score < 0.73 → fallback KNN search using 'form_field_vector' (top 5)
        3. Combine hits by template_name and merge IDs
        4. Rerank using cosine similarity on 'protocol_summary_vector'
        Special case: If any hit has source == 'Standard CRF', return it immediately.
        """

        #  Step 1: Generate embeddings
        embed_assessment = self.create_embedding(query, self.project_configs.get("default_embeddings_model_id"))
        embed_protocol = json.loads(protocol_query) if isinstance(protocol_query, str) else protocol_query
        
        print("embed_protocol",embed_protocol)
        if not isinstance(embed_protocol, list):
            raise Exception("Protocol embedding is not a valid list")
            

        vector_assessment = json.loads(embed_assessment["response"]) if isinstance(embed_assessment["response"], str) else embed_assessment["response"]
        vector_protocol = embed_protocol
        std_bool = 0
        print(std_bool)


        # Helper cosine similarity
        def cosine_similarity(vec1, vec2):
            v1, v2 = np.array(vec1), np.array(vec2)
            return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))

        # Step 2: First KNN search on 'assessment_vector' (top 10)
        def knn_search(vector, field, topk):
            '''search_query = {
                "size": topk,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"source.keyword": "Historical CRF"}}
                        ],
                        "should": [
                            {
                                "knn": {
                                    field: {
                                        "vector": vector,
                                        "k": topk
                                    }
                                }
                            }
                        ]
                    }
                    

                }
            }'''
            
            pipeline_name = "min_max_pipeline"
            pipeline_body = {
                "description": "Normalize BM25 _score using min-max scaling",
                "phase_results_processors": [
                    {
                        "normalization-processor": {
                            "normalization": { "technique": "min_max" },
                            "combination": {
                                "technique": "arithmetic_mean",
                                "parameters": { "weights": [1.0] }
                            }
                        }
                    }
                ]
            }

            self.opensearch_client.transport.perform_request(
                method="PUT",
                url=f"/_search/pipeline/{pipeline_name}",
                body=pipeline_body
            )
            print(f"Pipeline '{pipeline_name}' created (or replaced).")

            # === Step 2: Verify that the pipeline exists ===
            resp = self.opensearch_client.transport.perform_request(
                method="GET",
                url=f"/_search/pipeline/{pipeline_name}"
            )
            print("Pipeline configuration:")
            print(json.dumps(resp, indent=2))

            
            
            search_query = {
                    "size": 6,
                    "query": {
                        
                        "bool": {
                            "filter": [
                                {"term": {"source.keyword": "Historical CRF"}}
                            ],
                            "should": [
                                {
                                    "match": {
                                        "form_name": {
                                            "query": query,
                                            

                                        }
                                    }
                                }
                            ]
                        }
                    }
                   
                }
            
            
            

            
            return self.opensearch_client.search(index=index_name,params={"search_pipeline": pipeline_name}, body=json.dumps(search_query))


        def knn_search_step_1(vector, field, topk):
           

            search_query = {
                "size": topk,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"source.keyword": "Historical CRF"}}
                        ],
                        "should": [
                            {
                                "knn": {
                                    field: {
                                        "vector": vector,
                                        "k": topk
                                    }
                                }
                            }
                        ]
                    }
                    

                }
            }

            response = self.opensearch_client.search(index=index_name, body=json.dumps(search_query))

            

            return response


        response = knn_search(vector_assessment, "assessment_vector", 6)
        hits = response.get('hits', {}).get('hits', [])

        # Step 2.6: If highest score < 0.73 → fallback search using form_field_vector (top 5)
        print("lenth of hits from step 1: ",query,len(hits))
        if max(hit["_score"] for hit in hits) < 5 :
            print("Fallback triggered: Using form_feild_vector")
            response = knn_search_step_1(vector_assessment, "form_feild_vector", 6)
            hits = response.get('hits', {}).get('hits', [])


        grouped_hits = {}
        for hit in hits:
            src = hit["_source"]
            file_key = src.get("template_name")
            if file_key not in grouped_hits:
                grouped_hits[file_key] = {
                    "assessment_ids": set(),
                    "form_ids": set(),
                    "assessment_name": src.get("assessment"),
                    "path": src.get("path"),
                    "form_name": src.get("form_name"),
                    "source": src.get("source"),
                    "template_name": file_key,
                    "therapeutic_area": src.get("therapeutic_area"),
                    "protocol_vec": src.get("protocol_summary_vector"),
                    "knn_score": hit.get("_score", 1.0),
                    "similarity_score": hit.get("_score", 1.0)
                }
            grouped_hits[file_key]["assessment_ids"].add(src.get("assessment_id"))
            grouped_hits[file_key]["form_ids"].add(src.get("form_id"))


        for item in grouped_hits.values():
            protocol_vec = item.get("protocol_vec")
            if protocol_vec and isinstance(protocol_vec, list):
                item["similarity_score"] = cosine_similarity(protocol_vec, vector_protocol)


        results = [{
            "assessment_ids": list(item["assessment_ids"]),
            "form_ids": list(item["form_ids"]),
            "assessment_name": item["assessment_name"],
            "path": item["path"],
            "form_name": item["form_name"],
            "source": item["source"],
            "template_name": item["template_name"],
            "therapeutic_area": item["therapeutic_area"],
            "knn_score": item["knn_score"],
            "similarity_score": item["similarity_score"]
        } for item in grouped_hits.values()]

        return sorted(results, key=lambda x: x["knn_score"], reverse=True)[:k]

    
    '''def crf_search_similar_documents_intense(self, index_name, query, protocol_query, k):
        
        """
        Performs a two-level semantic similarity search:
        1. KNN search using 'assessment_vector'
        2. Combine hits with same file name (template_name) by merging IDs
        3. Rerank using cosine similarity on 'protocol_summary_vector'
        Special case: If any hit has source == 'Standard CRF', return it immediately.

        Args:
            index_name (str): OpenSearch index.
            query (str): Query text.
            protocol_query (str): Secondary protocol text.
            k (int): Top-k documents to return.

        Returns:
            list of dict: Top-k similar documents (grouped by file name).
        """

        # Step 1: Get both embeddings
        embed_assessment = self.create_embedding(query, self.project_configs.get("default_embeddings_model_id"))
        embed_protocol = json.loads(protocol_query)
        print(type(embed_protocol),"embed_protocol",embed_protocol[0:200])

        #if not (embed_assessment.get("success") and embed_protocol.get("success")):
        #raise Exception("Embedding generation failed for one or both queries.")

        vector_assessment = json.loads(embed_assessment["response"]) if isinstance(embed_assessment["response"], str) else embed_assessment["response"]
        vector_protocol = embed_protocol

        # Step 2: KNN search on 'assessment_vector'
        search_query = {
            "size": k,
            "query": {
                "knn": {
                    "assessment_vector": {
                        "vector": vector_assessment,
                        "k": k
                    }
                }
            }
        }

        response = self.opensearch_client.search(
            index=index_name,
            body=json.dumps(search_query)
        )

        hits = response.get('hits', {}).get('hits', [])
        results = []

        def cosine_similarity(vec1, vec2):
            v1 = np.array(vec1)
            v2 = np.array(vec2)
            return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))

        # ✅ Step 2.5: Short-circuit for "Standard CRF"
        for hit in hits:
            src = hit["_source"]
            if src.get("source", "").strip().lower() == "standard crf":
                return [{
                    "assessment_ids": [src.get("assessment_id")],
                    "form_ids": [src.get("form_id")],
                    "assessment_name": src.get("assessment"),
                    "path": src.get("path"),
                    "form_name": src.get("form_name"),
                    "source": src.get("source"),
                    "template_name": src.get("template_name"),
                    "therapeutic_area": src.get("therapeutic_area"),
                    "knn_score": hit.get("_score", 1.0),
                    "similarity_score": hit.get("_score", 1.0)  # Use KNN score if no cosine
                }]

        # ✅ Step 3: Group hits by file name (template_name) and merge IDs
        grouped_hits = {}
        for hit in hits:
            src = hit["_source"]
            file_key = src.get("template_name")  # grouping key

            if file_key not in grouped_hits:
                grouped_hits[file_key] = {
                    "assessment_ids": set(),
                    "form_ids": set(),
                    "assessment_name": src.get("assessment"),
                    "path": src.get("path"),
                    "form_name": src.get("form_name"),
                    "source": src.get("source"),
                    "template_name": file_key,
                    "therapeutic_area": src.get("therapeutic_area"),
                    "protocol_vec": src.get("protocol_summary_vector"),
                    "knn_score": hit.get("_score", 1.0),
                    "similarity_score": hit.get("_score", 1.0)  # initially use KNN score
                }

            # merge assessment_id and form_id
            grouped_hits[file_key]["assessment_ids"].add(src.get("assessment_id"))
            grouped_hits[file_key]["form_ids"].add(src.get("form_id"))

        # ✅ Step 4: Rerank using cosine similarity on protocol vector
        for key, item in grouped_hits.items():
            protocol_vec = item.get("protocol_vec")
            if protocol_vec and isinstance(protocol_vec, list):
                item["similarity_score"] = cosine_similarity(protocol_vec, vector_protocol)

        # ✅ Convert sets to lists and prepare final results
        for item in grouped_hits.values():
            results.append({
                "assessment_ids": list(item["assessment_ids"]),
                "form_ids": list(item["form_ids"]),
                "assessment_name": item["assessment_name"],
                "path": item["path"],
                "form_name": item["form_name"],
                "source": item["source"],
                "template_name": item["template_name"],
                "therapeutic_area": item["therapeutic_area"],
                "knn_score": item["knn_score"],
                "similarity_score": item["similarity_score"]
            })

        # Step 5: Sort by similarity score and return top-k
        results = sorted(results, key=lambda x: x["similarity_score"], reverse=True)
        return results[:k]'''

    


    def search_similar_documents(self, index_name, query, k, doc_id=None):
        """
        Searches for similar documents in OpenSearch using vector similarity.

        Args:
            index_name (str): The name of the OpenSearch index to search within.
            query (str): The query text to use for finding similar documents.
            k (int): The number of similar documents to retrieve.
            user_id (str, optional): A filter for restricting results to documents associated with a specific user.

        Returns:
            list of dict: A list of dictionaries containing the `doc_id`, `content`, `metadata`, and `similarity_score`
            for each similar document found.
        """


        embed_response = self.create_embedding(query, self.project_configs.get("default_embeddings_model_id"))
        print("model",self.project_configs.get("default_embeddings_model_id"))

        if not embed_response.get("success"):
            raise Exception(embed_response.get("message"))



        doc_filter_query = {
          "terms": {
            "metadata.file.keyword": doc_id if isinstance(doc_id, list) else [doc_id]
          }
        }


        filter_list = []


        if doc_id:
            filter_list.append(doc_filter_query)


        search_query = {
            "size": k,  # Ensures you get exactly `k` documents
            "query": {
                "bool": {
                    "filter": filter_list,  # Retain any filters you need
                    "should": [  # Use `should` instead of `must` to get documents that may not meet the exact threshold but are still relevant
                        {
                            "knn": {
                                "vector_field": {
                                    "vector": embed_response.get("response"),
                                    "k": k
                                }
                            }
                        }
                    ],
                    "minimum_should_match": 1  # This ensures at least one `should` clause is satisfied, even if similarity is low
                }
            }
        }




        # Execute search
        response = self.opensearch_client.search(
            index=index_name,
            body=json.dumps(search_query)
        )
        # Parse results

        hits = response.get('hits', {}).get('hits', [])

        results = [{"doc_id": hit["_source"]["id"], "content": hit["_source"]["text"], "metadata": hit["_source"]["metadata"], "similarity_score": hit["_score"]} for hit in hits]

        return results