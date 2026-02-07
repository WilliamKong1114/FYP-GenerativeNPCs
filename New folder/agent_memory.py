import uuid
import sqlite3
import time
import json
from pathlib import Path
from datetime import datetime

ID_FILE = Path.home() / ".agent_temp_user_id"
DB_FILE = Path("agent_memory.db")

def get_or_create_user_id(id_file_path: Path = ID_FILE) -> str:
    if id_file_path.exists():
        return id_file_path.read_text().strip()
    uid = str(uuid.uuid4())
    id_file_path.write_text(uid)
    return uid

def init_db(path: str | Path = DB_FILE):
    conn = sqlite3.connect(str(path), isolation_level=None)
    c = conn.cursor()
    # Summaries now accumulative (no primary key on user_id)
    c.execute("""CREATE TABLE IF NOT EXISTS summaries(
                 id TEXT PRIMARY KEY,
                 user_id TEXT,
                 summary TEXT,
                 log_id TEXT,
                 created_ts INTEGER
                 )""")
    # Ensure log_id column exists if table was created previously
    try:
        c.execute("ALTER TABLE summaries ADD COLUMN log_id TEXT")
    except sqlite3.OperationalError:
        pass # Column already exists
    
    # Conversation logs updated structure
    c.execute("""CREATE TABLE IF NOT EXISTS conversation_logs(
                 id TEXT PRIMARY KEY,
                 participants TEXT,
                 log_string TEXT,
                 place TEXT,
                 createdOn TEXT,
                 ts INTEGER
                 )""")
    return conn

def add_conversation_log(conn, participants: list, log_string: str, place: str):
    log_id = str(uuid.uuid4())
    participants_json = json.dumps(participants)
    created_on = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO conversation_logs(id, participants, log_string, place, createdOn, ts) VALUES (?,?,?,?,?,?)",
        (log_id, participants_json, log_string, place, created_on, int(time.time())),
    )
    return log_id

def get_recent_conversation_logs(conn, user_id: str, limit: int = 5):
    # Retrieve logs where user_id is in the participants JSON string
    # Using simple LIKE for JSON array check (not perfect but minimal dependency)
    like_pattern = f'%"{user_id}"%'
    cur = conn.execute(
        "SELECT participants, log_string, place, createdOn FROM conversation_logs WHERE participants LIKE ? ORDER BY ts DESC LIMIT ?",
        (like_pattern, limit),
    )
    return cur.fetchall()

def get_summary(conn, user_id: str):
    # Get the latest summary
    row = conn.execute(
        "SELECT summary FROM summaries WHERE user_id=? ORDER BY created_ts DESC LIMIT 1", 
        (user_id,)
    ).fetchone()
    return row[0] if row else None

def save_summary(conn, user_id: str, summary: str, log_id: str = None):
    summary_id = str(uuid.uuid4())
    ts = int(time.time())
    conn.execute(
        "INSERT INTO summaries(id, user_id, summary, log_id, created_ts) VALUES (?,?,?,?,?)",
        (summary_id, user_id, summary, log_id, ts),
    )

def recap(conn, user_id: str, recent_limit: int = 5) -> str:
    summary = get_summary(conn, user_id)
    if summary:
        return summary
    logs = get_recent_conversation_logs(conn, user_id, 1)
    if not logs:
        return "No conversation history found."
    # Return the most recent conversation log
    return logs[0][1] # log_string
