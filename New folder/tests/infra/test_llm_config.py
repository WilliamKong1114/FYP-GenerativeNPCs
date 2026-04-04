import pytest
import os
from langchain_azure_ai.chat_models import AzureAIChatCompletionsModel
from Secure.llm_config import dialogue_llm, skill_llm, planner_llm, routing_llm

def test_llm_initialization():
    """Test that all LLM objects are correctly initialized as AzureAIChatCompletionsModel."""
    assert isinstance(dialogue_llm, AzureAIChatCompletionsModel)
    assert isinstance(skill_llm, AzureAIChatCompletionsModel)
    assert isinstance(planner_llm, AzureAIChatCompletionsModel)
    assert isinstance(routing_llm, AzureAIChatCompletionsModel)

def test_llm_parameters():
    """Test that the LLMs have the expected temperature settings."""
    assert dialogue_llm.temperature == 0.3
    assert skill_llm.temperature == 0.2
    assert planner_llm.temperature == 0.1
    # Note: In the latest file, routing_llm is back to Phi-4-reasoning
    assert routing_llm.temperature == 0.0

def test_github_token_exists():
    """Verify that the GITHUB_TOKEN environment variable is loaded."""
    token = os.getenv("GITHUB_TOKEN")
    assert token is not None, "GITHUB_TOKEN not found in environment or .env file"
    assert token.startswith("github_") or len(token) > 20, "GITHUB_TOKEN looks invalid"

@pytest.mark.parametrize("llm_name, llm_instance", [
    ("Dialogue", dialogue_llm),
    ("Skill", skill_llm),
    ("Planner", planner_llm),
    ("Routing", routing_llm),
])
@pytest.mark.skipif(os.getenv("SKIP_LIVE_TESTS") == "true", reason="Skipping live API calls")
def test_llm_connectivity(llm_name, llm_instance):
    """Perform a simple invocation to verify actual connectivity to the endpoint."""
    try:
        response = llm_instance.invoke("test")
        assert response.content is not None
        assert len(response.content) > 0
    except Exception as e:
        pytest.fail(f"Connectivity test failed for {llm_name} LLM: {e}")
