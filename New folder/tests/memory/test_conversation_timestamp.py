import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Create a mock for execute_plan BEFORE importing conversation_manager 
# (although conversation_manager imports it lazily, it's safer)
mock_execute_plan = MagicMock()
sys.modules['execute_plan'] = mock_execute_plan

# Now import the class under test
from conversation_manager import ConversationManager

class TestConversationTimestamp(unittest.TestCase):

    @patch('conversation_manager.AgentMemoryManager')
    @patch('conversation_manager.manage_data')
    @patch('conversation_manager.dialogue_llm')
    def test_summary_includes_timestamp(self, mock_llm, mock_manage_data, mock_memory_manager_class):
        # Setup mocks
        mock_clock = MagicMock()
        mock_clock.get_time_string.return_value = "Day 5, 12:30"
        
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.content = "This is a summary of the chat."
        mock_llm.invoke.return_value = mock_response

        # Mock Memory Manager instance
        mock_memory_instance = mock_memory_manager_class.return_value
        
        # Initialize ConversationManager with the mock clock
        conv_mgr = ConversationManager(clock=mock_clock)
        conv_mgr.llm = mock_llm

        # Call the method
        user_id = "AgentA"
        raw_log = "Hello world"
        
        # We need to make sure execute_plan is mocked when the function runs
        with patch.dict(sys.modules, {'execute_plan': mock_execute_plan}):
            summary = conv_mgr.summarize_conversation_and_store(user_id, raw_log=raw_log)

        # Verification
        expected_time_str = "[Day 5, 12:30]"
        self.assertTrue(summary.startswith(expected_time_str), f"Summary '{summary}' should start with '{expected_time_str}'")
        self.assertIn("This is a summary of the chat.", summary)
        
        # Check if manage_data.add_memories was called with the timestamped summary
        mock_manage_data.add_memories.assert_called_with([summary], user_id=user_id)
        
        # Check if memory_manager.save_summary was called with the timestamped summary
        mock_memory_instance.save_summary.assert_called_with(user_id, summary, log_id=None)

        print(f"\nTest passed! Summary generated: {summary}")

if __name__ == '__main__':
    unittest.main()
