import pytest
import sys
from unittest.mock import patch, MagicMock

import execute_plan
import conversation_manager
from World_Environment.agent_state import AgentStateManager

def test_immediate_conversation():
    print("--- Starting Immediate Conversation Test ---")
    
    # Use existing reference to ConversationManager after mocking
    from conversation_manager import ConversationManager
    conv_manager = ConversationManager()
    agent1 = {
        "id": "Samson",
        "persona": "A young, energetic villager who loves woodworking and helping others.",
        "state": {
            "location": "Farm",
            "interaction_area": "Farm",
            "action": "Tilling soil"
        }
    }
    
    agent2 = {
        "id": "Jimmy",
        "persona": "A calm, observant older villager with decades of wisdom.",
        "state": {
            "location": "Farm",
            "interaction_area": "Farm",
            "action": "Resting"
        }
    }

    conversation_manager.PROBABILITY_TO_TALK = 1.0
    participants = [agent1, agent2]
    should_talk = conv_manager.start_conversation(participants)
    
    assert should_talk is True, "Conversation should have been triggered"

    context = f"{agent1['id']} and {agent2['id']} are both in the {agent1['state']['interaction_area']}."
    dialogue_gen = conv_manager.generate_dialogue(participants, context)
    
    assert dialogue_gen is not None, "Dialogue generation should not return None"
    
    dialogue_turns = list(dialogue_gen)
    print("\n--- Generated Dialogue ---")
    for turn in dialogue_turns:
        print(f"[{turn['speaker']}]: {turn['text']}")
        
    assert len(dialogue_turns) > 0, "Dialogue generation should return at least one turn"

def test_agent_state_initialization():
    state_manager = AgentStateManager()
    assert state_manager.state is not None
    assert "agents" in state_manager.state
    assert "objects" in state_manager.state

def test_parse_plan():
    description = "1) 7:00 am: Tilling soil\n2) 8:30 am: Watering plants\nNoise line"
    steps = execute_plan.parse_plan(description)
    assert len(steps) == 2
    assert steps[0] == ("7:00 am", "Tilling soil")
    assert steps[1] == ("8:30 am", "Watering plants")

@patch("execute_plan.llm")
def test_generate_new_skill(mock_llm):
    mock_response = MagicMock()
    mock_response.content = "```python\nresult = 5.0\n```"
    mock_llm.invoke.return_value = mock_response
    
    code = execute_plan.generate_new_skill("test action")
    assert "result = 5.0" in code
    assert "```python" not in code

def test_get_cached_memory_hit():
    execute_plan.memory_cache.clear()
    user_id = "test_user"
    query = "hello"
    
    import hashlib
    key = f"{user_id}:{hashlib.sha256(query.encode('utf-8')).hexdigest()}"
    
    # Pre-fill cache
    execute_plan.memory_cache[key] = "Cached Memory"
    
    # Test cache hit (should not call collection)
    context = execute_plan.get_cached_memory(query, user_id)
    assert context == "Cached Memory"

@patch("execute_plan.query_skill")
def test_resolve_and_execute_skill_fallback(mock_query):
    mock_query.return_value = {"ids": [[]]}
    duration = execute_plan.resolve_and_execute_skill("Unknown", "Target", None)
    assert duration == 3.0

# --- Complex Process Tests ---

@patch("conversation_manager.AgentMemoryManager")
@patch("conversation_manager.manage_data")
@patch("execute_plan.memory_cache")
def test_summarize_conversation_and_store(mock_cache, mock_manage_data, mock_memory_manager):
    from conversation_manager import ConversationManager
    conv_manager = ConversationManager()
    
    # Mock the LLM response
    conv_manager.llm.invoke.return_value = MagicMock(content="Samson talked about fishing.")
    
    log = "Samson: I like fishing. Jimmy: Me too."
    summary = conv_manager.summarize_conversation_and_store("Samson", raw_log=log)
    
    assert summary == "Samson talked about fishing."
    mock_manage_data.add_memories.assert_called_once_with([summary], user_id="Samson")
    conv_manager.memory_manager.save_summary.assert_called_once()
    mock_cache.clear.assert_called_once()

# --- Tool Tests ---

def test_getUserInfo_failure():
    # If getUserInfo is a MagicMock (due to module mocking), we can't test its real logic
    # but we can verify the test structure is sound.
    if isinstance(execute_plan.getUserInfo, MagicMock):
        pytest.skip("Skipping because getUserInfo is a mock from sys.modules isolation")
    
    mock_config = {"configurable": {"user_id": "nonexistent"}}
    with patch("execute_plan.get_user_collection") as mock_coll:
        mock_coll.return_value.get.side_effect = Exception("DB Error")
        result = execute_plan.getUserInfo.invoke({}, mock_config)
        assert "Error retrieving info" in result

if __name__ == "__main__":
    pytest.main([__file__])