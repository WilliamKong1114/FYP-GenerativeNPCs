import json
import os
import random
import re
import sqlite3
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Dict, List, Optional

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from Secure.llm_config import routing_llm
from World_Environment.agent_state_manager import AgentStateManager

DB_PATH = os.path.join(BASE_DIR, "Database", "places.db")

load_dotenv()

class EnvironmentNode:
    def __init__(self, name: str, node_type: str, parent: Optional["EnvironmentNode"] = None, uuid_str: str = None, game_object_name: str = None, state: str = "empty"):
        self.name = name
        self.node_type = node_type
        self.parent = parent
        self.children: List["EnvironmentNode"] = []
        self.uuid = uuid_str if uuid_str else str(uuid.uuid4())
        self.game_object_name = game_object_name
        self.state = state

    def add_child(self, child: "EnvironmentNode"):
        self.children.append(child)
        child.parent = self

    def get_path(self) -> str:
        path = []
        current = self
        while current:
            path.append(current.name)
            current = current.parent
        return "/".join(reversed(path))

    def __repr__(self):
        return f"<EnvironmentNode {self.name} ({self.node_type})>"


class EnvironmentTree:
    def __init__(self, db_path: str = DB_PATH, max_depth: int = 5):
        self.db_path = db_path
        self.max_depth = max_depth
        self.lock = threading.RLock()
        self.root: Optional[EnvironmentNode] = None
        self.nodes: Dict[str, EnvironmentNode] = {}
        self.location_cache: Dict[str, List[EnvironmentNode]] = {}
        self.action_map = self.load_action_map()
        self._routing_timeout = 10.0
        self._routing_executor = ThreadPoolExecutor(
            max_workers=5,
            thread_name_prefix="LocationRouting",
        )

    def load_action_map(self) -> Dict[str, List[str]]:
        config_path = os.path.join(BASE_DIR, "World_Environment", "action_config.json")
        mapping = {}
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Programmatic population: flatten grouped verbs into lookup keys.
            for entry in data:
                for verb in entry.get("verbs", []):
                    mapping[verb.lower()] = entry.get("targets", [])
        return mapping

    def get_conn(self):
        return sqlite3.connect(self.db_path)

    def load(self):
        with self.lock:
            conn = self.get_conn()
            cur = conn.execute(
                "SELECT uuid, name, type, parent_uuid, game_object_name, state FROM environment_tree"
            )
            rows = cur.fetchall()
            conn.close()

            self.nodes = {}
            parent_map = {}

            for r in rows:
                uid, name, ntype, pid, gname, state = r
                node = EnvironmentNode(name, ntype, uuid_str=uid, game_object_name=gname, state=state)
                self.nodes[uid] = node
                if pid:
                    parent_map[uid] = pid

            for uid, pid in parent_map.items():
                if pid in self.nodes:
                    parent = self.nodes[pid]
                    parent.add_child(self.nodes[uid])

            potential_roots = [n for n in self.nodes.values() if n.parent is None]
            self.root = potential_roots[0] if potential_roots else None

    def save_node(self, node: EnvironmentNode):
        with self.lock:
            conn = self.get_conn()
            conn.execute(
                """
                INSERT OR REPLACE INTO environment_tree (uuid, name, type, parent_uuid, game_object_name, state)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (node.uuid, node.name, node.node_type, node.parent.uuid if node.parent else None, node.game_object_name, node.state),
            )
            conn.commit()
            conn.close()

    def delete_node(self, uuid_str: str):
        with self.lock:
            if uuid_str in self.nodes:
                node = self.nodes[uuid_str]
                if node.parent:
                    node.parent.children.remove(node)
                for child in node.children:
                    child.parent = None
                del self.nodes[uuid_str]

            conn = self.get_conn()
            conn.execute("DELETE FROM environment_tree WHERE uuid = ?", (uuid_str,))
            conn.commit()
            conn.close()

    def add_node(self, name: str, node_type: str, parent: Optional[EnvironmentNode] = None, game_object_name: str = None, state: str = "empty") -> EnvironmentNode:
        with self.lock:
            node = EnvironmentNode(name, node_type, parent, game_object_name=game_object_name, state=state)
            if parent:
                parent.add_child(node)
            elif not self.root:
                self.root = node

            self.nodes[node.uuid] = node
            self.save_node(node)
            return node

    def find_suitable_location(self, action: str, agent_id: str) -> List[EnvironmentNode]:
        if not self.root:
            self.load()

        agent_name = agent_id
        target = None
        candidates: List[EnvironmentNode] = []

        type_1 = {"Bed", "House", "Hearth", "Table"}
        type_2 = {"Church", "River", "Well"}
        type_3 = {
            ("Wilton", "Bakery"): ["Table_Bakery", "Storage_Bakery"],
            ("Lona", "Bakery"): ["Table_Bakery", "Storage_Bakery"],
            ("Heath", "Bakery"): ["Table_Bakery", "Storage_Bakery"],
            ("Warwicke", "Blacksmith"): ["Table_Blacksmith", "Storage_Blacksmith"],
            ("Lona", "Bed_Wilton"): ["Bed_Wilton"],
            ("Lona", "House_Wilton"): ["House_Wilton"],
            ("Lona", "Hearth_Wilton"): ["Hearth_Wilton"],
            ("Heath", "Bed_Wilton"): ["Bed_Wilton"],
            ("Heath", "House_Wilton"): ["House_Wilton"],
            ("Heath", "Hearth_Wilton"): ["Hearth_Wilton"],
        }

        for n in type_1:
            if re.search(re.escape(n), action, re.IGNORECASE):
                target_name = f"{n}_{agent_name}"
                with self.lock:
                    candidates = [
                        node
                        for node in self.nodes.values()
                        if node.name == target_name and node.state == "empty"
                    ]
                if candidates:
                    target = candidates[0]
                    break

        if not target:
            for n in type_2:
                if re.search(re.escape(n), action, re.IGNORECASE):
                    with self.lock:
                        candidates = [
                            node
                            for node in self.nodes.values()
                            if node.name == n and node.state == "empty"
                        ]
                    if candidates:
                        target = candidates[0]
                        break

        if not target:
            for (spec_agent, keyword), loc_list in type_3.items():
                if agent_name == spec_agent and re.search(re.escape(keyword), action, re.IGNORECASE):
                    chosen_name = random.choice(loc_list)
                    with self.lock:
                        candidates = [
                            node
                            for node in self.nodes.values()
                            if node.name == chosen_name and node.state == "empty"
                        ]
                    if candidates:
                        target = candidates[0]
                        break

        if not target and self.root:
            target = self.find_target_location(self.root, agent_name, action)
            if target and target.state != "empty":
                target = None

        path: List[EnvironmentNode] = []
        current = target
        while current:
            path.append(current)
            current = current.parent
        path.reverse()

        with self.lock:
            self.location_cache[action] = path
        return path

    def _invoke_routing_llm(self, prompt: str) -> Optional[str]:
        try:
            response = routing_llm.invoke(prompt).content.strip()
            return response if isinstance(response, str) else None
        except Exception as exc:
            print(f"[LOCATION] Routing invoke failed: {exc}")
            return None

    def request_routing_path(self, action: str, agent_name: str, candidate_info: str) -> Optional[str]:
        agent_state = AgentStateManager().get_agent_state().get(agent_name, {})
        persona = agent_state.get("persona", "Unknown")
        prompt = (
            f"Action: {action}\n"
            f"Context: You are {agent_name} and you are trying to find the best location within the candidates list that fit to perform the action.\n"
            f"Persona of the agent: {persona}\n"
            f"Available locations: \n{candidate_info}.\n"
            "Instructions:\n"
            "- There are two types of path format: 1. Root/Area/Location (e.g. House/Room/Table) for normal nodes, 2. Root/Area/[Object1, Object2] for multiple leaf nodes under the same parent (e.g. House/Room/[Table, Bed]).\n"
            "- For format 1, return the path as is.\n"
            "- For format 2, return the path with choosing ONE specific object with the list that best fits the action (e.g. House/Room/Table).\n"
            "- ShopArea and WaitZone are for customers to buy items or wait for their turn, while Table and Storage are for work purposes for workers or shop owners to dealing with business.\n"
            "- Consider the agent's persona to identify the relationship between the agent and the location (e.g. if the agent is a shop owner, they are more likely to be at the table or storage).\n"
            "Restrictions:\n"
            "- Only select a location that appears exactly as written in the Available locations list. Do not create, infer, or modify any location names.\n"
            "- Prefer locations under the same root/area as the agent's current location if it suits the action.\n"
            "- Do NOT include explanations, descriptions, reasoning, extra text, state, type, or any other characters.\n"
            "- Do NOT add quotes, punctuation or parentheses.\n"
            "Examples of correct paths:\n"
            "- World/House_Wilton/Hearth_Wilton\n"
            "- World/Bakery/ShopArea_Bakery\n"
            "- World/House_Wilton/Hearth_Wilton\n"
        )

        future = self._routing_executor.submit(self._invoke_routing_llm, prompt)
        try:
            return future.result(timeout=self._routing_timeout)
        except TimeoutError:
            print(f"[LOCATION] Routing timeout for '{action}'")
            future.cancel()
            return None
        except Exception as exc:
            print(f"[LOCATION] Routing failed for '{action}': {exc}")
            return None

    def build_candidate_list(self, node: EnvironmentNode, max_depth: int = 5) -> str:
        from collections import defaultdict

        grouped_candidates = defaultdict(list)

        def traverse(current: EnvironmentNode, depth: int = 0):
            if depth > max_depth:
                return

            if not current.children and current.state == "empty":
                if current.parent:
                    parent_path = current.parent.get_path()
                    grouped_candidates[parent_path].append(current.name)
                else:
                    grouped_candidates["/"].append(current.name)
                return

            for child in current.children:
                traverse(child, depth + 1)

        with self.lock:
            traverse(node)

            formatted_output = []
            for path, objects in grouped_candidates.items():
                if len(objects) > 1:
                    formatted_output.append(f"- {path}/[{', '.join(objects)}]")
                elif path == "/":
                    formatted_output.append(f"- {objects[0]}")
                else:
                    formatted_output.append(f"- {path}/{objects[0]}")

        return "\n".join(formatted_output)

    def build_area_list(self, node: EnvironmentNode, max_depth: int = 5) -> str:
        areas = set()

        def traverse(current: EnvironmentNode, depth: int = 0):
            if depth > max_depth:
                return

            if not current.children:
                if current.parent:
                    areas.add(current.parent.name)
                else:
                    areas.add("World")
                return

            for child in current.children:
                traverse(child, depth + 1)

        with self.lock:
            traverse(node)
            formatted_output = [f"{area}" for area in sorted(list(areas))]

        return ", ".join(formatted_output)

    def find_target_location(self, current_node: EnvironmentNode, agent_name: str, action: str) -> Optional[EnvironmentNode]:
        if not current_node.children:
            return current_node

        candidate_info = self.build_candidate_list(current_node)
        response = self.request_routing_path(action, agent_name, candidate_info)
        fallback = f"World/House_{agent_name}/House_{agent_name}"
        target = self.find_node_by_path(current_node, response) if response else self.find_node_by_path(current_node, fallback)
        return target or current_node

    def find_node_by_path(self, start_node: EnvironmentNode, target_path: str) -> Optional[EnvironmentNode]:
        if not start_node or not target_path:
            return None

        segments = target_path.strip().split("/")
        current = start_node

        for s in segments:
            found_child = next((child for child in current.children if child.name == s), None)
            if found_child:
                current = found_child
            else:
                break
        else:
            return current

        from collections import deque
        leaf_name = segments[-1]
        queue = deque([self.root if self.root else start_node])
        
        while queue:
            node = queue.popleft()
            if node.name == leaf_name and not node.children:
                return node
            queue.extend(node.children)
            
        return None

    def get_location(self, node: EnvironmentNode) -> str:
        return node.game_object_name or node.name


def main():
    agents_state = AgentStateManager().get_agent_state()
    agents_config = [
        {
            "id": name,
            "persona": data["persona"],
            "home_node": data["home_node"],
            "home_area": data["home_area"],
        }
        for name, data in agents_state.items()
    ]

    agent_executions = {
        config["id"]: {
            "persona": config["persona"],
            "steps": [],
            "emojis": [],
            "current_step": 0,
            "is_busy_until": 0,
            "is_chatting": False,
            "is_reflecting": False,
            "active_task": None,
            "current_target": config["home_node"],
            "current_area": config["home_area"],
            "prev_target": None,
            "prev_area": None,
        }
        for config in agents_config
    }

    _ = agent_executions

    tree = EnvironmentTree()
    tree.load()
    path_nodes = tree.find_suitable_location(
        "Woke up at House_Wilton, checked on Heath, and lit the hearth to start breakfast preparations in the kitchen.",
        agent_id="Wilton",
    )
    if not path_nodes:
        print("No target found")
        return

    target_node = path_nodes[-1]
    target_name = tree.get_location(target_node)
    print(target_name)

if __name__ == "__main__":
    main()
