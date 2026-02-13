import sqlite3
import uuid
import datetime
import json
import re
import os
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
from Secure.llm_config import planner_llm as llm

load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "Database", "plans.db")

# llm definition moved to llm_config.py

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
            "INSERT OR REPLACE INTO plans(plan_id, user_id, plan_json, description, created_on, modified_on, parent_id) VALUES (?,?,?,?,?,?,?)",
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
            "provide exactly two emojis that best represent it. Do not add or include any gender signs or symbols.\n"
            "Return ONLY a JSON list of strings, where each string contains the two emojis. "
            "STRICT RULES:\n"
            "1. Use ONLY base Unicode emojis.\n"
            "2. DO NOT use skin tone modifiers or gender variants.\n"
            "3. Do not include markdown formatting or numbering in the output.\n\n"
            f"Actions:\n{actions_formatted}\n\n"
            "Output Example:\n"
            '["🚶‍♂️🌲", "📖🕯️", "😴🌙"]'
        )
        response = llm.invoke(prompt)
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
    now = today or datetime.date.today().isoformat()
    instruction = (
        "You are a helpful planning assistant.\n"
        "Given the person's profile and activities below, generate a concise plan for today as it would realistically occur in a medieval village setting\n"
        "Reply with a numbered list of broad strokes for the day which STRICTLY follows the output format.\n"
        
        f"Persona and context:\n{background}\n"
        
        "Requirements:\n"
        "1) Produce 5–8 high-level items for today's plan, numbered\n"
        "2) Keep each item to one sentence\n"
        "3) Use the persona details to prioritize tasks and habits\n"
        "4) Use short sentences, contractions, and everyday language\n"
        "5) Avoid sounding overly formal or poetic\n"
        
        "Output format (STRICT):\n"
        "1) Woke up and complete the morning routine at 7:00 am\n"
        "2) Gardening the backyard at 8:00 am to 11:00 am\n"
        "...\n"
        "8) Get ready to sleep around 10:00 pm.\n"
    )
    return instruction

def decompose_plan(parent_plan: Dict[str, Any], duration_prompt: str, emoji_generation: bool = False) -> Dict[str, Any]:
    system_msg = {"role": "system", "content": f"You are a planning assistant that breaks down plans into finer-grained actions."}
    user_msg = {"role": "user", "content": (
            f"Given the following plan description, break it down into finer-grained actions with provided time durations of {duration_prompt} for each sentence.\n"
            "The plan should be as it would realistically happens in a medieval village setting\n"
            f"Plan Description:\n{parent_plan.get('description')}\n"
            "Output each step as a sentence. Return a concise, numbered list of actions."
            
            "Requirements:\n"
            "1) Start each line with \"1) 6:00 am:\" format, then write a 10–15 word sentence.\n"
            "2) Use a single consistent character name who performs all actions.\n"
            "3) Combine related tasks into one action per time slot where reasonable.\n"
            "4) Maintain a simple, grounded tone without sounding poetic or overly formal.\n"
            "5) Ensure each action includes a location or object (e.g., \"at the herb garden,\" \"in the weaving hut\").\n"
            "6) The progression must follow a realistic medieval village routine with natural movement across locations.\n"
            
            "Output format (STRICT):\n"
            "1) 8:00 am: Tend the dirt land with tools to make the dirt better to be planted\n"
            "2) 9:30 am: Check the river for fish to prepare for the lunch later\n"
        ),
    }
    resp = llm.invoke([system_msg, user_msg])
    out = getattr(resp, "content", None) or str(resp)
    
    emojis = []
    if emoji_generation:
        lines = (out or "").split('\n')
        actions = []
        pattern = re.compile(r'\d+\)\s+(\d+:\d+\s+[ap]m):\s+(.*)')
        for line in lines:
            match = pattern.match(line.strip())
            if match:
                actions.append(match.group(2))
        
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
    store_plan([plan], user_id=user_id)
    return plan

def init_plan(user_id: str, background: Optional[str], today: Optional[str] = None) -> Dict[str, Any]:
    plan_id = str(uuid.uuid4())
    instruction = plan_prompt(background, today=today)
    system_msg = {"role": "system", "content": "You are a focused planning assistant. Produce a concise, numbered plan as instructed."}
    user_msg = {"role": "user", "content": instruction}
    resp = llm.invoke([system_msg, user_msg])
    out = getattr(resp, "content", None) or str(resp)

    top_plan: Dict[str, Any] = {
        "plan_id": plan_id,
        "user_id": user_id,
        "description": out or "",
        "emojis": [],
        "created_on": datetime.datetime.now().isoformat(),
        "modified_on": datetime.datetime.now().isoformat(),
    }

    store_plan([top_plan], user_id=user_id)
    child_plan = decompose_plan(top_plan, duration_prompt="1 hour", emoji_generation=False)   
    child_plan_2 = decompose_plan(child_plan, duration_prompt="15 minutes", emoji_generation=True)      
    return {"top_plan": top_plan, "child_plan": child_plan, "child_plan_2": child_plan_2}

if __name__ == "__main__":
    uid = "Jimmy"
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    persona = ("Name: Jimmy (age: 54)\n"
        "Innate traits: calm, dependable, observant."
        "Jimmy is a 53‑year‑old villager who has spent his entire life in a modest medieval settlement nestled between rolling pasturelands and a slow‑moving river. Behind the village lie dense woodlands where he often walks to observe wildlife and gather smooth branches for crafting."
        "He was born into a family known for their skill in weaving and dyeing textiles, and from an early age he learned how to work with fibers, mix natural pigments, and appreciate the rhythm of careful handiwork. Over the decades, Jimmy became admired for his steady presence, gentle manner, and practical advice during busy harvest seasons."
        "He enjoys spinning wool, weaving sturdy cloth for villagers, and experimenting with natural dyes using flowers, bark, and roots gathered from the forest. His weaving hut—filled with spindles, dyed yarn bundles, and a well‑worn loom—is where he spends most afternoons working on new patterns."
        "His normal daily routine includes checking on drying fabrics hung behind his home, tending a few herb beds used for dyes, taking calm walks along the woods to gather plants, and speaking with travelers to exchange stories about trade routes and new weaving techniques. In the evenings, he often sits by the communal fire, sharing small handmade gifts or teaching basic weaving skills to younger villagers.")
    init_plan(uid, background=persona, today="2026-02-13")
    print(f"Plan stored in {DB_PATH} for user: {uid}")
