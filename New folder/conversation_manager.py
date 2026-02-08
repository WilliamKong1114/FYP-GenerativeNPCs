import time
import random
import uuid
import json
from datetime import datetime
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
import manage_data

load_dotenv()

CONVERSATION_COOLDOWN = 300
PROBABILITY_TO_TALK = 0.5
MIN_CONVERSATION_TURNS = 8

class ConversationManager:
    def __init__(self, generate_response_func=None):
        self.last_conversation_time = {}
        self.generate_response_func = generate_response_func
        self.llm = ChatVertexAI(
            model="gemini-2.5-flash",
            project="finalyearproject-473307",
            location="us-central1",
            temperature=0.7,
            max_tokens=None,
            max_retries=3,
        )

    def _get_group_key(self, agent_ids):
        return tuple(sorted(agent_ids))

    def start_conversation(self, participants):
        if len(participants) < 2:
            return False
        
        agent_ids = [p['id'] for p in participants]
        group_key = self._get_group_key(agent_ids)
        last_time = self.last_conversation_time.get(group_key, 0)
        
        if time.time() - last_time < CONVERSATION_COOLDOWN:
            return False

        if random.random() > PROBABILITY_TO_TALK:
            self.last_conversation_time[group_key] = time.time() - (CONVERSATION_COOLDOWN - 10) 
            return False

        return True

    def check_conversation_status(self, dialogue_history):
        """
        Check if the conversation has reached a natural conclusion. 
        Returns True if it should end.
        """
        if len(dialogue_history) < MIN_CONVERSATION_TURNS:
            return False

        if len(dialogue_history) % 2 == 0:
            conv_history = "\n".join([f"{d['speaker']}: {d['text']}" for d in dialogue_history])
            prompt_content = f"""
                You are a conversation auditor.
                Review the recent conversation history and decide whether the conversation should end now, and if so, produce a closing message that suit your personality.
                Conversation history:{conv_history}

                Checklist — answer each internally (do NOT output the answers):
                1) Has either participant explicitly said goodbye, thanked, or signaled ending (e.g., "bye", "that's all", "thanks, done")?
                2) Has the main question been answered or the task completed with no clear follow-up request?
                3) Is the conversation looping or going far: are the last 4–6 turns mostly confirmations, rephrases, or minor variations without new progress?
                4) Has the same topic/question been asked again with substantially the same intent at least 2 times in the recent turns?
                5) Does a participant appear disinterested (very short replies, vague replies like "ok", "idk", "whatever", or no new info)?
                6) Are there more than 3 distinct topics being discussed in this conversation segment, suggesting drift or lack of focus?
                7) Are both sides repeating explanations or requests because the other side is not responding meaningfully?

                Decision rule:
                - Respond "YES" (conversation should end) if ANY of these are true:
                A) (1) is true, OR
                B) (2) is true AND no clear next step is requested, OR
                C) (3) OR (4) is true (looping or redundancy), OR
                D) (5) is true OR (7) is true (disinterest or stalled), OR
                E) (6) is true (too many topics).
                - Otherwise respond "NO".

                Output rules:
                - If the answer is NO:
                    Output ONLY: NO
                - If the answer is YES:
                    Output two parts:
                    Line 1: YES
                    Line 2: A wrap‑up message (1–2 sentences), e.g.:
                            "Gonna go now! If you need anything else later, feel free to ask."
                Do not output anything other than what is defined above.
                """

            try:
                full_resp = self.llm.invoke(prompt_content).content.strip()
                if full_resp.upper().startswith("YES"):
                    lines = full_resp.split('\n')
                    msg = lines[1].strip() if len(lines) > 1 else ""
                    return msg if msg else True
            except Exception:
                pass
        
        return False

    def generate_dialogue(self, participants, context_str):
        agent_ids = [p['id'] for p in participants]
        group_key = self._get_group_key(agent_ids)
        self.last_conversation_time[group_key] = time.time()

        max_turns = 10 + (len(participants) * 3)
        conv_id = str(uuid.uuid4())[:8]

        starter = random.choice(participants)
        print(f"[ConversationManager] Starting chat between {', '.join(agent_ids)} ({conv_id})")

        other_ids = [pid for pid in agent_ids if pid != starter['id']]
        last_text = f"You see {', '.join(other_ids)} nearby. {context_str} Say something to start a conversation."
        
        current_speaker = starter
        sender_id = "System"
        dialogue_history = []
        
        location_fallback = "Unknown Location"
        loc = participants[0]['state'].get('interaction_area', location_fallback) if participants else location_fallback

        for i in range(max_turns):
            try:
                others = [p for p in participants if p['id'] != current_speaker['id']]
                others_str = ", ".join([p['id'] for p in others])
                
                if self.generate_response_func:
                    response_text = self.generate_response_func(
                        agent_id=current_speaker['id'],
                        agent_persona=current_speaker['persona'],
                        triggering_msg=last_text,
                        sender_id=sender_id,
                        thread_id=f"{current_speaker['id']}_{conv_id}"
                    )
                else:
                    response_text = f"Hello, {others_str}!"
                
                response_text = response_text.strip('"').strip()
                if not response_text:
                    break

                turn_data = {"speaker": current_speaker['id'], "text": response_text}
                dialogue_history.append(turn_data)
                yield turn_data
                
                last_text = response_text
                sender_id = current_speaker['id']
                
                status = self.check_conversation_status(dialogue_history)
                if status:
                    if isinstance(status, str):
                        wrap_up_turn = {"speaker": current_speaker['id'], "text": status}
                        dialogue_history.append(wrap_up_turn)
                        yield wrap_up_turn
                    print(f"[ConversationManager] Conversation ended at turn {i+1}")
                    break
                
                if not others:
                    break
                current_speaker = random.choice(others)

            except Exception as e:
                print(f"[ConversationManager] Error in turn {i}: {e}")
                break
        
        self.record_conversation(agent_ids, dialogue_history, loc)

    def record_conversation(self, participants, dialogue, place):
        if not dialogue:
            return

        timestamp = datetime.now().isoformat()
        
        log_parts = []
        for turn in dialogue:
            log_parts.append(f'{turn["speaker"]}: "{turn["text"]}"')
        log_string = "; ".join(log_parts)

        log_id = manage_data.save_conversation_log(participants, log_string, place)

        for p in participants:
            if self.generate_response_func:
                import execute_plan
                execute_plan.summarize_conversation_and_store(p, raw_log=log_string, log_id=log_id)
            else:
                manage_data.add_memories([log_string], user_id=p)

        conversation_text = f"Conversation between {', '.join(participants)} at {timestamp} in {place}:\n"
        for turn in dialogue:
            conversation_text += f"{turn['speaker']}: {turn['text']}\n"
        
        for p in participants:
            manage_data.add_memories([conversation_text], user_id=p)
        
        print(f"[ConversationManager] Saved conversation logs and summaries for {participants}")

