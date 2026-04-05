import time
import random
import uuid
import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from dotenv import load_dotenv
import chromaMemory_manager

from agent_memory import AgentMemoryManager
from Secure.llm_config import dialogue_llm
from World_Environment.simulation_clock import SimulationClock
from commitment_manager import CommitmentManager

commitment_manager = CommitmentManager()

load_dotenv()

CONVERSATION_COOLDOWN = 200
MIN_CONVERSATION_TURNS = 6
MAX_TERNS = 10
EXTRA_TURNS_PER_PARTICIPANT = 2
LLM_TIMEOUT_SECONDS = 20

class ConversationManager:
    def __init__(self, graph=None, clock: "SimulationClock"=None, debug_mode: bool = False, preference_manager=None):
        self.memory_manager = AgentMemoryManager()
        self.llm = dialogue_llm
        self.clock = clock
        self.graph = graph
        self.debug_mode = debug_mode
        self.preference_manager = preference_manager
        self.db_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending_conversations: set[frozenset] = set()

    def _invoke_timeout(self, fn, *args, timeout: float = LLM_TIMEOUT_SECONDS, label: str = "LLM"):
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(fn, *args)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            print(f"[CONV] {label} timed out after {timeout}s.")
            return None
        except Exception as e:
            print(f"[CONV] {label} failed: {e}")
            return None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def check_conversation(self, area: str, group: list, agent_executions: dict, client=None, session_id: str = None) -> bool:
        agent_ids = [a["id"] for a in group]
        pair_key = frozenset(agent_ids)

        with self._state_lock:
            if pair_key in self._pending_conversations:
                return False

            now = time.time()
            for agent_id in agent_ids:
                agent_data = agent_executions.get(agent_id)
                if agent_data is None:
                    return False

                last_time = float(agent_data.get("last_conv_time", 0) or 0)
                if now - last_time < CONVERSATION_COOLDOWN:
                    if self.debug_mode:
                        print(f"\n--- No Conversation: {', '.join(agent_ids)} at {area} ---")
                    return False

            for agent_id in agent_ids:
                agent_executions[agent_id]["last_conv_time"] = now

            self._pending_conversations.add(pair_key)

        for a_id in agent_ids:
            agent_executions[a_id]["is_chatting"] = True
            agent_executions[a_id]["is_busy_until"] = time.time() + 600

        def _run():
            try:
                if client:
                    for a_id in agent_ids:
                        partner_id = next((pid for pid in agent_ids if pid != a_id), None)
                        client.set_chatting(a_id, "start", partner_id=partner_id)
                self.handle_conversation(area, group, agent_executions=agent_executions, client=client, session_id=session_id)
                if client:
                    for a_id in agent_ids:
                        partner_id = next((pid for pid in agent_ids if pid != a_id), None)
                        client.set_chatting(a_id, "stop", partner_id=partner_id)
                for a_id in agent_ids:
                    if a_id in agent_executions:
                        agent_executions[a_id]["is_chatting"] = False
                        agent_executions[a_id]["is_busy_until"] = time.time() + 1
            except Exception as e:
                print(f"[CONV] Error for {agent_ids}: {e}\n{traceback.format_exc()}")
                for a_id in agent_ids:
                    if a_id in agent_executions:
                        agent_executions[a_id]["is_chatting"] = False
                        agent_executions[a_id]["is_busy_until"] = time.time() + 5
            finally:
                with self._state_lock:
                    self._pending_conversations.discard(pair_key)

        t = threading.Thread(target=_run, daemon=True, name=f"Conv-{'&'.join(agent_ids)}")
        t.start()
        print(f"[CONV] {' & '.join(agent_ids)} started conversation at {area}.")
        return True

    def generate_agent_response(self, agent_id: str, persona: str, tone: str, triggering_msg: str, sender_id: str = None, partner_id: str = None, thread_id: str = None):
        #incharge of in-game conversation generation
        config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": agent_id,
                "agent_name": agent_id,
                "agent_persona": persona,
                "agent_tone": tone,
                "partner_id": partner_id
            }
        }
        
        inputs = {"messages": [{"role": "user", "content": triggering_msg}]}
        response_content = ""

        result = self._invoke_timeout(self.graph.invoke, inputs, config, label="Dialogue generation")
        if result is None:
            return ""

        messages = result.get("messages", [])
        if messages:
            response_content = messages[-1].content
        return response_content

    def handle_conversation(self, area: str, group: list, agent_executions: dict, client=None, session_id: str = None) -> None:
        agent_ids = [a["id"] for a in group]
        #group_key = self._get_group_key(agent_ids)

        if client:
            for a_id in agent_ids:
                client.stop(agent_id=a_id)

        for a_id in agent_ids:
            agent_executions[a_id]["is_chatting"] = True
            agent_executions[a_id]["is_busy_until"] = time.time() + 600 # Prevent other tasks while chatting

        print(f"\n--- Conversation Triggered: {', '.join(agent_ids)} at {area} ---")
        context = f"{', '.join(agent_ids)} are in the {area}."

        debug_convo = []
        dialogue_lines = []
        for turn in self.generate_dialogue(area, group, context):
            speaker = turn["speaker"]
            text = turn["text"]
            print(f"\n[D] {speaker}: {text}")

            if (self.debug_mode):
                debug_convo.append(f'{speaker}: "{text}"')
                
            dialogue_lines.append(f'{speaker}: "{text}"')
            #if client: 
                #client.show_dialogue("...", agent_id=speaker)

            if client:
                pair_key = tuple(sorted(agent_ids))
                client.dialogue_cache[pair_key] = list(dialogue_lines)
        
        if self.debug_mode and debug_convo:
            for a_id in agent_ids:
                if a_id in agent_executions:
                    agent_executions[a_id]["is_chatting"] = False
                    agent_executions[a_id]["is_busy_until"] = time.time() + 5
            return debug_convo
        
        if client and dialogue_lines:
            client.update_dialogue(agent_ids[0], dialogue_lines, agent_ids)
            client.wait_for_conv_finish(agent_ids[0])
            print(f"(With client) Conversation finished for {', '.join(agent_ids)}. Dialogue:\n" + "\n".join(dialogue_lines))
        else:
            print(f"(No client) Conversation finished for {', '.join(agent_ids)}. Dialogue:\n" + "\n".join(dialogue_lines))
            for a_id in agent_ids:
                if a_id in agent_executions:
                    agent_executions[a_id]["is_chatting"] = False
                    agent_executions[a_id]["is_busy_until"] = time.time() + 5

        print(f"--- Conversation Ended: {', '.join(agent_ids)} ---")
        current_time = self.clock.get_time_string()
        commitment_manager.assign_commitment(dialogue_lines, agent_executions, current_time)

    def summarize_conversation_and_store(self, user_id: str, raw_log: str = None, log_id: str = None) -> str:
        if self.debug_mode:
            print(f"(debug) summary skipped")
            return ""
        
        #execute_plan.memory_cache.clear()
        
        #time_context = ""
        #current_time_str = ""
        #if self.clock:
            #current_time_str = self.clock.get_time_string()
            #time_context = f"Record Time: {current_time_str}\n"

        system = {
            "role": "system",
            "content": 
                f"You are {user_id}.\n"
                #f"{time_context}"
                "You are trying to summarize the conversation with a list of 3 to 5 items, with each item must contains 10 to 15 words, with each include the name of the person.\n"
                "The summary will be accessed by your future self to recap what is going on, what have been mentioned and what needs to be done.\n"
                "The summary list must capture the following if any:\n"
                "1. Your own revealed plans, intent, or identity traits.\n"
                "2. Key information, news, or observations you gathered about the conversation partner.\n"
                "3. The main outcome or topic of the interaction.\n"
                "You also need to provide an importance rating (1-10) where 1 is purely mundane (e.g., brushing teeth, making bed) and 10 is extremely poignant, life-changing (e.g., getting married), rate the likely poignancy of the summarized memory.\n"
                "Output MUST be a valid JSON object with the following structure:\n"
                "{\"summaries\": ["
                "{\"description\": \"Samson is collaborating with Jimmy on designing garden benches using willow bend and ash wood\", \"importance\": 5},"
                "{\"description\": \"Samson and Jimmy are planning to meet at the workshop to finalize designs and select materials\", \"importance\": 7}"
                "]}"
        }
        user_msg = {"role": "user", "content": f"{raw_log}"}
        resp = self._invoke_timeout(self.llm.invoke, [system, user_msg], label=f"Summary generation for {user_id}")
        if resp is None:
            return ""

        data = json.loads(resp.content)
        summaries = data.get("summaries")

        last_summary = ""
        if self.clock:
            current_game_hours = self.clock.get_sim_hour()

        for item in summaries:
            description = item.get("description")
            importance = item.get("importance", 5)

            if self.clock:
                chromaMemory_manager.add_memories([description], user_id=user_id, importance=importance, type="summary", game_hour=current_game_hours)
            self.memory_manager.save_summary(user_id=user_id, summary=description, importance=importance, log_id=log_id)

            #print(f"[{user_id}]: {description} (Imp: {importance})")
            last_summary += f"- {description}\n"
            
        return last_summary

    def check_conversation_status(self, sender_id, sender_persona, dialogue_history):
        if len(dialogue_history) < MIN_CONVERSATION_TURNS:
            return False

        if len(dialogue_history) % 2 == 0:
            conv_history = "\n".join([f"{d['speaker']}: {d['text']}" for d in dialogue_history])
            prompt_content =(
                f"You are {sender_id}. Review the recent conversation history and decide whether the conversation should end now, and if so, produce a closing message that suit your personality.\n"
                f"Your persona: {sender_persona}\n"
                f"Conversation history:{conv_history}\n"
                "Checklist — answer each internally (do NOT output the answers):\n"
                "1) Has either participant explicitly said goodbye, thanked, or signaled ending (e.g., \"bye\", \"that's all\", \"thanks, done\")?\n"
                "2) Has the question been answered or the task completed with no clear follow-up request?\n"
                "3) Is the conversation looping or going far: are the last 4-6 turns mostly confirmations, rephrases, or minor variations without new progress?\n"
                "4) Has the same topic/question been asked again with substantially the same intent at least 2 times in the recent turns?\n"
                "5) Are there more than 3 distinct topics being discussed in this conversation segment, suggesting drift or lack of focus?\n"
                "6) Are both sides repeating explanations or requests because the other side is not responding meaningfully?\n"
                "- Respond \"YES\" (conversation should end) if ANY of the item above is true:\n"
                "- Otherwise respond \"NO\".\n"

                "\nOutput rules:\n"
                "- If the answer is NO: Output ONLY: NO\n"
                "- If the answer is YES: Output two parts:\n"
                "  Line 1: YES\n"
                "  Line 2: A wrap-up sentences. Including an answer within closing if a question has been asked.\n"
                "- The wrap-up sentence should be under first person perspective.\n"
                
                "\nHard constraints:\n"
                "- Do NOT output any lists, bullet points, numbered items, explanations, or reasoning.\n"
                "- Do NOT mention conditions (1)-(7), the decision rule, or the output rules.\n"
                "- Do NOT sounding overly formal or poetic.\n"
                "- Your output must be either:\n"
                "    - A single line: NO\n"
                "    - Or two lines: YES and a wrap-up sentence on the next line.\n"

                "\nSpecial rule:\n"
                "- If the other party asked you a question at any point, your wrap-up must begin by answering that question directly.\n"
                "- You may add a single additional sentence after the answer as a brief closing remark. Do not leave the question unanswered.\n"
                "- Example: Q: Anything special you want to bring along? A: I will bring my fishing rod. See you at the willow bend."
            )

            resp = self._invoke_timeout(self.llm.invoke, prompt_content, label=f"Status check for {sender_id}")
            if resp is None:
                return True

            full_resp = resp.content.strip()
            if full_resp.upper().startswith("YES"):
                lines = full_resp.split('\n')
                msg = lines[1].strip() if len(lines) > 1 else ""
                return msg if msg else True        
        return False

    def generate_dialogue(self, area: str, participants: list, context_str):
        if not participants:
            return
        
        agent_ids = [p['id'] for p in participants]
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
                partner_id = others[0]['id'] if others else None
                
                response_text = self.generate_agent_response(
                    agent_id=current_speaker['id'],
                    persona=current_speaker['persona'],
                    tone=current_speaker['tone'],
                    triggering_msg=last_text,
                    sender_id=sender_id,
                    partner_id=partner_id,
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
                sender_persona = current_speaker['persona']
                
                status = self.check_conversation_status(sender_id, sender_persona, dialogue_history)
                if status:
                    if isinstance(status, str):
                        wrap_up_turn = {"speaker": current_speaker['id'], "text": status}
                        dialogue_history.append(wrap_up_turn)
                        yield wrap_up_turn
                    #print(f"Conversation ended at turn {i+1}")
                    break
                if not others:
                    break
                current_speaker = random.choice(others)
            
            agent_personas = {p['id']: p['persona'] for p in participants}
            self.record_conversation(agent_ids, dialogue_history, area, max_turns, agent_personas)
        except Exception as e:
            print(f"Error during conversation: {e}\n{traceback.format_exc()}")

    def record_conversation(self, participants, dialogue, place, max_turns=None, agent_personas=None):
        if not dialogue:
            return
        
        if self.debug_mode:
            print(f"(debug) conversation log skipped")
            return
        
        log_parts = [f'{turn["speaker"]}: "{turn["text"]}"' for turn in dialogue]
        log_string = "; ".join(log_parts)

        if self.preference_manager and agent_personas:
            with ThreadPoolExecutor(max_workers=len(participants)) as executor:
                pref_tasks = []
                for i in range(len(participants)):
                    for j in range(len(participants)):
                        if i == j: continue
                        agent_a = participants[i]
                        agent_b = participants[j]
                        
                        def _update_pref(a, b, personas, log):
                            score = self.preference_manager.get_preference_score(a, b)
                            if score is None:
                                self.preference_manager.init_impression(a, personas[a], b, log)
                            else:
                                self.preference_manager.update_impression(a, personas[a], b, score, log)
                        
                        pref_tasks.append(executor.submit(_update_pref, agent_a, agent_b, agent_personas, log_string))
                
                for future in as_completed(pref_tasks):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[CONV] Preference update error: {e}")

        with self.db_lock:
            log_id = self.memory_manager.add_conversation_log(participants, log_string, place)
            
            with ThreadPoolExecutor(max_workers=len(participants)) as executor:
                futures = {executor.submit(self.summarize_conversation_and_store, p, raw_log=log_string, log_id=log_id): p for p in participants}
                for future in as_completed(futures):
                    p = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[CONV] Failed to summarize for {p}: {e}")

            print(f"Saved conversation logs and summaries for {participants}")
                
