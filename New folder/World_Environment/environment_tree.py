import sqlite3
import threading
import uuid
import os
import json
from dotenv import load_dotenv
from typing import List, Optional, Dict
from Secure.llm_config import routing_llm as llm

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "Database", "places.db")

load_dotenv()

class EnvironmentNode:
    def __init__(self, name: str, node_type: str, parent: Optional['EnvironmentNode'] = None, 
                 uuid_str: str = None, game_object_name: str = None, state: str = "empty"):
        self.name = name
        self.node_type = node_type
        self.parent = parent
        self.children: List['EnvironmentNode'] = []
        self.uuid = uuid_str if uuid_str else str(uuid.uuid4())
        self.game_object_name = game_object_name
        self.state = state
    
    def add_child(self, child: 'EnvironmentNode'):
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
    def __init__(self, db_path: str = DB_PATH, max_depth: int = 3):
        self.db_path = db_path
        self.max_depth = max_depth
        self.lock = threading.RLock()
        self.root: Optional[EnvironmentNode] = None
        self.nodes: Dict[str, EnvironmentNode] = {}
        self.location_cache: Dict[str, List[EnvironmentNode]] = {}
        self.action_map = self.load_action_map()

    def load_action_map(self) -> Dict[str, List[str]]:
        config_path = os.path.join(BASE_DIR, "World_Environment", "action_config.json")
        mapping = {}
        with open(config_path, 'r') as f:
            data = json.load(f)
            # Programmatic Population: Flatten grouped verbs into lookup keys
            for entry in data:
                for verb in entry.get("verbs", []):
                    mapping[verb.lower()] = entry.get("targets", [])
        return mapping

    def get_conn(self):
        return sqlite3.connect(self.db_path)

    def load(self):
        with self.lock:
            conn = self.get_conn()
            cur = conn.execute("SELECT uuid, name, type, parent_uuid, game_object_name, state FROM environment_tree")
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
            conn.execute("""
                INSERT OR REPLACE INTO environment_tree (uuid, name, type, parent_uuid, game_object_name, state)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (node.uuid, node.name, node.node_type, node.parent.uuid if node.parent else None, node.game_object_name, node.state))
            conn.commit()
            conn.close()

    def delete_node(self, uuid: str):
        with self.lock:
            if uuid in self.nodes:
                node = self.nodes[uuid]
                if node.parent:
                    node.parent.children.remove(node)
                for child in node.children:
                    child.parent = None
                del self.nodes[uuid]

            conn = self.get_conn()
            conn.execute("DELETE FROM environment_tree WHERE uuid = ?", (uuid,))
            conn.commit()
            conn.close()
        
    def add_node(self, name: str, node_type: str, parent: Optional[EnvironmentNode] = None,  
                 game_object_name: str = None, state: str = "empty") -> EnvironmentNode:
        with self.lock:
            node = EnvironmentNode(name, node_type, parent, game_object_name=game_object_name, state=state)
            if parent:
                parent.add_child(node)
            elif not self.root:
                self.root = node
            
            self.nodes[node.uuid] = node
            self.save_node(node)
            return node
        
    def find_suitable_location(self, action: str, agent_data=None) -> List[EnvironmentNode]:
        if not self.root:
            self.load()

        action_lower = action.lower()
        agent_name = agent_data.get("agent_name")
        cache_key = f"{action_lower}"
        target = None

        target_tags = []
        for verb, tags in self.action_map.items():
            if verb in action_lower:
                target_tags = tags
                break
        
        if target_tags:
            special_types = {"bed", "house", "storage", "table", "hearth"}
            candidates = []

            if agent_name:
                search_patterns = [f"{t.capitalize()}_{agent_name}" for t in target_tags if t.lower() in special_types]
                if search_patterns:
                    candidates = [
                        n for n in self.nodes.values() 
                        if n.state == "empty" and any(pat in n.name for pat in search_patterns)
                    ]

            if not candidates:
                candidates = [
                    n for n in self.nodes.values() 
                    if n.state == "empty" and any(t.lower() in n.name.lower() for t in target_tags)
                ]

            if candidates:
                target = candidates[0]

        if not target:
            target = self.find_target_location(self.root, action)
            if target and target.state != "empty":
                target = None

        if not target:
            return []
        
        # Build path
        path = []
        current = target
        while current:
            path.append(current)
            current = current.parent
        path.reverse()
        self.location_cache[cache_key] = path
        return path
    
    def _build_candidate_list(self, node: EnvironmentNode, max_depth: int = 5) -> str:
        candidate_info = []
        
        def traverse(current: EnvironmentNode, depth: int = 0):
            if depth > max_depth:
                return
            if not current.children and current.state == "empty":
               candidate_info.append(current.get_path())
            for child in current.children:
                traverse(child, depth + 1)

        traverse(node)
        return "\n".join(f"- {path}" for path in candidate_info)

    def find_target_location(self, current_node: EnvironmentNode, action: str, agent_context: str) -> Optional[EnvironmentNode]:
        if not current_node.children:
            return current_node

        candidate_info = self._build_candidate_list(current_node)        
        prompt = f"""Action: {action}
                Context: {agent_context}
                Candidates: {candidate_info}
                Output format (IMPORTANT):
                - Prefer locations under the same root/area as the agent's current location in Context (e.g. same House/room/area).
                - Ensure the location is a logical fit for the action.  
                - Return ONE location path ONLY. Format: Root/Area/Subarea/Location (e.g. House/Room/Table).
                - The path MUST be an EXACT match from the Candidates list above (copy-paste the path before the colon).
                - Do NOT include explanations, descriptions, reasoning, extra text, state, type, or any other characters.
                - Do NOT add quotes, punctuation, parentheses, or modify the path.
                Examples of correct paths:
                    - For "plant seeds in the garden": "World/Garden/Land/Dirt"
                    - For "dump trash": "World/Dump/Table"
                    - For "cook in the kitchen": "World/Kitchen/Stove"                - Final output: A single line with ONLY the path.                
                """
        response = llm.invoke(prompt).content.strip()
        target = self._find_node_by_path(current_node, response) if response else self.root
        return target or current_node
            
    def _find_node_by_path(self, start_node: EnvironmentNode, target_path: str) -> Optional[EnvironmentNode]:
        if not start_node:
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
        
        leaf_name = segments[-1]
        for node in self.nodes.values():
            if node.name == leaf_name and not node.children:
                return node
        return None

    def get_location(self, node: EnvironmentNode) -> str:
        return node.game_object_name or node.name
