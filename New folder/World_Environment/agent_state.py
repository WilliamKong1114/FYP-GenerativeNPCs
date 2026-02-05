import json
import os

class AgentStateManager:
    def __init__(self, state_file="agent_state.json"):
        self.state_file = state_file
        self.state = self.load_state()

    def load_state(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                return json.load(f)
        return {"agents": {}, "objects": {}, "time": "Day 0, 06:00"}

    def set_time(self, time_string):
        self.state["time"] = time_string
        self.save_state()

    def save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=4)

    def update_agent(self, agent_name, action_description):
        # Retrieve previous state to reset previous object if necessary
        prev_agent_data = self.state["agents"].get(agent_name, {})
        prev_object = prev_agent_data.get("interaction_object")
        prev_area = prev_agent_data.get("interaction_area")
        
        location = "unknown"
        interact_object = "unknown"
        area_of_object = "unknown"
        
        if " @ " in action_description:
            action_text, path_text = action_description.split(" @ ", 1)
            path_parts = [p.strip() for p in path_text.split(":")]

            location = path_parts[1] if len(path_parts) > 1 else path_parts[0]
            if len(path_parts) > 2:
                interact_object = path_parts[-1]
                area_of_object = path_parts[-2]
            
            if prev_object and prev_object != "unknown" and prev_area and prev_area != "unknown":
                 if prev_object != interact_object or prev_area != area_of_object:
                     self.update_object(prev_area, prev_object, "empty")

            if interact_object != "unknown":
                self.update_object(area_of_object, interact_object, "occupied")
        else:
            action_text = action_description
            if prev_object and prev_object != "unknown" and prev_area and prev_area != "unknown":
                 self.update_object(prev_area, prev_object, "empty")
        
        self.state["agents"][agent_name] = {
            "location": location,
            "action": action_description,
            "interaction_object": interact_object,
            "interaction_area": area_of_object
        }
        self.save_state()

    def update_object(self, area, object_name, state):
        if "objects" not in self.state:
            self.state["objects"] = {}
        
        if area not in self.state["objects"]:
             self.state["objects"][area] = {}

        self.state["objects"][area][object_name] = {"state": state}
        self.save_state()