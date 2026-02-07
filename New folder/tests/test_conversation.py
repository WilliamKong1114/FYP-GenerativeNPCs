import time
import conversation_manager
from conversation_manager import ConversationManager

def test_immediate_conversation():
    print("--- Starting Immediate Conversation Test ---")
    
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
    
    # Convert to list so we can check length AND print it
    dialogue_turns = list(dialogue_gen)
    print("\n--- Generated Dialogue ---")
    for turn in dialogue_turns:
        print(f"[{turn['speaker']}]: {turn['text']}")
        
    assert len(dialogue_turns) > 0, "Dialogue generation should return at least one turn"

if __name__ == "__main__":
    test_immediate_conversation()
