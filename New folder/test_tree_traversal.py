from skills.environment_tree import EnvironmentTree

def test_search():
    tree = EnvironmentTree()
    tree.load()
    
    tasks = ["cook dinner", "go to sleep", "do some gardening", "work on project"]
    
    for task in tasks:
        node = tree.find_suitable_location(task)
        if node:
            print(f"Task: '{task}' -> Location: {node.name} (Type: {node.node_type}) -> Unity Object: {tree.get_unity_path(node)}")
        else:
            print(f"Task: '{task}' -> No suitable location found.")

if __name__ == "__main__":
    test_search()
