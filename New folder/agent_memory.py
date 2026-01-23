import uuid
import sqlite3
import time
from pathlib import Path

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
    c.execute("""CREATE TABLE IF NOT EXISTS messages(
                 user_id TEXT,
                 role TEXT,
                 content TEXT,
                 ts INTEGER
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS summaries(
                 user_id TEXT PRIMARY KEY,
                 summary TEXT,
                 updated_ts INTEGER
                 )""")
    return conn

def add_message(conn, user_id: str, role: str, content: str):
    conn.execute(
        "INSERT INTO messages(user_id, role, content, ts) VALUES (?,?,?,?)",
        (user_id, role, content, int(time.time())),
    )

def get_recent_messages(conn, user_id: str, limit: int = 50):
    cur = conn.execute(
        "SELECT role, content, ts FROM messages WHERE user_id=? ORDER BY ts DESC LIMIT ?",
        (user_id, limit),
    )
    return cur.fetchall()

def get_summary(conn, user_id: str):
    row = conn.execute("SELECT summary FROM summaries WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row else None

def save_summary(conn, user_id: str, summary: str):
    ts = int(time.time())
    conn.execute(
        "INSERT INTO summaries(user_id, summary, updated_ts) VALUES (?,?,?)\n                 ON CONFLICT(user_id) DO UPDATE SET summary=excluded.summary, updated_ts=excluded.updated_ts",
        (user_id, summary, ts),
    )

def recap(conn, user_id: str, recent_limit: int = 50) -> str:
    summary = get_summary(conn, user_id)
    if summary:
        return summary
    msgs = get_recent_messages(conn, user_id, recent_limit)
    if not msgs:
        return "No conversation history found."
    # simple heuristic recap: join last few user messages
    lines = []
    for role, content, ts in reversed(msgs):
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)
