import json
import os

class AgentStateManager:
    def __init__(self, state_file=None):
        if state_file is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.state_file = os.path.join(base_dir, "agent_state.json")
        else:
            self.state_file = state_file
        self.state = self.load_state()

    def load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[ERROR] Loading state: {e}")
        return {"agents": {}, "objects": {}, "time": "Day 0, 06:00"}

    def refresh_state(self):
        """Force reload state from disk to ensure main thread sees thread updates"""
        self.state = self.load_state()

    def set_time(self, time_string):
        self.state["time"] = time_string
        self.save_state()

    def save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=4)

    def update_agent(self, agent_name, action_description, area="unknown", interaction_object="unknown"):
        prev_agent_data = self.state["agents"].get(agent_name, {})
        prev_object = prev_agent_data.get("interaction_object")
        prev_area = prev_agent_data.get("interaction_area")
        
        # Clean up old object state if agent is leaving it
        if prev_object and prev_object != "unknown" and prev_area and prev_area != "unknown":
            if prev_object != interaction_object or prev_area != area:
                self.update_object(prev_area, prev_object, "empty")

        # Update new object state if agent is entering one
        if interaction_object != "unknown":
            self.update_object(area, interaction_object, "occupied")
        
        self.state["agents"][agent_name] = {
            "action": action_description,
            "interaction_area": area,
            "interaction_object": interaction_object
        }
        self.save_state()

    def update_object(self, area, object_name, state):
        if "objects" not in self.state:
            self.state["objects"] = {}
        
        if area not in self.state["objects"]:
             self.state["objects"][area] = {}

        self.state["objects"][area][object_name] = {"state": state}
        self.save_state()