import uuid
import sqlite3
import time
import json
import os
import threading
from pathlib import Path
from datetime import datetime
from chroma_client import get_client
chroma_client = get_client(path="./chroma_db")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "Database", "agent_memory.db")

#ID_FILE = Path.home() / ".agent_temp_user_id"
#DB_FILE = Path("agent_memory.db")

class AgentMemoryManager:
    def __init__(self, db_path: str = DB_PATH):
        self.conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
        self._db_lock = threading.Lock()
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
        observer_id = str(observer_id) if observer_id is not None else ""
        obs_string = str(obs_string) if obs_string is not None else ""
        place = str(place) if place is not None else ""

        # Observation writes can come from worker threads, so guard shared connection access.
        with self._db_lock:
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

    def get_reflection(self, user_id: str, limit: int = 5):
        row = self.conn.execute(
            "SELECT insight FROM reflection WHERE user_id=? ORDER BY ts DESC LIMIT ?", 
            (user_id, limit)
        ).fetchall()
        return row if row else None

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
    
    def get_memory(self, query, user_id: str, current_hours: int, partner_id: str = None):
        try:
            if isinstance(query, list):
                query = " ".join(query)

            all_docs = []
            all_metas = []
            all_dists = []
            target_count = 5
            collections = ["summary", "reflection", "observation"]

            for col_name in collections:
                results = chroma_client.get_or_create_collection(col_name).query(
                    query_texts=[query],
                    n_results=target_count,
                    where={"user_id": user_id}
                )
                if results["documents"] and results["documents"][0]:
                    all_docs.extend(results["documents"][0])
                    all_metas.extend(results["metadatas"][0])
                    all_dists.extend(results["distances"][0])

            if not all_docs:
                return "No memories found."
            
            retrieved_memories = []
            DISTANCE_THRESHOLD = 1.5

            for doc, meta, dist in zip(all_docs, all_metas, all_dists):
                if dist > DISTANCE_THRESHOLD:
                    continue

                relevance = 1.0 / (1.0 + dist)
                importance = meta.get("importance", 3) / 10.0
                last_accessed = meta.get("modified_on", 0)
                delta_t = max(0, current_hours - last_accessed)
                recency = pow(0.99, delta_t)

                final_score = (0.5 * recency) + (0.3 * importance) + (0.2 * relevance)

                if partner_id and partner_id.lower() in doc.lower():
                    final_score *= 1.5
                
                retrieved_memories.append((doc, final_score))

            retrieved_memories.sort(key=lambda x: x[1], reverse=True)
            top_memories = [m[0] for m in retrieved_memories[:5]]
            
            if not top_memories:
                return "No highly relevant memories found."
            
            return f"\nRelevant memories: {top_memories}"
            #Return example: "\nRelevant memories: [memory1, memory2, memory3]"

        except Exception as e:
            print(f"Error retrieving memory context: {e}")
            return ""

if __name__ == "__main__":
    # Test script for get_memory function
    test_query = "What is the agent's favorite fruit?"
    test_user_id = "test_user_123"
    test_current_hours = 100
    
    print(f"Testing get_memory with query: '{test_query}'")
    
    # Note: This requires a running ChromaDB or appropriate mock
    # If the collection doesn't exist or is empty, it should return an empty string or relevant message
    try:
        memory_result = AgentMemoryManager().get_memory(
            query=test_query,
            user_id=test_user_id,
            current_hours=test_current_hours
        )
        print(f"Result: {memory_result}")
    except Exception as e:
        print(f"Test failed with error: {e}")

