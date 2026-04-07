import json
import os
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime
from typing import Dict, List, Optional

import chromaMemory_manager
import execute_plan as runtime
from Secure.llm_config import dialogue_llm
from World_Environment.agent_state_manager import AgentStateManager
from agent_memory import AgentMemoryManager
from chroma_client import get_client
from preference_manager import PreferenceManager


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DB_PATH = os.path.join(BASE_DIR, "Database", "interview_test_memory.db")
TEST_CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db_interview_test")
TEST_PREF_DIR = os.path.join(BASE_DIR, "Preference_List", "interview_test")

INTERVIEW_USER_ID = "Traveler"
INTERVIEW_PLACE = "Interview_Testing_CLI"
LLM_TIMEOUT_SECONDS = 20


class ExistingMemoryAdapter:
	"""Read-only adapter that reuses existing project memory stores for retrieval.

	Writes are intentionally handled elsewhere with interview test-only paths.
	"""

	def __init__(self):
		self.memory = AgentMemoryManager()

	def _sqlite_fallback(self, query: str, user_id: str, limit: int = 5) -> str:
		query = (query or "").strip().lower()
		tokens = [t for t in query.split() if len(t) >= 3]

		rows = self.memory.conn.execute(
			"""
			SELECT text FROM (
				SELECT summary AS text, ts FROM summaries WHERE user_id=?
				UNION ALL
				SELECT description AS text, ts FROM observation WHERE user_id=?
				UNION ALL
				SELECT insight AS text, ts FROM reflection WHERE user_id=?
			) ORDER BY ts DESC LIMIT 30
			""",
			(user_id, user_id, user_id),
		).fetchall()

		texts = [str(r[0]).strip() for r in rows if r and r[0]]
		if not texts:
			return "No memories found."

		if tokens:
			filtered = [t for t in texts if any(tok in t.lower() for tok in tokens)]
			if filtered:
				texts = filtered

		top_memories = texts[:limit]
		return f"\nRelevant memories: {top_memories}"

	def get_memory(self, query, user_id: str, current_hours: int, partner_id: str = None):
		query_text = " ".join(query) if isinstance(query, list) else str(query)
		try:
			result = self.memory.get_memory(query_text, user_id, current_hours, partner_id)
		except Exception as e:
			print(f"[INTERVIEW] Existing vector retrieval error: {e}")
			result = ""

		if result and result != "No memories found.":
			return result
		return self._sqlite_fallback(query_text, user_id)


class InterviewStorage:
	def __init__(self, sqlite_path: str, chroma_path: str):
		self.sqlite_path = sqlite_path
		self.chroma_path = chroma_path
		self.llm = dialogue_llm
		self.db_lock = threading.Lock()

		os.makedirs(os.path.dirname(self.sqlite_path), exist_ok=True)
		os.makedirs(self.chroma_path, exist_ok=True)
		self.conn = sqlite3.connect(self.sqlite_path, isolation_level=None, check_same_thread=False)
		self._ensure_schema()

	def _ensure_schema(self):
		self.conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS conversation_logs (
				id TEXT PRIMARY KEY,
				participants TEXT,
				log_string TEXT,
				place TEXT,
				createdOn TEXT,
				ts INTEGER
			)
			"""
		)
		self.conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS summaries (
				id TEXT PRIMARY KEY,
				user_id TEXT,
				summary TEXT,
				importance REAL,
				log_id TEXT,
				ts INTEGER
			)
			"""
		)
		self.conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS observation (
				id TEXT PRIMARY KEY,
				user_id TEXT,
				description TEXT,
				place TEXT,
				createdOn TEXT,
				ts INTEGER
			)
			"""
		)
		self.conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS reflection (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				user_id TEXT,
				insight TEXT,
				importance REAL,
				cited_memories TEXT,
				ts INTEGER,
				used INTEGER DEFAULT 0
			)
			"""
		)

	def close(self):
		self.conn.close()

	def add_conversation_log(self, participants: List[str], log_string: str, place: str) -> str:
		log_id = str(uuid.uuid4())
		participants_json = json.dumps(participants)
		created_on = datetime.now().isoformat()
		self.conn.execute(
			"INSERT INTO conversation_logs(id, participants, log_string, place, createdOn, ts) VALUES (?,?,?,?,?,?)",
			(log_id, participants_json, log_string, place, created_on, int(time.time())),
		)
		return log_id

	def save_summary(self, user_id: str, summary: str, importance: int, log_id: str = None):
		summary_id = str(uuid.uuid4())
		self.conn.execute(
			"INSERT INTO summaries(id, user_id, summary, importance, log_id, ts) VALUES (?,?,?,?,?,?)",
			(summary_id, user_id, summary, importance, log_id, int(time.time())),
		)

	def _invoke_timeout(self, fn, *args, timeout: float = LLM_TIMEOUT_SECONDS, label: str = "LLM"):
		executor = ThreadPoolExecutor(max_workers=1)
		future = executor.submit(fn, *args)
		try:
			return future.result(timeout=timeout)
		except TimeoutError:
			future.cancel()
			print(f"[INTERVIEW] {label} timed out after {timeout}s.")
			return None
		except Exception as e:
			print(f"[INTERVIEW] {label} failed: {e}")
			return None
		finally:
			executor.shutdown(wait=False, cancel_futures=True)

	def summarize_conversation_and_store(self, user_id: str, raw_log: str, log_id: str, game_hour: int):
		system = {
			"role": "system",
			"content": (
				f"You are {user_id}.\n"
				"You are trying to summarize the conversation with a list of 3 to 5 items, "
				"with each item containing 10 to 15 words and including the other person's name.\n"
				"The summary should help your future self recap what happened and what matters.\n"
				"You also need to provide an importance rating (1-10).\n"
				"Output MUST be valid JSON: "
				'{"summaries": [{"description": "...", "importance": 5}]}'
			),
		}
		user_msg = {"role": "user", "content": raw_log}

		resp = self._invoke_timeout(self.llm.invoke, [system, user_msg], label=f"Summary generation for {user_id}")
		if resp is None:
			return

		content = str(getattr(resp, "content", "")).strip()
		if not content:
			return

		if content.startswith("```"):
			content = re.sub(r"^```(?:json)?", "", content).strip()
			content = re.sub(r"```$", "", content).strip()

		try:
			data = json.loads(content)
		except json.JSONDecodeError:
			match = re.search(r"\{[\s\S]*\}", content)
			if not match:
				return
			data = json.loads(match.group(0))

		summaries = data.get("summaries", [])
		if not isinstance(summaries, list):
			return

		for item in summaries:
			description = str(item.get("description", "")).strip()
			if not description:
				continue

			importance = item.get("importance", 5)
			try:
				importance = max(1, min(10, int(importance)))
			except Exception:
				importance = 5

			chromaMemory_manager.add_memories(
				[description],
				user_id=user_id,
				path=self.chroma_path,
				importance=importance,
				type="summary",
				game_hour=game_hour,
			)
			self.save_summary(user_id=user_id, summary=description, importance=importance, log_id=log_id)

	def record_conversation(self, participants: List[str], dialogue_lines: List[str], place: str, game_hour: int):
		if not dialogue_lines:
			return

		log_string = "; ".join(dialogue_lines)
		with self.db_lock:
			log_id = self.add_conversation_log(participants, log_string, place)
			for participant in participants:
				self.summarize_conversation_and_store(
					user_id=participant,
					raw_log=log_string,
					log_id=log_id,
					game_hour=game_hour,
				)


class InterviewConversationRuntime:
	def __init__(self, memory_adapter: ExistingMemoryAdapter):
		self.memory_adapter = memory_adapter
		self.llm = dialogue_llm

	def _invoke_timeout(self, fn, *args, timeout: float = LLM_TIMEOUT_SECONDS, label: str = "LLM"):
		executor = ThreadPoolExecutor(max_workers=1)
		future = executor.submit(fn, *args)
		try:
			return future.result(timeout=timeout)
		except TimeoutError:
			future.cancel()
			print(f"[INTERVIEW] {label} timed out after {timeout}s.")
			return None
		except Exception as e:
			print(f"[INTERVIEW] {label} failed: {e}")
			return None
		finally:
			executor.shutdown(wait=False, cancel_futures=True)

	def generate_agent_response(
		self,
		agent_id: str,
		persona: str,
		tone: str,
		history: List[Dict[str, str]],
	) -> str:
		if not history:
			return ""

		user_msgs = []
		for m in history:
			role = str(m.get("role", "user")).strip().lower()
			content = str(m.get("content", "")).strip()
			if not content:
				continue
			user_msgs.append({"role": role, "content": content})

		if not user_msgs:
			return ""

		#msg_contents = [msg["content"] for msg in user_msgs]
		memory_context = self.memory_adapter.get_memory(
			query=user_msgs[-1]["content"],
			user_id=agent_id,
			current_hours=int(runtime.clock.get_sim_hour()),
			partner_id=None,
		)

		system_prompt = f"""
			The year is 1200A.D. You are {agent_id}, a villager living in a small medieval settlement near a river and pasturelands, with forests not far from the village edge.
			Here is your persona for better buildup for the conversation: {persona}
			Here is your tone guideline for conversation: {tone}
			Access the memory context to make the conversation relevant to current situation: {memory_context}.

			Respond guideline (IMPORTANT):
			- Keep your responses around 20 words
			- DO NOT start every message with "Morning", "Hello", or the partner's name. Use greetings that fit your personality.
			- Adapt responses to the user's latest input.
			- When someone is proposing a commitment, consider saying something vague that doesn't commit you to anything specific.
		"""

		result = self._invoke_timeout(
			self.llm.invoke,
			[{"role": "system", "content": system_prompt}] + user_msgs,
			label="Dialogue generation",
		)
		if result is None:
			return ""

		response_content = str(getattr(result, "content", "")).strip()
		return response_content.strip('"').strip()


def choose_agent(agents_state: Dict[str, Dict]) -> Optional[str]:
	if not agents_state:
		return None

	agent_ids = sorted(agents_state.keys())
	print("\nAvailable agents:")
	for idx, agent_id in enumerate(agent_ids, start=1):
		print(f"[{idx}] {agent_id}")

	while True:
		raw = input("Select agent (number or exact ID): ").strip()
		if not raw:
			print("Please enter a value.")
			continue

		if raw.isdigit():
			index = int(raw)
			if 1 <= index <= len(agent_ids):
				return agent_ids[index - 1]
			print("Invalid number.")
			continue

		if raw in agents_state:
			return raw
		print("Unknown agent ID.")


def build_runtime_graph():
	os.makedirs(TEST_CHROMA_PATH, exist_ok=True)
	os.makedirs(TEST_PREF_DIR, exist_ok=True)

	runtime.preference_manager = PreferenceManager(base_dir=TEST_PREF_DIR)
	runtime.memory_manager = ExistingMemoryAdapter()
	return runtime.memory_manager


def run_interview():
	agents_state = AgentStateManager().get_agent_state()
	agent_id = choose_agent(agents_state)
	if not agent_id:
		print("No agents available.")
		return

	persona = agents_state.get(agent_id, {}).get("persona", "")
	tone = agents_state.get(agent_id, {}).get("tone", "")

	memory_adapter = build_runtime_graph()
	chat_runtime = InterviewConversationRuntime(memory_adapter)
	storage = InterviewStorage(TEST_DB_PATH, TEST_CHROMA_PATH)

	session_id = f"interview_{agent_id}_{uuid.uuid4().hex[:8]}"
	dialogue_lines: List[str] = []
	history: List[Dict[str, str]] = []
	turn_count = 0

	print(f"\nInterview started with {agent_id}.")
	print("Type /exit to close the conversation.")

	try:
		while True:
			user_text = input(f"{INTERVIEW_USER_ID}: ").strip()
			if not user_text:
				print("Please type a message, or /exit.")
				continue

			if user_text.lower() == "/exit":
				break

			history.append({"role": "user", "content": user_text})

			response_text = chat_runtime.generate_agent_response(
				agent_id=agent_id,
				persona=persona,
				tone=tone,
				history=history,
			)
			if not response_text:
				response_text = "I could not produce a response this turn."

			print(f"{agent_id}: {response_text}")
			history.append({"role": "assistant", "content": response_text})

			dialogue_lines.append(f'{INTERVIEW_USER_ID}: "{user_text}"')
			dialogue_lines.append(f'{agent_id}: "{response_text}"')
			turn_count += 1

		if dialogue_lines:
			game_hour = int(runtime.clock.get_sim_hour())
			storage.record_conversation(
				participants=[INTERVIEW_USER_ID, agent_id],
				dialogue_lines=dialogue_lines,
				place=INTERVIEW_PLACE,
				game_hour=game_hour,
			)
	finally:
		storage.close()

	print("\nInterview ended.")
	print(f"Session: {session_id}")
	print(f"Agent: {agent_id}")
	print(f"Turns completed: {turn_count}")
	print(f"Test SQLite: {TEST_DB_PATH}")
	print(f"Test Chroma: {TEST_CHROMA_PATH}")


def main():
	try:
		run_interview()
	except KeyboardInterrupt:
		print("\nInterview interrupted by user.")
	except Exception as e:
		print(f"\nInterview failed: {e}")


if __name__ == "__main__":
	main()
