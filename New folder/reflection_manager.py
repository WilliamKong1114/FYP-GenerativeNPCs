import json
import queue
import time
import threading
import traceback
import re

from agent_memory import AgentMemoryManager
import chromaMemory_manager
from chroma_client import get_client
from Secure.llm_config import reflect_llm

REFLECTION_THRESHOLD = 100      # Importance sum (since last reflection) to trigger
RECENT_RECORDS_LIMIT = 100      # Most-recent SQLite records fed to question generation
NUM_QUESTIONS = 3               # High-level questions proposed per reflection
MEMORIES_PER_QUESTION = 5       # ChromaDB results fetched per question
NUM_INSIGHTS = 5                # Insights synthesised per reflection

memory_manager = AgentMemoryManager()
chroma = get_client(path="./chroma_db")

_reflection_queue: queue.Queue[tuple[str, object, object, object]] = queue.Queue()
_pending_agents: set[str] = set()
_pending_lock = threading.Lock()

def check_reflect(agent_id: str, clock, agent_executions: dict, client=None) -> bool:
    total = memory_manager.get_importance_score(agent_id)
    if total < REFLECTION_THRESHOLD:
        return False

    with _pending_lock:
        if agent_id in _pending_agents:
            return False
        _pending_agents.add(agent_id)

    agent_execution = agent_executions.get(agent_id)

    worker_is_idle = not any(data.get("is_reflecting") for data in agent_executions.values())
    if worker_is_idle:
        agent_execution["is_reflecting"] = True

    _reflection_queue.put((agent_id, clock, agent_execution, client))
    print(f"[REFLECT] {agent_id}: importance sum={total:.0f} >= {REFLECTION_THRESHOLD}. Queued for reflection.")
    return True

def _reflection_worker() -> None:
    while True:
        agent_id, clock, agent_execution, client = _reflection_queue.get()
        #print(f"[REFLECT] Starting reflection for {agent_id}...")
        try:
            run_reflect(agent_id, clock, client)
            memory_manager.mark_records_used(agent_id)
        except Exception as e:
            print(f"[REFLECT] Worker error for {agent_id}: {e}\n{traceback.format_exc()}")
        finally:
            with _pending_lock:
                _pending_agents.discard(agent_id)
                agent_execution["is_reflecting"] = False

threading.Thread(target=_reflection_worker, daemon=True, name="ReflectionWorker").start()

def run_reflect(agent_id: str, clock, client=None) -> None:
    if client:
        client.show_dialogue("Reflecting...", agent_id, display_time=5.0)
    questions = _generate_questions(agent_id)
    if not questions:
        print(f"[REFLECT] {agent_id}: no questions generated, aborting.")
        return

    memories = _retrieve_memories(agent_id, questions, clock)
    if not memories:
        print(f"[REFLECT] {agent_id}: no memories retrieved, aborting.")
        return

    insights = _synthesize_and_store(agent_id, memories, clock)
    if not insights:
        print(f"[REFLECT] {agent_id}: no insights synthesised.")
        return

    print(f"[REFLECT] {agent_id}: stored {len(insights)} insights.")

def _generate_questions(agent_id: str) -> list[str]:
    records = memory_manager.get_mixed_records(agent_id, RECENT_RECORDS_LIMIT)
    if not records:
        return []

    numbered = "\n".join(
        f"{i + 1}. [{r['source']}] {r['text']}"
        for i, r in enumerate(records)
    )

    system_prompt = (
        "You are a psychologist helping a simulated medieval-village character reflect on their recent experiences.\n"
        f"Given the character's {len(records)} most recent conversation summaries and observations, "
        f"propose exactly {NUM_QUESTIONS} high-level, salient questions that can be answered from these records and would best reveal the character's current situation, relationships, goals, or state of mind.\n"
        f"Output ONLY valid JSON: "
        f'{{"questions": ["question 1", "question 2", "question 3"]}}'
    )

    try:
        resp = reflect_llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Records for {agent_id}:\n{numbered}"},
        ])
        data = json.loads(resp.content)
        questions = data.get("questions")
        #print(f"[REFLECT] {agent_id} reflection questions: {questions}")
        return questions[:NUM_QUESTIONS]
    except Exception as e:
        print(f"[REFLECT] Question generation failed for {agent_id}: {e}")
        return []

def _retrieve_memories(agent_id: str, questions: list[str], clock=None) -> list[dict]:
    col = chroma.get_or_create_collection("memories")
    current_hours = clock.get_sim_hour() if clock else 0
    scored: dict[str, tuple[float, str]] = {}

    for question in questions:
        try:
            results = col.query(
                query_texts=[question],
                n_results=MEMORIES_PER_QUESTION,
                where={"user_id": agent_id},
            )
            ids = results.get("ids", [[]])[0]
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            for doc_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
                if not doc:
                    continue

                relevance  = 1.0 / (1.0 + dist)
                importance = meta.get("importance", 3) / 10.0
                last_accessed = meta.get("modified_on", 0)
                delta_t = max(0, current_hours - last_accessed)
                recency = pow(0.99, delta_t)

                final_score = (0.5 * recency) + (0.3 * importance) + (0.2 * relevance)

                if doc not in scored or final_score > scored[doc][0]:
                    scored[doc] = (final_score, doc_id)

        except Exception as e:
            print(f"[REFLECT] Memory retrieval failed for '{question}': {e}")

    return [
        {"text": doc, "id": chroma_id}
        for doc, (_, chroma_id) in sorted(scored.items(), key=lambda x: x[1][0], reverse=True)
    ]

def _synthesize_and_store(agent_id: str, memories: list[dict], clock) -> list[dict]:
    if not memories:
        return []

    text = [m["text"] for m in memories]
    text_numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(text))

    system_prompt = (
        f"You are helping a person named ({agent_id}) to reflect deeply on their recent experiences.\n"
        f"Given {len(memories)} numbered memory statements, produce exactly {NUM_INSIGHTS} high-level insights the character can infer about themselves, their relationships, or their world.\n\n"
        "Format each insight with 1-based citation numbers referencing the source statements:\n"
        'Example: "Samson values solitary craftsmanship over social interaction (because of 2, 5, 7)"\n'
        "Output ONLY valid JSON:\n"
        '{"insights": [{"insight": "...", "citations": [2, 5, 7]}, ...]}'
    )

    try:
        resp = reflect_llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": f"Memory statements for {agent_id}:\n{text_numbered}"},
        ])
        data = json.loads(resp.content)
        insights = data.get("insights", [])
    except Exception as e:
        print(f"[REFLECT] Insight synthesis failed for {agent_id}: {e}")
        return []

    game_hour = clock.get_sim_hour()

    for item in insights:
        raw_insight = item.get("insight", "")
        insight_text = re.sub(r'\s*[\(\[].*?\d+.*?[\)\]]$', '', raw_insight).strip()
        citations = item.get("citations", [])
        if not insight_text:
            print(f"[REFLECT] Empty insight for {agent_id}.")
            continue

        cited_ids = []
        for c in citations:
            try:
                idx = int(c) - 1
                if 0 <= idx < len(memories):
                    cited_ids.append(memories[idx]["id"])
            except (ValueError, TypeError):
                continue

        memory_manager.save_reflection(user_id=agent_id, insight=insight_text, importance=9, cited_memories=cited_ids)
        chromaMemory_manager.add_memories([insight_text], user_id=agent_id, importance=9, type="reflection", game_hour=game_hour)
        #print(f"[REFLECT] [{agent_id}] {insight_text}")

    return insights
