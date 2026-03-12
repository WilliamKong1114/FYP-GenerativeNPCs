import json
import os
import socket
import sqlite3
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AREAS_DIR = os.path.join(BASE_DIR, "areas")
AGENT_STATE_DIR = os.path.join(BASE_DIR, "agent_state.json")

class AreaStateManager:
    def __init__(self, area_name):
        self.area_name = area_name
        self.db_path = os.path.join(AREAS_DIR, f"{area_name}.db")
        self.lock = threading.RLock()
        with self._get_conn() as conn:
            pass

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")     #.wal(Write-Ahead Log) is a temp log file to store changes before being applied to the main db; .shm(Shared Memory) is used for coordinating access between multiple connection to the same database.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS objects (
                name        TEXT PRIMARY KEY,
                state       TEXT NOT NULL DEFAULT 'empty',
                occupied_by TEXT)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                name TEXT PRIMARY KEY)
        """)
        conn.commit()
        return conn

    def get_area_state(self):
        with self.lock:
            with self._get_conn() as conn:
                cur = conn.execute("SELECT name, state, occupied_by FROM objects")
                return {
                    row[0]: {"state": row[1], "occupied_by": row[2]}
                    for row in cur.fetchall()
                }

    def get_agents_in_area(self):
        with self.lock:
            with self._get_conn() as conn:
                cur = conn.execute("SELECT name FROM agents")
                return [row[0] for row in cur.fetchall()]

    def set_agent_in_area(self, agent: str, area: str, status: str):
        with self.lock:
            with self._get_conn() as conn:
                if status == "enter":
                    conn.execute("INSERT OR IGNORE INTO agents (name) VALUES (?)", (agent,))
                elif status == "exit":
                    conn.execute("DELETE FROM agents WHERE name = ?", (agent,))
                conn.commit()

    def set_obj_state(self, obj_name, state, agent_id=None):
        with self.lock:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO objects (name, state, occupied_by) VALUES (?, ?, ?)",
                    (obj_name, state, agent_id)
                )
                conn.commit()

class AreaSystem:
    def __init__(self):
        self.area_managers = {}
        self.area_lock = threading.RLock()
        self.listener_socket = None

    def get_manager(self, area_name):
        with self.area_lock:
            if area_name not in self.area_managers:
                self.area_managers[area_name] = AreaStateManager(area_name)
            return self.area_managers[area_name]

    def start_listener(self, port=5006):
        def handle_client(conn):
            with conn:
                data = conn.recv(1024).decode('utf-8').strip()
                if data:
                    agent, area, status = json.loads(data)
                    mgr = self.get_manager(area)
                    #mgr.set_agent_in_area(agent, area, status) 
                    #print(f"[AreaUpdate] {agent} {status}ed {area}")

        def server_loop():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    self.listener_socket = s
                    s.bind(('0.0.0.0', port))
                    s.listen()
                    while True:
                        conn, _ = s.accept()
                        threading.Thread(target=handle_client, args=(conn,), daemon=True).start()
            except OSError:
                print("[AreaListener] Socket closed, stopping listener.")    
        
        threading.Thread(target=server_loop, daemon=True).start()

    def stop_listener(self):
        if self.listener_socket:
            self.listener_socket.close()
            self.listener_socket = None

    def reset_area(self):        
        if not os.path.exists(AREAS_DIR):
            return
        
        with self.area_lock:
            for filename in os.listdir(AREAS_DIR):
                if filename.endswith(".db"):
                    area_name = filename[:-3]
                    mgr = self.get_manager(area_name)
                    with mgr.lock:
                        with mgr._get_conn() as conn:
                            conn.execute("UPDATE objects SET state = 'empty', occupied_by = NULL")
                            conn.execute("DELETE FROM agents")
                            conn.commit()
            #print("[AreaManager] All area agent lists and object states have been reset.")

        if not os.path.exists(AGENT_STATE_DIR):
            return

        with open(AGENT_STATE_DIR, 'r') as f:
            agent_data = json.load(f)

        agents = agent_data.get("agents")
        for agent_id, agent_info in agents.items():
            home_node = agent_info.get("home_node")
            home_area = agent_info.get("home_area")
            if home_node and home_area:
                mgr = self.get_manager(home_area)
                mgr.set_obj_state(home_node, "occupied", agent_id)