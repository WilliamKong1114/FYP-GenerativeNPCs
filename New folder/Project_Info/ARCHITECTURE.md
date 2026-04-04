# Project Architecture — AI-Driven NPC Simulation

A multi-agent simulation where LLM-powered NPCs (Jimmy, Samson) live in a Unity world, follow daily plans, perform actions, observe their environment, and hold spontaneous conversations. Python backend communicates with Unity via TCP sockets.

---

## Directory Structure

```
New folder/
├── execute_plan.py             # Main loop: agent scheduling, action execution
├── conversation_manager.py     # Conversation triggers, dialogue gen, recording
├── agent_memory.py             # SQLite wrapper (observations, conversations, summaries)
├── manage_data.py              # ChromaDB operations (memories, skills, user_info)
├── planner.py                  # LLM daily plan generation (3-level hierarchy)
├── unity_comm.py               # TCP socket client to Unity
├── chroma_client.py            # ChromaDB persistent client factory
├── debug_server.py             # Flask dev server for testing
│
├── World_Environment/
│   ├── simulation_clock.py     # Game-time scaling (1s real = 5 sim hours)
│   ├── environment_tree.py     # World hierarchy tree (areas → objects)
│   ├── agent_state_manager.py  # Global agent state JSON (action, location)
│   ├── area_state_manager.py   # Per-area object/agent state + TCP listener
│   ├── place_db.py             # SQLite: Unity transform positions
│   ├── action_config.json      # Verb → target-area mappings
│   ├── config.json             # World tree definition
│   ├── agent_state.json        # Live agent states
│   └── areas/                  # Per-area JSON state files (e.g. Workshop.json)
│
├── Skill_Manage/
│   ├── chroma_skill_lib.py     # ChromaDB skill storage & code execution
│   └── populate_farming_skills.py
│
├── Secure/
│   └── llm_config.py           # 4 LLM instances (dialogue, skill, planner, routing)
│
└── Database/
    ├── agent_memory.db         # SQLite: conversation_logs, summaries, observation, reflection
    ├── plans.db                # SQLite: daily plans per agent
    └── places.db               # SQLite: world location positions
```

---

## Core Execution Loop (`execute_plan.py`)

### Startup

1. Load agents from `agent_state_manager` (persona, home node)
2. Connect `UnityClient` on port 5005
3. Start `AreaSystem` TCP listener on port 5006 (receives area enter/exit from Unity)
4. Init `ConversationManager`, `ThreadPoolExecutor`

### Daily Cycle

```
is_new_day() triggers:
  ├─ get_plan(agent_id)        → 3-level LLM plan → ~30 (time, action) steps
  ├─ Reset area states         → all objects empty, agent lists cleared
  └─ Move all agents home

Between 6:00–22:00 sim time (every 1 real second):
  For each agent not busy/chatting:
    submit execute_agent_action() to thread pool
    mark busy for 6s cooldown
```

### `execute_agent_action()` — one agent, one step

```
1. find_target(action, tree)     → (target_name, action_desc, area_name, obj_name)
2. client.move_to()              → send to Unity, wait for "ARRIVED:{agent_id}"
3. [Block 1] lock → snapshot area state + agents in area → release lock
4. record_observation()          → LLM generates natural-language perception → SQLite
5. [Block 2] lock → fresh read → check occupancy → claim object → release lock
6. resolve_and_execute_skill()   → query ChromaDB skills → exec Python code
7. lock → release object → get agents nearby
8. If other agents present → trigger conversation flow
9. state_manager.set_agent_state()
```

### Key In-Memory Dict: `agent_executions`

```python
{
  "agent_id": {
    "persona": str,          # Personality description
    "steps": [(time, action), ...],
    "emojis": [str, ...],
    "current_step": int,
    "is_busy_until": float,  # time.time() cooldown
    "is_chatting": bool,
    "active_task": Future    # ThreadPoolExecutor future
  }
}
```

---

## Planning System (`planner.py`)

Three-level LLM decomposition (all use `planner_llm = gpt-4o-mini`):

```
Level 1: 8–10 high-level tasks for the day   (e.g. "7:00: Morning routine")
Level 2: Decomposed to 1-hour steps
Level 3: Decomposed to 30-minute steps + emojis

Stored in: plans.db → plans table
Retrieved: get_plan(user_id) → latest plan JSON

Parsed in execute_plan.py:
  regex r'\d+\)\s+(\d+:\d+):\s+(.*)' → List[(time, action)]
```

---

## Environment System

### World Tree (`environment_tree.py`)

Hierarchy stored in `places.db`:

```
World (root)
├─ House_Samson (area)  → Bed, Table, Hearth, Storage (objects)
├─ House_Jimmy (area)   → same pattern
├─ Garden (area)
│  └─ Land (area)       → Dirt (1–12) (objects)
├─ Workshop (area)      → Table_Workshop ×3
└─ River (area)
```

**Target finding** (`find_suitable_location`):

1. Check `action_config.json` verb→target mappings
2. Find empty matching node in tree
3. LLM fallback if no match (`routing_llm = Phi-4`)

### Area State (`area_state_manager.py`)

Each area has its own JSON file (`areas/Workshop.json`):

```json
{
  "agents": ["Samson"],
  "objects": {
    "Table_Workshop": { "state": "occupied", "occupied_by": "Samson" }
  }
}
```

- `AreaStateManager` uses `threading.RLock` per area
- `AreaSystem` singleton caches managers, runs TCP listener for Unity signals
- Unity sends `[agent_id, area_name, "enter"/"exit"]` on agent movement

### Agent State (`agent_state_manager.py`)

Single JSON (`agent_state.json`):

```json
{
  "agents": {
    "Samson": {
      "action": "reading a book @ Library: Table_Library",
      //"interaction_area": "Library",
      //"interaction_object": "Table_Library",
      "persona": "...",
      "home_node": "House_Samson"
    }
  }
}
```

### Simulation Clock (`simulation_clock.py`)

```
time_scale = 300  →  1 real second = 5 simulated hours
Day runs 6:00–22:00 sim time ≈ 3.2 real seconds
API: get_sim_time(), get_sim_hour(), get_time_string(), is_new_day()
```

---

## Memory System

### SQLite (`agent_memory.db`) — `agent_memory.py`

| Table               | Purpose                                        | Key Columns                                 |
| ------------------- | ---------------------------------------------- | ------------------------------------------- |
| `conversation_logs` | Raw dialogue transcripts                       | participants (JSON), log_string, place, ts  |
| `summaries`         | LLM-generated conversation summaries           | user_id, summary, importance (1–10), log_id |
| `observation`       | LLM-generated perceptual records               | user_id, description, place, ts             |
| `reflection`        | (Reserved, same minimal schema as observation) | user_id, description                        |

`AgentMemoryManager` methods:

- `add_conversation_log(participants, log_string, place)`
- `add_observation(observer_id, obs_string, place)`
- `get_recent_observations(user_id, limit=5)`
- `get_recent_conversation_logs(user_id, limit=5)`
- `save_summary(user_id, summary, importance, log_id)`
- `_ensure_schema()` — idempotent column migration on init

### ChromaDB (`chroma_db/`) — `manage_data.py`

| Collection      | Purpose                     | Key Metadata                                |
| --------------- | --------------------------- | ------------------------------------------- |
| `memories`      | Long-term semantic memories | user_id, importance, created_at (game_hour) |
| `user_info`     | Agent persona/background    | user_id, type                               |
| `skills`        | Executable skill code       | name, code (Python string)                  |
| `conversations` | (Rarely used directly)      | user_id                                     |

**Memory retrieval scoring:**

```
score = (0.5 × recency) + (0.3 × importance) + (0.2 × relevance)
recency   = 0.99 ^ (current_game_hour − created_at)
importance = metadata["importance"] / 10
relevance  = 1 / (1 + cosine_distance)
Top 3 memories injected into conversation/planning context
```

---

## Observation System (`execute_plan.py` + `agent_memory.py`)

Triggers immediately after `move_to()` and area state snapshot, before occupancy claim:

```
Input:  area_state dict, agents_in_area list, action string, state_manager
LLM:    skill_llm (gpt-4.1-mini) — generates 1–3 natural sentences in 3rd-person
Output: e.g. "Samson steps into the workshop. The workbench is occupied by Jimmy,
              who is crafting items. The shelves are bare."
Store:  SQLite observation table (user_id, description, place, createdOn, ts)
```

---

## Conversation System (`conversation_manager.py`)

### Trigger conditions

```
CONVERSATION_COOLDOWN = 200s (real time, per pair)
PROBABILITY_TO_TALK   = 0.8
Both agents must not already be chatting (chat_lock)
```

### Dialogue generation

```
LLM: dialogue_llm = Meta-Llama-3.1-8B-Instruct
MIN_CONVERSATION_TURNS = 6
MAX_TURNS = 20 + (participants × 2)

Each turn:
  current_speaker → LLM → response text → appended to history
  Check end conditions (LLM evaluates):
    - Explicit goodbye
    - Looping / topic drift
    - 3+ distinct topics
  Switch speaker → repeat
```

### Recording

```
record_conversation():
  1. Serialize to log_string: "Agent1: text; Agent2: text; ..."
  2. INSERT INTO conversation_logs
  3. For each participant → summarize_conversation_and_store():
       LLM → 3–5 bullet summaries with importance ratings
       INSERT INTO summaries
       manage_data.add_memories() → ChromaDB memories collection
```

### Conversation Visualizer (Unity side)

```
Conversation ends → button appears in Unity
User clicks → Unity sends "request_conversation" command
Backend: handle_incoming_command() → generate full dialogue list
         update_dialogue() → send lines to Unity UI panel
User clicks through → Unity signals "conversation_finished"
Backend: conversation_finished() → unblocks execution
```

---

## Skill System (`Skill_Manage/chroma_skill_lib.py`)

```
Skills stored in ChromaDB "skills" collection:
  Document: description text
  Metadata: { "name": "TillLand", "code": "python string" }

Execution flow:
  1. query_skill(action_desc) → top 5 by cosine similarity
  2. Filter by distance < 1.0
  3. exec(skill_code, {"unity": client, "params": {...}})
  4. Call namespace["run"](unity, params)
  5. Return namespace["result"] (float duration)
  Fallback: return 3.0s if no skill matches
```

---

## Unity Communication (`unity_comm.py`)

Port 5005 — Python → Unity commands (JSON over TCP, one connection per agent):

| Method                                       | `action` field      | Purpose                                              |
| -------------------------------------------- | ------------------- | ---------------------------------------------------- |
| `move_to(target, content, desc, agent_id)`   | `"move_to"`         | Move agent; optionally wait for `"ARRIVED:{id}"`     |
| `interact(target, method, params, agent_id)` | `"interact"`        | Call Unity object method (Till, Water, change_color) |
| `set_chatting(agent_id, "start"/"stop")`     | `"set_chatting"`    | Toggle chat animation                                |
| `update_dialogue(agent_id, lines)`           | `"update_dialogue"` | Push dialogue lines to UI panel                      |
| `stop(agent_id)`                             | `"stop"`            | Halt agent animation                                 |

Port 5006 — Unity → Python area signals (TCP, `AreaSystem` listener):

```
Unity sends: [agent_id, area_name, "enter"/"exit"]
Python: updates areas/{area_name}.json agents list
```

---

## LLM Assignments (`Secure/llm_config.py`)

All models via Azure AI (`https://models.github.ai/inference`), auth from `GITHUB_TOKEN` env var:

| Instance       | Model                      | Used For                                |
| -------------- | -------------------------- | --------------------------------------- |
| `dialogue_llm` | Meta-Llama-3.1-8B-Instruct | NPC dialogue generation                 |
| `skill_llm`    | gpt-4.1-mini               | Skill code gen, observations, summaries |
| `planner_llm`  | gpt-4o-mini                | Daily plan generation                   |
| `routing_llm`  | Microsoft Phi-4            | Target location selection fallback      |

All: temperature=0.3, timeout=10s, max_retries=2

---

## Thresholds & Constants

```python
# Conversation
CONVERSATION_COOLDOWN       = 200      # real seconds between same pair
PROBABILITY_TO_TALK         = 0.8
MIN_CONVERSATION_TURNS      = 6
MAX_TURNS                   = 20 + (participants × 2)

# Agent execution
ACTION_COOLDOWN             = 6        # real seconds between steps
MAIN_LOOP_SLEEP             = 1        # real seconds
MOVE_TO_TIMEOUT             = 20       # seconds waiting for Unity ARRIVED
THREAD_POOL_MAX_WORKERS     = min(agents + 1, 20)

# Memory scoring weights
RECENCY_WEIGHT              = 0.5
IMPORTANCE_WEIGHT           = 0.3
RELEVANCE_WEIGHT            = 0.2
RECENCY_DECAY               = 0.99     # per game hour
TOP_MEMORIES_COUNT          = 3

# Time simulation
TIME_SCALE                  = 300      # sim-minutes per real-second
SIM_DAY_START               = 6        # 6:00 AM
SIM_DAY_END                 = 22       # 10:00 PM
```
