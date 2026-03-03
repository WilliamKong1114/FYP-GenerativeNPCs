import json
import os

class AgentStateManager:
    def __init__(self, file_path="World_Environment/agent_state.json"):
        self.state_file = file_path
        self.state = {"agents": {}, "time": "unknown"}
        self.load_state()

    def get_agent_state(self):
        return self.state.get("agents", {})
        
    def set_agent_state(self, area, agent_id, action_desc, obj):
        if "agents" not in self.state:
            self.state["agents"] = {}
        self.state["agents"][agent_id] = {
            "action": action_desc,
            "interaction_area": area,
            "interaction_object": obj
        }
        self.save_state()

    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    content = f.read()
                    if content:
                        self.state = json.loads(content)
                    return self.state
            except (json.JSONDecodeError, IOError):
                pass
        self.save_state()
        return self.state

    def save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=4)

    def set_time(self, time_string):
        self.state["time"] = time_string
        self.save_state()

    def reset_agents(self):
        default = {
            "Jimmy": {
                "action": "Jimmy is resting at home.",
                "interaction_area": "House_Jimmy",
                "interaction_object": "House_Jimmy"
            },
            "Samson": {
                "action": "Samson is resting at home.",
                "interaction_area": "House_Samson",
                "interaction_object": "House_Samson"
            }
        }
        self.state["agents"] = default
        self.save_state()
