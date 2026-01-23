import sqlite3
import json
import uuid
import os
from typing import List, Optional, Dict, Any

# Get the directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "places.db")

class EnvironmentNode:
    def __init__(self, name: str, node_type: str, parent: Optional['EnvironmentNode'] = None, 
                 uuid_str: str = None, affordances: List[str] = None, game_object_name: str = None, status: int = 0):
        self.name = name
        self.node_type = node_type # "area", "subarea", "object"
        self.parent = parent
        self.children: List['EnvironmentNode'] = []
        self.uuid = uuid_str if uuid_str else str(uuid.uuid4())
        self.affordances = affordances if affordances else []
        self.game_object_name = game_object_name
        self.status = status
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
        self._init_db()
        self.root: Optional[EnvironmentNode] = None
        self.nodes: Dict[str, EnvironmentNode] = {} # uuid -> node

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        conn = self._get_conn()
        conn.execute("""
        CREATE TABLE IF NOT EXISTS environment_tree (
            uuid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            parent_uuid TEXT,
            affordances TEXT, -- JSON list of strings
            game_object_name TEXT,
            status INTEGER
        )""")
        conn.commit()
        conn.close()

    def load(self):
        conn = self._get_conn()
        cur = conn.execute("SELECT uuid, name, type, parent_uuid, affordances, game_object_name, status FROM environment_tree")
        rows = cur.fetchall()
        conn.close()

        self.nodes = {}
        temp_parent_map = {}

        # First pass: Create all nodes
        for r in rows:
            uid, name, ntype, pid, aff_text, gname, status = r
            affs = json.loads(aff_text) if aff_text else []
            node = EnvironmentNode(name, ntype, uuid_str=uid, affordances=affs, game_object_name=gname, status=status)
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
        conn = self._get_conn()
        aff_text = json.dumps(node.affordances)
        conn.execute("""
            INSERT OR REPLACE INTO environment_tree (uuid, name, type, parent_uuid, affordances, game_object_name, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (node.uuid, node.name, node.node_type, node.parent.uuid if node.parent else None, aff_text, node.game_object_name, node.status))
        conn.commit()
        conn.close()
        
    def add_node(self, name: str, node_type: str, parent: Optional[EnvironmentNode] = None, 
                 affordances: List[str] = None, game_object_name: str = None, status: int = 0) -> EnvironmentNode:
        node = EnvironmentNode(name, node_type, parent, affordances=affordances, game_object_name=game_object_name, status=status)
        if parent:
            parent.add_child(node)
        elif not self.root:
            self.root = node
        
        self.nodes[node.uuid] = node
        self.save_node(node)
        return node

    def find_suitable_location(self, action: str) -> Optional[EnvironmentNode]:
        if not self.root:
            self.load()
            if not self.root:
                return None
                
        matches = []
        
        queue = [self.root]
        while queue:
            current = queue.pop(0)
            for aff in current.affordances:
                if aff.lower() in action.lower():
                    matches.append(current)
                    break
            
            queue.extend(current.children)
        
        if not matches:
            return None
        
        # Filter for unoccupied nodes (status == 0)
        unoccupied = [m for m in matches if m.status == 0]
        
        # If we have unoccupied nodes, prefer them
        pool = unoccupied if unoccupied else matches
        
        objects = [m for m in pool if m.node_type == "object"]
        if objects:
            return objects[0]
        
        return pool[0]

    def get_location(self, node: EnvironmentNode) -> str:
        return node.game_object_name if node.game_object_name else node.name
