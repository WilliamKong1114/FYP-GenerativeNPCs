import sqlite3
import json
import time
import re
from World_Environment.environment_tree import EnvironmentTree
from unity_comm import UnityClient
from World_Environment.agent_state import AgentStateManager
from planner import llm

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
            except Exception as e:
                print(f"--> Error communicating with Unity at {time_str}: {e}")
                        
        time.sleep(3) 

    print("\nPlan Execution Complete.")
    client.close()

if __name__ == "__main__":
    execute_plan()
