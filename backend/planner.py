import json
import re

def map_legacy_action(plan) -> list:
    """Helper to convert legacy single action format into multi-step format."""
    if isinstance(plan, list):
        return plan
    if not isinstance(plan, dict):
        return []
    if "steps" in plan:
        return plan["steps"]
    
    atype = plan.get("action_type") or plan.get("type")
    if atype == "open_app_and_type":
        return [
            {"type": "launch_app", "app": plan.get("app")},
            {"type": "wait", "seconds": 3},
            {"type": "type", "text": plan.get("text")}
        ]
    elif atype == "open_url":
        return [{"type": "new_tab", "url": plan.get("url")}]
    elif atype == "send_email":
        to = plan.get("to", "")
        subject = plan.get("subject", "")
        body = plan.get("body", "")
        return [{"type": "new_tab", "url": f"mailto:{to}?subject={subject}&body={body}"}]
    elif atype == "system_command":
        cmd_map = {
            "open_notepad": "notepad",
            "open_calc": "calc",
            "open_calculator": "calc",
            "open_explorer": "explorer",
            "open_vscode": "vscode",
            "open_volume": "volume"
        }
        return [{"type": "launch_app", "app": cmd_map.get(plan.get("command"), "notepad")}]
    elif atype == "save_memory":
        return [{"type": "save_memory", "fact": plan.get("fact")}]
    
    if "type" in plan:
        return [plan]
        
    return []

def parse_execution_plan(llm_output: str) -> tuple:
    """
    Parses LLM response to extract the structured execution plan (JSON)
    and separate it from the conversational response text.
    
    Returns:
        (clean_conversational_text, list_of_steps)
    """
    # 1. Look for <<<ACTION>>> delimiters
    match = re.search(r'<<<ACTION>>>([\s\S]*?)<<<END_ACTION>>>', llm_output)
    if match:
        clean_text = llm_output.replace(match.group(0), '').strip()
        try:
            plan = json.loads(match.group(1).strip())
            return clean_text, map_legacy_action(plan)
        except Exception as e:
            print(f"Error parsing delimited action JSON: {e}")
            
    # 2. Fallback: Search for any json code block
    json_block_match = re.search(r'```json\s*([\s\S]*?)\s*```', llm_output)
    if json_block_match:
        clean_text = llm_output.replace(json_block_match.group(0), '').strip()
        try:
            plan = json.loads(json_block_match.group(1).strip())
            return clean_text, map_legacy_action(plan)
        except Exception as e:
            print(f"Error parsing json code block: {e}")

    # 3. Fallback: Try to find the first '{' and last '}'
    brace_start = llm_output.find('{')
    brace_end = llm_output.rfind('}')
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        json_candidate = llm_output[brace_start:brace_end + 1]
        try:
            plan = json.loads(json_candidate)
            clean_text = (llm_output[:brace_start] + llm_output[brace_end + 1:]).strip()
            return clean_text, map_legacy_action(plan)
        except Exception:
            pass

    return llm_output, []
