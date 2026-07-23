# output_crfs = extract_crf('/Annotated_Otsuka_405 201 00157_00150405_v1.0_Complete eCRF (1).pdf')
# Single search over OpenSearch index with hybrid similarity (vector + fuzzy)
import time
from sklearn.metrics.pairwise import cosine_similarity
from rapidfuzz import fuzz  # for fuzzy text similarity
import pandas as pd 
import dataikuapi
from crf_extraction_module.opensearch_utils import OpensearchUtil

start = time.time()

DATAIKU_HOST = "http://10.45.152.66:10000"
API_SECRET_KEY = "dkuaps-b3EsRXVjU3w4y7nd4KEwibEr04CjFPZr"          
PROJECT_NAME = "ECSGENERATION"
client = dataikuapi.DSSClient(DATAIKU_HOST, API_SECRET_KEY)
proj = client.get_project(PROJECT_NAME)

# Initialize OpenSearch client
opensearch_client = OpensearchUtil(client, proj)
client_os = opensearch_client.opensearch_client

output_list = []

# Get the OpenSearch index name from project variables
index_name = proj.get_variables()['local'].get('ecs_opensearch')
standard_index = "${projectKey}_ecs_index_data"
dataiku_project_var = "${projectKey}"
if dataiku_project_var in index_name:
    # Replace projectKey placeholder with actual project key
    index_name = index_name.replace(dataiku_project_var, opensearch_client.project.project_key).lower()
    standard_index = standard_index.replace(dataiku_project_var, opensearch_client.project.project_key).lower()
    print(standard_index)
    
def compute_similarity(vec1, vec2, text1, text2, w_cos=0.8, w_text=0.2):
    cos_sim = cosine_similarity([vec1], [vec2])[0][0]
    print('cosine score ->',cos_sim)
    text_score = fuzz.token_sort_ratio(text1, text2) / 100
    print('cosine score ->',cos_sim,'=fuzz score=',text_score)
    return cos_sim 
 


def generate_review_table(json_output):
    i = 0
    output_list = []

    


    for  row in json_output:
        i += 1
        form_name, field_name = row['form_name'], row['field_name']
        print(form_name, field_name )

        # Embeddings
        form_vec = opensearch_client.create_embedding(
            form_name, proj.get_variables()['local'].get("default_embeddings_model_id")
        )['response']
        field_vec = opensearch_client.create_embedding(
            field_name, proj.get_variables()['local'].get("default_embeddings_model_id")
        )['response']

        # -------- Historic Search -------- #
        hist_query = {
            "query": {
                "bool": {
                    "should": [
                        {"knn": {"form_name_vector": {"vector": form_vec, "k": 10}}},
                        {"knn": {"form_field_value_vector": {"vector": field_vec, "k": 10}}}
                    ],
                    "filter": [{"term": {"source.keyword": "Historic"}}]
                }
            }
        }

        hist_result = opensearch_client.opensearch_client.search(
            index=index_name, body=hist_query, size=5
        )

        best_hist = None
        best_hist_score = -1
        for hit in hist_result["hits"]["hits"]:
            if "form_field_value_vector" in hit["_source"]:
                score = compute_similarity(
                     field_vec, hit["_source"]["form_field_value_vector"],
                     field_name, hit["_source"]["form_field_value"]
                 )
                print("historic score",hit['_score'])
                #score = float(llm_similarity_score( field_name, hit["_source"]["form_field_value"]))
            else:
                continue
                score = fuzz.token_sort_ratio(
                    form_name.lower().strip(),
                    hit["_source"]["form_name"].lower().strip()
                ) / 100.0

            if score > best_hist_score:
                best_hist_score, best_hist = score, hit

        if best_hist and best_hist_score > 0.65:
            best_hist['_source'].update({
                "original_form_name": form_name,
                "original_field": field_name,
                "score": best_hist['_score'] / 2,
                "fuzzy_or_vector_score": best_hist_score
            })
            output_list.append(best_hist['_source'])
            continue  # ✅ Found in Historic, skip Standard

        # -------- Standard Search (using compute_similarity) -------- #
        print("Switching to Standard…")

        std_query = {
            "query": {
                "bool": {
                    "should": [
                        {"knn": {"form_name_vector": {"vector": form_vec, "k": 10}}},
                        {"knn": {"form_field_vector": {"vector": field_vec, "k": 10}}}
                    ],
                    "filter": [{"term": {"source.keyword": "Standard"}}]
                }
            }
        }

        std_result = opensearch_client.opensearch_client.search(
            index=standard_index, body=std_query, size=5
        )

        best_std = None
        best_score = -1

        print('====original field name=====',field_name)
        for hit in std_result["hits"]["hits"]:


            # 🔑 Compute hybrid similarity instead of pure fuzzy
            score = compute_similarity(
                field_vec, hit["_source"]["form_field_vector"],
                field_name, hit["_source"]["form_field_value"]
            )
    #         score = float(llm_similarity_score( field_name, hit["_source"]["form_field_value"]))
            print('----------------------',score,'opensearch field', hit["_source"]["form_field_value"])

            if score > best_score:
                best_score = score
                best_std = hit

        # --- Post-filtering & LLM fallback --- #
        print('total score',best_std['_score'])
        if best_std:
            best_std['_source'].update({
                "original_form_name": form_name,
                "original_field": field_name,
                "score": best_std['_score'] / 2,
                "fuzzy_or_vector_score": best_score
            })

            if form_name.lower().strip() == "informed consent":
                print(f"original: {form_name}, {field_name}")
                print(f"hit: {best_std['_source']['form_name']}, {best_std['_source']['form_field_value']}")
                print(f"similarity_score={best_score:.3f}, opensearch_score={best_std['_score']/2:.3f}")

            # ✅ Accept if hybrid score passes threshold
            if best_std['_score'] / 2 > 0.64 and best_score > 0.60:
                print('appened')
                output_list.append(best_std['_source'])
            else:
                # ❌ Too weak → fallback to LLM
                print("LLM fallback triggered…")
                output = {}  # output = json.loads(make_llm_call(form_name, field_name))
                if isinstance(output, list):
                    output = output[0]

                output.update({
                    "ecs_id": best_std['_source']['ecs_id'],
                    "form_id": best_std['_source']['form_id'],
                    "original_form_name": form_name,
                    "original_field": field_name,
                    "score": best_std['_score'] / 2,
                    "source": "LLM Generated"
                })
                output_list.append(output)
                    
    #output = pd.DataFrame(output_list)
    # out_final = output[['original_form_name', 'original_field','source','form_name',  'form_field_value','score', 'form_domain_name','variable_name',
    #'validation_logic', 'reasoning', 'action', 'action_details',]]
    #list_of_dicts = out_final.to_dict(orient="records")
    
    required_columns = [
    'original_form_name', 'original_field', 'source', 'form_name',
    'form_field_value', 'score', 'form_domain_name', 'variable_name',
    'validation_logic', 'reasoning', 'action', 'action_details'
    ]

    list_of_dicts = [
        {k: d.get(k, None) for k in required_columns}
        for d in output_list
]



    return list_of_dicts
