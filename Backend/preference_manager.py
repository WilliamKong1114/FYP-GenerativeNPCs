import json
import re
import random
import sqlite3
import os
import time
from dotenv import load_dotenv
from Secure.llm_config import impression_llm
from World_Environment.agent_state_manager import AgentStateManager
from conversation_manager import ConversationManager

load_dotenv()

PREFERENCE_LIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Preference_List")
AGENT_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "World_Environment", "agent_state.json")

class PreferenceDB:
    def __init__(self, agent_id: str, base_dir: str = PREFERENCE_LIST_DIR):
        os.makedirs(base_dir, exist_ok=True)
        db_path = os.path.join(base_dir, f"{agent_id}_preferences.db")
        self.conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self._ensure_schema()

    def _ensure_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                target_agent_id TEXT NOT NULL PRIMARY KEY,
                impression_score REAL NOT NULL DEFAULT 5.0,
                interaction_count INTEGER NOT NULL DEFAULT 0,
                relationship_type TEXT,
                modified_on INTEGER
            )
        """)

    def init_relationship(self, target_id: str, score: float, relationship_type: str):
        ts = int(time.time())
        self.conn.execute("""
            INSERT OR IGNORE INTO preferences (target_agent_id, interaction_count, impression_score, relationship_type, modified_on)
            VALUES (?, ?, ?, ?, ?)
        """, (target_id, "1", score, relationship_type, ts))

    def get_score(self, target_id: str) -> float:
        row = self.conn.execute(
            "SELECT impression_score FROM preferences WHERE target_agent_id=?", (target_id,)
        ).fetchone()
        if row is None:
            return None
        return row[0]
    
    def get_relationship_type(self, target_id: str) -> str:
        row = self.conn.execute(
            "SELECT relationship_type FROM preferences WHERE target_agent_id=?", (target_id,)
        ).fetchone()
        if row is None:
            return None
        return row[0]
    
    def get_interaction_count(self, target_id: str) -> int:
        row = self.conn.execute(
            "SELECT interaction_count FROM preferences WHERE target_agent_id=?", (target_id,)
        ).fetchone()
        if row is None:
            return None
        return row[0]

    def get_list(self) -> list:
        cur = self.conn.execute(
            "SELECT target_agent_id, impression_score FROM preferences ORDER BY impression_score DESC"
        )
        return cur.fetchall()

    def update_score(self, target_id: str, delta: float):
        score = self.get_score(target_id)
        type = self.get_relationship_type(target_id)
        count = self.get_interaction_count(target_id)
        if score is None:
            score = 5.0
        new_score = max(1.0, min(10.0, score + delta))

        if (type != "Family"):
            if (new_score >= 6.5):
                type = 'Friend'
            elif (new_score > 3.0 and new_score < 6.5):
                type = 'Acquaintance'
            else:
                type = 'Stranger'

        ts = int(time.time())
        self.conn.execute("""
            UPDATE preferences
            SET impression_score=?, interaction_count=?, relationship_type=?, modified_on=?
            WHERE target_agent_id=?
        """, (new_score, count+1, type, ts, target_id))

def init_preference_lists(agent_state_path: str = AGENT_STATE_PATH, base_dir: str = PREFERENCE_LIST_DIR) -> list[str]:
    try:
        with open(agent_state_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        agents = payload.get("agents", {})
        if not isinstance(agents, dict):
            return []

        agent_ids = []
        for agent_id in agents.keys():
            if isinstance(agent_id, str) and agent_id.strip():
                agent_ids.append(agent_id.strip())
    except (OSError, json.JSONDecodeError):
        return []

    for agent_id in agent_ids:
        db = PreferenceDB(agent_id, base_dir)
        db.conn.close()
    return agent_ids

class PreferenceManager:
    def __init__(self, base_dir: str = PREFERENCE_LIST_DIR):
        self.llm = impression_llm
        self.base_dir = base_dir
        self._dbs: dict[str, PreferenceDB] = {}

    def get_db(self, agent_id: str) -> PreferenceDB:
        if agent_id not in self._dbs:
            self._dbs[agent_id] = PreferenceDB(agent_id, self.base_dir)
        return self._dbs[agent_id]

    def init_relationship(self, agent_id: str, target_id: str, score: float, relationship_type: str):
        self.get_db(agent_id).init_relationship(target_id, score, relationship_type)

    def get_relationship_type(self, agent_id: str, target_id: str) -> str:
        return self.get_db(agent_id).get_relationship_type(target_id)

    def get_preference_score(self, agent_id: str, target_id: str) -> float:
        return self.get_db(agent_id).get_score(target_id)

    def get_preference_list(self, agent_id: str) -> list:
        return self.get_db(agent_id).get_list()

    def select_partner(self, agent_id: str, candidates: list[str]) -> str:
        if not candidates:
            return None

        scores = []
        for candidate in candidates:
            score = self.get_db(agent_id).get_score(candidate)
            if score is None:
                score = 3.0
            scores.append((candidate, score))

        random.shuffle(scores)  # ensure random tiebreak
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[0][0]

    def init_impression(self, agent_id: str, persona: list, target_id: str, conv_log: str) -> float:
        prompt = f"""
            You are {agent_id}. You have just had your first conversation with {target_id}.
            Your persona (this defines your preferences, values, and typical behavior): {persona}
            Conversation log between you and {target_id}: {conv_log}
            Task:
            - Based ONLY on this persona and this conversation, rate how interested you are in talking to {target_id} again in the future.
            - The score must reflect {agent_id}'s perspective and personality, not a generic or neutral view.
            - Use a scale from 3.0 to 7.0, with one decimal place (e.g., 3.2, 6.5, 4.8). 3.0 = Not much interest in talking again; 7.0 = Desired to talk again next time.
            - If the conversation log is empty or contains almost no interaction, base your score mostly on your persona and give a moderate score (e.g., around the middle of the scale), not an extreme one.
            Output format:
            - Return ONLY a valid JSON object.
            - Do not include any explanation, comments, or additional fields.
            - The JSON must have exactly one key: \"score\".
            - The value must be a number (float) between 3.0 and 7.0.
            Return ONLY this JSON object, in this format: (score: float)
            """

        response = self.llm.invoke(prompt).content
        try:
            match = re.search(r'\{.*?\}', response, re.DOTALL)
            score = float(json.loads(match.group(0)).get("score", 3.0)) if match else 3.0
        except Exception:
            score = 3.0

        self.get_db(agent_id).init_relationship(target_id, score, 'Stranger')
        print(f"Initialized impression for {agent_id} towards {target_id}: score={score}")
        return score

    def update_impression(self, agent_id: str, persona: list, target_id: str, current_score: float, conv_log: str) -> float:
        prompt = f"""
            You are {agent_id}, you just had a follow-up conversation with {target_id}.
            Your persona (this defines your preferences, values, and typical behavior): {persona}
            Your current impression score for {target_id}: {current_score}
            Conversation log between you and {target_id}: {conv_log}

            Task:
            Your goal is to decide how this specific conversation changes your impression of {target_id}. 
            You MUST evaluate the conversation **through the lens of your persona**. Different personalities
            should produce different emotional reactions to the same events.

            Evaluation rules:
            1. Consider how your persona would *emotionally interpret* this conversation.
            - Someone who dislikes socializing should be drained or irritated by long or chatty interactions.
            - Someone sociable or warm should appreciate cooperation, friendliness, or harmony.
            - Someone stern or traditional should react poorly to disrespect, chaos, or irresponsibility.
            - Someone curious or intellectual should appreciate new ideas or learning moments.
            - Someone impatient should dislike long explanations or slow progress.
            - Someone cautious should appreciate plans, stability, or cooperation.

            2. Rate the emotional impact of the conversation on a scale from -2.0 to +2.0:
            - Strongly negative experience → -2.0 to -1.0
            - Mildly negative → -0.9 to -0.1
            - Neutral → 0.0
            - Mildly positive → +0.1 to +0.9
            - Strongly positive → +1.0 to +2.0
            - If your persona dislikes or gets drained by the interaction style, output a negative delta.
            - If your persona benefits from or enjoys this interaction style, output a positive delta.

            3. Think step-by-step internally (do NOT output reasoning):
            - Identify persona traits that influence emotional reaction.
            - Identify conversation elements that trigger those traits.
            - Determine whether this persona would feel better, worse, or neutral.
            - Convert that emotional impact into a numeric delta.

            Output format:
            - Do not include any explanation, comments, or additional fields.
            - The value must be a number (float) between -2.0 and +2.0.
            Return ONLY this JSON object, in this format: (delta: float)
            """
        
        partner_type = self.get_db(agent_id).get_relationship_type(target_id)
        if partner_type == "Family":
            return 0.0
        response = self.llm.invoke(prompt).content
        try:
            match = re.search(r'\{.*?\}', response, re.DOTALL)
            delta = float(json.loads(match.group(0)).get('delta', 0.0))
        except Exception:
            delta = 0.0

        self.get_db(agent_id).update_score(target_id, delta)
        print(f"Updated impression for {agent_id} towards {target_id}: delta={delta}")
        return delta

def main():
    from execute_plan import get_graph
    pref_manager = PreferenceManager()
    conv_manager = ConversationManager(graph=get_graph(), preference_manager=pref_manager)
    agents_state = AgentStateManager().get_agent_state()
    agents_config = [
        {
            "id": name,
            "persona": data["persona"],
            "home_node": data["home_node"],
            "home_area": data["home_area"]
        }
        for name, data in agents_state.items()
    ]

    agent_executions = {
        config["id"]: {
            "persona": config["persona"],
            "steps": [],
            "emojis": [],
            "current_step": 0,
            "is_busy_until": 0,
            "is_chatting": False,
            "is_reflecting": False,
            "active_task": None,    # Track running future
            "current_target": config["home_node"],  # Track current target node
            "current_area": config["home_area"],    # Track current area
            "prev_target": None,
            "prev_area": None
        } for config in agents_config
    }

    agent_id = "Jimmy"
    potential_partners = ["Samson", "Swithin Eldrede", "Beowulf Warwicke"]
    partner_id = pref_manager.select_partner(agents_config[0]["id"], potential_partners)
    group = [
        {"id": agent_id, "persona": agent_executions[agent_id]["persona"]},
        {"id": partner_id, "persona": agent_executions[partner_id]["persona"]}
    ]
    conv_manager.handle_conversation("Garden", group, agent_executions)
    
if __name__ == "__main__":
    main()
