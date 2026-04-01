from types import SimpleNamespace
from Interaction_manager import UserToAgentInteractManager

class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    def invoke(self, _messages):
        if not self.responses:
            raise RuntimeError("No fake responses left")
        return SimpleNamespace(content=self.responses.pop(0))


def test_get_starter_questions_returns_static_options():
    manager = UserToAgentInteractManager(llm=FakeLLM([]))
    payload = manager.get_starter_questions(agent_id="Samson")

    assert payload["status"] == "success"
    assert payload["option_mode"] == "starter"
    assert payload["ended"] is False
    assert len(payload["options"]) == 3
    assert payload["options"][0]["id"] == "starter_0"


def test_start_conversation_returns_three_tone_options():
    fake_llm = FakeLLM([
        '{"agent_text":"I am doing well.","asks_yes_no":false,"yes_no_question":""}',
        '{"options":[{"tone":"friendly","text":"How is your day going?"},{"tone":"neutral","text":"What happened today?"},{"tone":"assertive","text":"Can you update me now?"}]}',
    ])
    manager = UserToAgentInteractManager(llm=fake_llm)

    payload = manager.start_conversation(agent_id="Samson", starter_question_id="starter_0")

    assert payload["status"] == "success"
    assert payload["option_mode"] == "generated_options"
    assert payload["ended"] is False
    assert len(payload["options"]) == 3
    assert [o["tone"] for o in payload["options"]] == ["friendly", "neutral", "assertive"]


def test_start_conversation_yes_no_branch_returns_binary_options():
    fake_llm = FakeLLM([
        '{"agent_text":"I need one quick confirmation.","asks_yes_no":true,"yes_no_question":"Are you free now?"}'
    ])
    manager = UserToAgentInteractManager(llm=fake_llm)

    payload = manager.start_conversation(agent_id="Samson", starter_question_id="starter_1")

    assert payload["option_mode"] == "yes_no"
    assert [o["id"] for o in payload["options"]] == ["yes", "no"]
    assert "Are you free now?" in payload["agent_text"]


def test_followup_generation_falls_back_when_json_invalid():
    fake_llm = FakeLLM([
        '{"agent_text":"I am here.","asks_yes_no":false,"yes_no_question":""}',
        'not valid json',
    ])
    manager = UserToAgentInteractManager(llm=fake_llm)

    payload = manager.start_conversation(agent_id="Samson", starter_question_id="starter_2")

    assert payload["option_mode"] == "generated_options"
    assert len(payload["options"]) == 3
    assert [o["tone"] for o in payload["options"]] == ["friendly", "neutral", "assertive"]

