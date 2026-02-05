import sqlite3
import json
import time
import re
from planner import llm
from unity_comm import UnityClient
from World_Environment.environment_tree import EnvironmentTree
from World_Environment.agent_state import AgentStateManager
from Skill_Manage.chroma_skill_lib import execute_skill, add_skill, query_skill

def generate_new_skill(action_desc, agent_state=None, relevant_skills=None, last_code=None, error=None):
    guidelines = """
    Guidelines:
    1. Your function will be reused for building more complex functions. Therefore, you should make it generic and reusable.
    2. Write VALID Python code. Do NOT wrap in markdown blocks. Do NOT provide explanations.
    3. The code should extract target from params: `target = params.get('target_name')`
    4. The code MUST end by setting variable `result` to an estimated duration (float in seconds) for the action. E.g., `result = 4.0`.
    """
    
    primitives = """
    Control Primitives:
    - Variable `unity` is a UnityClient instance.
    - Variable `params` is a dictionary containing 'target_name'.
    - Use `unity.move_to(target_name, description)` to move.
    - Use `unity.interact(target_name, method_name)` to act. Method names are usually verbs like 'Till', 'Water', 'Harvest'.
    """
    
    skills_context = ""
    if relevant_skills:
        skills_context = "Relevant Skills from Library:\n"
        for s in relevant_skills:
            desc = s.get('doc') or s.get('description') or "No description"
            code = s.get('metadata', {}).get('code') or "# No code"
            skills_context += f"--- Skill: {desc} ---\n{code}\n"
            
    feedback_section = ""
    if last_code:
        feedback_section = f"""
        Previous Code Attempt:{last_code}
        Execution Error / Feedback:{error}
        Critique:
        The previous code failed. Analyze the error and generate a fixed version.
        """
        
    state_section = f"Current Agent State: {agent_state}" if agent_state else ""
    prompt = f"""
    You are an AI generating Python code for a game agent skill. Task: {action_desc}
    {guidelines}
    {primitives}
    {skills_context}
    {state_section}
    {feedback_section}
    Generate the Python code now.
    """
    response = llm.invoke(prompt)
    code = response.content.replace("```python", "").replace("```", "").strip()
    return code

def resolve_and_execute_skill(action_desc, target_name, client):
    print(f"--> Searching skill for: {action_desc}")
    
    res = query_skill(action_desc, n_results=5)
    candidates = []
    if res and res.get('ids') and len(res['ids']) > 0:
        ids_list = res['ids'][0]
        dists_list = res.get('distances', [[]])[0] if res.get('distances') else []

        for i, sid in enumerate(ids_list):
            dist = dists_list[i] if i < len(dists_list) else 0.0            
            if dist > 1.0:
                continue

            doc = res['documents'][0][i] if res['documents'] else None
            meta = res['metadatas'][0][i] if res['metadatas'] else None
            candidates.append({"id": sid, "description": doc, "metadata": meta, "distance": dist})

    params = {"target_name": target_name, "action_desc": action_desc}

    for skill in candidates:
        name = skill['metadata'].get('name', 'Unknown')
        print(f"--> Candidate: {name} (Dist: {skill.get('distance', 'N/A')})")
        try:
            return float(execute_skill(skill, params=params, unity_client=client))
        except Exception as e:
            print(f"--> Skill '{name}' execution failed: {e}")
            continue

    print(f"--> No suitable skill found or executed for: {action_desc}")

    # --- Generation Logic Commented Out ---
    # print(f"--> Generating new skill for: {action_desc}")
    # 
    # state_manager = AgentStateManager()
    # agent_info = state_manager.state.get("agents", {}).get("Samson", "Unknown")
    # 
    # relevant_skills = candidates[:3] # Use the ones we found
    #
    # max_retries = 2
    # current_code = None
    # last_error = None
    # 
    # for attempt in range(max_retries + 1):
    #     try:
    #         current_code = generate_new_skill(
    #             action_desc, 
    #             agent_state=agent_info, 
    #             relevant_skills=relevant_skills, 
    #             last_code=current_code, 
    #             error=last_error
    #         )
    #         
    #         print(f"--> Generated Code (Attempt {attempt+1}):\n{current_code}")
    #         
    #         temp_skill = {"metadata": {"code": current_code}}
    #         duration = execute_skill(temp_skill, params=params, unity_client=client)
    #         
    #         if not isinstance(duration, (int, float)):
    #             duration = 3.0
    #         
    #         print(f"--> Skill Executed Successfully. Duration: {duration}s")
    #         
    #         skill_id = "gen_" + str(hash(action_desc))
    #         print("--> Learning new skill...")
    #         add_skill(
    #             name=skill_id,
    #             description=action_desc,
    #             code=current_code,
    #             meta={"type": "generated", "base_duration": duration}
    #         )
    #         print("--> Skill Saved to Memory.")
    #         
    #         return float(duration)
    #         
    #     except Exception as e:
    #         print(f"--> Execution Error in Attempt {attempt+1}: {e}")
    #         last_error = str(e)
            
    # print("--> All attempts failed.")
    return 3.0

def generate_emojis(actions):
    try:
        actions_formatted = "\n".join([f"{i+1}. {act}" for i, act in enumerate(actions)])
        
        prompt = (
            "You are an emoji translator. For each action in the numbered list below, "
            "provide exactly two emojis that best represent it. Do not add or include any gender signs or symbols.\n"
            "Return ONLY a JSON list of strings, where each string contains the two emojis. "
            "Do not include markdown formatting or numbering in the output.\n\n"
            f"Actions:\n{actions_formatted}\n\n"
            "Output Example:\n"
            '["🚶‍♂️🌲", "📖🕯️", "😴🌙"]'
        )
        
        response = llm.invoke(prompt)
        content = response.content.strip()
        
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "")
        if content.startswith("```"):
            content = content.replace("```", "")
        
        emoji_list = json.loads(content)            
        return emoji_list
    
    except Exception as e:
        print(f"Batch emoji generation failed: {e}")
        return ["🤖⚡"] * len(actions)

def get__plan():
    conn = sqlite3.connect("plans.db")
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM plans ORDER BY created_on DESC LIMIT 1")
        row = cur.fetchone()
    except Exception as e:
        print(f"Error reading DB: {e}")
        return None
    finally:
        conn.close()

    if not row:
        return None

    plan_json_str = row[3]
    plan_data = json.loads(plan_json_str)
    return plan_data.get("description", "")

def parse_plan_steps(description):
    lines = description.split('\n')
    steps = []
    # Regex for "1) 7:00 am: Action text"
    # Matches: number, paren, space, time, colon, space, action
    pattern = re.compile(r'\d+\)\s+(\d+:\d+\s+[ap]m):\s+(.*)')
    
    for line in lines:
        line = line.strip()
        match = pattern.match(line)
        if match:
            time_str = match.group(1)
            action_text = match.group(2)
            steps.append((time_str, action_text))
    return steps

def execute_plan():
    #print("Loading Environment Tree...")
    tree = EnvironmentTree()
    tree.load()
    
    #print("Connecting to Unity...")
    client = UnityClient()
    state_manager = AgentStateManager()
    
    description = get__plan()
    if not description:
        print("No plan found in database.")
        return

    #print("Parsing Plan...")
    steps = parse_plan_steps(description)
    print(f"Found {len(steps)} steps.")
    
    print("Generating emojis for the plan...")
    actions_list = [s[1] for s in steps]
    emojis_list = generate_emojis(actions_list)

    for i, (time_str, action) in enumerate(steps):
        print(f"\nTime: {time_str}")
        print(f"Action: {action}")

        emojis = emojis_list[i] if i < len(emojis_list) else "🤖❓"
        print(f"--> Emojis: {emojis}")
        #client.show_dialogue(emojis)
        
        path_nodes = tree.find_suitable_location(action)
        target_name = None
        full_action_desc = action

        if path_nodes:
            target_node = path_nodes[-1]
            target_name = tree.get_location(target_node)
            #print(f"--> Identified Location: {target_node.name}  (Unity: {target_name})")
            
            path_str = ": ".join([n.name for n in path_nodes])
            full_action_desc = f"{action} @ {path_str}"
        else:
            print("--> No specific location found in tree. Staying put or using default.")
            client.show_dialogue(emojis)
            
        if target_name:
            print(f"--> Sending Move Command to '{target_name}'...")
            try:
                client.move_to(target_name, emojis, action)
                state_manager.update_agent("Samson", full_action_desc)
                
                duration = resolve_and_execute_skill(action, target_name, client)
                time.sleep(duration)
                
            except Exception as e:
                print(f"--> Error communicating with Unity at {time_str}: {e}")
                time.sleep(3)
                        
    print("\nPlan Execution Complete.")
    client.close()

if __name__ == "__main__":
    execute_plan()
