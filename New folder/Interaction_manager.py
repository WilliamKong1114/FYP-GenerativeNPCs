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

user_id = "William"
agent_id = "Wilton"
conf = agents_config.get(agent_id, {})
persona = conf["persona"]
tone = conf["tone"]
relationship = "Stranger"

class InteractManager:
    def __init__(self, max_turns: int = 12):
        self.llm = dialogue_llm
        self.question_list = QUESTION_LIST
        self.max_turns = max_turns
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _ended_payload(self, session: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "success",
            "session_id": session["session_id"],
            "agent_id": session["agent_id"],
            "agent_text": "Alright! See you next time!",
            "options": [],
            "ended": True,
        }

    def normalize_options(self, options: List[Any]) -> List[Dict[str, str]]:
        normalized = []
        for i, opt in enumerate(options):
            if isinstance(opt, str):
                text = opt.strip()
            else:
                text = str(opt.get("text")).strip()

            if not text:
                continue

            normalized.append({
                "id": str(i),
                "text": text
            })
        return normalized

    def start_conversation(self, agent_id: str, question: str) -> Dict[str, Any]:
        if not agent_id:
            raise ValueError("agent_id is required")

        if not question:
            raise ValueError("Invalid question")

        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "agent_id": agent_id,
            "history": [{"role": "user", "text": question}],
            "ended": False,
        }

        with self._lock:
            self._sessions[session_id] = session

        return self.advance_turn(session_id, question)

    def advance_turn(self, session_id: str, user_text: str) -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise ValueError("Unknown session_id")

            session["history"].append({"role": "user", "text": user_text})

            if len(session["history"]) >= self.max_turns:
                session["ended"] = True
                return self._ended_payload(session)

            agent_data = self.generate_agent_reply(session["agent_id"], session["history"])
            agent_text = agent_data["response"].strip()
            agent_question = agent_data["question"]
            agent_exit = agent_data["exit"]

            session["history"].append({"role": "agent", "text": agent_text})

            if agent_exit:
                session["ended"] = True
                return {
                    "status": "success",
                    "session_id": session["session_id"],
                    "agent_id": session["agent_id"],
                    "agent_text": agent_text,
                    "options": [],
                    "ended": True,
                }

            options = self.generate_user_reply(session["agent_id"], session["history"], agent_question)
            
            return {
                "status": "success",
                "session_id": session["session_id"],
                "agent_id": session["agent_id"],
                "agent_text": agent_text,
                "options": options,
                "ended": False,
            }

    def generate_agent_reply(self, agent_id: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        history_conv = "\n".join(f"{h['role']}: {h['text']}" for h in history)

        question_prompt = ""
        question_prob = random.uniform(0.1, 1.0)
        if (question_prob > 0.3) and len(history) > 2:
            question_prompt += f"""
                - After answering the user's latest question, you MUST include a follow-up Yes/No question to know more about the {user_id}, such as their background, interests, or preference. 
                - Generate the follow-up question based on the the conversation history, current relationship ({relationship}) with {user_id} and choose cooresponding tone with the user.
                - The question MUST be a Yes/No question which the agents will only reply "Yes" or "No" to, sometimes with a very short explanation (e.g., "Yes, I like traveling." or "No, I don't have a pet.").
                - Do not repeat similar questions you've already asked. If a topic has already been explored, choose a different angle or subject.
                - Set "question" field in the output to true.
            """
        else:
            question_prompt += "- Do not ask any follow-up question after answering the user's latest input. Set 'question' field in the output to false."
            
        system_prompt = f"""
            The year is 1200A.D. You are {agent_id}, a villager living in a medieval settlement.
            Your persona: {persona}
            Context: You are meeting {user_id} for the first time.
            Your tone when meeting with people in different relationships (Current relationship with {user_id}: {relationship}): {tone}

            Conversation history: {history_conv}\n
            {question_prompt}
            Guidelines:
            - Keep your responses around 20 words
            - Adapt responses to the user's latest input.
            - Return JSON format: {{"response": "...", "question": true/false, "exit": true/false}}
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

    def generate_user_reply(self, agent_id: str, history: List[Dict[str, str]], agent_question: bool=False) -> List[Dict[str, str]]:
        history_conv = "\n".join(f"{h['role']}: {h['text']}" for h in history)
        relationship = "Stranger"

        if agent_question:
            system_prompt = f"""
                The year is 1200A.D. You are a traveller visiting a medieval settlement and talking to {agent_id}, a local villager.
                Provide exactly 3 reply options: 
                    1. A positive response (e.g., "Yes", "Sure", "Alright") with a brief natural explanation.
                    2. A polite refusal (e.g., "No", "Sorry") with a short explanation.
                    3. A response that leads toward exiting the conversation, with a smooth transition connected to the previous dialogue. Do NOT involve questions for this.
                Make sure each option fits the current {relationship} relationship and the conversation history.                
                Conversation history: {history_conv}
                Output Format: {{"options": ["reply 1", "reply 2", "reply 3 (exit intent)"]}}
            """
        else:
            system_prompt = f"""
                The year is 1200A.D. You are a traveller visiting a medieval settlement and talking to {agent_id}, a villager.
                Provide exactly 4 questions:
                    - 3 natural follow-up questions which fit the current {relationship} relationship and the conversation history, and should be continuations of the dialogue.
                    - 1 question designed to leads toward exiting the conversation, with a smooth transition connected to the previous dialogue. Do NOT involve questions for this. 
                Conversation history: {history_conv}
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
        return self.normalize_options(raw_options)
        
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

    print(f"\n{user_id}: {user_text}")
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
        print(f"\n{user_id}: {user_text}")

        if choice_id == str(len(options) - 1):
            print("\n=== Conversation Ended by User ===")
            break
        
        response = interact_manager.advance_turn(session_id, user_text)

if __name__ == "__main__":
    main()
