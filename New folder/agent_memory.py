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
        self._ensure_schema()

    def _ensure_schema(self):
        for col, col_type in [("place", "TEXT"), ("createdOn", "TEXT"), ("ts", "INTEGER")]:
            try:
                self.conn.execute(f"ALTER TABLE observation ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # Column already exists

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

    def get_summary(self, user_id: str):
        user_id = user_id or self.user_id
        row = self.conn.execute(
            "SELECT summary FROM summaries WHERE user_id=? ORDER BY created_ts DESC LIMIT 1", 
            (user_id,)
        ).fetchone()
        return row[0] if row else None

    def save_summary(self, user_id: str, summary: str, importance: int, log_id: str = None):
        user_id = user_id or self.user_id
        summary_id = str(uuid.uuid4())
        ts = int(time.time())
        self.conn.execute(
            "INSERT INTO summaries(id, user_id, summary, importance, log_id, created_ts) VALUES (?,?,?,?,?,?)",
            (summary_id, user_id, summary, importance, log_id, ts),
        )

    def add_observation(self, observer_id: str, obs_string: str, place: str) -> None:
        created_on = datetime.now().isoformat()
        summary_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO observation(id, user_id, description, place, createdOn, ts) VALUES (?,?,?,?,?,?)",
            (summary_id, observer_id, obs_string, place, created_on, int(time.time())),
        )

    def get_recent_observations(self, user_id: str, limit: int = 5):
        cur = self.conn.execute(
            "SELECT user_id, description, place, createdOn "
            "FROM observation WHERE user_id=? ORDER BY ts DESC LIMIT ?",
            (user_id, limit),
        )
        return cur.fetchall()


"""     def init_db(path: str | Path = DB_FILE):
        conn = sqlite3.connect(str(path), isolation_level=None)
        c = conn.cursor()
        c.execute(CREATE TABLE IF NOT EXISTS summaries(
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    summary TEXT,
                    log_id TEXT,
                    created_ts INTEGER
                    ))
        c.execute(ALTER TABLE summaries ADD COLUMN log_id TEXT)        
        c.execute(CREATE TABLE IF NOT EXISTS conversation_logs(
                    id TEXT PRIMARY KEY,
                    participants TEXT,
                    log_string TEXT,
                    place TEXT,
                    createdOn TEXT,
                    ts INTEGER
                    ))
        return conn"""
