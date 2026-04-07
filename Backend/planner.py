import sqlite3
import uuid
import datetime
import json
import re
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
from Secure.llm_config import planner_llm
from World_Environment.environment_tree import EnvironmentTree
from agent_memory import AgentMemoryManager
from tools.runtime_monitor import monitor
from chromaMemory_manager import get_reflection

memory_manager = AgentMemoryManager()
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "Database", "plans.db")

def get_plan(user_id: str):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT plan_json FROM plans WHERE user_id = ? ORDER BY created_on DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        plan_data = json.loads(row[0])
        return plan_data.get("description", ""), plan_data.get("emojis", [])

    except sqlite3.Error as e:
        print(f"Error reading database: {e}")
        return None, []
    except json.JSONDecodeError as e:
        print(f"Error decoding plan JSON for user {user_id}: {e}")
        return None, []
    finally:
        if conn:
            conn.close()

def get_plan_id(user_id: str):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT plan_id FROM plans WHERE user_id = ? ORDER BY created_on DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None

    except sqlite3.Error as e:
        print(f"Error reading database: {e}")
        return None
    finally:
        if conn:
            conn.close()

def parse_plan(description: str):
    lines = description.split('\n')
    steps = []
    # Example: "15) 13:00: Head to the workshop to gather materials for crafting furniture."
    # \d+\) - 1); \s - whitespace; \d+:\d+\s+[ap]m - 6:00 am
    pattern = re.compile(r'\d+\)\s+(\d+:\d+):\s+(.*)')
    
    for line in lines:
        line = line.strip()
        match = pattern.match(line)
        if match:
            time = match.group(1)
            action = match.group(2)
            steps.append((time, action))
    return steps

def modify_plan(user_id: str, description: Optional[str] = None, new_emojis: Optional[List[str]] = None):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        modified_on = datetime.datetime.now().isoformat()
        if description is not None and new_emojis is not None:
            cur.execute("""
                UPDATE plans 
                SET description = ?, 
                    plan_json = json_set(plan_json, '$.description', ?, '$.emojis', json(?)), 
                    modified_on = ? 
                WHERE plan_id = (
                    SELECT plan_id
                    FROM plans
                    WHERE user_id = ?
                    ORDER BY created_on DESC
                    LIMIT 1
                )
            """, (description, description, json.dumps(new_emojis), modified_on, user_id))

            if cur.rowcount == 0:
                print(f"No existing plan found for user_id={user_id}; update skipped.")
                return False
        else:
            print("No updates provided for modify_plan.")
            return False
        
        conn.commit()
        return True
    finally:
        if conn:
            conn.close()

def store_plan(plan: List[Dict[str, Any]], user_id: str = "default_user", parent_id: Optional[str] = None) -> List[str]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    ids = []
    for p in plan:
        plan_id = p.get("plan_id") or str(uuid.uuid4())        
        cur.execute(
            "INSERT INTO plans(plan_id, user_id, plan_json, description, created_on, modified_on, parent_id) VALUES (?,?,?,?,?,?,?)",
            (plan_id, user_id, json.dumps(p), p.get("description"), p.get("created_on"), p.get("modified_on"), parent_id or p.get("parent_id")),
        )
        ids.append(plan_id)
        
    conn.commit()
    conn.close()
    return ids

@monitor.track("Emoji Generation")
def generate_emojis(actions: List[str]) -> List[str]:
    try:
        actions_formatted = "\n".join([f"{i+1}. {act}" for i, act in enumerate(actions)])
        prompt = (
            "You are an emoji translator. For each action in the numbered list below, translate it into a concise emoji representation that captures the essence of the activity. Use only two emojis per action to create a simple visual summary.\n"
            "Output must be a pure JSON array of strings. No prose, no comments, no extra keys."
            "Each string MUST contain exactly 2 emoji characters back-to-back — no spaces, no punctuation, no words." 
            "Use only single-codepoint emojis with default emoji presentation (no sequences)."
            "Absolutely FORBIDDEN characters/sequences:"
            "- Zero Width Joiner (U+200D)"
            "- Variation Selectors (U+FE0E, U+FE0F)"
            "- Keycap combining mark (U+20E3)"
            "- Skin tones (U+1F3FB-U+1F3FF)" 
            "- Gender signs/symbols (e.g., U+2640, U+2642)"
            "- Avoid newly added emojis; choose widely supported ones (no “🪟”, etc.)."
            "- Do not output any letters, words, or spaces (e.g., NOT 'basket🥕')." 
            f"Actions:\n{actions_formatted}\n\n"
            "Strictly following this output example under a JSON array:\n"
            '["📖🕯️", "😴🌙", ...]'
        )
        response = planner_llm.invoke(prompt)
        content = getattr(response, "content", "").strip()
        
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
             content = content.split("```")[1].split("```")[0].strip()        
        
        emoji_list = json.loads(content)
        return emoji_list
    
    except Exception as e:
        print(f"Emoji generation failed: {e}")
        return ["❓❓"]

def plan_prompt(background: str, candidate_info: List[Dict], reflections: List[str]) -> str:
    #now = today or datetime.date.today().isoformat()
    prompt = (
        "You are a helpful planning assistant to plan for a medieval villager in the year 1200A.D.\n"
        f"Persona and context:\n{background}\n"
        "- The available location within the village are listed below. Design each action based on available locations, and prioritize the areas that are more relevant to the persona. For example, if the persona is more social, then the actions should be more likely to happen in the market, tavern, or chapel."
        "- Use clean, restrained prose. Prefer strong, simple verbs over verbs modified by adverbs. Avoid unnecessary adjectives and adverbs. Do not decorate every action with an emotional modifier. Only use modifiers when they add important meaning.\n"
        f"- Place within the villager: {candidate_info}\n"
        f"- Here is some recent reflections needs to be considered for the plan generation. Informations including relationships with others, or improtance things for the person, will affect tasks that the agent want to do:\n{reflections}\n"
        "- Given the person's profile and activities below, generate a concise plan for today as it would realistically occur in a medieval village setting, and being performed by the person with their particular personality.\n"
        """Personality adaptation examples (for guidance, not to be copied verbatim):\n
        - Someone who dislikes socializing should avoid busy public places, stay mostly at home, and only go out to get necessities (e.g., collecting water from the well, quick visits to the market).
        - Someone curious or intellectual should go out exploring, watching craftsmen at work, visiting the local scribe or priest, and talking with others more frequently.
        - Someone physically strong and energetic might volunteer for heavy tasks (carrying water, chopping wood, helping build or repair fences, assisting as a guard at the village gate).
        - Someone physically frail or often tired should have lighter duties (sorting grain, sewing, preparing food, watching children) with more rest periods.\n"""

        "Reply with a numbered list of broad strokes for the day using a STRICT 24-hour time format (e.g., 13:00, 18:30). Do not include 'am' or 'pm', and ensure all times are formatted as HH:MM."        
        "Requirements:\n"
        "- You MUST ONLY Cover the hour within the 06:00 to 22:00 period specifically.\n"
        "- Produce 10 to 12 high-level items for today's plan, numbered\n"
        "- Keep each item to one sentence\n"
        "- Use the persona details to prioritize tasks and habits\n"
        "- Use short sentences, contractions, and everyday language\n"
        "- Maintain a simple, grounded tone without sounding poetic or overly formal.\n"
        
        "Output format (STRICT):\n"
        "1) Woke up and complete the morning routine at 7:00\n"
        "2) Gardening the backyard at 8:00 to 11:00\n"
        "...\n"
        "8) Get ready to sleep around 22:00.\n"
    )
    return prompt

@monitor.track("Plan Decomposition")
def decompose_plan(parent_plan: Dict[str, Any], duration_prompt: str, candidate_info: List[Dict] = None, background: Optional[str] = None, emoji_generation: bool = False, reflections: List[str] = None, auto_store: bool = True) -> Dict[str, Any]:
    prompt = (
        f"You are a planning assistant that breaks down plans into finer-grained actions."
        f"Plan Description:\n{parent_plan.get('description')}\n"
        f"Given the plan owner's persona, background and plan description, break it down into finer-grained actions with provided time durations of specifically {duration_prompt} for each sentence.\n"
        "The plan should be as it would realistically happens in a medieval village setting in the year 1200A.D. and reflect the owner's persona\n"
    )

    if background:
        prompt += (
            f"Persona and context:\n{background}\n"
            """Personality adaptation examples (for guidance, not to be copied verbatim):\n
            - Someone who dislikes socializing should avoid busy public places, stay mostly at home, and only go out to get necessities (e.g., collecting water from the well, quick visits to the market).
            - Someone curious or intellectual should go out exploring, watching craftsmen at work, visiting the local scribe or priest, and talking with others more frequently.
            - Someone physically strong and energetic might volunteer for heavy tasks (carrying water, chopping wood, helping build or repair fences, assisting as a guard at the village gate).
            - Someone physically frail or often tired should have lighter duties (sorting grain, sewing, preparing food, watching children) with more rest periods.
            """)
    
    if reflections:
        prompt += (
            f"- Here is some recent reflections needs to be considered for the plan generation. Informations including relationships with others, or improtance things for the person, will affect tasks that the agent want to do:\n{reflections}\n"
        )

    prompt += (
        "Output each step as a sentence. Return a concise, numbered list of actions using a STRICT 24-hour time format (e.g., 13:00, 18:30). Do not include 'am' or 'pm', and ensure all times are formatted as HH:MM."
        "Requirements:\n"
        "- The available location within the village are listed below. Use them to design the actions, and prioritize the areas that are more relevant to the persona. For example, if the persona is more social, then the actions should be more likely to happen in the market, tavern, or chapel."
        "- Do NOT add any symbol to the location, such as \"**\", \"\"\"\", etc. Just the plain text of the location name is good enough.\n"
        "- Include the location for each action.\n"
        "- Use clean, restrained prose. Prefer strong, simple verbs over verbs modified by adverbs. Avoid unnecessary adjectives and adverbs. Do not decorate every action with an emotional modifier. Only use modifiers when they add important meaning.\n"
        f"- Place within the villager: {candidate_info}\n"
        "- Only select locations that appears exactly as written in the Available locations list. Do not create, infer, or modify any location names.\n"
        f"- You MUST ONLY Cover every hour from 06:00 to 22:00 with time period of {duration_prompt} specifically.\n"
        "- Start each line with \"1) 6:00:\" format, then write a 15-20 word sentence.\n"
        "- Do not use any pronouns in the sentences. Reference the agent with the name of the agent."
        "- Maintain a simple, grounded tone without sounding poetic or overly formal.\n"
        "- Provide task or actions based on the provided guidlines within each time frame. For example, if the provided description is: 'Gathered herbs and fallen branches in the woods from 08:00 to 10:00.' then provide task ONLY related to gathering herbs and fallen branches in the woods."
        "- Do NOT involves tasks that needs to be done with a specific person, such as 'Walk home with Heath' or 'Visit the blacksmith with Marcus'"
        "Output format (STRICT):\n"
        "1) 8:00: Tend the dirt land with tools to make the dirt better to be planted\n"
        "2) 9:30: Check the river for fish to prepare for the lunch later\n"
        "..."
        "31) 22:00: Get ready to sleep.\n"
    )
    system_msg = { "role": "system", "content": prompt }
    response = planner_llm.invoke([system_msg])
    content = getattr(response, "content", str(response))
    
    emojis = []
    if emoji_generation:
        lines = content.split('\n')
        actions = []
        pattern = re.compile(r'\d+\)\s+(\d{1,2}:\d{2})[:\s-]*(.*)')
        for line in lines:
            match = pattern.search(line)
            if match:
                actions.append(match.group(2).strip())
        
        emojis = generate_emojis(actions)

    plan_id = str(uuid.uuid4())
    user_id = parent_plan.get("user_id")
    plan: Dict[str, Any] = {
        "plan_id": plan_id,
        "user_id": user_id,
        "description": content,
        "emojis": emojis,
        "created_on": datetime.datetime.now().isoformat(),
        "modified_on": datetime.datetime.now().isoformat(),
        "parent_id": parent_plan.get("plan_id")
    }
    if emoji_generation and auto_store:
        store_plan([plan], user_id=user_id)
    return plan

@monitor.track("Initial Plan Generation")
def init_plan(user_id: str, background: Optional[str], candidate_info: List[Dict]) -> Dict[str, Any]:
    plan_id = str(uuid.uuid4())
    reflections = memory_manager.get_reflection(user_id)
    instruction = plan_prompt(background, candidate_info, reflections)
    #system_msg = {"role": "system", "content": "You are a focused planning assistant. Produce a concise, numbered plan as instructed."}
    system_msg = {"role": "system", "content": instruction}
    response = planner_llm.invoke([system_msg])
    content = getattr(response, "content", str(response))
    #out = getattr(resp, "content", None) or str(resp)

    top_plan: Dict[str, Any] = {
        "plan_id": plan_id,
        "user_id": user_id,
        "description": content,
        "emojis": [],
        "created_on": datetime.datetime.now().isoformat(),
        "modified_on": datetime.datetime.now().isoformat(),
    }

    #store_plan([top_plan], user_id=user_id)
    child_plan = decompose_plan(top_plan, duration_prompt="1 hour", candidate_info=candidate_info, background=background, emoji_generation=False, reflections=reflections, auto_store=False)
    child_plan_2 = decompose_plan(child_plan, duration_prompt="30 minutes", candidate_info=candidate_info, background=background, emoji_generation=True, auto_store=False)
    return {"top_plan": top_plan, "child_plan": child_plan, "child_plan_2": child_plan_2}

def generate_plans(agents_data: Dict[str, Any], candidate_info: List[Dict]):
    agent_items = [(uid, info.get("persona")) for uid, info in agents_data.items()]
    if not agent_items:
        print("[Planner] No agents to generate plans for.")
        return []

    max_workers = min(len(agent_items), 5)

    results = []
    print(f"[Planner] Generating plans for {len(agent_items)} agents...")
    
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Planner") as executor:
        futures = {
            executor.submit(init_plan, uid, persona, candidate_info): uid
            for uid, persona in agent_items
        }
        for future in as_completed(futures):
            uid = futures[future]
            plans = future.result()
            if plans:
                results.append((uid, plans))
                print(f"[Planner] Generated plan for {uid}")

    print(f"[Planner] Storing plans for {len(results)} agents...")
    for uid, plans in results:
        store_plan([plans["child_plan_2"]], user_id=uid)
    
    print(f"[Planner] Done. {len(results)} plans stored.")
    return [uid for uid, _ in results]

def generate_plans_for_missing_agents(agents_data: Dict[str, Any], candidate_info: List[Dict]):
    eligible_agents = {
        uid: info
        for uid, info in agents_data.items()
        if get_plan_id(uid) is None
    }
    skipped_count = len(agents_data) - len(eligible_agents)
    print(f"[Planner] Found {len(eligible_agents)} agents without existing plans. Skipping {skipped_count} agents with existing plans.")
    return generate_plans(eligible_agents, candidate_info)

def generate_plans_for_specific_agents(agents_data: Dict[str, Any], candidate_info: List[Dict], target_agent_ids: List[str]):
    target_set = set(target_agent_ids)
    eligible_agents = {uid: info for uid, info in agents_data.items() if uid in target_set}
    missing_ids = sorted(target_set - set(eligible_agents.keys()))

    if missing_ids:
        print(f"[Planner] Agent IDs not found in state file: {missing_ids}")

    return generate_plans(eligible_agents, candidate_info)

if __name__ == "__main__":
    monitor.start()
    AGENT_STATE_DIR = os.path.join(BASE_DIR, "World_Environment", "agent_state.json")
    with open(AGENT_STATE_DIR, 'r', encoding='utf-8') as f:
        agent_data = json.load(f)

    tree = EnvironmentTree()
    tree.load()
    candidate_info = tree.build_area_list(tree.root)

    agents = agent_data.get("agents", {})

    menu_options = {
        "1": {
            "description": "Generate plans only for agents without existing plans",
            "function": lambda: generate_plans_for_missing_agents(agents, candidate_info),
            "print_result": lambda generated: print(
                "Generated plans for: " + ", ".join(generated) if generated else "No plans generated."
            ),
        },
        "2": {
            "description": "Generate plans for specific agent IDs",
            "function": lambda: generate_plans_for_specific_agents(
                agents,
                candidate_info,
                [item.strip() for item in input("Enter agent IDs (comma-separated): ").split(",") if item.strip()],
            ),
            "print_result": lambda generated: print(
                "Generated plans for: " + ", ".join(generated) if generated else "No plans generated."
            ),
        },
    }

    while True:
        try:
            menu_text = (
                "\nPlanner Command Interface\n"
                + "\n".join(f"{key}) {opt['description']}" for key, opt in menu_options.items())
                + "\nChoose (or 'exit' to quit): "
            )
            choice = input(menu_text).strip()

            if not choice:
                continue
            if choice.lower() == "exit":
                break
            if choice in menu_options:
                result = menu_options[choice]["function"]()
                menu_options[choice]["print_result"](result)
            else:
                print("Invalid choice. Try again.")
        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print(f"Error: {e}")
            continue

    monitor.report()

