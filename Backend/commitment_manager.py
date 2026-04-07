import json
import os
import sqlite3
import queue
import threading
import traceback
import time
from typing import List, Sequence, Tuple
from Secure.llm_config import commitment_llm
from planner import get_plan, modify_plan, parse_plan
from concurrent.futures import ThreadPoolExecutor, TimeoutError
Step = Tuple[str, str]

commitment_queue: queue.Queue[tuple[list[str], dict, str, str]] = queue.Queue()
_commitment_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="CommitmentWorker")
_commitment_thread = None
MAXIMUM_COMMITMENTS = 2
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "Database", "agent_memory.db")

class CommitmentManager:
    def __init__(self, db_path: str = DB_PATH):
        self.conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)

    def set_commitment(self, invitee_id: str, initiator_id: str, event_name: str, start_time: str, end_time: str):
        ts = int(time.time())
        self.conn.execute("""
            INSERT INTO commitments (invitee_id, initiator_id, event_name, start_time, end_time, ts)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (invitee_id, initiator_id, event_name, start_time, end_time, ts))
        print(f"[COMMITMENT] Saved {event_name} for {invitee_id} to database.")

    def get_commitments(self, agent_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT commitment_id, event_name, start_time, end_time FROM commitments WHERE invitee_id=?", (agent_id,)
        ).fetchall()

        if not rows:
            return []
        
        commitment_list = [
            f"{n[0]}: {n[1]} from {n[2]} to {n[3]}" for n in rows
        ]
        return commitment_list
    
    def remove_commitment(self, agent_id: str):
        self.conn.execute("DELETE FROM commitments WHERE invitee_id=?", (agent_id,))

    def pop_commitment(self, agent_state: dict):
        pending = agent_state.get("pending_commitments")
        if not pending:
            return None
        return pending.pop(0)

    def pending_steps(self, steps: List[Step], start_time: str, end_time: str) -> List[Step]:
        try:
            def round_to_30(time_str: str) -> str:
                h, m = map(int, time_str.split(':'))
                if m < 15: m = 0
                elif m < 45: m = 30
                else:
                    m = 0
                    h = (h + 1) % 24
                return f"{h:02d}:{m:02d}"

            rounded_start = round_to_30(start_time)
            rounded_end = round_to_30(end_time)

            window_steps = [
                (t, desc) for t, desc in steps
                if rounded_start <= t <= rounded_end
            ]    
            return window_steps
        
        except Exception as e:
            print(f"[COMMITMENT] Error in pending_steps: {e}\n{traceback.format_exc()}")
            return []
    
    def assign_commitment(self, dialogue_lines, agent_executions, current_time):    #Queue commitment check when a conversation happens
        if not dialogue_lines:
            return False

        request = "\n".join(dialogue_lines)
        commitment_queue.put((list(dialogue_lines), agent_executions, request, current_time))
        print("[COMMITMENT] Queued invitation analysis.")
        return True
    
    def check_commitment(self, dialogue_lines, agent_executions, sim_time):    #identify invitation within conversation
        dialogue_text = "\n".join(dialogue_lines)

        prompt = f"""
        Analyze the following dialogue for any invitation or commitment to a future event.
        Dialogue: {dialogue_text}

        If an invitation is found, extract:
        1. initiator: The agent name who is inviting.
        2. target: The agent name being invited.
        3. event_name: What the event is (e.g., "Meet at tavern", "Go fishing").
        4. start_time: The time needs to be in HH:MM format (24h).
            - This is the current time: {sim_time}. 
            - You MUST choose a start_time that is AT LEAST 3 hour later than the current time.
            - Rules:
                - start_time must NOT be earlier than current_time + 03:00
                - start_time must NOT be within the next 60 minutes
                - start_time >= current_time + 03:00
            - Example:
            - 06:00 -> earliest allowed start_time = 09:00
            - 09:30 -> earliest allowed start_time = 12:30

        5. end_time: Estimated end time. The time needs to be in HH:MM format (24h). The the time duration MUST NOT exceed 3 hours.

        Constraints:
        - If no clear invitation is found, return the word None without any quotes or JSON formatting.
        - If an invitation is found, output MUST be a valid JSON object.
        - Do NOT output any lists, bullet points, numbered items, explanations, reasoning or statement.
        - The initiator and target must be valid agent names.
        - Ensure the start_time and end_time fall within the 30-minute slots (06:00, 06:30, 07:00, ..., 21:30, 22:00).

        JSON Structure if invitation is found:
        {{
            "initiator": "...",
            "invitee": "...",
            "event_name": "...",
            "start_time": "HH:MM",
            "end_time": "HH:MM"
        }}

        Return None if invitation is not found
        """

        response = commitment_llm.invoke(prompt).content.strip()

        if response.startswith("```"):
            response = response.strip("`").strip("json").strip()

        if response.lower() == "none":
            print(f"[COMMITMENT] No invitation detected in the dialogue.")
            return
        
        invite_info = json.loads(response)
        target_id = invite_info.get("invitee")
        inviter_id = invite_info.get("initiator")
        if not target_id or not inviter_id  or target_id not in agent_executions or inviter_id not in agent_executions:
            print(f"[COMMITMENT] Invalid invitation format.")
            return

        existing_commitment = self.get_commitments(target_id)
        if existing_commitment and len(existing_commitment) >= MAXIMUM_COMMITMENTS:
            print(f"[COMMITMENT] Skipping commitment check for {target_id} due to already existing commitments [{MAXIMUM_COMMITMENTS}].")
            return
        
        print(f"[COMMITMENT] Detected invitation: {invite_info['initiator']} -> {invite_info['invitee']} for {invite_info['event_name']} at {invite_info['start_time']}")
        #self.initiator_commitment(agent_executions, target_id, invite)
        self.decide_commitment_invitee(agent_executions, invite_info)

    def decide_commitment_invitee(self, agent_executions: dict, invite_info: dict):     #for invitee to decide whether accept the invitation, and if accept, what steps to replan within the event window
        event_name = invite_info.get("event_name")
        invitee_id = invite_info.get("invitee")
        initiator_id = invite_info.get("initiator")
        start_time = invite_info.get("start_time")
        end_time = invite_info.get("end_time")
        persona = agent_executions[invitee_id].get("persona")
        steps = agent_executions[invitee_id].get("steps")

        from preference_manager import PreferenceManager
        impression_score = PreferenceManager().get_preference_score(invitee_id, initiator_id)
        relationship_type = PreferenceManager().get_relationship_type(invitee_id, initiator_id)
        
        existing_commitment = self.get_commitments(invitee_id)
        additional_prompt = ""
        if existing_commitment:
            additional_prompt = f"""
            - Here is a list of existing commitments you have in this format: ["commitment_id"]: ["event_name"] from ["start_time"] to ["end_time"]".
            - Search for any time conflicts with the new event "{event_name}" starting at {start_time} and ending at {end_time}.
            """
        else:
            additional_prompt = "There are no existing commitments from the CommitmentManager."

        if impression_score and impression_score <= 6.5:
            print(f"[COMMITMENT] Declined {event_name} from {initiator_id} due to low impression score ({impression_score:.1f})")
            return {"state": "DECLINE", "steps": None}

        if relationship_type and relationship_type == "Stranger":
            print(f"[COMMITMENT] Declined {event_name} from {initiator_id} due to Stranger relationship")
            return {"state": "DECLINE", "steps": None}

        window_steps = self.pending_steps(steps, start_time, end_time)

        prompt = f"""
            You are a scheduling agent acting on behalf of {invitee_id}.

            Context:
            - Event: {event_name}
            - Event start time: {start_time}
            - Event end time: {end_time}
            - current steps: {window_steps}.

            - Decide whether to ACCEPT or DECLINE the invitation based on the importance score ONLY. Follows the instructions:
                1. Compare the new commitment with both `current_steps` and any `existing_commitments` for time conflicts.
                2. Evaluate importance based on:
                    - Persona: {persona} (Basic importance score 0-10).
                    - Relationship with initiator: {relationship_type}. (Variables: Family: 1.5, Friend: 1.2, Acquaintance: 0.7).
                3. Calculate and compare scores. If the new commitment has a higher importance score than the conflicting task or existing commitment, ACCEPT it. Otherwise, DECLINE it.
                Output if DECLINING (Do NOT modify any future steps):
                {{
                    "state": "DECLINE",
                    "steps": null,
                    "reason": "current steps [task/commitment]: [basic score] * [relationship variable] = [final result], New commitment: [basic score] * [relationship variable] = [final result]. The new commitment is less important."
                }}

            \nThe existing_commitment checker: {additional_prompt}\n
            
            If ACCEPTING:
            - Replace ALL steps within the window steps.
            - Transitions should be appeared at the starting and ending time slot of the modified window, and they must logically connect the event to the rest of the schedule.

            Constraints on modified steps:
            - Do NOT create or remove time slots; only rewrite the content of existing steps within the allowed window.
            - Only rewrite the content of the steps within the selected inclusive window.
            - All times must remain in 30-minute intervals in correct 24-hour HH:MM format.
            - Maintain a simple, grounded tone (not poetic or overly formal) with 15-20 words per action.
            - A specific area or object in each action (e.g., "at the herb garden", "in the weaving hut").
            - Provide transition actions that logically connect the event to the rest of the schedule.

            Output format (STRICT)
            - Output a single JSON object with the exact structure ONLY.
            - Do NOT output any lists, bullet points, numbered items, explanations, reasoning or statement for the step section.
            - For example, if the event starts at 18:00 and ends at 19:00. The example output would be:
            {{
            "state": "ACCEPT",
            "steps": "15) 18:00: Action 1\n16) 18:30: Action 2\n17) 19:00: Action 3",
            "reason": Provide a brief explanation of why you accepted the commitment, with the importance scores and relationship factors of both comparing element mentioned.
            }}"""
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            future = executor.submit(commitment_llm.invoke, prompt)
            try:
                response = future.result(timeout=20).content.strip()
            except TimeoutError:
                print(f"[COMMITMENT] LLM response timed out for {invitee_id} on event {event_name}. Defaulting to DECLINE.")
                return {"state": "DECLINE", "steps": None, "reason": "LLM response timed out."}

        if response.startswith("```"):
            response = response.strip("`").strip("json").strip()

        decision_data = json.loads(response, strict=False)
        state = str(decision_data.get("state", "DECLINE")).upper()
        new_steps = decision_data.get("steps")

        if (state != "ACCEPT"):
            print(f"[COMMITMENT] {invitee_id} declined the invitation for {event_name}. Reason: {decision_data.get('reason', 'No reason provided')}")
            return {"state": "DECLINE", "steps": None}

        if not isinstance(new_steps, str) or not new_steps.strip():
            print(f"[COMMITMENT] Invalid or empty steps provided by LLM for {invitee_id} on event {event_name}. Defaulting to DECLINE.")
            return {"state": "DECLINE", "steps": None}

        self.set_commitment(invitee_id, initiator_id, event_name, start_time, end_time)

        initiator_persona = agent_executions[initiator_id].get("persona")
        initiator_steps = agent_executions[initiator_id].get("steps")
        self.tasks_replan(invitee_id, new_steps, steps)
        self.build_commitment_initiator(initiator_persona, invite_info, initiator_steps, new_steps)

    def build_commitment_initiator(self, persona: str, invite_info: dict, steps: List[Step], new_steps: str):    #after the invitee accepts the commitment, the initiator also needs to replan their schedule to fit the event in.
        initiator_id = invite_info["initiator"]
        #invitee_id = invite_info.get("invitee")
        event_name = invite_info["event_name"]
        start_time = invite_info.get("start_time")
        end_time = invite_info.get("end_time")

        window_steps = self.pending_steps(steps, start_time, end_time)

        prompt = f"""
            You are a scheduling agent acting on behalf of {initiator_id}.
            You are the INVITATOR, and the invitee accepted your event.

            Context:
            - Persona: {persona}
            - Event: {event_name}
            - Event window: {start_time} to {end_time}
            - The tasks to be replaced: {window_steps}.
            - The new steps provided by the invitee: {new_steps}.

            - Replace ALL steps within the window steps.
            - Referening the new steps provided by the invitee to generate context_similar steps.
            - Transitions should be appeared at the starting and ending time slot of the modified window, and they must logically connect the event to the rest of the schedule.

            Constraints on modified steps:
            - Do NOT create or remove time slots; only rewrite the content of existing steps within the allowed window.
            - Only rewrite the content of the steps within the selected inclusive window.
            - All times must remain in 30-minute intervals in correct 24-hour HH:MM format.
            - Maintain a simple, grounded tone (not poetic or overly formal) with 15-20 words per action.
            - A specific area or object in each action (e.g., "at the herb garden", "in the weaving hut").
            - Provide transition actions that logically connect the event to the rest of the schedule.

            Output format (STRICT)
            - Output a single JSON object with the exact structure ONLY.
            - Do NOT output any lists, bullet points, numbered items, explanations, reasoning or statement.
            - For example, if the event starts at 18:00 and ends at 19:00. The example output would be:
            {{"steps": "15) 18:00: Action 1\n16) 18:30: Action 2\n17) 19:00: Action 3"}}
        """

        response = commitment_llm.invoke(prompt).content.strip()
        if response.startswith("```"):
            response = response.strip("`").strip("json").strip()

        try:
            decision_data = json.loads(response, strict=False)
        except json.JSONDecodeError as e:
            print(f"[COMMITMENT] Failed to parse initiator JSON: {e}")
            return

        new_step = decision_data.get("steps")
        if not isinstance(new_step, str) or not new_step.strip():
            return

        self.tasks_replan(initiator_id, new_step, steps)

    def tasks_replan(self, agent_id: str, new_steps: str, steps: List[Step]) -> bool:
        new_steps_section = parse_plan(new_steps)
        if not new_steps_section:
            print(f"[REPLAN] No valid replacement steps parsed for {agent_id}.")
            return False

        new_steps_map = {time_str: action for time_str, action in new_steps_section}
        updated_full_steps = []
        for time_str, action in steps:
            if time_str in new_steps_map:
                updated_full_steps.append((time_str, new_steps_map[time_str]))
            else:
                updated_full_steps.append((time_str, action))

        new_desc = "\n".join([
            f"{i+1}) {time_str}: {action}" 
            for i, (time_str, action) in enumerate(updated_full_steps)
        ])

        _, original_emojis = get_plan(agent_id)
        if not isinstance(original_emojis, list):
            original_emojis = []

        success = modify_plan(agent_id, description=new_desc, new_emojis=original_emojis)
        
        if success:
            print(f"[REPLAN] Successfully updated plan for {agent_id} with new commitment.")
            return True

        print(f"[REPLAN] Failed to update plan for {agent_id}.")
        return False
    
def _commitment_worker():
    commitment_manager = CommitmentManager()
    while True:
        try:
            payload = commitment_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        dialogue_lines, agent_executions, request_key, current_time = payload

        try:
            future = _commitment_executor.submit(
                commitment_manager.check_commitment,
                dialogue_lines,
                agent_executions,
                current_time
            )
            future.result(timeout=30)
            #commitment_manager.check_commitment(dialogue_lines, agent_executions, current_time)
        except Exception as e:
            print(f"[COMMITMENT] Worker error: {e}\n{traceback.format_exc()}")

_commitment_thread = threading.Thread(target=_commitment_worker, daemon=True, name="CommitmentWorker")
_commitment_thread.start()

def main():
    commitment_manager = CommitmentManager()
    
    # --- TEST 1: tasks_replan replacement ---
    print("--- Test: tasks_replan Replacement ---")
    agent_id = "Warwicke"
    steps = [("09:00", "Old Work"), ("09:30", "Stay Put"), ("10:00", "Eat")]
    new_steps = "1) 09:30: Meet Friend at the Plaza\n"
    
    data = {} 
    
    try:
        success = commitment_manager.tasks_replan(
            agent_id=agent_id,
            new_steps=new_steps,
            steps=steps
        )
        print(f"Replan success: {success}")
    except Exception as e:
        print(f"tasks_replan failed: {e}")

    # --- TEST 2: check_commitment ---
    print("\n--- Test: check_commitment ---")
    agent_executions = {
        "Warwicke": {
            "persona": "A helpful villager who loves social gatherings",
            "steps": [("17:30", "Prepare dinner"), ("18:00", "Eat alone"), ("18:30", "Read book"), ("19:00", "Read book"), ("19:30", "Read book"), ("20:00", "Read book")]
        },
        "Jimmy": {
            "persona": "A friendly neighbor",
            "steps": [("17:30", "Walk dog"), ("18:00", "Eat alone"), ("18:30", "Walk dog"), ("19:00", "Walk dog"), ("19:30", "Walk dog"), ("20:00", "Walk dog")]
        }
    }
    dialogue = ["Jimmy: Hey Warwicke, want to meet at the tavern at 18:00?"]
    sim_time = "12:00"

    try:
        commitment_manager.check_commitment(dialogue_lines=dialogue, agent_executions=agent_executions, sim_time=sim_time)
    except Exception as e:
        print(f"check_commitment failed: {e}")

if __name__ == "__main__":
    main()
