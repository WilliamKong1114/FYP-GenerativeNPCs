import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "agent_state.json")
SIM_TIME_FILE = os.path.join(BASE_DIR, "simulationTime.json")

class AgentStateManager:
    def __init__(self, file_path=STATE_FILE, time_file=SIM_TIME_FILE):
        self.state_file = file_path
        self.time_file = time_file
        self.state = {
            "agents": {}
        }
        self.simulation_time = {
            "time": ""
        }
        legacy_time = self.load_state()
        self.load_simulation_time(legacy_time)

    def get_agent_state(self):
        return self.state.get("agents", {})
        
    def set_agent_state(self, agent_id, action_desc):
        if agent_id not in self.state["agents"]:
            self.state["agents"][agent_id] = {}

        self.state["agents"][agent_id].update({
            "action": action_desc,
        })
        self.save_state()

    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content:
                        data = json.loads(content)
                        legacy_time = data.pop("time", "")
                        self.state.update(data)
                        return legacy_time
                    return ""
            except (json.JSONDecodeError, IOError):
                pass
        self.save_state()
        return ""

    def load_simulation_time(self, fallback_time=""):
        if os.path.exists(self.time_file):
            try:
                with open(self.time_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        self.simulation_time.update(json.loads(content))
                        return
            except (json.JSONDecodeError, IOError):
                pass

        if fallback_time:
            self.simulation_time["time"] = fallback_time
        self.save_simulation_time()

    def save_state(self):
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=4)

    def save_simulation_time(self):
        with open(self.time_file, 'w', encoding='utf-8') as f:
            json.dump(self.simulation_time, f, indent=4)

    def get_time(self):
        return self.simulation_time.get("time", "")

    def set_time(self, time_string):
        self.simulation_time["time"] = time_string
        self.save_simulation_time()

    def reset_agents(self):
        for agent_id, config in self.state["agents"].items():
            home = config.get("home_node", f"House_{agent_id}")
            config.update({
                "action": f"{agent_id} is resting at home."
            })
            
        self.save_state()
