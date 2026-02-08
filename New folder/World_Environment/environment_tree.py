import sqlite3
import uuid
import os
import vertexai
from dotenv import load_dotenv
from typing import List, Optional, Dict
from langchain_google_vertexai import ChatVertexAI

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "places.db")

load_dotenv()
vertexai.init(project="finalyearproject-473307", location="us-central1")
llm = ChatVertexAI(model="gemini-2.5-flash", temperature=0.0)

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
        if self.parent:
            return f"{self.parent.get_path()}/{self.name}"
        return self.name
    
    def __repr__(self):
        return f"<EnvironmentNode {self.name} ({self.node_type})>"

class EnvironmentTree:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_db()
        self.root: Optional[EnvironmentNode] = None
        self.nodes: Dict[str, EnvironmentNode] = {}
        self.location_cache: Dict[str, List[EnvironmentNode]] = {}

    def get_conn(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        conn = self.get_conn()
        conn.execute("""
        CREATE TABLE IF NOT EXISTS environment_tree (
            uuid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            parent_uuid TEXT,
            game_object_name TEXT,
            state TEXT
        )""")
        conn.commit()
        conn.close()

    def load(self):
        conn = self.get_conn()
        cur = conn.execute("SELECT uuid, name, type, parent_uuid, game_object_name, state FROM environment_tree")
        rows = cur.fetchall()
        conn.close()

        self.nodes = {}
        temp_parent_map = {}

        # First pass: Create all nodes
        for r in rows:
            uid, name, ntype, pid, gname, state = r
            node = EnvironmentNode(name, ntype, uuid_str=uid, game_object_name=gname, state=state)
            self.nodes[uid] = node
            if pid:
                temp_parent_map[uid] = pid
        
        # Second pass: Link parents and children
        for uid, pid in temp_parent_map.items():
            if pid in self.nodes:
                parent = self.nodes[pid]
                child = self.nodes[uid]
                parent.add_child(child)
        
        potential_roots = [n for n in self.nodes.values() if n.parent is None]
        if potential_roots:
            self.root = potential_roots[0] 
        else:
            self.root = None

    def save_node(self, node: EnvironmentNode):
        conn = self.get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO environment_tree (uuid, name, type, parent_uuid, game_object_name, state)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (node.uuid, node.name, node.node_type, node.parent.uuid if node.parent else None, node.game_object_name, node.state))
        conn.commit()
        conn.close()

    def delete_node(self, uuid: str):
        if uuid in self.nodes:
            del self.nodes[uuid]
        
        conn = self.get_conn()
        conn.execute("DELETE FROM environment_tree WHERE uuid = ?", (uuid,))
        conn.commit()
        conn.close()
        
    def add_node(self, name: str, node_type: str, parent: Optional[EnvironmentNode] = None,  
                 game_object_name: str = None, state: str = "empty") -> EnvironmentNode:
        node = EnvironmentNode(name, node_type, parent, game_object_name=game_object_name, state=state)
        if parent:
            parent.add_child(node)
        elif not self.root:
            self.root = node
        
        self.nodes[node.uuid] = node
        self.save_node(node)
        return node

    def find_suitable_location(self, action: str, agent_context: str = "") -> List[EnvironmentNode]:
        if not self.root:
            self.load()
            if not self.root:
                return []

        # 1. Simple cache check
        cache_key = f"{action.lower()}|{agent_context}"
        if cache_key in self.location_cache:
            return self.location_cache[cache_key]

        # 2. Fast string match before LLM
        action_lower = action.lower()
        sorted_nodes = sorted(self.nodes.values(), key=lambda x: len(x.name), reverse=True)
        for node in sorted_nodes:
            if node.name.lower() in action_lower:
                if node.name.lower() == "world":
                    continue
                path = []
                curr = node
                while curr:
                    path.insert(0, curr)
                    curr = curr.parent
                self.location_cache[cache_key] = path
                return path

        # 3. Fallback to LLM for complex reasoning
        target_node = self._recursive_find_target(self.root, action, agent_context)
        if target_node:
            if target_node.name.lower() == "world" and target_node.children:
                target_node = target_node.children[0]

            path = []
            curr = target_node
            while curr:
                path.insert(0, curr)
                curr = curr.parent
            self.location_cache[cache_key] = path
            return path

        # 4. Final Fallback (ensures no 'World' target)
        res = self._fallback_find_suitable_location(action)
        if res and res[-1].name.lower() == "world" and len(res) == 1 and res[0].children:
             child = res[0].children[0]
             res = [res[0], child]
             
        self.location_cache[cache_key] = res
        return res

    def _recursive_find_target(self, current_node: EnvironmentNode, action: str, agent_context: str) -> Optional[EnvironmentNode]:
        if not current_node.children:
            return current_node

        options = [child.name for child in current_node.children]
        options_str = ", ".join(options)
        
        prompt = f"""
            {agent_context}
            Current Area: {current_node.name}
            Sub-areas: {options_str}
            Activity: {action}

            Which area should the agent go to? Choose one from the Sub-areas. 
            If the current area '{current_node.name}' is the most suitable and specific enough, or if none of the sub-areas are suitable, reply with '{current_node.name}'.
            Output just the name of the area.
            """
        try:
            print(f"Thinking about location at {current_node.name}...")
            response = llm.invoke(prompt).content.strip()
            response_clean = response.strip(".'\"")
            
            if response_clean.lower() == current_node.name.lower():
                return current_node
            
            for child in current_node.children:
                if child.name.lower() == response_clean.lower() or child.name.lower() in response_clean.lower():
                    return self._recursive_find_target(child, action, agent_context)
            
            return current_node
            
        except Exception as e:
            print(f"Error in LLM location search: {e}")
            return None

    def _fallback_find_suitable_location(self, action: str) -> List[EnvironmentNode]:
        if not self.root:
            return []
            
        matches = [] 
        action_lower = action.lower()
        
        queue = [self.root]
        while queue:
            current = queue.pop(0)
            if current.name.lower() in action_lower:
                path = []
                curr = current
                while curr:
                    path.insert(0, curr)
                    curr = curr.parent
                return path
            queue.extend(current.children)
        
        return [self.root]

    def get_location(self, node: EnvironmentNode) -> str:
        return node.game_object_name if node.game_object_name else node.name
