from World_Environment.agent_state import AgentState

def test_agent_state_initialization():
    # Test if AgentState can be initialized with basic data
    agent_id = "TestAgent"
    state = AgentState(agent_id)
    assert state.agent_id == agent_id
    # Add more basic assertions based on what AgentState does
