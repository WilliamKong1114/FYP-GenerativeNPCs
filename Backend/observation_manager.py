import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

import chromaMemory_manager
from Secure.llm_config import observe_llm

OBSERVATION_WORKERS = 5
_observation_executor = ThreadPoolExecutor(max_workers=OBSERVATION_WORKERS, thread_name_prefix="ObservationWorker")

def observe_and_store(agent_id: str, area_name: str, obj_name: str, action: str, agents_nearby: list, memory_manager, game_hour: int):
	user_content = (
		f"Agent: {agent_id}\n"
		f"About to perform: {action}\n"
		f"Current location: {area_name}\n"
		f"Current object using: {obj_name}\n"
		f"Other agents nearby: {agents_nearby}\n"
	)

	system_msg = {
		"role": "system",
		"content": (
			"You are writing an observation record for a simulated village agent."
			"Write exactly 1 concise sentence (under 15 words) in third-person."
			"Describe what the agent perceives and what the agent is about to do."
			"Be neutral, precise and specific - describe the state of objects related to the agent's action."
			"Avoid sounding overly formal or poetic."
			"Output plain text only. Do not use JSON, markdown, code fences, keys, labels, or surrounding quotes."
			"Examples:\n"
			"\"Samson occupied the table in workshop to craft items using bare materials.\"\n"
			"\"The well is being used by Samson to draw some water.\""
			"\"Samson saw Wilton is using the table.\"\n"
		),
	}
	user_msg = {"role": "user", "content": user_content}

	response = observe_llm.invoke([system_msg, user_msg])
	obs_text = response.content.strip()
	if not obs_text:
		return

	chromaMemory_manager.add_memories([obs_text], user_id=agent_id, importance=3, type="observation", game_hour=game_hour)
	memory_manager.add_observation(agent_id, obs_text, area_name)

def _log_failure(future):
	try:
		future.result()
	except Exception as e:
		print(f"[OBSERVE] Observation worker failed: {e}\n{traceback.format_exc()}")

def record_observation(agent_id: str, area_name: str, obj_name: str, action: str, area_state_manager, memory_manager, clock) -> bool:
	if area_name is None:
		return False

	try:
		area_manager = area_state_manager.get_manager(area_name)
		with area_manager.lock:
			agents_nearby = list(area_manager.get_agents_in_area())
	except Exception as e:
		print(f"[OBSERVE] Failed to read area state for {agent_id} at {area_name}: {e}")
		return False

	future = _observation_executor.submit(observe_and_store, agent_id, area_name, obj_name, action, agents_nearby, memory_manager, clock.get_sim_hour())
	future.add_done_callback(_log_failure)
	return True
