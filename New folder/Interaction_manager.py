import json
import random
import threading
import uuid
from typing import Any, Dict, List, Optional

from Secure.llm_config import dialogue_llm
from World_Environment.agent_state_manager import AgentStateManager
from preference_manager import PreferenceManager

QUESTION_LIST = [
    "Hi! How are you feeling today?",
    "What have you been up to since we last spoke?",
    "Whatsup!",
]

pref_manager = PreferenceManager()
agents_state = AgentStateManager().get_agent_state()
agents_config = {
    name: {
        "persona": data["persona"],
        "tone": data["tone"],
        "home_node": data["home_node"],
        "home_area": data["home_area"]
    }
    for name, data in agents_state.items()
}

user_config = {
    "user_id": "Traveler",
    "relationship": "Stranger",
}
DEFAULT_OPENING_LINE = "Hi! How are you today?"

class InteractManager:
    def __init__(self, max_turns: int = 12):
        self.llm = dialogue_llm
        self.question_list = QUESTION_LIST
        self.max_turns = max_turns
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _agent_profile(self, agent_id: str) -> Dict[str, str]:
        conf = agents_config.get(agent_id, {})
        return {
            "persona": conf.get("persona"),
            "tone": conf.get("tone"),
        }

    def _ended_payload(self, session: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "success",
            "session_id": session["session_id"],
            "agent_id": session["agent_id"],
            "agent_text": "Alright! See you next time!",
            "agent_question": False,
            "options": [],
            "ended": True,
        }

    def normalize_options(self, options: List[Any]) -> List[Dict[str, str]]:
        normalized = []
        for i, opt in enumerate(options):
            if isinstance(opt, str):
                text = opt.strip()
                option_id = str(i)
                tone = None
            else:
                text = str(opt.get("text")).strip()
                option_id = str(opt.get("id", i))
                tone = opt.get("tone")

            if not text:
                continue

            option = {
                "id": option_id,
                "text": text,
            }
            if tone:
                option["tone"] = str(tone)

            normalized.append(option)
        return normalized

    def start_conversation(self, agent_id: str, question: str, current_area: str = None, current_target: str = None) -> Dict[str, Any]:
        if not agent_id:
            raise ValueError("agent_id is required")

        if not question:
            raise ValueError("Invalid question")

        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "agent_id": agent_id,
            "history": [],
            "options": [],
            "ended": False,
        }

        with self._lock:
            self._sessions[session_id] = session

        payload = self.advance_turn(session_id, question, current_area, current_target)
        return payload

    def continue_conversation(self, session_id: str, user_text: str, current_area: str = None, current_target: str = None) -> Dict[str, Any]:
        return self.advance_turn(session_id, user_text, current_area=current_area, current_target=current_target)

    def advance_turn(self, session_id: str, user_text: str, current_area: str = None, current_target: str = None) -> Dict[str, Any]:
        if not user_text:
            raise ValueError("Invalid user text")

        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise ValueError("Unknown session_id")

            session["history"].append({"role": "user", "text": user_text})

            if len(session["history"]) >= self.max_turns:
                session["ended"] = True
                return self._ended_payload(session)

            agent_data = self.generate_agent_reply(session["agent_id"], session["history"], user_text, current_area, current_target)
            agent_response = str(agent_data.get("response")).strip()
            agent_question = agent_data.get("question") #true/false
            agent_exit = agent_data.get("exit")

            session["history"].append({"role": "agent", "text": agent_response})

            if agent_exit:
                session["ended"] = True
                session["options"] = []
                return {
                    "status": "success",
                    "session_id": session["session_id"],
                    "agent_id": session["agent_id"],
                    "agent_text": agent_response,
                    "agent_question": False,
                    #"option_mode": "none",
                    "options": [],
                    "ended": True,
                }

            options = self.generate_user_reply(session["agent_id"], agent_question, agent_response, current_area, current_target)
            session["options"] = options
            
            return {
                "status": "success",
                "session_id": session["session_id"],
                "agent_id": session["agent_id"],
                "agent_text": agent_response,
                "agent_question": agent_question,
                #"option_mode": "yes_no" if agent_question else "generated_options",
                "options": options,
                "ended": False,
            }

    def generate_agent_reply(self, agent_id: str, history: List[Dict[str, str]], user_text: str, current_area: str = None, current_target: str = None) -> Dict[str, Any]:
        history_conv = "\n".join(f"{h['role']}: {h['text']}" for h in history)
        profile = self._agent_profile(agent_id)
        persona = profile["persona"]
        tone = profile["tone"]
        relationship = "Stranger"

        question_prompt = ""
        question_prob = random.uniform(0.1, 1.0)
        question_condition = (question_prob > 0.5) and len(history) > 4
        if question_condition:
            question_prompt += f"""
                - After answering the user's latest question, you MUST include a follow-up Yes/No question to continue the conversation with {user_config['user_id']}.
                - The question should helps you learn more about the user, and can be related to the user's preference, experience, or opinion.
                - Or it can be promoting your product, works or services provided by you depending on your job.
                - Generate the follow-up question based on the the conversation history, current relationship ({relationship}) with {user_config['user_id']} and choose cooresponding tone with the user.
                - The question MUST be a Yes/No question which the agents will only reply "Yes" or "No" to, sometimes with a very short explanation (e.g., "Yes, I like traveling." or "No, I don't have a pet.").
                - Do not repeat similar questions you've already asked. If a topic has already been explored, choose a different angle or subject.
                - Set "question" field in the output to true.
            """
        else:
            question_prompt += "- Do NOT include any questions in the response. Set 'question' field in the output to false."
            
        system_prompt = f"""
            The year is 1200A.D. You are {agent_id}, a villager living in a medieval settlement.
            Your persona: {persona}
            Context: {user_config['user_id']} starts a conversation with you. You are at {current_area}, {current_target}.
            Choose the corresponding tone regrading the relationship. (Current relationship with {user_config['user_id']}: {relationship}): {tone}
            Here is the reply or question from {user_config['user_id']}: "{user_text}". Generate your response based on this.
            Here is the Conversation history for your reference: {history_conv}\n
            {question_prompt}
            Guidelines:
            - Keep your responses around 20 words
            - Adapt responses to the user's latest input.
            - Do NOT repeat the content already mentioned in the conversation history.
            - Avoid poetic or flowery language, use natural expressions.
            - Return JSON format: {{"response": "...", "question": {question_condition}, "exit": true/false}}
        """
        msg = [{"role": "system", "content": system_prompt}]
        response = self.llm.invoke(msg)
        content = str(getattr(response, "content", response)).strip()
        
        """
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        """
        return json.loads(content)

    def generate_user_reply(self, agent_id: str, agent_question: bool, agent_response: str, current_area: str = None, current_target: str = None) -> List[Dict[str, str]]:
        #history_conv = "\n".join(f"{h['role']}: {h['text']}" for h in history)
        relationship = user_config.get("relationship", "Stranger")

        if agent_question:
            system_prompt = f"""
                The year is 1200A.D. You are a traveller named {user_config['user_id']}, visiting a medieval settlement for the first time and talking to {agent_id} at {current_area}, a local villager. The village is using the {current_target}.
                Generate exactly 3 reply options based on the response from the villager: {agent_response}. The 3 reply options MUST includes: 
                    1. A positive response (e.g., "Yes", "Sure", "Alright").
                    2. A polite refusal (e.g., "No", "Sorry").
                    3. A response that leads toward exiting the conversation, with a smooth transition connected to the previous dialogue. Do NOT includes any questions.
                Make sure each option fits the current {relationship} relationship.                
                Output Format: {{"options": ["reply 1", "reply 2", "reply 3 (exit intent)"]}}
            """
        else:
            system_prompt = f"""
                The year is 1200A.D. You are a traveller named {user_config['user_id']}, visiting a medieval settlement for the first time and talking to {agent_id}, a local villager. The village is using the {current_target}.
                Generate exactly 4 questions:
                    - 3 natural follow-up questions which fit the current {relationship} relationship, and can be the continuations of agent's response: {agent_response}.
                    - Questions should be related your current location: {current_area} and the {current_target} being used by the villager. If the location is relevant to the agent's work, you can ask questions related to the agent's job.
                    - 1 question designed to leads toward exiting the conversation, with a smooth transition connected to the previous dialogue. Do NOT involve questions for this. 
                Output Format: {{"options": ["question 1", "question 2", "question 3", "question 4 (exit intent)"]}}
            """
        
        msg = [{"role": "system", "content": system_prompt}]
        response = self.llm.invoke(msg)
        content = str(getattr(response, "content", response)).strip()

        """
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        """
        data = json.loads(content)
        raw_options = data.get("options", [])
        normalized = self.normalize_options(raw_options)
        if normalized:
            return normalized
        
def main():
    interact_manager = InteractManager()    
    agent_id = "Wilton"

    start_options = interact_manager.normalize_options(QUESTION_LIST)
    print("\nAvailable starting questions:")
    for opt in start_options:
        print(f"[{opt['id']}] {opt['text']}")

    choice_id = input("Choose Question ID to start: ").strip()
    
    user_text = None
    for opt in start_options:
        if opt["id"] == choice_id:
            user_text = opt["text"]
            break
            
    if not user_text:
        print("Invalid choice, exiting.")
        return

    print(f"\n{user_config['user_id']}: {user_text}")
    print("-" * 30)
    
    response = interact_manager.start_conversation(agent_id, question=user_text)
    session_id = response['session_id']
    
    while True:
        print(f"\n[AGENT] {response['agent_text']}")
        
        if response.get('ended'):
            print("\n=== Conversation Ended ===")
            break
            
        options = response.get('options', [])
        if not options:
            print("\n=== Conversation Ended (No follow-ups) ===")
            break
            
        print("\nYour options:")
        for opt in options:
            if (opt["id"] == str(len(options) - 1)):
                print(f"[{opt['id']}]: {opt['text']} (Exit)")
            else:
                print(f"[{opt['id']}]: {opt['text']}")
            
        choice_id = input("\nChoose an option ID: ").strip()
        
        selected_option = next((opt for opt in options if opt["id"] == choice_id), None)
        if not selected_option:
            print("Invalid choice, please try again.")
            continue

        user_text = selected_option["text"]
        print(f"\n{user_config['user_id']}: {user_text}")

        if choice_id == str(len(options) - 1):
            print("\n=== Conversation Ended by User ===")
            break
        
        response = interact_manager.advance_turn(session_id, user_text)

if __name__ == "__main__":
    main()
