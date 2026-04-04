import sys
import os
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from World_Environment.environment_tree import EnvironmentTree

class TestFindLocation(unittest.TestCase):

    def setUp(self):
        self.tree = EnvironmentTree()
        self.tree.load()
        
    def test_find_basin_location(self):
        shutdown = False
        while not shutdown:
            task = input("Enter task (or 'quit' to stop): ")
            if task.lower() == "quit":
                shutdown = True
                break
            agent_data = {"agent_name": "Samson"}
            #print(f"\n[Test] Agent Task: '{task}'")
            path_nodes = self.tree.find_suitable_location(action=task, agent_context="House_Samson", agent_data=agent_data)
            
            if path_nodes:
                target_node = path_nodes[-1]
                location_name = target_node.game_object_name or target_node.name
                print(f"Output Location: \"{location_name}\"")
                
                self.assertIsNotNone(target_node, "Should return a target node")
                self.assertTrue(len(location_name) > 0, "Location name should not be empty")
            else:
                self.fail("No suitable location found in the actual environment tree.")

if __name__ == "__main__":
    unittest.main()
