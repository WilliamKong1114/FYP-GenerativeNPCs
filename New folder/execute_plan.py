import sqlite3
import json
import time
import re
from World_Environment.environment_tree import EnvironmentTree
from unity_comm import UnityClient

def get__plan():
    conn = sqlite3.connect("plans.db")
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM plans ORDER BY created_on DESC LIMIT 1")
        row = cur.fetchone()
    except Exception as e:
        print(f"Error reading DB: {e}")
        return None
    finally:
        conn.close()

    if not row:
        return None

    plan_json_str = row[3]
    plan_data = json.loads(plan_json_str)
    return plan_data.get("description", "")

def parse_plan_steps(description):
    lines = description.split('\n')
    steps = []
    # Regex for "1) 7:00 am: Action text"
    # Matches: number, paren, space, time, colon, space, action
    pattern = re.compile(r'\d+\)\s+(\d+:\d+\s+[ap]m):\s+(.*)')
    
    for line in lines:
        line = line.strip()
        match = pattern.match(line)
        if match:
            time_str = match.group(1)
            action_text = match.group(2)
            steps.append((time_str, action_text))
    return steps

def execute_plan():
    #print("Loading Environment Tree...")
    tree = EnvironmentTree()
    tree.load()
    
    #print("Connecting to Unity...")
    client = UnityClient()
    
    description = get__plan()
    if not description:
        print("No plan found in database.")
        return

    #print("Parsing Plan...")
    steps = parse_plan_steps(description)
    print(f"Found {len(steps)} steps.")
    
    for time_str, action in steps:
        print(f"\nTime: {time_str}")
        print(f"Action: {action}")
        
        location_node = tree.find_suitable_location(action)
        
        target_name = None
        if location_node:
            target_name = tree.get_location(location_node)
            print(f"--> Identified Location: {location_node.name} (Unity: {target_name})")
        else:
            print("--> No specific location found in tree. Staying put or using default.")
        
        if target_name:
            #print(f"--> Sending Move Command to '{target_name}'...")
            try:
                client.move_to(target_name)
            except Exception as e:
                print(f"--> Error communicating with Unity: {e}")
        
        time.sleep(1) 

    print("\nPlan Execution Complete.")
    client.close()

if __name__ == "__main__":
    execute_plan()
