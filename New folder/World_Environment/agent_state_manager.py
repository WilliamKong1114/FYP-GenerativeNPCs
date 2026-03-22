import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "agent_state.json")

class AgentStateManager:
    def __init__(self, file_path=STATE_FILE):
        self.state_file = file_path
        self.state = {
            "agents": {},
            "time": ""
        }
        self.load_state()

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
                        self.state.update(data)
                        return self.state
                    return self.state
            except (json.JSONDecodeError, IOError):
                pass
        self.save_state()
        return self.state

    def save_state(self):
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=4)

    def set_time(self, time_string):
        self.state["time"] = time_string
        self.save_state()

    def reset_agents(self):
        for agent_id, config in self.state["agents"].items():
            home = config.get("home_node", f"House_{agent_id}")
            config.update({
                "action": f"{agent_id} is resting at home."
            })
            
        self.save_state()
