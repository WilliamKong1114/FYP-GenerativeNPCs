import json
import os
import socket
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AREAS_DIR = os.path.join(BASE_DIR, "areas")
AGENT_STATE_DIR = os.path.join(BASE_DIR, "agent_state.json")

class AreaStateManager:
    def __init__(self, area_name):
        self.area_name = area_name
        self.file_path = os.path.join(AREAS_DIR, f"{area_name}.json")
        self.lock = threading.RLock()
        self.state = {"objects": {}, "agents": []}
        self.load_state()

    def load_state(self):
        with self.lock:
            if os.path.exists(self.file_path):
                with open(self.file_path, "r") as f:
                    self.state = json.load(f)
            else:
                self.save_state()

    def save_state(self):
        with self.lock:
            with open(self.file_path, 'w') as f:
                json.dump(self.state, f, indent=4)

    def get_area_state(self):
        with self.lock:
            objects = self.state.get("objects", {})
            #agents_in_area = list({details.get("occupied_by") for details in objects.values() if details.get("occupied_by")})
            return objects
    
    def get_agents_in_area(self):
        with self.lock:
            agent_list = self.state.get("agents", [])
            return agent_list

    def set_agent_in_area(self, agent: str, area: str, status: str):
        with self.lock:
            agents = self.state.get("agents", [])        
            if status == "enter":
                if agent not in agents:
                    agents.append(agent)
            elif status == "exit":
                if agent in agents:
                    agents.remove(agent)
            self.save_state()

    def set_area_state(self, obj_name, state, agent_id=None):
        with self.lock:
            if "objects" not in self.state:
                self.state["objects"] = {}
            self.state["objects"][obj_name] = {
                "state": state,
                "occupied_by": agent_id
            }
            self.save_state()

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
                    mgr.set_agent_in_area(agent, area, status) 
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
                if filename.endswith(".json"):
                    area_name = filename[:-5]
                    mgr = self.get_manager(area_name)
                    with mgr.lock:
                        mgr.state["agents"] = []
                        if "objects" in mgr.state:
                            for obj in mgr.state["objects"]:
                                mgr.state["objects"][obj]["state"] = "empty"
                                mgr.state["objects"][obj]["occupied_by"] = None
                        mgr.save_state()
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
                with mgr.lock:
                    mgr.set_area_state(home_node, "occupied", agent_id)