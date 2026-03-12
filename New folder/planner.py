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

def generate_emojis(actions: List[str]) -> List[str]:
    try:
        actions_formatted = "\n".join([f"{i+1}. {act}" for i, act in enumerate(actions)])
        prompt = (
            "You are an emoji translator. For each action in the numbered list below, "
            "Output must be a pure JSON array of strings. No prose, no comments, no extra keys."
            "Each string MUST contain exactly two emoji characters back-to-back — no spaces, no punctuation, no words." 
            "Use only single-codepoint emojis with default emoji presentation (no sequences)."
            "Absolutely FORBIDDEN characters/sequences:"
            "- Zero Width Joiner (U+200D)"
            "- Variation Selectors (U+FE0E, U+FE0F)"
            "- Keycap combining mark (U+20E3)"
            "- Skin tones (U+1F3FB–U+1F3FF)" 
            "- Gender signs/symbols (e.g., U+2640, U+2642)"
            "- Avoid newly added emojis; choose widely supported ones (no “🪟”, etc.)."
            "- Do not output any letters, words, or spaces (e.g., NOT 'basket🥕')." 
            f"Actions:\n{actions_formatted}\n\n"
            "Strictly following this output example without adding additional punctuation:\n"
            '["🚶‍♂️🌲", "📖🕯️", "😴🌙", ...]'
        )
        response = planner_llm.invoke(prompt)
        content = getattr(response, "content", "").strip()
        
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].strip()
        emoji_list = json.loads(content)
        return emoji_list
    
    except Exception as e:
        print(f"Emoji generation failed: {e}")
        return ["❓❓"] * len(actions)

def plan_prompt(background: str, today: Optional[str] = None) -> str:
    #now = today or datetime.date.today().isoformat()
    instruction = (
        "You are a helpful planning assistant.\n"
        "Given the person's profile and activities below, generate a concise plan for today as it would realistically occur in a medieval village setting\n"
        "Reply with a numbered list of broad strokes for the day using a STRICT 24-hour time format (e.g., 13:00, 18:30). Do not include 'am' or 'pm', and ensure all times are formatted as HH:MM."        
        f"Persona and context:\n{background}\n"
        
        "Requirements:\n"
        "- Produce 8 to 10 high-level items for today's plan, numbered\n"
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
    return instruction

def decompose_plan(parent_plan: Dict[str, Any], duration_prompt: str, emoji_generation: bool = False, auto_store: bool = True) -> Dict[str, Any]:
    system_msg = {"role": "system", "content": f"You are a planning assistant that breaks down plans into finer-grained actions."}
    user_msg = {"role": "user", "content": (
            f"Given the following plan description, break it down into finer-grained actions with provided time durations of specifically {duration_prompt} for each sentence.\n"
            "The plan should be as it would realistically happens in a medieval village setting\n"
            f"Plan Description:\n{parent_plan.get('description')}\n"
            "Output each step as a sentence. Return a concise, numbered list of actions using a STRICT 24-hour time format (e.g., 13:00, 18:30). Do not include 'am' or 'pm', and ensure all times are formatted as HH:MM."
            
            "Requirements:\n"
            f"- Cover every hour from 06:00 to 22:00 with time period of {duration_prompt} specifically.\n"
            "- Start each line with \"1) 6:00:\" format, then write a 15–20 word sentence.\n"
            "- Maintain a simple, grounded tone without sounding poetic or overly formal.\n"
            "- Each action needs to include a specific area or object (e.g., \"at the herb garden,\" \"in the weaving hut\").\n"
            "- Provide task or actions based on the provided guidlines within each time frame. For example, if the provided description is: 'Gathered herbs and fallen branches in the woods from 08:00 to 10:00.' then provide task ONLY related to gathering herbs and fallen branches in the woods."
            
            "Output format (STRICT):\n"
            "1) 8:00: Tend the dirt land with tools to make the dirt better to be planted\n"
            "2) 9:30: Check the river for fish to prepare for the lunch later\n"
            "...\n"
            "31) 22:00: Get ready to sleep.\n"

        ),
    }
    resp = planner_llm.invoke([system_msg, user_msg])
    out = getattr(resp, "content", None) or str(resp)
    
    emojis = []
    if emoji_generation:
        lines = (out or "").split('\n')
        actions = []
        pattern = re.compile(r'\d+\)\s+(\d{1,2}:\d{2})[:\s-]*(.*)')
        for line in lines:
            match = pattern.search(line)
            if match:
                actions.append(match.group(2).strip())
        
        emojis = generate_emojis(actions)

    plan_id = str(uuid.uuid4())
    user_id = parent_plan.get("user_id", "default_user")
    plan: Dict[str, Any] = {
        "plan_id": plan_id,
        "user_id": user_id,
        "description": out or "",
        "emojis": emojis,
        "created_on": datetime.datetime.now().isoformat(),
        "modified_on": datetime.datetime.now().isoformat(),
        "parent_id": parent_plan.get("plan_id")
    }
    if emoji_generation and auto_store:
        store_plan([plan], user_id=user_id)
    return plan

def init_plan(user_id: str, background: Optional[str], today: Optional[str] = None) -> Dict[str, Any]:
    plan_id = str(uuid.uuid4())
    instruction = plan_prompt(background, today=today)
    #system_msg = {"role": "system", "content": "You are a focused planning assistant. Produce a concise, numbered plan as instructed."}
    user_msg = {"role": "user", "content": instruction}
    resp = planner_llm.invoke([user_msg])
    out = getattr(resp, "content", None) or str(resp)

    top_plan: Dict[str, Any] = {
        "plan_id": plan_id,
        "user_id": user_id,
        "description": out or "",
        "emojis": [],
        "created_on": datetime.datetime.now().isoformat(),
        "modified_on": datetime.datetime.now().isoformat(),
    }

    #store_plan([top_plan], user_id=user_id)
    child_plan = decompose_plan(top_plan, duration_prompt="1 hour", emoji_generation=False, auto_store=False)
    child_plan_2 = decompose_plan(child_plan, duration_prompt="30 minutes", emoji_generation=True, auto_store=False)
    return {"top_plan": top_plan, "child_plan": child_plan, "child_plan_2": child_plan_2}

def _generate_agent_plans(uid: str, persona: str, today: str) -> tuple:
    """Worker: runs init_plan for one agent and returns (uid, plans_dict).
    Called concurrently — no DB writes happen inside."""
    try:
        plans = init_plan(uid, background=persona, today=today)
        return uid, plans
    except Exception as e:
        print(f"[ERROR] Plan generation failed for {uid}: {e}")
        return uid, None


if __name__ == "__main__":
    AGENT_STATE_DIR = os.path.join(BASE_DIR, "World_Environment", "agent_state.json")

    with open(AGENT_STATE_DIR, 'r', encoding='utf-8') as f:
        agent_data = json.load(f)

    agents = agent_data.get("agents")
    today_str = datetime.date.today().isoformat()
    agent_items = [(uid, info.get("persona")) for uid, info in agents.items()]
    max_workers = min(len(agent_items), 5)

    # Phase 1 — generate all plans concurrently; At most 5 concurrent request
    results: list = []
    print(f"[Planner] Generating plans for {len(agent_items)} agents with {max_workers} workers...")
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Planner") as executor:
        futures = {
            executor.submit(_generate_agent_plans, uid, persona, today_str): uid
            for uid, persona in agent_items
        }
        for future in as_completed(futures):
            uid, plans = future.result()
            if plans is not None:
                results.append((uid, plans))
                print(f"[Planner] Generated plan for {uid}")
            else:
                print(f"[Planner] Skipping store for {uid} due to generation error")

    # Phase 2 — write all plans to DB sequentially (no concurrency issues)
    print(f"[Planner] Storing plans for {len(results)} agents...")
    for uid, plans in results:
        child_plan_2 = plans["child_plan_2"]
        store_plan([child_plan_2], user_id=uid)
        print(f"[Planner] Stored plan for {uid}")

    print(f"[Planner] Done. Plans stored for {len(results)}/{len(agent_items)} agents.")



