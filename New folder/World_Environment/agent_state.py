import json
import os
import threading

class AgentStateManager:
    def __init__(self, file_path="agent_state.json"):
        self.state_file = file_path
        self.lock = threading.RLock()
        self.state = {}

    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    content = f.read()
                    if not content:
                        return getattr(self, "state", {})
                    return json.loads(content)
            except (json.JSONDecodeError, IOError):
                return getattr(self, "state", {})
        else:
            raise FileNotFoundError(f"{self.state_file} not found.")

    def save_state(self):
        with self.lock:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=4)

    def refresh_state(self):
        self.state = self.load_state()

    def set_time(self, time_string):
        with self.lock:
            self.state["time"] = time_string
            self.save_state()

    def update_agent(self, agent_name, action_desc, area, obj):
        with self.lock:
            prev_agent_data = self.state["agents"].get(agent_name, {})
            prev_object = prev_agent_data.get("interaction_object")
            prev_area = prev_agent_data.get("interaction_area")
            
            if prev_object and prev_object != "unknown" and prev_area and prev_area != "unknown":
                if prev_object != obj or prev_area != area:
                    self.update_object(prev_area, prev_object, "empty", save_now=False)

            if obj != "unknown":
                self.update_object(area, obj, "occupied", save_now=False)
            
            self.state["agents"][agent_name] = {
                "action": action_desc,
                "interaction_area": area,
                "interaction_object": obj
            }
            self.save_state()

    def update_object(self, area, obj, state, save_now=True):
        with self.lock:
            if "objects" not in self.state:
                self.state["objects"] = {}
            
            if area not in self.state["objects"]:
                 self.state["objects"][area] = {}

            self.state["objects"][area][obj] = {"state": state}
            if save_now:
                self.save_state()

    def reset_agents(self):
        with self.lock:
            if "objects" in self.state:
                for area in self.state["objects"]:
                    for obj in self.state["objects"][area]:
                        if self.state["objects"][area][obj].get("state") == "occupied":
                            self.state["objects"][area][obj]["state"] = "empty"

            default = {
                "Jimmy": {
                    "action": "Jimmy is resting at home. @ World/House_Jimmy/House_Jimmy",
                    "interaction_area": "House_Jimmy",
                    "interaction_object": "House_Jimmy"
                },
                "Samson": {
                    "action": "Samson is resting at home. @ World/House_Samson/House_Samson",
                    "interaction_area": "House_Samson",
                    "interaction_object": "House_Samson"
                }
            }

            for agent_name, initial_data in default.items():
                self.state["agents"][agent_name] = initial_data
                area = initial_data["interaction_area"]
                obj = initial_data["interaction_object"]
                if area not in self.state["objects"]:
                    self.state["objects"][area] = {}
                self.state["objects"][area][obj] = {"state": "empty"}

            self.save_state()
