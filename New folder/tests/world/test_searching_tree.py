import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add the project root to sys.path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from World_Environment.environment_tree import EnvironmentTree, EnvironmentNode

class TestEnvironmentTree(unittest.TestCase):
    def setUp(self):
        # Create a mock tree for testing
        self.tree = EnvironmentTree(db_path=":memory:")  # In-memory DB for tests
        # Manually build a small tree to avoid DB dependencies
        self.root = EnvironmentNode("World", "area")
        self.tree.root = self.root
        self.tree.nodes[self.root.uuid] = self.root

        # Add some nodes
        house = EnvironmentNode("House_Samson", "area", parent=self.root)
        self.root.add_child(house)
        self.tree.nodes[house.uuid] = house

        room = EnvironmentNode("Room", "area", parent=house)
        house.add_child(room)
        self.tree.nodes[room.uuid] = room

        table = EnvironmentNode("Table", "object", parent=room, state="empty")
        room.add_child(table)
        self.tree.nodes[table.uuid] = table

        dirt = EnvironmentNode("Dirt (1)", "object", parent=self.root, state="empty")
        self.root.add_child(dirt)
        self.tree.nodes[dirt.uuid] = dirt

    @patch('World_Environment.environment_tree.llm')
    def test_find_target_location_valid_path(self, mock_llm):
        # Mock LLM to return a valid path
        mock_llm.invoke.return_value = MagicMock(content="World/House_Samson/Room/Table")
        result = self.tree.find_target_location(self.root, "sit", "Agent in House_Samson")
        self.assertEqual(result.name, "Table")

    @patch('World_Environment.environment_tree.llm')
    def test_find_target_location_non_existent_path(self, mock_llm):
        # Mock LLM to return non-existent path (fallback to first empty node)
        mock_llm.invoke.return_value = MagicMock(content="World/House_Samson/Door_Samson")
        result = self.tree.find_target_location(self.root, "open", "Agent in House_Samson")
        # Assuming fallback picks Dirt (1) as first empty
        self.assertEqual(result.name, "Dirt (1)")

    @patch('World_Environment.environment_tree.llm')
    def test_find_target_location_incomplete_path(self, mock_llm):
        # Mock LLM to return incomplete path (should find via global search)
        mock_llm.invoke.return_value = MagicMock(content="Table")
        result = self.tree.find_target_location(self.root, "place", "Agent in Room")
        self.assertEqual(result.name, "Table")

    @patch('World_Environment.environment_tree.llm')
    def test_find_target_location_no_candidates(self, mock_llm):
        # No empty nodes, should return root
        for node in self.tree.nodes.values():
            if node.state == "empty":
                node.state = "occupied"
        mock_llm.invoke.return_value = MagicMock(content="Invalid")
        result = self.tree.find_target_location(self.root, "act", "")
        self.assertEqual(result, self.root)

    def test_build_candidate_list(self):
        candidates = self.tree._build_candidate_list(self.root)
        expected = "- World/House_Samson/Room/Table\n- World/Dirt (1)"
        self.assertEqual(candidates, expected)

    def test_find_node_by_path_exact_match(self):
        path = "World/House_Samson/Room/Table"
        result = self.tree._find_node_by_path(self.root, path)
        self.assertEqual(result.name, "Table")

    def test_find_node_by_path_partial_match(self):
        path = "Table"  # Incomplete, should find globally
        result = self.tree._find_node_by_path(self.root, path)
        self.assertEqual(result.name, "Table")

    def test_find_node_by_path_no_match(self):
        path = "NonExistent"
        result = self.tree._find_node_by_path(self.root, path)
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()