from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, ToolMessage
import json
import re
import dataikuapi
from utils import connection 
# imports from library 
from utilities.variables import RD_PROJECT_NAME
from utilities.variables import SECRET_NAME , TOKEN_KEY
from crf_extraction_module.calculate_tokens import count_tokens
import uuid 
import traceback
 
from dataiku.langchain.dku_llm import DKUChatLLM
from dataiku.llm.python import BaseLLM
 
OPENAI_CONNECTION_NAME = "REPLACE_BY_YOUR_OPENAI_CONNECTION_NAME"
 
@tool
def add(a: int, b: int) -> int:
    """Adds a and b."""
    return a + b
 
@tool
def multiply(a: int, b: int) -> int:
    """Multiplies a and b."""
    return a * b
 
tools = [add, multiply]
def make_llm_call_batch(form_name, field_names_list,client,proj):
    """
    Modified LLM call that generates validation rules for multiple fields at once.
    """
    fields_str = "\n".join([f"{i+1}. {field}" for i, field in enumerate(field_names_list)])
 
    prompt = f"""
 
        You are an Edit Check Specification Specialist for Case Report Forms (CRFs).
 
        Generate validation rules for the following form and its fields:
 
        Form Name: {form_name}
        Field Names:
        {fields_str}
 
        Instructions:
 
        Return ONLY a JSON array — no markdown, no headings, no explanations, and no code fences.
 
        Generate one validation object per field in the same order as the provided field list.
 
        Each validation object must contain exactly the following keys:

            - form_name
            - form_domain_name
            - form_field_value
            - validation_logic
            - reasoning
            - action
            - action_details
            - source
 
        Deterministic Derivations:
        1. form_domain_name
 
            Use the following standard mappings:
 
            Demographics → DM
 
            Medical History → MH
 
            Vital Signs → VS
 
            Adverse Event → AE
 
            Concomitant Medications → CM
 
            Informed Consent → IC
 
            Physical Examination → PE
 
            Laboratory → LB
 
            If no mapping exists, derive by taking the first 2–3 letters of each significant word in the form name and uppercasing them.
            Example: "Post Treatment Follow Up" → "PTF".
 
        2. form_field_value
 
            Use the exact field name as provided.
 
        3. Validation Logic Rules (Apply Only if Deterministically Appropriate):
 
            Missing Field Check: Field must not be blank when enterable.
 
            Date Fields:
 
                - Must be a valid calendar date.
 
                - Must not be a future date.
 
            Time Fields:
 
                - Must be valid 24-hour format.
 
            Numeric Fields:
 
                - Must be numeric.
 
                If no range is known, apply numeric check only.
 
            Yes/No Fields:
 
                - Must contain a valid Yes/No value.
 
            Controlled Terminology Fields:
 
                - Must match controlled codes (if known). Otherwise set "NaN".
 
            Other Specify Fields:
 
                - Required when “Other” is selected in the parent field.
 
            Chronology Rules:
 
                - End date must not occur before start date.
 
                - Visit date cannot precede previous visit date.
 
                - Visit date cannot occur after disposition date.
 
                - AE Start Date must not be before Informed Consent Date.
 
                - MH Start Date must not be after Informed Consent Date.
 
            Cross-Form Checks (only if deterministically inferable):
 
            If an AE/MH record references a CM record, the CM start date must not be after the event start date.
 
            If any rule cannot be determined from the field name alone, output "NaN" for that part.
        4. Action
         - The type of response the system should take when the edit check fires.
         - example 1 : AE.AEENDAT is enterable
         - example 2 : prompt user with ACTION DETAILS
        5. Action details
         - The specific instructions or parameters on how that action should be executed (e.g., text, target fields, formulas).
           example 1 : The Visit Date at Day 3 is more than one day from the Visit Date at Day 2. Please review and update or clarify.
 
       
 
        No Hallucination Rule
 
            - Do not invent field types, code lists, dependencies, or relationships.
 
            - If field purpose/type cannot be inferred from its name, use:
 
            - "validation_logic": "Field must not be blank"
 
            - "reasoning": "Basic data completeness check"
 
            
 
        Final Output Requirement
 
        Return ONLY the JSON array.
        No text before or after.
        No markdown.
        No explanation.
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
        input_tokens = count_tokens(prompt)
 
        output = llm.invoke(prompt)
        output_tokens = count_tokens(output)
        return output , input_tokens , output_tokens
 
    except Exception as e:
        print(f"❌ LLM batch call failed for form '{form_name}': {e}")
        return None
 
def parse_llm_batch_output( llm_response, form_name, field_names_list,all_fields_json):
    """
    Parse LLM batch response and ensure all fields are covered.
    """
    try:
        response_text = str(llm_response)
        response_text = re.sub(r'```json\s*', '', response_text)
        response_text = re.sub(r'```\s*', '', response_text)
        response_text = response_text.strip()
        ecs_ids = []
        parsed = json.loads(response_text)
        for each_field in all_fields_json:
            print("each_fields : ",each_field)
            ecs_ids.append(each_field["ecs_id"])
        print("ecs_ids: ",ecs_ids)
        if not isinstance(parsed, list):
            print(f"⚠️ LLM returned non-array for '{form_name}'")
            return {}
 
        results_map = {}
        for u,item in enumerate(parsed):
            print("u :",u)
            if 'error' in item:
                continue
 
            field_value = item.get("form_field_value", "")
            if field_value:
                results_map[field_value.strip().lower()] = {
                    "ecs_id": ecs_ids[u],
                    "form_id": None,
                    "form_name": item.get("form_name", form_name),
                    "form_field_value": field_value,
                    "validation_logic": item.get("validation_logic"),
                    "reasoning": item.get("reasoning"),
                    "action": item.get("action"),
                    "action_details": item.get("action_details"),
                    "source": "LLM Generated",
                    "path": None,
                    "form_domain_name": item.get("form_domain_name")
                }
 
        missing_fields = []
        for field in field_names_list:
            if field.strip().lower() not in results_map:
                missing_fields.append(field)
 
        if missing_fields:
            print(f"⚠️ LLM missed {len(missing_fields)} fields for '{form_name}': {missing_fields[:10]}...")
 
        return results_map
 
    except json.JSONDecodeError as e:
        print(f"❌ JSON parse error for '{form_name}': {e}")
        print(f"Response preview: {response_text[:300]}...")
        return {}
    except Exception as e:
        print(f"❌ Parse error for '{form_name}': {e}")
        return {}
 
def create_default_validation(form_name, field_name):
    """
    Create a basic validation rule when LLM fails or misses a field.
    """
    variable_name = field_name.upper().replace(' ', '_')
    variable_name = ''.join(c for c in variable_name if c.isalnum() or c == '_')
 
    return {
        "validation_id": None,
        "ecs_id": str(uuid.uuid4()),
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
 
 
class MyLLM(BaseLLM):
    def __init__(self):
        pass
 
    def process(self, query, settings, trace):
        try:
            data = query["context"].get("payload")
            form_name = data.get("form_name")
            fields = data.get("field_name")
            field_names = [f['form_field_value'] for f in fields]
            DATAIKU_HOST , API_SECRET_KEY  = connection.get_dataiku_host_and_api_key(RD_PROJECT_NAME,SECRET_NAME,TOKEN_KEY)
            output_list=[]
 
            client = dataikuapi.DSSClient(DATAIKU_HOST, API_SECRET_KEY)
            project = client.get_project(RD_PROJECT_NAME)
 
            llm_response , input_token , output_token = make_llm_call_batch(form_name, field_names,client,project)
            print("llm_response : ",llm_response)
 
            if llm_response:
                results_map = parse_llm_batch_output(llm_response, form_name, field_names,fields)
                print("results_map : ",results_map)
                for field_data in fields:
                    field_name = field_data['form_field_value']
                    field_key = field_name.strip().lower()
 
                    if field_key in results_map:
                        llm_result = results_map[field_key]
                        llm_result.update({
                            "original_form_name": form_name,
                            "original_field": field_name,
                            "score": None
                        })
                        output_list.append(llm_result)
                        print(f"    ✅ {field_name}")
                    else:
                        default_result = create_default_validation(form_name, field_name)
                        default_result.update({
                            "original_form_name": form_name,
                            "original_field": field_name,
                            "score": None
                        })
                        output_list.append(default_result)
                        print(f"    ⚠️ {field_name} (using default)")
            else:
                print(f"  ❌ LLM call failed - using defaults")
                for field_data in fields:
                    field_name = field_data['form_field_value']
                    default_result = create_default_validation(form_name, field_name)
                    default_result.update({
                        "original_form_name": form_name,
                        "original_field": field_name,
                        "score": None
                    })
                    output_list.append(default_result)
 
            return {
                    "text": json.dumps(
                        {
                            "response": output_list,
                            "input_token":input_token,
                            "output_token":output_token
 
                        }
                    )
                }
        except Exception as e:
            t = traceback.format_exc()
            return {
                "text":t
            }