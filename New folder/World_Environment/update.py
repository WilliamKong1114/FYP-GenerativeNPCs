# run the script after updating environment_config.json

import json
import os
import sys

# Add the root directory to sys.path so we can import from World_Environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from World_Environment.environment_tree import EnvironmentTree

# Path relative to this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"Config file {CONFIG_FILE} not found.")
        return None
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def process_node(tree, config_node, parent_node=None):
    name = config_node.get("name")
    node_type = config_node.get("type", "object")
    affordances = config_node.get("affordances", [])
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
        
        if set(current_node.affordances) != set(affordances):
            current_node.affordances = affordances
            updated = True

        if current_node.state != state:
            current_node.state = state
            updated = True

        if updated:
            tree.save_node(current_node)
    else:
        print(f"Creating new node: {name}")
        current_node = tree.add_node(
            name, 
            node_type, 
            parent=parent_node, 
            affordances=affordances, 
            state=state
        )

    config_children = config_node.get("children", [])
    for child_config in config_children:
        process_node(tree, child_config, current_node)

def update_tree():
    config = load_config()
    if not config:
        return

    tree = EnvironmentTree()
    tree.load()
    
    print("Updating Environment Tree from JSON...")
    process_node(tree, config)
    print("Environment Tree Updated.")

if __name__ == "__main__":
    update_tree()
