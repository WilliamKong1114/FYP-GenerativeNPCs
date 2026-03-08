# Claude Code Context — AI NPC Simulation

> Read `ARCHITECTURE.md` for full system details. This file gives the critical fast-load context.

## What This Project Is
Python backend for a multi-agent NPC simulation connected to a Unity game. LLM-powered agents (Jimmy, Samson) follow daily plans, perform actions in a shared world, observe their environment, and hold spontaneous conversations. **Do NOT explore files from scratch** — everything is documented in `ARCHITECTURE.md`.

---

## Critical File Map

| File | Role |
|------|------|
| `execute_plan.py` | Main loop — agent scheduling, `execute_agent_action()`, `record_observation()` |
| `conversation_manager.py` | Dialogue generation, recording, summarization |
| `agent_memory.py` | SQLite wrapper — `AgentMemoryManager` (observations, conv logs, summaries) |
| `manage_data.py` | ChromaDB wrapper — memories, skills, user_info |
| `planner.py` | 3-level LLM daily plan generation |
| `unity_comm.py` | TCP socket client to Unity (port 5005) |
| `World_Environment/area_state_manager.py` | Per-area JSON state + TCP listener (port 5006) |
| `World_Environment/agent_state_manager.py` | Global agent state JSON |
| `World_Environment/environment_tree.py` | World hierarchy tree (areas → objects) |
| `Secure/llm_config.py` | 4 LLM instances: dialogue_llm, skill_llm, planner_llm, routing_llm |

---

## Database Layout

**SQLite (`Database/agent_memory.db`):**
- `conversation_logs` — raw dialogue transcripts (participants JSON, log_string, place, ts)
- `summaries` — LLM-generated summaries per agent per conversation (importance 1–10)
- `observation` — LLM-generated perceptual records (added columns: place, createdOn, ts via `_ensure_schema()`)
- `reflection` — reserved, same minimal schema

**SQLite (`Database/plans.db`):** daily plans per agent
**SQLite (`Database/places.db`):** world location Unity transforms
**ChromaDB (`chroma_db/`):** collections — `memories`, `user_info`, `skills`, `conversations`

---

## Key Patterns & Conventions

- **Area state is per-file**: `World_Environment/areas/{AreaName}.json` — each area manages its own state with `threading.RLock`
- **Dual storage**: Important data (conversation summaries, memories) goes to both SQLite (raw log) AND ChromaDB (semantic search). Observations go SQLite only.
- **Thread pool**: Agents run concurrently in `ThreadPoolExecutor`; `chat_lock` prevents concurrent conversations
- **LLM model map**: dialogue → Llama-3.1-8B, skills/observations/summaries → gpt-4.1-mini, planning → gpt-4o-mini, routing → Phi-4
- **Observation trigger**: After `move_to()` + area state snapshot, BEFORE occupancy claim (split lock block in `execute_agent_action`)
- **Conversation trigger**: After action completes, if other agents present in same area

---

## Recently Completed Work

| Feature | Files Changed | Notes |
|---------|--------------|-------|
| Observation system | `agent_memory.py`, `execute_plan.py` | LLM generates 1–3 sentence 3rd-person perception log before each action; stored in SQLite `observation` table |
| Per-area state files | `area_state_manager.py` | Replaced single `agent_state.json` with individual `areas/*.json` files to avoid read/write conflicts |
| Conversation visualizer | `execute_plan.py`, Unity side | Button appears after conversation; user clicks through dialogue panel |

---

## Agent Config (from `agent_state.json`)
Agents: **Jimmy**, **Samson**
Each has: `persona` (string), `home_node` (e.g. `House_Samson`), current `action`, `interaction_area`, `interaction_object`

---

## Environment (`.env` required)
```
GITHUB_TOKEN=<token>   # Azure AI inference API key
```
