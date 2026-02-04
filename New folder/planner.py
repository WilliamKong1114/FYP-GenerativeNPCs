import sqlite3
import uuid
import datetime
import json as _json
import vertexai
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
from langchain_google_vertexai import ChatVertexAI

load_dotenv()
PLANS_DB = Path("plans.db")
vertexai.init(project="finalyearproject-473307", location="us-central1")

llm = ChatVertexAI(
    model="gemini-2.5-flash",
    temperature=0.2,
    max_tokens=None,
    max_retries=3,
    stop=None,
)

def _init_db(path: Path = PLANS_DB):
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS plans(
            plan_id TEXT PRIMARY KEY,
            user_id TEXT,
            plan_json TEXT,
            description TEXT,
            created_on TEXT,
            modified_on TEXT,
            parent_id TEXT
        )"""
    )
    try:
        cur.execute("ALTER TABLE plans ADD COLUMN parent_id TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn

def store_plan(plan: List[Dict[str, Any]], user_id: str = "default_user", parent_id: Optional[str] = None) -> List[str]:
    conn = _init_db(PLANS_DB)
    cur = conn.cursor()
    ids = []
    for p in plan:
        plan_id = p.get("plan_id") or str(uuid.uuid4())        
        cur.execute(
            "INSERT OR REPLACE INTO plans(plan_id, user_id, plan_json, description, created_on, modified_on, parent_id) VALUES (?,?,?,?,?,?,?)",
            (plan_id, user_id, _json.dumps(p), p.get("description"), p.get("created_on"), p.get("modified_on"), parent_id or p.get("parent_id")),
        )
        ids.append(plan_id)
        
    conn.commit()
    conn.close()
    return ids

def plan_prompt(background: str, today: Optional[str] = None) -> str:
    now = today or datetime.date.today().isoformat()
    instruction = (
        "You are a helpful planning assistant.\n"
        "Given the person's profile and activities below, generate a concise plan for today as it would realistically occur in a medieval village setting\n"
        "Reply with a short, numbered list of broad strokes for the day which follows the format with time section.\n"
        "Use short sentences, contractions, and everyday language"
        "Avoid sounding overly formal or poetic"
        "Avoid repeating previous statements unless necessary"
        "Requirements:\n"
        "1) Produce 5–8 high-level items for today's plan, numbered\n"
        "2) Keep each item to one sentence\n"
        "3) Use the persona details to prioritize tasks and habits\n"
        "4) Use short sentences, contractions, and everyday language\n"
        "5) Avoid sounding overly formal or poetic\n"
        "6) Avoid repeating previous statements unless necessary\n"
        f"Persona and context:\n{background}\n"
        "Output format:\n"
        "1) Woke up and complete the morning routine at 7:00 am\n"
        "2) Gardening the backyard at 8:00 am to 11:00 am\n"
        "...\n"
        "8) Get ready to sleep around 10:00 pm.\n"
    )
    return instruction

def decompose_plan(parent_plan: Dict[str, Any], duration_prompt: str) -> Dict[str, Any]:
    system_msg = {"role": "system", "content": f"You are a helpful planning assistant that breaks down plans into finer-grained actions with time durations of {duration_prompt}."}
    user_msg = {"role": "user", "content": (
            f"Given the following plan description, break it down into finer-grained actions with provided time durations of {duration_prompt} for each sentence.\n"
            "The plan should be as it would realistically occur in a medieval village setting"
            f"Plan Description:\n{parent_plan.get('description')}\n"
            "Output each step as a sentence. Return a concise, numbered list of actions."
            "Requirements:\n"
            "1) Keep each item to one 10 to 15 words sentence with the name of the location or object that the action is performed at\n"
            "2) Use relevant details to prioritize tasks and habits\n"
            "3) Avoid sounding overly formal or poetic\n"
            "4) Try to elaborate or extend the content where possible with reasonable activity\n"
            "Output format example:\n"
            "1) 8:00 am: Tend the dirt land with tools to make the dirt better to be planted\n"
            "2) 9:30 am: Check the river for fish to prepare for the lunch later\n"
        ),
    }
    resp = llm.invoke([system_msg, user_msg])
    out = getattr(resp, "content", None) or str(resp)
    
    plan_id = str(uuid.uuid4())
    user_id = parent_plan.get("user_id", "default_user")
    plan: Dict[str, Any] = {
        "plan_id": plan_id,
        "user_id": user_id,
        "description": out or "",
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
        "created_on": datetime.datetime.now().isoformat(),
        "modified_on": datetime.datetime.now().isoformat(),
    }

    store_plan([top_plan], user_id=user_id)
    child_plan = decompose_plan(top_plan, duration_prompt="1 hour")   
    child_plan_2 = decompose_plan(child_plan, duration_prompt="15 minutes")      
    return {"top_plan": top_plan, "child_plan": child_plan, "child_plan_2": child_plan_2}

if __name__ == "__main__":
    uid = "default_user"
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    persona = ("Name: Ben (age: 19)\n"
        "Innate traits: friendly, outgoing. "
        "Ben is a young villager living in a small medieval settlement near a river and pasturelands, with forests not far from the village edge."
        "He was born to a farming family and learned from an early age how to tend crops, care for simple tools, and respect the rhythms of the seasons."
        "He enjoys helping others like growing fruit or vegetables, fishing, and woodworking. "
        "He has a small workshop where he crafts simple furniture and tools. "
        "Ben is also keen on learning new skills from travelers passing through the village.\n "
        "Goals: Improve his woodworking skills to create more intricate furniture, expand his garden to include a wider variety of plants, and build stronger relationships within the village community, and busy to get ready for the coming winter.")
    init_plan(uid, background=persona, today="2026-02-13")
    print(f"Plan stored in {PLANS_DB} for user: {uid}")
