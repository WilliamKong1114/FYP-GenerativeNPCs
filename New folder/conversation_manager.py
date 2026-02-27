import time
import random
import uuid
import json
import threading
from dotenv import load_dotenv
import manage_data
from agent_memory import AgentMemoryManager
from Secure.llm_config import dialogue_llm
from World_Environment.simulation_clock import SimulationClock

load_dotenv()

CONVERSATION_COOLDOWN = 300
PROBABILITY_TO_TALK = 0.7
MIN_CONVERSATION_TURNS = 6
MAX_TERNS = 20
EXTRA_TURNS_PER_PARTICIPANT = 2

class ConversationManager:
    def __init__(self, graph=None, clock: "SimulationClock"=None, debug_mode: bool = False):
        self.last_conversation_time = {}
        self.memory_manager = AgentMemoryManager()
        self.llm = dialogue_llm
        self.clock = clock
        self.graph = graph
        self.debug_mode = debug_mode
        self.db_lock = threading.Lock()

    def generate_agent_response(self,agent_id: str, agent_persona: str, triggering_msg: str, sender_id: str = None, thread_id: str = None):
        #incharge of in-game conversation generation
        config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": agent_id,
                "agent_name": agent_id,
                "agent_persona": agent_persona
            }
        }
        
        inputs = {"messages": [{"role": "user", "content": triggering_msg}]}
        response_content = ""
        result = self.graph.invoke(inputs, config)       #trigger agent_node and tools
        messages = result.get("messages", [])
        if messages:
            response_content = messages[-1].content
        return response_content

    def _get_group_key(self, agent_ids):
        return tuple(sorted(agent_ids))

    def handle_conversation(self, area: str, group: list, agent_executions: dict, client=None) -> None:
        agent_ids = [a["id"] for a in group]

        for a_id in agent_ids:
            agent_executions[a_id]["is_chatting"] = True
            agent_executions[a_id]["is_busy_until"] = time.time() + 600 # Prevent other tasks while chatting
            if client: 
                client.stop(agent_id=a_id)

        print(f"\n--- Conversation Triggered: {', '.join(agent_ids)} at {area} ---")
        context = f"{', '.join(agent_ids)} are in the {area}."

        debug_convo = []
        for turn in self.generate_dialogue(area, group, context):
            speaker = turn["speaker"]
            text = turn["text"]
            print(f"\n[D] {speaker}: {text}")
            if (self.debug_mode):
                debug_convo.append(f'{speaker}: "{text}"')
            if client: 
                client.show_dialogue("dialogue", agent_id=speaker)

        for a_id in agent_ids:
            if a_id in agent_executions:
                agent_executions[a_id]["is_chatting"] = False
                agent_executions[a_id]["is_busy_until"] = time.time() + 5
        
        if self.debug_mode and debug_convo:
            return debug_convo
        print(f"--- Conversation Ended: {', '.join(agent_ids)} ---")

    def start_conversation(self, areaName: str, group: list):        
        agent_ids = [p['id'] for p in group]
        group_key = self._get_group_key(agent_ids)
        last_time = self.last_conversation_time.get(group_key, 0)
        
        if time.time() - last_time < CONVERSATION_COOLDOWN:
            if self.debug_mode:
                print(f"\n--- No Conversation: {', '.join(agent_ids)} at {areaName} ---")
            return False

        if random.uniform(0.1, 1.0) > PROBABILITY_TO_TALK:
            self.last_conversation_time[group_key] = time.time() - (CONVERSATION_COOLDOWN - 10)
            if self.debug_mode:
                print(f"\n--- No Conversation: {', '.join(agent_ids)} at {areaName} ---")
            return False

        self.last_conversation_time[group_key] = time.time()
        return True

    def summarize_conversation_and_store(self, user_id: str, raw_log: str = None, log_id: str = None) -> str:
        if self.debug_mode:
            print(f"(debug) summary skipped")
            return raw_log or ""
        
        import execute_plan
        execute_plan.memory_cache.clear()
        convo_length = 100
        
        time_context = ""
        current_time_str = ""
        if self.clock:
            current_time_str = self.clock.get_time_string()
            time_context = f"Record Time: {current_time_str}\n"

        system = {
            "role": "system",
            "content": 
                f"You are {user_id}.\n"
                f"{time_context}"
                f"You are trying to summarize the conversation you just had into 2 to 4 reasonable amount of sentence (total <={convo_length} words) to be stored as your long-term memory.\n"
                "The summary will be accessed by your future self to recap what is going on, and what have been mentioned.\n"
                "The summary must capture:\n"
                "1. your own revealed plans, intent, or identity traits.\n"
                "2. Key information, news, or observations you gathered about the conversation partner.\n"
                "3. The main outcome or topic of the interaction.\n"
                "Output only the sentence — no explanations or filler.\n"
        }
        user_msg = {"role": "user", "content": f"{raw_log}"}

        resp = self.llm.invoke([system, user_msg])
        summary = getattr(resp, "content", None) or str(resp)

        if current_time_str:
            summary = f"[{current_time_str}] {summary}"

        manage_data.add_memories([summary], user_id=user_id)
        self.memory_manager.save_summary(user_id, summary, log_id=log_id)

        #print(f"--- Conversation summary for {user_id} saved ---")
        print(f"[{user_id}]: {summary}")
        return summary

    def check_conversation_status(self, sender_id,dialogue_history):
        if len(dialogue_history) < MIN_CONVERSATION_TURNS:
            return False

        if len(dialogue_history) % 2 == 0:
            conv_history = "\n".join([f"{d['speaker']}: {d['text']}" for d in dialogue_history])
            prompt_content =(
                f"You are {sender_id}. Review the recent conversation history and decide whether the conversation should end now, and if so, produce a closing message that suit your personality.\n"
                f"Conversation history:{conv_history}\n"
                "Checklist — answer each internally (do NOT output the answers):\n"
                "1) Has either participant explicitly said goodbye, thanked, or signaled ending (e.g., \"bye\", \"that's all\", \"thanks, done\")?\n"
                "2) Has the question been answered or the task completed with no clear follow-up request?\n"
                "3) Is the conversation looping or going far: are the last 4–6 turns mostly confirmations, rephrases, or minor variations without new progress?\n"
                "4) Has the same topic/question been asked again with substantially the same intent at least 2 times in the recent turns?\n"
                "5) Are there more than 3 distinct topics being discussed in this conversation segment, suggesting drift or lack of focus?\n"
                "6) Are both sides repeating explanations or requests because the other side is not responding meaningfully?\n"
                "- Respond \"YES\" (conversation should end) if ANY of the item above is true:\n"
                "- Otherwise respond \"NO\".\n"

                "\nOutput rules:\n"
                "- If the answer is NO: Output ONLY: NO\n"
                "- If the answer is YES: Output two parts:\n"
                "  Line 1: YES\n"
                "  Line 2: A wrap‑up sentences. Including an answer within closing if a question has been asked.\n"
                "- The wrap-up sentence should be under first person perspective.\n"
                
                "\nHard constraints:\n"
                "- Do NOT output any lists, bullet points, numbered items, explanations, or reasoning.\n"
                "- Do NOT mention conditions (1)–(7), the decision rule, or the output rules.\n"
                "- Do NOT sounding overly formal or poetic.\n"
                "- Your output must be either:\n"
                "    - A single line: NO\n"
                "    - Or two lines: YES and a wrap‑up sentence on the next line.\n"

                "\nSpecial rule:\n"
                "- If the other party asked you a question at any point, your wrap‑up must begin by answering that question directly.\n"
                "- You may add a single additional sentence after the answer as a brief closing remark. Do not leave the question unanswered.\n"
                "- Example: Q: Anything special you want to bring along? A: I’ll bring my fishing rod. See you at the willow bend."
            )

            full_resp = self.llm.invoke(prompt_content).content.strip()
            if full_resp.upper().startswith("YES"):
                lines = full_resp.split('\n')
                msg = lines[1].strip() if len(lines) > 1 else ""
                return msg if msg else True        
        return False

    def generate_dialogue(self, area: str, participants: list, context_str):
        if not participants:
            return
        
        agent_ids = [p['id'] for p in participants]
        group_key = self._get_group_key(agent_ids)
        #self.last_conversation_time[group_key] = time.time()
        max_turns = MAX_TERNS + (len(participants) * EXTRA_TURNS_PER_PARTICIPANT)
        conv_id = str(uuid.uuid4())[:8]
        starter = random.choice(participants)
        print(f"Starting chat between {', '.join(agent_ids)} ({conv_id})")
        
        try:
            current_speaker = starter
            sender_id = "System"

            other_ids = [pid for pid in agent_ids if pid != starter['id']]
            last_text = f"You see {', '.join(other_ids)} nearby. {context_str} Say something to start a conversation."
            dialogue_history = []

            for i in range(max_turns):
                others = [p for p in participants if p['id'] != current_speaker['id']]
                others_str = ", ".join([p['id'] for p in others])
                
                response_text = self.generate_agent_response(
                    agent_id=current_speaker['id'],
                    agent_persona=current_speaker['persona'],
                    triggering_msg=last_text,
                    sender_id=sender_id,
                    thread_id=f"{current_speaker['id']}_{conv_id}"
                )
                
                response_text = response_text.strip('"').strip()
                if not response_text:
                    break

                turn_data = {"speaker": current_speaker['id'], "text": response_text}
                dialogue_history.append(turn_data)
                yield turn_data
                
                last_text = response_text
                sender_id = current_speaker['id']
                
                status = self.check_conversation_status(sender_id, dialogue_history)
                if status:
                    if isinstance(status, str):
                        wrap_up_turn = {"speaker": current_speaker['id'], "text": status}
                        dialogue_history.append(wrap_up_turn)
                        yield wrap_up_turn
                    print(f"Conversation ended at turn {i+1}")
                    break
                if not others:
                    break
                current_speaker = random.choice(others)
            self.record_conversation(agent_ids, dialogue_history, area)
        except Exception as e:
            print(f"Error during conversation: {e}")

    def record_conversation(self, participants, dialogue, place):
        if not dialogue:
            return
        
        if self.debug_mode:
            print(f"(debug) conversation log skipped")
            return
        
        with self.db_lock:
            try:
                log_parts = [f'{turn["speaker"]}: "{turn["text"]}"' for turn in dialogue]
                log_string = "; ".join(log_parts)
                log_id = self.memory_manager.add_conversation_log(participants, log_string, place)
                for p in participants:
                    self.summarize_conversation_and_store(p, raw_log=log_string, log_id=log_id)
                print(f"Saved conversation logs and summaries for {participants}")
            except Exception as e:
                print(f"Error saving conversation: {e}")
