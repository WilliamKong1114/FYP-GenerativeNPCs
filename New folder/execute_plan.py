import sqlite3
import json
import time
import re
from planner import llm
from unity_comm import UnityClient
from World_Environment.environment_tree import EnvironmentTree
from World_Environment.agent_state import AgentStateManager
from World_Environment.simulation_clock import SimulationClock
from Skill_Manage.chroma_skill_lib import execute_skill, add_skill, query_skill
from conversation_manager import ConversationManager

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
    - Variable `params` is a dictionary containing 'target_name' and 'agent_id'.
    - Use `unity.move_to(target_name, description, agent_id=params.get('agent_id'))` to move.
    - Use `unity.interact(target_name, method_name, agent_id=params.get('agent_id'))` to act. Method names are usually verbs like 'Till', 'Water', 'Harvest'.
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

def resolve_and_execute_skill(action_desc, target_name, client, agent_id=None):
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
    if agent_id:
        params["agent_id"] = agent_id

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

def get_plan(user_id: str = "Samson"):
    conn = sqlite3.connect("plans.db")
    cur = conn.cursor()
    try:
        cur.execute("SELECT plan_json, description FROM plans WHERE user_id = ? ORDER BY created_on DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
    except Exception as e:
        print(f"Error reading DB: {e}")
        return None, []
    finally:
        conn.close()

    if not row:
        return None, []

    plan_json_str = row[0]
    try:
        plan_data = json.loads(plan_json_str)
    except json.JSONDecodeError as e:
        print(f"Error decoding plan_json for {user_id}: {e}")
        return row[1] or "", []
        
    return plan_data.get("description", ""), plan_data.get("emojis", [])

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

def parse_time_to_minutes(time_str):
    match = re.search(r'(\d+):(\d+)\s*([ap]m)', time_str.lower())
    if not match: return 0
    h, m, p = int(match.group(1)), int(match.group(2)), match.group(3)
    if p == 'pm' and h < 12: h += 12
    if p == 'am' and h == 12: h = 0
    return h * 60 + m

def execute_plan():
    agents_config = [
        {
            "id": "Samson",
            "persona": ("Innate traits: friendly, outgoing."
                "Samson is a young villager living in a small medieval settlement near a river and pasturelands, with forests not far from the village edge."
                "He was born to a farming family and learned from an early age how to tend crops, care for simple tools, and respect the rhythms of the seasons."
                "He enjoys helping others like growing fruit or vegetables, fishing, and woodworking. "
                "He has a small workshop where he crafts simple furniture and tools. "
                "Samson is also keen on learning new skills from travelers passing through the village.\n "
                "Goals: Improve his woodworking skills to create more intricate furniture, expand his garden to include a wider variety of plants, and build stronger relationships within the village community, and busy to get ready for the coming winter.")
        },
        {
            "id": "Jimmy",
            "persona": ("Innate traits: calm, dependable, observant."
            "Jimmy is a 53‑year‑old villager who has spent his entire life in a modest medieval settlement nestled between rolling pasturelands and a slow‑moving river. Behind the village lie dense woodlands where he often walks to gather herbs and fallen branches."
            "He was raised in a family known for their skill in maintaining tools and tending livestock, and from a young age he learned patience, precision, and the value of steady work. Over decades, Edric became respected for his reliability and quiet wisdom."
            "He enjoys repairing equipment for farmers, carving wooden utensils and small household items, and preparing simple herbal mixtures he learned from an elderly healer many years ago. His workshop—an aging shed filled with tools, scraps of wood, and half‑finished projects—is where he spends most afternoons."
            "His normal daily routine includes checking on neighbors’ tools that need fixing, tending a small patch of vegetables behind his home, taking quiet walks in the woods to gather materials, and chatting with travelers to hear news of faraway lands. In the evenings, he often sits by the communal fire, sharing stories or offering advice to younger villagers.")
        }
    ]
    
    tree = EnvironmentTree()
    tree.load()
    
    client = UnityClient()
    state_manager = AgentStateManager()
    clock = SimulationClock(time_scale=90.0)
    conv_manager = ConversationManager()

    agent_executions = {
        config["id"]: {
            "persona": config["persona"],
            "steps": [],
            "emojis": [],
            "current_step": 0,
            "is_busy_until": 0
        } for config in agents_config
    }

    while True:
        sim_days, cur_h, cur_m = clock.get_sim_time()
        current_sim_total_minutes = cur_h * 60 + cur_m
        
        if clock.is_new_day():
            print(f"\n--- New Simulation Day - {clock.get_time_string()} ---")
            for agent_id, data in agent_executions.items():
                description, emojis = get_plan(agent_id)
                data["steps"] = parse_plan_steps(description) if description else []
                data["emojis"] = emojis
                data["current_step"] = 0
                print(f"[{agent_id}] Loaded plan with {len(data['steps'])} steps and {len(data['emojis'])} emojis.")

        # Process each agent
        for agent_id, data in agent_executions.items():
            # Check if agent has steps left and is not busy
            if data["current_step"] < len(data["steps"]) and time.time() >= data["is_busy_until"]:
                time_str, action = data["steps"][data["current_step"]]
                scheduled_minutes = parse_time_to_minutes(time_str)

                # Is it time for this step?
                if current_sim_total_minutes >= scheduled_minutes:
                    print(f"\n[{clock.get_time_string()}] Agent {agent_id} Executing: {action}")
                    emojis = data["emojis"][data["current_step"]] if data["current_step"] < len(data["emojis"]) else "🤖❓"
                    
                    path_nodes = tree.find_suitable_location(action)
                    target_name = None
                    full_action_desc = action

                    if path_nodes:
                        target_node = path_nodes[-1]
                        target_name = tree.get_location(target_node)
                        path_str = ": ".join([n.name for n in path_nodes])
                        full_action_desc = f"{action} @ {path_str}"
                    
                    if target_name:
                        try:
                            client.move_to(target_name, emojis, action, agent_id=agent_id)
                            state_manager.update_agent(agent_id, full_action_desc)
                            
                            duration = resolve_and_execute_skill(action, target_name, client, agent_id=agent_id)
                            # Set busy time instead of sleeping here so other agents can proceed
                            data["is_busy_until"] = time.time() + duration
                            data["current_step"] += 1
                        except Exception as e:
                            print(f"--> [{agent_id}] Error: {e}")
                    else:
                        client.show_dialogue(emojis, agent_id=agent_id)
                        data["current_step"] += 1

        current_agent_states = []
        for agent_id, data in agent_executions.items():
            agent_state = state_manager.state.get("agents", {}).get(agent_id, {})
            current_agent_states.append({
                "id": agent_id,
                "persona": data["persona"],
                "state": agent_state
            })

        # Group agents by interaction area for dynamic multi-agent conversations
        agents_by_area = {}
        for agent in current_agent_states:
            area = agent["state"].get("interaction_area", "unknown")
            if area and area != "unknown":
                if area not in agents_by_area:
                    agents_by_area[area] = []
                agents_by_area[area].append(agent)

        for area, group in agents_by_area.items():
            if len(group) >= 2:
                if conv_manager.start_conversation(group):
                    ids = [a['id'] for a in group]
                    loc = group[0]["state"].get("location", "unknown")
                    print(f"\n--- Conversation Triggered: {', '.join(ids)} at {area} ({loc}) ---")
                    context = f"{', '.join(ids)} are in the {area} near {loc}."
                    
                    for turn in conv_manager.generate_dialogue(group, context):
                        speaker = turn["speaker"]
                        text = turn["text"]
                        print(f"[{speaker}] {text}")
                        client.show_dialogue("💬", agent_id=speaker)
                        time.sleep(1.5)

        state_manager.set_time(clock.get_time_string())
        time.sleep(1)

    client.close()

if __name__ == "__main__":
    execute_plan()
