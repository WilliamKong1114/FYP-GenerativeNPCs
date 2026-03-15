import uuid
import sqlite3
import time
import json
import os
from pathlib import Path
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "Database", "agent_memory.db")

#ID_FILE = Path.home() / ".agent_temp_user_id"
#DB_FILE = Path("agent_memory.db")

class AgentMemoryManager:
    def __init__(self, db_path: str = DB_PATH):
        self.conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
        self.user_id = str(uuid.uuid4()) #random user ID

    def add_conversation_log(self, participants: list, log_string: str, place: str):        
        log_id = str(uuid.uuid4())
        participants_json = json.dumps(participants)
        created_on = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO conversation_logs(id, participants, log_string, place, createdOn, ts) VALUES (?,?,?,?,?,?)",
            (log_id, participants_json, log_string, place, created_on, int(time.time())),
        )
        return log_id

    def get_recent_conversation_logs(self, user_id: str, limit: int = 5):
        user_id = user_id or self.user_id
        cur = self.conn.execute(
            "SELECT participants, log_string, place, createdOn FROM conversation_logs WHERE participants LIKE ? ORDER BY ts DESC LIMIT ?",
            (f'%"{user_id}"%', limit),
        )
        return cur.fetchall()

    def get_conv_logs_between(self, agent_a: str, agent_b: str, limit: int = 1):
        conv_pair = [agent_a, agent_b]
        if not conv_pair:
            return []

        pair_1 = json.dumps(conv_pair)
        pair_2 = json.dumps(conv_pair[::-1])

        cur = self.conn.execute(
            "SELECT id, participants, log_string, place, createdOn, ts "
            "FROM conversation_logs WHERE participants IN (?, ?) ORDER BY ts DESC LIMIT ?",
            (pair_1, pair_2, limit),
        )
        return cur.fetchall()

    def get_summary(self, user_id: str):
        user_id = user_id or self.user_id
        row = self.conn.execute(
            "SELECT summary FROM summaries WHERE user_id=? ORDER BY ts DESC LIMIT 1", 
            (user_id,)
        ).fetchone()
        return row[0] if row else None

    def save_summary(self, user_id: str, summary: str, importance: int, log_id: str = None):
        user_id = user_id or self.user_id
        summary_id = str(uuid.uuid4())
        ts = int(time.time())
        self.conn.execute(
            "INSERT INTO summaries(id, user_id, summary, importance, log_id, ts) VALUES (?,?,?,?,?,?)",
            (summary_id, user_id, summary, importance, log_id, ts),
        )

    def add_observation(self, observer_id: str, obs_string: str, place: str) -> None:
        created_on = datetime.now().isoformat()
        summary_id = str(uuid.uuid4())
        ts = int(time.time())

        self.conn.execute(
            "INSERT INTO observation(id, user_id, description, place, createdOn, ts) VALUES (?,?,?,?,?,?)",
            (summary_id, observer_id, obs_string, place, created_on, ts),
        )

    def get_recent_observations(self, user_id: str, limit: int = 5):
        cur = self.conn.execute(
            "SELECT user_id, description, place, createdOn "
            "FROM observation WHERE user_id=? ORDER BY ts DESC LIMIT ?",
            (user_id, limit),
        )
        return cur.fetchall()

    def save_reflection(self, user_id: str, insight: str, importance: int, cited_memories: list) -> str:
        ts = int(time.time())
        cur = self.conn.execute(
            "INSERT INTO reflection(user_id, insight, importance, cited_memories, ts, used)"
            " VALUES (?,?,?,?,?,?)",
            (user_id, insight, importance, json.dumps(cited_memories), ts, 0),
        )
        return str(cur.lastrowid)

    def get_importance_score(self, user_id: str) -> float:
        imp_score_imp = self.conn.execute(
            "SELECT IFNULL(SUM(CAST(importance AS REAL)), 0) FROM summaries"
            " WHERE user_id=? AND used=0", (user_id,)
        ).fetchone()[0]

        imp_score_ref = self.conn.execute(
            "SELECT IFNULL(SUM(CAST(importance AS REAL)), 0) FROM reflection"
            " WHERE user_id=? AND used=0", (user_id,)
        ).fetchone()[0]

        obs_score = self.conn.execute(
            "SELECT COUNT(*) FROM observation WHERE user_id=? AND used=0",
            (user_id,)
        ).fetchone()[0]
        return float(imp_score_imp + imp_score_ref) + obs_score * 1.5

    def mark_records_used(self, user_id: str) -> None:
        """Mark all unused summaries and observations as used, resetting the importance accumulator."""
        self.conn.execute("UPDATE summaries SET used=1 WHERE user_id=? AND used=0", (user_id,))
        self.conn.execute("UPDATE observation SET used=1 WHERE user_id=? AND used=0", (user_id,))
        self.conn.execute("UPDATE reflection SET used=1 WHERE user_id=? AND used=0", (user_id,))

    def get_mixed_records(self, user_id: str, limit: int = 100) -> list:
        rows = self.conn.execute("""
            SELECT 'summary' AS source, summary AS text, ts
            FROM summaries WHERE user_id=? AND used=0
            UNION ALL
            SELECT 'observation', description, ts
            FROM observation WHERE user_id=? AND used=0
            UNION ALL
            SELECT 'reflection', insight, ts
            FROM reflection WHERE user_id=? AND used=0
            ORDER BY ts DESC LIMIT ?
        """, (user_id, user_id, user_id, limit)).fetchall()
        return [{"source": r[0], "text": r[1], "ts": r[2]} for r in rows]