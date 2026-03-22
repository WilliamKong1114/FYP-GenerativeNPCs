import json
import os
import sqlite3
import queue
import threading
import traceback
import time
from typing import List, Sequence, Tuple
from Secure.llm_config import commitment_llm
from World_Environment.simulation_clock import SimulationClock

Step = Tuple[str, str]

commitment_queue: queue.Queue[tuple[list[str], dict, str, str]] = queue.Queue()
pending_commitment_keys: set[str] = set()
pending_lock = threading.Lock()
agent_exec_lock = threading.Lock()
pending_commitment_lock = threading.Lock()
maximum_commitment = 2
action_window = 3

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

    def get_commitments(self, agent_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT commitment_id, event_name, start_time, end_time FROM commitments WHERE invitee_id=?", (agent_id,)
        ).fetchall()

        if not rows:
            return None
        
        commitment_list = [
            f"{n[0]}: {n[1]} from {n[2]} to {n[3]}" for n in rows
        ]
        return commitment_list
    
    def remove_commitment(self, agent_id: str):
        self.conn.execute("DELETE FROM commitments WHERE invitee_id=?", (agent_id,))

    def replan_steps(self, original_steps: List[Step], original_emojis: List[str], new_steps_section: List[Step], new_emoji_section: List[str], current_step_idx: int) -> Tuple[List[Step], List[str]]:
        updated_steps = list(original_steps)
        updated_emojis = list(original_emojis)

        time_to_index = {t: i for i, (t, _) in enumerate(original_steps)}

        for i, (t, new_action) in enumerate(new_steps_section):
            idx = time_to_index.get(t)
            if idx is not None:
                updated_steps[idx] = (t, new_action)
                updated_emojis[idx] = new_emoji_section[i]

        """         
        final_steps = []        # filter out past steps
        final_emojis = []
        
        for idx, step in enumerate(updated_steps):
            if idx >= current_step_idx:
                final_steps.append(step)
                final_emojis.append(updated_emojis[idx])
        return final_steps, final_emojis"""
        return updated_steps, updated_emojis

    def check_commitment(self, dialogue_lines, agent_executions, sim_time):    
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
            - You MUST choose a start_time that is AT LEAST 2 hour later than the current time.
            - Rules:
                - start_time must NOT be earlier than current_time + 02:00
                - start_time must NOT be within the next 60 minutes
                - start_time >= current_time + 02:00
            - Example:
            - 06:00 -> earliest allowed start_time = 08:00
            - 09:30 -> earliest allowed start_time = 11:30

        5. end_time: Estimated end time. The time needs to be in HH:MM format (24h). Needs to be reasonable based on the event type and start_time.

        Constraints:
        - If no clear invitation is found, return the word None without any quotes or JSON formatting.
        - If an invitation is found, output MUST be a valid JSON object.
        - Do NOT output any lists, bullet points, numbered items, explanations, reasoning or statement.

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
            return
        
        invite = json.loads(response)
        target_id = invite["invitee"]
        
        existing_commitment = self.get_commitments(target_id)
        if existing_commitment and len(existing_commitment) >= maximum_commitment:
            print(f"[COMMITMENT] Skipping commitment check for {target_id} due to already existing commitments [{maximum_commitment}].")
            return
        
        if target_id not in agent_executions:
            return

        print(f"[COMMITMENT] Detected invitation: {invite['initiator']} -> {invite['invitee']} for {invite['event_name']} at {invite['start_time']}")
        self.initiator_commitment(agent_executions, target_id, invite)

    def initiator_commitment(self, agent_executions: dict, agent_id: str, invite_info: dict) -> bool:
        with agent_exec_lock:
            target_state = agent_executions.get(agent_id)
            if not target_state:
                return False

            pending = target_state["pending_commitments"]
            pending.append(invite_info)
        return True

    def pop_commitment(self, agent_state: dict):
        with pending_commitment_lock:
            pending = agent_state.get("pending_commitments")
            if not pending:
                return None
            return pending.pop(0)

    def assign_commitment(self, dialogue_lines, agent_executions, current_time):
        if not dialogue_lines:
            return False

        request = "\n".join(dialogue_lines)
        with pending_lock:
            if request in pending_commitment_keys:
                return False
            pending_commitment_keys.add(request)

        commitment_queue.put((list(dialogue_lines), agent_executions, request, current_time))
        print("[COMMITMENT] Queued invitation analysis.")
        return True

    def decide_commitment(self, persona: str, invite_info: dict, future_steps: List[Step], current_step_idx: int):
        event_name = invite_info["event_name"]
        invitee_id = invite_info["invitee"]
        initiator_id = invite_info["initiator"]

        existing_commitment = self.get_commitments(invitee_id)

        from preference_manager import PreferenceManager
        impression_score = PreferenceManager().get_preference_score(invitee_id, initiator_id)
        relationship_type = PreferenceManager().get_relationship_type(invitee_id, initiator_id)

        additional_prompt = ""
        if existing_commitment:
            additional_prompt = f"""
            - Here is a list of existing commitments you have in this format: ["commitment_id"]: ["event_name"] from ["start_time"] to ["end_time"]".
            - Search for any time conflicts with the new event "{event_name}" starting at {invite_info["start_time"]} and ending at {invite_info["end_time"]}.
            """
        else:
            additional_prompt = "There are no existing commitments from the CommitmentManager."

        if impression_score and impression_score <= 6.5:
            print(f"[COMMITMENT] Declined {event_name} from {initiator_id} due to low impression score ({impression_score:.1f})")
            return {"state": "DECLINE", "steps": None}

        if relationship_type and relationship_type == "Stranger":
            print(f"[COMMITMENT] Declined {event_name} from {initiator_id} due to Stranger relationship")
            return {"state": "DECLINE", "steps": None}

        current_task_time = "Unknown"
        current_task_desc = "Unknown"
        if 0 <= current_step_idx < len(future_steps):
            current_task_time, current_task_desc = future_steps[current_step_idx]
            
        prompt = f"""
            You are a scheduling agent acting on behalf of {invitee_id}.

            Context:
            - You have been invited to the event "{event_name}" starting at {invite_info["start_time"]} by {invite_info["initiator"]}.
            - Your upcoming schedule (future_steps) are: {future_steps}.
            - Current task at this index: [{current_task_time}] {current_task_desc}.
            {additional_prompt}

            - Decide whether to ACCEPT or DECLINE the invitation based on the importance score ONLY. Follows the instructions:
                1. Compare the new commitment with both `future_steps` and any `existing_commitments` for time conflicts.
                2. Evaluate importance based on:
                    - Persona: {persona} (Basic importance score 0-10).
                    - Relationship with initiator: {relationship_type}. (Variables: Family: 1.5, Friend: 1.2, Acquaintance: 0.7).
                3. Calculate and compare scores:
                    - If the new commitment has a higher importance score than the conflicting task or existing commitment, ACCEPT it.
                    - Otherwise, DECLINE it.
                Output if DECLINING (Do NOT modify any steps):
                {{
                    "state": "DECLINE",
                    "steps": null,
                    "reason": "Original [task/commitment]: [basic score] * [relationship variable] = [final result], New commitment: [basic score] * [relationship variable] = [final result]. The new commitment is less important."
                }}

            \nThe existing_commitment checker: {{additional_prompt}}\n
            
            If ACCEPTING:
            - You must adjust `future_steps` to include the event and adapt surrounding actions.
            - Identify the step whose time exactly matches {invite_info["start_time"]}.
            - The event should be ended at {invite_info["end_time"]}.
            - You may modify:
            - Up to {action_window} steps BEFORE event_start, and
            - Up to {action_window} steps AFTER event_start,
            - plus the step at event_start itself.
            - This means you can adjust at most:
            - {action_window} steps before + 1 event step + {action_window} steps after.
            - You may choose to modify fewer steps than this maximum, but NEVER more.

            Constraints on modified steps:
            - Do NOT create or remove time slots; only rewrite the content of existing steps within the allowed window.
            - Keep all times at 30-minute intervals and in correct 24-hour HH:MM format.
            - Ensure the full day still covers every 30-minute slot from 06:00 to 22:00.
            - Maintain a simple, grounded tone (not poetic or overly formal) with 15-20 words per action.
            - A specific area or object in each action (e.g., "at the herb garden", "in the weaving hut").
            - Provide transition actions that logically connect the event to the rest of the schedule.
            - Respect any existing activity descriptions and time ranges.
            For example, if the original description for 08:00-10:00 is: "Gathered herbs and fallen branches in the woods from 08:00 to 10:00.",
            then only propose tasks related to gathering herbs and fallen branches in the woods during that period.

            Output format (STRICT)
            - Always output a single JSON object with this exact structure, and nothing else.
            - For example, if the event is at 18:00 and you decide to change tasks within the +/- {action_window} window:        
            - The example output would be:
            {{
            "state": "ACCEPT",
            "steps": "15) 17:00: Action 1\n16) 17:30: Action 2\n17) 18:00: Action 3",
            "reason": Provide a brief explanation of why you accepted the commitment, with the importance scores and relationship factors of both comparing element mentioned.
            }}"""
                
        response = commitment_llm.invoke(prompt).content.strip()
        if response.startswith("```"):
            response = response.strip("`").strip("json").strip()

        decision_data = json.loads(response)
        state = str(decision_data.get("state", "DECLINE")).upper()
        steps_text = decision_data.get("steps")

        if (state != "ACCEPT"):
            return {"state": "DECLINE", "steps": None}

        if not isinstance(steps_text, str) or not steps_text.strip():
            return {"state": "DECLINE", "steps": None}

        self.set_commitment(invitee_id, initiator_id, event_name, invite_info["start_time"], invite_info["end_time"])
        print(f"[COMMITMENT] Saved {event_name} for {invitee_id} to database.")

        return {"state": "ACCEPT", "steps": steps_text}

    def build_initiator_replan(self, persona: str, invite_info: dict, future_steps: List[Step], current_step_idx: int):
        initiator_id = invite_info["initiator"]
        invitee_id = invite_info.get("invitee")
        event_name = invite_info["event_name"]

        current_task_time = "Unknown"
        current_task_desc = "Unknown"
        if 0 <= current_step_idx < len(future_steps):
            current_task_time, current_task_desc = future_steps[current_step_idx]

        prompt = f"""
            You are a scheduling agent acting on behalf of {initiator_id}.
            You are the INVITATOR, and the invitee ({invitee_id}) accepted your event.

            Context:
            - Persona: {persona}
            - Event: {event_name}
            - Event window: {invite_info["start_time"]} to {invite_info["end_time"]}
            - Your upcoming schedule (future_steps): {future_steps}
            - Current task: [{current_task_time}] {current_task_desc}

            - You must adjust `future_steps` to include the event and adapt surrounding actions.
            - Identify the step whose time exactly matches {invite_info["start_time"]}.
            - The event should be ended at {invite_info["end_time"]}.
            - You may modify:
            - Up to {action_window} steps BEFORE event_start, and
            - Up to {action_window} steps AFTER event_start,
            - plus the step at event_start itself.
            - This means you can adjust at most:
            - {action_window} steps before + 1 event step + {action_window} steps after.
            - You may choose to modify fewer steps than this maximum, but NEVER more.

            Constraints on modified steps:
            - Do NOT create or remove time slots; only rewrite the content of existing steps within the allowed window.
            - Keep all times at 30-minute intervals and in correct 24-hour HH:MM format.
            - Ensure the full day still covers every 30-minute slot from 06:00 to 22:00.
            - Maintain a simple, grounded tone (not poetic or overly formal) with 15-20 words per action.
            - A specific area or object in each action (e.g., "at the herb garden", "in the weaving hut").
            - Provide transition actions that logically connect the event to the rest of the schedule.
            - Respect any existing activity descriptions and time ranges.
            For example, if the original description for 08:00-10:00 is: "Gathered herbs and fallen branches in the woods from 08:00 to 10:00.",
            then only propose tasks related to gathering herbs and fallen branches in the woods during that period.

            Output format (STRICT)
            - Always output a single JSON object with this exact structure, and nothing else.
            - For example, if the event is at 18:00 and you decide to change tasks within the +/- {action_window} window:        
            - The example output would be:
            {{
            "state": "ACCEPT",
            "steps": "15) 17:00: Action 1\n16) 17:30: Action 2\n17) 18:00: Action 3",
            }}
        """

        response = commitment_llm.invoke(prompt).content.strip()
        if response.startswith("```"):
            response = response.strip("`").strip("json").strip()

        decision_data = json.loads(response)
        steps_text = decision_data.get("steps")
        if not isinstance(steps_text, str) or not steps_text.strip():
            return {"state": "DECLINE", "steps": None}

        return {"state": "ACCEPT", "steps": steps_text}

def _commitment_worker() -> None:
    commitment_manager = CommitmentManager()
    while True:
        dialogue_lines, agent_executions, request_key, current_time = commitment_queue.get()
        try:
            commitment_manager.check_commitment(dialogue_lines, agent_executions, current_time)
        except Exception as e:
            print(f"[COMMITMENT] Worker error: {e}\n{traceback.format_exc()}")
        finally:
            with pending_lock:
                pending_commitment_keys.discard(request_key)

threading.Thread(target=_commitment_worker, daemon=True, name="CommitmentWorker").start()

def main():
    commitment_manager = CommitmentManager()
    # --- TEST 1: replan_steps replacement and filtering ---
    original_steps = [("09:00", "Old Work"), ("09:30", "Stay Put"), ("10:00", "Eat")]
    original_emojis = ["??", "??", "??"]
    
    new_steps = [("09:30", "Meet Friend")]
    new_emoj = ["??"]
    
    updated_steps, updated_emojis = commitment_manager.replan_steps(
        original_steps, 
        original_emojis, 
        new_steps, 
        new_emoj, 
        current_step_idx=1
    )
    
    print("--- Test: replan_steps Replacement ---")
    print(f"Original: {original_steps[1]} -> {original_emojis[1]}")
    print(f"Updated:  {updated_steps[0]} -> {updated_emojis[0]}") 
    print(f"Full Result Steps:  {updated_steps}")
    print(f"Full Result Emojis: {updated_emojis}")

    # --- TEST 2: check_commitment ---
    agent_executions = {
        "id": "Warwicke",
        "Warwicke": {
            "persona": "A helpful villager",
            "pending_commitments": []
        }
    }
    dialogue = ["Jimmy: Hey Warwicke, want to meet at the tavern at 18:00?"]
    sim_time = (1, 12, 30, 0) # Day 1, 12:30

    print("\n--- Test: check_commitment ---")
    try:
        commitment_manager.check_commitment(dialogue_lines=dialogue, agent_executions=agent_executions, sim_time=sim_time)
        pending = agent_executions["Warwicke"]["pending_commitments"]
        print(f"Pending commitments for Warwicke: {pending}")
    except Exception as e:
        print(f"check_commitment failed: {e}")

    # --- TEST 3: decide_commitment ---
    if agent_executions["Warwicke"]["pending_commitments"]:
        invite = agent_executions["Warwicke"]["pending_commitments"][0]
        future_steps = [("17:30", "Work"), ("18:00", "Dinner"), ("18:30", "Sleep")]
        print("\n--- Test: decide_commitment ---")
        try:
            decision = commitment_manager.decide_commitment("A social villager", invite, future_steps, 0)
            print(f"Decision: {decision["state"]}")
            if decision["steps"]:
                print(f"New Plan Section:\n{decision["steps"]}")
        except Exception as e:
            print(f"decide_commitment failed: {e}")

if __name__ == "__main__":
    main()
