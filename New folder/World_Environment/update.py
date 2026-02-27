# run the script after updating config.json

import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from World_Environment.environment_tree import EnvironmentTree
from World_Environment.area_state_manager import get_area_manager, AREAS_DIR

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"Config file {CONFIG_FILE} not found.")
        return None
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def process_node(tree, config_node, parent_node=None, valid_uuids=None):
    if valid_uuids is None:
        valid_uuids = set()

    name = config_node.get("name")
    node_type = config_node.get("type", "object")
    state = config_node.get("state", "empty")
    
    current_node = None
    
    if parent_node:
        for child in parent_node.children:
            if child.name == name:
                current_node = child
                break
    else:
        if tree.root and tree.root.name == name:
            current_node = tree.root

    if current_node:
        print(f"Updating existing node: {name}")
        updated = False
        
        if current_node.state != state:
            current_node.state = state
            updated = True
        
        if current_node.node_type != node_type:
            current_node.node_type = node_type
            updated = True

        if updated:
            tree.save_node(current_node)
    else:
        print(f"Creating new node: {name} ({node_type})")
        current_node = tree.add_node(
            name, 
            node_type, 
            parent=parent_node, 
            state=state
        )

    if current_node:
        valid_uuids.add(current_node.uuid)

    config_children = config_node.get("children", [])
    for child_config in config_children:
        process_node(tree, child_config, current_node, valid_uuids)

def update_tree():
    config = load_config()
    if not config:
        return

    tree = EnvironmentTree()
    tree.load()
    
    print("Updating Environment Tree from JSON...")
    
    valid_uuids = set()
    process_node(tree, config, valid_uuids=valid_uuids)
    
    all_uuids = set(tree.nodes.keys())
    to_remove = all_uuids - valid_uuids
    
    if to_remove:
        print(f"Removing {len(to_remove)} obsolete nodes...")
        for uid in to_remove:
            node = tree.nodes.get(uid)
            name = node.name if node else "Unknown"
            print(f" - Removing: {name} ({uid})")
            tree.delete_node(uid)

    print("Environment Tree Updated.")

def initialize_areas_json():
    tree = EnvironmentTree()
    tree.load()
    
    area_mapping = {}
    
    if tree.nodes:
        for node in tree.nodes.values():
            if node.node_type == "object" and node.parent:
                area_name = node.parent.name
                if area_name not in area_mapping:
                    area_mapping[area_name] = []
                area_mapping[area_name].append(node.name)
            elif node.node_type in ["room", "area", "house"]:
                if node.name not in area_mapping:
                    area_mapping[node.name] = []

    for area_name, obj_names in area_mapping.items():
        manager = get_area_manager(area_name)
        current_objects, agents_in_area = manager.get_area_state()
        
        for obj_name in obj_names:
            if obj_name not in current_objects:
                manager.set_area_state(obj_name, "empty", None)
        
        manager.save_state()
    
    print(f"[AreaStateManager] Synchronized {len(area_mapping)} area state files in {AREAS_DIR}")

if __name__ == "__main__":
    update_tree()
    initialize_areas_json()
